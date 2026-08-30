import asyncio
import sqlite3
import logging
from datetime import datetime, timezone
from config import DB_PATH

logger = logging.getLogger(__name__)


# In-memory timezone cache for instant lookups without DB queries
_TIMEZONE_CACHE = {}


def _get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def _init_db_sync():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                timezone TEXT DEFAULT 'US/Eastern',
                is_active INTEGER DEFAULT 1,
                subscribed_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """)
        
        # Check if timezone column exists (for seamless migration)
        cursor = conn.execute("PRAGMA table_info(subscribers)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "timezone" not in columns:
            conn.execute("ALTER TABLE subscribers ADD COLUMN timezone TEXT DEFAULT 'US/Eastern'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT UNIQUE,
                sent_at TIMESTAMP,
                recipient_count INTEGER
            );
        """)
        conn.commit()
    logger.info("Database initialized with WAL mode at %s", DB_PATH)


async def init_db():
    """Initializes SQLite database tables asynchronously."""
    await asyncio.to_thread(_init_db_sync)


def _add_or_reactivate_subscriber_sync(chat_id: int, username: str | None, first_name: str | None) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        cursor = conn.execute("SELECT is_active FROM subscribers WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO subscribers (chat_id, username, first_name, is_active, subscribed_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (chat_id, username, first_name, now, now),
            )
            conn.commit()
            return True
        elif row["is_active"] == 0:
            conn.execute(
                "UPDATE subscribers SET is_active = 1, username = ?, first_name = ?, updated_at = ? WHERE chat_id = ?",
                (username, first_name, now, chat_id),
            )
            conn.commit()
            return True
        else:
            conn.execute(
                "UPDATE subscribers SET username = ?, first_name = ?, updated_at = ? WHERE chat_id = ?",
                (username, first_name, now, chat_id),
            )
            conn.commit()
            return False


async def add_or_reactivate_subscriber(chat_id: int, username: str | None, first_name: str | None) -> bool:
    """Adds a subscriber or reactivates an existing one. Returns True if newly subscribed/reactivated."""
    return await asyncio.to_thread(_add_or_reactivate_subscriber_sync, chat_id, username, first_name)


def _unsubscribe_user_sync(chat_id: int) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        cursor = conn.execute("UPDATE subscribers SET is_active = 0, updated_at = ? WHERE chat_id = ?", (now, chat_id))
        conn.commit()
        return cursor.rowcount > 0


async def unsubscribe_user(chat_id: int) -> bool:
    """Deactivates notifications for a user."""
    return await asyncio.to_thread(_unsubscribe_user_sync, chat_id)


def _reactivate_all_subscribers_sync() -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        cursor = conn.execute("UPDATE subscribers SET is_active = 1, updated_at = ?", (now,))
        conn.commit()
        return cursor.rowcount


async def reactivate_all_subscribers() -> int:
    """Reactivates all registered users."""
    return await asyncio.to_thread(_reactivate_all_subscribers_sync)


def _set_user_timezone_sync(chat_id: int, tz_str: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    _TIMEZONE_CACHE[chat_id] = tz_str
    with _get_db() as conn:
        cursor = conn.execute("UPDATE subscribers SET timezone = ?, updated_at = ? WHERE chat_id = ?", (tz_str, now, chat_id))
        conn.commit()
        return cursor.rowcount > 0


async def set_user_timezone(chat_id: int, tz_str: str) -> bool:
    """Sets a user's timezone."""
    _TIMEZONE_CACHE[chat_id] = tz_str
    return await asyncio.to_thread(_set_user_timezone_sync, chat_id, tz_str)


def _get_user_timezone_sync(chat_id: int) -> str:
    if chat_id in _TIMEZONE_CACHE:
        return _TIMEZONE_CACHE[chat_id]

    with _get_db() as conn:
        cursor = conn.execute("SELECT timezone FROM subscribers WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        tz = row["timezone"] if row and row["timezone"] else "US/Eastern"
        _TIMEZONE_CACHE[chat_id] = tz
        return tz


async def get_user_timezone(chat_id: int) -> str:
    """Gets a user's timezone (default: US/Eastern)."""
    if chat_id in _TIMEZONE_CACHE:
        return _TIMEZONE_CACHE[chat_id]
    return await asyncio.to_thread(_get_user_timezone_sync, chat_id)


def _get_active_subscribers_sync() -> list[int]:
    with _get_db() as conn:
        cursor = conn.execute("SELECT chat_id FROM subscribers WHERE is_active = 1")
        rows = cursor.fetchall()
        return [row["chat_id"] for row in rows]


async def get_active_subscribers() -> list[int]:
    """Returns a list of all active chat IDs."""
    return await asyncio.to_thread(_get_active_subscribers_sync)


def _get_subscriber_stats_sync() -> dict:
    with _get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*), SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) FROM subscribers")
        row = cursor.fetchone()
        total = row[0] if row and row[0] is not None else 0
        active = row[1] if row and row[1] is not None else 0
        return {"total": total, "active": active}


async def get_subscriber_stats() -> dict:
    """Returns total and active subscriber counts."""
    return await asyncio.to_thread(_get_subscriber_stats_sync)


def _is_notification_sent_sync(event_key: str) -> bool:
    with _get_db() as conn:
        cursor = conn.execute("SELECT 1 FROM sent_notifications WHERE event_key = ?", (event_key,))
        return cursor.fetchone() is not None


async def is_notification_sent(event_key: str) -> bool:
    """Checks if a notification event has already been broadcasted."""
    return await asyncio.to_thread(_is_notification_sent_sync, event_key)


def _mark_notification_sent_sync(event_key: str, recipient_count: int):
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sent_notifications (event_key, sent_at, recipient_count) VALUES (?, ?, ?)",
            (event_key, now, recipient_count),
        )
        conn.commit()


async def mark_notification_sent(event_key: str, recipient_count: int):
    """Records that a notification has been sent so it won't be sent again."""
    await asyncio.to_thread(_mark_notification_sent_sync, event_key, recipient_count)
