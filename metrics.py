"""
Performance Metrics, Benchmark Experiment, Error Analysis, and Multi-Objective Trade-Off Models.

Quantifies Cost, Service, Emissions, and Reliability trade-offs comparing
the Explainable Probability Prototype against the Naive Sequential Baseline.

Provides dedicated Section 31 Error Analysis engine categorizing failure modes:
- Missing evidence
- Conflicting evidence
- Stale evidence
- Incorrect scan
- Phantom inventory
- Invalid location
- Insufficient history

All calculated financial and emissions metrics are transparently labeled as
ESTIMATES / ASSUMPTIONS per academic evaluation guidelines.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from data_generator import generate_benchmark_test_cases, generate_locations
from algorithm import find_discrepancy_locations
from baseline import (
    run_baseline_search, run_prototype_search, run_random_baseline_search,
    DEFAULT_SECONDS_PER_LOCATION_CHECK, DEFAULT_FIXED_LOOKUP_SECONDS
)


def run_discrepancy_benchmark(
    num_cases: int = 56,
    seconds_per_check: float = DEFAULT_SECONDS_PER_LOCATION_CHECK,
    fixed_lookup_seconds: float = DEFAULT_FIXED_LOOKUP_SECONDS,
    db_path=None,
    seed: int = 101,
    include_random_baseline: bool = True
) -> Dict[str, Any]:
    """
    Executes a controlled benchmark experiment across 50, 56, 75, or 100 realistic dark store discrepancy cases.
    Directly compares Baseline Sequential Walk vs Probability Prototype vs Optional Random Search.
    Performs comprehensive per-case error analysis and categorization.
    """
    test_cases = generate_benchmark_test_cases(num_cases=num_cases, seed=seed)
    locations_df = generate_locations()
    active_locs = locations_df[locations_df["active"] == 1]["location_id"].tolist()
    loc_meta = {loc["location_id"]: loc for loc in locations_df.to_dict(orient="records")}

    results = []
    error_analysis_records = []

    sim_ref_time = datetime(2026, 9, 15, 10, 0, 0)

    for case in test_cases:
        sku = case["sku"]
        expected_loc = case["expected_location"]
        true_loc = case["true_location"]
        dtype = case["discrepancy_type"]

        # Synthesize realistic historical event trail leading to this discrepancy
        events = {
            "sku": sku,
            "locations": loc_meta,
            "putaways": [
                {
                    "location_id": expected_loc,
                    "timestamp": (sim_ref_time - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "employee_id": "EMP-101",
                    "confidence": 1.0
                }
            ],
            "moves": [],
            "pick_failures": [
                {
                    "failure_id": f"PF-SIM-{case['case_id']}",
                    "expected_location": expected_loc,
                    "timestamp": (sim_ref_time - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
                    "reason": "Missing on shelf",
                    "order_id": f"ORD-{case['case_id']}"
                }
            ],
            "cycle_counts": []
        }

        # Inject evidence corresponding to the discrepancy pattern
        if dtype == "completed_move_discrepancy":
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": true_loc,
                "move_status": "completed",
                "timestamp": (sim_ref_time - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-104"
            })
        elif dtype == "incomplete_move_staging":
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": true_loc,
                "move_status": "incomplete",
                "timestamp": (sim_ref_time - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-108"
            })
        elif dtype == "missing_move_scan_adjacent":
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": true_loc,
                "move_status": "missing_scan",
                "timestamp": (sim_ref_time - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-102"
            })
        elif dtype == "misplaced_putaway":
            events["cycle_counts"].append({
                "location_id": true_loc,
                "counted_quantity": 12,
                "physical_quantity": 12,
                "timestamp": (sim_ref_time - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-115",
                "verified_by": "EMP-115"
            })
        elif dtype == "stale_cycle_count_discrepancy":
            events["cycle_counts"].append({
                "location_id": expected_loc,
                "counted_quantity": 15,
                "physical_quantity": 15,
                "timestamp": (sim_ref_time - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-112",
                "verified_by": "EMP-112"
            })
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": true_loc,
                "move_status": "completed",
                "timestamp": (sim_ref_time - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-104"
            })
        elif dtype == "conflicting_scans_divergence":
            alt_target = "B08" if true_loc != "B08" else "C09"
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": true_loc,
                "move_status": "completed",
                "timestamp": (sim_ref_time - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-104"
            })
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": alt_target,
                "move_status": "completed",
                "timestamp": (sim_ref_time - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-108"
            })
        elif dtype == "phantom_inventory_loss":
            events["cycle_counts"].append({
                "location_id": expected_loc,
                "counted_quantity": 0,
                "physical_quantity": 0,
                "timestamp": (sim_ref_time - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-112",
                "verified_by": "EMP-112"
            })
            events["pick_failures"].append({
                "failure_id": f"PF-SIM-2-{case['case_id']}",
                "expected_location": expected_loc,
                "timestamp": (sim_ref_time - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
                "reason": "Repeated missing stock on re-attempt",
                "order_id": f"ORD-2-{case['case_id']}"
            })
        elif dtype == "invalid_location_move":
            events["moves"].append({
                "from_location": expected_loc,
                "to_location": "Z99",
                "move_status": "completed",
                "timestamp": (sim_ref_time - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "employee_id": "EMP-104"
            })
        else:  # unscanned_distant_move
            # Unrecorded move to a non-adjacent shelf; pick failure at expected
            pass

        # Run Probability Prototype
        proto_output = find_discrepancy_locations(
            sku=sku,
            expected_location=expected_loc,
            custom_events=events
        )
        proto_sim = run_prototype_search(
            proto_output["recommendations"],
            true_physical_location=true_loc,
            all_locations=active_locs,
            seconds_per_check=seconds_per_check,
            fixed_lookup_seconds=fixed_lookup_seconds
        )

        # Run Sequential Walk Baseline
        base_sim = run_baseline_search(
            expected_location=expected_loc,
            true_physical_location=true_loc,
            all_locations=active_locs,
            seconds_per_check=seconds_per_check,
            fixed_lookup_seconds=fixed_lookup_seconds
        )

        # Optional Random Search Baseline
        rand_steps = 0
        rand_time_min = 0.0
        if include_random_baseline:
            rand_sim = run_random_baseline_search(
                expected_location=expected_loc,
                true_physical_location=true_loc,
                all_locations=active_locs,
                seconds_per_check=seconds_per_check,
                fixed_lookup_seconds=fixed_lookup_seconds,
                seed=seed + int(case["case_id"].split("-")[1])
            )
            rand_steps = rand_sim["locations_checked"]
            rand_time_min = round(rand_sim["search_time_minutes"], 2)

        top1_correct = (proto_output["recommended_location"] == true_loc)
        candidate_ids = [r["location_id"] for r in proto_output["recommendations"] if r["location_id"] != "UNKNOWN"]
        top3_locs = candidate_ids[:3]
        top3_correct = (true_loc in top3_locs)
        rank_found = proto_sim.get("rank_found")

        rec_entry = {
            "case_id": case["case_id"],
            "sku": sku,
            "item_name": case["item_name"],
            "expected_location": expected_loc,
            "true_location": true_loc,
            "discrepancy_type": dtype,
            "recommended_top1": proto_output["recommended_location"],
            "top1_probability": proto_output["top_probability"],
            "confidence": proto_output["confidence"],
            "top1_correct": top1_correct,
            "top3_correct": top3_correct,
            "rank_found": rank_found if rank_found is not None else 999,
            "baseline_steps": base_sim["locations_checked"],
            "baseline_time_sec": base_sim["search_time_seconds"],
            "baseline_time_min": round(base_sim["search_time_minutes"], 2),
            "prototype_steps": proto_sim["locations_checked"],
            "prototype_time_sec": proto_sim["search_time_seconds"],
            "prototype_time_min": round(proto_sim["search_time_minutes"], 2),
            "time_saved_sec": base_sim["search_time_seconds"] - proto_sim["search_time_seconds"],
            "time_saved_min": round(base_sim["search_time_minutes"] - proto_sim["search_time_minutes"], 2)
        }
        if include_random_baseline:
            rec_entry["random_baseline_steps"] = rand_steps
            rec_entry["random_baseline_time_min"] = rand_time_min

        results.append(rec_entry)

        # ---------------------------------------------------------------------
        # Error Analysis Classification (Section 31)
        # ---------------------------------------------------------------------
        if not top1_correct:
            # Determine primary root cause
            if dtype == "phantom_inventory_loss" or proto_output.get("phantom_inventory_detected"):
                err_category = "Phantom inventory"
                why_failed = "Stock missing or depleted in dark store; repeated pick failures occurred."
            elif dtype == "invalid_location_move" or "Z99" in proto_output.get("excluded_locations", {}):
                err_category = "Invalid location"
                why_failed = "Scan trail pointed to decommissioned shelf Z99; excluded from valid recommendations."
            elif dtype == "conflicting_scans_divergence" or proto_output.get("conflict_detected"):
                err_category = "Conflicting evidence"
                why_failed = "Multiple contradictory scan events occurred in close temporal proximity."
            elif dtype == "stale_cycle_count_discrepancy":
                err_category = "Stale evidence"
                why_failed = "Older cycle count retained residual score despite exponential decay."
            elif dtype == "misplaced_putaway":
                err_category = "Incorrect scan"
                why_failed = "Put-away scan at wrong shelf competed against physical verification evidence."
            elif dtype == "unscanned_distant_move":
                err_category = "Insufficient history"
                why_failed = "Physical transfer omitted barcode scan to distant shelf; no historical trail."
            else:
                err_category = "Missing evidence"
                why_failed = "Scan trail was partial or indirect."

            error_analysis_records.append({
                "case_id": case["case_id"],
                "sku": sku,
                "expected_location": expected_loc,
                "actual_location": true_loc,
                "top_recommendation": proto_output["recommended_location"],
                "actual_location_rank": rank_found,
                "top1_probability": f"{proto_output['top_probability']*100:.1f}%",
                "error_category": err_category,
                "likely_reason": why_failed,
                "human_recoverable": (rank_found is not None and rank_found <= 3)
            })

    df = pd.DataFrame(results)
    error_df = pd.DataFrame(error_analysis_records)

    # Compute Summary Statistics
    total_cases = len(df)
    avg_base_steps = float(df["baseline_steps"].mean())
    avg_proto_steps = float(df["prototype_steps"].mean())
    avg_base_time_min = float(df["baseline_time_min"].mean())
    avg_proto_time_min = float(df["prototype_time_min"].mean())
    avg_time_saved_min = avg_base_time_min - avg_proto_time_min
    time_improvement_pct = ((avg_base_time_min - avg_proto_time_min) / max(0.01, avg_base_time_min)) * 100.0

    top1_accuracy = float((df["top1_correct"].sum() / total_cases) * 100.0)
    top3_accuracy = float((df["top3_correct"].sum() / total_cases) * 100.0)

    # Error Category Breakdown
    error_summary = {}
    if not error_df.empty:
        error_summary = error_df["error_category"].value_counts().to_dict()

    return {
        "summary": {
            "total_cases": total_cases,
            "top1_accuracy_pct": round(top1_accuracy, 1),
            "top3_accuracy_pct": round(top3_accuracy, 1),
            "unresolved_rate_pct": round(100.0 - top3_accuracy, 1),
            "avg_baseline_steps": round(avg_base_steps, 1),
            "avg_prototype_steps": round(avg_proto_steps, 1),
            "avg_baseline_time_min": round(avg_base_time_min, 2),
            "avg_prototype_time_min": round(avg_proto_time_min, 2),
            "avg_time_saved_min": round(avg_time_saved_min, 2),
            "time_improvement_pct": round(time_improvement_pct, 1),
            "seconds_per_check": seconds_per_check,
            "fixed_lookup_seconds": fixed_lookup_seconds
        },
        "details_df": df,
        "error_analysis_df": error_df,
        "error_category_breakdown": error_summary
    }


def calculate_tradeoffs(
    benchmark_summary: Dict[str, Any],
    monthly_discrepancies: int = 1200,
    hourly_labor_rate: float = 18.0,
    monthly_system_cost: float = 120.0,
    sla_target_minutes: float = 10.0,
    replacement_delivery_rate: float = 0.25,
    co2_kg_per_replacement_trip: float = 0.45
) -> Dict[str, Any]:
    """
    Quantifies multi-objective trade-offs across Cost, Service, Emissions, and Reliability (Section 34).
    All metrics explicitly annotated as SIMULATION ESTIMATES.
    """
    time_saved_per_case_min = benchmark_summary.get("avg_time_saved_min", 4.5)
    total_hours_saved_monthly = (monthly_discrepancies * time_saved_per_case_min) / 60.0

    # 1. Cost Trade-offs (Section 34)
    gross_labor_savings = total_hours_saved_monthly * hourly_labor_rate
    net_monthly_savings = gross_labor_savings - monthly_system_cost
    annual_net_savings = net_monthly_savings * 12.0
    roi_percentage = (net_monthly_savings / max(1.0, monthly_system_cost)) * 100.0

    # 2. Service Impact (Section 34)
    orders_saved_from_breach = round(monthly_discrepancies * 0.42)
    fulfillment_cycle_reduction_pct = min(
        40.0,
        round((time_saved_per_case_min / max(1.0, sla_target_minutes)) * 100.0, 1)
    )

    # 3. Emissions Model (Section 34)
    avoided_trips_monthly = round(monthly_discrepancies * replacement_delivery_rate)
    co2_saved_kg_monthly = avoided_trips_monthly * co2_kg_per_replacement_trip
    co2_saved_kg_annual = co2_saved_kg_monthly * 12.0

    # 4. Reliability Metrics (Section 34)
    top1_acc = benchmark_summary.get("top1_accuracy_pct", 85.0)
    top3_acc = benchmark_summary.get("top3_accuracy_pct", 95.0)
    failure_rate = round(100.0 - top3_acc, 1)

    return {
        "cost": {
            "total_hours_saved_monthly": round(total_hours_saved_monthly, 1),
            "gross_labor_savings": round(gross_labor_savings, 2),
            "monthly_system_cost": round(monthly_system_cost, 2),
            "net_monthly_savings": round(net_monthly_savings, 2),
            "annual_net_savings": round(annual_net_savings, 2),
            "roi_percentage": round(roi_percentage, 1),
            "hourly_labor_rate": hourly_labor_rate,
            "label": "SIMULATION ESTIMATE"
        },
        "service": {
            "time_saved_per_discrepancy_min": round(time_saved_per_case_min, 2),
            "fulfillment_cycle_reduction_pct": fulfillment_cycle_reduction_pct,
            "estimated_sla_breaches_prevented": orders_saved_from_breach,
            "sla_target_minutes": sla_target_minutes,
            "label": "SIMULATION ESTIMATE"
        },
        "emissions": {
            "avoided_replacement_trips_monthly": avoided_trips_monthly,
            "co2_saved_kg_monthly": round(co2_saved_kg_monthly, 2),
            "co2_saved_kg_annual": round(co2_saved_kg_annual, 2),
            "co2_kg_per_trip": co2_kg_per_replacement_trip,
            "label": "SIMULATION ESTIMATE",
            "assumptions_note": (
                f"Assumes {replacement_delivery_rate*100:.0f}% of unlocated items require a secondary courier dispatch, "
                f"emitting {co2_kg_per_replacement_trip} kg CO2 per two-wheeler delivery trip."
            )
        },
        "reliability": {
            "top1_accuracy_pct": top1_acc,
            "top3_accuracy_pct": top3_acc,
            "unresolved_rate_pct": failure_rate,
            "false_positive_rate_pct": round(100.0 - top1_acc, 1),
            "label": "EMPIRICAL SIMULATION RESULT"
        }
    }


if __name__ == "__main__":
    print("Running benchmark verification (56 cases)...")
    res = run_discrepancy_benchmark(num_cases=56)
    print("Summary:", res["summary"])
    print("Error breakdown:", res["error_category_breakdown"])
