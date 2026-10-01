"""
Utility functions for Dark Store Inventory-Location Discrepancy Finder.
Provides shelf adjacency calculations, spatial distance/proximity modeling,
timestamp parsing, recency decay helpers, CSV validation, and formatting utilities.
"""

from datetime import datetime
import re
from typing import Tuple, Dict, Any, List, Optional
import pandas as pd


def parse_location(location_id: str) -> Tuple[str, int]:
    """
    Parses a location identifier (e.g., 'A12', 'B08', 'C03', 'E05') into aisle letter and shelf number.
    Returns (aisle_str, shelf_num).
    """
    if not location_id:
        return ("", 0)
    match = re.match(r"^([A-Za-z]+)(\d+)$", str(location_id).strip().upper())
    if match:
        return match.group(1), int(match.group(2))
    return (str(location_id).strip().upper(), 0)


def compute_location_distance(
    loc1: str,
    loc2: str,
    locations_dict: Optional[Dict[str, Any]] = None
) -> float:
    """
    Computes spatial Manhattan-style warehouse distance between two locations:
    distance = aisle_difference * 2.0 + shelf_difference + zone_penalty.
    Used for physical proximity bonus in misplacement heuristics.
    """
    if not loc1 or not loc2 or loc1 == loc2:
        return 0.0

    aisle1, shelf1 = parse_location(loc1)
    aisle2, shelf2 = parse_location(loc2)

    # Aisle difference (e.g. A vs B = 1)
    if aisle1 and aisle2 and len(aisle1) == 1 and len(aisle2) == 1:
        aisle_diff = abs(ord(aisle1) - ord(aisle2))
    else:
        aisle_diff = 2.0 if aisle1 != aisle2 else 0.0

    shelf_diff = abs(shelf1 - shelf2)

    # Zone penalty
    zone_penalty = 0.0
    if locations_dict:
        meta1 = locations_dict.get(loc1, {})
        meta2 = locations_dict.get(loc2, {})
        zone1 = meta1.get("zone", aisle1)
        zone2 = meta2.get("zone", aisle2)
        if zone1 != zone2:
            zone_penalty = 4.0
    elif aisle1 != aisle2:
        zone_penalty = 2.0

    return (aisle_diff * 2.0) + shelf_diff + zone_penalty


def compute_proximity_weight(distance: float) -> float:
    """
    Converts spatial distance into a proximity factor:
    proximity_weight = 1.0 / (1.0 + distance).
    Direct neighbors receive higher bonus; distant shelves receive near-zero bonus.
    """
    return 1.0 / (1.0 + max(0.0, distance))


def are_locations_adjacent(loc1: str, loc2: str) -> bool:
    """
    Returns True if two locations are physically adjacent on the same aisle/rack
    (e.g., A11 and A12, or same shelf).
    """
    if not loc1 or not loc2 or loc1 == loc2:
        return False
    aisle1, num1 = parse_location(loc1)
    aisle2, num2 = parse_location(loc2)
    return (aisle1 == aisle2 and abs(num1 - num2) <= 1)


def are_locations_same_aisle(loc1: str, loc2: str) -> bool:
    """
    Returns True if two locations are within the same aisle (e.g., A01 and A08).
    """
    if not loc1 or not loc2 or loc1 == loc2:
        return False
    aisle1, _ = parse_location(loc1)
    aisle2, _ = parse_location(loc2)
    return (aisle1 == aisle2 and bool(aisle1))


def parse_timestamp(ts_str: Any) -> datetime:
    """Safely parses timestamp string into datetime object."""
    if isinstance(ts_str, datetime):
        return ts_str
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S"
    ]
    cleaned = str(ts_str).strip()
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except (ValueError, TypeError):
            continue
    # Fallback to current time if unparseable
    return datetime.now()


def get_hours_elapsed(earlier_ts: Any, reference_ts: Any = None) -> float:
    """Calculates hours elapsed between earlier_ts and reference_ts (or now)."""
    t_start = parse_timestamp(earlier_ts)
    t_ref = parse_timestamp(reference_ts) if reference_ts else datetime.now()
    diff = (t_ref - t_start).total_seconds()
    return max(0.0, diff / 3600.0)


def format_probability(prob: Optional[float]) -> str:
    """Formats float probability (0.0 to 1.0) into readable percentage string."""
    if prob is None:
        return "N/A"
    return f"{prob * 100.0:.1f}%"


def convert_df_to_csv(df: pd.DataFrame) -> bytes:
    """Encodes a Pandas DataFrame into UTF-8 CSV bytes for download."""
    return df.to_csv(index=False).encode("utf-8")


# -----------------------------------------------------------------------------
# CSV Upload Validation Helper
# -----------------------------------------------------------------------------
REQUIRED_TABLE_COLUMNS: Dict[str, List[str]] = {
    "locations": ["location_id", "zone"],
    "inventory": ["sku", "item_name", "current_location_id"],
    "current_inventory": ["sku", "item_name", "location_id"],
    "putaway_scans": ["sku", "location_id", "timestamp"],
    "put_away_scans": ["sku", "location_id", "timestamp"],
    "move_events": ["sku", "timestamp"],
    "pick_failures": ["sku", "expected_location_id", "timestamp"],
    "cycle_counts": ["sku", "location_id", "timestamp"],
    "audit_history": ["sku", "previous_location", "new_location"],
    "stakeholder_feedback": ["role", "q1_easy", "q2_useful"]
}


def validate_csv_data(
    df: pd.DataFrame,
    table_name: str,
    valid_locations: Optional[List[str]] = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Validates uploaded CSV against schema rules:
    - Required columns presence
    - Null / missing value detection
    - Duplicate primary key check
    - Location validity check
    - Timestamp validity check

    Returns:
    (is_valid: bool, errors: List[str], warnings: List[str])
    """
    errors: List[str] = []
    warnings: List[str] = []

    if df.empty:
        errors.append("Uploaded CSV is empty (0 rows).")
        return False, errors, warnings

    # 1. Required column validation
    table_key = table_name.lower().strip()
    req_cols = REQUIRED_TABLE_COLUMNS.get(table_key, [])
    # Support alternate column names (e.g. expected_location vs expected_location_id)
    alias_map = {
        "expected_location_id": "expected_location",
        "current_location_id": "location_id",
        "counted_quantity": "physical_quantity",
        "from_location_id": "from_location",
        "to_location_id": "to_location"
    }

    missing_cols = []
    for col in req_cols:
        if col not in df.columns:
            alt = alias_map.get(col)
            if not alt or alt not in df.columns:
                missing_cols.append(col)

    if missing_cols:
        errors.append(f"Missing required column(s): {', '.join(missing_cols)}")

    # 2. Check null values in critical fields
    for col in df.columns:
        null_count = df[col].isnull().sum()
        if null_count > 0:
            if col in ["sku", "location_id", "expected_location", "expected_location_id", "location_name"]:
                errors.append(f"Column '{col}' contains {null_count} null/empty values.")
            else:
                warnings.append(f"Column '{col}' has {null_count} missing values (will use defaults).")

    # 3. Check duplicate primary keys where applicable
    pk_map = {
        "locations": "location_id",
        "current_inventory": "sku",
        "inventory": "sku",
        "pick_failures": "failure_id",
        "cycle_counts": "count_id"
    }
    pk_col = pk_map.get(table_key)
    if pk_col and pk_col in df.columns:
        dupes = df[pk_col].duplicated().sum()
        if dupes > 0:
            errors.append(f"Primary key '{pk_col}' contains {dupes} duplicate entries.")

    # 4. Check location validity against existing location master
    if valid_locations:
        loc_cols = [c for c in ["location_id", "expected_location", "expected_location_id", "to_location"] if c in df.columns]
        for col in loc_cols:
            unknown = set(df[col].dropna().astype(str).unique()) - set(valid_locations)
            if unknown:
                warnings.append(
                    f"Column '{col}' contains unknown locations not currently in Location Master: {list(unknown)[:5]}"
                )

    # 5. Timestamp validation
    ts_cols = [c for c in ["timestamp", "last_updated", "updated_at"] if c in df.columns]
    for col in ts_cols:
        invalid_ts_count = 0
        for val in df[col].dropna().head(50):
            try:
                parse_timestamp(val)
            except Exception:
                invalid_ts_count += 1
        if invalid_ts_count > 0:
            errors.append(f"Column '{col}' contains invalid timestamp formats.")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings
