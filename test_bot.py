import asyncio
import os
import unittest
from datetime import date, timedelta

# Set dummy environment variables for testing
os.environ["BOT_TOKEN"] = "123456789:TEST_MOCK_TOKEN"
os.environ["ADMIN_USER_ID"] = "111222333"
os.environ["DB_PATH"] = "test_sat_bot.db"
os.environ["PORT"] = "8099"

import config
import database
import web_server


class TestSATBot(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        database._DISK_BACKUP_PATH = "test_subscribers_snapshot.json"
        database._REPO_BACKUP_PATH = "test_subscribers_snapshot.json"
        for f in ["test_sat_bot.db", "test_sat_bot.db-shm", "test_sat_bot.db-wal", "test_subscribers_snapshot.json"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        await database.init_db()

    async def asyncTearDown(self):
        for f in ["test_sat_bot.db", "test_sat_bot.db-shm", "test_sat_bot.db-wal", "test_subscribers_snapshot.json"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    async def test_subscriber_and_timezone_management(self):
        # Add a new subscriber
        is_new = await database.add_or_reactivate_subscriber(
            chat_id=1001,
            username="testuser",
            first_name="Test",
        )
        self.assertTrue(is_new)

        # Check default timezone (Tashkent, Uzbekistan)
        tz = await database.get_user_timezone(1001)
        self.assertEqual(tz, "Asia/Tashkent")

        # Update timezone
        tz_ok = await database.set_user_timezone(1001, "US/Eastern")
        self.assertTrue(tz_ok)

        new_tz = await database.get_user_timezone(1001)
        self.assertEqual(new_tz, "US/Eastern")

        active = await database.get_active_subscribers()
        self.assertIn(1001, active)

        # Unsubscribe
        unsub_ok = await database.unsubscribe_user(1001)
        self.assertTrue(unsub_ok)

        active_after = await database.get_active_subscribers()
        self.assertNotIn(1001, active_after)

    async def test_snapshot_persistence_and_restore(self):
        # Add subscribers
        await database.add_or_reactivate_subscriber(1001, "user1", "User One")
        await database.add_or_reactivate_subscriber(1002, "user2", "User Two")
        await database.set_user_timezone(1002, "Europe/London")

        stats_before = await database.get_subscriber_stats()
        self.assertEqual(stats_before["active"], 2)

        # Simulate ephemeral container redeploy (db file deleted, snapshot remains)
        for f in ["test_sat_bot.db", "test_sat_bot.db-shm", "test_sat_bot.db-wal"]:
            if os.path.exists(f):
                os.remove(f)

        # Clear in-memory timezone cache
        database._TIMEZONE_CACHE.clear()

        # Re-initialize DB (as happens on bot startup)
        await database.init_db()

        # Check that subscribers were recovered from snapshot
        stats_after = await database.get_subscriber_stats()
        self.assertEqual(stats_after["active"], 2)
        self.assertEqual(stats_after["total"], 2)

        tz1 = await database.get_user_timezone(1001)
        tz2 = await database.get_user_timezone(1002)
        self.assertEqual(tz1, "Asia/Tashkent")
        self.assertEqual(tz2, "Europe/London")

    async def test_notification_deduplication(self):
        event_key = "test_event_2026"
        self.assertFalse(await database.is_notification_sent(event_key))

        await database.mark_notification_sent(event_key, recipient_count=10)
        self.assertTrue(await database.is_notification_sent(event_key))

    def test_schedule_and_countdown_logic(self):
        upcoming = config.get_upcoming_tests(tz_name="Asia/Tashkent")
        self.assertIsInstance(upcoming, list)

        next_test = config.get_next_test(tz_name="Asia/Tashkent")
        if next_test:
            self.assertIn("name", next_test)
            self.assertIn("test_date", next_test)

        next_score = config.get_next_score_release(tz_name="Asia/Tashkent")
        if next_score:
            self.assertIn("name", next_score)
            self.assertIn("score_release_date", next_score)

    def test_early_checker(self):
        import checker
        alerts = checker.fetch_collegeboard_alerts()
        self.assertIsInstance(alerts, list)
        is_early, details = checker.detect_early_score_release()
        self.assertIsInstance(is_early, bool)

    def test_templates_formatting(self):
        test_data = {
            "test_name": "October 2026 SAT",
            "test_date": "Saturday, October 3, 2026",
            "release_date": "Friday, October 16, 2026",
        }

        msg_7d = config.TEMPLATES["exam_7days"].format(**test_data)
        self.assertIn("7 Days Until", msg_7d)

        msg_1d = config.TEMPLATES["exam_1day"].format(**test_data)
        self.assertIn("Tomorrow is the", msg_1d)

        msg_morning = config.TEMPLATES["exam_morning"].format(**test_data)
        self.assertIn("GOOD LUCK", msg_morning)

        msg_scores = config.TEMPLATES["score_release_morning"].format(**test_data)
        self.assertIn("SCORES ARE RELEASING TODAY", msg_scores)
        self.assertIn("Tashkent Time", msg_scores)

        msg_scores_1d = config.TEMPLATES["score_release_1day"].format(**test_data)
        self.assertIn("SCORES RELEASE TOMORROW", msg_scores_1d)
        self.assertIn("Tashkent Time", msg_scores_1d)

    async def test_get_all_subscribers_and_historical_preservation(self):
        await database.add_or_reactivate_subscriber(chat_id=2001, username="decade_user", first_name="OldUser")
        await database.add_or_reactivate_subscriber(chat_id=2002, username="new_user", first_name="NewUser")
        
        # Deactivate one user to simulate unsubscription / blocked
        await database.unsubscribe_user(2001)

        # Active should be 1, but get_all_subscribers must show everyone
        active = await database.get_active_subscribers()
        self.assertIn(2002, active)
        self.assertNotIn(2001, active)

        all_subs = await database.get_all_subscribers()
        all_ids = [u["chat_id"] for u in all_subs]
        self.assertIn(2001, all_ids)
        self.assertIn(2002, all_ids)
        
        # User who joined earlier must have their join date and inactive status preserved
        u2001 = next(u for u in all_subs if u["chat_id"] == 2001)
        self.assertEqual(u2001["is_active"], 0)
        self.assertEqual(u2001["timezone"], "Asia/Tashkent")
        self.assertIsNotNone(u2001["subscribed_at"])

    def test_tashkent_permanent_timezone_lock(self):
        self.assertEqual(config.MAIN_TIMEZONE_NAME, "Asia/Tashkent")
        self.assertEqual(config.TIMEZONE_NAME, "Asia/Tashkent")
        tz = config.get_user_zoneinfo(None)
        self.assertIn(str(tz), ["Asia/Tashkent", "UTC+05:00"])
        # Legacy US/Eastern fallback must automatically redirect to Asia/Tashkent
        legacy_tz = config.get_user_zoneinfo("US/Eastern")
        self.assertIn(str(legacy_tz), ["Asia/Tashkent", "UTC+05:00"])

    async def test_web_server_health_endpoints(self):
        server = await web_server.start_web_server(port=8099)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 8099)
            writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()
            raw_response = await reader.read(4096)
            writer.close()
            await writer.wait_closed()

            response_str = raw_response.decode("utf-8")
            self.assertIn("HTTP/1.1 200 OK", response_str)
            self.assertIn('"status": "healthy"', response_str)
        finally:
            server.close()
            await server.wait_closed()

    async def test_ui_content_generators(self):
        import sys
        from unittest.mock import MagicMock
        if "telegram" not in sys.modules:
            mock_tg = MagicMock()
            sys.modules["telegram"] = mock_tg
            sys.modules["telegram.ext"] = mock_tg
            sys.modules["telegram.error"] = mock_tg
        import bot
        dash_text = await bot.get_dashboard_content(1001)
        self.assertIn("SAT Notify Dashboard", dash_text)
        self.assertIn("Timezone:", dash_text)

        sched_text = await bot.get_schedule_content(1001)
        self.assertIn("Official SAT Schedule", sched_text)

        countdown_text = await bot.get_countdown_content(1001)
        self.assertIn("Live SAT Countdowns", countdown_text)

        tips_text = await bot.get_tips_content()
        self.assertIn("Tips & Checklist", tips_text)

        tutors_text = await bot.get_tutors_content()
        self.assertIn("SAT Prep", tutors_text)

        contact_text = await bot.get_contact_content()
        self.assertIn("Contact & Support", contact_text)

        status_text = await bot.get_status_content(1001)
        self.assertIn("Notification Settings", status_text)

    async def test_admin_users_and_test_scores_commands(self):
        import sys
        from unittest.mock import MagicMock, AsyncMock
        if "telegram" not in sys.modules:
            mock_tg = MagicMock()
            sys.modules["telegram"] = mock_tg
            sys.modules["telegram.ext"] = mock_tg
            sys.modules["telegram.error"] = mock_tg
        import bot

        # Mock Update and Context
        update = MagicMock()
        update.effective_chat.id = 111222333  # Matches ADMIN_USER_ID
        update.effective_user.id = 111222333
        update.message.reply_text = AsyncMock()
        update.message.reply_document = AsyncMock()

        context = MagicMock()
        context.args = []
        context.bot.send_message = AsyncMock()

        # Add mock subscribers
        await database.add_or_reactivate_subscriber(chat_id=9001, username="student_one", first_name="Alice")
        await database.add_or_reactivate_subscriber(chat_id=9002, username="student_two", first_name="Bob")

        # Test /users command
        await bot.users_command(update, context)
        update.message.reply_text.assert_called()
        call_args = update.message.reply_text.call_args[0][0]
        self.assertIn("Registered Users Database", call_args)
        self.assertIn("Alice", call_args)
        self.assertIn("Bob", call_args)
        self.assertIn("Asia/Tashkent", call_args)

        # Test /test_scores command (private test preview)
        update.message.reply_text.reset_mock()
        await bot.test_scores_command(update, context)
        self.assertTrue(update.message.reply_text.call_count >= 2)
        score_preview = update.message.reply_text.call_args_list[0][0][0]
        self.assertIn("Test: 1 Day Before Score Release", score_preview)
        self.assertIn("Tashkent Time", score_preview)

        # Test /test_eve command
        update.message.reply_text.reset_mock()
        await bot.test_score_eve_command(update, context)
        eve_call = update.message.reply_text.call_args[0][0]
        self.assertIn("SCORES RELEASE TOMORROW", eve_call)


if __name__ == "__main__":
    unittest.main()
