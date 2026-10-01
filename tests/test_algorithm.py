"""
Unit tests for the Explainable Probability Discrepancy Algorithm.
Tests:
- Scoring calculation
- Recency exponential decay
- Probability normalization (sums to 100%)
- Positive and Negative evidence tracking
- Spatial proximity modeling
- Conflict detection
- Inactive location exclusion
- Explainability trail generation
- Baseline search comparison
"""

import unittest
from datetime import datetime, timedelta
from algorithm import find_discrepancy_locations, compute_recency_factor
from baseline import run_baseline_search, run_prototype_search
from utils import compute_location_distance, compute_proximity_weight


class TestAlgorithm(unittest.TestCase):

    def setUp(self):
        self.mock_locations = {
            "A11": {"location_id": "A11", "location_name": "Dry Shelf A11", "zone": "Dry Grocery", "active": 1, "active_status": "Active"},
            "A12": {"location_id": "A12", "location_name": "Dry Shelf A12", "zone": "Dry Grocery", "active": 1, "active_status": "Active"},
            "B08": {"location_id": "B08", "location_name": "Snacks Shelf B08", "zone": "Snacks", "active": 1, "active_status": "Active"},
            "B09": {"location_id": "B09", "location_name": "Snacks Shelf B09", "zone": "Snacks", "active": 1, "active_status": "Active"},
            "C01": {"location_id": "C01", "location_name": "Produce Shelf C01", "zone": "Fresh Produce", "active": 1, "active_status": "Active"},
            "X99": {"location_id": "X99", "location_name": "Maintenance Bay", "zone": "Maintenance", "active": 0, "active_status": "Inactive"}
        }

    def test_recency_decay_scaling(self):
        """Tests that older events decay in importance."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        day_ago = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

        weight_now = compute_recency_factor(now_str)
        weight_day = compute_recency_factor(day_ago)
        weight_3days = compute_recency_factor(three_days_ago)

        self.assertGreater(weight_now, weight_day)
        self.assertGreater(weight_day, weight_3days)
        self.assertAlmostEqual(weight_day, 0.5, delta=0.08)  # 24hr half-life

    def test_probabilities_sum_to_one(self):
        """Tests that candidate probabilities normalize properly to 1.0 (100%)."""
        events = {
            "sku": "SKU-RICE-01",
            "locations": self.mock_locations,
            "putaways": [{"location_id": "A12", "timestamp": "2026-09-04 10:00:00", "employee_id": "EMP-101"}],
            "moves": [{"from_location": "A12", "to_location": "B08", "move_status": "completed", "timestamp": "2026-09-05 08:00:00", "employee_id": "EMP-102"}],
            "pick_failures": [{"failure_id": "PF-01", "expected_location": "A12", "timestamp": "2026-09-05 09:00:00", "reason": "Not on shelf"}],
            "cycle_counts": [{"location_id": "B08", "physical_quantity": 10, "timestamp": "2026-09-05 08:30:00", "verified_by": "EMP-105"}]
        }

        output = find_discrepancy_locations(sku="SKU-RICE-01", expected_location="A12", custom_events=events)
        total_prob = sum(r["probability"] for r in output["recommendations"])

        self.assertAlmostEqual(total_prob, 1.0, places=2)
        self.assertEqual(output["recommended_location"], "B08")
        self.assertGreater(output["top_probability"], 0.45)

    def test_explainability_evidence_generation(self):
        """Tests that every recommended candidate location includes explanatory evidence."""
        events = {
            "sku": "SKU-MILK-01",
            "locations": self.mock_locations,
            "putaways": [{"location_id": "C01", "timestamp": "2026-09-04 10:00:00", "employee_id": "EMP-101"}],
            "moves": [{"from_location": "C01", "to_location": "B08", "move_status": "incomplete", "timestamp": "2026-09-05 08:00:00", "employee_id": "EMP-102"}],
            "pick_failures": [{"failure_id": "PF-02", "expected_location": "C01", "timestamp": "2026-09-05 09:00:00", "reason": "Empty"}],
            "cycle_counts": []
        }

        output = find_discrepancy_locations(sku="SKU-MILK-01", expected_location="C01", custom_events=events)
        for rec in output["recommendations"]:
            self.assertIn("evidence", rec)
            self.assertGreater(len(rec["evidence"]), 0)

    def test_spatial_proximity_metrics(self):
        """Tests warehouse distance and proximity weight calculations."""
        # Adjacent shelves on same rack: A11 and A12
        dist_adj = compute_location_distance("A11", "A12")
        weight_adj = compute_proximity_weight(dist_adj)

        # Distant shelf in different zone: A11 and C01
        dist_far = compute_location_distance("A11", "C01")
        weight_far = compute_proximity_weight(dist_far)

        self.assertLess(dist_adj, dist_far)
        self.assertGreater(weight_adj, weight_far)

    def test_inactive_location_exclusion(self):
        """Tests that decommissioned location X99 is excluded from candidate recommendations."""
        events = {
            "sku": "SKU-TEST-INACTIVE",
            "locations": self.mock_locations,
            "putaways": [{"location_id": "A12", "timestamp": "2026-09-05 07:00:00", "employee_id": "EMP-101"}],
            "moves": [{"from_location": "A12", "to_location": "X99", "move_status": "completed", "timestamp": "2026-09-05 08:00:00", "employee_id": "EMP-102"}],
            "pick_failures": [{"failure_id": "PF-03", "expected_location": "A12", "timestamp": "2026-09-05 08:30:00", "reason": "Missing"}],
            "cycle_counts": []
        }
        output = find_discrepancy_locations(sku="SKU-TEST-INACTIVE", expected_location="A12", custom_events=events)
        rec_ids = [r["location_id"] for r in output["recommendations"]]
        self.assertNotIn("X99", rec_ids)
        self.assertIn("X99", output["excluded_locations"])

    def test_baseline_vs_prototype_search(self):
        """Tests that prototype finds item in fewer steps than sequential baseline."""
        recs = [
            {"location_id": "B08", "probability": 0.85},
            {"location_id": "A12", "probability": 0.10},
            {"location_id": "UNKNOWN", "probability": 0.05}
        ]
        all_locs = ["A01", "A02", "A12", "B01", "B02", "B08"]

        proto_result = run_prototype_search(recs, true_physical_location="B08", all_locations=all_locs)
        base_result = run_baseline_search(expected_location="A12", true_physical_location="B08", all_locations=all_locs)

        # Prototype checks B08 first -> 1 step
        self.assertEqual(proto_result["locations_checked"], 1)
        self.assertTrue(proto_result["top1_hit"])

        # Baseline checks A12 (fail), A01, A02, B01, B02, B08 -> 6 steps
        self.assertGreater(base_result["locations_checked"], proto_result["locations_checked"])


if __name__ == "__main__":
    unittest.main()
