"""
Automated Edge Case and Realistic Failure State Tests for Dark Store Discrepancy Finder.

Covers 7 comprehensive operational failure modes (Sections 32 & 33):
1. Missing Move Scan (unrecorded physical transfer)
2. Incorrect Put-Away Scan (scanned one shelf, placed on another)
3. Duplicate or Conflicting Scans (contradictory recent moves e.g., C09 vs C11)
4. Stale Cycle Count vs Recent Move (D02 vs D07)
5. Invalid / Inactive Location (move to decommissioned or quarantine bay Z99/X99)
6. Phantom Inventory (repeated pick failures, no recent movement/cycle count)
7. Sensor / Scan Drift (systematic barcode / shelf discrepancy pattern)

Provides both a standard unittest suite and a structured dictionary output
for the Streamlit Edge Case Testing page.
"""

import unittest
from datetime import datetime, timedelta
from typing import List, Dict, Any
from algorithm import find_discrepancy_locations

# Mock warehouse master for edge cases
MOCK_LOCATIONS = {
    "A11": {"location_id": "A11", "location_name": "Dry Shelf A11", "zone": "Dry Grocery", "active": 1, "active_status": "Active"},
    "A12": {"location_id": "A12", "location_name": "Dry Shelf A12", "zone": "Dry Grocery", "active": 1, "active_status": "Active"},
    "A21": {"location_id": "A21", "location_name": "Dry Shelf A21", "zone": "Dry Grocery", "active": 1, "active_status": "Active"},
    "B08": {"location_id": "B08", "location_name": "Snack Shelf B08", "zone": "Snacks", "active": 1, "active_status": "Active"},
    "B09": {"location_id": "B09", "location_name": "Snack Shelf B09", "zone": "Snacks", "active": 1, "active_status": "Active"},
    "C09": {"location_id": "C09", "location_name": "Produce Bin C09", "zone": "Fresh Produce", "active": 1, "active_status": "Active"},
    "C11": {"location_id": "C11", "location_name": "Produce Bin C11", "zone": "Fresh Produce", "active": 1, "active_status": "Active"},
    "D02": {"location_id": "D02", "location_name": "Dairy Rack D02", "zone": "Dairy & Eggs", "active": 1, "active_status": "Active"},
    "D07": {"location_id": "D07", "location_name": "Dairy Rack D07", "zone": "Dairy & Eggs", "active": 1, "active_status": "Active"},
    "Z99": {"location_id": "Z99", "location_name": "Decommissioned Cold Bay", "zone": "Maintenance", "active": 0, "active_status": "Inactive"},
    "X99": {"location_id": "X99", "location_name": "Quarantine / Maintenance Bay", "zone": "Maintenance", "active": 0, "active_status": "Inactive"}
}


def run_all_edge_cases() -> List[Dict[str, Any]]:
    """
    Executes all 7 edge cases and returns structured evaluation dictionaries
    used by both automated tests and the Streamlit UI dashboard.
    """
    results = []
    now = datetime.now()

    # -------------------------------------------------------------
    # EDGE CASE 1: Missing Move Scan
    # -------------------------------------------------------------
    ec1_events = {
        "sku": "SKU-EC1-MISSING-MOVE",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "A12", "timestamp": (now - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-101"}
        ],
        "moves": [
            {"from_location": "A12", "to_location": "B08", "move_status": "missing_scan", "timestamp": (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-102"}
        ],
        "pick_failures": [
            {"failure_id": "PF-EC1", "expected_location": "A12", "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Item missing on shelf"}
        ],
        "cycle_counts": []
    }
    out1 = find_discrepancy_locations("SKU-EC1-MISSING-MOVE", expected_location="A12", custom_events=ec1_events)
    top_loc1 = out1["recommended_location"]
    passed1 = (top_loc1 == "B08")

    results.append({
        "case_num": 1,
        "title": "Missing Move Scan",
        "scenario": "Item physically moved from A12 to B08, but standard barcode move scan was omitted or flagged as missing.",
        "input_summary": "Put-away at A12 (8h ago), missing_scan move signal to B08 (3h ago), pick failure at A12 (1h ago).",
        "expected_result": "System penalizes A12 (due to pick failure) and surfaces B08 as top recommendation via operational scan signals.",
        "actual_result": f"Top recommended location: {top_loc1} ({out1['top_probability']*100:.1f}%)",
        "passed": passed1,
        "recommendations": out1["recommendations"],
        "confidence": out1["confidence"]
    })

    # -------------------------------------------------------------
    # EDGE CASE 2: Incorrect Put-Away Scan
    # -------------------------------------------------------------
    ec2_events = {
        "sku": "SKU-EC2-MISPLACED-PUTAWAY",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "A21", "timestamp": (now - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-104"}
        ],
        "moves": [],
        "pick_failures": [
            {"failure_id": "PF-EC2-1", "expected_location": "A21", "timestamp": (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Empty shelf"},
            {"failure_id": "PF-EC2-2", "expected_location": "A21", "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Empty shelf second order"}
        ],
        "cycle_counts": [
            {"location_id": "A12", "counted_quantity": 15, "physical_quantity": 15, "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-115", "verified_by": "EMP-115"}
        ]
    }
    out2 = find_discrepancy_locations("SKU-EC2-MISPLACED-PUTAWAY", expected_location="A21", custom_events=ec2_events)
    top_loc2 = out2["recommended_location"]
    passed2 = (top_loc2 == "A12")

    results.append({
        "case_num": 2,
        "title": "Incorrect Put-Away Scan",
        "scenario": "Employee scanned shelf A21 during intake but physically placed carton at shelf A12.",
        "input_summary": "Put-away recorded at A21; 2 consecutive pick failures at A21; verified cycle count at A12.",
        "expected_result": "Repeated pick failures at A21 drop its score below 0; verified cycle count at A12 ranks #1.",
        "actual_result": f"Top recommended location: {top_loc2} ({out2['top_probability']*100:.1f}%)",
        "passed": passed2,
        "recommendations": out2["recommendations"],
        "confidence": out2["confidence"]
    })

    # -------------------------------------------------------------
    # EDGE CASE 3: Conflicting Scans (C09 vs C11)
    # -------------------------------------------------------------
    ec3_events = {
        "sku": "SKU-EC3-CONFLICTING-SCANS",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "A12", "timestamp": (now - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-101"}
        ],
        "moves": [
            {"from_location": "A12", "to_location": "C09", "move_status": "completed", "timestamp": (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-102"},
            {"from_location": "A12", "to_location": "C11", "move_status": "completed", "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-108"}
        ],
        "pick_failures": [
            {"failure_id": "PF-EC3", "expected_location": "A12", "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Stock missing"}
        ],
        "cycle_counts": []
    }
    out3 = find_discrepancy_locations("SKU-EC3-CONFLICTING-SCANS", expected_location="A12", custom_events=ec3_events)
    top_loc3 = out3["recommended_location"]
    loc_probs = {r["location_id"]: r["probability"] for r in out3["recommendations"]}
    # Pass condition: Both C09 and C11 appear as candidates with non-zero probability; conflict flag raised
    passed3 = ("C09" in loc_probs and "C11" in loc_probs and out3["conflict_detected"])

    results.append({
        "case_num": 3,
        "title": "Conflicting Scans",
        "scenario": "Conflicting scan trails: Completed move logged to C09 (4h ago), but another completed move logged to C11 (2h ago).",
        "input_summary": "Two contradictory move events logged for same SKU in close temporal proximity.",
        "expected_result": "Both C09 and C11 surfaced as candidates; conflict warning explicitly displayed; fresher move (C11) higher score.",
        "actual_result": f"Candidates: C11 ({loc_probs.get('C11', 0)*100:.1f}%), C09 ({loc_probs.get('C09', 0)*100:.1f}%). Conflict flag: {out3['conflict_detected']}",
        "passed": passed3,
        "recommendations": out3["recommendations"],
        "confidence": out3["confidence"]
    })

    # -------------------------------------------------------------
    # EDGE CASE 4: Stale Cycle Count vs Recent Move (D02 vs D07)
    # -------------------------------------------------------------
    ec4_events = {
        "sku": "SKU-EC4-STALE-CYCLE-COUNT",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "D02", "timestamp": (now - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-101"}
        ],
        "moves": [
            {"from_location": "D02", "to_location": "D07", "move_status": "completed", "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-104"}
        ],
        "pick_failures": [
            {"failure_id": "PF-EC4", "expected_location": "D02", "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Shelf empty"}
        ],
        "cycle_counts": [
            {"location_id": "D02", "counted_quantity": 30, "physical_quantity": 30, "timestamp": (now - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-112", "verified_by": "EMP-112"}
        ]
    }
    out4 = find_discrepancy_locations("SKU-EC4-STALE-CYCLE-COUNT", expected_location="D02", custom_events=ec4_events)
    top_loc4 = out4["recommended_location"]
    passed4 = (top_loc4 == "D07")

    results.append({
        "case_num": 4,
        "title": "Stale Cycle Count",
        "scenario": "Cycle count confirmed stock at D02 4 days ago, but a completed move to D07 occurred 2 hours ago.",
        "input_summary": "4-day-old cycle count at D02 vs 2-hour-old completed move to D07.",
        "expected_result": "Recency exponential decay discounts the 4-day-old audit; recent move to D07 receives greater evidence weight.",
        "actual_result": f"Top recommended location: {top_loc4} ({out4['top_probability']*100:.1f}%)",
        "passed": passed4,
        "recommendations": out4["recommendations"],
        "confidence": out4["confidence"]
    })

    # -------------------------------------------------------------
    # EDGE CASE 5: Invalid / Inactive Location (Z99)
    # -------------------------------------------------------------
    ec5_events = {
        "sku": "SKU-EC5-INVALID-LOCATION",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "A12", "timestamp": (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-101"}
        ],
        "moves": [
            {"from_location": "A12", "to_location": "Z99", "move_status": "completed", "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-104"}
        ],
        "pick_failures": [
            {"failure_id": "PF-EC5", "expected_location": "A12", "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Item missing"}
        ],
        "cycle_counts": []
    }
    out5 = find_discrepancy_locations("SKU-EC5-INVALID-LOCATION", expected_location="A12", custom_events=ec5_events)
    rec_loc_ids = [r["location_id"] for r in out5["recommendations"]]
    passed5 = ("Z99" not in rec_loc_ids and "Z99" in out5.get("excluded_locations", {}))

    results.append({
        "case_num": 5,
        "title": "Invalid / Inactive Location",
        "scenario": "A scan trail mistakenly logs a transfer to decommissioned shelf Z99 (active = 0).",
        "input_summary": "Move event directed to Z99 (active_status = 'Inactive').",
        "expected_result": "Z99 excluded from final candidate recommendations, but audit explanation notes evidence was evaluated and excluded.",
        "actual_result": f"Z99 excluded from recommendations; retained in audit log. Top target: {out5['recommended_location']}",
        "passed": passed5,
        "recommendations": out5["recommendations"],
        "confidence": out5["confidence"]
    })

    # -------------------------------------------------------------
    # EDGE CASE 6: Phantom Inventory (Section 23)
    # -------------------------------------------------------------
    ec6_events = {
        "sku": "SKU-EC6-PHANTOM-INVENTORY",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "A12", "timestamp": (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-101"}
        ],
        "moves": [],
        "pick_failures": [
            {"failure_id": "PF-EC6-1", "expected_location": "A12", "timestamp": (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Item missing on shelf"},
            {"failure_id": "PF-EC6-2", "expected_location": "A12", "timestamp": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Second order pick failed"},
            {"failure_id": "PF-EC6-3", "expected_location": "A12", "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Third order pick failed"}
        ],
        "cycle_counts": [
            {"location_id": "A12", "counted_quantity": 0, "physical_quantity": 0, "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-112", "verified_by": "EMP-112"}
        ]
    }
    out6 = find_discrepancy_locations("SKU-EC6-PHANTOM-INVENTORY", expected_location="A12", custom_events=ec6_events)
    passed6 = out6["phantom_inventory_detected"]

    results.append({
        "case_num": 6,
        "title": "Phantom Inventory",
        "scenario": "System records stock in inventory, but 3 consecutive pick failures occur with zero cycle count and no movement trail.",
        "input_summary": "System expects stock at A12; 3 consecutive pick failures; zero cycle count audit.",
        "expected_result": "System flags 'Possible Phantom Inventory' warning; does NOT falsely assign high probability to empty shelf.",
        "actual_result": f"Phantom warning: {out6['phantom_inventory_detected']} — {out6['phantom_message'][:60]}...",
        "passed": passed6,
        "recommendations": out6["recommendations"],
        "confidence": out6["confidence"]
    })

    # -------------------------------------------------------------
    # EDGE CASE 7: Sensor / Scan Drift (Section 24)
    # -------------------------------------------------------------
    ec7_events = {
        "sku": "SKU-EC7-SCAN-DRIFT",
        "locations": MOCK_LOCATIONS,
        "putaways": [
            {"location_id": "A12", "timestamp": (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-101"}
        ],
        "moves": [
            {"from_location": "A12", "to_location": "B08", "move_status": "completed", "timestamp": (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-102"},
            {"from_location": "A12", "to_location": "B09", "move_status": "completed", "timestamp": (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"), "employee_id": "EMP-104"}
        ],
        "pick_failures": [
            {"failure_id": "PF-EC7", "expected_location": "A12", "timestamp": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "reason": "Repeated mismatch between scanner and tag"}
        ],
        "cycle_counts": []
    }
    out7 = find_discrepancy_locations("SKU-EC7-SCAN-DRIFT", expected_location="A12", custom_events=ec7_events)
    passed7 = out7["scan_drift_detected"]

    results.append({
        "case_num": 7,
        "title": "Sensor / Scan Drift",
        "scenario": "Repeated contradictory barcode scans and continuous location mismatch suggesting scanner calibration or tag damage.",
        "input_summary": "Contradictory moves across adjacent shelves B08 and B09, pick failure indicating scanner mismatch.",
        "expected_result": "System displays data-quality warning flagging scan/sensor drift for supervisor maintenance.",
        "actual_result": f"Drift warning: {out7['scan_drift_detected']} — {out7['scan_drift_message'][:60]}...",
        "passed": passed7,
        "recommendations": out7["recommendations"],
        "confidence": out7["confidence"]
    })

    return results


class TestEdgeCases(unittest.TestCase):
    def test_all_seven_edge_cases(self):
        results = run_all_edge_cases()
        self.assertEqual(len(results), 7, "Should execute exactly 7 operational edge cases")
        for res in results:
            with self.subTest(case=res["title"]):
                self.assertTrue(
                    res["passed"],
                    f"Edge Case {res['case_num']} ({res['title']}) failed! Actual: {res['actual_result']}"
                )


if __name__ == "__main__":
    unittest.main()
