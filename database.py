import asyncio
import json
import os
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from config import DB_PATH, DATABASE_URL

logger = logging.getLogger(__name__)

# Default Timezone: Tashkent, Uzbekistan (UZT, UTC+5)
DEFAULT_TIMEZONE = "Asia/Tashkent"

# In-memory timezone cache for instant lookups without DB queries
_TIMEZONE_CACHE = {}

# Paths for snapshot backups (preserves subscriber state across container restarts and git deployments)
_DISK_BACKUP_PATH = os.path.join(os.path.dirname(DB_PATH) or ".", "subscribers_snapshot.json")
_REPO_BACKUP_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), "subscribers_snapshot.json")


@contextmanager
def _get_db():
    """Context manager for SQLite connections that ensures connections are closed and WAL mode is active."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception as e:
            logger.warning("Could not create database directory %s: %s", db_dir, e)

    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        yield conn
    finally:
        conn.close()


def _save_snapshot_sync():
    """Saves active and historical subscribers to JSON snapshot files, merging existing records so no user is ever lost."""
    try:
        # 1. Load existing records from snapshot files if present
        existing_map: dict[int, dict] = {}
        for path in [_DISK_BACKUP_PATH, _REPO_BACKUP_PATH]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            for r in data:
                                if isinstance(r, dict) and "chat_id" in r:
                                    existing_map[r["chat_id"]] = r
                except Exception as ex:
                    logger.debug("Could not read existing snapshot at %s: %s", path, ex)

        # 2. Merge records from current SQLite DB
        with _get_db() as conn:
            cursor = conn.execute("SELECT chat_id, username, first_name, timezone, is_active, subscribed_at, updated_at FROM subscribers")
            for row in cursor.fetchall():
                row_dict = dict(row)
                cid = row_dict["chat_id"]
                if cid in existing_map:
                    # Preserve earliest subscribed_at
                    old_sub = existing_map[cid].get("subscribed_at")
                    new_sub = row_dict.get("subscribed_at")
                    if old_sub and (not new_sub or old_sub < new_sub):
                        row_dict["subscribed_at"] = old_sub
                existing_map[cid] = row_dict

        rows = list(existing_map.values())

        # 3. Write merged list to both disk backup and repo backup
        for path in {_DISK_BACKUP_PATH, _REPO_BACKUP_PATH}:
            backup_dir = os.path.dirname(path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("Failed to write snapshot backup: %s", e)


def _restore_snapshot_sync():
    """Restores/merges subscribers from JSON snapshot into SQLite. Never skips even if DB already has records."""
    records_map: dict[int, dict] = {}
    for path in [_DISK_BACKUP_PATH, _REPO_BACKUP_PATH]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for r in data:
                            if isinstance(r, dict) and "chat_id" in r:
                                records_map[r["chat_id"]] = r
            except Exception as e:
                logger.warning("Error reading snapshot from %s: %s", path, e)

    if not records_map:
        return

    try:
        with _get_db() as conn:
            restored = 0
            for r in records_map.values():
                tz = r.get("timezone") or DEFAULT_TIMEZONE
                if tz in ("US/Eastern", "UTC"):
                    tz = DEFAULT_TIMEZONE

                conn.execute(
                    f"""
                    INSERT INTO subscribers (chat_id, username, first_name, timezone, is_active, subscribed_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        username = coalesce(excluded.username, subscribers.username),
                        first_name = coalesce(excluded.first_name, subscribers.first_name),
                        timezone = CASE
                            WHEN subscribers.timezone IS NULL OR subscribers.timezone = '' OR subscribers.timezone = 'US/Eastern' OR subscribers.timezone = 'UTC'
                            THEN coalesce(excluded.timezone, '{DEFAULT_TIMEZONE}')
                            ELSE subscribers.timezone
                        END,
                        is_active = max(subscribers.is_active, excluded.is_active),
                        subscribed_at = coalesce(subscribers.subscribed_at, excluded.subscribed_at),
                        updated_at = max(coalesce(subscribers.updated_at, ''), coalesce(excluded.updated_at, ''))
                    """,
                    (
                        r["chat_id"],
                        r.get("username"),
                        r.get("first_name"),
                        tz,
                        r.get("is_active", 1),
                        r.get("subscribed_at"),
                        r.get("updated_at"),
                    ),
                )
                restored += 1
            conn.commit()
            if restored > 0:
                logger.info("Successfully merged/restored %d subscribers from snapshots", restored)
    except Exception as e:
        logger.warning("Error restoring subscribers from snapshot: %s", e)


def _init_db_sync():
    with _get_db() as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                timezone TEXT DEFAULT '{DEFAULT_TIMEZONE}',
                is_active INTEGER DEFAULT 1,
                subscribed_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """)
        
        # Check if timezone column exists (for seamless migration)
        cursor = conn.execute("PRAGMA table_info(subscribers)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "timezone" not in columns:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN timezone TEXT DEFAULT '{DEFAULT_TIMEZONE}'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT UNIQUE,
                sent_at TIMESTAMP,
                recipient_count INTEGER
            );
        """)
        
        # Migrate any legacy 'US/Eastern', 'UTC', or blank records to Asia/Tashkent
        conn.execute(f"UPDATE subscribers SET timezone = '{DEFAULT_TIMEZONE}' WHERE timezone = 'US/Eastern' OR timezone = 'UTC' OR timezone IS NULL OR timezone = '';")
        conn.commit()

    _restore_snapshot_sync()
    logger.info("Database initialized with WAL mode at %s (Default Timezone: %s)", DB_PATH, DEFAULT_TIMEZONE)


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
                f"INSERT INTO subscribers (chat_id, username, first_name, timezone, is_active, subscribed_at, updated_at) VALUES (?, ?, ?, '{DEFAULT_TIMEZONE}', 1, ?, ?)",
                (chat_id, username, first_name, now, now),
            )
            conn.commit()
            _save_snapshot_sync()
            return True
        elif row["is_active"] == 0:
            conn.execute(
                "UPDATE subscribers SET is_active = 1, username = ?, first_name = ?, updated_at = ? WHERE chat_id = ?",
                (username, first_name, now, chat_id),
            )
            conn.commit()
            _save_snapshot_sync()
            return True
        else:
            conn.execute(
                "UPDATE subscribers SET username = ?, first_name = ?, updated_at = ? WHERE chat_id = ?",
                (username, first_name, now, chat_id),
            )
            conn.commit()
            _save_snapshot_sync()
            return False


async def add_or_reactivate_subscriber(chat_id: int, username: str | None, first_name: str | None) -> bool:
    """Adds a subscriber or reactivates an existing one. Returns True if newly subscribed/reactivated."""
    return await asyncio.to_thread(_add_or_reactivate_subscriber_sync, chat_id, username, first_name)


def _unsubscribe_user_sync(chat_id: int) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        cursor = conn.execute("UPDATE subscribers SET is_active = 0, updated_at = ? WHERE chat_id = ?", (now, chat_id))
        conn.commit()
        _save_snapshot_sync()
        return cursor.rowcount > 0


async def unsubscribe_user(chat_id: int) -> bool:
    """Deactivates notifications for a user."""
    return await asyncio.to_thread(_unsubscribe_user_sync, chat_id)


def _reactivate_all_subscribers_sync() -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        cursor = conn.execute("UPDATE subscribers SET is_active = 1, updated_at = ?", (now,))
        conn.commit()
        _save_snapshot_sync()
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
        _save_snapshot_sync()
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
        tz = row["timezone"] if row and row["timezone"] else DEFAULT_TIMEZONE
        _TIMEZONE_CACHE[chat_id] = tz
        return tz


async def get_user_timezone(chat_id: int) -> str:
    """Gets a user's timezone (default: Asia/Tashkent)."""
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


def _get_all_subscribers_sync() -> list[dict]:
    with _get_db() as conn:
        cursor = conn.execute(
            "SELECT chat_id, username, first_name, timezone, is_active, subscribed_at, updated_at FROM subscribers ORDER BY subscribed_at ASC"
        )
        return [dict(row) for row in cursor.fetchall()]


async def get_all_subscribers() -> list[dict]:
    """Returns a list of all subscribers (both active and inactive) ever registered."""
    return await asyncio.to_thread(_get_all_subscribers_sync)


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
