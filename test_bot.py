import asyncio
import os
import unittest
import urllib.request
import json
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
        if os.path.exists("test_sat_bot.db"):
            os.remove("test_sat_bot.db")
        await database.init_db()

    async def asyncTearDown(self):
        if os.path.exists("test_sat_bot.db"):
            os.remove("test_sat_bot.db")

    async def test_subscriber_management(self):
        # Add a new subscriber
        is_new = await database.add_or_reactivate_subscriber(
            chat_id=1001,
            username="testuser",
            first_name="Test",
        )
        self.assertTrue(is_new)

        active = await database.get_active_subscribers()
        self.assertIn(1001, active)

        stats = await database.get_subscriber_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["active"], 1)

        # Unsubscribe
        unsub_ok = await database.unsubscribe_user(1001)
        self.assertTrue(unsub_ok)

        active_after = await database.get_active_subscribers()
        self.assertNotIn(1001, active_after)

        # Reactivate
        reactivated = await database.add_or_reactivate_subscriber(
            chat_id=1001,
            username="testuser",
            first_name="Test",
        )
        self.assertTrue(reactivated)
        active_final = await database.get_active_subscribers()
        self.assertIn(1001, active_final)

    async def test_notification_deduplication(self):
        event_key = "test_event_2026"
        self.assertFalse(await database.is_notification_sent(event_key))

        await database.mark_notification_sent(event_key, recipient_count=10)
        self.assertTrue(await database.is_notification_sent(event_key))

    def test_schedule_and_countdown_logic(self):
        upcoming = config.get_upcoming_tests()
        self.assertIsInstance(upcoming, list)

        next_test = config.get_next_test()
        if next_test:
            self.assertIn("name", next_test)
            self.assertIn("test_date", next_test)

        next_score = config.get_next_score_release()
        if next_score:
            self.assertIn("name", next_score)
            self.assertIn("score_release_date", next_score)

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

    async def test_web_server_health_endpoints(self):
        server = await web_server.start_web_server(port=8099)
        try:
            # Test /health
            reader, writer = await asyncio.open_connection("127.0.0.1", 8099)
            writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()
            raw_response = await reader.read(4096)
            writer.close()
            await writer.wait_closed()

            response_str = raw_response.decode("utf-8")
            self.assertIn("HTTP/1.1 200 OK", response_str)
            self.assertIn('"status": "healthy"', response_str)
            self.assertIn('"service": "sat-telegram-notify-bot"', response_str)

            # Test / (HTML home)
            reader, writer = await asyncio.open_connection("127.0.0.1", 8099)
            writer.write(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()
            raw_response = await reader.read(4096)
            writer.close()
            await writer.wait_closed()

            response_str = raw_response.decode("utf-8")
            self.assertIn("HTTP/1.1 200 OK", response_str)
            self.assertIn("SAT Notify Bot", response_str)
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
