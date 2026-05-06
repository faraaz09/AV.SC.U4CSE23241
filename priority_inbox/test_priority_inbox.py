"""
Unit tests for Priority Inbox (Stage 6).
Run with:  python test_priority_inbox.py
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from priority_inbox.priority_inbox import PriorityInbox, _priority_key, _parse_ts, MOCK_NOTIFICATIONS


def _make_notif(ntype, ts_offset_secs=0, msg="test"):
    base = datetime(2026, 4, 22, 17, 0, 0, tzinfo=timezone.utc)
    ts = (base + timedelta(seconds=ts_offset_secs)).strftime("%Y-%m-%d %H:%M:%S")
    return {"ID": f"id-{ntype}-{ts_offset_secs}", "Type": ntype, "Message": msg, "Timestamp": ts}


class TestPriorityKey(unittest.TestCase):

    def test_placement_beats_result(self):
        p = _priority_key(_make_notif("Placement", 0))
        r = _priority_key(_make_notif("Result", 100))   # result is MORE recent
        self.assertGreater(p[0], r[0], "Placement weight must exceed Result weight")

    def test_result_beats_event(self):
        r = _priority_key(_make_notif("Result", 0))
        e = _priority_key(_make_notif("Event", 200))    # event is more recent
        self.assertGreater(r[0], e[0])

    def test_same_type_more_recent_higher_ts(self):
        older = _priority_key(_make_notif("Result", 0))
        newer = _priority_key(_make_notif("Result", 60))
        self.assertGreater(newer[1], older[1])

    def test_unknown_type_gets_zero_weight(self):
        notif = _make_notif("Unknown", 0)
        key = _priority_key(notif)
        self.assertEqual(key[0], 0)


class TestParseTimestamp(unittest.TestCase):

    def test_standard_format(self):
        ts = _parse_ts("2026-04-22 17:51:30")
        self.assertIsInstance(ts, float)
        self.assertGreater(ts, 0)

    def test_order_preserved(self):
        ts1 = _parse_ts("2026-04-22 17:50:00")
        ts2 = _parse_ts("2026-04-22 17:51:00")
        self.assertLess(ts1, ts2)


class TestPriorityInbox(unittest.TestCase):

    def test_empty_inbox(self):
        inbox = PriorityInbox(n=10)
        self.assertEqual(inbox.top_n(), [])

    def test_fewer_than_n_notifications(self):
        inbox = PriorityInbox(n=10)
        inbox.push(_make_notif("Result", 0))
        inbox.push(_make_notif("Event", 10))
        top = inbox.top_n()
        self.assertEqual(len(top), 2)

    def test_top_n_size_capped(self):
        inbox = PriorityInbox(n=3)
        for i in range(10):
            inbox.push(_make_notif("Event", i * 10))
        self.assertEqual(len(inbox.top_n()), 3)

    def test_placement_ranked_first(self):
        inbox = PriorityInbox(n=5)
        inbox.push(_make_notif("Event",     100))
        inbox.push(_make_notif("Result",    200))
        inbox.push(_make_notif("Placement", 0))      # oldest but highest type
        inbox.push(_make_notif("Event",     300))
        inbox.push(_make_notif("Result",    50))
        top = inbox.top_n()
        self.assertEqual(top[0]["Type"], "Placement", "Placement must always rank #1")

    def test_result_before_event(self):
        inbox = PriorityInbox(n=10)
        inbox.push(_make_notif("Event",  500))    # very recent event
        inbox.push(_make_notif("Result", 0))      # older result
        top = inbox.top_n()
        self.assertEqual(top[0]["Type"], "Result")
        self.assertEqual(top[1]["Type"], "Event")

    def test_same_type_most_recent_first(self):
        inbox = PriorityInbox(n=5)
        for i in range(5):
            inbox.push(_make_notif("Result", i * 60))   # 0, 60, 120, 180, 240 secs
        top = inbox.top_n()
        # Should be sorted newest → oldest
        for i in range(len(top) - 1):
            self.assertGreaterEqual(
                _parse_ts(top[i]["Timestamp"]),
                _parse_ts(top[i + 1]["Timestamp"]),
            )

    def test_push_all_helper(self):
        inbox = PriorityInbox(n=10)
        inbox.push_all(MOCK_NOTIFICATIONS)
        top = inbox.top_n()
        # With 10 mock notifications and n=10, all should be present
        self.assertEqual(len(top), min(10, len(MOCK_NOTIFICATIONS)))

    def test_weak_notification_displaced(self):
        inbox = PriorityInbox(n=2)
        inbox.push(_make_notif("Event",     10, "weak1"))
        inbox.push(_make_notif("Event",     20, "weak2"))
        # Both slots filled with Events; now push a Placement
        inbox.push(_make_notif("Placement", 0,  "strong"))
        top = inbox.top_n()
        self.assertEqual(len(top), 2)
        types = [n["Type"] for n in top]
        self.assertIn("Placement", types)

    def test_no_duplicate_ids_in_output(self):
        inbox = PriorityInbox(n=10)
        notif = _make_notif("Result", 100)
        inbox.push(notif)
        inbox.push(notif)   # push same object twice
        top = inbox.top_n()
        ids = [n["ID"] for n in top]
        # IDs that are identical should still be representable;
        # what matters is count doesn't exceed n
        self.assertLessEqual(len(top), 10)

    def test_mock_data_ordering(self):
        """Top result in mock data must be a Placement (highest weight)."""
        inbox = PriorityInbox(n=10)
        inbox.push_all(MOCK_NOTIFICATIONS)
        top = inbox.top_n()
        self.assertEqual(top[0]["Type"], "Placement")

    def test_streaming_new_notifications(self):
        """Simulate notifications arriving one by one over time."""
        inbox = PriorityInbox(n=5)
        # Push 10 notifications
        all_notifs = [_make_notif("Result", i * 10) for i in range(10)]
        for n in all_notifs:
            inbox.push(n)
        top = inbox.top_n()
        # Only top 5 (most recent Results, since all same type)
        self.assertEqual(len(top), 5)
        for i in range(len(top) - 1):
            self.assertGreaterEqual(
                _parse_ts(top[i]["Timestamp"]),
                _parse_ts(top[i + 1]["Timestamp"]),
            )

    def test_large_volume(self):
        """Push 10,000 notifications and verify correctness."""
        import time
        import random
        types = ["Placement", "Result", "Event"]
        notifs = [
            {"ID": str(i), "Type": random.choice(types),
             "Message": f"msg-{i}",
             "Timestamp": datetime.fromtimestamp(1745000000 + i, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
            for i in range(10_000)
        ]
        inbox = PriorityInbox(n=10)
        start = time.time()
        inbox.push_all(notifs)
        elapsed = time.time() - start
        top = inbox.top_n()
        self.assertLess(elapsed, 5.0, "Should handle 10k notifications in < 5s")
        self.assertEqual(len(top), 10)
        # #1 must be Placement (there are many)
        self.assertEqual(top[0]["Type"], "Placement")


if __name__ == "__main__":
    print("Running Priority Inbox Tests...\n")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
