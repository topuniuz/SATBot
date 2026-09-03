import os
import asyncio
import logging
from datetime import datetime, date
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    InlineQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from telegram.error import Forbidden, BadRequest

from config import (
    BOT_TOKEN,
    ADMIN_IDS,
    ADMIN_CONTACT,
    SAT_SCHEDULE,
    TEMPLATES,
    POPULAR_TIMEZONES,
    get_user_zoneinfo,
    get_current_date,
    get_next_test,
    get_next_score_release,
    get_upcoming_tests,
    custom_emoji,
)
import io
from database import (
    init_db,
    add_or_reactivate_subscriber,
    unsubscribe_user,
    reactivate_all_subscribers,
    set_user_timezone,
    get_user_timezone,
    get_active_subscribers,
    get_all_subscribers,
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

def get_persistent_reply_keyboard(is_user_admin: bool = False) -> ReplyKeyboardMarkup:
    """Returns the persistent bottom navigation bar."""
    keyboard = [
        [KeyboardButton("📅 SAT Schedule"), KeyboardButton("⏳ Live Countdown")],
        [KeyboardButton("📝 Test-Day Tips"), KeyboardButton("🌍 Timezone")],
        [KeyboardButton("📚 SAT Tutors & Prep"), KeyboardButton("💬 Contact Support")],
    ]
    if is_user_admin:
        keyboard.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_admin_panel_inline_keyboard() -> InlineKeyboardMarkup:
    """Returns interactive inline buttons for Admin Control Panel."""
    buttons = [
        [
            InlineKeyboardButton("📊 Live Subscriber Stats", callback_data="admin:stats"),
            InlineKeyboardButton("👥 View All Users", callback_data="admin:users"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast Message", callback_data="admin:broadcast_prompt"),
            InlineKeyboardButton("🚀 Announce Scores Now", callback_data="admin:announce_scores"),
        ],
        [
            InlineKeyboardButton("🧪 Send Test Score Alert", callback_data="admin:test_scores_menu"),
            InlineKeyboardButton("🔍 Check CB Live Feed", callback_data="admin:check_cb"),
        ],
        [
            InlineKeyboardButton("🧪 Test 7-Day Alert", callback_data="admin:test_7d"),
            InlineKeyboardButton("🧪 Test 1-Day Alert", callback_data="admin:test_1d"),
        ],
        [
            InlineKeyboardButton("🧪 Test Exam Morning", callback_data="admin:test_morning"),
            InlineKeyboardButton("⚡ Test Scores Tomorrow", callback_data="admin:test_score_1d"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def get_timezone_inline_keyboard(selected_tz: str) -> InlineKeyboardMarkup:
    """Returns clean 2-column timezone selection grid."""
    buttons = []
    row = []

    # Build 2-column layout for compact, clean look
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

    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------
# CONTENT GENERATORS
# ---------------------------------------------------------

async def get_dashboard_content(chat_id: int) -> str:
    user_tz = await get_user_timezone(chat_id)
    next_test = get_next_test(user_tz)
    next_score = get_next_score_release(user_tz)

    next_test_str = f"{next_test['name']} ({next_test['test_date'].strftime('%b %d, %Y')})" if next_test else "None listed"
    next_score_str = f"{next_score['name']} ({next_score['score_release_date'].strftime('%b %d, %Y')})" if next_score else "None listed"

    return (
        f"{custom_emoji('sparkles', '✨')} <b>SAT Notify Dashboard</b>\n\n"
        f"{custom_emoji('globe', '🌍')} <b>Timezone:</b> <code>{user_tz}</code>\n"
        f"{custom_emoji('calendar', '📅')} <b>Next Exam:</b> {next_test_str}\n"
        f"{custom_emoji('megaphone', '📢')} <b>Next Scores:</b> {next_score_str}\n\n"
        "<i>Use the menu buttons below to check schedules, live countdowns, tips, and settings.</i>"
    )


async def get_admin_panel_content() -> tuple[str, InlineKeyboardMarkup]:
    stats = await get_subscriber_stats()
    next_test = get_next_test()
    next_scores = get_next_score_release()

    text = (
        f"{custom_emoji('crown', '👑')} <b>Admin Control Panel</b>\n\n"
        f"{custom_emoji('stats', '📊')} <b>Active Subscribers:</b> <code>{stats.get('active', 0)}</code>\n"
        f"{custom_emoji('users', '👥')} <b>Total Users:</b> <code>{stats.get('total', 0)}</code>\n"
        f"{custom_emoji('calendar', '📅')} <b>Next Test:</b> {next_test['name'] if next_test else 'None'}\n"
        f"{custom_emoji('megaphone', '📢')} <b>Next Score Date:</b> {next_scores['score_release_date'] if next_scores else 'None'}\n\n"
        "<b>Actions:</b>\n"
        "• <b>Stats:</b> View real-time database counts\n"
        "• <b>Broadcast:</b> Send a message to all users\n"
        "• <b>Announce Scores:</b> Trigger score release alert\n"
        "• <b>Check CB Feed:</b> Test live College Board API\n"
        "• <b>Test Alerts:</b> Preview templates"
    )
    return text, get_admin_panel_inline_keyboard()


async def get_schedule_content(chat_id: int) -> str:
    user_tz = await get_user_timezone(chat_id)
    upcoming = get_upcoming_tests(limit=6, tz_name=user_tz)
    today = get_current_date(user_tz)

    if not upcoming:
        return "No upcoming SAT dates found in the schedule."

    lines = [
        f"{custom_emoji('calendar', '📅')} <b>Official SAT Schedule</b>\n"
        f"<i>Timezone: {user_tz}</i>\n"
    ]
    for item in upcoming:
        test_d = item["test_date"]
        score_d = item["score_release_date"]
        test_badge = "<i>Finished</i>" if test_d < today else f"<b>{test_d.strftime('%b %d, %Y')}</b>"
        score_badge = "<i>Released</i>" if score_d < today else f"<b>{score_d.strftime('%b %d, %Y')}</b>"

        lines.append(
            f"{custom_emoji('grad', '🎓')} <b>{item['name']}</b>\n"
            f"  • Test Date: {test_badge}\n"
            f"  • Score Release: {score_badge}\n"
        )

    lines.append(f"{custom_emoji('info', 'ℹ️')} <i>Dates follow the official College Board calendar.</i>")
    return "\n".join(lines)


async def get_countdown_content(chat_id: int) -> str:
    user_tz = await get_user_timezone(chat_id)
    today = get_current_date(user_tz)
    next_test = get_next_test(user_tz)
    next_score = get_next_score_release(user_tz)

    lines = [
        f"{custom_emoji('countdown', '⏳')} <b>Live SAT Countdowns</b>\n"
        f"<i>Timezone: {user_tz}</i>\n"
    ]

    if next_test:
        days_until_test = (next_test["test_date"] - today).days
        if days_until_test == 0:
            test_str = "🔥 <b>TODAY IS EXAM DAY!</b>"
        elif days_until_test == 1:
            test_str = "⚡ <b>Tomorrow!</b>"
        else:
            test_str = f"<b>{days_until_test} days</b> remaining"
        lines.append(
            f"{custom_emoji('checklist', '📝')} <b>Next SAT Exam:</b>\n"
            f"   {next_test['name']} ({next_test['test_date'].strftime('%b %d, %Y')})\n"
            f"   ↳ {test_str}\n"
        )
    else:
        lines.append(f"{custom_emoji('checklist', '📝')} <b>Next SAT Exam:</b> No upcoming exams listed.\n")

    if next_score:
        days_until_scores = (next_score["score_release_date"] - today).days
        if days_until_scores == 0:
            score_str = "🎉 <b>TODAY IS SCORE RELEASE DAY!</b>"
        elif days_until_scores == 1:
            score_str = "⚡ <b>Tomorrow!</b>"
        else:
            score_str = f"<b>{days_until_scores} days</b> remaining"
        lines.append(
            f"{custom_emoji('megaphone', '📢')} <b>Next Score Release:</b>\n"
            f"   {next_score['name']} ({next_score['score_release_date'].strftime('%b %d, %Y')})\n"
            f"   ↳ {score_str}\n"
        )
    else:
        lines.append(f"{custom_emoji('megaphone', '📢')} <b>Next Score Release:</b> No upcoming score releases listed.\n")

    return "\n".join(lines)


async def get_tips_content() -> str:
    return TEMPLATES["tips"]


async def get_tutors_content() -> str:
    contact_handle = ADMIN_CONTACT.lstrip('@')
    return (
        f"{custom_emoji('books', '📚')} <b>SAT Prep & Recommended Resources</b>\n\n"
        f"{custom_emoji('target', '🎯')} <b>Official Free Practice:</b>\n"
        "• <b><a href=\"https://bluebook.collegeboard.org/\">Bluebook™ App</a>:</b> 6 Official adaptive practice exams\n"
        "• <b><a href=\"https://www.khanacademy.org/digital-sat\">Khan Academy</a>:</b> Official Digital SAT prep course\n"
        "• <b><a href=\"https://satsuitequestionbank.collegeboard.org/\">Question Bank</a>:</b> 3,000+ real practice questions\n\n"
        f"{custom_emoji('tutor', '👨‍🏫')} <b>Featured SAT Tutors & Channels:</b>\n"
        "• Partner with us to feature your courses or channel here!\n\n"
        f"📩 <i>Contact admin (<a href=\"https://t.me/{contact_handle}\">{ADMIN_CONTACT}</a>) to get featured.</i>"
    )


async def get_contact_content() -> str:
    contact_handle = ADMIN_CONTACT.lstrip('@')
    return (
        f"{custom_emoji('chat', '💬')} <b>Contact & Support</b>\n\n"
        f"👤 <b>Admin:</b> <a href=\"https://t.me/{contact_handle}\">{ADMIN_CONTACT}</a>\n\n"
        "📩 <b>Send Message in Bot:</b>\n"
        "Type <code>/contact &lt;Your message&gt;</code>\n"
        "<i>(Our admin will reply directly in this chat)</i>"
    )


async def get_status_content(chat_id: int) -> str:
    active_subs = await get_active_subscribers()
    is_sub = chat_id in active_subs
    user_tz = await get_user_timezone(chat_id)

    status_icon = f"{custom_emoji('active', '🟢')} Active" if is_sub else f"{custom_emoji('paused', '🔴')} Paused"
    return (
        f"{custom_emoji('settings', '⚙️')} <b>Notification Settings</b>\n\n"
        f"📡 <b>Status:</b> {status_icon}\n"
        f"{custom_emoji('globe', '🌍')} <b>Timezone:</b> <code>{user_tz}</code>\n\n"
        "<b>Included alerts:</b>\n"
        "• 7-Day Countdown & Bluebook setup\n"
        "• 1-Day Before packing checklist\n"
        "• Exam Morning good-luck message\n"
        "• Official Score Release Day announcement\n\n"
        "<i>To change timezone, use the 🌍 Timezone button or /timezone &lt;City/Region&gt;.</i>"
    )


async def get_timezone_menu_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    current_tz = await get_user_timezone(chat_id)
    now_str = datetime.now(get_user_zoneinfo(current_tz)).strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"{custom_emoji('globe', '🌍')} <b>Timezone Preferences</b>\n\n"
        f"📍 <b>Active:</b> <code>{current_tz}</code>\n"
        f"🕒 <b>Local Time:</b> {now_str}\n\n"
        "<b>Select your timezone below or type:</b>\n"
        "<code>/timezone &lt;City/Region&gt;</code> (e.g. <code>/timezone Asia/Tashkent</code>)"
    )
    return text, get_timezone_inline_keyboard(current_tz)


# ---------------------------------------------------------
# BROADCAST HELPER
# ---------------------------------------------------------

async def broadcast_message(bot, text: str, parse_mode: str = "HTML") -> tuple[int, int]:
    """Sends a message to all active subscribers with rate limiting and automatic HTML fallback."""
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
            )
            success += 1
            await asyncio.sleep(0.04)  # 25 msgs/sec for high speed
        except BadRequest as e:
            err_msg = str(e).lower()
            if "can't parse entities" in err_msg or "tag" in err_msg or "entity" in err_msg:
                # Malformed HTML: Retry sending as plain text without HTML parsing
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode=None,
                        disable_web_page_preview=True,
                    )
                    success += 1
                    await asyncio.sleep(0.04)
                    continue
                except Exception as inner_e:
                    logger.error("Failed plain text broadcast to %s: %s", chat_id, inner_e)
                    failed += 1
            elif "chat not found" in err_msg or "user is deactivated" in err_msg or "blocked" in err_msg:
                logger.warning("User %s no longer accessible: %s. Unsubscribing.", chat_id, e)
                await unsubscribe_user(chat_id)
                failed += 1
            else:
                logger.error("BadRequest sending to %s: %s", chat_id, e)
                failed += 1
        except Forbidden as e:
            logger.warning("Bot was blocked by user %s. Unsubscribing.", chat_id)
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
    """Handler for /start command - responds instantly with dashboard and bottom keyboard."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_is_admin = is_admin(chat_id)

    await add_or_reactivate_subscriber(
        chat_id=chat_id,
        username=user.username,
        first_name=user.first_name,
    )

    text = await get_dashboard_content(chat_id)
    await update.message.reply_text(
        text=text,
        reply_markup=get_persistent_reply_keyboard(is_user_admin=user_is_admin),
        parse_mode="HTML",
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /admin command to open the control panel."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ You are not authorized to view the admin panel.")
        return

    text, kb = await get_admin_panel_content()
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_schedule_content(update.effective_chat.id)
    await update.message.reply_text(text, parse_mode="HTML")


async def countdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_countdown_content(update.effective_chat.id)
    await update.message.reply_text(text, parse_mode="HTML")


async def tips_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_tips_content()
    await update.message.reply_text(text, parse_mode="HTML")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_status_content(update.effective_chat.id)
    await update.message.reply_text(text, parse_mode="HTML")


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if context.args:
        custom_tz = context.args[0].strip()
        try:
            _ = get_user_zoneinfo(custom_tz)
            await set_user_timezone(chat_id, custom_tz)
            now_str = datetime.now(get_user_zoneinfo(custom_tz)).strftime("%Y-%m-%d %H:%M:%S")
            await update.message.reply_text(
                f"✅ <b>Timezone Updated to:</b> <code>{custom_tz}</code>\n🕒 <b>Local Time:</b> {now_str}",
                parse_mode="HTML",
            )
            return
        except Exception:
            await update.message.reply_text(f"⚠️ Invalid timezone <code>{custom_tz}</code>.", parse_mode="HTML")

    text, kb = await get_timezone_menu_content(chat_id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


# Admin states for interactive broadcast flow
_ADMIN_STATES: dict[int, str] = {}
_PENDING_BROADCASTS: dict[int, str] = {}


# ---------------------------------------------------------
# TEXT MESSAGE ROUTER (For Persistent Reply Keyboard Buttons)
# ---------------------------------------------------------

async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on persistent bottom reply keyboard buttons and admin text inputs."""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Check if admin is sending a broadcast message
    if is_admin(chat_id) and _ADMIN_STATES.get(chat_id) == "awaiting_broadcast":
        _ADMIN_STATES.pop(chat_id, None)
        _PENDING_BROADCASTS[chat_id] = text

        stats = await get_subscriber_stats()
        active_count = stats.get("active", 0)

        preview_msg = (
            "📢 <b>Broadcast Preview & Confirmation</b>\n\n"
            f"{text}\n\n"
            f"👥 <b>Target Recipients:</b> <code>{active_count} active users</code>\n\n"
            "<i>Send this broadcast to all subscribers now?</i>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Send Broadcast Now", callback_data="admin:confirm_broadcast")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin:panel")],
        ])
        await update.message.reply_text(preview_msg, reply_markup=kb, parse_mode="HTML")
        return

    if text == "📅 SAT Schedule":
        msg = await get_schedule_content(chat_id)
        await update.message.reply_text(msg, parse_mode="HTML")
    elif text == "⏳ Live Countdown":
        msg = await get_countdown_content(chat_id)
        await update.message.reply_text(msg, parse_mode="HTML")
    elif text == "📝 Test-Day Tips":
        msg = await get_tips_content()
        await update.message.reply_text(msg, parse_mode="HTML")
    elif text == "📚 SAT Tutors & Prep":
        msg = await get_tutors_content()
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    elif text == "💬 Contact Support":
        msg = await get_contact_content()
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    elif text == "🌍 Timezone":
        msg, kb = await get_timezone_menu_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text in ["⚙️ Notification Status", "⚙️ Status & Alerts"]:
        msg = await get_status_content(chat_id)
        await update.message.reply_text(msg, parse_mode="HTML")
    elif text in ["👑 Admin Panel", "👑 Admin Control Panel"]:
        if is_admin(chat_id):
            msg, kb = await get_admin_panel_content()
            await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
        else:
            await update.message.reply_text("⛔ You are not authorized to view the admin panel.")
    elif text == "🔗 Score Portal":
        await update.message.reply_text(
            "🔗 <b>College Board Student Score Portal</b>\n\n"
            "Access your official SAT scores here: https://studentscores.collegeboard.org/",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        # Default: Show Main Dashboard
        msg = await get_dashboard_content(chat_id)
        await update.message.reply_text(msg, parse_mode="HTML")


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
        text = await get_dashboard_content(chat_id)
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "nav:schedule":
        text = await get_schedule_content(chat_id)
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "nav:countdown":
        text = await get_countdown_content(chat_id)
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "nav:tips":
        text = await get_tips_content()
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "nav:tutors":
        text = await get_tutors_content()
        await query.edit_message_text(text, parse_mode="HTML", disable_web_page_preview=True)

    elif data == "nav:contact":
        text = await get_contact_content()
        await query.edit_message_text(text, parse_mode="HTML", disable_web_page_preview=True)

    elif data == "nav:timezone":
        text, kb = await get_timezone_menu_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:status":
        text = await get_status_content(chat_id)
        await query.edit_message_text(text, parse_mode="HTML")

    elif data == "action:toggle_sub":
        active_subs = await get_active_subscribers()
        if chat_id in active_subs:
            await unsubscribe_user(chat_id)
        else:
            user = update.effective_user
            await add_or_reactivate_subscriber(chat_id, user.username, user.first_name)
        text = await get_status_content(chat_id)
        await query.edit_message_text(text, parse_mode="HTML")

    elif data.startswith("set_tz:"):
        tz_code = data.split(":", 1)[1]
        await set_user_timezone(chat_id, tz_code)
        text, kb = await get_timezone_menu_content(chat_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    # Admin Panel Actions
    elif data == "admin:panel":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        text, kb = await get_admin_panel_content()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:stats":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        stats = await get_subscriber_stats()
        text = (
            "📊 <b>Live Subscriber Stats</b>\n\n"
            f"🟢 <b>Active:</b> <code>{stats.get('active', 0)}</code>\n"
            f"👥 <b>Total:</b> <code>{stats.get('total', 0)}</code>\n"
            f"🌍 <b>Main Timezone:</b> <code>Asia/Tashkent (UZT, UTC+5)</code>\n"
            f"⚡ <b>Engine:</b> <code>Healthy (Persistent Snapshot WAL)</code>\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 View All Users", callback_data="admin:users")],
            [InlineKeyboardButton("📥 Export Full List (.txt)", callback_data="admin:export_users")],
            [InlineKeyboardButton("⚡ Reactivate All Users", callback_data="admin:reactivate_all")],
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin:stats")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:reactivate_all":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        count = await reactivate_all_subscribers()
        await query.answer(f"✅ Reactivated {count} users!", show_alert=True)
        stats = await get_subscriber_stats()
        text = (
            "📊 <b>Live Subscriber Stats</b>\n\n"
            f"🟢 <b>Active:</b> <code>{stats.get('active', 0)}</code>\n"
            f"👥 <b>Total:</b> <code>{stats.get('total', 0)}</code>\n"
            f"⚡ <b>Engine:</b> <code>Healthy (WAL Mode)</code>\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin:stats")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:users":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        all_users = await get_all_subscribers()
        total = len(all_users)
        active = sum(1 for u in all_users if u.get("is_active"))
        inactive = total - active

        header = (
            f"👥 <b>Registered Users Database</b> (All-Time)\n\n"
            f"📊 <b>Total:</b> <code>{total}</code> | 🟢 <b>Active:</b> <code>{active}</code> | ⚪ <b>Inactive:</b> <code>{inactive}</code>\n"
            f"🌍 <b>Main Timezone:</b> <code>Asia/Tashkent</code>\n\n"
        )

        if not all_users:
            msg_text = header + "<i>No users found in database yet.</i>"
        else:
            lines = []
            for i, u in enumerate(all_users[:30], 1):
                name = u.get("first_name") or "User"
                username = f"@{u['username']}" if u.get("username") else "No handle"
                uid = u["chat_id"]
                tz = u.get("timezone") or "Asia/Tashkent"
                status = "🟢" if u.get("is_active") else "⚪"
                joined = (u.get("subscribed_at") or "")[:10]
                lines.append(f"{i}. {status} <b>{name}</b> ({username}) - <code>{uid}</code>\n   🌍 {tz} | 📅 {joined}")

            user_list_str = "\n".join(lines)
            if total > 30:
                user_list_str += f"\n\n<i>...and {total - 30} more users. Click below to export full file.</i>"
            msg_text = header + user_list_str

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Export Full List (.txt)", callback_data="admin:export_users")],
            [InlineKeyboardButton("🔄 Refresh List", callback_data="admin:users")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(msg_text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:export_users":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        all_users = await get_all_subscribers()
        out = io.StringIO()
        out.write("====================================================\n")
        out.write("   SAT NOTIFY BOT - COMPLETE REGISTERED USERS LIST  \n")
        out.write("====================================================\n")
        out.write(f"Generated: {datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%Y-%m-%d %H:%M:%S')} Tashkent Time\n")
        out.write(f"Total Users: {len(all_users)}\n\n")
        out.write(f"{'#':<4} {'CHAT_ID':<14} {'STATUS':<10} {'TIMEZONE':<18} {'JOINED':<12} {'USERNAME':<18} {'FIRST_NAME'}\n")
        out.write("-" * 90 + "\n")
        for i, u in enumerate(all_users, 1):
            status = "ACTIVE" if u.get("is_active") else "INACTIVE"
            tz = u.get("timezone") or "Asia/Tashkent"
            joined = (u.get("subscribed_at") or "")[:10]
            uname = f"@{u['username']}" if u.get("username") else "N/A"
            fname = u.get("first_name") or "N/A"
            out.write(f"{i:<4} {u['chat_id']:<14} {status:<10} {tz:<18} {joined:<12} {uname:<18} {fname}\n")
        
        file_bytes = out.getvalue().encode("utf-8")
        out.close()
        bio = io.BytesIO(file_bytes)
        bio.name = f"sat_bot_users_{datetime.now().strftime('%Y%m%d')}.txt"

        await query.answer("📤 Sending users export file...")
        await context.bot.send_document(
            chat_id=chat_id,
            document=bio,
            caption=f"📋 Complete user database: {len(all_users)} total subscribers.",
        )

    elif data == "admin:broadcast_prompt":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        _ADMIN_STATES[chat_id] = "awaiting_broadcast"
        text = (
            "📢 <b>Broadcast to All Subscribers</b>\n\n"
            "✍️ <b>Send the message you want to broadcast below:</b>\n\n"
            "<i>(Standard text, announcements, bold or links supported)</i>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel Broadcast", callback_data="admin:cancel_broadcast")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:cancel_broadcast":
        _ADMIN_STATES.pop(chat_id, None)
        _PENDING_BROADCASTS.pop(chat_id, None)
        text, kb = await get_admin_panel_content()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:confirm_broadcast":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        broadcast_text = _PENDING_BROADCASTS.pop(chat_id, None)
        if not broadcast_text:
            await query.answer("⚠️ No pending message found to broadcast.", show_alert=True)
            text, kb = await get_admin_panel_content()
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            return

        await query.edit_message_text("🚀 <b>Broadcasting message to subscribers in real-time...</b>", parse_mode="HTML")
        success, failed = await broadcast_message(context.bot, broadcast_text)
        result_msg = (
            "✅ <b>Broadcast Completed</b>\n\n"
            f"• 📤 <b>Delivered:</b> <code>{success} users</code>\n"
            f"• ⚠️ <b>Failed / Inactive:</b> <code>{failed}</code>\n"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")]])
        await query.edit_message_text(result_msg, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:announce_scores":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        test = get_next_score_release()
        test_name = test["name"] if test else "Recent SAT"
        announcement = TEMPLATES["score_release_morning"].format(
            test_name=test_name,
            release_date=get_current_date().strftime("%B %d, %Y"),
        )
        await query.edit_message_text(f"🚀 Broadcasting score release announcement for <b>{test_name}</b>...", parse_mode="HTML")
        success, failed = await broadcast_message(context.bot, announcement)
        text = (
            f"✅ <b>Score Announcement Sent!</b>\n\n"
            f"• Delivered to: <b>{success}</b> subscribers\n"
            f"• Failed/Removed: <b>{failed}</b>\n"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:check_cb":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        from checker import fetch_collegeboard_alerts, detect_early_score_release
        alerts = await asyncio.to_thread(fetch_collegeboard_alerts)
        is_early, detail = await asyncio.to_thread(detect_early_score_release)
        text = (
            "🔍 <b>College Board Feed Status</b>\n\n"
            f"📡 <b>Alerts Feed Count:</b> {len(alerts)} alerts\n"
            f"⚡ <b>Early Release Detected:</b> {'YES 🚨' if is_early else 'NO (Normal Schedule)'}\n"
            f"ℹ️ <b>Detail:</b> {detail or 'Feed reachable, no active emergency banners.'}\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Re-check Feed", callback_data="admin:check_cb")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:test_scores_menu":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        next_score = get_next_score_release() or {"name": "August 2026 SAT", "score_release_date": date(2026, 9, 4)}
        text = (
            "🧪 <b>Score Release Test Center</b>\n\n"
            f"📅 <b>Target Test:</b> {next_score['name']}\n"
            f"📢 <b>Score Date:</b> {next_score['score_release_date'].strftime('%A, %B %d, %Y')}\n\n"
            "Choose an action below to test notifications before score release day:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Send Test to Me (Private)", callback_data="admin:send_test_score_me")],
            [InlineKeyboardButton("📢 Broadcast Test to All Users", callback_data="admin:send_test_score_all")],
            [InlineKeyboardButton("⚡ Preview Tomorrow Alert", callback_data="admin:test_score_1d")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:send_test_score_me":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        next_score = get_next_score_release() or {"name": "August 2026 SAT", "score_release_date": date(2026, 9, 4)}
        eve_msg = (
            "🧪 <b>[Test: 1 Day Before Score Release]</b>\n\n" +
            TEMPLATES["score_release_1day"].format(
                test_name=next_score["name"],
                release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
            )
        )
        morning_msg = (
            "🧪 <b>[Test: Score Release Day Morning]</b>\n\n" +
            TEMPLATES["score_release_morning"].format(
                test_name=next_score["name"],
                release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
            )
        )
        await context.bot.send_message(chat_id=chat_id, text=eve_msg, parse_mode="HTML", disable_web_page_preview=True)
        await context.bot.send_message(chat_id=chat_id, text=morning_msg, parse_mode="HTML", disable_web_page_preview=True)
        await query.answer("✅ Sent 2 test alerts to your private chat!", show_alert=True)

    elif data == "admin:send_test_score_all":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        next_score = get_next_score_release() or {"name": "August 2026 SAT", "score_release_date": date(2026, 9, 4)}
        announcement = TEMPLATES["score_release_1day"].format(
            test_name=next_score["name"],
            release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
        )
        await query.edit_message_text(f"🚀 Broadcasting pre-score-release alert for <b>{next_score['name']}</b>...", parse_mode="HTML")
        success, failed = await broadcast_message(context.bot, announcement)
        result_msg = (
            "✅ <b>Pre-Score Release Alert Broadcasted</b>\n\n"
            f"• 📤 <b>Delivered:</b> <code>{success} users</code>\n"
            f"• ⚠️ <b>Failed / Inactive:</b> <code>{failed}</code>\n"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")]])
        await query.edit_message_text(result_msg, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:test_score_1d":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        next_score = get_next_score_release() or {"name": "August 2026 SAT", "score_release_date": date(2026, 9, 4)}
        preview_text = TEMPLATES["score_release_1day"].format(
            test_name=next_score["name"],
            release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
        )
        text = f"🧪 <b>[Admin Preview: 1 Day Before Score Release]</b>\n\n" + preview_text
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Send Test to Me", callback_data="admin:send_test_score_me")],
            [InlineKeyboardButton("📢 Broadcast Test to All", callback_data="admin:send_test_score_all")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)

    elif data in ["admin:test_7d", "admin:test_1d", "admin:test_morning", "admin:test_scores"]:
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        next_test = get_next_test() or {"name": "August 2026 SAT", "test_date": date(2026, 8, 22), "score_release_date": date(2026, 9, 4)}
        if data == "admin:test_7d":
            preview_text = TEMPLATES["exam_7days"].format(test_name=next_test["name"], test_date=next_test["test_date"].strftime("%A, %B %d, %Y"))
        elif data == "admin:test_1d":
            preview_text = TEMPLATES["exam_1day"].format(test_name=next_test["name"], test_date=next_test["test_date"].strftime("%A, %B %d, %Y"))
        elif data == "admin:test_morning":
            preview_text = TEMPLATES["exam_morning"].format(test_name=next_test["name"], test_date=next_test["test_date"].strftime("%A, %B %d, %Y"))
        else:
            preview_text = TEMPLATES["score_release_morning"].format(test_name=next_test["name"], release_date=next_test["score_release_date"].strftime("%A, %B %d, %Y"))
        
        text = f"🧪 <b>[Admin Preview]</b>\n\n" + preview_text
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Send Test to Me", callback_data="admin:send_test_score_me")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
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


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: View all users who ever sent /start."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    all_users = await get_all_subscribers()
    total = len(all_users)
    active = sum(1 for u in all_users if u.get("is_active"))
    inactive = total - active

    header = (
        f"👥 <b>Registered Users Database</b> (All-Time)\n\n"
        f"📊 <b>Total Users:</b> <code>{total}</code>\n"
        f"🟢 <b>Active Subscribers:</b> <code>{active}</code>\n"
        f"⚪ <b>Inactive/Paused:</b> <code>{inactive}</code>\n"
        f"🌍 <b>Main Timezone:</b> <code>Asia/Tashkent (UZT, UTC+5)</code>\n\n"
    )

    if not all_users:
        await update.message.reply_text(header + "<i>No registered users found in database yet.</i>", parse_mode="HTML")
        return

    lines = []
    for i, u in enumerate(all_users[:30], 1):
        name = u.get("first_name") or "User"
        username = f"@{u['username']}" if u.get("username") else "No handle"
        uid = u["chat_id"]
        tz = u.get("timezone") or "Asia/Tashkent"
        status = "🟢 Active" if u.get("is_active") else "⚪ Inactive"
        joined = (u.get("subscribed_at") or "")[:10]
        lines.append(f"{i}. <b>{name}</b> ({username}) - <code>{uid}</code>\n   🌍 {tz} | 📅 Joined: {joined} | {status}")

    user_list_str = "\n".join(lines)
    if total > 30:
        user_list_str += f"\n\n<i>...and {total - 30} more users. Full database export attached below.</i>"

    await update.message.reply_text(header + user_list_str, parse_mode="HTML")

    if total > 20:
        out = io.StringIO()
        out.write("====================================================\n")
        out.write("   SAT NOTIFY BOT - COMPLETE REGISTERED USERS LIST  \n")
        out.write("====================================================\n")
        out.write(f"Generated: {datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%Y-%m-%d %H:%M:%S')} Tashkent Time\n")
        out.write(f"Total Users: {len(all_users)}\n\n")
        out.write(f"{'#':<4} {'CHAT_ID':<14} {'STATUS':<10} {'TIMEZONE':<18} {'JOINED':<12} {'USERNAME':<18} {'FIRST_NAME'}\n")
        out.write("-" * 90 + "\n")
        for i, u in enumerate(all_users, 1):
            status = "ACTIVE" if u.get("is_active") else "INACTIVE"
            tz = u.get("timezone") or "Asia/Tashkent"
            joined = (u.get("subscribed_at") or "")[:10]
            uname = f"@{u['username']}" if u.get("username") else "N/A"
            fname = u.get("first_name") or "N/A"
            out.write(f"{i:<4} {u['chat_id']:<14} {status:<10} {tz:<18} {joined:<12} {uname:<18} {fname}\n")
        
        file_bytes = out.getvalue().encode("utf-8")
        out.close()
        bio = io.BytesIO(file_bytes)
        bio.name = f"sat_bot_users_{datetime.now().strftime('%Y%m%d')}.txt"
        await update.message.reply_document(
            document=bio,
            caption=f"📋 Complete user list: {len(all_users)} total subscribers.",
        )


async def test_scores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /test_scores [me|all] - Send test score release message before score release day."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    mode = context.args[0].lower() if context.args else "me"
    next_score = get_next_score_release() or {"name": "August 2026 SAT", "score_release_date": date(2026, 9, 4)}

    eve_msg = (
        "🧪 <b>[Test: 1 Day Before Score Release]</b>\n\n" +
        TEMPLATES["score_release_1day"].format(
            test_name=next_score["name"],
            release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
        )
    )
    morning_msg = (
        "🧪 <b>[Test: Score Release Day Morning]</b>\n\n" +
        TEMPLATES["score_release_morning"].format(
            test_name=next_score["name"],
            release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
        )
    )

    if mode in ("all", "broadcast"):
        status_msg = await update.message.reply_text("🚀 Broadcasting pre-score-release test alert to all subscribers...", parse_mode="HTML")
        success, failed = await broadcast_message(context.bot, eve_msg)
        await status_msg.edit_text(
            f"✅ <b>Pre-Score Release Alert Broadcasted:</b>\n"
            f"• Successfully sent: {success}\n"
            f"• Failed/Inactive: {failed}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(eve_msg, parse_mode="HTML", disable_web_page_preview=True)
        await update.message.reply_text(morning_msg, parse_mode="HTML", disable_web_page_preview=True)
        await update.message.reply_text(
            "💡 <i>Test messages sent to your private chat. To broadcast to all users, type:</i>\n<code>/test_scores all</code>",
            parse_mode="HTML",
        )


async def test_score_eve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /test_eve [me|all] - Send 1-day-before score release notification."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    mode = context.args[0].lower() if context.args else "me"
    next_score = get_next_score_release() or {"name": "August 2026 SAT", "score_release_date": date(2026, 9, 4)}
    msg = TEMPLATES["score_release_1day"].format(
        test_name=next_score["name"],
        release_date=next_score["score_release_date"].strftime("%A, %B %d, %Y"),
    )

    if mode in ("all", "broadcast"):
        status_msg = await update.message.reply_text("🚀 Broadcasting 1-day reminder to all subscribers...", parse_mode="HTML")
        success, failed = await broadcast_message(context.bot, msg)
        await status_msg.edit_text(
            f"✅ <b>Broadcast Complete:</b>\n• Sent: {success}\n• Failed: {failed}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(f"🧪 <b>[Admin Preview: 1 Day Before Scores]</b>\n\n{msg}", parse_mode="HTML", disable_web_page_preview=True)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Broadcast custom message to subscribers."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    if not context.args:
        _ADMIN_STATES[chat_id] = "awaiting_broadcast"
        await update.message.reply_text(
            "📢 <b>Broadcast to All Subscribers</b>\n\n"
            "✍️ <b>Please send the message you want to broadcast below:</b>\n\n"
            "<i>(Standard text, announcements, bold or links supported)</i>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin:cancel_broadcast")]]),
            parse_mode="HTML",
        )
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


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /contact and /feedback commands."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not context.args:
        text = await get_contact_content()
        await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
        return

    user_message = update.message.text.partition(" ")[2].strip()

    # Forward to Admins
    if ADMIN_IDS:
        admin_alert = (
            "📩 <b>New Support Message</b>\n\n"
            f"👤 <b>From:</b> {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 <b>User ID:</b> <code>{chat_id}</code>\n\n"
            f"💬 <b>Message:</b>\n{user_message}\n\n"
            f"👉 <b>To reply, type:</b>\n<code>/reply {chat_id} &lt;Your reply&gt;</code>"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_alert, parse_mode="HTML")
            except Exception as e:
                logger.error("Failed to forward support message to admin %s: %s", admin_id, e)

    await update.message.reply_text(
        "✅ <b>Message Sent to Support!</b>\n\n"
        "Our admin has received your message and will reply directly in this chat.",
        parse_mode="HTML",
    )


async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /reply <user_id> <message> to reply directly to a customer."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /reply <user_id> <message>")
        return

    target_id_str = context.args[0]
    if not target_id_str.isdigit():
        await update.message.reply_text("⚠️ Invalid User ID.")
        return

    target_id = int(target_id_str)
    reply_text = " ".join(context.args[1:])

    msg_to_user = (
        "💬 <b>Support Team Response</b>\n\n"
        f"{reply_text}\n\n"
        "<i>To send another message, type /contact &lt;message&gt;</i>"
    )

    try:
        await context.bot.send_message(chat_id=target_id, text=msg_to_user, parse_mode="HTML")
        await update.message.reply_text(f"✅ Response delivered to user <code>{target_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver message to <code>{target_id}</code>: {e}", parse_mode="HTML")


# ---------------------------------------------------------
# INLINE MODE & GROUP CHAT HANDLERS
# ---------------------------------------------------------

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline queries (@BotUsername in any chat or group)."""
    today = get_current_date()
    next_test = get_next_test()
    next_score = get_next_score_release()

    bot_user = context.bot.username or "SATBot"

    # 1. Countdown Article
    days_to_test = (next_test["test_date"] - today).days if next_test else 0
    days_to_score = (next_score["score_release_date"] - today).days if next_score else 0

    countdown_text = (
        "⏳ <b>Live SAT Countdowns</b>\n\n"
        f"📝 <b>Next Exam:</b> {next_test['name'] if next_test else 'None'}\n"
        f"   ↳ <b>{days_to_test} days</b> remaining ({next_test['test_date'].strftime('%b %d, %Y') if next_test else 'N/A'})\n\n"
        f"📢 <b>Next Score Release:</b> {next_score['name'] if next_score else 'None'}\n"
        f"   ↳ <b>{days_to_score} days</b> remaining ({next_score['score_release_date'].strftime('%b %d, %Y') if next_score else 'N/A'})\n\n"
        "<i>Track live SAT alerts & countdowns on Telegram!</i>"
    )
    countdown_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Open SAT Bot", url=f"https://t.me/{bot_user}?start=inline")],
        [InlineKeyboardButton("🌐 College Board Score Portal", url="https://studentscores.collegeboard.org/")],
    ])

    # 2. Schedule Article
    upcoming = get_upcoming_tests(limit=5)
    sched_lines = ["📅 <b>Official SAT Schedule</b>\n\n"]
    for item in upcoming:
        sched_lines.append(f"🎓 <b>{item['name']}</b>\n  • Test Date: <b>{item['test_date'].strftime('%b %d, %Y')}</b>\n  • Score Release: <b>{item['score_release_date'].strftime('%b %d, %Y')}</b>\n")
    sched_text = "\n".join(sched_lines)

    # 3. Test-Day Checklist Article
    tips_text = TEMPLATES["tips"]

    results = [
        InlineQueryResultArticle(
            id="sat_countdown",
            title="⏳ SAT Exam & Score Countdown",
            description=f"Next SAT: {days_to_test} days | Next Scores: {days_to_score} days",
            input_message_content=InputTextMessageContent(countdown_text, parse_mode="HTML"),
            reply_markup=countdown_kb,
        ),
        InlineQueryResultArticle(
            id="sat_schedule",
            title="📅 Official SAT Testing Schedule",
            description="View all 2026-2027 SAT test dates & score release dates",
            input_message_content=InputTextMessageContent(sched_text, parse_mode="HTML"),
            reply_markup=countdown_kb,
        ),
        InlineQueryResultArticle(
            id="sat_tips",
            title="🎒 Digital SAT Test-Day Checklist",
            description="Bluebook readiness, calculator rules, what to bring",
            input_message_content=InputTextMessageContent(tips_text, parse_mode="HTML"),
            reply_markup=countdown_kb,
        ),
    ]

    await update.inline_query.answer(results, cache_time=60, is_personal=True)


async def chat_member_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles bot being added to groups or supergroups."""
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        return

    # Add group chat_id to subscribers database
    await add_or_reactivate_subscriber(
        chat_id=chat.id,
        username=chat.title or chat.username or "Group",
        first_name=chat.title or "SAT Study Group",
    )

    welcome_msg = (
        "👋 <b>SAT Notify Bot is active in this group!</b>\n\n"
        "This group will automatically receive:\n"
        "✨ Test-Day Reminders & Checklists\n"
        "🌟 Exam Morning Motivation\n"
        "📢 Instant Score Release Drops\n\n"
        "<b>Commands:</b> /countdown, /schedule, /tips, /timezone"
    )
    group_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏳ Live Countdown", callback_data="nav:countdown"),
            InlineKeyboardButton("📅 SAT Schedule", callback_data="nav:schedule"),
        ],
        [
            InlineKeyboardButton("🌐 Score Portal", url="https://studentscores.collegeboard.org/"),
        ],
    ])

    try:
        await context.bot.send_message(chat_id=chat.id, text=welcome_msg, reply_markup=group_kb, parse_mode="HTML")
    except Exception as e:
        logger.error("Failed to send welcome message to group %s: %s", chat.id, e)


from checker import detect_early_score_release


# ---------------------------------------------------------
# BACKGROUND NOTIFICATION RUNNER
# ---------------------------------------------------------

async def check_and_send_scheduled_alerts(bot):
    """Checks schedule against today's date and triggers automated alerts including early releases."""
    today = get_current_date()
    logger.info("Running scheduled alert check for date: %s", today)

    # 1. Early Score Release Live Scanner
    next_scores = get_next_score_release()
    if next_scores:
        item_id = next_scores["id"]
        test_name = next_scores["name"]
        score_date = next_scores["score_release_date"]
        test_date = next_scores["test_date"]

        # Only scan if test has finished and scores are not yet marked as sent
        if test_date <= today <= score_date:
            event_key = f"{item_id}_score_release_day"
            if not await is_notification_sent(event_key):
                is_early, alert_header = await asyncio.to_thread(detect_early_score_release)
                if is_early:
                    logger.info("🚨 EARLY SCORE RELEASE DETECTED for %s (%s)", test_name, alert_header)
                    msg = TEMPLATES["early_score_release"].format(test_name=test_name)
                    success, _ = await broadcast_message(bot, msg)
                    await mark_notification_sent(event_key, success)

    # 2. Standard Calendar Trigger Checks
    for item in SAT_SCHEDULE:
        item_id = item["id"]
        test_name = item["name"]
        test_date = item["test_date"]
        score_date = item["score_release_date"]

        days_to_test = (test_date - today).days

        # Check 7 Days Before Exam
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

        # Check 1 Day Before Exam
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

        # Check Exam Morning
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

        # Check 1 Day Before Score Release Day (Score Release Eve)
        days_to_scores = (score_date - today).days
        if days_to_scores == 1:
            event_key = f"{item_id}_score_release_1day"
            if not await is_notification_sent(event_key):
                logger.info("Triggering 1-day-before score release reminder for %s", test_name)
                msg = TEMPLATES["score_release_1day"].format(
                    test_name=test_name,
                    release_date=score_date.strftime("%A, %B %d, %Y"),
                )
                success, _ = await broadcast_message(bot, msg)
                await mark_notification_sent(event_key, success)

        # Check Official Score Release Day
        elif days_to_scores == 0:
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and notify user gracefully if update is available."""
    logger.error("Exception while handling an update: %s", context.error)


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

    # Register Error Handler
    application.add_error_handler(error_handler)

    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("countdown", countdown_command))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(CommandHandler("tips", tips_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("contact", contact_command))
    application.add_handler(CommandHandler("feedback", contact_command))

    # Admin Handlers
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("subscribers", users_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("announce_scores", announce_scores_command))
    application.add_handler(CommandHandler("test_scores", test_scores_command))
    application.add_handler(CommandHandler("test_score_release", test_scores_command))
    application.add_handler(CommandHandler("test_eve", test_score_eve_command))
    application.add_handler(CommandHandler("test_score_eve", test_score_eve_command))
    application.add_handler(CommandHandler("reply", reply_command))

    # Inline Button Navigation Router
    application.add_handler(CallbackQueryHandler(inline_callback_router))

    # Inline Mode Query Handler (@BotUsername in any chat)
    application.add_handler(InlineQueryHandler(inline_query_handler))

    # Group Join / Chat Member Update Handler
    application.add_handler(ChatMemberHandler(chat_member_update_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    # Persistent Text Buttons Message Router
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    logger.info("Starting SAT Notify Telegram Bot with Premium UI...")

    # Wire application to web server
    from web_server import set_telegram_app
    set_telegram_app(application)

    # Initialize Telegram Application
    await application.initialize()
    await application.start()

    webhook_base = os.getenv("WEBHOOK_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
    if webhook_base:
        webhook_url = f"{webhook_base}/webhook"
        try:
            await application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Telegram Webhook successfully set to: %s", webhook_url)
        except Exception as e:
            logger.error("Failed to set webhook: %s. Falling back to polling.", e)
            webhook_base = ""
            await application.updater.start_polling(drop_pending_updates=True)
    else:
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Polling started.")

    scheduler_task = asyncio.create_task(background_scheduler_loop(application))

    # Keep bot running until shutdown signal
    stop_signal = asyncio.Event()
    try:
        await stop_signal.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutdown signal received...")
    finally:
        scheduler_task.cancel()
        if not webhook_base and application.updater and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()
        logger.info("Application shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
