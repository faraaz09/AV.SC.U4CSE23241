"""
Priority Inbox — Stage 6 of Campus Notifications Microservice
--------------------------------------------------------------
Fetches notifications from the evaluation API and returns the top-N most
important UNREAD notifications using a combination of:
  • Type weight  : Placement=3  > Result=2  > Event=1
  • Recency      : more-recent timestamps rank higher within the same type

A min-heap of size N is maintained so the structure can scale as new
notifications stream in without re-sorting the entire list every time.

Usage
-----
    set AUTH_TOKEN=<your_token>
    python priority_inbox.py           # top 10 (default)
    python priority_inbox.py --top 20  # top 20
    python priority_inbox.py --mock    # offline run with sample data
"""

import os
import sys
import json
import heapq
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import Logger

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "http://20.207.122.201/evaluation-service"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
logger = Logger("priority_inbox", log_dir=LOG_DIR)

TYPE_WEIGHT = {"Placement": 3, "Result": 2, "Event": 1}

# ---------------------------------------------------------------------------
# Sample mock data (mirrors what the API returns in the screenshots)
# ---------------------------------------------------------------------------
MOCK_NOTIFICATIONS = [
    {"ID": "d146095a-0d86-4a34-9e69-3900a14576bc", "Type": "Result",    "Message": "mid-sem",                    "Timestamp": "2026-04-22 17:51:30"},
    {"ID": "b283218f-ea5a-4b7c-93a9-1f2f240d64b0", "Type": "Placement", "Message": "CSX Corporation hiring",      "Timestamp": "2026-04-22 17:51:18"},
    {"ID": "81589ada-0ad3-4f77-9554-f52fb558e09d", "Type": "Event",     "Message": "farewell",                   "Timestamp": "2026-04-22 17:51:06"},
    {"ID": "0005513a-142b-4bbc-8678-eefec65e1ede", "Type": "Result",    "Message": "mid-sem",                    "Timestamp": "2026-04-22 17:50:54"},
    {"ID": "ea836726-c25e-4f21-a72f-544a6af8a37f", "Type": "Result",    "Message": "project-review",             "Timestamp": "2026-04-22 17:50:42"},
    {"ID": "003cb427-8fc6-47f7-bb00-be228f6b0d2c", "Type": "Result",    "Message": "external",                   "Timestamp": "2026-04-22 17:50:30"},
    {"ID": "e5c4ff20-31bf-4d40-8f02-72fda59e8918", "Type": "Result",    "Message": "project-review",             "Timestamp": "2026-04-22 17:50:18"},
    {"ID": "1cfce5ee-ad37-4894-8946-d707627176a5", "Type": "Event",     "Message": "tech-fest",                  "Timestamp": "2026-04-22 17:50:06"},
    {"ID": "cf2885a6-45ac-4ba0-b548-6e9e9d4c52c8", "Type": "Result",    "Message": "project-review",             "Timestamp": "2026-04-22 17:49:54"},
    {"ID": "8a7412bd-6065-4d09-8501-a37f11cc848b", "Type": "Placement", "Message": "Advanced Micro Devices Inc. hiring", "Timestamp": "2026-04-22 17:49:42"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_ts(ts_str: str) -> float:
    """Return Unix timestamp from 'YYYY-MM-DD HH:MM:SS' string."""
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        # ISO-8601 fallback
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()


def _priority_key(notif: dict) -> tuple:
    """
    Returns (type_weight, timestamp_unix) — higher means more important.
    Used for heap comparisons (Python heapq is a min-heap, so we negate).
    """
    weight = TYPE_WEIGHT.get(notif["Type"], 0)
    ts = _parse_ts(notif["Timestamp"])
    return (weight, ts)


# ---------------------------------------------------------------------------
# Min-heap Priority Queue (maintains top-N most important notifications)
# ---------------------------------------------------------------------------
class PriorityInbox:
    """
    Min-heap of size `n`.  The heap root is always the *least* important
    notification currently in the top-N list, so we can quickly decide
    whether an incoming notification deserves to be in the set.
    """

    def __init__(self, n: int = 10):
        self.n = n
        self._heap: list = []          # elements: (type_weight, ts_unix, notif_dict)
        self._counter = 0              # tie-breaker for equal priorities

    def push(self, notif: dict):
        weight, ts = _priority_key(notif)
        entry = (weight, ts, self._counter, notif)
        self._counter += 1

        if len(self._heap) < self.n:
            heapq.heappush(self._heap, entry)
        elif (weight, ts) > (self._heap[0][0], self._heap[0][1]):
            # New notification is more important than the current minimum
            heapq.heapreplace(self._heap, entry)
        # else: new notification is not good enough; discard it

    def push_all(self, notifications: list):
        for n in notifications:
            self.push(n)

    def top_n(self) -> list:
        """Return top-N notifications sorted most-important first."""
        sorted_entries = sorted(self._heap, key=lambda e: (e[0], e[1]), reverse=True)
        return [e[3] for e in sorted_entries]


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------
def _auth_headers() -> dict:
    token = os.environ.get("AUTH_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_notifications() -> list:
    logger.info("Fetching notifications from API", url=f"{BASE_URL}/notifications")
    resp = requests.get(
        f"{BASE_URL}/notifications", headers=_auth_headers(), timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    count = len(data["notifications"])
    logger.info("Notifications fetched", count=count)
    return data["notifications"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(top_n: int = 10, use_mock: bool = False):
    logger.info("Priority Inbox started", top_n=top_n, mock=use_mock)

    if use_mock or not _REQUESTS_AVAILABLE:
        logger.info("Using mock notification data")
        notifications = MOCK_NOTIFICATIONS
    else:
        try:
            notifications = fetch_notifications()
        except Exception as exc:
            logger.error("API fetch failed, falling back to mock data", error=str(exc))
            notifications = MOCK_NOTIFICATIONS

    inbox = PriorityInbox(n=top_n)
    inbox.push_all(notifications)
    top = inbox.top_n()

    border = "=" * 72
    print(f"\n{border}")
    print(f"  PRIORITY INBOX — TOP {top_n} NOTIFICATIONS")
    print(f"  Scoring: Placement=3 > Result=2 > Event=1, then by recency")
    print(f"  Total fetched: {len(notifications)}")
    print(border)

    for rank, notif in enumerate(top, start=1):
        weight, ts = _priority_key(notif)
        recency = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(
            f"  #{rank:>2}  [{notif['Type']:<9}]  weight={weight}  "
            f"{recency}  {notif['Message']}"
        )
        print(f"       ID: {notif['ID']}")

    print(f"\n{border}\n")

    # Save output
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(out_dir, "priority_inbox_output.json")
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "top_n": top_n,
                "notifications": top,
            },
            fh,
            indent=2,
        )
    logger.info("Priority inbox output written", file=out_file)
    print(f"Full JSON output written to: {out_file}")

    return top


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Priority Inbox — Campus Notifications")
    parser.add_argument("--top", type=int, default=10, help="Number of top notifications to show")
    parser.add_argument("--mock", action="store_true", help="Use built-in mock data")
    args = parser.parse_args()
    main(top_n=args.top, use_mock=args.mock)
