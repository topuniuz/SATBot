import asyncio
import logging
from datetime import datetime, date
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
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


# ---------------------------------------------------------
# UI & KEYBOARD BUILDERS (Clean & Premium Design)
# ---------------------------------------------------------

def get_persistent_reply_keyboard() -> ReplyKeyboardMarkup:
    """Returns the persistent bottom navigation bar."""
    keyboard = [
        [KeyboardButton("📅 SAT Schedule"), KeyboardButton("⏳ Live Countdown")],
        [KeyboardButton("📝 Test-Day Tips"), KeyboardButton("🌍 Timezone")],
        [KeyboardButton("⚙️ Notification Status"), KeyboardButton("🔗 Score Portal")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_main_menu_inline_keyboard() -> InlineKeyboardMarkup:
    """Returns clean inline buttons for the main dashboard."""
    buttons = [
        [
            InlineKeyboardButton("📅 Official Schedule", callback_data="nav:schedule"),
            InlineKeyboardButton("⏳ Live Countdown", callback_data="nav:countdown"),
        ],
        [
            InlineKeyboardButton("📝 Test-Day Checklist", callback_data="nav:tips"),
            InlineKeyboardButton("🌍 Set Timezone", callback_data="nav:timezone"),
        ],
        [
            InlineKeyboardButton("⚙️ Notification Status", callback_data="nav:status"),
            InlineKeyboardButton("🔗 College Board Portal", url="https://studentscores.collegeboard.org/"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def get_subpage_inline_keyboard(current_page: str, is_subscribed: bool = True) -> InlineKeyboardMarkup:
    """Returns contextual action buttons and a back button for sub-pages."""
    buttons = []

    if current_page == "schedule":
        buttons.append([
            InlineKeyboardButton("⏳ View Countdown", callback_data="nav:countdown"),
            InlineKeyboardButton("🌍 Change Timezone", callback_data="nav:timezone"),
        ])
    elif current_page == "countdown":
        buttons.append([
            InlineKeyboardButton("🔄 Refresh Countdown", callback_data="nav:countdown"),
            InlineKeyboardButton("📅 Full Schedule", callback_data="nav:schedule"),
        ])
    elif current_page == "tips":
        buttons.append([
            InlineKeyboardButton("⏳ View Countdown", callback_data="nav:countdown"),
            InlineKeyboardButton("📅 Full Schedule", callback_data="nav:schedule"),
        ])
    elif current_page == "status":
        sub_btn = (
            InlineKeyboardButton("🔕 Pause Alerts", callback_data="action:toggle_sub")
            if is_subscribed
            else InlineKeyboardButton("🔔 Resume Alerts", callback_data="action:toggle_sub")
        )
        buttons.append([sub_btn, InlineKeyboardButton("🌍 Change Timezone", callback_data="nav:timezone")])

    # Always provide quick return to Main Menu
    buttons.append([
        InlineKeyboardButton("🏠 Main Dashboard", callback_data="nav:menu"),
        InlineKeyboardButton("🔗 College Board", url="https://studentscores.collegeboard.org/"),
    ])
    return InlineKeyboardMarkup(buttons)


def get_timezone_inline_keyboard(selected_tz: str) -> InlineKeyboardMarkup:
    """Returns clean 2-column timezone selection grid."""
    buttons = []
    row = []

    # Build 2-column layout for compact, premium look
    for label, tz_code in POPULAR_TIMEZONES:
        # Simplify label for buttons
        short_label = label.split("(")[0].strip()
        if "UTC" in label:
            short_label = "🌐 UTC"
        prefix = "✓ " if tz_code == selected_tz else ""
        btn_text = f"{prefix}{short_label}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"set_tz:{tz_code}"))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🏠 Back to Main Dashboard", callback_data="nav:menu")])
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------
# CONTENT GENERATORS
# ---------------------------------------------------------

async def get_dashboard_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user_tz = await get_user_timezone(chat_id)
    next_test = get_next_test(user_tz)
    next_score = get_next_score_release(user_tz)
    today = get_current_date(user_tz)

    next_test_str = f"{next_test['name']} ({next_test['test_date'].strftime('%b %d, %Y')})" if next_test else "None listed"
    next_score_str = f"{next_score['name']} ({next_score['score_release_date'].strftime('%b %d, %Y')})" if next_score else "None listed"

    text = (
        "✨ <b>SAT NOTIFY DASHBOARD</b> ✨\n"
        "────────────────────────\n"
        f"🌍 <b>Your Timezone:</b> <code>{user_tz}</code>\n"
        f"📅 <b>Next SAT Exam:</b> {next_test_str}\n"
        f"📢 <b>Next Score Release:</b> {next_score_str}\n\n"
        "<i>Tap any button below for instant updates, checklists, and countdowns:</i>"
    )
    return text, get_main_menu_inline_keyboard()


async def get_schedule_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user_tz = await get_user_timezone(chat_id)
    upcoming = get_upcoming_tests(limit=6, tz_name=user_tz)
    today = get_current_date(user_tz)

    if not upcoming:
        return "No upcoming SAT dates found in the schedule.", get_subpage_inline_keyboard("schedule")

    lines = [
        "📅 <b>OFFICIAL COLLEGE BOARD SAT SCHEDULE</b>\n"
        f"<i>Timezone: {user_tz}</i>\n"
        "────────────────────────\n"
    ]
    for item in upcoming:
        test_d = item["test_date"]
        score_d = item["score_release_date"]
        test_badge = "✅ <i>Finished</i>" if test_d < today else f"🗓 <b>{test_d.strftime('%b %d, %Y')}</b>"
        score_badge = "✅ <i>Released</i>" if score_d < today else f"📢 <b>{score_d.strftime('%b %d, %Y')}</b>"

        lines.append(
            f"🎓 <b>{item['name']}</b>\n"
            f"  ├ 📝 Test Date: {test_badge}\n"
            f"  └ 🎯 Score Release: {score_badge}\n"
        )

    lines.append("────────────────────────\nℹ️ <i>Dates follow the official College Board testing calendar.</i>")
    return "\n".join(lines), get_subpage_inline_keyboard("schedule")


async def get_countdown_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user_tz = await get_user_timezone(chat_id)
    today = get_current_date(user_tz)
    next_test = get_next_test(user_tz)
    next_score = get_next_score_release(user_tz)

    lines = [
        "⏳ <b>LIVE SAT COUNTDOWNS</b>\n"
        f"<i>Timezone: {user_tz}</i>\n"
        "────────────────────────\n"
    ]

    if next_test:
        days_until_test = (next_test["test_date"] - today).days
        if days_until_test == 0:
            test_str = "🔥 <b>TODAY IS EXAM DAY! Good luck!</b>"
        elif days_until_test == 1:
            test_str = "⚡ <b>1 DAY REMAINING (Tomorrow!)</b>"
        else:
            test_str = f"<b>{days_until_test} days</b> remaining"
        lines.append(
            f"📝 <b>Next SAT Exam:</b>\n"
            f"   {next_test['name']} ({next_test['test_date'].strftime('%b %d, %Y')})\n"
            f"   ↳ {test_str}\n"
        )
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
        lines.append(
            f"📢 <b>Next Score Release:</b>\n"
            f"   {next_score['name']} ({next_score['score_release_date'].strftime('%b %d, %Y')})\n"
            f"   ↳ {score_str}\n"
        )
    else:
        lines.append("📢 <b>Next Score Release:</b> No upcoming score releases listed.\n")

    lines.append("────────────────────────\n<i>Tap Refresh below for updated live stats!</i>")
    return "\n".join(lines), get_subpage_inline_keyboard("countdown")


async def get_tips_content() -> tuple[str, InlineKeyboardMarkup]:
    return TEMPLATES["tips"], get_subpage_inline_keyboard("tips")


async def get_status_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    active_subs = await get_active_subscribers()
    is_sub = chat_id in active_subs
    user_tz = await get_user_timezone(chat_id)

    status_icon = "🟢 ACTIVE" if is_sub else "🔴 PAUSED"
    msg = (
        "⚙️ <b>NOTIFICATION SETTINGS & STATUS</b>\n"
        "────────────────────────\n"
        f"📡 <b>Alert Status:</b> {status_icon}\n"
        f"🌍 <b>Your Timezone:</b> <code>{user_tz}</code>\n\n"
        "<b>Automated alerts included:</b>\n"
        "• 📅 7-Day Countdown & Bluebook setup reminder\n"
        "• 🎒 1-Day Before packing & rest checklist\n"
        "• 🌟 Exam Morning motivational good-luck message\n"
        "• 📢 Official Score Release Day announcement (Morning & Evening batches)\n\n"
        "<i>Use the buttons below to toggle alerts or change timezone:</i>"
    )
    return msg, get_subpage_inline_keyboard("status", is_subscribed=is_sub)


async def get_timezone_menu_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    current_tz = await get_user_timezone(chat_id)
    now_str = datetime.now(get_user_zoneinfo(current_tz)).strftime("%Y-%m-%d %H:%M:%S")

    text = (
        "🌍 <b>TIMEZONE PREFERENCES</b>\n"
        "────────────────────────\n"
        f"📍 <b>Active Timezone:</b> <code>{current_tz}</code>\n"
        f"🕒 <b>Current Local Time:</b> {now_str}\n\n"
        "<b>Select your timezone below:</b>\n"
        "<i>(Or type <code>/timezone &lt;City/Region&gt;</code> e.g. <code>/timezone Asia/Tashkent</code>)</i>"
    )
    return text, get_timezone_inline_keyboard(current_tz)


# ---------------------------------------------------------
# BROADCAST HELPER
# ---------------------------------------------------------

async def broadcast_message(bot, text: str, parse_mode: str = "HTML") -> tuple[int, int]:
    """Sends a message to all active subscribers with rate limiting."""
    subscribers = await get_active_subscribers()
    success = 0
    failed = 0

    for chat_id in subscribers:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_markup=get_main_menu_inline_keyboard(),
            )
            success += 1
            await asyncio.sleep(0.05)
        except (Forbidden, BadRequest) as e:
            logger.warning("Failed to send message to %s (%s). Deactivating.", chat_id, e)
            await unsubscribe_user(chat_id)
            failed += 1
        except Exception as e:
            logger.error("Unexpected error sending to %s: %s", chat_id, e)
            failed += 1

    return success, failed


# ---------------------------------------------------------
# COMMAND & MESSAGE HANDLERS
# ---------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    await add_or_reactivate_subscriber(
        chat_id=chat_id,
        username=user.username,
        first_name=user.first_name,
    )

    text, inline_kb = await get_dashboard_content(chat_id)
    # Send persistent reply keyboard AND interactive inline keyboard
    await update.message.reply_text(
        text=text,
        reply_markup=get_persistent_reply_keyboard(),
        parse_mode="HTML",
    )
    await update.message.reply_text(
        text="👇 <b>Quick Actions:</b>",
        reply_markup=inline_kb,
        parse_mode="HTML",
    )


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await get_schedule_content(update.effective_chat.id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def countdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await get_countdown_content(update.effective_chat.id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def tips_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await get_tips_content()
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await get_status_content(update.effective_chat.id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if context.args:
        custom_tz = context.args[0].strip()
        try:
            _ = get_user_zoneinfo(custom_tz)
            await set_user_timezone(chat_id, custom_tz)
            now_str = datetime.now(get_user_zoneinfo(custom_tz)).strftime("%Y-%m-%d %H:%M:%S")
            text, kb = await get_dashboard_content(chat_id)
            await update.message.reply_text(
                f"✅ <b>Timezone Updated to:</b> <code>{custom_tz}</code>\n🕒 <b>Local Time:</b> {now_str}",
                reply_markup=kb,
                parse_mode="HTML",
            )
            return
        except Exception:
            await update.message.reply_text(f"⚠️ Invalid timezone <code>{custom_tz}</code>.", parse_mode="HTML")

    text, kb = await get_timezone_menu_content(chat_id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


# ---------------------------------------------------------
# TEXT MESSAGE ROUTER (For Persistent Reply Keyboard Buttons)
# ---------------------------------------------------------

async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on persistent bottom reply keyboard buttons."""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    if text == "📅 SAT Schedule":
        msg, kb = await get_schedule_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "⏳ Live Countdown":
        msg, kb = await get_countdown_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "📝 Test-Day Tips":
        msg, kb = await get_tips_content()
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "🌍 Timezone":
        msg, kb = await get_timezone_menu_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "⚙️ Notification Status":
        msg, kb = await get_status_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "🔗 Score Portal":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Open College Board Score Portal", url="https://studentscores.collegeboard.org/")],
            [InlineKeyboardButton("🏠 Back to Dashboard", callback_data="nav:menu")],
        ])
        await update.message.reply_text(
            "🔗 <b>College Board Student Score Portal</b>\n\n"
            "Tap below to log into your official College Board account and view your SAT scores:",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        # Default: Show Main Dashboard
        msg, kb = await get_dashboard_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")


# ---------------------------------------------------------
# INLINE CALLBACK QUERY HANDLER (Seamless Navigation)
# ---------------------------------------------------------

async def inline_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes all inline button clicks for in-place page transitions."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id

    if not data:
        return

    # Navigation routing
    if data == "nav:menu":
        text, kb = await get_dashboard_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:schedule":
        text, kb = await get_schedule_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:countdown":
        text, kb = await get_countdown_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:tips":
        text, kb = await get_tips_content()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:timezone":
        text, kb = await get_timezone_menu_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:status":
        text, kb = await get_status_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "action:toggle_sub":
        active_subs = await get_active_subscribers()
        if chat_id in active_subs:
            await unsubscribe_user(chat_id)
        else:
            user = update.effective_user
            await add_or_reactivate_subscriber(chat_id, user.username, user.first_name)
        text, kb = await get_status_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data.startswith("set_tz:"):
        tz_code = data.split(":", 1)[1]
        await set_user_timezone(chat_id, tz_code)
        text, kb = await get_timezone_menu_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")


# ---------------------------------------------------------
# ADMIN COMMANDS
# ---------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Show subscriber statistics."""
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
    """Admin command: Broadcast custom message to subscribers."""
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
    """Admin command: Triggers score release broadcast."""
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


# ---------------------------------------------------------
# BACKGROUND NOTIFICATION RUNNER
# ---------------------------------------------------------

async def check_and_send_scheduled_alerts(bot):
    """Checks schedule against today's date and triggers automated alerts."""
    today = get_current_date()
    logger.info("Running scheduled alert check for date: %s", today)

    for item in SAT_SCHEDULE:
        item_id = item["id"]
        test_name = item["name"]
        test_date = item["test_date"]
        score_date = item["score_release_date"]

        days_to_test = (test_date - today).days

        # 1. Check 7 Days Before Exam
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

        # 3. Check Exam Morning
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


# ---------------------------------------------------------
# MAIN APP ENTRY POINT
# ---------------------------------------------------------

async def main():
    if not BOT_TOKEN:
        logger.error("CRITICAL: BOT_TOKEN is missing! Set BOT_TOKEN in .env or Render environment variables.")
        print("\n[!] ERROR: BOT_TOKEN is missing. Please set BOT_TOKEN in .env or environment variables.\n")
        return

    # Initialize Database & Web Server
    await init_db()
    await start_web_server()

    # Build Telegram Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("countdown", countdown_command))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(CommandHandler("tips", tips_command))
    application.add_handler(CommandHandler("status", status_command))

    # Admin Handlers
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("announce_scores", announce_scores_command))

    # Inline Button Navigation Router
    application.add_handler(CallbackQueryHandler(inline_callback_router))

    # Persistent Text Buttons Message Router
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    logger.info("Starting SAT Notify Telegram Bot with Premium UI...")

    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        scheduler_task = asyncio.create_task(background_scheduler_loop(application))
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
