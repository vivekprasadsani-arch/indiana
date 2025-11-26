# WhatsApp OTP Telegram Bot

Multi-site OTP generation bot with admin approval system for Telegram.

## Features

- 🔐 Multi-site WhatsApp OTP generation (4 sites)
- 👥 Admin approval system
- 💰 User balance tracking (৳10 per successful number)
- 📊 Daily statistics and reports
- ⏰ Working hours management (10:30 AM - 3:00 PM Bangladesh Time)
- 🔄 Hourly reward claims
- 📱 Concurrent processing support (100+ users)
- 🗄️ PostgreSQL database (Supabase)

## Deployment

### Prerequisites

1. Telegram Bot Token (from @BotFather)
2. Supabase account with PostgreSQL database
3. Render account (free tier works)
4. GitHub account

### Step 1: Setup Supabase Database

1. Go to your Supabase project: https://sgnnqvfoajqsfdyulolm.supabase.co
2. Open SQL Editor
3. Run the SQL from `supabase_setup.sql`
4. Verify tables are created

### Step 2: Deploy to Render

1. Fork/Push this repository to GitHub
2. Go to https://dashboard.render.com
3. Click "New +" → "Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Name**: whatsapp-otp-bot (or any name)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python telegram_bot_deploy.py`
   - **Instance Type**: Free

6. Add Environment Variables:
   ```
   BOT_TOKEN=your_telegram_bot_token
   ADMIN_ID=your_telegram_user_id
   SITE_USERNAME=9475595762
   SITE_PASSWORD=raja0000
   DATABASE_URL=postgresql://postgres:53561106@Tojo@db.sgnnqvfoajqsfdyulolm.supabase.co:5432/postgres
   ```

7. Click "Create Web Service"

### Step 3: Start Bot

Render will automatically build and start your bot. Check logs for:
```
[OK] PostgreSQL connected
[OK] All sites logged in successfully
[OK] Bot started successfully!
```

## Local Development

For local development, use the original `telegram_bot.py` with SQLite:

```bash
python telegram_bot.py
```

## Bot Commands

### User Commands
- `/start` - Register/Login
- `💰 Balance` - Check balance
- `📊 My Stats` - View statistics
- `❓ Help` - Usage instructions
- Send phone number (e.g., `+8801234567890`) - Process OTP

### Admin Commands
- `/approve <user_id>` - Approve user
- `/reject <user_id>` - Reject user
- `/report` - Daily report
- `📈 Admin Panel` - Admin dashboard

## Configuration

Edit environment variables in Render dashboard:

- `BOT_TOKEN` - Your Telegram bot token
- `ADMIN_ID` - Your Telegram user ID
- `SITE_USERNAME` - Site login username
- `SITE_PASSWORD` - Site login password
- `DATABASE_URL` - PostgreSQL connection string

## Working Hours

- **Active**: 10:30 AM - 3:00 PM (Bangladesh Time)
- **Daily Reset**: 8:00 AM
- **Daily Report**: 3:00 PM
- **Hourly Rewards**: Every hour at :30 minutes

## Payment

- ৳10 per successfully linked phone number
- Must complete all 4 sites to earn payment

## Support

For issues or questions, contact the admin through Telegram.

## License

Private - All rights reserved

