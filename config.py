import os
from datetime import datetime, date
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from datetime import timezone as ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin User ID (optional, allows admin-only broadcast commands)
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()
ADMIN_IDS = [int(i.strip()) for i in ADMIN_USER_ID.split(",") if i.strip().isdigit()]

# Server Port (for Render web service / health check)
PORT = int(os.getenv("PORT", "8080"))

# Timezone (College Board releases scores in US/Eastern)
TIMEZONE_NAME = os.getenv("TIMEZONE", "US/Eastern")
try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception:
    import datetime
    TIMEZONE = datetime.timezone.utc

# SQLite Database path
DB_PATH = os.getenv("DB_PATH", "sat_bot.db")

# Official College Board SAT Testing & Score Release Schedule
# Source: https://satsuite.collegeboard.org/scores/score-release-dates & https://satsuite.collegeboard.org/sat/dates-deadlines
SAT_SCHEDULE = [
    # 2026 - 2027 Official College Board Testing Year
    {
        "id": "sat_2026_08",
        "name": "August 2026 SAT",
        "test_date": date(2026, 8, 22),
        "score_release_date": date(2026, 9, 4),
        "registration_deadline": date(2026, 8, 7),
    },
    {
        "id": "sat_2026_09",
        "name": "September 2026 SAT",
        "test_date": date(2026, 9, 12),
        "score_release_date": date(2026, 9, 25),
        "registration_deadline": date(2026, 8, 28),
    },
    {
        "id": "sat_2026_10",
        "name": "October 2026 SAT",
        "test_date": date(2026, 10, 3),
        "score_release_date": date(2026, 10, 16),
        "registration_deadline": date(2026, 9, 18),
    },
    {
        "id": "sat_2026_11",
        "name": "November 2026 SAT",
        "test_date": date(2026, 11, 7),
        "score_release_date": date(2026, 11, 20),
        "registration_deadline": date(2026, 10, 23),
    },
    {
        "id": "sat_2026_12",
        "name": "December 2026 SAT",
        "test_date": date(2026, 12, 5),
        "score_release_date": date(2026, 12, 18),
        "registration_deadline": date(2026, 11, 20),
    },
    {
        "id": "sat_2027_03",
        "name": "March 2027 SAT",
        "test_date": date(2027, 3, 6),
        "score_release_date": date(2027, 3, 19),
        "registration_deadline": date(2027, 2, 19),
    },
    {
        "id": "sat_2027_05",
        "name": "May 2027 SAT",
        "test_date": date(2027, 5, 1),
        "score_release_date": date(2027, 5, 14),
        "registration_deadline": date(2027, 4, 16),
    },
    {
        "id": "sat_2027_06",
        "name": "June 2027 SAT",
        "test_date": date(2027, 6, 5),
        "score_release_date": date(2027, 6, 18),
        "registration_deadline": date(2027, 5, 21),
    },
    # 2027 - 2028 Anticipated College Board Dates
    {
        "id": "sat_2027_08",
        "name": "August 2027 SAT",
        "test_date": date(2027, 8, 28),
        "score_release_date": date(2027, 9, 10),
    },
    {
        "id": "sat_2027_09",
        "name": "September 2027 SAT",
        "test_date": date(2027, 9, 18),
        "score_release_date": date(2027, 10, 1),
    },
    {
        "id": "sat_2027_10",
        "name": "October 2027 SAT",
        "test_date": date(2027, 10, 2),
        "score_release_date": date(2027, 10, 15),
    },
    {
        "id": "sat_2027_11",
        "name": "November 2027 SAT",
        "test_date": date(2027, 11, 6),
        "score_release_date": date(2027, 11, 19),
    },
    {
        "id": "sat_2027_12",
        "name": "December 2027 SAT",
        "test_date": date(2027, 12, 4),
        "score_release_date": date(2027, 12, 17),
    },
    {
        "id": "sat_2028_03",
        "name": "March 2028 SAT",
        "test_date": date(2028, 3, 4),
        "score_release_date": date(2028, 3, 17),
    },
    {
        "id": "sat_2028_05",
        "name": "May 2028 SAT",
        "test_date": date(2028, 5, 6),
        "score_release_date": date(2028, 5, 19),
    },
    {
        "id": "sat_2028_06",
        "name": "June 2028 SAT",
        "test_date": date(2028, 6, 3),
        "score_release_date": date(2028, 6, 16),
    },
]


# Popular timezones for user selection
POPULAR_TIMEZONES = [
    ("🇺🇸 US Eastern (New York, ET)", "US/Eastern"),
    ("🇺🇸 US Central (Chicago, CT)", "US/Central"),
    ("🇺🇸 US Mountain (Denver, MT)", "US/Mountain"),
    ("🇺🇸 US Pacific (LA, PT)", "US/Pacific"),
    ("🇬🇧 UK / London (GMT/BST)", "Europe/London"),
    ("🇪🇺 Central Europe (Paris, Berlin)", "Europe/Paris"),
    ("🇹🇷 Turkey (Istanbul)", "Europe/Istanbul"),
    ("🇦🇪 UAE (Dubai, GST)", "Asia/Dubai"),
    ("🇺🇿 Uzbekistan (Tashkent, UZT)", "Asia/Tashkent"),
    ("🇰🇿 Kazakhstan (Almaty, ALMT)", "Asia/Almaty"),
    ("🇵🇰 Pakistan (Karachi, PKT)", "Asia/Karachi"),
    ("🇮🇳 India (Kolkata, IST)", "Asia/Kolkata"),
    ("🇦🇿 Azerbaijan (Baku, AZT)", "Asia/Baku"),
    ("🇸🇬 Singapore (SGT)", "Asia/Singapore"),
    ("🇰🇷 Korea / Japan (KST/JST)", "Asia/Seoul"),
    ("🌐 UTC", "UTC"),
]


def get_user_zoneinfo(tz_name: str):
    """Safely returns ZoneInfo for a timezone string, falling back to US/Eastern."""
    try:
        return ZoneInfo(tz_name)
    except Exception:
        try:
            return ZoneInfo("US/Eastern")
        except Exception:
            import datetime
            return datetime.timezone.utc


def get_current_date(tz_name: str = None) -> date:
    """Returns today's date in specified timezone or default US/Eastern."""
    tz = get_user_zoneinfo(tz_name) if tz_name else TIMEZONE
    return datetime.now(tz).date()


def get_next_test(tz_name: str = None) -> dict | None:
    """Returns the next upcoming SAT test event."""
    today = get_current_date(tz_name)
    for item in SAT_SCHEDULE:
        if item["test_date"] >= today:
            return item
    return None


def get_next_score_release(tz_name: str = None) -> dict | None:
    """Returns the next upcoming score release event."""
    today = get_current_date(tz_name)
    for item in SAT_SCHEDULE:
        if item["score_release_date"] >= today:
            return item
    return None


def get_upcoming_tests(limit: int = 5, tz_name: str = None) -> list[dict]:
    """Returns a list of upcoming tests starting from today."""
    today = get_current_date(tz_name)
    upcoming = [item for item in SAT_SCHEDULE if item["test_date"] >= today or item["score_release_date"] >= today]
    return upcoming[:limit]


# Notification Message Templates
TEMPLATES = {
    "welcome": (
        "👋 <b>Welcome to SAT Notify Bot!</b>\n\n"
        "I will keep you updated with:\n"
        "✨ <b>Good luck wishes & test-day checklist</b> before every SAT exam\n"
        "📢 <b>Instant score release alerts</b> on official College Board release days\n"
        "⏳ <b>Live countdowns</b> to upcoming SAT exams\n\n"
        "<b>Available Commands:</b>\n"
        "📅 /schedule - View official College Board SAT dates\n"
        "⏳ /countdown - Countdown to next exam & score release\n"
        "🌍 /timezone - Change your personal timezone\n"
        "📝 /tips - Essential Digital SAT test-day checklist\n"
        "⚙️ /status - Check your notification status\n"
        "🔕 /unsubscribe - Pause notifications\n"
        "🔔 /subscribe - Resume notifications\n\n"
        "<i>You are automatically subscribed to all alerts!</i>"
    ),
    "exam_7days": (
        "📅 <b>7 Days Until the {test_name}!</b>\n\n"
        "🗓 <b>Exam Date:</b> {test_date}\n\n"
        "<b>Checklist for this week:</b>\n"
        "✅ Update and log into the <b>Bluebook™</b> app on your testing device.\n"
        "✅ Download your exam setup in Bluebook (opens 5 days before test).\n"
        "✅ Print or save your <b>Admission Ticket</b>.\n"
        "✅ Take one final timed practice module on Bluebook.\n"
        "✅ Make sure your approved calculator and photo ID are ready.\n\n"
        "<i>Stay calm, study smart, and get plenty of rest this week! 💪</i>"
    ),
    "exam_1day": (
        "⚡ <b>Tomorrow is the {test_name}!</b>\n\n"
        "🗓 <b>Exam Date:</b> {test_date}\n\n"
        "🎒 <b>Night-Before Checklist:</b>\n"
        "1. 🔋 <b>Fully charge your laptop/tablet</b> and pack the charging cord.\n"
        "2. 🪪 <b>Government-issued or School Photo ID</b>.\n"
        "3. 🎟 <b>Printed Admission Ticket</b> from Bluebook.\n"
        "4. 🧮 <b>Approved Calculator</b> (with fresh batteries).\n"
        "5. ✏️ <b>Pen/Pencil</b> for scratch paper.\n"
        "6. 💧 Water bottle and a snack for the 10-minute break.\n\n"
        "🛌 <i>Put the prep books away, drink water, and get 8+ hours of sleep. You have prepared for this! Good luck! 🌟</i>"
    ),
    "exam_morning": (
        "🌟 <b>GOOD LUCK ON YOUR SAT TODAY!</b> 🌟\n\n"
        "Today is the <b>{test_name}</b> ({test_date}).\n\n"
        "✨ <b>Final Reminders for this morning:</b>\n"
        "• Eat a good, protein-rich breakfast 🍳\n"
        "• Arrive at the test center by <b>7:45 AM</b> (doors close promptly at 8:00 AM)\n"
        "• Double check your bag for: Device + Charger, Photo ID, Admission Ticket, Calculator\n"
        "• Remember: Take deep breaths. If a question is tough, flag it, move on, and return later.\n\n"
        "<b>You've got this! Go crush that score! 🚀💯</b>"
    ),
    "score_release_morning": (
        "📢 <b>SAT SCORES ARE RELEASING TODAY!</b> 📢\n\n"
        "🎉 College Board is releasing scores for the <b>{test_name}</b> today ({release_date})!\n\n"
        "ℹ️ <b>Release Batches:</b>\n"
        "• 🌅 <b>Batch 1:</b> ~6:00 AM – 8:00 AM ET\n"
        "• 🌇 <b>Batch 2:</b> ~6:00 PM – 8:00 PM ET\n\n"
        "🔗 <b>Check Your Score:</b>\n"
        "👉 <a href='https://studentscores.collegeboard.org/'>College Board Student Score Portal</a>\n\n"
        "<i>Best of luck on your scores! 🎯💯</i>"
    ),
    "early_score_release": (
        "🚨 <b>SAT SCORES RELEASED EARLY!</b> 🚨\n\n"
        "⚡ Scores for the <b>{test_name}</b> have just been made available early by College Board!\n\n"
        "🔗 <b>Check Your Score Now:</b>\n"
        "👉 <a href='https://studentscores.collegeboard.org/'>College Board Student Score Portal</a>\n\n"
        "<i>Good luck! Go check your portal now! 🚀🎉</i>"
    ),
    "tips": (
        "📝 <b>Digital SAT Test-Day Tips & Checklist</b>\n\n"
        "<b>Device & Bluebook™ Setup:</b>\n"
        "• Complete the exam setup in Bluebook 1-5 days before exam.\n"
        "• Bring your device fully charged + charging cable.\n"
        "• Bluebook has a built-in Desmos graphing calculator!\n\n"
        "<b>What to Bring:</b>\n"
        "• Photo ID (Passport, Driver's License, or School ID)\n"
        "• Printed/Digital Admission Ticket from Bluebook\n"
        "• Approved backup calculator\n"
        "• Pencils/pens for scratch paper (center provides paper)\n"
        "• Snack & water for the 10-minute break\n\n"
        "<b>Pacing Strategies:</b>\n"
        "• <b>Reading & Writing:</b> 2 modules, 32 mins each (27 questions per module). Average ~1 min 11s per question.\n"
        "• <b>Math:</b> 2 modules, 35 mins each (22 questions per module). Average ~1 min 35s per question.\n"
        "• Never leave an answer blank — there is no penalty for guessing!\n"
        "• Flag questions you are unsure about and come back before time expires."
    ),
}
