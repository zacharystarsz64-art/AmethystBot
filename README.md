# Minecraft Tierlist Waitlist Bot

A Discord bot for managing Minecraft tierlist evaluation waitlists with account verification.

## Features

- **Verify Account**: Opens a modal to enter your Minecraft IGN and verifies it against the Mojang API
- **Enter Waitlist**: Adds verified users to a waitlist with their region
- **Skin Preview**: Shows the user's Minecraft skin upon successful verification
- **Ephemeral Messages**: All responses are private (only the user can see them)

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file with your bot token:
   ```
   DISCORD_TOKEN=your_bot_token_here
   ```

3. Run the bot:
   ```bash
   python bot.py
   ```

4. Use the `/waitlist` command to send the waitlist embed in your desired channel

## How It Works

1. User clicks **"Verify Account"** and enters their IGN
2. Bot verifies the account using the PlayerDB API
3. If valid, shows success message with skin preview
4. If invalid, shows "Please Try Again"
5. User clicks **"Enter Waitlist"** after verification
6. Bot asks for region and adds them to the waitlist
7. If not verified, shows "Please Verify Your Account First Before Entering Waitlist"

## Note

For HT3+ high ticket creation, you'll need to implement your own tier checking logic in the `RegionModal.on_submit` method.
