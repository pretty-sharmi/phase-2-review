"""
Database Layer for Dark Store Inventory-Location Discrepancy Finder.
Handles SQLite schema creation, data persistence, atomic audit logging,
relational integrity, and querying using standard Python sqlite3.
Supports Section 9 relational schema specifications and full backwards compatibility.
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

DEFAULT_DB_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "darkstore.db")


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Establishes and returns a connection to SQLite database."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """
    Initializes SQLite database with all required dark store relational tables.
    Matches Section 9 relational schema specifications while preserving backward compatibility.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. Location Master
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS locations (
        location_id TEXT PRIMARY KEY,
        location_name TEXT NOT NULL,
        zone TEXT NOT NULL,
        aisle TEXT NOT NULL DEFAULT 'A',
        shelf INTEGER NOT NULL DEFAULT 1,
        location_type TEXT NOT NULL DEFAULT 'Shelf',
        capacity INTEGER NOT NULL DEFAULT 150,
        active INTEGER NOT NULL DEFAULT 1,
        active_status TEXT NOT NULL DEFAULT 'Active'
    );
    """)

    # 2. Inventory State (Current physical / system state)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        inventory_id TEXT PRIMARY KEY,
        sku TEXT NOT NULL UNIQUE,
        item_name TEXT NOT NULL,
        current_location_id TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'In Stock',
        updated_at TEXT NOT NULL,
        FOREIGN KEY (current_location_id) REFERENCES locations(location_id)
    );
    """)

    # Backwards-compatible current_inventory table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS current_inventory (
        sku TEXT PRIMARY KEY,
        item_name TEXT NOT NULL,
        location_id TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        last_updated TEXT NOT NULL,
        FOREIGN KEY (location_id) REFERENCES locations(location_id)
    );
    """)

    # 3. Put-Away Scans
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS put_away_scans (
        putaway_id TEXT PRIMARY KEY,
        event_id TEXT,
        sku TEXT NOT NULL,
        item_name TEXT NOT NULL DEFAULT '',
        quantity INTEGER NOT NULL DEFAULT 1,
        location_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        employee_id TEXT NOT NULL,
        scan_status TEXT NOT NULL DEFAULT 'completed',
        confidence REAL NOT NULL DEFAULT 1.0,
        FOREIGN KEY (location_id) REFERENCES locations(location_id)
    );
    """)

    # 4. Move Events
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS move_events (
        move_id TEXT PRIMARY KEY,
        event_id TEXT,
        sku TEXT NOT NULL,
        item_name TEXT NOT NULL DEFAULT '',
        from_location_id TEXT NOT NULL,
        from_location TEXT NOT NULL,
        to_location_id TEXT NOT NULL,
        to_location TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        timestamp TEXT NOT NULL,
        employee_id TEXT NOT NULL,
        move_status TEXT NOT NULL CHECK(move_status IN ('completed', 'incomplete', 'missing_scan')),
        scan_complete INTEGER NOT NULL DEFAULT 1
    );
    """)

    # 5. Pick Failures
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pick_failures (
        failure_id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        sku TEXT NOT NULL,
        expected_location_id TEXT NOT NULL,
        expected_location TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'unresolved',
        resolved_status TEXT NOT NULL DEFAULT 'unresolved',
        reason TEXT NOT NULL
    );
    """)

    # 6. Cycle Counts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cycle_counts (
        count_id TEXT PRIMARY KEY,
        sku TEXT NOT NULL,
        location_id TEXT NOT NULL,
        counted_quantity INTEGER NOT NULL DEFAULT 0,
        physical_quantity INTEGER NOT NULL DEFAULT 0,
        timestamp TEXT NOT NULL,
        employee_id TEXT NOT NULL,
        verified_by TEXT NOT NULL,
        FOREIGN KEY (location_id) REFERENCES locations(location_id)
    );
    """)

    # 7. Audit History (Immutable ledger of verified physical updates)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_history (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        previous_location TEXT NOT NULL,
        new_location TEXT NOT NULL,
        action_type TEXT NOT NULL,
        reason TEXT NOT NULL,
        user_role TEXT NOT NULL DEFAULT 'Picker / Associate',
        user_name TEXT NOT NULL DEFAULT 'Store Associate',
        user TEXT NOT NULL DEFAULT 'Store Associate',
        probability_score REAL,
        evidence_notes TEXT,
        evidence TEXT,
        timestamp TEXT NOT NULL
    );
    """)

    # 8. Stakeholder Feedback
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stakeholder_feedback (
        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
        id INTEGER,
        role TEXT NOT NULL,
        understandability INTEGER NOT NULL DEFAULT 5,
        probability_usefulness INTEGER NOT NULL DEFAULT 5,
        search_time_reduction INTEGER NOT NULL DEFAULT 5,
        trust INTEGER NOT NULL DEFAULT 5,
        improvements TEXT DEFAULT '',
        q1_easy INTEGER NOT NULL DEFAULT 5,
        q2_useful INTEGER NOT NULL DEFAULT 5,
        q3_reduce_time INTEGER NOT NULL DEFAULT 5,
        q4_trust INTEGER NOT NULL DEFAULT 5,
        q5_comments TEXT DEFAULT '',
        timestamp TEXT NOT NULL
    );
    """)

    # High-Performance Indexes for Scan Trail Ingestion
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_putaway_sku ON put_away_scans(sku);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_putaway_ts ON put_away_scans(timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_move_sku ON move_events(sku);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_move_ts ON move_events(timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pick_sku ON pick_failures(sku);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pick_status ON pick_failures(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_count_sku ON cycle_counts(sku);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_sku ON audit_history(sku);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_history(timestamp);")

    conn.commit()
    conn.close()


def execute_query(sql: str, params: tuple = (), db_path: Optional[str] = None) -> Optional[int]:
    """Executes an INSERT, UPDATE, or DELETE query and commits."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def fetch_all(sql: str, params: tuple = (), db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Executes a SELECT query and returns rows as dictionaries."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def fetch_one(sql: str, params: tuple = (), db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Executes a SELECT query and returns a single row dictionary."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_dataframe(sql: str, params: tuple = (), db_path: Optional[str] = None) -> pd.DataFrame:
    """Executes a SELECT query and returns a pandas DataFrame."""
    conn = get_connection(db_path)
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def record_audit_entry(
    sku: str,
    previous_location: str,
    new_location: str,
    action_type: str,
    reason: str,
    probability_score: Optional[float],
    evidence: str,
    user: str = "Store Associate",
    user_role: str = "Picker / Associate",
    user_name: Optional[str] = None,
    db_path: Optional[str] = None,
    failure_id_to_resolve: Optional[str] = None
) -> int:
    """
    CRITICAL HUMAN-IN-THE-LOOP REQUIREMENT:
    Atomically records an immutable audit log entry AND updates current inventory locations.
    Never silently overwrites without an audit record.
    Optionally marks the associated pick failure as resolved.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uname = user_name or user

    try:
        # 1. Insert immutable audit history record
        cursor.execute("""
            INSERT INTO audit_history (
                sku, previous_location, new_location, action_type,
                reason, user_role, user_name, user, probability_score,
                evidence_notes, evidence, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sku,
            previous_location,
            new_location,
            action_type,
            reason,
            user_role,
            uname,
            uname,
            round(float(probability_score), 4) if probability_score is not None else None,
            evidence,
            evidence,
            now_str
        ))
        audit_id = cursor.lastrowid

        # 2. Update current inventory location in current_inventory
        cursor.execute("""
            UPDATE current_inventory
            SET location_id = ?, last_updated = ?
            WHERE sku = ?
        """, (new_location, now_str, sku))

        # If SKU doesn't exist in current_inventory, insert it
        if cursor.rowcount == 0:
            cursor.execute("""
                INSERT INTO current_inventory (sku, item_name, location_id, quantity, last_updated)
                VALUES (?, ?, ?, 10, ?)
            """, (sku, f"Item {sku}", new_location, now_str))

        # 3. Synchronize inventory table
        cursor.execute("""
            UPDATE inventory
            SET current_location_id = ?, updated_at = ?
            WHERE sku = ?
        """, (new_location, now_str, sku))

        if cursor.rowcount == 0:
            inv_id = f"INV-{sku}"
            cursor.execute("""
                INSERT INTO inventory (inventory_id, sku, item_name, current_location_id, quantity, status, updated_at)
                VALUES (?, ?, ?, ?, 10, 'In Stock', ?)
            """, (inv_id, sku, f"Item {sku}", new_location, now_str))

        # 4. If failure_id provided, mark resolved in pick_failures
        if failure_id_to_resolve:
            cursor.execute("""
                UPDATE pick_failures
                SET resolved_status = 'resolved', status = 'resolved'
                WHERE failure_id = ?
            """, (failure_id_to_resolve,))

        conn.commit()
        return audit_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def insert_stakeholder_feedback(
    role: str,
    q1_easy: int,
    q2_useful: int,
    q3_reduce_time: int,
    q4_trust: int,
    q5_comments: str,
    db_path: Optional[str] = None
) -> int:
    """Inserts an authentic stakeholder evaluation response."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return execute_query("""
        INSERT INTO stakeholder_feedback (
            role, understandability, probability_usefulness, search_time_reduction, trust, improvements,
            q1_easy, q2_useful, q3_reduce_time, q4_trust, q5_comments, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        role, q1_easy, q2_useful, q3_reduce_time, q4_trust, q5_comments,
        q1_easy, q2_useful, q3_reduce_time, q4_trust, q5_comments, now_str
    ), db_path=db_path)


def reset_database(db_path: Optional[str] = None) -> None:
    """Drops and recreates all tables for a clean test environment."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    tables = [
        "stakeholder_feedback", "audit_history", "current_inventory", "inventory",
        "cycle_counts", "pick_failures", "move_events",
        "put_away_scans", "locations"
    ]
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table};")
    conn.commit()
    conn.close()
    init_db(db_path)


def get_database_summary(db_path: Optional[str] = None) -> Dict[str, int]:
    """Returns row counts for all dark store tables."""
    tables = [
        "locations", "inventory", "current_inventory",
        "put_away_scans", "move_events", "pick_failures",
        "cycle_counts", "audit_history", "stakeholder_feedback"
    ]
    summary = {}
    for tbl in tables:
        try:
            res = fetch_one(f"SELECT COUNT(*) as count FROM {tbl};", db_path=db_path)
            summary[tbl] = res["count"] if res else 0
        except Exception:
            summary[tbl] = 0
    return summary


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DEFAULT_DB_PATH)
    print("Table counts:", get_database_summary())
