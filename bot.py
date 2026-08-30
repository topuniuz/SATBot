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


def get_main_menu_inline_keyboard(is_user_admin: bool = False) -> InlineKeyboardMarkup:
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
            InlineKeyboardButton("📚 SAT Tutors & Prep", callback_data="nav:tutors"),
            InlineKeyboardButton("💬 Contact Support", callback_data="nav:contact"),
        ],
        [
            InlineKeyboardButton("⚙️ Status & Alerts", callback_data="nav:status"),
            InlineKeyboardButton("🌐 Score Portal", url="https://studentscores.collegeboard.org/"),
        ],
    ]
    if is_user_admin:
        buttons.append([InlineKeyboardButton("👑 Admin Control Panel", callback_data="admin:panel")])
    return InlineKeyboardMarkup(buttons)


def get_admin_panel_inline_keyboard() -> InlineKeyboardMarkup:
    """Returns interactive inline buttons for Admin Control Panel."""
    buttons = [
        [
            InlineKeyboardButton("📊 Live Subscriber Stats", callback_data="admin:stats"),
            InlineKeyboardButton("📢 Broadcast Message", callback_data="admin:broadcast_prompt"),
        ],
        [
            InlineKeyboardButton("🚀 Announce Scores Now", callback_data="admin:announce_scores"),
            InlineKeyboardButton("🔍 Check CB Live Feed", callback_data="admin:check_cb"),
        ],
        [
            InlineKeyboardButton("🧪 Test 7-Day Alert", callback_data="admin:test_7d"),
            InlineKeyboardButton("🧪 Test 1-Day Alert", callback_data="admin:test_1d"),
        ],
        [
            InlineKeyboardButton("🧪 Test Exam Morning", callback_data="admin:test_morning"),
            InlineKeyboardButton("🧪 Test Score Release", callback_data="admin:test_scores"),
        ],
        [
            InlineKeyboardButton("🏠 Back to Main Dashboard", callback_data="nav:menu"),
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
            InlineKeyboardButton("📚 SAT Prep & Tutors", callback_data="nav:tutors"),
        ])
    elif current_page == "tutors":
        buttons.append([
            InlineKeyboardButton("💬 Contact Admin to Feature Tutor", callback_data="nav:contact"),
        ])
        buttons.append([
            InlineKeyboardButton("📝 Test Tips", callback_data="nav:tips"),
            InlineKeyboardButton("⏳ View Countdown", callback_data="nav:countdown"),
        ])
    elif current_page == "contact":
        contact_url = f"https://t.me/{ADMIN_CONTACT.lstrip('@')}" if ADMIN_CONTACT.startswith("@") else ADMIN_CONTACT
        buttons.append([
            InlineKeyboardButton("💬 Open Chat with Admin", url=contact_url),
        ])
    elif current_page == "status":
        sub_btn = (
            InlineKeyboardButton("🔕 Pause Alerts", callback_data="action:toggle_sub")
            if is_subscribed
            else InlineKeyboardButton("🔔 Resume Alerts", callback_data="action:toggle_sub")
        )
        buttons.append([sub_btn, InlineKeyboardButton("🌍 Change Timezone", callback_data="nav:timezone")])

    buttons.append([
        InlineKeyboardButton("🏠 Main Dashboard", callback_data="nav:menu"),
        InlineKeyboardButton("🔗 Score Portal", url="https://studentscores.collegeboard.org/"),
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
    user_is_admin = is_admin(chat_id)

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
    return text, get_main_menu_inline_keyboard(is_user_admin=user_is_admin)


async def get_admin_panel_content() -> tuple[str, InlineKeyboardMarkup]:
    stats = await get_subscriber_stats()
    next_test = get_next_test()
    next_scores = get_next_score_release()

    text = (
        "👑 <b>ADMIN CONTROL PANEL</b> 👑\n"
        "────────────────────────\n"
        f"📊 <b>Active Subscribers:</b> <code>{stats.get('active', 0)}</code>\n"
        f"👥 <b>Total Users:</b> <code>{stats.get('total', 0)}</code>\n"
        f"📅 <b>Next Test:</b> {next_test['name'] if next_test else 'None'}\n"
        f"📢 <b>Next Score Date:</b> {next_scores['score_release_date'] if next_scores else 'None'}\n\n"
        "<b>Available Admin Actions:</b>\n"
        "• <b>Stats:</b> View real-time database counts\n"
        "• <b>Broadcast:</b> Send a message to all users\n"
        "• <b>Announce Scores:</b> Instantly trigger score release alert\n"
        "• <b>Check CB Feed:</b> Test live College Board API feed\n"
        "• <b>Test Alerts:</b> Preview templates sent only to you"
    )
    return text, get_admin_panel_inline_keyboard()


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


async def get_tutors_content() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "📚 <b>SAT PREPARATION & RECOMMENDED TUTORS</b>\n"
        "────────────────────────\n"
        "🎯 <b>Official Free Practice:</b>\n"
        "• <b>Bluebook™:</b> 6 Official full-length adaptive practice exams\n"
        "• <b>Khan Academy:</b> Official Digital SAT interactive course & video explanations\n"
        "• <b>College Board Question Bank:</b> Over 3,000+ real practice questions\n\n"
        "👨‍🏫 <b>Featured SAT Tutors & Channels:</b>\n"
        "• Are you an SAT tutor or education channel?\n"
        "• Partner with us to feature your courses, mock exams, and channels here!\n\n"
        "📩 <i>Contact the bot admin to get your tutoring service or channel featured!</i>"
    )
    return text, get_subpage_inline_keyboard("tutors")


async def get_contact_content() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "💬 <b>CONTACT & SUPPORT</b>\n"
        "────────────────────────\n"
        "Have questions, feedback, or want to partner with us?\n\n"
        f"👤 <b>Admin Contact:</b> {ADMIN_CONTACT}\n"
        "📩 <b>Send Message in Bot:</b>\n"
        "Type <code>/contact &lt;Your message here&gt;</code>\n"
        "<i>(Our admin team will receive your message and reply directly in this chat!)</i>"
    )
    return text, get_subpage_inline_keyboard("contact")


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
            await asyncio.sleep(0.04)  # 25 msgs/sec for high speed
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
    """Handler for /start command - responds instantly with dashboard."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_is_admin = is_admin(chat_id)

    await add_or_reactivate_subscriber(
        chat_id=chat_id,
        username=user.username,
        first_name=user.first_name,
    )

    text, inline_kb = await get_dashboard_content(chat_id)
    # Send single snappy response with both keyboards
    await update.message.reply_text(
        text=text,
        reply_markup=inline_kb,
        parse_mode="HTML",
    )
    # Ensure bottom reply keyboard is presented
    await update.message.reply_text(
        text="👋 Choose an option from the menu below or tap any button above:",
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
            "📢 <b>BROADCAST PREVIEW & CONFIRMATION</b>\n"
            "────────────────────────\n"
            f"{text}\n"
            "────────────────────────\n"
            f"👥 <b>Target Recipients:</b> <code>{active_count} active users</code>\n\n"
            "⚠️ <i>Do you want to send this broadcast to all subscribers now?</i>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Send Broadcast Now", callback_data="admin:confirm_broadcast")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin:panel")],
        ])
        await update.message.reply_text(preview_msg, reply_markup=kb, parse_mode="HTML")
        return

    if text == "📅 SAT Schedule":
        msg, kb = await get_schedule_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "⏳ Live Countdown":
        msg, kb = await get_countdown_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "📝 Test-Day Tips":
        msg, kb = await get_tips_content()
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "📚 SAT Tutors & Prep":
        msg, kb = await get_tutors_content()
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "💬 Contact Support":
        msg, kb = await get_contact_content()
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text == "🌍 Timezone":
        msg, kb = await get_timezone_menu_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text in ["⚙️ Notification Status", "⚙️ Status & Alerts"]:
        msg, kb = await get_status_content(chat_id)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    elif text in ["👑 Admin Panel", "👑 Admin Control Panel"]:
        if is_admin(chat_id):
            msg, kb = await get_admin_panel_content()
            await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
        else:
            await update.message.reply_text("⛔ You are not authorized to view the admin panel.")
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

    elif data == "nav:tutors":
        text, kb = await get_tutors_content()
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "nav:contact":
        text, kb = await get_contact_content()
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
            "📊 <b>DETAILED LIVE STATS</b>\n"
            "────────────────────────\n"
            f"🟢 <b>Active Subscribers:</b> <code>{stats.get('active', 0)}</code>\n"
            f"👥 <b>Total Registered:</b> <code>{stats.get('total', 0)}</code>\n"
            f"⚡ <b>Engine Status:</b> <code>Healthy (WAL Mode)</code>\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin:stats")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    elif data == "admin:broadcast_prompt":
        if not is_admin(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return
        _ADMIN_STATES[chat_id] = "awaiting_broadcast"
        text = (
            "📢 <b>BROADCAST TO ALL SUBSCRIBERS</b>\n"
            "────────────────────────\n"
            "✍️ <b>Please send the message you want to broadcast below:</b>\n\n"
            "<i>(You can type standard text, paste an announcement, or use bold/links. You do NOT need to type /broadcast)</i>"
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

        await query.edit_message_text("🚀 <b>Broadcasting message to all subscribers in real-time...</b>", parse_mode="HTML")
        success, failed = await broadcast_message(context.bot, broadcast_text)
        result_msg = (
            "✅ <b>BROADCAST COMPLETED</b>\n"
            "────────────────────────\n"
            f"• 📤 <b>Successfully Delivered:</b> <code>{success} users</code>\n"
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
            "🔍 <b>COLLEGE BOARD LIVE FEED STATUS</b>\n"
            "────────────────────────\n"
            f"📡 <b>Alerts Feed Count:</b> {len(alerts)} alerts\n"
            f"⚡ <b>Early Release Detected:</b> {'YES 🚨' if is_early else 'NO (Normal Schedule)'}\n"
            f"ℹ️ <b>Detail:</b> {detail or 'Feed reachable, no active emergency banners.'}\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Re-check Feed", callback_data="admin:check_cb")],
            [InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")],
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

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
        
        text = f"🧪 <b>[ADMIN PREVIEW ONLY]</b>\n────────────────────────\n" + preview_text
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👑 Back to Admin Panel", callback_data="admin:panel")]])
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
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    if not context.args:
        _ADMIN_STATES[chat_id] = "awaiting_broadcast"
        await update.message.reply_text(
            "📢 <b>BROADCAST TO ALL SUBSCRIBERS</b>\n"
            "────────────────────────\n"
            "✍️ <b>Please send the message you want to broadcast below:</b>\n\n"
            "<i>(You can type standard text, paste an announcement, or use bold/links)</i>",
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
        text, kb = await get_contact_content()
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
        return

    user_message = update.message.text.partition(" ")[2].strip()

    # Forward to Admins
    if ADMIN_IDS:
        admin_alert = (
            "📩 <b>NEW CUSTOMER SUPPORT MESSAGE</b>\n"
            "────────────────────────\n"
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
        "Our admin has received your message and will reply to you directly in this bot.",
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
        "💬 <b>SUPPORT TEAM RESPONSE</b>\n"
        "────────────────────────\n"
        f"{reply_text}\n\n"
        "<i>To send another message, type /contact &lt;message&gt;</i>"
    )

    try:
        await context.bot.send_message(chat_id=target_id, text=msg_to_user, parse_mode="HTML")
        await update.message.reply_text(f"✅ Response successfully delivered to user <code>{target_id}</code>.", parse_mode="HTML")
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
        "⏳ <b>SAT LIVE COUNTDOWNS</b>\n"
        "────────────────────────\n"
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
    sched_lines = ["📅 <b>OFFICIAL SAT TESTING SCHEDULE</b>\n────────────────────────\n"]
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
        "👋 <b>Hello Everyone! SAT Notify Bot is now active in this group!</b>\n"
        "────────────────────────\n"
        "This group will now automatically receive:\n"
        "✨ <b>Test-Day Reminders & Checklists</b> (7 days & 1 day before exam)\n"
        "🌟 <b>Exam Morning Motivation</b>\n"
        "📢 <b>Instant Score Release Drops</b> on release days\n\n"
        "<b>Group Commands:</b>\n"
        "• /countdown - Live countdown to next exam & score drop\n"
        "• /schedule - Official College Board SAT calendar\n"
        "• /tips - Digital SAT checklist & pacing strategies\n"
        "• /timezone - Set group timezone"
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

        # Check Official Score Release Day
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
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("announce_scores", announce_scores_command))
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

    async with application:
        await application.start()

        webhook_base = os.getenv("WEBHOOK_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
        if webhook_base:
            webhook_url = f"{webhook_base}/webhook"
            await application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Telegram Webhook active on: %s", webhook_url)
        else:
            await application.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram Polling active.")

        scheduler_task = asyncio.create_task(background_scheduler_loop(application))
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        finally:
            if not webhook_base and application.updater:
                await application.updater.stop()
            await application.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
