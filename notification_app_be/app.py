"""
Campus Notification Platform — Backend REST API
================================================
Implements all endpoints from the notification system design (Stages 1–6).
Uses SQLite for persistence and a min-heap for the Stage 6 Priority Inbox.

Endpoints
---------
GET    /health
GET    /api/v1/notifications            ?student_id= &page= &limit= &type= &is_read=
GET    /api/v1/notifications/unread-count  ?student_id=
GET    /api/v1/notifications/priority      ?student_id= &n=10
GET    /api/v1/notifications/<id>          ?student_id=
POST   /api/v1/notifications
PATCH  /api/v1/notifications/<id>/read    ?student_id=
PATCH  /api/v1/notifications/read-all     ?student_id=
DELETE /api/v1/notifications/<id>         ?student_id=

Auth
----
Pre-authorised for this evaluation.  Pass student identity via either:
  Header:  X-Student-ID: 1042
  Query:   ?student_id=1042

Run
---
    set AUTH_TOKEN=<token>
    python app.py               # starts on port 5000
"""

import os
import sys
import uuid
import heapq
import sqlite3
import json
from datetime import datetime, timezone
from flask import Flask, jsonify, request

# Logging middleware (repo root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_middleware.logger import Log

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "notifications.db"),
)

VALID_TYPES = ("Event", "Result", "Placement")


def get_db() -> sqlite3.Connection:
    path = os.environ.get("DB_PATH", DATABASE)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id          TEXT    PRIMARY KEY,
            student_id  INTEGER NOT NULL,
            type        TEXT    NOT NULL
                CHECK(type IN ('Event', 'Result', 'Placement')),
            message     TEXT    NOT NULL,
            is_read     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_student_unread_time
            ON notifications (student_id, is_read, created_at DESC);
    """)
    conn.commit()
    conn.close()
    Log("backend", "info", "db", "SQLite database initialised with notifications table")


def row_to_dict(row) -> dict:
    return {
        "id":         row["id"],
        "student_id": row["student_id"],
        "type":       row["type"],
        "message":    row["message"],
        "is_read":    bool(row["is_read"]),
        "created_at": row["created_at"],
    }


# ── Priority Inbox (Stage 6) ──────────────────────────────────────────────────
TYPE_WEIGHT = {"Placement": 3, "Result": 2, "Event": 1}


def _top_n_inbox(notifications: list, n: int) -> list:
    """
    Min-heap of size n.  O(total × log n) time, O(n) space.
    Root = least-important notification currently in the top-n set.
    """
    heap: list = []
    counter = 0
    for notif in notifications:
        weight = TYPE_WEIGHT.get(notif["type"], 0)
        try:
            ts = datetime.fromisoformat(notif["created_at"]).timestamp()
        except (ValueError, TypeError):
            ts = 0.0
        entry = (weight, ts, counter, notif)
        if len(heap) < n:
            heapq.heappush(heap, entry)
        elif (weight, ts) > (heap[0][0], heap[0][1]):
            heapq.heapreplace(heap, entry)
        counter += 1
    return [e[3] for e in sorted(heap, key=lambda e: (e[0], e[1]), reverse=True)]


# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)


def _student_id() -> int | None:
    raw = request.headers.get("X-Student-ID") or request.args.get("student_id")
    try:
        return int(raw) if raw else None
    except (ValueError, TypeError):
        return None


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "not_found"}), 404


@app.errorhandler(400)
def bad_request(_e):
    return jsonify({"error": "bad_request"}), 400


@app.errorhandler(500)
def server_error(_e):
    return jsonify({"error": "internal_server_error"}), 500


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    Log("backend", "info", "route", "Health check requested")
    return jsonify({"status": "ok", "service": "campus-notification-api"})


@app.route("/api/v1/notifications", methods=["GET"])
def list_notifications():
    student_id = _student_id()
    if not student_id:
        Log("backend", "warn", "handler",
            "GET /notifications called without student_id")
        return jsonify({"error": "student_id is required (header X-Student-ID or query param)"}), 400

    page  = max(1, request.args.get("page", 1, type=int))
    limit = min(100, max(1, request.args.get("limit", 20, type=int)))
    n_type   = request.args.get("type")
    is_read  = request.args.get("is_read")
    offset   = (page - 1) * limit

    if n_type and n_type not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {VALID_TYPES}"}), 400

    where  = ["student_id = ?"]
    params = [student_id]
    if n_type:
        where.append("type = ?");  params.append(n_type)
    if is_read is not None:
        where.append("is_read = ?")
        params.append(1 if is_read.lower() == "true" else 0)

    sql_where = " AND ".join(where)
    conn = get_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM notifications WHERE {sql_where}", params
        ).fetchone()[0]
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE student_id=? AND is_read=0",
            [student_id],
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM notifications WHERE {sql_where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()

    Log("backend", "info", "handler",
        f"Fetched {len(rows)} notifications for student_id={student_id} "
        f"(page={page}, limit={limit})")
    return jsonify({
        "data": [row_to_dict(r) for r in rows],
        "meta": {"page": page, "limit": limit, "total": total, "unread_count": unread},
    })


@app.route("/api/v1/notifications/unread-count", methods=["GET"])
def unread_count():
    student_id = _student_id()
    if not student_id:
        return jsonify({"error": "student_id is required"}), 400

    conn = get_db()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE student_id=? AND is_read=0",
            [student_id],
        ).fetchone()[0]
    finally:
        conn.close()

    Log("backend", "info", "handler",
        f"Unread count for student_id={student_id}: {count}")
    return jsonify({"student_id": student_id, "unread_count": count})


@app.route("/api/v1/notifications/priority", methods=["GET"])
def priority_inbox():
    student_id = _student_id()
    if not student_id:
        return jsonify({"error": "student_id is required"}), 400

    n = min(100, max(1, request.args.get("n", 10, type=int)))

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM notifications "
            "WHERE student_id=? AND is_read=0 ORDER BY created_at DESC",
            [student_id],
        ).fetchall()
    finally:
        conn.close()

    notifications = [row_to_dict(r) for r in rows]
    top = _top_n_inbox(notifications, n)

    Log("backend", "info", "service",
        f"Priority inbox for student_id={student_id}: top {n} of {len(notifications)} unread")
    return jsonify({"top_n": n, "total_unread": len(notifications), "notifications": top})


@app.route("/api/v1/notifications/<notif_id>", methods=["GET"])
def get_notification(notif_id: str):
    student_id = _student_id()
    conn = get_db()
    try:
        if student_id:
            row = conn.execute(
                "SELECT * FROM notifications WHERE id=? AND student_id=?",
                [notif_id, student_id],
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM notifications WHERE id=?", [notif_id]
            ).fetchone()
    finally:
        conn.close()

    if not row:
        Log("backend", "warn", "handler",
            f"Notification not found: id={notif_id}")
        return jsonify({"error": "notification_not_found"}), 404

    Log("backend", "info", "handler", f"Fetched notification id={notif_id}")
    return jsonify(row_to_dict(row))


@app.route("/api/v1/notifications", methods=["POST"])
def create_notification():
    data = request.get_json(silent=True)
    if not data:
        Log("backend", "warn", "handler",
            "POST /notifications called with empty or non-JSON body")
        return jsonify({"error": "JSON body required"}), 400

    student_id = data.get("student_id")
    n_type     = data.get("type")
    message    = data.get("message", "").strip()

    if not all([student_id, n_type, message]):
        Log("backend", "warn", "handler",
            "POST /notifications missing required fields: student_id, type, message")
        return jsonify({"error": "student_id, type, and message are required"}), 400

    if n_type not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {VALID_TYPES}"}), 400

    notif_id = str(uuid.uuid4())
    now      = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO notifications (id, student_id, type, message, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [notif_id, student_id, n_type, message, now],
        )
        conn.commit()
    finally:
        conn.close()

    Log("backend", "info", "handler",
        f"Notification created: id={notif_id} student_id={student_id} type={n_type}")
    return jsonify({
        "id":         notif_id,
        "student_id": student_id,
        "type":       n_type,
        "message":    message,
        "is_read":    False,
        "created_at": now,
    }), 201


@app.route("/api/v1/notifications/read-all", methods=["PATCH"])
def mark_all_read():
    student_id = _student_id()
    if not student_id:
        return jsonify({"error": "student_id is required"}), 400

    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE notifications SET is_read=1 WHERE student_id=? AND is_read=0",
            [student_id],
        )
        conn.commit()
        updated = cur.rowcount
    finally:
        conn.close()

    Log("backend", "info", "handler",
        f"Marked all {updated} notifications as read for student_id={student_id}")
    return jsonify({"updated": updated})


@app.route("/api/v1/notifications/<notif_id>/read", methods=["PATCH"])
def mark_one_read(notif_id: str):
    student_id = _student_id()
    conn = get_db()
    try:
        if student_id:
            cur = conn.execute(
                "UPDATE notifications SET is_read=1 WHERE id=? AND student_id=?",
                [notif_id, student_id],
            )
        else:
            cur = conn.execute(
                "UPDATE notifications SET is_read=1 WHERE id=?", [notif_id]
            )
        conn.commit()
        updated = cur.rowcount
    finally:
        conn.close()

    if not updated:
        Log("backend", "warn", "handler",
            f"Mark-read failed — notification not found: id={notif_id}")
        return jsonify({"error": "notification_not_found"}), 404

    Log("backend", "info", "handler", f"Notification id={notif_id} marked as read")
    return jsonify({"updated": updated})


@app.route("/api/v1/notifications/<notif_id>", methods=["DELETE"])
def delete_notification(notif_id: str):
    student_id = _student_id()
    conn = get_db()
    try:
        if student_id:
            cur = conn.execute(
                "DELETE FROM notifications WHERE id=? AND student_id=?",
                [notif_id, student_id],
            )
        else:
            cur = conn.execute(
                "DELETE FROM notifications WHERE id=?", [notif_id]
            )
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()

    if not deleted:
        Log("backend", "warn", "handler",
            f"Delete failed — notification not found: id={notif_id}")
        return jsonify({"error": "notification_not_found"}), 404

    Log("backend", "info", "handler", f"Notification id={notif_id} deleted")
    return "", 204


# ── Startup ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    Log("backend", "info", "route",
        "Campus Notification API server starting on port 5000")
    app.run(debug=True, port=5000)
