# 🎓 SAT Notification & Score Release Telegram Bot

An automated Telegram bot that sends reminders, test-day checklists, and good luck wishes before SAT exams, and notifies students when College Board releases SAT scores. Ready to deploy for **free** on [Render.com](https://render.com).

---

## ✨ Features

- 📢 **Automated Score Release Alerts**: Sends immediate announcements on score release days (with morning and evening release batch reminders).
- 🌟 **Test-Day Motivation & Reminders**:
  - **7 Days Before Exam**: Bluebook setup checklist & registration reminders.
  - **1 Day Before Exam**: Night-before checklist (photo ID, calculator, device charger, rest).
  - **Exam Morning**: Motivational good-luck message.
- 📅 **Interactive Commands**:
  - `/start` - Subscribe to alerts and get the welcome guide.
  - `/schedule` - View full calendar of upcoming SAT test dates and expected score release dates.
  - `/countdown` - Live countdown to the next SAT and the next score release.
  - `/tips` - Digital SAT test-day checklist, pacing tips, and Bluebook advice.
  - `/status` - Check your subscription status.
  - `/subscribe` & `/unsubscribe` - Manage notification preferences.
- 👑 **Admin Commands** (for bot owner):
  - `/broadcast <message>` - Send custom announcements to all active subscribers.
  - `/announce_scores [SAT Name]` - Instantly trigger a score release broadcast.
  - `/test_alert <7days|1day|morning|scores>` - Preview alert templates in your private chat.
  - `/stats` - View active and total subscriber counts.
- ⚡ **Hosting Optimized**:
  - Built-in lightweight health-check web server on port `8080` (allows free hosting on Render, Railway, Fly.io, etc.).
  - Deduplication engine ensures users never receive duplicate alerts for the same event.

---

## 🚀 Quick Setup Guide

### 1. Get a Telegram Bot Token
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the instructions to name your bot and choose a username (must end in `bot`, e.g. `sat_score_notify_bot`).
3. Copy the **HTTP API Token** provided by BotFather (looks like `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

### 2. (Optional) Get Your Admin User ID
1. Search for [@userinfobot](https://t.me/userinfobot) on Telegram.
2. Send any message to get your numeric `Id` (e.g. `123456789`).
3. This allows you to use admin commands like `/broadcast` and `/announce_scores`.

---

## 💻 Local Development

### 1. Install Dependencies
```bash
# Clone or navigate to the directory
cd "sat notify"

# Create a virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file from the `.env.example` template:
```bash
cp .env.example .env
```
Open `.env` and fill in your details:
```env
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_USER_ID=your_telegram_user_id
PORT=8080
TIMEZONE=US/Eastern
```

### 3. Run the Bot
```bash
python bot.py
```
Open your bot in Telegram and send `/start`!

---

## 🌐 Deploy to Render.com (100% Free)

[Render](https://render.com) provides free web services that run Python applications with zero maintenance.

### Step 1: Push Code to GitHub
1. Create a new repository on GitHub.
2. Push your project:
   ```bash
   git init
   git add .
   git commit -m "Initial commit for SAT notify bot"
   git branch -M main
   git remote add origin https://github.com/topuniuz/SATBot.git
   git push -u origin main
   ```

### Step 2: Create a Web Service on Render
1. Log in to [Render Dashboard](https://dashboard.render.com).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository.
4. Fill in the service configuration:
   - **Name**: `sat-notify-bot`
   - **Language**: `Python 3`
   - **Region**: Closest to you (e.g., Oregon or Frankfurt)
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
   - **Instance Type**: `Free`
5. Under **Environment Variables**, add:
   - `BOT_TOKEN`: Your Telegram bot token from `@BotFather`
   - `ADMIN_USER_ID`: Your Telegram numeric user ID
   - `TIMEZONE`: `US/Eastern`
   - `PORT`: `8080`
6. Click **Create Web Service**.

### Step 3: Keep-Alive Tip (Optional for 24/7 Free Hosting)
Render free web services may sleep after 15 minutes of no HTTP requests. Because the bot includes a lightweight `/health` endpoint:
1. Copy your Render web service URL (e.g. `https://sat-notify-bot.onrender.com`).
2. Go to a free monitoring service like [UptimeRobot](https://uptimerobot.com) or [cron-job.org](https://cron-job.org).
3. Add a new HTTP monitor pointing to `https://sat-notify-bot.onrender.com/health` with a 5-10 minute interval.
4. Your bot will remain awake and active 24/7 at $0 cost!

---

## 📁 Project Structure

```
sat notify/
├── bot.py               # Main bot logic, command handlers, and background scheduler
├── config.py            # SAT schedule calendar, templates, and timezone configuration
├── database.py          # SQLite database layer for subscriber and alert deduplication
├── web_server.py        # aiohttp server providing / and /health endpoints
├── requirements.txt     # Python package dependencies
├── render.yaml          # Render.com Blueprint configuration
├── Procfile             # Process file for Render / Heroku
├── Dockerfile           # Container configuration
├── .env.example         # Environment variables template
└── README.md            # Documentation and deployment instructions
```

---

## 🛠 Adding / Updating SAT Dates

To add new testing seasons or update test dates:
1. Open [config.py](config.py).
2. Add the new date object to `SAT_SCHEDULE`:
   ```python
   {
       "id": "sat_2027_08",
       "name": "August 2027 SAT",
       "test_date": date(2027, 8, 28),
       "score_release_date": date(2027, 9, 10),
   }
   ```
3. Commit and push to GitHub — Render will automatically redeploy!
