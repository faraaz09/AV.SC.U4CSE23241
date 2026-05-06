"""
Unit tests for the Vehicle Maintenance Scheduler.
Run: python test_scheduler.py
"""

import os
import sys
import time
import unittest

os.environ["TESTING"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vehicle_maintence_scheduler.scheduler import knapsack, schedule_depot, MOCK_DEPOTS, MOCK_VEHICLES


class TestKnapsack(unittest.TestCase):

    def test_empty_tasks_returns_zero(self):
        impact, chosen = knapsack([], 100)
        self.assertEqual(impact, 0)
        self.assertEqual(chosen, [])

    def test_zero_capacity_returns_zero(self):
        tasks = [{"TaskID": "t1", "Duration": 2, "Impact": 5}]
        impact, chosen = knapsack(tasks, 0)
        self.assertEqual(impact, 0)
        self.assertEqual(chosen, [])

    def test_single_task_fits(self):
        tasks = [{"TaskID": "t1", "Duration": 3, "Impact": 7}]
        impact, chosen = knapsack(tasks, 5)
        self.assertEqual(impact, 7)
        self.assertEqual(len(chosen), 1)

    def test_single_task_does_not_fit(self):
        tasks = [{"TaskID": "t1", "Duration": 10, "Impact": 9}]
        impact, chosen = knapsack(tasks, 5)
        self.assertEqual(impact, 0)
        self.assertEqual(chosen, [])

    def test_classic_three_item_example(self):
        tasks = [
            {"TaskID": "A", "Duration": 2, "Impact": 3},
            {"TaskID": "B", "Duration": 3, "Impact": 4},
            {"TaskID": "C", "Duration": 4, "Impact": 5},
        ]
        impact, chosen = knapsack(tasks, 5)
        self.assertEqual(impact, 7)
        ids = {t["TaskID"] for t in chosen}
        self.assertEqual(ids, {"A", "B"})

    def test_all_tasks_fit(self):
        tasks = [
            {"TaskID": "A", "Duration": 1, "Impact": 10},
            {"TaskID": "B", "Duration": 2, "Impact": 5},
            {"TaskID": "C", "Duration": 3, "Impact": 8},
        ]
        impact, chosen = knapsack(tasks, 100)
        self.assertEqual(impact, 23)
        self.assertEqual(len(chosen), 3)

    def test_dp_beats_greedy(self):
        # Greedy (by density) picks A (ratio=5), optimal is B+C (impact=21)
        tasks = [
            {"TaskID": "A", "Duration": 3, "Impact": 15},
            {"TaskID": "B", "Duration": 2, "Impact": 10},
            {"TaskID": "C", "Duration": 2, "Impact": 11},
        ]
        impact, chosen = knapsack(tasks, 4)
        self.assertEqual(impact, 21)
        ids = {t["TaskID"] for t in chosen}
        self.assertIn("B", ids)
        self.assertIn("C", ids)

    def test_chosen_within_capacity(self):
        tasks = [
            {"TaskID": str(i), "Duration": i % 5 + 1, "Impact": i % 10 + 1}
            for i in range(20)
        ]
        capacity = 30
        impact, chosen = knapsack(tasks, capacity)
        total_dur = sum(t["Duration"] for t in chosen)
        self.assertLessEqual(total_dur, capacity)
        self.assertEqual(sum(t["Impact"] for t in chosen), impact)

    def test_impact_is_optimal_vs_brute_force(self):
        tasks = [
            {"TaskID": str(i), "Duration": (i % 4) + 1, "Impact": (i % 7) + 1}
            for i in range(10)
        ]
        capacity = 15
        dp_impact, _ = knapsack(tasks, capacity)

        best = 0
        for mask in range(1 << len(tasks)):
            dur = imp = 0
            for j in range(len(tasks)):
                if mask & (1 << j):
                    dur += tasks[j]["Duration"]
                    imp += tasks[j]["Impact"]
            if dur <= capacity and imp > best:
                best = imp

        self.assertEqual(dp_impact, best)

    def test_500_tasks_under_10_seconds(self):
        tasks = [
            {"TaskID": str(i), "Duration": (i % 8) + 1, "Impact": (i % 10) + 1}
            for i in range(500)
        ]
        start = time.time()
        impact, chosen = knapsack(tasks, 188)
        elapsed = time.time() - start
        self.assertLess(elapsed, 10.0)
        self.assertLessEqual(sum(t["Duration"] for t in chosen), 188)

    def test_no_duplicate_tasks_in_result(self):
        tasks = [{"TaskID": "X", "Duration": 2, "Impact": 6},
                 {"TaskID": "Y", "Duration": 2, "Impact": 6}]
        _, chosen = knapsack(tasks, 2)
        self.assertEqual(len(chosen), 1)


class TestScheduleDepot(unittest.TestCase):

    def test_result_has_required_fields(self):
        depot = {"ID": 3, "MechanicHours": 10}
        tasks = [
            {"TaskID": "t1", "Duration": 3, "Impact": 7},
            {"TaskID": "t2", "Duration": 4, "Impact": 5},
        ]
        r = schedule_depot(depot, tasks)
        for field in ("DepotID", "MechanicHoursAvailable", "MechanicHoursUsed",
                      "TotalImpact", "TasksSelected", "Tasks"):
            self.assertIn(field, r)

    def test_hours_used_never_exceeds_budget(self):
        for depot in MOCK_DEPOTS:
            r = schedule_depot(depot, MOCK_VEHICLES)
            self.assertLessEqual(r["MechanicHoursUsed"], r["MechanicHoursAvailable"],
                                 f"Depot {depot['ID']} exceeded budget")

    def test_hours_used_matches_sum_of_chosen_tasks(self):
        depot = {"ID": 1, "MechanicHours": 60}
        r = schedule_depot(depot, MOCK_VEHICLES)
        self.assertEqual(r["MechanicHoursUsed"],
                         sum(t["Duration"] for t in r["Tasks"]))

    def test_impact_matches_sum_of_chosen_tasks(self):
        depot = {"ID": 2, "MechanicHours": 50}
        r = schedule_depot(depot, MOCK_VEHICLES)
        self.assertEqual(r["TotalImpact"],
                         sum(t["Impact"] for t in r["Tasks"]))

    def test_tasks_selected_count_matches_list(self):
        depot = {"ID": 4, "MechanicHours": 97}
        r = schedule_depot(depot, MOCK_VEHICLES)
        self.assertEqual(r["TasksSelected"], len(r["Tasks"]))

    def test_positive_impact_for_all_mock_depots(self):
        for depot in MOCK_DEPOTS:
            r = schedule_depot(depot, MOCK_VEHICLES)
            self.assertGreater(r["TotalImpact"], 0,
                               f"Depot {depot['ID']} produced zero impact")

    def test_empty_task_list(self):
        depot = {"ID": 1, "MechanicHours": 60}
        r = schedule_depot(depot, [])
        self.assertEqual(r["TotalImpact"], 0)
        self.assertEqual(r["TasksSelected"], 0)


if __name__ == "__main__":
    print("Running Vehicle Maintenance Scheduler Tests...\n")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
