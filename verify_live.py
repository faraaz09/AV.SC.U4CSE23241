"""
Live endpoint verification for Campus Notification Backend.
Starts the Flask app in-process (test client) and exercises every endpoint.
Reports PASS / FAIL per scenario with a final summary.
"""

import os
import sys
import tempfile

os.environ["TESTING"] = "1"
_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = _TEST_DB

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notification_app_be.app import app, init_db

app.testing = True
client = app.test_client()
init_db()

PASS = 0
FAIL = 0


def check(label, actual_status, expected_status, extra_check=None, extra_label=""):
    global PASS, FAIL
    status_ok = actual_status == expected_status
    extra_ok = extra_check() if extra_check else True
    if status_ok and extra_ok:
        print("  PASS  " + label)
        PASS += 1
    else:
        reasons = []
        if not status_ok:
            reasons.append("status " + str(actual_status) + " != " + str(expected_status))
        if not extra_ok:
            reasons.append(extra_label or "body check failed")
        print("  FAIL  " + label + "  [" + ", ".join(reasons) + "]")
        FAIL += 1


def sid(n):
    return {"X-Student-ID": str(n)}


def create(student_id, n_type="Placement", message="test msg"):
    return client.post(
        "/api/v1/notifications",
        json={"student_id": student_id, "type": n_type, "message": message},
        content_type="application/json",
    )


print("\n========== Health ==========")
r = client.get("/health")
check("GET /health -> 200", r.status_code, 200,
      lambda: r.get_json().get("status") == "ok", "status != ok")

print("\n========== Create Notification ==========")
r = create(1, "Placement", "TCS hiring")
body = r.get_json()
created_id = body.get("id")
check("POST Placement -> 201", r.status_code, 201,
      lambda: body.get("type") == "Placement" and body.get("is_read") is False,
      "type or is_read wrong")

r = create(1, "Result", "mid-sem results out")
check("POST Result -> 201", r.status_code, 201,
      lambda: r.get_json().get("type") == "Result", "type != Result")

r = create(1, "Event", "farewell party")
check("POST Event -> 201", r.status_code, 201,
      lambda: r.get_json().get("type") == "Event", "type != Event")

r = create(1, "Unknown", "bad type")
check("POST invalid type -> 400", r.status_code, 400)

r = client.post("/api/v1/notifications",
                json={"student_id": 1, "type": "Event"},
                content_type="application/json")
check("POST missing message -> 400", r.status_code, 400)

r = client.post("/api/v1/notifications",
                json={"type": "Event", "message": "no sid"},
                content_type="application/json")
check("POST missing student_id -> 400", r.status_code, 400)

r = client.post("/api/v1/notifications",
                data="not json", content_type="text/plain")
check("POST non-JSON body -> 400", r.status_code, 400)

print("\n========== List Notifications ==========")
r = client.get("/api/v1/notifications")
check("GET list without X-Student-ID -> 400", r.status_code, 400)

create(20, "Result", "exam result")
r = client.get("/api/v1/notifications", headers=sid(20))
body = r.get_json()
check("GET list student=20 -> 200 with data+meta", r.status_code, 200,
      lambda: "data" in body and "meta" in body, "missing data or meta")
check("GET list returns >= 1 item", r.status_code, 200,
      lambda: len(body.get("data", [])) >= 1, "empty data")

create(21, "Placement", "p1")
create(21, "Event",     "e1")
r = client.get("/api/v1/notifications?type=Placement", headers=sid(21))
types = [n["type"] for n in r.get_json().get("data", [])]
check("GET list filter type=Placement -> only Placement", r.status_code, 200,
      lambda: all(t == "Placement" for t in types), "got unexpected types: " + str(types))

create(22, "Event", "evt")
r = client.get("/api/v1/notifications?is_read=false", headers=sid(22))
reads = [n["is_read"] for n in r.get_json().get("data", [])]
check("GET list filter is_read=false -> all unread", r.status_code, 200,
      lambda: all(not rd for rd in reads), "some are read")

for i in range(5):
    create(23, message="msg " + str(i))
r = client.get("/api/v1/notifications?page=1&limit=2", headers=sid(23))
body = r.get_json()
check("GET list pagination limit=2 -> meta.limit==2", r.status_code, 200,
      lambda: body["meta"]["limit"] == 2, "meta.limit != 2")
check("GET list pagination limit=2 -> <=2 items", r.status_code, 200,
      lambda: len(body["data"]) <= 2, "got " + str(len(body.get("data", []))) + " items")

r = client.get("/api/v1/notifications?type=BadType", headers=sid(1))
check("GET list invalid type filter -> 400", r.status_code, 400)

print("\n========== Get Single Notification ==========")
r2 = create(24)
single_id = r2.get_json()["id"]
r = client.get("/api/v1/notifications/" + single_id, headers=sid(24))
check("GET /notifications/<id> -> 200", r.status_code, 200,
      lambda: r.get_json()["id"] == single_id, "id mismatch")

r = client.get("/api/v1/notifications/no-such-id")
check("GET nonexistent id -> 404", r.status_code, 404)

print("\n========== Mark as Read ==========")
mark_id = create(25).get_json()["id"]
r = client.patch("/api/v1/notifications/" + mark_id + "/read", headers=sid(25))
check("PATCH /<id>/read -> 200 updated=1", r.status_code, 200,
      lambda: r.get_json().get("updated") == 1, "updated != 1")
r2 = client.get("/api/v1/notifications/" + mark_id)
check("GET after mark-read -> is_read True", r2.status_code, 200,
      lambda: r2.get_json()["is_read"] is True, "is_read still False")

r = client.patch("/api/v1/notifications/fake-id/read", headers=sid(1))
check("PATCH nonexistent id/read -> 404", r.status_code, 404)

for _ in range(3):
    create(26, "Event", "e")
r = client.patch("/api/v1/notifications/read-all", headers=sid(26))
check("PATCH /read-all -> 200 updated>=3", r.status_code, 200,
      lambda: r.get_json().get("updated", 0) >= 3, "updated < 3")

r = client.patch("/api/v1/notifications/read-all")
check("PATCH /read-all without student-id -> 400", r.status_code, 400)

print("\n========== Delete Notification ==========")
del_id = create(27).get_json()["id"]
r = client.delete("/api/v1/notifications/" + del_id, headers=sid(27))
check("DELETE /<id> -> 204", r.status_code, 204)
r2 = client.get("/api/v1/notifications/" + del_id)
check("GET deleted id -> 404", r2.status_code, 404)

r = client.delete("/api/v1/notifications/ghost-id", headers=sid(1))
check("DELETE nonexistent -> 404", r.status_code, 404)

print("\n========== Unread Count ==========")
create(30, "Placement")
create(30, "Event")
r = client.get("/api/v1/notifications/unread-count", headers=sid(30))
check("GET /unread-count -> 200 count>=2", r.status_code, 200,
      lambda: r.get_json().get("unread_count", 0) >= 2, "count < 2")

create(31, "Result")
before = client.get("/api/v1/notifications/unread-count",
                    headers=sid(31)).get_json()["unread_count"]
client.patch("/api/v1/notifications/read-all", headers=sid(31))
after = client.get("/api/v1/notifications/unread-count",
                   headers=sid(31)).get_json()["unread_count"]
check("Unread count decreases after read-all", 200, 200,
      lambda: after < before, "after=" + str(after) + " not < before=" + str(before))

print("\n========== Priority Inbox ==========")
r = client.get("/api/v1/notifications/priority")
check("GET /priority without student-id -> 400", r.status_code, 400)

for t in ["Event", "Result", "Placement"]:
    create(40, t, t + " msg")
r = client.get("/api/v1/notifications/priority?n=10", headers=sid(40))
body = r.get_json()
check("GET /priority -> 200 with notifications key", r.status_code, 200,
      lambda: "notifications" in body, "missing notifications key")

create(41, "Event",     "evt")
create(41, "Result",    "res")
create(41, "Placement", "placement")
r = client.get("/api/v1/notifications/priority?n=10", headers=sid(41))
top = r.get_json().get("notifications", [])
first_type = top[0]["type"] if top else "empty"
check("GET /priority -> Placement first", r.status_code, 200,
      lambda: len(top) > 0 and top[0]["type"] == "Placement",
      "first type is " + first_type)

n_id = create(42, "Result", "r").get_json()["id"]
create(42, "Placement", "p")
client.patch("/api/v1/notifications/" + n_id + "/read", headers=sid(42))
r = client.get("/api/v1/notifications/priority?n=10", headers=sid(42))
notifs = r.get_json().get("notifications", [])
check("GET /priority -> only unread items", r.status_code, 200,
      lambda: all(not n["is_read"] for n in notifs),
      "some read notifications in priority inbox")

print("\n" + "=" * 50)
total = PASS + FAIL
print("Results: " + str(PASS) + "/" + str(total) + " passed, " + str(FAIL) + " failed")
print("=" * 50)

import os as _os
_os.unlink(_TEST_DB) if _os.path.exists(_TEST_DB) else None

sys.exit(0 if FAIL == 0 else 1)
