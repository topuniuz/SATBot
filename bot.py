import asyncio
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import Forbidden, BadRequest

from config import (
    BOT_TOKEN,
    ADMIN_IDS,
    SAT_SCHEDULE,
    TEMPLATES,
    POPULAR_TIMEZONES,
    get_user_zoneinfo,
    get_current_date,
    get_next_test,
    get_next_score_release,
    get_upcoming_tests,
)
from database import (
    init_db,
    add_or_reactivate_subscriber,
    unsubscribe_user,
    set_user_timezone,
    get_user_timezone,
    get_active_subscribers,
    get_subscriber_stats,
    is_notification_sent,
    mark_notification_sent,
)
from web_server import start_web_server

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# Helper: Broadcast to active subscribers
async def broadcast_message(bot, text: str, parse_mode: str = "HTML") -> tuple[int, int]:
    """Sends a message to all active subscribers. Returns (success_count, failed_count)."""
    subscribers = await get_active_subscribers()
    success = 0
    failed = 0

    for chat_id in subscribers:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, disable_web_page_preview=True)
            success += 1
            await asyncio.sleep(0.05)  # Rate limiting protection
        except (Forbidden, BadRequest) as e:
            logger.warning("Failed to send message to %s (%s). Deactivating.", chat_id, e)
            await unsubscribe_user(chat_id)
            failed += 1
        except Exception as e:
            logger.error("Unexpected error sending to %s: %s", chat_id, e)
            failed += 1

    return success, failed


# User Command Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    is_new = await add_or_reactivate_subscriber(
        chat_id=chat_id,
        username=user.username,
        first_name=user.first_name,
    )

    welcome_text = TEMPLATES["welcome"]
    if not is_new:
        welcome_text += "\n\n<i>(You were already subscribed to notifications!)</i>"

    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /schedule command."""
    chat_id = update.effective_chat.id
    user_tz = await get_user_timezone(chat_id)
    upcoming = get_upcoming_tests(limit=6, tz_name=user_tz)
    today = get_current_date(user_tz)

    if not upcoming:
        await update.message.reply_text("No upcoming SAT dates found in the schedule.")
        return

    lines = [
        "📅 <b>Official College Board SAT Schedule:</b>\n"
        f"<i>(Calculated for your timezone: {user_tz})</i>\n"
    ]
    for item in upcoming:
        test_d = item["test_date"]
        score_d = item["score_release_date"]
        test_badge = "✅ Passed" if test_d < today else f"🗓 {test_d.strftime('%b %d, %Y')}"
        score_badge = "✅ Released" if score_d < today else f"📢 {score_d.strftime('%b %d, %Y')}"

        lines.append(
            f"🎓 <b>{item['name']}</b>\n"
            f"  • Exam Date: {test_badge}\n"
            f"  • Score Release: {score_badge}\n"
        )

    lines.append("<i>Dates follow official College Board testing calendar.</i>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def countdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /countdown command."""
    chat_id = update.effective_chat.id
    user_tz = await get_user_timezone(chat_id)
    today = get_current_date(user_tz)
    next_test = get_next_test(user_tz)
    next_score = get_next_score_release(user_tz)

    lines = [
        "⏳ <b>SAT Live Countdowns:</b>\n"
        f"<i>(Your Timezone: {user_tz})</i>\n"
    ]

    if next_test:
        days_until_test = (next_test["test_date"] - today).days
        if days_until_test == 0:
            test_str = "🔥 <b>TODAY IS EXAM DAY! Good luck!</b>"
        elif days_until_test == 1:
            test_str = "⚡ <b>1 DAY REMAINING (Tomorrow!)</b>"
        else:
            test_str = f"<b>{days_until_test} days</b> remaining"
        lines.append(f"📝 <b>Next SAT Exam:</b> {next_test['name']} ({next_test['test_date'].strftime('%b %d, %Y')})\n   ↳ {test_str}\n")
    else:
        lines.append("📝 <b>Next SAT Exam:</b> No upcoming exams listed.\n")

    if next_score:
        days_until_scores = (next_score["score_release_date"] - today).days
        if days_until_scores == 0:
            score_str = "🎉 <b>TODAY IS SCORE RELEASE DAY!</b>"
        elif days_until_scores == 1:
            score_str = "⚡ <b>1 DAY REMAINING (Tomorrow!)</b>"
        else:
            score_str = f"<b>{days_until_scores} days</b> remaining"
        lines.append(f"📢 <b>Next Score Release:</b> {next_score['name']} ({next_score['score_release_date'].strftime('%b %d, %Y')})\n   ↳ {score_str}\n")
    else:
        lines.append("📢 <b>Next Score Release:</b> No upcoming score releases listed.\n")

    lines.append("Use /schedule for full calendar, /timezone to change timezone, or /tips for exam checklists.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /timezone command to view and set timezone."""
    chat_id = update.effective_chat.id
    current_tz = await get_user_timezone(chat_id)

    # Check if user passed arguments: /timezone Asia/Tashkent
    if context.args:
        custom_tz = context.args[0].strip()
        try:
            # Validate timezone
            _ = get_user_zoneinfo(custom_tz)
            await set_user_timezone(chat_id, custom_tz)
            now_str = datetime.now(get_user_zoneinfo(custom_tz)).strftime("%Y-%m-%d %H:%M:%S")
            await update.message.reply_text(
                f"✅ <b>Timezone Updated!</b>\n\n"
                f"🌍 <b>Your Timezone:</b> <code>{custom_tz}</code>\n"
                f"🕒 <b>Current Time:</b> {now_str}",
                parse_mode="HTML",
            )
            return
        except Exception:
            await update.message.reply_text(
                f"⚠️ Invalid timezone <code>{custom_tz}</code>. Please select from the menu below or provide a valid IANA timezone.",
                parse_mode="HTML",
            )

    # Build Interactive Keyboard for popular timezones
    buttons = []
    for label, tz_code in POPULAR_TIMEZONES:
        prefix = "✅ " if tz_code == current_tz else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"set_tz:{tz_code}")])

    keyboard = InlineKeyboardMarkup(buttons)
    now_str = datetime.now(get_user_zoneinfo(current_tz)).strftime("%Y-%m-%d %H:%M:%S")

    text = (
        "🌍 <b>Select Your Timezone</b>\n\n"
        f"Current Timezone: <b>{current_tz}</b>\n"
        f"Local Time: <b>{now_str}</b>\n\n"
        "Tap a timezone below to update, or type:\n"
        "<code>/timezone &lt;Timezone_Name&gt;</code> (e.g. <code>/timezone Asia/Tashkent</code>)"
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def timezone_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles timezone inline button selections."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data or not data.startswith("set_tz:"):
        return

    tz_code = data.split(":", 1)[1]
    chat_id = update.effective_chat.id

    await set_user_timezone(chat_id, tz_code)
    now_str = datetime.now(get_user_zoneinfo(tz_code)).strftime("%Y-%m-%d %H:%M:%S")

    # Re-render keyboard with updated checkmark
    buttons = []
    for label, code in POPULAR_TIMEZONES:
        prefix = "✅ " if code == tz_code else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"set_tz:{code}")])

    keyboard = InlineKeyboardMarkup(buttons)

    text = (
        "🌍 <b>Timezone Updated Successfully!</b>\n\n"
        f"Selected Timezone: <b>{tz_code}</b>\n"
        f"Current Local Time: <b>{now_str}</b>\n\n"
        "Tap below to change anytime, or use /countdown to check SAT dates."
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def tips_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /tips command."""
    await update.message.reply_text(TEMPLATES["tips"], parse_mode="HTML")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /status command."""
    chat_id = update.effective_chat.id
    active_subs = await get_active_subscribers()
    is_sub = chat_id in active_subs
    user_tz = await get_user_timezone(chat_id)

    status_str = "ACTIVE 🔔" if is_sub else "PAUSED 🔕"
    msg = (
        f"⚙️ <b>Your Notification Status: {status_str}</b>\n"
        f"🌍 <b>Active Timezone:</b> <code>{user_tz}</code> (change with /timezone)\n\n"
        "<b>Automated alerts you receive:</b>\n"
        "• 7-day test preparation reminders & Bluebook setup\n"
        "• 1-day before test checklist (ID, calculator, charger)\n"
        "• Exam morning good luck wishes\n"
        "• Official Score release day morning announcements\n\n"
        f"{'To pause alerts, type /unsubscribe' if is_sub else 'To resume alerts, type /subscribe'}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /subscribe command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    await add_or_reactivate_subscriber(chat_id, user.username, user.first_name)
    await update.message.reply_text(
        "🔔 <b>Subscribed!</b> You will now receive SAT exam reminders, good luck wishes, and score release alerts.",
        parse_mode="HTML",
    )


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /unsubscribe command."""
    chat_id = update.effective_chat.id
    await unsubscribe_user(chat_id)
    await update.message.reply_text(
        "🔕 <b>Unsubscribed.</b> You will no longer receive automated notifications. You can resume anytime with /subscribe.",
        parse_mode="HTML",
    )


# Admin Handlers
def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Show subscriber count."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    stats = await get_subscriber_stats()
    msg = (
        f"📊 <b>Bot Statistics:</b>\n"
        f"• Active Subscribers: <b>{stats.get('active', 0)}</b>\n"
        f"• Total Registered Users: <b>{stats.get('total', 0)}</b>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /broadcast <message> sends text to all active subscribers."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <Your message here>")
        return

    text = update.message.text.partition(" ")[2].strip()
    status_msg = await update.message.reply_text("🚀 Starting broadcast...")

    success, failed = await broadcast_message(context.bot, text)
    await status_msg.edit_text(
        f"✅ <b>Broadcast Completed:</b>\n"
        f"• Successfully sent: {success}\n"
        f"• Failed/Removed: {failed}",
        parse_mode="HTML",
    )


async def announce_scores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /announce_scores [SAT Name] triggers instant score release announcement."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    test = get_next_score_release()
    test_name = " ".join(context.args) if context.args else (test["name"] if test else "Recent SAT")
    release_date_str = get_current_date().strftime("%B %d, %Y")

    announcement = TEMPLATES["score_release_morning"].format(
        test_name=test_name,
        release_date=release_date_str,
    )

    status_msg = await update.message.reply_text(f"🚀 Broadcasting score release announcement for <b>{test_name}</b>...", parse_mode="HTML")
    success, failed = await broadcast_message(context.bot, announcement)
    await status_msg.edit_text(
        f"✅ <b>Score Announcement Sent:</b>\n"
        f"• Sent to: {success} subscribers\n"
        f"• Failed: {failed}",
        parse_mode="HTML",
    )


async def test_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /test_alert <7days|1day|morning|scores> sends a preview of the alert to the admin only."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    alert_type = context.args[0].lower() if context.args else "morning"
    next_test = get_next_test() or {"name": "Upcoming SAT", "test_date": date(2025, 5, 3), "score_release_date": date(2025, 5, 16)}

    if alert_type == "7days":
        text = TEMPLATES["exam_7days"].format(
            test_name=next_test["name"],
            test_date=next_test["test_date"].strftime("%A, %B %d, %Y"),
        )
    elif alert_type == "1day":
        text = TEMPLATES["exam_1day"].format(
            test_name=next_test["name"],
            test_date=next_test["test_date"].strftime("%A, %B %d, %Y"),
        )
    elif alert_type == "scores":
        text = TEMPLATES["score_release_morning"].format(
            test_name=next_test["name"],
            release_date=next_test["score_release_date"].strftime("%A, %B %d, %Y"),
        )
    else:  # morning
        text = TEMPLATES["exam_morning"].format(
            test_name=next_test["name"],
            test_date=next_test["test_date"].strftime("%A, %B %d, %Y"),
        )

    await update.message.reply_text(f"🔍 <i>[PREVIEW ONLY - Type: {alert_type}]</i>\n\n" + text, parse_mode="HTML")


# Automated Notification Background Runner
async def check_and_send_scheduled_alerts(bot):
    """Checks schedule against today's date and triggers automated alerts."""
    today = get_current_date()
    logger.info("Running scheduled alert check for date: %s", today)

    for item in SAT_SCHEDULE:
        item_id = item["id"]
        test_name = item["name"]
        test_date = item["test_date"]
        score_date = item["score_release_date"]

        # 1. Check 7 Days Before Exam
        days_to_test = (test_date - today).days
        if days_to_test == 7:
            event_key = f"{item_id}_7days"
            if not await is_notification_sent(event_key):
                logger.info("Triggering 7-day reminder for %s", test_name)
                msg = TEMPLATES["exam_7days"].format(
                    test_name=test_name,
                    test_date=test_date.strftime("%A, %B %d, %Y"),
                )
                success, _ = await broadcast_message(bot, msg)
                await mark_notification_sent(event_key, success)

        # 2. Check 1 Day Before Exam
        elif days_to_test == 1:
            event_key = f"{item_id}_1day"
            if not await is_notification_sent(event_key):
                logger.info("Triggering 1-day reminder for %s", test_name)
                msg = TEMPLATES["exam_1day"].format(
                    test_name=test_name,
                    test_date=test_date.strftime("%A, %B %d, %Y"),
                )
                success, _ = await broadcast_message(bot, msg)
                await mark_notification_sent(event_key, success)

        # 3. Check Exam Morning (Day 0)
        elif days_to_test == 0:
            event_key = f"{item_id}_exam_morning"
            if not await is_notification_sent(event_key):
                logger.info("Triggering Exam Morning good luck message for %s", test_name)
                msg = TEMPLATES["exam_morning"].format(
                    test_name=test_name,
                    test_date=test_date.strftime("%A, %B %d, %Y"),
                )
                success, _ = await broadcast_message(bot, msg)
                await mark_notification_sent(event_key, success)

        # 4. Check Score Release Day
        days_to_scores = (score_date - today).days
        if days_to_scores == 0:
            event_key = f"{item_id}_score_release_day"
            if not await is_notification_sent(event_key):
                logger.info("Triggering Score Release Announcement for %s", test_name)
                msg = TEMPLATES["score_release_morning"].format(
                    test_name=test_name,
                    release_date=score_date.strftime("%A, %B %d, %Y"),
                )
                success, _ = await broadcast_message(bot, msg)
                await mark_notification_sent(event_key, success)


async def background_scheduler_loop(application):
    """Runs periodic checks in the background every 30 minutes."""
    while True:
        try:
            await check_and_send_scheduled_alerts(application.bot)
        except Exception as e:
            logger.error("Error in background scheduler loop: %s", e)
        await asyncio.sleep(1800)


async def main():
    if not BOT_TOKEN:
        logger.error("CRITICAL: BOT_TOKEN environment variable is missing! Please set BOT_TOKEN in .env or your host environment.")
        print("\n[!] ERROR: BOT_TOKEN is missing. Please set your Telegram bot token in .env or environment variables.\n")
        return

    # Initialize Database
    await init_db()

    # Start Health Check Web Server for Render hosting
    await start_web_server()

    # Build Telegram Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("countdown", countdown_command))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(CommandHandler("tips", tips_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))

    # Add Callback Query Handlers (for interactive timezone buttons)
    application.add_handler(CallbackQueryHandler(timezone_callback_handler, pattern=r"^set_tz:"))

    # Add Admin Handlers
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("announce_scores", announce_scores_command))
    application.add_handler(CommandHandler("test_alert", test_alert_command))

    logger.info("Starting SAT Notify Telegram Bot...")

    # Initialize and start polling
    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        # Start Background Scheduler
        scheduler_task = asyncio.create_task(background_scheduler_loop(application))

        # Keep running
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        finally:
            await application.updater.stop()
            await application.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
