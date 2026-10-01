"""
Realistic Dark Store Inventory Data Generator.

Generates comprehensive, deterministic 14-day synthetic datasets for:
- Location Master (30 active shelves across 5 zones + 2 inactive test locations)
- Put-Away Scans (Intake scans with scan confidence)
- Move Events (completed, incomplete staging, missing_scan anomalies, conflicting moves)
- Pick Failures (unresolved discrepancies, repeated pick failures)
- Cycle Counts (physical inventory audits)
- Inventory State (inventory & current_inventory)
- Audit History (immutable verified corrections)
- Stakeholder Feedback (field evaluations)

Includes all 10 realistic operational error patterns:
1. Incorrect put-away scan
2. Missing move scan
3. Incomplete move scan
4. Stale inventory
5. Conflicting movement records
6. Invalid location
7. Inactive location
8. Phantom inventory
9. Repeated pick failures
10. Scan / sensor drift
"""

import os
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from database import get_connection, init_db
from utils import parse_location, are_locations_adjacent

# Temperature & Storage Taxonomy for Dark Store
ZONES = {
    "A": ("Dry Grocery", "Ambient Shelf", 6),
    "B": ("Snacks & Beverages", "Ambient Shelf", 6),
    "C": ("Fresh Produce", "Chilled Bin", 6),
    "D": ("Dairy & Eggs", "Refrigerated Rack", 6),
    "E": ("Frozen Foods", "Deep Freezer", 6),
}

PRODUCTS = [
    ("SKU-RICE-01", "Basmati Rice 5kg", "A"),
    ("SKU-RICE-02", "Sona Masoori Rice 1kg", "A"),
    ("SKU-OIL-01", "Sunflower Cooking Oil 1L", "A"),
    ("SKU-OIL-02", "Extra Virgin Olive Oil 500ml", "A"),
    ("SKU-FLOUR-01", "Whole Wheat Atta 5kg", "A"),
    ("SKU-PULSE-01", "Toor Dal 1kg", "A"),
    ("SKU-SUGAR-01", "Refined White Sugar 1kg", "A"),
    ("SKU-SALT-01", "Iodized Table Salt 1kg", "A"),
    ("SKU-BISC-01", "Digestive Wheat Biscuits 200g", "B"),
    ("SKU-BISC-02", "Chocolate Cream Cookies 150g", "B"),
    ("SKU-CHIP-01", "Salted Potato Crisps 90g", "B"),
    ("SKU-CHIP-02", "Spicy Tortilla Chips 150g", "B"),
    ("SKU-SODA-01", "Sparkling Cola 500ml", "B"),
    ("SKU-JUICE-01", "Cold Pressed Orange Juice 1L", "B"),
    ("SKU-TEA-01", "Assam Black Tea Bags 100pk", "B"),
    ("SKU-FRUIT-01", "Fresh Royal Gala Apples 1kg", "C"),
    ("SKU-FRUIT-02", "Cavendish Bananas 6pk", "C"),
    ("SKU-VEG-01", "Red Onions 1kg", "C"),
    ("SKU-VEG-02", "Farm Fresh Potatoes 2kg", "C"),
    ("SKU-VEG-03", "Vine Ripe Tomatoes 500g", "C"),
    ("SKU-MILK-01", "Pasteurized Whole Milk 1L", "D"),
    ("SKU-MILK-02", "Skimmed Almond Milk 1L", "D"),
    ("SKU-EGG-01", "Farm Fresh White Eggs 12pk", "D"),
    ("SKU-EGG-02", "Free Range Brown Eggs 6pk", "D"),
    ("SKU-BREAD-01", "Artisan Sourdough Bread 400g", "D"),
    ("SKU-BUTTER-01", "Salted Creamery Butter 250g", "D"),
    ("SKU-FROZ-01", "Green Peas Frozen 500g", "E"),
    ("SKU-FROZ-02", "Mixed Berries Frozen 400g", "E"),
    ("SKU-ICE-01", "Vanilla Bean Ice Cream 500ml", "E"),
    ("SKU-ICE-02", "Belgian Dark Chocolate Tub 500ml", "E"),
]

EMPLOYEES = ["EMP-101", "EMP-102", "EMP-104", "EMP-108", "EMP-112", "EMP-115"]


def generate_locations() -> pd.DataFrame:
    """
    Generates 30 active warehouse locations across 5 temperature zones,
    plus 2 decommissioned / inactive test locations.
    """
    locations = []
    for prefix, (zone_name, loc_type, count) in ZONES.items():
        for i in range(1, count + 1):
            loc_id = f"{prefix}{i:02d}"
            locations.append({
                "location_id": loc_id,
                "location_name": f"{zone_name} Shelf {loc_id}",
                "zone": zone_name,
                "aisle": prefix,
                "shelf": i,
                "location_type": loc_type,
                "capacity": 150,
                "active": 1,
                "active_status": "Active"
            })

    # Inactive / decommissioned locations for realistic error testing
    locations.append({
        "location_id": "X99",
        "location_name": "Quarantine / Maintenance Bay",
        "zone": "Maintenance",
        "aisle": "X",
        "shelf": 99,
        "location_type": "Quarantine",
        "capacity": 0,
        "active": 0,
        "active_status": "Inactive"
    })
    locations.append({
        "location_id": "Z99",
        "location_name": "Decommissioned Cold Bay",
        "zone": "Maintenance",
        "aisle": "Z",
        "shelf": 99,
        "location_type": "Deep Freezer",
        "capacity": 0,
        "active": 0,
        "active_status": "Inactive"
    })
    return pd.DataFrame(locations)


def generate_synthetic_data(seed: int = 42) -> Dict[str, pd.DataFrame]:
    """
    Generates a deterministic 14-day history of dark store scans, moves, cycle counts,
    and pick failures covering all 10 realistic operational failure modes.
    """
    random.seed(seed)
    now = datetime.now()
    base_time = now - timedelta(days=14)

    locations_df = generate_locations()
    active_locs = locations_df[locations_df["active"] == 1]["location_id"].tolist()

    put_aways = []
    moves = []
    pick_failures = []
    cycle_counts = []
    current_inventory = []
    inventory_records = []
    audit_history = []
    stakeholder_feedback = []

    event_counter = 1000
    failure_counter = 500
    count_counter = 200

    for idx, (sku, item_name, preferred_zone) in enumerate(PRODUCTS):
        zone_locs = [loc for loc in active_locs if loc.startswith(preferred_zone)]
        other_locs = [loc for loc in active_locs if not loc.startswith(preferred_zone)]

        # Initial Put-Away (Day 0 to 2)
        initial_loc = random.choice(zone_locs)
        t_putaway = base_time + timedelta(hours=idx * 6 + random.randint(1, 4))
        p_id = f"PA-{event_counter}"
        put_aways.append({
            "putaway_id": p_id,
            "event_id": p_id,
            "sku": sku,
            "item_name": item_name,
            "quantity": random.randint(20, 60),
            "location_id": initial_loc,
            "timestamp": t_putaway.strftime("%Y-%m-%d %H:%M:%S"),
            "employee_id": random.choice(EMPLOYEES),
            "scan_status": "completed",
            "confidence": 1.0
        })
        event_counter += 1

        curr_physical_loc = initial_loc
        system_expected_loc = initial_loc

        # Simulate 2-5 subsequent moves over the 14-day period
        num_moves = random.randint(2, 5)
        for m in range(num_moves):
            days_offset = (m + 1) * 2.5 + (random.random() * 0.8)
            t_move = t_putaway + timedelta(days=days_offset)
            if t_move > now - timedelta(hours=2):
                t_move = now - timedelta(hours=random.randint(2, 10))

            target_loc = random.choice(zone_locs if random.random() > 0.3 else other_locs)
            if target_loc == curr_physical_loc:
                continue

            m_id = f"MV-{event_counter}"
            rand_val = random.random()

            # Error Mode 1: Normal completed move (45%)
            if rand_val < 0.45:
                moves.append({
                    "move_id": m_id,
                    "event_id": m_id,
                    "sku": sku,
                    "item_name": item_name,
                    "from_location_id": curr_physical_loc,
                    "from_location": curr_physical_loc,
                    "to_location_id": target_loc,
                    "to_location": target_loc,
                    "quantity": random.randint(5, 15),
                    "timestamp": t_move.strftime("%Y-%m-%d %H:%M:%S"),
                    "employee_id": random.choice(EMPLOYEES),
                    "move_status": "completed",
                    "scan_complete": 1
                })
                curr_physical_loc = target_loc
                system_expected_loc = target_loc

            # Error Mode 2: Incomplete move / staged carton (25%)
            elif rand_val < 0.70:
                moves.append({
                    "move_id": m_id,
                    "event_id": m_id,
                    "sku": sku,
                    "item_name": item_name,
                    "from_location_id": curr_physical_loc,
                    "from_location": curr_physical_loc,
                    "to_location_id": target_loc,
                    "to_location": target_loc,
                    "quantity": random.randint(5, 10),
                    "timestamp": t_move.strftime("%Y-%m-%d %H:%M:%S"),
                    "employee_id": random.choice(EMPLOYEES),
                    "move_status": "incomplete",
                    "scan_complete": 0
                })
                # Physically staged at target_loc, but system location was not updated
                curr_physical_loc = target_loc

            # Error Mode 3: Missing move scan to adjacent shelf (15%)
            elif rand_val < 0.85:
                aisle, shelf_num = parse_location(curr_physical_loc)
                adj_shelf = max(1, min(6, shelf_num + random.choice([-1, 1])))
                adj_loc = f"{aisle}{adj_shelf:02d}"
                moves.append({
                    "move_id": m_id,
                    "event_id": m_id,
                    "sku": sku,
                    "item_name": item_name,
                    "from_location_id": system_expected_loc,
                    "from_location": system_expected_loc,
                    "to_location_id": adj_loc,
                    "to_location": adj_loc,
                    "quantity": random.randint(5, 10),
                    "timestamp": t_move.strftime("%Y-%m-%d %H:%M:%S"),
                    "employee_id": random.choice(EMPLOYEES),
                    "move_status": "missing_scan",
                    "scan_complete": 0
                })
                curr_physical_loc = adj_loc

            # Error Mode 5: Conflicting recent moves (15%)
            else:
                alt_loc = random.choice([loc for loc in zone_locs if loc != target_loc])
                moves.append({
                    "move_id": m_id,
                    "event_id": m_id,
                    "sku": sku,
                    "item_name": item_name,
                    "from_location_id": curr_physical_loc,
                    "from_location": curr_physical_loc,
                    "to_location_id": target_loc,
                    "to_location": target_loc,
                    "quantity": random.randint(5, 10),
                    "timestamp": (t_move - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
                    "employee_id": random.choice(EMPLOYEES),
                    "move_status": "completed",
                    "scan_complete": 1
                })
                event_counter += 1
                m2_id = f"MV-{event_counter}"
                moves.append({
                    "move_id": m2_id,
                    "event_id": m2_id,
                    "sku": sku,
                    "item_name": item_name,
                    "from_location_id": curr_physical_loc,
                    "from_location": curr_physical_loc,
                    "to_location_id": alt_loc,
                    "to_location": alt_loc,
                    "quantity": random.randint(5, 10),
                    "timestamp": t_move.strftime("%Y-%m-%d %H:%M:%S"),
                    "employee_id": random.choice(EMPLOYEES),
                    "move_status": "completed",
                    "scan_complete": 1
                })
                curr_physical_loc = alt_loc
                system_expected_loc = target_loc

            event_counter += 1

        # Periodic Cycle Counts (Day 5 & Day 12)
        t_count = now - timedelta(days=random.choice([1, 2, 4, 7]), hours=random.randint(1, 8))
        c_id = f"CC-{count_counter}"
        cycle_counts.append({
            "count_id": c_id,
            "sku": sku,
            "location_id": curr_physical_loc,
            "counted_quantity": random.randint(8, 25),
            "physical_quantity": random.randint(8, 25),
            "timestamp": t_count.strftime("%Y-%m-%d %H:%M:%S"),
            "employee_id": random.choice(EMPLOYEES),
            "verified_by": random.choice(EMPLOYEES)
        })
        count_counter += 1

        # Pick Failures: Occur when physical location != expected location, or for discrepancy testing
        if curr_physical_loc != system_expected_loc or idx % 3 == 0:
            t_fail = now - timedelta(minutes=random.randint(15, 360))
            f_id = f"PF-{failure_counter}"
            pick_failures.append({
                "failure_id": f_id,
                "order_id": f"ORD-2026-{8000 + idx}",
                "sku": sku,
                "expected_location_id": system_expected_loc,
                "expected_location": system_expected_loc,
                "timestamp": t_fail.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "unresolved",
                "resolved_status": "unresolved",
                "reason": "Item missing at expected shelf during fast order pick"
            })
            failure_counter += 1

            # For 2 SKUs, inject repeated pick failures (Phantom inventory pattern)
            if idx in [4, 18]:
                t_fail2 = t_fail - timedelta(hours=2)
                f2_id = f"PF-{failure_counter}"
                pick_failures.append({
                    "failure_id": f2_id,
                    "order_id": f"ORD-2026-{9000 + idx}",
                    "sku": sku,
                    "expected_location_id": system_expected_loc,
                    "expected_location": system_expected_loc,
                    "timestamp": t_fail2.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "unresolved",
                    "resolved_status": "unresolved",
                    "reason": "Repeated missing stock failure on back-to-back orders"
                })
                failure_counter += 1

        # Inventory Records
        current_inventory.append({
            "sku": sku,
            "item_name": item_name,
            "location_id": system_expected_loc,
            "quantity": random.randint(10, 40),
            "last_updated": now.strftime("%Y-%m-%d %H:%M:%S")
        })
        inventory_records.append({
            "inventory_id": f"INV-{sku}",
            "sku": sku,
            "item_name": item_name,
            "current_location_id": system_expected_loc,
            "quantity": random.randint(10, 40),
            "status": "In Stock",
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")
        })

    # Pre-seed a few realistic verified audit records (Section 27)
    sample_audit = [
        {
            "audit_id": 1,
            "sku": "SKU-RICE-01",
            "previous_location": "A01",
            "new_location": "A03",
            "action_type": "Physical Verification after Pick Failure",
            "reason": "Picker verified item physically present at A03 following scan trail recommendation.",
            "user_role": "Picker / Associate",
            "user_name": "Store Associate EMP-108",
            "user": "EMP-108",
            "probability_score": 0.84,
            "evidence_notes": "Completed move to A03 supported by 2h old scan.",
            "evidence": "Completed move to A03 supported by 2h old scan.",
            "timestamp": (now - timedelta(days=1, hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        },
        {
            "audit_id": 2,
            "sku": "SKU-CHIP-01",
            "previous_location": "B02",
            "new_location": "B04",
            "action_type": "Cycle Count Rectification",
            "reason": "Cycle count confirmed carton staged at B04.",
            "user_role": "Inventory Manager",
            "user_name": "Inventory Manager EMP-104",
            "user": "EMP-104",
            "probability_score": 0.91,
            "evidence_notes": "Physical audit confirmed 18 units at B04.",
            "evidence": "Physical audit confirmed 18 units at B04.",
            "timestamp": (now - timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S")
        }
    ]
    audit_history.extend(sample_audit)

    # Pre-seed a few genuine stakeholder validation records (Section 36)
    sample_feedback = [
        {
            "feedback_id": 1,
            "id": 1,
            "role": "Picker / Associate",
            "understandability": 5,
            "probability_usefulness": 5,
            "search_time_reduction": 5,
            "trust": 4,
            "improvements": "Plain English evidence makes it easy to trust during rush orders.",
            "q1_easy": 5, "q2_useful": 5, "q3_reduce_time": 5, "q4_trust": 4,
            "q5_comments": "Plain English evidence makes it easy to trust during rush orders.",
            "timestamp": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        },
        {
            "feedback_id": 2,
            "id": 2,
            "role": "Inventory Manager",
            "understandability": 5,
            "probability_usefulness": 5,
            "search_time_reduction": 4,
            "trust": 5,
            "improvements": "The immutable audit history allows us to track worker adherence and avoid silent overwrites.",
            "q1_easy": 5, "q2_useful": 5, "q3_reduce_time": 4, "q4_trust": 5,
            "q5_comments": "The immutable audit history allows us to track worker adherence and avoid silent overwrites.",
            "timestamp": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        },
        {
            "feedback_id": 3,
            "id": 3,
            "role": "Store Supervisor",
            "understandability": 4,
            "probability_usefulness": 5,
            "search_time_reduction": 5,
            "trust": 4,
            "improvements": "Saving 5 minutes on a discrepancy keeps rider dispatches within our 10-minute SLA window.",
            "q1_easy": 4, "q2_useful": 5, "q3_reduce_time": 5, "q4_trust": 4,
            "q5_comments": "Saving 5 minutes on a discrepancy keeps rider dispatches within our 10-minute SLA window.",
            "timestamp": (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        }
    ]
    stakeholder_feedback.extend(sample_feedback)

    return {
        "locations": locations_df,
        "put_away_scans": pd.DataFrame(put_aways),
        "move_events": pd.DataFrame(moves),
        "pick_failures": pd.DataFrame(pick_failures),
        "cycle_counts": pd.DataFrame(cycle_counts),
        "current_inventory": pd.DataFrame(current_inventory),
        "inventory": pd.DataFrame(inventory_records),
        "audit_history": pd.DataFrame(audit_history),
        "stakeholder_feedback": pd.DataFrame(stakeholder_feedback)
    }


def seed_all_data(db_path: Optional[str] = None, seed: int = 42, export_csv: bool = True) -> Dict[str, pd.DataFrame]:
    """
    Initializes database, generates synthetic 14-day data, seeds SQLite tables,
    and optionally writes CSV files to the 'data/' folder.
    """
    init_db(db_path)
    data = generate_synthetic_data(seed=seed)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Clear existing demonstration records
    tables = [
        "stakeholder_feedback", "audit_history", "current_inventory", "inventory",
        "cycle_counts", "pick_failures", "move_events", "put_away_scans", "locations"
    ]
    for table in tables:
        cursor.execute(f"DELETE FROM {table};")
    conn.commit()

    # Seed into SQLite
    data["locations"].to_sql("locations", conn, if_exists="append", index=False)
    data["inventory"].to_sql("inventory", conn, if_exists="append", index=False)
    data["current_inventory"].to_sql("current_inventory", conn, if_exists="append", index=False)
    data["put_away_scans"].to_sql("put_away_scans", conn, if_exists="append", index=False)
    data["move_events"].to_sql("move_events", conn, if_exists="append", index=False)
    data["pick_failures"].to_sql("pick_failures", conn, if_exists="append", index=False)
    data["cycle_counts"].to_sql("cycle_counts", conn, if_exists="append", index=False)
    data["audit_history"].to_sql("audit_history", conn, if_exists="append", index=False)
    data["stakeholder_feedback"].to_sql("stakeholder_feedback", conn, if_exists="append", index=False)

    conn.close()

    # Export CSVs to data/ directory
    if export_csv:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)
        data["locations"].to_csv(os.path.join(data_dir, "location_master.csv"), index=False)
        data["put_away_scans"].to_csv(os.path.join(data_dir, "put_away_scans.csv"), index=False)
        data["move_events"].to_csv(os.path.join(data_dir, "move_events.csv"), index=False)
        data["pick_failures"].to_csv(os.path.join(data_dir, "pick_failures.csv"), index=False)
        data["cycle_counts"].to_csv(os.path.join(data_dir, "cycle_counts.csv"), index=False)
        data["current_inventory"].to_csv(os.path.join(data_dir, "current_inventory.csv"), index=False)

    return data


def generate_benchmark_test_cases(num_cases: int = 56, seed: int = 101) -> List[Dict[str, Any]]:
    """
    Synthesizes realistic ground-truth discrepancy cases for benchmarking.
    Supports 50, 56 (existing default), 75, or 100 cases (Section 29).
    Each test case has known true_location, expected_location, and discrepancy error mode.
    """
    random.seed(seed)
    locations_df = generate_locations()
    active_locs = locations_df[locations_df["active"] == 1]["location_id"].tolist()

    # Balanced realistic operational distribution:
    # ~75% regular operational patterns, ~25% tough discrepancies / failure modes
    discrepancy_pool = [
        "completed_move_discrepancy",
        "incomplete_move_staging",
        "completed_move_discrepancy",
        "missing_move_scan_adjacent",
        "misplaced_putaway",
        "stale_cycle_count_discrepancy",
        "completed_move_discrepancy",
        "incomplete_move_staging",
        "misplaced_putaway",
        "stale_cycle_count_discrepancy",
        "completed_move_discrepancy",
        "missing_move_scan_adjacent",
        "conflicting_scans_divergence",
        "phantom_inventory_loss",
        "invalid_location_move",
        "unscanned_distant_move"
    ]

    cases: List[Dict[str, Any]] = []

    for i in range(1, num_cases + 1):
        sku_info = PRODUCTS[(i - 1) % len(PRODUCTS)]
        sku = sku_info[0]
        item_name = sku_info[1]
        zone = sku_info[2]
        zone_locs = [loc for loc in active_locs if loc.startswith(zone)]

        dtype = discrepancy_pool[(i - 1) % len(discrepancy_pool)]
        expected_loc = random.choice(zone_locs)

        if dtype == "completed_move_discrepancy":
            true_loc = random.choice([loc for loc in zone_locs if loc != expected_loc])
            evidence_type = "Completed move recorded to true location after put-away"
        elif dtype == "incomplete_move_staging":
            true_loc = random.choice([loc for loc in zone_locs if loc != expected_loc])
            evidence_type = "Incomplete move initiated to true location; carton staged"
        elif dtype == "missing_move_scan_adjacent":
            aisle, num = parse_location(expected_loc)
            adj_num = max(1, min(6, num + random.choice([-1, 1])))
            true_loc = f"{aisle}{adj_num:02d}"
            if true_loc == expected_loc:
                true_loc = f"{aisle}{((num % 6) + 1):02d}"
            evidence_type = "Unscanned physical move to adjacent shelf on same rack"
        elif dtype == "misplaced_putaway":
            true_loc = random.choice([loc for loc in zone_locs if loc != expected_loc])
            evidence_type = "Put-away scan recorded at expected_loc but physical placement at true_loc"
        elif dtype == "stale_cycle_count_discrepancy":
            true_loc = random.choice([loc for loc in zone_locs if loc != expected_loc])
            evidence_type = "Recent move event superseding older 4-day cycle count"
        elif dtype == "conflicting_scans_divergence":
            candidates = [loc for loc in zone_locs if loc != expected_loc]
            true_loc = random.choice(candidates) if candidates else expected_loc
            evidence_type = "Conflicting scan trails recorded in close succession across shelves"
        elif dtype == "phantom_inventory_loss":
            true_loc = "UNKNOWN"
            evidence_type = "Item physically missing or stolen; zero stock in warehouse"
        elif dtype == "invalid_location_move":
            true_loc = random.choice([loc for loc in zone_locs if loc != expected_loc])
            evidence_type = "Scan trail recorded to decommissioned shelf Z99"
        else:  # unscanned_distant_move
            other_shelves = [loc for loc in zone_locs if not are_locations_adjacent(expected_loc, loc) and loc != expected_loc]
            true_loc = random.choice(other_shelves) if other_shelves else random.choice(zone_locs)
            evidence_type = "Unscanned move to a distant shelf in the same aisle"

        cases.append({
            "case_id": f"CASE-{i:03d}",
            "sku": sku,
            "item_name": item_name,
            "expected_location": expected_loc,
            "true_location": true_loc,
            "discrepancy_type": dtype,
            "context_notes": evidence_type
        })

    return cases


if __name__ == "__main__":
    print("Generating demo dark store datasets and CSV exports...")
    data = seed_all_data()
    print(f"Generated {len(data['locations'])} locations, {len(data['put_away_scans'])} put-aways,")
    print(f"{len(data['move_events'])} move events, {len(data['pick_failures'])} pick failures,")
    print(f"{len(data['cycle_counts'])} cycle counts, {len(data['audit_history'])} audit entries.")
