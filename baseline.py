"""
Baseline Search Method and Comparative Search Models for Dark Store Operations.

Implements:
1. Operational Baseline (Deterministic Sequential Walk):
   - First checks the last recorded (expected) location.
   - If missing, sequentially searches valid warehouse shelves in deterministic physical order (A01 -> A02 -> ...).
2. Probability Prototype Search:
   - Traverses candidate shelves in descending probability order (Rank 1 -> Rank 2 -> Rank 3).
   - If not found in recommendations, falls back to remaining active locations.
3. Optional Unstructured Random Walk Baseline:
   - Explores warehouse shelves in random sequence without systematic ordering.

Search Time Formulation (Section 30):
search_time = fixed_lookup_time + (locations_checked * seconds_per_check)
"""

import random
from typing import List, Dict, Any, Optional
from database import fetch_all

# Industry dark store standard benchmarks
DEFAULT_FIXED_LOOKUP_SECONDS = 10.0   # Time to scan prompt / check handheld terminal
DEFAULT_SECONDS_PER_LOCATION_CHECK = 30.0  # Physical shelf inspection time


def get_ordered_warehouse_locations(db_path=None) -> List[str]:
    """Returns active warehouse locations in physical sequential order (A01, A02, A03...)."""
    rows = fetch_all(
        "SELECT location_id FROM locations WHERE active = 1 OR active_status = 'Active' ORDER BY location_id ASC",
        db_path=db_path
    )
    if rows:
        return [r["location_id"] for r in rows]
    # Fallback default sequence across 5 zones
    return [f"{z}{i:02d}" for z in ["A", "B", "C", "D", "E"] for i in range(1, 7)]


def run_baseline_search(
    expected_location: str,
    true_physical_location: str,
    all_locations: Optional[List[str]] = None,
    seconds_per_check: float = DEFAULT_SECONDS_PER_LOCATION_CHECK,
    fixed_lookup_seconds: float = DEFAULT_FIXED_LOOKUP_SECONDS,
    db_path=None
) -> Dict[str, Any]:
    """
    Simulates the standard operational baseline:
    1. Checks the last recorded expected location first.
    2. If item is missing (pick failure), systematically searches valid locations in sequential order.
    """
    locations = all_locations or get_ordered_warehouse_locations(db_path=db_path)
    steps = 0
    checked_path = []

    # 1. Step 1: Check expected location
    steps += 1
    checked_path.append(expected_location)
    if expected_location == true_physical_location:
        total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
        return {
            "found": True,
            "locations_checked": steps,
            "search_time_seconds": total_sec,
            "search_time_minutes": total_sec / 60.0,
            "checked_path": checked_path,
            "method": "Baseline (Expected Location Match)"
        }

    # 2. Sequential walk through remaining active locations
    for loc in locations:
        if loc == expected_location:
            continue
        steps += 1
        checked_path.append(loc)
        if loc == true_physical_location:
            total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
            return {
                "found": True,
                "locations_checked": steps,
                "search_time_seconds": total_sec,
                "search_time_minutes": total_sec / 60.0,
                "checked_path": checked_path,
                "method": "Baseline (Sequential Walk)"
            }

    # If not found after checking all locations
    total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
    return {
        "found": False,
        "locations_checked": steps,
        "search_time_seconds": total_sec,
        "search_time_minutes": total_sec / 60.0,
        "checked_path": checked_path,
        "method": "Baseline (Exhausted Search)"
    }


def run_prototype_search(
    ranked_recommendations: List[Dict[str, Any]],
    true_physical_location: str,
    all_locations: Optional[List[str]] = None,
    seconds_per_check: float = DEFAULT_SECONDS_PER_LOCATION_CHECK,
    fixed_lookup_seconds: float = DEFAULT_FIXED_LOOKUP_SECONDS,
    db_path=None
) -> Dict[str, Any]:
    """
    Simulates the probability-guided prototype:
    1. Checks candidate locations in descending order of calculated probability.
    2. If not found in candidates, falls back to remaining active warehouse shelves.
    """
    steps = 0
    checked_path = []
    top1_hit = False
    top3_hit = False
    rank_found = None

    # Filter out UNKNOWN pseudo-location
    candidate_locs = [
        r["location_id"] for r in ranked_recommendations
        if r.get("location_id") not in ["UNKNOWN", "None", None]
    ]

    # 1. Check probability-ranked candidates
    for rank_idx, loc in enumerate(candidate_locs, start=1):
        steps += 1
        checked_path.append(loc)
        if loc == true_physical_location:
            if rank_idx == 1:
                top1_hit = True
            if rank_idx <= 3:
                top3_hit = True
            rank_found = rank_idx
            total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
            return {
                "found": True,
                "rank_found": rank_found,
                "top1_hit": top1_hit,
                "top3_hit": top3_hit,
                "locations_checked": steps,
                "search_time_seconds": total_sec,
                "search_time_minutes": total_sec / 60.0,
                "checked_path": checked_path,
                "method": "Probability Prototype (Top-Ranked Guidance)"
            }

    # 2. Fallback to remaining warehouse locations
    locations = all_locations or get_ordered_warehouse_locations(db_path=db_path)
    for loc in locations:
        if loc in checked_path:
            continue
        steps += 1
        checked_path.append(loc)
        if loc == true_physical_location:
            total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
            return {
                "found": True,
                "rank_found": steps,
                "top1_hit": False,
                "top3_hit": False,
                "locations_checked": steps,
                "search_time_seconds": total_sec,
                "search_time_minutes": total_sec / 60.0,
                "checked_path": checked_path,
                "method": "Probability Prototype (Fallback Search)"
            }

    total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
    return {
        "found": False,
        "rank_found": None,
        "top1_hit": False,
        "top3_hit": False,
        "locations_checked": steps,
        "search_time_seconds": total_sec,
        "search_time_minutes": total_sec / 60.0,
        "checked_path": checked_path,
        "method": "Probability Prototype (Exhausted)"
    }


def run_random_baseline_search(
    expected_location: str,
    true_physical_location: str,
    all_locations: Optional[List[str]] = None,
    seconds_per_check: float = DEFAULT_SECONDS_PER_LOCATION_CHECK,
    fixed_lookup_seconds: float = DEFAULT_FIXED_LOOKUP_SECONDS,
    seed: Optional[int] = None,
    db_path=None
) -> Dict[str, Any]:
    """
    Optional secondary baseline: Unstructured random search.
    Included explicitly for academic comparison against systematic sequential search.
    """
    locations = list(all_locations or get_ordered_warehouse_locations(db_path=db_path))
    rng = random.Random(seed)
    rng.shuffle(locations)

    steps = 0
    checked_path = []

    # First check expected location
    steps += 1
    checked_path.append(expected_location)
    if expected_location == true_physical_location:
        total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
        return {
            "found": True,
            "locations_checked": steps,
            "search_time_seconds": total_sec,
            "search_time_minutes": total_sec / 60.0,
            "checked_path": checked_path,
            "method": "Random Baseline (Expected Match)"
        }

    for loc in locations:
        if loc == expected_location:
            continue
        steps += 1
        checked_path.append(loc)
        if loc == true_physical_location:
            total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
            return {
                "found": True,
                "locations_checked": steps,
                "search_time_seconds": total_sec,
                "search_time_minutes": total_sec / 60.0,
                "checked_path": checked_path,
                "method": "Random Baseline (Random Walk)"
            }

    total_sec = fixed_lookup_seconds + (steps * seconds_per_check)
    return {
        "found": False,
        "locations_checked": steps,
        "search_time_seconds": total_sec,
        "search_time_minutes": total_sec / 60.0,
        "checked_path": checked_path,
        "method": "Random Baseline (Exhausted)"
    }
