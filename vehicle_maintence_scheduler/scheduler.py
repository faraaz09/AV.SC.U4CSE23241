"""
Vehicle Maintenance Scheduler
==============================
For each depot (with a fixed mechanic-hour budget), find the optimal subset
of maintenance tasks that maximises total operational impact score without
exceeding the available mechanic hours — a 0/1 Knapsack problem solved with
bottom-up dynamic programming.

Complexity: O(n × W) per depot  |  n = #tasks, W = mechanic-hour budget

Usage
-----
    set AUTH_TOKEN=<token>      # enables Log API + data API auth
    python scheduler.py         # fetch live data from evaluation service
    python scheduler.py --mock  # offline run with built-in sample data
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

# Allow imports from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_middleware.logger import Log

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── API ───────────────────────────────────────────────────────────────────────
BASE_URL = "http://20.207.122.201/evaluation-service"


def _auth_headers() -> dict:
    token = os.environ.get("AUTH_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_depots() -> list:
    Log("backend", "info", "service", "Fetching depot list from evaluation API")
    resp = requests.get(f"{BASE_URL}/depots", headers=_auth_headers(), timeout=15)
    resp.raise_for_status()
    depots = resp.json()["depots"]
    Log("backend", "info", "service", f"Fetched {len(depots)} depots from API")
    return depots


def fetch_vehicles() -> list:
    Log("backend", "info", "service", "Fetching vehicle task list from evaluation API")
    resp = requests.get(f"{BASE_URL}/vehicles", headers=_auth_headers(), timeout=15)
    resp.raise_for_status()
    vehicles = resp.json()["vehicles"]
    Log("backend", "info", "service", f"Fetched {len(vehicles)} vehicle tasks from API")
    return vehicles


# ── Mock data (mirrored from screenshots) ────────────────────────────────────
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


# ── Knapsack solver ───────────────────────────────────────────────────────────

def knapsack(tasks: list, capacity: int) -> tuple[int, list]:
    """
    0/1 Knapsack via bottom-up DP.
    Returns (max_impact, list_of_chosen_tasks).
    Time O(n·W), Space O(n·W) for backtracking.
    """
    n = len(tasks)
    dp = [[0] * (capacity + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dur = tasks[i - 1]["Duration"]
        imp = tasks[i - 1]["Impact"]
        for w in range(capacity + 1):
            dp[i][w] = dp[i - 1][w]
            if w >= dur:
                take = dp[i - 1][w - dur] + imp
                if take > dp[i][w]:
                    dp[i][w] = take

    # Backtrack to recover chosen tasks
    chosen, w = [], capacity
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            chosen.append(tasks[i - 1])
            w -= tasks[i - 1]["Duration"]

    return dp[n][capacity], chosen


# ── Per-depot scheduling ──────────────────────────────────────────────────────

def schedule_depot(depot: dict, tasks: list) -> dict:
    dep_id   = depot["ID"]
    capacity = depot["MechanicHours"]

    Log("backend", "info", "service",
        f"Scheduling depot {dep_id}: budget={capacity}h, available_tasks={len(tasks)}")

    max_impact, chosen = knapsack(tasks, capacity)
    hours_used = sum(t["Duration"] for t in chosen)

    Log("backend", "info", "service",
        f"Depot {dep_id} scheduled: tasks={len(chosen)}, "
        f"hours_used={hours_used}/{capacity}, impact={max_impact}")

    return {
        "DepotID":               dep_id,
        "MechanicHoursAvailable": capacity,
        "MechanicHoursUsed":     hours_used,
        "TotalImpact":           max_impact,
        "TasksSelected":         len(chosen),
        "Tasks": [
            {"TaskID": t["TaskID"], "Duration": t["Duration"], "Impact": t["Impact"]}
            for t in chosen
        ],
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main(use_mock: bool = False):
    Log("backend", "info", "service",
        f"Vehicle Maintenance Scheduler started (mock={use_mock})")

    if use_mock or not _REQUESTS_OK:
        depots  = MOCK_DEPOTS
        vehicles = MOCK_VEHICLES
    else:
        try:
            depots   = fetch_depots()
            vehicles = fetch_vehicles()
        except Exception as exc:
            Log("backend", "error", "service",
                f"API fetch failed: {exc} — falling back to mock data")
            depots   = MOCK_DEPOTS
            vehicles = MOCK_VEHICLES

    results = [schedule_depot(d, vehicles) for d in depots]

    sep = "=" * 72
    print(f"\n{sep}")
    print("  VEHICLE MAINTENANCE SCHEDULE")
    print(f"  Generated : {datetime.now(timezone.utc).isoformat()}")
    print(sep)

    for r in results:
        util = round(r["MechanicHoursUsed"] / r["MechanicHoursAvailable"] * 100, 1)
        print(f"\nDepot {r['DepotID']}")
        print(f"  Budget      : {r['MechanicHoursAvailable']} h")
        print(f"  Used        : {r['MechanicHoursUsed']} h  ({util}% utilisation)")
        print(f"  Total Impact: {r['TotalImpact']}")
        print(f"  Tasks       : {r['TasksSelected']}")
        for t in r["Tasks"]:
            print(f"    • {t['TaskID']}  dur={t['Duration']}h  impact={t['Impact']}")

    print(f"\n{sep}\n")

    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_output.json")
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "schedule": results},
            fh, indent=2,
        )
    Log("backend", "info", "service", f"Schedule results written to {out_file}")
    print(f"Full JSON saved to: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vehicle Maintenance Scheduler")
    parser.add_argument("--mock", action="store_true",
                        help="Use built-in mock data instead of live API")
    args = parser.parse_args()
    main(use_mock=args.mock)
