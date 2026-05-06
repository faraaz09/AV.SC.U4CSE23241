"""
Vehicle Maintenance Scheduler
-------------------------------
For each depot (with a fixed mechanic-hour budget), find the optimal subset
of maintenance tasks that maximises total operational impact without exceeding
the available hours.  This is a classic 0/1 Knapsack problem solved with
bottom-up dynamic programming.

Usage
-----
    # With real API (set AUTH_TOKEN env var):
    set AUTH_TOKEN=<your_token>
    python scheduler.py

    # Mock / offline run:
    python scheduler.py --mock
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

# Allow imports from parent directory
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
logger = Logger("vehicle_scheduler", log_dir=LOG_DIR)

# ---------------------------------------------------------------------------
# Mock data (used when --mock flag is set or API is unavailable)
# ---------------------------------------------------------------------------
MOCK_DEPOTS = [
    {"ID": 1, "MechanicHours": 60},
    {"ID": 2, "MechanicHours": 135},
    {"ID": 3, "MechanicHours": 188},
    {"ID": 4, "MechanicHours": 97},
    {"ID": 5, "MechanicHours": 164},
]

MOCK_VEHICLES = [
    {"TaskID": "264e638f-1c7a-4d67-9f9c-53f3d1766d37", "Duration": 1, "Impact": 5},
    {"TaskID": "73ce9dca-1536-4a7a-9f1e-c67083afad61", "Duration": 6, "Impact": 2},
    {"TaskID": "4b6e22ee-b4ed-45a4-a6af-5294b0d69f37", "Duration": 1, "Impact": 3},
    {"TaskID": "d6372f32-852b-46a9-8e8c-e730fecc3c22", "Duration": 5, "Impact": 5},
    {"TaskID": "ec40b581-bdfc-43e0-a047-871fdafe8167", "Duration": 7, "Impact": 3},
    {"TaskID": "fb1e3165-67c9-4e96-a5c3-2d20085d293b", "Duration": 6, "Impact": 3},
    {"TaskID": "330065c0-3815-4e10-a18a-b93b117e30a8", "Duration": 5, "Impact": 1},
    {"TaskID": "72a91abc-4ed7-492c-9e99-348e7437953b", "Duration": 5, "Impact": 9},
    {"TaskID": "8a7ff5b1-335c-4a2f-96d8-09c4a362e781", "Duration": 6, "Impact": 10},
    {"TaskID": "18c655b2-380d-4295-8905-863f0de32c8f", "Duration": 2, "Impact": 9},
    {"TaskID": "436e87a6-2b5b-42b9-9c35-deaa2c8ef54e", "Duration": 2, "Impact": 3},
    {"TaskID": "0a823f1b-03c3-4722-af40-e17a7b9ee0ff", "Duration": 2, "Impact": 5},
    {"TaskID": "0bf780cb-1099-4f61-99bf-dec95a7063b6", "Duration": 3, "Impact": 10},
    {"TaskID": "e716fb11-1064-4db7-9d76-06d19f4f6f67", "Duration": 5, "Impact": 5},
    {"TaskID": "60586e47-ab9c-407d-85ca-1215084f3f41", "Duration": 8, "Impact": 8},
    {"TaskID": "08635e52-dad5-4b78-8ab1-e55db53c0c18", "Duration": 8, "Impact": 5},
    {"TaskID": "871ddcf5-0bba-4233-bf12-c776c496e314", "Duration": 7, "Impact": 10},
    {"TaskID": "b57f17dc-db77-42bf-a7e9-8fec596ce498", "Duration": 7, "Impact": 8},
    {"TaskID": "1d893de7-fbba-4c77-927b-e3076fe805d5", "Duration": 1, "Impact": 8},
    {"TaskID": "1743e1b5-9dfd-450b-9905-98c3e054aee1", "Duration": 5, "Impact": 8},
    {"TaskID": "48851915-eaf5-48ec-a20c-5074d7050c5f", "Duration": 8, "Impact": 8},
    {"TaskID": "7d81e6ca-8f03-4c4a-9ec0-701f820c5655", "Duration": 7, "Impact": 8},
    {"TaskID": "08d00114-9506-463d-ba2e-3343ec4e2e89", "Duration": 6, "Impact": 6},
    {"TaskID": "a1e0b8e6-1076-4a2f-b83b-5e6017900033", "Duration": 6, "Impact": 1},
    {"TaskID": "52635341-7c5f-475a-9839-4676f8fe5fd4", "Duration": 1, "Impact": 5},
    {"TaskID": "9e08defa-7bb5-4a83-9e29-417165922894", "Duration": 6, "Impact": 9},
    {"TaskID": "f92b0f39-35ec-47c3-a465-3e49c22185b6", "Duration": 2, "Impact": 5},
    {"TaskID": "65c0d74a-82ef-4fcc-9d85-9b082bb85310", "Duration": 5, "Impact": 7},
    {"TaskID": "68ee2f8d-4145-4472-bce9-1d0968a8092a", "Duration": 1, "Impact": 1},
    {"TaskID": "8a294532-c7ee-4e19-803d-f98b7e73e8bc", "Duration": 8, "Impact": 7},
]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def _auth_headers() -> dict:
    token = os.environ.get("AUTH_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_depots() -> list:
    logger.info("Fetching depots from API", url=f"{BASE_URL}/depots")
    resp = requests.get(f"{BASE_URL}/depots", headers=_auth_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    logger.info("Depots fetched", count=len(data["depots"]))
    return data["depots"]


def fetch_vehicles() -> list:
    logger.info("Fetching vehicles/tasks from API", url=f"{BASE_URL}/vehicles")
    resp = requests.get(f"{BASE_URL}/vehicles", headers=_auth_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    logger.info("Vehicles fetched", count=len(data["vehicles"]))
    return data["vehicles"]


# ---------------------------------------------------------------------------
# Knapsack solver  (0/1 DP, O(n·W) time, O(n·W) space for backtracking)
# ---------------------------------------------------------------------------
def knapsack(tasks: list, capacity: int):
    """
    Returns (max_impact, selected_tasks).
    Uses full 2-D DP table so we can backtrack the exact chosen tasks.
    For very large n*W, a greedy fractional relaxation can be used as a
    fast heuristic; the DP remains exact.
    """
    n = len(tasks)
    # dp[i][w] = best impact using first i tasks with budget w hours
    dp = [[0] * (capacity + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dur = tasks[i - 1]["Duration"]
        imp = tasks[i - 1]["Impact"]
        for w in range(capacity + 1):
            dp[i][w] = dp[i - 1][w]          # skip this task
            if w >= dur:
                take = dp[i - 1][w - dur] + imp
                if take > dp[i][w]:
                    dp[i][w] = take           # include this task

    # Back-track to find chosen tasks
    selected = []
    w = capacity
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:         # task i was included
            selected.append(tasks[i - 1])
            w -= tasks[i - 1]["Duration"]

    return dp[n][capacity], selected


# ---------------------------------------------------------------------------
# Per-depot scheduling
# ---------------------------------------------------------------------------
def schedule_depot(depot: dict, tasks: list) -> dict:
    dep_id = depot["ID"]
    capacity = depot["MechanicHours"]

    logger.info(
        "Scheduling depot",
        depot_id=dep_id,
        budget_hours=capacity,
        available_tasks=len(tasks),
    )

    max_impact, chosen = knapsack(tasks, capacity)
    hours_used = sum(t["Duration"] for t in chosen)

    logger.info(
        "Depot scheduled",
        depot_id=dep_id,
        tasks_selected=len(chosen),
        hours_used=hours_used,
        total_impact=max_impact,
    )

    return {
        "DepotID": dep_id,
        "MechanicHoursAvailable": capacity,
        "MechanicHoursUsed": hours_used,
        "TotalImpact": max_impact,
        "TasksSelected": len(chosen),
        "Tasks": [
            {"TaskID": t["TaskID"], "Duration": t["Duration"], "Impact": t["Impact"]}
            for t in chosen
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(use_mock: bool = False):
    logger.info("Vehicle Maintenance Scheduler started", mock=use_mock)

    if use_mock or not _REQUESTS_AVAILABLE:
        logger.info("Using mock data")
        depots = MOCK_DEPOTS
        tasks = MOCK_VEHICLES
    else:
        try:
            depots = fetch_depots()
            tasks = fetch_vehicles()
        except Exception as exc:
            logger.error("API fetch failed, falling back to mock data", error=str(exc))
            depots = MOCK_DEPOTS
            tasks = MOCK_VEHICLES

    results = [schedule_depot(d, tasks) for d in depots]

    # ---- Print summary ----
    border = "=" * 70
    print(f"\n{border}")
    print("  VEHICLE MAINTENANCE SCHEDULE")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    print(border)

    for r in results:
        utilisation = (
            round(r["MechanicHoursUsed"] / r["MechanicHoursAvailable"] * 100, 1)
            if r["MechanicHoursAvailable"] > 0
            else 0
        )
        print(f"\nDepot {r['DepotID']}")
        print(f"  Budget : {r['MechanicHoursAvailable']} hours")
        print(f"  Used   : {r['MechanicHoursUsed']} hours  ({utilisation}% utilisation)")
        print(f"  Impact : {r['TotalImpact']}")
        print(f"  Tasks  : {r['TasksSelected']}")
        for t in r["Tasks"]:
            print(f"    • {t['TaskID']}  dur={t['Duration']}h  impact={t['Impact']}")

    print(f"\n{border}\n")

    # ---- Persist output ----
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(out_dir, "schedule_output.json")
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "schedule": results},
            fh,
            indent=2,
        )
    logger.info("Results written", file=out_file)
    print(f"Full JSON output written to: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vehicle Maintenance Scheduler")
    parser.add_argument(
        "--mock", action="store_true", help="Use built-in mock data instead of live API"
    )
    args = parser.parse_args()
    main(use_mock=args.mock)
