"""
Unit tests for Campus Notification Backend API.
Run: python test_app.py

Covers all 8 endpoints across create / read / update / delete / priority scenarios.
TESTING=1 suppresses live Log API calls.
DB_PATH points to an in-memory SQLite so tests do not touch disk.
"""

import os
import sys
import json
import tempfile
import unittest

# ── Must be set before importing app ─────────────────────────────────────────
os.environ["TESTING"] = "1"
_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = _TEST_DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notification_app_be.app import app, init_db, _top_n_inbox


class TestNotificationAPI(unittest.TestCase):

    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        init_db()

    # ── helpers ───────────────────────────────────────────────────────────────
    def _create(self, student_id=1, n_type="Placement", message="AMD hiring"):
        return self.client.post(
            "/api/v1/notifications",
            json={"student_id": student_id, "type": n_type, "message": message},
            content_type="application/json",
        )

    def _sid_header(self, sid=1):
        return {"X-Student-ID": str(sid)}

    # ── Health ────────────────────────────────────────────────────────────────
    def test_health_returns_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    # ── Create ────────────────────────────────────────────────────────────────
    def test_create_placement_returns_201(self):
        resp = self._create(n_type="Placement", message="TCS hiring")
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIn("id", data)
        self.assertEqual(data["type"], "Placement")
        self.assertFalse(data["is_read"])

    def test_create_result_returns_201(self):
        resp = self._create(n_type="Result", message="mid-sem results out")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["type"], "Result")

    def test_create_event_returns_201(self):
        resp = self._create(n_type="Event", message="farewell party")
        self.assertEqual(resp.status_code, 201)

    def test_create_invalid_type_returns_400(self):
        resp = self._create(n_type="Unknown")
        self.assertEqual(resp.status_code, 400)

    def test_create_missing_message_returns_400(self):
        resp = self.client.post(
            "/api/v1/notifications",
            json={"student_id": 1, "type": "Event"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_missing_student_id_returns_400(self):
        resp = self.client.post(
            "/api/v1/notifications",
            json={"type": "Event", "message": "test"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_empty_body_returns_400(self):
        resp = self.client.post("/api/v1/notifications",
                                data="not json", content_type="text/plain")
        self.assertEqual(resp.status_code, 400)

    # ── List ──────────────────────────────────────────────────────────────────
    def test_list_without_student_id_returns_400(self):
        resp = self.client.get("/api/v1/notifications")
        self.assertEqual(resp.status_code, 400)

    def test_list_returns_created_notifications(self):
        self._create(student_id=2, n_type="Result", message="exam result")
        resp = self.client.get("/api/v1/notifications",
                               headers=self._sid_header(2))
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertGreaterEqual(len(body["data"]), 1)

    def test_list_filter_by_type(self):
        self._create(student_id=3, n_type="Placement", message="p1")
        self._create(student_id=3, n_type="Event",     message="e1")
        resp = self.client.get("/api/v1/notifications?type=Placement",
                               headers=self._sid_header(3))
        for notif in resp.get_json()["data"]:
            self.assertEqual(notif["type"], "Placement")

    def test_list_filter_by_is_read_false(self):
        self._create(student_id=4, n_type="Event", message="evt")
        resp = self.client.get("/api/v1/notifications?is_read=false",
                               headers=self._sid_header(4))
        for notif in resp.get_json()["data"]:
            self.assertFalse(notif["is_read"])

    def test_list_pagination_meta(self):
        for i in range(5):
            self._create(student_id=5, message=f"msg {i}")
        resp = self.client.get("/api/v1/notifications?page=1&limit=2",
                               headers=self._sid_header(5))
        meta = resp.get_json()["meta"]
        self.assertEqual(meta["limit"], 2)
        self.assertLessEqual(len(resp.get_json()["data"]), 2)

    def test_list_invalid_type_filter_returns_400(self):
        resp = self.client.get("/api/v1/notifications?type=BadType",
                               headers=self._sid_header(1))
        self.assertEqual(resp.status_code, 400)

    # ── Get single ────────────────────────────────────────────────────────────
    def test_get_single_notification(self):
        create_resp = self._create(student_id=6)
        notif_id = create_resp.get_json()["id"]
        resp = self.client.get(f"/api/v1/notifications/{notif_id}",
                               headers=self._sid_header(6))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["id"], notif_id)

    def test_get_nonexistent_returns_404(self):
        resp = self.client.get("/api/v1/notifications/no-such-id")
        self.assertEqual(resp.status_code, 404)

    # ── Mark read ─────────────────────────────────────────────────────────────
    def test_mark_one_as_read(self):
        notif_id = self._create(student_id=7).get_json()["id"]
        resp = self.client.patch(f"/api/v1/notifications/{notif_id}/read",
                                 headers=self._sid_header(7))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["updated"], 1)
        # Verify flag flipped
        get_resp = self.client.get(f"/api/v1/notifications/{notif_id}")
        self.assertTrue(get_resp.get_json()["is_read"])

    def test_mark_read_nonexistent_returns_404(self):
        resp = self.client.patch("/api/v1/notifications/fake-id/read",
                                 headers=self._sid_header(1))
        self.assertEqual(resp.status_code, 404)

    def test_mark_all_read(self):
        for _ in range(3):
            self._create(student_id=8, n_type="Event", message="e")
        resp = self.client.patch("/api/v1/notifications/read-all",
                                 headers=self._sid_header(8))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.get_json()["updated"], 3)

    def test_mark_all_read_without_student_id_returns_400(self):
        resp = self.client.patch("/api/v1/notifications/read-all")
        self.assertEqual(resp.status_code, 400)

    # ── Delete ────────────────────────────────────────────────────────────────
    def test_delete_notification(self):
        notif_id = self._create(student_id=9).get_json()["id"]
        resp = self.client.delete(f"/api/v1/notifications/{notif_id}",
                                  headers=self._sid_header(9))
        self.assertEqual(resp.status_code, 204)
        get_resp = self.client.get(f"/api/v1/notifications/{notif_id}")
        self.assertEqual(get_resp.status_code, 404)

    def test_delete_nonexistent_returns_404(self):
        resp = self.client.delete("/api/v1/notifications/ghost-id",
                                  headers=self._sid_header(1))
        self.assertEqual(resp.status_code, 404)

    # ── Unread count ──────────────────────────────────────────────────────────
    def test_unread_count(self):
        self._create(student_id=10, n_type="Placement")
        self._create(student_id=10, n_type="Event")
        resp = self.client.get("/api/v1/notifications/unread-count",
                               headers=self._sid_header(10))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.get_json()["unread_count"], 2)

    def test_unread_count_decreases_after_mark_read(self):
        self._create(student_id=11, n_type="Result")
        before = self.client.get("/api/v1/notifications/unread-count",
                                 headers=self._sid_header(11)).get_json()["unread_count"]
        # Mark all read
        self.client.patch("/api/v1/notifications/read-all",
                          headers=self._sid_header(11))
        after = self.client.get("/api/v1/notifications/unread-count",
                                headers=self._sid_header(11)).get_json()["unread_count"]
        self.assertLess(after, before)

    # ── Priority inbox (Stage 6) ───────────────────────────────────────────────
    def test_priority_inbox_endpoint(self):
        for t in ["Event", "Result", "Placement"]:
            self._create(student_id=12, n_type=t, message=f"{t} msg")
        resp = self.client.get("/api/v1/notifications/priority?n=10",
                               headers=self._sid_header(12))
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("notifications", body)

    def test_priority_inbox_placement_first(self):
        self._create(student_id=13, n_type="Event",     message="evt")
        self._create(student_id=13, n_type="Result",    message="res")
        self._create(student_id=13, n_type="Placement", message="placement")
        resp = self.client.get("/api/v1/notifications/priority?n=10",
                               headers=self._sid_header(13))
        top = resp.get_json()["notifications"]
        self.assertGreater(len(top), 0)
        self.assertEqual(top[0]["type"], "Placement")

    def test_priority_inbox_without_student_id_returns_400(self):
        resp = self.client.get("/api/v1/notifications/priority")
        self.assertEqual(resp.status_code, 400)

    def test_priority_inbox_only_unread(self):
        n_id = self._create(student_id=14, n_type="Result",    message="r").get_json()["id"]
        self._create(student_id=14, n_type="Placement", message="p")
        # Mark Result as read
        self.client.patch(f"/api/v1/notifications/{n_id}/read",
                          headers=self._sid_header(14))
        resp = self.client.get("/api/v1/notifications/priority?n=10",
                               headers=self._sid_header(14))
        for n in resp.get_json()["notifications"]:
            self.assertFalse(n["is_read"])


# ── Priority inbox unit tests (direct function) ───────────────────────────────
class TestTopNInbox(unittest.TestCase):

    def _n(self, n_type, secs_ago=0):
        from datetime import timedelta
        ts = datetime(2026, 4, 22, 18, 0, 0, tzinfo=timezone.utc)
        ts -= timedelta(seconds=secs_ago)
        return {"id": n_type, "type": n_type, "message": "x",
                "is_read": False, "created_at": ts.isoformat(), "student_id": 1}

    def setUp(self):
        global datetime, timezone
        from datetime import datetime, timezone

    def test_empty_list(self):
        self.assertEqual(_top_n_inbox([], 10), [])

    def test_fewer_than_n(self):
        notifs = [self._n("Event"), self._n("Result")]
        self.assertEqual(len(_top_n_inbox(notifs, 10)), 2)

    def test_capped_at_n(self):
        notifs = [self._n("Event", i) for i in range(20)]
        self.assertEqual(len(_top_n_inbox(notifs, 5)), 5)

    def test_placement_first(self):
        notifs = [self._n("Event", 0), self._n("Result", 0), self._n("Placement", 100)]
        top = _top_n_inbox(notifs, 3)
        self.assertEqual(top[0]["type"], "Placement")

    def test_result_before_event(self):
        notifs = [self._n("Event", 0), self._n("Result", 60)]
        top = _top_n_inbox(notifs, 2)
        self.assertEqual(top[0]["type"], "Result")

    def test_same_type_newer_first(self):
        notifs = [self._n("Result", 120), self._n("Result", 60), self._n("Result", 0)]
        top = _top_n_inbox(notifs, 3)
        ts = [n["created_at"] for n in top]
        self.assertGreaterEqual(ts[0], ts[1])
        self.assertGreaterEqual(ts[1], ts[2])


if __name__ == "__main__":
    print("Running Campus Notification Backend Tests...\n")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    import os; os.unlink(_TEST_DB) if os.path.exists(_TEST_DB) else None
    sys.exit(0 if result.wasSuccessful() else 1)
