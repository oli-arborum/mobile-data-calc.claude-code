"""SQLite database operations for storing extracted data usage entries."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def create_database(db_path: Path) -> None:
    """Create the database and table if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_usage (
            year INTEGER,
            month INTEGER,
            app_name TEXT,
            data_volume_kb REAL
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database ready: %s", db_path)


def insert_entries(
    db_path: Path, entries: list[tuple[int, int, str, float]]
) -> int:
    """
    Insert deduplicated entries into the database.

    Deduplication: exact match on (year, month, app_name, data_volume_kb).
    Returns the number of entries inserted.
    """
    conn = sqlite3.connect(db_path)

    # Load existing entries for dedup
    existing = set(
        conn.execute(
            "SELECT year, month, app_name, data_volume_kb FROM data_usage"
        ).fetchall()
    )

    # Deduplicate within the new batch and against existing data
    seen: set[tuple[int, int, str, float]] = set(existing)
    to_insert: list[tuple[int, int, str, float]] = []
    for entry in entries:
        key = (entry[0], entry[1], entry[2], entry[3])
        if key not in seen:
            to_insert.append(entry)
            seen.add(key)

    if to_insert:
        conn.executemany(
            "INSERT INTO data_usage (year, month, app_name, data_volume_kb) VALUES (?, ?, ?, ?)",
            to_insert,
        )
        conn.commit()

    conn.close()
    logger.info("Inserted %d entries (skipped %d duplicates)", len(to_insert), len(entries) - len(to_insert))
    return len(to_insert)
