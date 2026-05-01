import discord
from discord import app_commands
from discord.ui import Modal, TextInput, View, Button
import aiohttp
import asyncio
import os
import time
import json
from datetime import datetime
from dotenv import load_dotenv

# Data persistence file paths
DATA_DIR = "data"
STATS_FILE = os.path.join(DATA_DIR, "tester_stats.json")
COOLDOWNS_FILE = os.path.join(DATA_DIR, "user_cooldowns.json")
RANKS_FILE = os.path.join(DATA_DIR, "user_ranks.json")
VERIFIED_FILE = os.path.join(DATA_DIR, "verified_users.json")
LAST_SESSION_FILE = os.path.join(DATA_DIR, "last_testing_session.json")

# Load environment variables from .env file
load_dotenv()

# ==================== CONFIGURATION ====================
# Set these to your actual channel/role IDs (right-click → Copy ID)
# Leave as None to use channel name matching instead

# Channel IDs
NA_WAITLIST_CHANNEL_ID = 1499251438260588675
EU_WAITLIST_CHANNEL_ID = 1497774564959326349
AS_WAITLIST_CHANNEL_ID = 1497774571238068324
RESULTS_CHANNEL_ID = 1497774543350009936
BOT_COMMANDS_CHANNEL_ID = 1498027031513006191
REQUEST_TEST_CHANNEL_ID = 1497774516892336159     # Channel for the main waitlist form (e.g., #request-test)
LOG_CHANNEL_ID = 1497774455588651179                              # Channel for bot logs (set to enable logging)
LEADERBOARD_CHANNEL_ID = 1499214454405992609                      # Channel for testing leaderboards (set to enable)

# Store message IDs for updating the queue display
waitlist_messages = {"na": None, "eu": None, "as": None}

# Role IDs
TESTER_ROLE_ID = 1497772488170537031
HT3_PLUS_ROLE_ID = None            # Role for high tier auto-ticket
BOOSTER_ROLE_ID = None             # Role for reduced cooldown (1 day instead of 4)
RESTRICTED_ROLE_ID = None          # Role for restricted users (cannot enter waitlist)
BLACKLISTED_ROLE_ID = None         # Role for blacklisted users (cannot enter waitlist)
NA_WAITLIST_ROLE_ID = 1497772227708452935         # ID for @NA Waitlist role
EU_WAITLIST_ROLE_ID = 1497772232741617786         # ID for @EU Waitlist role
AS_WAITLIST_ROLE_ID = 1497772222855647252         # ID for @AS Waitlist role

# Cooldown settings (in seconds)
NORMAL_COOLDOWN = 4 * 24 * 60 * 60      # 4 days
BOOSTER_COOLDOWN = 1 * 24 * 60 * 60     # 1 day

# Store last test completion timestamps {user_id: timestamp}
user_cooldowns = {}

# Store last testing session timestamp per region {region: datetime}
last_testing_session = {"na": None, "eu": None, "as": None}

# Store tester statistics for leaderboards
# {tester_id: {"all_time": count, "monthly": {("year", "month"): count}}}
tester_stats = {}
current_leaderboard_month = None  # Track current month for auto-reset
leaderboard_message_ids = {"all_time": None, "monthly": None}  # Store message IDs for updates

# =======================================================

# Store verified users {user_id: {"ign": ign, "uuid": uuid}}
verified_users = {}
# Store waitlist [{"user_id": id, "ign": ign, "region": region}]
waitlist = []
# Store active testers per region {"na": [user_id, ...], "eu": [...], "as": [...]}
active_testers = {"na": set(), "eu": set(), "as": set()}
# Store user ranks {user_id: "ht3", etc.}
user_ranks = {}
# Store active testing sessions {channel_id: {"tester_id": id, "user_id": id, "ign": ign, "region": region, "skin_url": url}}
active_sessions = {}
# Queue size limit
QUEUE_SIZE_LIMIT = 10


async def log_event(guild, title, description, color=discord.Color.blue(), fields=None):
    """Send a log embed to the configured log channel"""
    if not LOG_CHANNEL_ID:
        return
    
    try:
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            return
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now()
        )
        
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to send log: {e}")


def save_data():
    """Save all data to JSON files"""
    try:
        # Create data directory if it doesn't exist
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        
        # Save tester stats (convert keys to strings for JSON)
        stats_to_save = {}
        for tester_id, stats in tester_stats.items():
            monthly_str_keys = {}
            for (year, month), count in stats["monthly"].items():
                monthly_str_keys[f"{year}-{month}"] = count
            stats_to_save[str(tester_id)] = {
                "all_time": stats["all_time"],
                "monthly": monthly_str_keys
            }
        with open(STATS_FILE, 'w') as f:
            json.dump(stats_to_save, f, indent=2)
        
        # Save cooldowns
        with open(COOLDOWNS_FILE, 'w') as f:
            json.dump(user_cooldowns, f, indent=2)
        
        # Save ranks
        with open(RANKS_FILE, 'w') as f:
            json.dump(user_ranks, f, indent=2)
        
        # Save verified users
        with open(VERIFIED_FILE, 'w') as f:
            json.dump(verified_users, f, indent=2)
        
        # Save last testing session (convert datetime to ISO format)
        session_to_save = {}
        for region, timestamp in last_testing_session.items():
            if timestamp:
                session_to_save[region] = timestamp.isoformat()
            else:
                session_to_save[region] = None
        with open(LAST_SESSION_FILE, 'w') as f:
            json.dump(session_to_save, f, indent=2)
        
        print("✅ Data saved successfully")
    except Exception as e:
        print(f"❌ Failed to save data: {e}")


def load_data():
    """Load all data from JSON files"""
    global tester_stats, user_cooldowns, user_ranks, verified_users, last_testing_session
    
    try:
        # Load tester stats
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                stats_data = json.load(f)
                for tester_id_str, stats in stats_data.items():
                    monthly_dict = {}
                    for month_key, count in stats["monthly"].items():
                        year, month = map(int, month_key.split('-'))
                        monthly_dict[(year, month)] = count
                    tester_stats[int(tester_id_str)] = {
                        "all_time": stats["all_time"],
                        "monthly": monthly_dict
                    }
            print(f"✅ Loaded {len(tester_stats)} tester stats")
        
        # Load cooldowns
        if os.path.exists(COOLDOWNS_FILE):
            with open(COOLDOWNS_FILE, 'r') as f:
                user_cooldowns.update(json.load(f))
            print(f"✅ Loaded {len(user_cooldowns)} cooldowns")
        
        # Load ranks
        if os.path.exists(RANKS_FILE):
            with open(RANKS_FILE, 'r') as f:
                user_ranks.update(json.load(f))
            print(f"✅ Loaded {len(user_ranks)} ranks")
        
        # Load verified users
        if os.path.exists(VERIFIED_FILE):
            with open(VERIFIED_FILE, 'r') as f:
                verified_users.update(json.load(f))
            print(f"✅ Loaded {len(verified_users)} verified users")
        
        # Load last testing session
        if os.path.exists(LAST_SESSION_FILE):
            with open(LAST_SESSION_FILE, 'r') as f:
                session_data = json.load(f)
                for region, timestamp_str in session_data.items():
                    if timestamp_str:
                        last_testing_session[region] = datetime.fromisoformat(timestamp_str)
                    else:
                        last_testing_session[region] = None
            print(f"✅ Loaded last testing session data")
        
        print("✅ All data loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load data: {e}")


async def update_leaderboard(guild):
    """Update the testing leaderboard display"""
    global current_leaderboard_month, leaderboard_message_ids
    
    if not LEADERBOARD_CHANNEL_ID:
        return
    
    try:
        channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            return
        
        now = datetime.now()
        current_month_key = (now.year, now.month)
        month_name = now.strftime("%B %Y")
        
        # Check if month changed - reset monthly stats
        if current_leaderboard_month != current_month_key:
            current_leaderboard_month = current_month_key
            # Monthly stats auto-reset because we use new month key
        
        # Get all-time top 10
        all_time_leaderboard = sorted(
            [(tester_id, stats["all_time"]) for tester_id, stats in tester_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Get monthly top 10
        monthly_leaderboard = sorted(
            [(tester_id, stats["monthly"].get(current_month_key, 0)) 
             for tester_id, stats in tester_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Calculate total tests for monthly
        total_monthly_tests = sum(count for _, count in monthly_leaderboard)

        # Build all-time embed
        all_time_text = ""
        if all_time_leaderboard:
            for i, (tester_id, count) in enumerate(all_time_leaderboard, 1):
                member = guild.get_member(tester_id)
                name = member.mention if member else f"<@{tester_id}>"
                all_time_text += f"**{i}.** {name} — **{count}** tests\n"
        else:
            all_time_text = "No tests completed yet!"

        all_time_embed = discord.Embed(
            title="🏆 All-Time Testing Leaderboard",
            description=all_time_text,
            color=discord.Color.gold(),
            timestamp=now
        )
        
        # Build monthly embed
        monthly_text = ""
        if monthly_leaderboard and monthly_leaderboard[0][1] > 0:
            for i, (tester_id, count) in enumerate(monthly_leaderboard, 1):
                if count == 0:
                    break
                member = guild.get_member(tester_id)
                name = member.mention if member else f"<@{tester_id}>"
                monthly_text += f"**{i}.** {name} — **{count}** tests\n"
        else:
            monthly_text = f"No tests for {month_name} yet!"

        monthly_embed = discord.Embed(
            title=f"🥇 {now.strftime('%B')} Testing Leaderboard",
            description=monthly_text,
            color=discord.Color.blue(),
            timestamp=now
        )
        
        # Add total count footer to monthly
        if total_monthly_tests > 0:
            monthly_embed.add_field(
                name="\u200b",
                value=f"**Total Tests this Month: {total_monthly_tests}**",
                inline=False
            )
        
        # Send or edit messages
        if leaderboard_message_ids["all_time"]:
            try:
                message = await channel.fetch_message(leaderboard_message_ids["all_time"])
                await message.edit(embed=all_time_embed)
            except:
                message = await channel.send(embed=all_time_embed)
                leaderboard_message_ids["all_time"] = message.id
        else:
            message = await channel.send(embed=all_time_embed)
            leaderboard_message_ids["all_time"] = message.id
        
        if leaderboard_message_ids["monthly"]:
            try:
                message = await channel.fetch_message(leaderboard_message_ids["monthly"])
                await message.edit(embed=monthly_embed)
            except:
                message = await channel.send(embed=monthly_embed)
                leaderboard_message_ids["monthly"] = message.id
        else:
            message = await channel.send(embed=monthly_embed)
            leaderboard_message_ids["monthly"] = message.id
            
    except Exception as e:
        print(f"Failed to update leaderboard: {e}")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


class QueueUpdateView(View):
    def __init__(self, region):
        super().__init__(timeout=None)
        self.region = region

    @discord.ui.button(
        label="Join Queue",
        style=discord.ButtonStyle.success,
        custom_id="join_queue_button"
    )
    async def join_button(self, interaction: discord.Interaction, button: Button):
        # Check if user has restricted or blacklisted role
        restricted_reason = None
        if RESTRICTED_ROLE_ID:
            restricted_role = interaction.guild.get_role(RESTRICTED_ROLE_ID)
            if restricted_role and restricted_role in interaction.user.roles:
                restricted_reason = "restricted"
        if BLACKLISTED_ROLE_ID and not restricted_reason:
            blacklisted_role = interaction.guild.get_role(BLACKLISTED_ROLE_ID)
            if blacklisted_role and blacklisted_role in interaction.user.roles:
                restricted_reason = "blacklisted"
        
        if restricted_reason:
            await interaction.response.send_message(
                f"**You are {restricted_reason} from entering the waitlist.**\n"
                "If you believe this is an error, please contact an administrator.",
                ephemeral=True
            )

            # Log restricted/blacklisted attempt
            await log_event(
                interaction.guild,
                f"🚫 {restricted_reason.title()} User Attempt",
                f"{interaction.user.mention} attempted to join the waitlist but is {restricted_reason}",
                discord.Color.red(),
                [
                    ("User", interaction.user.mention, True),
                    ("User ID", str(interaction.user.id), True),
                    ("Status", restricted_reason.title(), True),
                    ("Attempted Via", "Join Queue Button", False)
                ]
            )
            return

        # Check if already in ANY waitlist
        for entry in waitlist:
            if entry["user_id"] == interaction.user.id:
                await interaction.response.send_message(
                    f"You are already in the **{entry['region'].upper()}** waitlist!",
                    ephemeral=True
                )
                return

        # Check cooldown
        import time
        last_test_time = user_cooldowns.get(interaction.user.id, 0)
        current_time = time.time()
        
        # Determine cooldown duration based on booster role
        has_booster = False
        if BOOSTER_ROLE_ID:
            booster_role = interaction.guild.get_role(BOOSTER_ROLE_ID)
            if booster_role and booster_role in interaction.user.roles:
                has_booster = True
        
        cooldown_duration = BOOSTER_COOLDOWN if has_booster else NORMAL_COOLDOWN
        remaining_time = last_test_time + cooldown_duration - current_time
        
        if remaining_time > 0:
            # Calculate days, hours, minutes remaining
            days = int(remaining_time // 86400)
            hours = int((remaining_time % 86400) // 3600)
            minutes = int((remaining_time % 3600) // 60)
            
            cooldown_text = []
            if days > 0:
                cooldown_text.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                cooldown_text.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                cooldown_text.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            
            time_str = ", ".join(cooldown_text) if cooldown_text else "less than a minute"
            cooldown_type = "Booster" if has_booster else "Normal"
            
            await interaction.response.send_message(
                f"**You Are Still On Cooldown!**\n"
                f"Cooldown Type: {cooldown_type} (4 Days / 1 Day for Boosters)\n"
                f"Time Remaining: **{time_str}**",
                ephemeral=True
            )

            # Log cooldown violation
            await log_event(
                interaction.guild,
                "⏱️ Cooldown Violation",
                f"{interaction.user.mention} attempted to join waitlist while on cooldown",
                discord.Color.yellow(),
                [
                    ("User", interaction.user.mention, True),
                    ("Cooldown Type", cooldown_type, True),
                    ("Time Remaining", time_str, True),
                    ("Attempted Via", "Join Queue Button", False)
                ]
            )
            return

        # Log if user is using booster cooldown
        if has_booster:
            await log_event(
                interaction.guild,
                "⚡ Booster Cooldown Active",
                f"{interaction.user.mention} passed cooldown check with booster status",
                discord.Color.purple(),
                [
                    ("User", interaction.user.mention, True),
                    ("Cooldown Type", "Booster (1 Day)", True),
                    ("Status", "Cooldown expired/passed", True)
                ]
            )

        # This button is for players to enter the waitlist modal
        if interaction.user.id not in verified_users:
            await interaction.response.send_message(
                "Please Verify Your Account First Before Entering Waitlist",
                ephemeral=True
            )
            return
        
        # Check if queue is full
        players_in_queue = [entry for entry in waitlist if entry["region"] == self.region]
        if len(players_in_queue) >= QUEUE_SIZE_LIMIT:
            await interaction.response.send_message(
                f"The {self.region.upper()} queue is currently full ({QUEUE_SIZE_LIMIT}/{QUEUE_SIZE_LIMIT}). Please try again later.",
                ephemeral=True
            )
            return

        # Show waitlist modal but pre-fill the region
        modal = WaitlistModal()
        modal.region.default = self.region.upper()
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Leave Queue",
        style=discord.ButtonStyle.danger,
        custom_id="leave_queue_button"
    )
    async def leave_button(self, interaction: discord.Interaction, button: Button):
        global waitlist
        user_entry = None
        for entry in waitlist:
            if entry["user_id"] == interaction.user.id and entry["region"] == self.region:
                user_entry = entry
                break

        if user_entry:
            waitlist.remove(user_entry)
            
            # Remove the waitlist role
            role_id_map = {
                "na": NA_WAITLIST_ROLE_ID,
                "eu": EU_WAITLIST_ROLE_ID,
                "as": AS_WAITLIST_ROLE_ID
            }
            role_id = role_id_map.get(self.region)
            if role_id:
                role = interaction.guild.get_role(role_id)
                if role:
                    try:
                        await interaction.user.remove_roles(role)
                    except Exception as e:
                        print(f"Failed to remove waitlist role from {interaction.user.name}: {e}")

            await interaction.response.send_message(
                f"You have been removed from the **{self.region.upper()}** waitlist.",
                ephemeral=True
            )
            await update_queue_display(interaction.guild, self.region)
        else:
            await interaction.response.send_message(
                f"You are not currently in the **{self.region.upper()}** waitlist.",
                ephemeral=True
            )


async def update_queue_display(guild, region):
    if not guild:
        # Try to find a guild where the bot is present if not provided
        if bot.guilds:
            guild = bot.guilds[0]
        else:
            return

    channel_id_map = {
        "na": NA_WAITLIST_CHANNEL_ID,
        "eu": EU_WAITLIST_CHANNEL_ID,
        "as": AS_WAITLIST_CHANNEL_ID
    }
    channel_id = channel_id_map.get(region)
    if not channel_id:
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        print(f"Error: Could not find channel object for {region} (ID: {channel_id}). Is the bot in the channel members list?")
        return

    testers_for_region = active_testers.get(region, set())
    players_in_queue = [entry for entry in waitlist if entry["region"] == region]
    
    # Format last testing session time for this region
    region_last_session = last_testing_session.get(region)
    if region_last_session:
        last_session_str = region_last_session.strftime('%B %d, %Y %I:%M %p')
    else:
        last_session_str = "No recent testing sessions"

    if not testers_for_region:
        # No testers online embed
        embed = discord.Embed(
            title="No Testers Online",
            description=(
                "No testers for your region are available at this time.\n"
                "You will be pinged when a tester is available.\n"
                "Check back later!"
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Last testing session: {last_session_str}")
        view = None # No buttons when no testers
    else:
        # Testers available embed
        embed = discord.Embed(
            title="Tester(s) Available!",
            description=(
                "**Tester(s) Available!**\n"
                "ℹ️ The queue updates every 10 seconds.\n"
                "Use `/leavewaitlist` if you wish to be removed from the waitlist or queue."
            ),
            color=discord.Color.blue()
        )
        
        # Queue field
        queue_text = "Queue is empty."
        if players_in_queue:
            queue_text = "\n".join([f"{i+1}. <@{entry['user_id']}>" for i, entry in enumerate(players_in_queue[:QUEUE_SIZE_LIMIT])])
        
        embed.add_field(
            name=f"Queue ({len(players_in_queue)}/{QUEUE_SIZE_LIMIT}):",
            value=queue_text,
            inline=False
        )
        
        # Active testers field
        tester_list = "\n".join([f"{i+1}. <@{t_id}>" for i, t_id in enumerate(testers_for_region)])
        embed.add_field(
            name="Active Testers:",
            value=tester_list if tester_list else "None",
            inline=False
        )
        view = QueueUpdateView(region)

    # Check if we have a message to edit or need to send a new one
    msg_id = waitlist_messages.get(region)
    try:
        if msg_id:
            try:
                message = await channel.fetch_message(msg_id)
                await message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                pass # Message was deleted, proceed to clear and send fresh
        
        # Clear old bot messages
        try:
            async for msg in channel.history(limit=20):
                if msg.author == bot.user:
                    await msg.delete()
        except Exception as e:
            print(f"Warning: Could not clear history in {region}: {e}")

        # Send fresh message
        message = await channel.send(embed=embed, view=view)
        waitlist_messages[region] = message.id
        print(f"Successfully updated queue display for {region}")

    except Exception as e:
        print(f"Error updating display for {region}: {e}")


class VerifyModal(Modal, title="Verify Minecraft Account"):
    ign = TextInput(
        label="What Is Your IGN?",
        placeholder="Enter your Minecraft username...",
        max_length=16,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        ign = self.ign.value.strip()

        # Check if it's a real Minecraft account using Mojang API
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://playerdb.co/api/player/minecraft/{ign}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success") and data.get("data") and data.get("data").get("player"):
                        player_data = data["data"]["player"]
                        uuid = player_data["id"]
                        real_ign = player_data["username"]
                        # Use full body skin render instead of just head
                        skin_url = f"https://mc-heads.net/player/{uuid}"

                        # Store verified user
                        verified_users[interaction.user.id] = {
                            "ign": real_ign,
                            "uuid": uuid,
                            "skin_url": f"https://mc-heads.net/player/{uuid}"
                        }

                        # Create embed with skin
                        embed = discord.Embed(
                            title="Verification Successful",
                            description=f"You Have Successfully Verified As:",
                            color=discord.Color.green()
                        )
                        embed.add_field(name="IGN", value=real_ign, inline=False)
                        embed.set_thumbnail(url=skin_url)

                        await interaction.response.send_message(
                            embed=embed,
                            ephemeral=True
                        )

                        # Log verification
                        await log_event(
                            interaction.guild,
                            "✅ User Verified",
                            f"{interaction.user.mention} verified their Minecraft account",
                            discord.Color.green(),
                            [
                                ("Discord User", interaction.user.mention, True),
                                ("IGN", real_ign, True),
                                ("UUID", uuid[:8] + "...", False)
                            ]
                        )
                        
                        # Save data
                        save_data()
                        return

        # If we get here, verification failed
        await interaction.response.send_message(
            "Please Try Again",
            ephemeral=True
        )


class WaitlistModal(Modal, title="Join the Waitlist"):
    ign = TextInput(
        label="Minecraft Username",
        placeholder="Enter your Minecraft username...",
        max_length=16,
        required=True
    )

    region = TextInput(
        label="Region (EU, NA, AS, AU)",
        placeholder="Enter your region...",
        max_length=5,
        required=True
    )

    preferred_server = TextInput(
        label="Preferred Server",
        placeholder="Enter your preferred server...",
        max_length=50,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Check if user has restricted or blacklisted role
        restricted_reason = None
        if RESTRICTED_ROLE_ID:
            restricted_role = interaction.guild.get_role(RESTRICTED_ROLE_ID)
            if restricted_role and restricted_role in interaction.user.roles:
                restricted_reason = "restricted"
        if BLACKLISTED_ROLE_ID and not restricted_reason:
            blacklisted_role = interaction.guild.get_role(BLACKLISTED_ROLE_ID)
            if blacklisted_role and blacklisted_role in interaction.user.roles:
                restricted_reason = "blacklisted"
        
        if restricted_reason:
            await interaction.response.send_message(
                f"**You are {restricted_reason} from entering the waitlist.**\n"
                "If you believe this is an error, please contact an administrator.",
                ephemeral=True
            )

            # Log restricted/blacklisted attempt
            await log_event(
                interaction.guild,
                f"🚫 {restricted_reason.title()} User Attempt",
                f"{interaction.user.mention} attempted to join the waitlist but is {restricted_reason}",
                discord.Color.red(),
                [
                    ("User", interaction.user.mention, True),
                    ("User ID", str(interaction.user.id), True),
                    ("Status", restricted_reason.title(), True),
                    ("Attempted Via", "Waitlist Modal", False)
                ]
            )
            return

        if interaction.user.id not in verified_users:
            await interaction.response.send_message(
                "Please Verify Your Account First Before Entering Waitlist",
                ephemeral=True
            )
            return

        user_data = verified_users[interaction.user.id]
        verified_ign = user_data["ign"]
        entered_ign = self.ign.value.strip()
        region = self.region.value.strip().upper()
        preferred_server = self.preferred_server.value.strip()

        # Check if entered IGN matches verified IGN
        if entered_ign.lower() != verified_ign.lower():
            await interaction.response.send_message(
                "The Minecraft Username you entered does not match your verified account. Please enter your verified IGN.",
                ephemeral=True
            )
            return

        # Check cooldown
        import time
        last_test_time = user_cooldowns.get(interaction.user.id, 0)
        current_time = time.time()
        
        # Determine cooldown duration based on booster role
        has_booster = False
        if BOOSTER_ROLE_ID:
            booster_role = interaction.guild.get_role(BOOSTER_ROLE_ID)
            if booster_role and booster_role in interaction.user.roles:
                has_booster = True
        
        cooldown_duration = BOOSTER_COOLDOWN if has_booster else NORMAL_COOLDOWN
        remaining_time = last_test_time + cooldown_duration - current_time
        
        if remaining_time > 0:
            # Calculate days, hours, minutes remaining
            days = int(remaining_time // 86400)
            hours = int((remaining_time % 86400) // 3600)
            minutes = int((remaining_time % 3600) // 60)
            
            cooldown_text = []
            if days > 0:
                cooldown_text.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                cooldown_text.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                cooldown_text.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            
            time_str = ", ".join(cooldown_text) if cooldown_text else "less than a minute"
            cooldown_type = "Booster" if has_booster else "Normal"
            
            await interaction.response.send_message(
                f"**You Are Still On Cooldown!**\n"
                f"Cooldown Type: {cooldown_type} (4 Days / 1 Day for Boosters)\n"
                f"Time Remaining: **{time_str}**",
                ephemeral=True
            )

            # Log cooldown violation
            await log_event(
                interaction.guild,
                "⏱️ Cooldown Violation",
                f"{interaction.user.mention} attempted to join waitlist while on cooldown",
                discord.Color.yellow(),
                [
                    ("User", interaction.user.mention, True),
                    ("Cooldown Type", cooldown_type, True),
                    ("Time Remaining", time_str, True),
                    ("Attempted Via", "Waitlist Modal", False)
                ]
            )
            return

        # Log if user is using booster cooldown
        if has_booster:
            await log_event(
                interaction.guild,
                "⚡ Booster Cooldown Active",
                f"{interaction.user.mention} passed cooldown check with booster status",
                discord.Color.purple(),
                [
                    ("User", interaction.user.mention, True),
                    ("Cooldown Type", "Booster (1 Day)", True),
                    ("Status", "Cooldown expired/passed", True)
                ]
            )

        # Map region to channel (AS and AU both go to as-waitlist)
        region_lower = region.lower()
        if region_lower == "au":
            region_lower = "as"

        # Add to waitlist silently or post to queue
        waitlist.append({
            "user_id": interaction.user.id,
            "region": region_lower,
            "ign": entered_ign,
            "preferred_server": preferred_server,
            "skin_url": f"https://mc-heads.net/player/{user_data['uuid']}"
        })
        
        # Trigger queue display update
        await update_queue_display(interaction.guild, region_lower)

        # Give the waitlist role
        role_id_map = {
            "na": NA_WAITLIST_ROLE_ID,
            "eu": EU_WAITLIST_ROLE_ID,
            "as": AS_WAITLIST_ROLE_ID
        }
        role_id = role_id_map.get(region_lower)
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                except Exception as e:
                    print(f"Failed to add waitlist role to {interaction.user.name}: {e}")

        # Confirm to user
        testers_for_region = active_testers.get(region_lower, set())
        if not testers_for_region:
            await interaction.response.send_message(
                f"No testers are currently available for **{region}**. You have been added to the waitlist and will be pinged when a tester joins.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"You have been added to the **{region.upper()}** waitlist. Please wait for a tester to pick you up!",
                ephemeral=True
            )

        # Log waitlist join
        await log_event(
            interaction.guild,
            "📋 User Joined Waitlist",
            f"{interaction.user.mention} joined the {region.upper()} waitlist",
            discord.Color.blue(),
            [
                ("User", interaction.user.mention, True),
                ("IGN", entered_ign, True),
                ("Region", region.upper(), True),
                ("Preferred Server", preferred_server, False),
                ("Testers Available", "Yes" if testers_for_region else "No", True),
                ("Queue Position", str(len([e for e in waitlist if e["region"] == region_lower])), True)
            ]
        )
        return


class WaitlistView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify Account",
        style=discord.ButtonStyle.primary,
        custom_id="verify_account"
    )
    async def verify_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(VerifyModal())

    @discord.ui.button(
        label="Enter Waitlist",
        style=discord.ButtonStyle.secondary,
        custom_id="enter_waitlist"
    )
    async def waitlist_button(self, interaction: discord.Interaction, button: Button):
        # Check if verified before showing waitlist modal
        if interaction.user.id not in verified_users:
            await interaction.response.send_message(
                "Please Verify Your Account First Before Entering Waitlist",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(WaitlistModal())

    @discord.ui.button(
        label="View Cooldown",
        style=discord.ButtonStyle.danger,
        custom_id="view_cooldown"
    )
    async def cooldown_button(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        
        # Check if user has cooldown
        if user_id not in user_cooldowns:
            await interaction.response.send_message(
                "✅ **No Cooldown Active**\nYou are free to enter the waitlist!",
                ephemeral=True
            )
            return
        
        last_test_time = user_cooldowns[user_id]
        current_time = time.time()
        
        # Check if user has booster role
        has_booster = False
        if BOOSTER_ROLE_ID:
            booster_role = interaction.guild.get_role(BOOSTER_ROLE_ID)
            if booster_role and booster_role in interaction.user.roles:
                has_booster = True
        
        cooldown_duration = BOOSTER_COOLDOWN if has_booster else NORMAL_COOLDOWN
        remaining_time = last_test_time + cooldown_duration - current_time
        
        if remaining_time <= 0:
            await interaction.response.send_message(
                "✅ **Cooldown Expired**\nYou are free to enter the waitlist!",
                ephemeral=True
            )
        else:
            # Format remaining time
            days = int(remaining_time // 86400)
            hours = int((remaining_time % 86400) // 3600)
            minutes = int((remaining_time % 3600) // 60)
            
            time_parts = []
            if days > 0:
                time_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                time_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                time_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            
            time_str = ", ".join(time_parts) if time_parts else "less than a minute"
            cooldown_type = "Booster (1 Day)" if has_booster else "Normal (4 Days)"
            
            embed = discord.Embed(
                title="⏱️ Cooldown Status",
                description=f"**Time Remaining:** {time_str}",
                color=discord.Color.red()
            )
            embed.add_field(name="Cooldown Type", value=cooldown_type, inline=True)
            embed.add_field(name="Status", value="🔒 On Cooldown", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    # Load saved data
    load_data()
    
    # Sync commands to every guild the bot is in
    for guild in bot.guilds:
        try:
            await tree.sync(guild=guild)
            print(f"Synced commands to guild: {guild.name}")
        except Exception as e:
            print(f"Failed to sync to {guild.name}: {e}")
        
        # Update queue display for each region on startup
        for region in ["na", "eu", "as"]:
            try:
                await update_queue_display(guild, region)
            except Exception as e:
                print(f"Error updating queue display for {region}: {e}")
        
        # Initialize leaderboard on startup
        try:
            await update_leaderboard(guild)
            print(f"Leaderboard initialized for {guild.name}")
        except Exception as e:
            print(f"Error initializing leaderboard: {e}")

    print("Bot is ready!")

    # Auto-post waitlist embed
    if REQUEST_TEST_CHANNEL_ID:
        try:
            channel = bot.get_channel(REQUEST_TEST_CHANNEL_ID)
            if channel:
                # Clear old bot messages in request channel first
                async for message in channel.history(limit=20):
                    if message.author == bot.user:
                        await message.delete()
                
                embed = discord.Embed(
                    title="Evaluation Testing Waitlist",
                    description=(
                        "Upon applying, you will be added to a waitlist channel.\n"
                        "Here you will be pinged when a tester of your region is available.\n"
                        "If you are HT3 or higher, a high ticket will be created.\n\n"
                        "• Region should be the region of the server you wish to test on\n"
                        "• Username should be the name of the account you will be testing on\n\n"
                        "Failure to provide authentic information will result in a denied test."
                    ),
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else "https://cdn.discordapp.com/embed/avatars/0.png")

                view = WaitlistView()
                await channel.send(embed=embed, view=view)
                print(f"Waitlist embed posted to {channel.name}")
        except Exception as e:
            print(f"Error posting waitlist embed: {e}")

    # Auto-post/initialize leaderboard
    if LEADERBOARD_CHANNEL_ID:
        try:
            # Clear old bot messages in leaderboard channel first
            lb_channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
            if lb_channel:
                async for message in lb_channel.history(limit=20):
                    if message.author == bot.user:
                        await message.delete()
                
                # Get first guild to initialize leaderboard
                for guild in bot.guilds:
                    await update_leaderboard(guild)
                    break
                
                print(f"Leaderboard initialized in {lb_channel.name}")
        except Exception as e:
            print(f"Error initializing leaderboard channel: {e}")

    # Send startup log message
    if LOG_CHANNEL_ID:
        try:
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                startup_embed = discord.Embed(
                    title="🤖 Bot Started",
                    description=f"**{bot.user.name}** is now online and ready!",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                startup_embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
                startup_embed.add_field(name="Commands", value=str(len(tree.get_commands())), inline=True)
                await log_channel.send(embed=startup_embed)
                print(f"Startup log sent to {log_channel.name}")
        except Exception as e:
            print(f"Error sending startup log: {e}")

@bot.event
async def on_member_join(member):
    """Automatically give new members the Member role"""
    MEMBER_ROLE_ID = 1497772252031352943
    
    try:
        role = member.guild.get_role(MEMBER_ROLE_ID)
        if role:
            await member.add_roles(role, reason="Auto-assign Member role on join")
            print(f"✅ Assigned Member role to {member.name}")
    except Exception as e:
        print(f"❌ Failed to assign Member role to {member.name}: {e}")

@tree.command(name="sync", description="Force sync slash commands (Owner only)")
async def sync_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only admins can use this.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    try:
        await tree.sync()
        await interaction.followup.send("Commands synced globally!")
    except Exception as e:
        await interaction.followup.send(f"Sync failed: {e}")


@tree.command(name="cmds", description="List all available bot commands")
async def cmds_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Amethyst Tiers - Available Commands",
        description="Here's a complete list of all bot commands:",
        color=discord.Color.blue()
    )
    
    # Player Commands
    player_cmds = (
        "`/verify` - Verify your Minecraft account\n"
        "`/waitlist` - Open the waitlist entry form\n"
        "`/leavewaitlist` - Remove yourself from the waitlist\n"
        "`/queue` - View the current queue for your region\n"
        "`/cooldown` - Check your cooldown status"
    )
    embed.add_field(name="👤 Player Commands", value=player_cmds, inline=False)
    
    # Tester Commands
    tester_cmds = (
        "`/joinqueue <region>` - Join the tester queue (NA/EU/AS)\n"
        "`/leavequeue <region>` - Leave the tester queue\n"
        "`/next` - Pick the next player from the waitlist\n"
        "`/closetest <rank>` - Close test and post results\n"
        "`/reload` - Reload the testing session message\n"
        "`/adduser @user` - Add a user to the testing channel\n"
        "`/removeuser @user` - Remove a user from the testing channel"
    )
    embed.add_field(name="🧪 Tester Commands", value=tester_cmds, inline=False)
    
    # Admin Commands
    admin_cmds = (
        "`/sync` - Force sync slash commands\n"
        "`/cmds` - Show this command list\n"
        "`/features` - Show bot features\n"
        "`/leaderboard` - View testing leaderboards\n"
        "`/resetcooldown @user` - Reset user's cooldown (Admin only)\n"
        "`/clearqueue <region>` - Clear a region queue (Admin only)"
    )
    embed.add_field(name="⚙️ Admin/Info Commands", value=admin_cmds, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="features", description="List all bot features and capabilities")
async def features_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✨ Amethyst Tiers - Bot Features",
        description="Here's everything the bot can do:",
        color=discord.Color.gold()
    )
    
    # Queue System
    queue_features = (
        "• **Regional Queues** - Separate queues for NA, EU, and AS regions\n"
        "• **Dynamic Queue Display** - Live queue updates with Join/Leave buttons\n"
        "• **Queue Size Limit** - Max 10 players per region queue\n"
        "• **Duplicate Prevention** - Can't join queue if already in one"
    )
    embed.add_field(name="📊 Queue System", value=queue_features, inline=False)
    
    # Testing System
    testing_features = (
        "• **Private Testing Channels** - Auto-created channels for each test\n"
        "• **Tester Assignment** - Testers can pick next player with `/next`\n"
        "• **Session Management** - Track active tests and session data\n"
        "• **Channel Permissions** - Only tester + player can see the channel"
    )
    embed.add_field(name="🔒 Testing System", value=testing_features, inline=False)
    
    # Role Management
    role_features = (
        "• **Waitlist Roles** - Auto-assign @NA/EU/AS Waitlist roles\n"
        "• **Rank Roles** - Auto-assign HT1-5 and LT1-5 rank roles\n"
        "• **Role Removal** - Old rank roles removed when new ones assigned\n"
        "• **Role Pings** - Waitlist roles pinged when testers become available"
    )
    embed.add_field(name="🏷️ Role Management", value=role_features, inline=False)
    
    # Cooldown System
    cooldown_features = (
        "• **4-Day Cooldown** - Normal users must wait 4 days between tests\n"
        "• **Booster Cooldown** - Boosters only wait 1 day\n"
        "• **Cooldown Tracking** - Automatic tracking of last test completion\n"
        "• **Time Remaining Display** - Shows exact time left on cooldown"
    )
    embed.add_field(name="⏱️ Cooldown System", value=cooldown_features, inline=False)
    
    # Results & Verification
    results_features = (
        "• **Minecraft Verification** - Verify accounts via Mojang API\n"
        "• **Test Results** - Posted to #results with rank info\n"
        "• **Emoji Reactions** - Auto-added reactions to result posts\n"
        "• **Rank History** - Tracks previous vs earned ranks"
    )
    embed.add_field(name="📈 Results & Verification", value=results_features, inline=False)
    
    # Leaderboard System
    leaderboard_features = (
        "• **All-Time Leaderboard** - Top 10 testers with most tests ever\n"
        "• **Monthly Leaderboard** - Top 10 testers for current month\n"
        "• **Auto-Reset** - Monthly stats reset automatically each month\n"
        "• **Personal Stats** - View your own testing statistics\n"
        "• **Live Updates** - Updates automatically when tests complete"
    )
    embed.add_field(name="🏆 Leaderboard System", value=leaderboard_features, inline=False)
    
    # Quality of Life
    qol_features = (
        "• **Auto-Cleanup** - Old bot messages deleted on restart\n"
        "• **Channel Management** - Testing channels auto-delete after completion\n"
        "• **Error Handling** - Friendly error messages for all issues\n"
        "• **Ephemeral Messages** - Private responses for sensitive info"
    )
    embed.add_field(name="🎯 Quality of Life", value=qol_features, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="leaderboard", description="View testing leaderboards (Admin only refresh)")
@app_commands.describe(action="Action to perform")
@app_commands.choices(action=[
    app_commands.Choice(name="view", value="view"),
    app_commands.Choice(name="refresh", value="refresh"),
    app_commands.Choice(name="my_stats", value="my_stats")
])
async def leaderboard_command(interaction: discord.Interaction, action: str = "view"):
    # Only allow refresh for testers/admins
    if action == "refresh":
        tester_role = interaction.guild.get_role(TESTER_ROLE_ID)
        if tester_role and tester_role not in interaction.user.roles:
            await interaction.response.send_message(
                "Only testers can refresh the leaderboard!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        await update_leaderboard(interaction.guild)
        await interaction.followup.send("Leaderboard refreshed!")
        return
    
    if action == "my_stats":
        user_id = interaction.user.id
        stats = tester_stats.get(user_id, {"all_time": 0, "monthly": {}})
        
        now = datetime.now()
        month_key = (now.year, now.month)
        monthly_count = stats["monthly"].get(month_key, 0)
        
        embed = discord.Embed(
            title="📊 Your Testing Statistics",
            color=discord.Color.purple(),
            timestamp=now
        )
        embed.add_field(name="All-Time Tests", value=str(stats["all_time"]), inline=True)
        embed.add_field(name=f"{now.strftime('%B')} Tests", value=str(monthly_count), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Default: view leaderboards
    now = datetime.now()
    current_month_key = (now.year, now.month)
    
    # Get all-time top 10
    all_time_leaderboard = sorted(
        [(tester_id, stats["all_time"]) for tester_id, stats in tester_stats.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]
    
    # Get monthly top 10
    monthly_leaderboard = sorted(
        [(tester_id, stats["monthly"].get(current_month_key, 0)) 
         for tester_id, stats in tester_stats.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]
    
    total_monthly_tests = sum(count for _, count in monthly_leaderboard)

    # Build all-time text (top 10 for ephemeral)
    all_time_text = ""
    if all_time_leaderboard:
        for i, (tester_id, count) in enumerate(all_time_leaderboard[:10], 1):
            member = interaction.guild.get_member(tester_id)
            name = member.mention if member else f"<@{tester_id}>"
            all_time_text += f"**{i}.** {name} — **{count}** tests\n"
    else:
        all_time_text = "No tests completed yet!"

    # Build monthly text (top 10 for ephemeral)
    monthly_text = ""
    if monthly_leaderboard and monthly_leaderboard[0][1] > 0:
        for i, (tester_id, count) in enumerate(monthly_leaderboard[:10], 1):
            member = interaction.guild.get_member(tester_id)
            name = member.mention if member else f"<@{tester_id}>"
            monthly_text += f"**{i}.** {name} — **{count}** tests\n"
    else:
        monthly_text = f"No tests for {now.strftime('%B')} yet!"

    embed = discord.Embed(
        title="🏆 Testing Leaderboards",
        color=discord.Color.gold(),
        timestamp=now
    )
    
    embed.add_field(name="🏆 All-Time Top 10", value=all_time_text, inline=False)
    embed.add_field(name=f"🥇 {now.strftime('%B')} Top 10", value=monthly_text, inline=False)
    
    if total_monthly_tests > 0:
        embed.add_field(name="\u200b", value=f"**Total Tests this Month: {total_monthly_tests}**", inline=False)
    
    embed.set_footer(text="Use /leaderboard action:refresh to update • /leaderboard action:my_stats for your stats")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="cooldown", description="Check your cooldown status")
async def cooldown_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    if user_id not in user_cooldowns:
        await interaction.response.send_message(
            "✅ **No Cooldown Active**\nYou are free to enter the waitlist!",
            ephemeral=True
        )
        return
    
    last_test_time = user_cooldowns[user_id]
    current_time = time.time()
    
    # Check if user has booster role
    has_booster = False
    if BOOSTER_ROLE_ID:
        booster_role = interaction.guild.get_role(BOOSTER_ROLE_ID)
        if booster_role and booster_role in interaction.user.roles:
            has_booster = True
    
    cooldown_duration = BOOSTER_COOLDOWN if has_booster else NORMAL_COOLDOWN
    remaining_time = last_test_time + cooldown_duration - current_time
    
    if remaining_time <= 0:
        await interaction.response.send_message(
            "✅ **Cooldown Expired**\nYou are free to enter the waitlist!",
            ephemeral=True
        )
    else:
        # Format remaining time
        days = int(remaining_time // 86400)
        hours = int((remaining_time % 86400) // 3600)
        minutes = int((remaining_time % 3600) // 60)
        
        time_parts = []
        if days > 0:
            time_parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            time_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            time_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        time_str = ", ".join(time_parts) if time_parts else "less than a minute"
        cooldown_type = "Booster (1 Day)" if has_booster else "Normal (4 Days)"
        
        embed = discord.Embed(
            title="⏱️ Cooldown Status",
            description=f"**Time Remaining:** {time_str}",
            color=discord.Color.yellow()
        )
        embed.add_field(name="Cooldown Type", value=cooldown_type, inline=True)
        embed.add_field(name="Status", value="🔒 On Cooldown", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="resetcooldown", description="Reset cooldown for a user (Admin only)")
@app_commands.describe(user="The user to reset cooldown for")
async def resetcooldown_command(interaction: discord.Interaction, user: discord.Member):
    # Check if user has admin permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Only administrators can reset cooldowns!",
            ephemeral=True
        )
        return
    
    user_id = str(user.id)
    
    if user_id in user_cooldowns:
        del user_cooldowns[user_id]
        save_data()
        
        await interaction.response.send_message(
            f"✅ Cooldown reset for {user.mention}!",
            ephemeral=True
        )
        
        # Log the action
        await log_event(
            interaction.guild,
            "⚙️ Cooldown Reset",
            f"{interaction.user.mention} reset cooldown for {user.mention}",
            discord.Color.orange(),
            [
                ("Admin", interaction.user.mention, True),
                ("User", user.mention, True),
                ("Action", "Cooldown Reset", True)
            ]
        )
    else:
        await interaction.response.send_message(
            f"{user.mention} is not currently on cooldown.",
            ephemeral=True
        )


@tree.command(name="clearqueue", description="Clear all users from a region queue (Admin only)")
@app_commands.describe(region="The region queue to clear")
async def clearqueue_command(interaction: discord.Interaction, region: str):
    # Check if user has admin permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Only administrators can clear queues!",
            ephemeral=True
        )
        return
    
    region = region.lower()
    if region not in ["na", "eu", "as"]:
        await interaction.response.send_message(
            "Invalid region. Use: NA, EU, or AS",
            ephemeral=True
        )
        return
    
    # Count users in queue
    users_in_queue = [entry for entry in waitlist if entry["region"] == region]
    count = len(users_in_queue)
    
    if count == 0:
        await interaction.response.send_message(
            f"The **{region.upper()}** queue is already empty.",
            ephemeral=True
        )
        return
    
    # Remove users from queue
    for entry in users_in_queue:
        waitlist.remove(entry)
        
        # Remove waitlist role
        waitlist_role_id = None
        if region == "na":
            waitlist_role_id = NA_WAITLIST_ROLE_ID
        elif region == "eu":
            waitlist_role_id = EU_WAITLIST_ROLE_ID
        else:
            waitlist_role_id = AS_WAITLIST_ROLE_ID
        
        if waitlist_role_id:
            role = interaction.guild.get_role(waitlist_role_id)
            if role:
                user = interaction.guild.get_member(entry["user_id"])
                if user:
                    try:
                        await user.remove_roles(role)
                    except:
                        pass
    
    # Update queue display
    await update_queue_display(interaction.guild, region)
    
    await interaction.response.send_message(
        f"✅ Cleared **{count}** user(s) from the **{region.upper()}** queue.",
        ephemeral=True
    )
    
    # Log the action
    await log_event(
        interaction.guild,
        "⚠️ Queue Cleared",
        f"{interaction.user.mention} cleared the {region.upper()} queue",
        discord.Color.red(),
        [
            ("Admin", interaction.user.mention, True),
            ("Region", region.upper(), True),
            ("Users Removed", str(count), True)
        ]
    )


@tree.command(name="joinqueue", description="Join the tester queue for your region")
@app_commands.describe(region="Your testing region (NA, EU, AS)")
async def joinqueue_command(interaction: discord.Interaction, region: str):
    # Check if used in bot-commands channel
    if not BOT_COMMANDS_CHANNEL_ID or interaction.channel_id != BOT_COMMANDS_CHANNEL_ID:
        await interaction.response.send_message(
            "This command can only be used in #bot-commands",
            ephemeral=True
        )
        return

    region = region.lower()
    if region not in active_testers:
        await interaction.response.send_message(
            "Invalid region. Use: NA, EU, or AS",
            ephemeral=True
        )
        return

    # Check if there were no testers before this one joined
    had_testers_before = len(active_testers[region]) > 0

    active_testers[region].add(interaction.user.id)
    await interaction.response.send_message(
        f"You are now active as a tester for region **{region.upper()}**",
        ephemeral=True
    )

    # Log tester joining queue
    await log_event(
        interaction.guild,
        "🧪 Tester Joined Queue",
        f"{interaction.user.mention} joined the {region.upper()} tester queue",
        discord.Color.purple(),
        [
            ("Tester", interaction.user.mention, True),
            ("Region", region.upper(), True),
            ("Active Testers", str(len(active_testers[region])), True),
            ("Queue Opened", "Yes" if not had_testers_before else "No", True)
        ]
    )

    # Update queue display in waitlist channel
    await update_queue_display(interaction.guild, region)
    
    # Ping waitlist role if this is the first tester joining
    if not had_testers_before:
        role_id_map = {
            "na": NA_WAITLIST_ROLE_ID,
            "eu": EU_WAITLIST_ROLE_ID,
            "as": AS_WAITLIST_ROLE_ID
        }
        role_id = role_id_map.get(region)
        if role_id:
            channel_id_map = {
                "na": NA_WAITLIST_CHANNEL_ID,
                "eu": EU_WAITLIST_CHANNEL_ID,
                "as": AS_WAITLIST_CHANNEL_ID
            }
            channel_id = channel_id_map.get(region)
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                await channel.send(f"<@&{role_id}> Queue is now open for **{region.upper()}**!")


@tree.command(name="leavequeue", description="Leave the tester queue for your region")
@app_commands.describe(region="Your testing region (NA, EU, AS)")
async def leavequeue_command(interaction: discord.Interaction, region: str):
    if not BOT_COMMANDS_CHANNEL_ID or interaction.channel_id != BOT_COMMANDS_CHANNEL_ID:
        await interaction.response.send_message(
            "This command can only be used in #bot-commands",
            ephemeral=True
        )
        return

    region = region.lower()
    if region in active_testers and interaction.user.id in active_testers[region]:
        active_testers[region].remove(interaction.user.id)
        await interaction.response.send_message(
            f"You have left the queue for region **{region.upper()}**",
            ephemeral=True
        )

        # Log tester leaving queue
        await log_event(
            interaction.guild,
            "🚪 Tester Left Queue",
            f"{interaction.user.mention} left the {region.upper()} tester queue",
            discord.Color.orange(),
            [
                ("Tester", interaction.user.mention, True),
                ("Region", region.upper(), True),
                ("Remaining Testers", str(len(active_testers[region])), True),
                ("Queue Closed", "Yes" if len(active_testers[region]) == 0 else "No", True)
            ]
        )

        # Update queue display in waitlist channel
        await update_queue_display(interaction.guild, region)
    else:
        await interaction.response.send_message(
            "You are not in the queue for that region",
            ephemeral=True
        )


@tree.command(name="leavewaitlist", description="Leave the testing waitlist")
async def leavewaitlist_command(interaction: discord.Interaction):
    global waitlist
    # Find user's entry in waitlist
    user_entry = None
    for entry in waitlist:
        if entry["user_id"] == interaction.user.id:
            user_entry = entry
            break

    if user_entry:
        region = user_entry["region"]
        waitlist.remove(user_entry)
        
        # Remove the waitlist role
        role_id_map = {
            "na": NA_WAITLIST_ROLE_ID,
            "eu": EU_WAITLIST_ROLE_ID,
            "as": AS_WAITLIST_ROLE_ID
        }
        role_id = role_id_map.get(region)
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await interaction.user.remove_roles(role)
                except Exception as e:
                    print(f"Failed to remove waitlist role from {interaction.user.name}: {e}")

        await interaction.response.send_message(
            f"You have been removed from the **{user_entry['region'].upper()}** waitlist.",
            ephemeral=True
        )

        # Log waitlist leave
        await log_event(
            interaction.guild,
            "🚪 User Left Waitlist",
            f"{interaction.user.mention} left the {user_entry['region'].upper()} waitlist",
            discord.Color.orange(),
            [
                ("User", interaction.user.mention, True),
                ("Region", user_entry['region'].upper(), True),
                ("IGN", user_entry.get('ign', 'Unknown'), True)
            ]
        )

        # Update queue display in waitlist channel
        await update_queue_display(interaction.guild, region)
    else:
        await interaction.response.send_message(
            "You are not currently in any waitlist.",
            ephemeral=True
        )


@tree.command(name="queue", description="View the current queue for your region")
async def queue_command(interaction: discord.Interaction):
    # Get user's region from their queue entry or show all
    user_region = None
    for entry in waitlist:
        if entry["user_id"] == interaction.user.id:
            user_region = entry["region"]
            break

    # If user is a tester, show their testing region
    if not user_region:
        for region, testers in active_testers.items():
            if interaction.user.id in testers:
                user_region = region
                break

    if not user_region:
        await interaction.response.send_message(
            "You are not in any queue. Use `/joinqueue <region>` to join as a tester, or enter the waitlist to be tested.",
            ephemeral=True
        )
        return

    # Get players in waitlist for this region
    players_in_queue = [entry for entry in waitlist if entry["region"] == user_region]

    # Get testers active for this region
    testers_in_queue = active_testers.get(user_region, set())

    # Create queue embed
    queue_embed = discord.Embed(
        title=f"Queue for {user_region.upper()}",
        color=discord.Color.blue()
    )

    # Normal players in queue
    if players_in_queue:
        player_list = "\n".join([f"{i+1}. {entry['ign']}" for i, entry in enumerate(players_in_queue[:QUEUE_SIZE_LIMIT])])
        queue_embed.add_field(
            name=f"Normal Players in Queue ({len(players_in_queue)}/{QUEUE_SIZE_LIMIT})",
            value=player_list,
            inline=False
        )
    else:
        queue_embed.add_field(
            name="Normal Players in Queue (0/10)",
            value="No players in queue",
            inline=False
        )

    # Testers in queue
    if testers_in_queue:
        tester_mentions = " ".join([f"<@{tester_id}>" for tester_id in testers_in_queue])
        queue_embed.add_field(
            name=f"Testers in Queue (Testing) ({len(testers_in_queue)})",
            value=tester_mentions,
            inline=False
        )
    else:
        queue_embed.add_field(
            name="Testers in Queue (Testing) (0)",
            value="No testers available",
            inline=False
        )

    await interaction.response.send_message(embed=queue_embed, ephemeral=True)


@tree.command(name="next", description="Pick the next person from the waitlist (Testers only)")
async def next_command(interaction: discord.Interaction):
    global waitlist

    # Check if user is a tester
    if not is_tester(interaction):
        await interaction.response.send_message(
            "Only testers can use the `/next` command.",
            ephemeral=True
        )
        return

    # Find which region this tester is active in
    tester_region = None
    for region, testers in active_testers.items():
        if interaction.user.id in testers:
            tester_region = region
            break
            
    # If not in active_testers list but has role, default to first region with users or allow selection?
    # For now, if they have the role but aren't in a queue, we'll ask them to join one.
    if not tester_region:
        await interaction.response.send_message(
            "You have the tester role, but you haven't joined a region queue. Use `/joinqueue <region>` first so I know which region you want to test for.",
            ephemeral=True
        )
        return

    # Find the first person in waitlist for this region
    next_user_entry = None
    for entry in waitlist:
        if entry["region"] == tester_region:
            next_user_entry = entry
            break

    if not next_user_entry:
        await interaction.response.send_message(
            f"No users are currently in the **{tester_region.upper()}** waitlist.",
            ephemeral=True
        )
        return

    # Get the user object
    guild = interaction.guild
    user = guild.get_member(next_user_entry["user_id"])

    if not user:
        # User left the server, remove from waitlist
        waitlist.remove(next_user_entry)
        await interaction.response.send_message(
            "The next user in queue is no longer in the server. They have been removed from the waitlist.",
            ephemeral=True
        )
        return

    # Remove user from waitlist
    waitlist.remove(next_user_entry)
    
    # Remove the waitlist role
    role_id_map = {
        "na": NA_WAITLIST_ROLE_ID,
        "eu": EU_WAITLIST_ROLE_ID,
        "as": AS_WAITLIST_ROLE_ID
    }
    role_id = role_id_map.get(tester_region)
    if role_id:
        role = interaction.guild.get_role(role_id)
        if role:
            try:
                await user.remove_roles(role)
            except Exception as e:
                print(f"Failed to remove waitlist role from {user.name}: {e}")

    # Update queue display in waitlist channel
    await update_queue_display(interaction.guild, tester_region)

    # Create a private text channel
    channel_name = f"testing-{next_user_entry['ign'].lower()}"

    # Create overwrites for the channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }

    try:
        # Create the testing channel in the same category as the waitlist channel
        channel_id_map = {
            "na": NA_WAITLIST_CHANNEL_ID,
            "eu": EU_WAITLIST_CHANNEL_ID,
            "as": AS_WAITLIST_CHANNEL_ID
        }
        waitlist_channel_id = channel_id_map.get(tester_region)
        waitlist_channel = guild.get_channel(waitlist_channel_id) if waitlist_channel_id else None

        category = None
        if waitlist_channel and waitlist_channel.category:
            category = waitlist_channel.category

        testing_channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category,
            topic=f"Testing session for {next_user_entry['ign']} | Region: {tester_region.upper()}"
        )

        # Send initial message in the channel (format: @User, embed, User, Region, Preferred Server, Request Time)
        embed = discord.Embed(
            title="Testing Session Started",
            description=f"Testing session for **{next_user_entry['ign']}**",
            color=discord.Color.green()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Region", value=tester_region.upper(), inline=True)
        embed.add_field(name="Preferred Server", value=next_user_entry['preferred_server'], inline=False)
        embed.add_field(name="Request Time", value=next_user_entry.get('request_time', 'N/A'), inline=False)
        embed.set_thumbnail(url=next_user_entry['skin_url'])

        await testing_channel.send(
            content=f"{user.mention}",
            embed=embed
        )

        # Store active session data for later use
        active_sessions[testing_channel.id] = {
            "tester_id": interaction.user.id,
            "tester_mention": interaction.user.mention,
            "user_id": user.id,
            "user_mention": user.mention,
            "ign": next_user_entry['ign'],
            "region": tester_region,
            "skin_url": next_user_entry['skin_url']  # Already full body URL
        }

        # Send confirmation to tester
        await interaction.response.send_message(
            f"You are now testing **{next_user_entry['ign']}** in {testing_channel.mention}",
            ephemeral=True
        )

        # Log test started
        await log_event(
            interaction.guild,
            "🎯 Test Started",
            f"Testing session started for {user.mention}",
            discord.Color.green(),
            [
                ("Tester", interaction.user.mention, True),
                ("Player", user.mention, True),
                ("IGN", next_user_entry['ign'], True),
                ("Region", tester_region.upper(), True),
                ("Channel", testing_channel.mention, False)
            ]
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "I don't have permission to create channels. Please check my permissions.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"An error occurred: {str(e)}",
            ephemeral=True
        )


def is_tester(interaction: discord.Interaction):
    # Check if user has the tester role
    if TESTER_ROLE_ID:
        role = interaction.guild.get_role(TESTER_ROLE_ID)
        if role and role in interaction.user.roles:
            return True
            
    # Fallback to internal active_testers list
    for testers in active_testers.values():
        if interaction.user.id in testers:
            return True
    return False


@tree.command(name="reload", description="Reload the testing session message (Testers only)")
async def reload_command(interaction: discord.Interaction):
    # Check if user is a tester
    if not is_tester(interaction):
        await interaction.response.send_message(
            "Only testers can reload testing messages.",
            ephemeral=True
        )
        return

    # Check if this is a testing channel
    if not interaction.channel.name.startswith("testing-"):
        await interaction.response.send_message(
            "This command can only be used in testing channels.",
            ephemeral=True
        )
        return

    # Get session data
    session = active_sessions.get(interaction.channel.id)
    if not session:
        await interaction.response.send_message(
            "Could not find session data for this channel.",
            ephemeral=True
        )
        return

    # Get the user object
    guild = interaction.guild
    user = guild.get_member(session["user_id"])

    if not user:
        await interaction.response.send_message(
            "The user being tested is no longer in the server.",
            ephemeral=True
        )
        return

    # Delete the old message (the first message in the channel)
    async for message in interaction.channel.history(limit=1):
        if message.author == bot.user:
            await message.delete()
            break

    # Send new message with updated info
    embed = discord.Embed(
        title="Testing Session Started",
        description=f"Testing session for **{session['ign']}**",
        color=discord.Color.green()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Region", value=session["region"].upper(), inline=True)
    embed.add_field(name="Preferred Server", value=session.get('preferred_server', 'N/A'), inline=False)
    embed.add_field(name="Request Time", value=session.get('request_time', 'N/A'), inline=False)
    embed.set_thumbnail(url=session["skin_url"])

    await interaction.channel.send(
        content=f"{user.mention}",
        embed=embed
    )

    await interaction.response.send_message(
        "Message reloaded successfully.",
        ephemeral=True
    )


@tree.command(name="adduser", description="Add a user to the testing channel (Testers only)")
@app_commands.describe(user="The user to add to the channel")
async def adduser_command(interaction: discord.Interaction, user: discord.Member):
    # Check if user is a tester
    if not is_tester(interaction):
        await interaction.response.send_message(
            "Only testers can add users to testing channels.",
            ephemeral=True
        )
        return

    # Check if this is a testing channel
    if not interaction.channel.name.startswith("testing-"):
        await interaction.response.send_message(
            "This command can only be used in testing channels.",
            ephemeral=True
        )
        return

    # Add user to channel
    await interaction.channel.set_permissions(
        user,
        view_channel=True,
        send_messages=True
    )

    await interaction.response.send_message(
        f"Added {user.mention} to the testing channel.",
        ephemeral=True
    )


@tree.command(name="removeuser", description="Remove a user from the testing channel (Testers only)")
@app_commands.describe(user="The user to remove from the channel")
async def removeuser_command(interaction: discord.Interaction, user: discord.Member):
    # Check if user is a tester
    if not is_tester(interaction):
        await interaction.response.send_message(
            "Only testers can remove users from testing channels.",
            ephemeral=True
        )
        return

    # Check if this is a testing channel
    if not interaction.channel.name.startswith("testing-"):
        await interaction.response.send_message(
            "This command can only be used in testing channels.",
            ephemeral=True
        )
        return

    # Don't allow removing the tester or the original user
    session = active_sessions.get(interaction.channel.id)
    if session and user.id == session["user_id"]:
        await interaction.response.send_message(
            "You cannot remove the original user being tested.",
            ephemeral=True
        )
        return

    if user.id == interaction.user.id:
        await interaction.response.send_message(
            "You cannot remove yourself.",
            ephemeral=True
        )
        return

    # Remove user from channel
    await interaction.channel.set_permissions(
        user,
        view_channel=False,
        send_messages=False
    )

    await interaction.response.send_message(
        f"Removed {user.mention} from the testing channel.",
        ephemeral=True
    )


@tree.command(name="closetest", description="Close the current testing channel and post results (Testers only)")
@app_commands.describe(rank="The rank earned")
@app_commands.choices(rank=[
    app_commands.Choice(name="High Tier 1", value="ht1"),
    app_commands.Choice(name="High Tier 2", value="ht2"),
    app_commands.Choice(name="High Tier 3", value="ht3"),
    app_commands.Choice(name="High Tier 4", value="ht4"),
    app_commands.Choice(name="High Tier 5", value="ht5"),
    app_commands.Choice(name="Low Tier 1", value="lt1"),
    app_commands.Choice(name="Low Tier 2", value="lt2"),
    app_commands.Choice(name="Low Tier 3", value="lt3"),
    app_commands.Choice(name="Low Tier 4", value="lt4"),
    app_commands.Choice(name="Low Tier 5", value="lt5"),
    app_commands.Choice(name="None", value="none"),
])
async def closetest_command(interaction: discord.Interaction, rank: str):
    # Defer the response immediately to avoid timeout
    await interaction.response.defer(ephemeral=True)

    # Check if user is a tester
    if not is_tester(interaction):
        await interaction.followup.send(
            "Only testers can close testing channels."
        )
        return

    # Check if this is a testing channel
    if not interaction.channel.name.startswith("testing-"):
        await interaction.followup.send(
            "This command can only be used in testing channels."
        )
        return

    # Get session data
    session = active_sessions.get(interaction.channel.id)
    if not session:
        await interaction.followup.send(
            "Could not find session data for this channel."
        )
        return

    # Format rank for display
    rank = rank.lower()
    rank_map = {
        "ht1": "High Tier 1",
        "ht2": "High Tier 2",
        "ht3": "High Tier 3",
        "ht4": "High Tier 4",
        "ht5": "High Tier 5",
        "lt1": "Low Tier 1",
        "lt2": "Low Tier 2",
        "lt3": "Low Tier 3",
        "lt4": "Low Tier 4",
        "lt5": "Low Tier 5",
        "none": "None"
    }
    
    # Map rank codes to Role IDs for automatic assignment
    # Update these with your actual Role IDs
    rank_role_map = {
        "ht1": 1497772309619019786, # Replace with HT1 Role ID
        "ht2": 1497772299112153169, # Replace with HT2 Role ID
        "ht3": 1497772288550899752, # Replace with HT3 Role ID
        "ht4": 1497772278619045969, # Replace with HT4 Role ID
        "ht5": 1497772267902468197, # Replace with HT5 Role ID
        "lt1": 1497772304636186704, # Replace with LT1 Role ID
        "lt2": 1497772293504630794, # Replace with LT2 Role ID
        "lt3": 1497772283794690099, # Replace with LT3 Role ID
        "lt4": 1497772273677897861, # Replace with LT4 Role ID
        "lt5": 1497772262349078528, # Replace with LT5 Role ID
    }
    
    rank_display = rank_map.get(rank, rank.upper())

    # Get previous rank code and map it to display name
    previous_rank_code = user_ranks.get(session["user_id"], "none")
    previous_rank = rank_map.get(previous_rank_code, previous_rank_code.upper())

    # Get the user object and assign the role
    guild = interaction.guild
    user = guild.get_member(session["user_id"])
    
    if user and rank in rank_role_map:
        role_id = rank_role_map[rank]
        if role_id != 000000000000000000:
            role = guild.get_role(role_id)
            if role:
                try:
                    # Remove previous rank roles if any
                    for r_code, r_id in rank_role_map.items():
                        old_role = guild.get_role(r_id)
                        if old_role and old_role in user.roles:
                            await user.remove_roles(old_role)
                    
                    # Add new rank role
                    await user.add_roles(role)
                    print(f"Assigned {rank_display} to {user.display_name}")
                except Exception as e:
                    print(f"Failed to assign role: {e}")

    # Find results channel by ID
    results_channel = None

    if RESULTS_CHANNEL_ID:
        results_channel = guild.get_channel(RESULTS_CHANNEL_ID)

    if not results_channel:
        await interaction.followup.send(
            "Could not find #results channel. Please check the channel ID configuration."
        )
        return

    # Create results embed
    results_embed = discord.Embed(
        title=f"{session['ign']}'s Test Results 🏆",
        color=discord.Color.red()
    )
    results_embed.add_field(name="Tester:", value=session["tester_mention"], inline=False)
    results_embed.add_field(name="Region:", value=session["region"].upper(), inline=False)
    results_embed.add_field(name="Username:", value=session["ign"], inline=False)
    results_embed.add_field(name="Previous Rank:", value=previous_rank, inline=False)
    results_embed.add_field(name="Rank Earned:", value=rank_display, inline=False)
    results_embed.set_thumbnail(url=session["skin_url"])

    # Send results to results channel with user mention
    results_message = await results_channel.send(
        content=f"{session['user_mention']}",
        embed=results_embed
    )

    # Add emoji reactions
    emojis = ["👑", "😭", "😤", "😢", "😂", "💀"]
    for emoji in emojis:
        try:
            await results_message.add_reaction(emoji)
        except:
            pass  # Ignore if emoji fails

    # Update user's rank
    user_ranks[session["user_id"]] = rank

    # Set cooldown timestamp for the user
    user_cooldowns[session["user_id"]] = time.time()

    # Check if user has booster role for logging
    user = guild.get_member(session["user_id"])
    has_booster = False
    if BOOSTER_ROLE_ID and user:
        booster_role = guild.get_role(BOOSTER_ROLE_ID)
        if booster_role and booster_role in user.roles:
            has_booster = True

    # Log cooldown assignment
    cooldown_type = "Booster (1 Day)" if has_booster else "Normal (4 Days)"
    await log_event(
        guild,
        "⏱️ Cooldown Assigned",
        f"{session['user_mention']} has been placed on cooldown",
        discord.Color.blue(),
        [
            ("User", session['user_mention'], True),
            ("Cooldown Type", cooldown_type, True),
            ("Expires", "1 day from now" if has_booster else "4 days from now", True),
            ("Booster Role", "Active" if has_booster else "Not Active", False)
        ]
    )

    # Update last testing session timestamp for this region
    global last_testing_session
    from datetime import datetime
    test_region = session.get("region", "na")  # Get region from session
    last_testing_session[test_region] = datetime.now()

    # Update queue display to show new last testing session time
    await update_queue_display(guild, test_region)

    # Remove from active sessions
    del active_sessions[interaction.channel.id]

    # Send closing confirmation
    await interaction.followup.send(
        f"Test completed! Results posted in {results_channel.mention}"
    )

    # Update tester statistics for leaderboard
    tester_id = session["tester_id"]
    if tester_id not in tester_stats:
        tester_stats[tester_id] = {"all_time": 0, "monthly": {}}
    
    # Update all-time count
    tester_stats[tester_id]["all_time"] += 1
    
    # Update monthly count
    now = datetime.now()
    month_key = (now.year, now.month)
    if month_key not in tester_stats[tester_id]["monthly"]:
        tester_stats[tester_id]["monthly"][month_key] = 0
    tester_stats[tester_id]["monthly"][month_key] += 1

    # Update leaderboard display
    await update_leaderboard(guild)
    
    # Save data to persist stats
    save_data()

    # Log test completion
    await log_event(
        interaction.guild,
        "✅ Test Completed",
        f"Testing session completed for {session['user_mention']}",
        discord.Color.gold(),
        [
            ("Tester", session['tester_mention'], True),
            ("Player", session['user_mention'], True),
            ("IGN", session['ign'], True),
            ("Region", test_region.upper(), True),
            ("Previous Rank", previous_rank, True),
            ("Earned Rank", rank_display, True),
            ("Results", results_channel.mention, False)
        ]
    )

    # Wait a moment then delete the channel
    await asyncio.sleep(5)
    await interaction.channel.delete(reason="Testing session completed")


@tree.command(name="waitlist", description="Send the waitlist embed with buttons")
async def waitlist_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Evaluation Testing Waitlist",
         description=(
            "Upon applying, you will be added to a waitlist channel.\n"
            "Here you will be pinged when a tester of your region is available.\n"
            "If you are HT3 or higher, a high ticket will be created.\n\n"
            "• Region should be the region of the server you wish to test on\n"
            "• Username should be the name of the account you will be testing on\n\n"
            "Failure to provide authentic information will result in a denied test."
        ),
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else "https://cdn.discordapp.com/embed/avatars/0.png")

    view = WaitlistView()
    await interaction.response.send_message(embed=embed, view=view)


# Handle graceful shutdown
def handle_shutdown(signum, frame):
    print("\n⚠️  Shutdown signal received, saving data...")
    save_data()
    print("✅ Data saved. Exiting...")
    exit(0)

# Register signal handlers
import signal
signal.signal(signal.SIGINT, handle_shutdown)  # Ctrl+C
signal.signal(signal.SIGTERM, handle_shutdown)  # Termination signal

# Run the bot
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
finally:
    # Save data when bot stops
    print("⚠️  Bot stopped, saving data...")
    save_data()
    print("✅ Data saved.")
