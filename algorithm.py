"""
Explainable Probability-Based Inventory-Location Discrepancy Finder.

Analyzes operational scan trails (put-away, moves, pick failures, cycle counts, location master)
and computes recency-decayed Bayesian/evidence scores to rank candidate physical locations.

Key Mathematical Principles:
1. Time Decay: D(t) = exp(-lambda * delta_t) = 2^(-delta_t / half_life)
2. Spatial Proximity: P_dist = 1 / (1 + distance(candidate, expected))
3. Scan Confidence: C_scan in [0.5, 0.7, 1.0]
4. Combined Evidence: E_i = W_type * D(t) * C_scan * P_dist
5. Candidate Score: S(loc) = sum(Positive Evidence) - sum(Negative Evidence)
6. Softmax Normalization: P(loc_i) = exp(S_i / T) / sum_j exp(S_j / T)

Also provides:
- Conflict detection (never hides contradictory scans)
- Inactive/invalid location filtering (excluded from recommendation with audit notes)
- Phantom inventory detection
- Sensor / scan drift detection
"""

from datetime import datetime
import math
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd

from database import fetch_all
from utils import (
    parse_timestamp, get_hours_elapsed, parse_location,
    compute_location_distance, compute_proximity_weight,
    are_locations_adjacent, are_locations_same_aisle
)

# -----------------------------------------------------------------------------
# Centralized Algorithmic Configuration & Starting Weights (Section 15)
# -----------------------------------------------------------------------------
DEFAULT_ALGO_CONFIG = {
    # Time decay
    "recency_half_life_hours": 24.0,  # Half-life in hours
    "lambda_decay": math.log(2.0) / 24.0,  # ~0.02888 per hour

    # Positive evidence base weights
    "weight_completed_move": 10.0,
    "weight_incomplete_move": 7.0,
    "weight_cycle_count_positive": 6.0,
    "weight_putaway": 5.0,
    "weight_historical": 3.0,
    "weight_adjacent_bonus": 2.5,
    "weight_same_aisle_bonus": 1.0,

    # Negative evidence base penalties
    "penalty_pick_failure": 6.0,
    "penalty_move_out": 4.0,
    "penalty_cycle_count_zero": 8.0,
    "penalty_conflict": 2.0,

    # Scan-trail confidence factors (Section 17)
    "confidence_completed_scan": 1.0,
    "confidence_incomplete_scan": 0.7,
    "confidence_missing_scan": 0.5,
    "confidence_indirect": 0.5,

    # Softmax normalization
    "temperature": 4.0,
    "unknown_baseline_score": 1.0
}


def compute_recency_factor(
    event_time_str: Any,
    ref_time_str: Optional[Any] = None,
    half_life_hours: float = 24.0
) -> float:
    """
    Computes exponential recency weight decay:
    D(t) = exp(-lambda * delta_t) = 2^(-delta_t / half_life).
    Events 0h old -> 1.0; 24h old -> 0.5; 72h old -> 0.125.
    Clamped to minimum 0.05 to avoid complete erasure of historical trail.
    """
    delta_hours = get_hours_elapsed(event_time_str, ref_time_str)
    decay = math.pow(2.0, -max(0.0, delta_hours) / max(1.0, half_life_hours))
    return max(0.05, min(1.0, decay))


def get_sku_operational_trail(sku: str, db_path=None) -> Dict[str, Any]:
    """Retrieves all historical scans, moves, counts, and failures for a given SKU."""
    putaways = fetch_all(
        "SELECT * FROM put_away_scans WHERE sku = ? ORDER BY timestamp ASC",
        (sku,), db_path=db_path
    )
    moves = fetch_all(
        "SELECT * FROM move_events WHERE sku = ? ORDER BY timestamp ASC",
        (sku,), db_path=db_path
    )
    pick_failures = fetch_all(
        "SELECT * FROM pick_failures WHERE sku = ? ORDER BY timestamp ASC",
        (sku,), db_path=db_path
    )
    cycle_counts = fetch_all(
        "SELECT * FROM cycle_counts WHERE sku = ? ORDER BY timestamp ASC",
        (sku,), db_path=db_path
    )
    locations = fetch_all(
        "SELECT location_id, location_name, zone, aisle, shelf, active_status, active FROM locations",
        db_path=db_path
    )
    current_inv = fetch_all(
        "SELECT * FROM current_inventory WHERE sku = ?",
        (sku,), db_path=db_path
    )

    return {
        "sku": sku,
        "putaways": putaways,
        "moves": moves,
        "pick_failures": pick_failures,
        "cycle_counts": cycle_counts,
        "locations": {loc["location_id"]: loc for loc in locations},
        "current_inventory": current_inv[0] if current_inv else None
    }


def find_discrepancy_locations(
    sku: str,
    expected_location: Optional[str] = None,
    failure_id: Optional[str] = None,
    db_path=None,
    custom_events: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Core Discrepancy Finder Algorithm.

    Evaluates historical scan trails using Bayesian recency-decayed scoring,
    spatial topology, and scan reliability factors to compute probability distributions
    over candidate physical locations with plain-English auditable explanations.
    """
    cfg = {**DEFAULT_ALGO_CONFIG, **(config or {})}
    trail = custom_events if custom_events else get_sku_operational_trail(sku, db_path=db_path)
    locations_dict = trail.get("locations", {})

    # Determine reference timestamp for recency calculation
    # If failure_id provided, use that pick failure's timestamp
    ref_ts = None
    if failure_id and trail.get("pick_failures"):
        for pf in trail["pick_failures"]:
            if pf.get("failure_id") == failure_id:
                ref_ts = pf.get("timestamp")
                if not expected_location:
                    expected_location = pf.get("expected_location") or pf.get("expected_location_id")
                break

    # If no ref_ts, infer latest timestamp across all events in trail
    if not ref_ts:
        all_event_timestamps = []
        for pf in trail.get("pick_failures", []):
            if pf.get("timestamp"):
                all_event_timestamps.append(pf["timestamp"])
        for mv in trail.get("moves", []):
            if mv.get("timestamp"):
                all_event_timestamps.append(mv["timestamp"])
        for cc in trail.get("cycle_counts", []):
            if cc.get("timestamp"):
                all_event_timestamps.append(cc["timestamp"])
        for pa in trail.get("putaways", []):
            if pa.get("timestamp"):
                all_event_timestamps.append(pa["timestamp"])

        if all_event_timestamps:
            ref_ts = max(all_event_timestamps)
        else:
            ref_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Determine expected location if not passed
    if not expected_location:
        if trail.get("pick_failures"):
            pf_last = trail["pick_failures"][-1]
            expected_location = pf_last.get("expected_location") or pf_last.get("expected_location_id")
        elif trail.get("current_inventory"):
            expected_location = trail["current_inventory"].get("location_id") or trail["current_inventory"].get("current_location_id")
        elif trail.get("putaways"):
            expected_location = trail["putaways"][-1].get("location_id")
        else:
            expected_location = "UNKNOWN"

    # Identify all candidate locations touched by historical scan trails
    candidate_locations = set()
    if expected_location and expected_location != "UNKNOWN":
        candidate_locations.add(expected_location)

    for pa in trail.get("putaways", []):
        if pa.get("location_id"):
            candidate_locations.add(pa["location_id"])
    for mv in trail.get("moves", []):
        from_loc = mv.get("from_location") or mv.get("from_location_id")
        to_loc = mv.get("to_location") or mv.get("to_location_id")
        if from_loc:
            candidate_locations.add(from_loc)
        if to_loc:
            candidate_locations.add(to_loc)
    for cc in trail.get("cycle_counts", []):
        if cc.get("location_id"):
            candidate_locations.add(cc["location_id"])
    for pf in trail.get("pick_failures", []):
        loc = pf.get("expected_location") or pf.get("expected_location_id")
        if loc:
            candidate_locations.add(loc)

    # Add spatially adjacent shelves to the expected location (common misplacement)
    if expected_location and expected_location in locations_dict:
        for loc_id in locations_dict:
            if are_locations_adjacent(expected_location, loc_id):
                candidate_locations.add(loc_id)

    # Data structures for score tracking & evidence breakdown
    positive_scores: Dict[str, float] = {loc: 0.0 for loc in candidate_locations}
    negative_scores: Dict[str, float] = {loc: 0.0 for loc in candidate_locations}
    positive_evidence: Dict[str, List[str]] = {loc: [] for loc in candidate_locations}
    negative_evidence: Dict[str, List[str]] = {loc: [] for loc in candidate_locations}

    # Tracking for conflicts and failure modes
    completed_moves_to: List[Tuple[str, str, float]] = []  # (loc, timestamp, recency)
    recent_positive_counts: List[str] = []
    pick_failure_count_at_expected = 0

    # -------------------------------------------------------------------------
    # 1. Evaluate Put-Away Scans
    # -------------------------------------------------------------------------
    for pa in trail.get("putaways", []):
        loc = pa.get("location_id")
        if not loc:
            continue
        ts = pa.get("timestamp", ref_ts)
        recency = compute_recency_factor(ts, ref_ts, cfg["recency_half_life_hours"])
        conf = float(pa.get("confidence", cfg["confidence_completed_scan"]))
        hours_ago = get_hours_elapsed(ts, ref_ts)

        score = cfg["weight_putaway"] * recency * conf
        positive_scores[loc] = positive_scores.get(loc, 0.0) + score
        positive_evidence.setdefault(loc, []).append(
            f"+ Put-away intake scan (+{score:.1f} pts, recency {recency:.2f}, conf {conf:.1f}): "
            f"Stored by {pa.get('employee_id', 'Staff')} {hours_ago:.1f}h ago."
        )

    # -------------------------------------------------------------------------
    # 2. Evaluate Move Events
    # -------------------------------------------------------------------------
    for mv in trail.get("moves", []):
        from_loc = mv.get("from_location") or mv.get("from_location_id")
        to_loc = mv.get("to_location") or mv.get("to_location_id")
        status = mv.get("move_status", "completed")
        ts = mv.get("timestamp", ref_ts)
        recency = compute_recency_factor(ts, ref_ts, cfg["recency_half_life_hours"])
        hours_ago = get_hours_elapsed(ts, ref_ts)

        if status == "completed":
            conf = cfg["confidence_completed_scan"]
            w_to = cfg["weight_completed_move"] * recency * conf
            w_from = cfg["penalty_move_out"] * recency * conf

            if to_loc:
                positive_scores[to_loc] = positive_scores.get(to_loc, 0.0) + w_to
                positive_evidence.setdefault(to_loc, []).append(
                    f"+ Completed move TO location (+{w_to:.1f} pts, recency {recency:.2f}): "
                    f"Moved from {from_loc} by {mv.get('employee_id', 'Staff')} {hours_ago:.1f}h ago."
                )
                completed_moves_to.append((to_loc, ts, recency))

            if from_loc:
                negative_scores[from_loc] = negative_scores.get(from_loc, 0.0) + w_from
                negative_evidence.setdefault(from_loc, []).append(
                    f"- Item moved OUT of location (-{w_from:.1f} pts): "
                    f"Transferred to {to_loc} {hours_ago:.1f}h ago."
                )

        elif status == "incomplete":
            conf = cfg["confidence_incomplete_scan"]
            w_inc = cfg["weight_incomplete_move"] * recency * conf
            if to_loc:
                positive_scores[to_loc] = positive_scores.get(to_loc, 0.0) + w_inc
                positive_evidence.setdefault(to_loc, []).append(
                    f"+ Incomplete/staged move TO location (+{w_inc:.1f} pts): "
                    f"Move initiated to {to_loc} but not finalized; stock likely staged here."
                )

        elif status == "missing_scan":
            conf = cfg["confidence_missing_scan"]
            w_miss = cfg["weight_completed_move"] * recency * conf
            if to_loc:
                positive_scores[to_loc] = positive_scores.get(to_loc, 0.0) + w_miss
                positive_evidence.setdefault(to_loc, []).append(
                    f"+ Missing-scan anomaly (+{w_miss:.1f} pts): Operational signal suggests "
                    f"item diverted to {to_loc} without barcode finalization."
                )

    # -------------------------------------------------------------------------
    # 3. Evaluate Cycle Counts (Physical audits)
    # -------------------------------------------------------------------------
    for cc in trail.get("cycle_counts", []):
        loc = cc.get("location_id")
        if not loc:
            continue
        qty = cc.get("counted_quantity", cc.get("physical_quantity", 0))
        ts = cc.get("timestamp", ref_ts)
        recency = compute_recency_factor(ts, ref_ts, cfg["recency_half_life_hours"])
        hours_ago = get_hours_elapsed(ts, ref_ts)

        if qty > 0:
            w_cc = cfg["weight_cycle_count_positive"] * recency
            positive_scores[loc] = positive_scores.get(loc, 0.0) + w_cc
            positive_evidence.setdefault(loc, []).append(
                f"+ Verified cycle count (+{w_cc:.1f} pts, recency {recency:.2f}): "
                f"{qty} units physically counted by {cc.get('employee_id', cc.get('verified_by', 'Auditor'))} {hours_ago:.1f}h ago."
            )
            if hours_ago <= 72.0:
                recent_positive_counts.append(loc)
        else:
            w_zero = cfg["penalty_cycle_count_zero"] * recency
            negative_scores[loc] = negative_scores.get(loc, 0.0) + w_zero
            negative_evidence.setdefault(loc, []).append(
                f"- Zero-stock cycle count (-{w_zero:.1f} pts): Confirmed empty {hours_ago:.1f}h ago."
            )

    # -------------------------------------------------------------------------
    # 4. Evaluate Pick Failures (Item missing verification)
    # -------------------------------------------------------------------------
    for pf in trail.get("pick_failures", []):
        loc = pf.get("expected_location") or pf.get("expected_location_id")
        if not loc:
            continue
        ts = pf.get("timestamp", ref_ts)
        recency = compute_recency_factor(ts, ref_ts, cfg["recency_half_life_hours"])
        w_pf = cfg["penalty_pick_failure"] * recency
        negative_scores[loc] = negative_scores.get(loc, 0.0) + w_pf
        negative_evidence.setdefault(loc, []).append(
            f"- Pick failure reported (-{w_pf:.1f} pts, recency {recency:.2f}): "
            f"Order {pf.get('order_id', '')} could not find item here. Reason: {pf.get('reason', 'Missing')}."
        )
        if loc == expected_location:
            pick_failure_count_at_expected += 1

    # -------------------------------------------------------------------------
    # 5. Spatial Proximity & Misplacement Heuristics (Supporting evidence)
    # -------------------------------------------------------------------------
    if expected_location and expected_location in candidate_locations:
        for loc in candidate_locations:
            if loc == expected_location:
                continue
            if are_locations_adjacent(expected_location, loc):
                prox_score = cfg["weight_adjacent_bonus"]
                positive_scores[loc] = positive_scores.get(loc, 0.0) + prox_score
                positive_evidence.setdefault(loc, []).append(
                    f"+ Physical adjacency bonus (+{prox_score:.1f} pts): "
                    f"Directly adjacent shelf to expected {expected_location} on same rack."
                )
            elif are_locations_same_aisle(expected_location, loc):
                prox_score = cfg["weight_same_aisle_bonus"]
                positive_scores[loc] = positive_scores.get(loc, 0.0) + prox_score
                positive_evidence.setdefault(loc, []).append(
                    f"+ Same-aisle proximity bonus (+{prox_score:.1f} pts): "
                    f"Located in same aisle as expected {expected_location}."
                )

    # -------------------------------------------------------------------------
    # 6. Conflict Detection (Section 21)
    # -------------------------------------------------------------------------
    conflict_detected = False
    conflict_notes: List[str] = []
    # Identify distinct locations with recent completed moves (recency >= 0.25)
    recent_move_targets = {}
    for loc, ts, rec in completed_moves_to:
        if rec >= 0.25:
            recent_move_targets[loc] = ts

    if len(recent_move_targets) > 1:
        conflict_detected = True
        loc_list_str = " and ".join(recent_move_targets.keys())
        msg = f"Conflict detected: Multiple recent movement records point to different locations ({loc_list_str})."
        conflict_notes.append(msg)
        for loc in recent_move_targets:
            negative_scores[loc] = negative_scores.get(loc, 0.0) + cfg["penalty_conflict"]
            negative_evidence.setdefault(loc, []).append(
                f"- Conflicting scan penalty (-{cfg['penalty_conflict']:.1f} pts): Contradictory recent move logged."
            )

    # -------------------------------------------------------------------------
    # 7. Inactive / Invalid Location Filtering (Section 22)
    # -------------------------------------------------------------------------
    valid_scores: Dict[str, float] = {}
    excluded_locations: Dict[str, Dict[str, Any]] = {}

    for loc in candidate_locations:
        raw_score = positive_scores.get(loc, 0.0) - negative_scores.get(loc, 0.0)
        loc_meta = locations_dict.get(loc)

        is_active = True
        status_text = "Active"
        if loc_meta:
            if "active" in loc_meta and loc_meta["active"] in [0, False, "0"]:
                is_active = False
                status_text = "Inactive"
            elif "active_status" in loc_meta and str(loc_meta["active_status"]).lower() != "active":
                is_active = False
                status_text = str(loc_meta["active_status"])

        if not is_active:
            excluded_locations[loc] = {
                "location_id": loc,
                "raw_score": round(raw_score, 2),
                "reason": f"Location is inactive/decommissioned (Status: '{status_text}'). Excluded from recommendations.",
                "positive_evidence": positive_evidence.get(loc, []),
                "negative_evidence": negative_evidence.get(loc, [])
            }
            continue

        valid_scores[loc] = raw_score

    # -------------------------------------------------------------------------
    # 8. Phantom Inventory & Sensor Drift Detection (Sections 23, 24)
    # -------------------------------------------------------------------------
    phantom_inventory_warning = False
    phantom_message = ""
    # Phantom pattern: Repeated pick failures at expected_location, no positive moves or cycle counts elsewhere
    has_positive_move = any(rec >= 0.20 for _, _, rec in completed_moves_to)
    if pick_failure_count_at_expected >= 2 and not has_positive_move and not recent_positive_counts:
        phantom_inventory_warning = True
        phantom_message = (
            "⚠️ Possible Phantom Inventory Detected: Multiple pick failures recorded with no confirming "
            "physical movements or cycle counts. Stock may be depleted, stolen, or unrecorded scrap."
        )

    scan_drift_warning = False
    drift_message = ""
    if conflict_detected or (expected_location and positive_scores.get(expected_location, 0) == 0 and pick_failure_count_at_expected >= 2):
        scan_drift_warning = True
        drift_message = (
            "⚠️ Scan/Sensor Drift Warning: Persistent mismatch between system expectation and physical scans. "
            "Inspect physical barcode labels in this storage zone for label damage or scanning errors."
        )

    # -------------------------------------------------------------------------
    # 9. Probability Normalization via Softmax with Numerical Stability (Section 19)
    # -------------------------------------------------------------------------
    # Residual uncertainty score for UNKNOWN / Lost in Transit
    valid_scores["UNKNOWN"] = cfg["unknown_baseline_score"]
    positive_evidence["UNKNOWN"] = ["Baseline residual probability accounting for unrecorded transit or stock shrinkage."]
    negative_evidence["UNKNOWN"] = []

    temperature = cfg["temperature"]
    max_raw_score = max(valid_scores.values())

    exp_scores = {}
    for loc, raw in valid_scores.items():
        # Shift scores for numerical stability
        shifted = (raw - max_raw_score) / temperature
        exp_scores[loc] = math.exp(max(-10.0, min(10.0, shifted)))

    total_exp = sum(exp_scores.values())
    probabilities = {loc: exp_scores[loc] / total_exp for loc in exp_scores}

    # Rank candidate locations descending by probability
    ranked = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)

    recommendations = []
    for rank_idx, (loc, prob) in enumerate(ranked, start=1):
        loc_info = locations_dict.get(loc, {})
        all_ev = positive_evidence.get(loc, []) + negative_evidence.get(loc, [])
        recommendations.append({
            "rank": rank_idx,
            "location_id": loc,
            "location_name": loc_info.get("location_name", "Unknown Location / In-Transit"),
            "zone": loc_info.get("zone", "Unassigned"),
            "aisle": loc_info.get("aisle", parse_location(loc)[0]),
            "shelf": loc_info.get("shelf", parse_location(loc)[1]),
            "is_active": loc not in excluded_locations,
            "probability": round(prob, 4),
            "percentage": f"{prob * 100.0:.1f}%",
            "raw_score": round(valid_scores.get(loc, 0.0), 2),
            "positive_evidence": positive_evidence.get(loc, []),
            "negative_evidence": negative_evidence.get(loc, []),
            "evidence": all_ev if all_ev else ["No direct scan evidence."]
        })

    # Filter out UNKNOWN from top-1 recommendation target if valid candidate exists
    candidate_recs = [r for r in recommendations if r["location_id"] != "UNKNOWN"]
    top_rec = candidate_recs[0] if candidate_recs else recommendations[0]

    # Calculate confidence level (Section 20)
    top_p = top_rec["probability"] if top_rec else 0.0
    second_p = candidate_recs[1]["probability"] if len(candidate_recs) > 1 else 0.0
    margin = top_p - second_p

    if top_p >= 0.55 and margin >= 0.15 and not conflict_detected:
        confidence = "High"
    elif top_p >= 0.35 or margin >= 0.08:
        confidence = "Medium"
    else:
        confidence = "Low"

    top3_coverage = sum(r["probability"] for r in candidate_recs[:3])

    return {
        "sku": sku,
        "expected_location": expected_location,
        "status": "ITEM NOT FOUND AT EXPECTED LOCATION",
        "recommended_location": top_rec["location_id"] if top_rec else "UNKNOWN",
        "top_probability": top_p,
        "top3_coverage": round(top3_coverage, 4),
        "confidence": confidence,
        "conflict_detected": conflict_detected,
        "conflict_notes": conflict_notes,
        "phantom_inventory_detected": phantom_inventory_warning,
        "phantom_message": phantom_message,
        "scan_drift_detected": scan_drift_warning,
        "scan_drift_message": drift_message,
        "recommendations": recommendations,
        "excluded_locations": excluded_locations,
        "evaluation_timestamp": ref_ts
    }


if __name__ == "__main__":
    print("Algorithm module loaded successfully.")
