# -*- coding: utf-8 -*-
"""Relax claim_provenance.axis from a closed 8-value enum to a format check.

WHY
---
`claim_provenance.axis` carried `CHECK (axis IN ('Axis_1'..'Axis_8'))`, which made it
impossible to record provenance for any axis outside the legacy taxonomy -- including the
`ce.*` conclusion-encoding family. That closed enum also contradicted the storage doctrine
stated in pipeline/query_engine/axis_registry.py: `analysis_derivation` is deliberately
open-world (a new axis needs only a new axis_key string, no DDL change) and a registry entry
is governance metadata, never a write-time gate. Provenance was the one place that gate had
leaked into the schema.

WHAT REPLACES IT
----------------
A FORMAT check rather than a membership check:

    axis GLOB 'Axis_[1-8]'                            -- the legacy contract, unchanged
    OR axis GLOB '[a-z][a-z0-9_]*.[a-z][a-z0-9_]*'    -- <family>.<name>, e.g. ce.segmentation

This keeps the table open-world for any future family while still rejecting empty strings and
unstructured garbage. Membership questions ("is this axis registered?") stay where the doctrine
puts them: axis_registry.is_registered(), used by governance tooling, never by the writer.

ENVIRONMENT NOTE -- WHY THIS SCRIPT STAGES THROUGH A LOCAL TEMP FILE
-------------------------------------------------------------------
This repository is routinely mounted over a network/virtual filesystem that does NOT support the
page-level writes and journal locking SQLite needs. Running a table rebuild directly against a
mounted database fails at COMMIT with `disk I/O error`, and leaves a hot journal beside the file
that the mount then cannot roll back either -- the database becomes unopenable in place, even
read-only, until the file is copied somewhere that supports real writes.

Whole-file copies to and from the mount are reliable; only SQLite's incremental writes are not.
So this script does all SQLite work on a copy in the system temp directory and copies the finished
file back. Never point a SQLite writer directly at a mounted database in this project.

SAFETY
------
SQLite cannot ALTER a CHECK constraint, so the table is rebuilt. The table is copied column for
column, its explicit index is recreated, and foreign keys are verified before commit. A
timestamped backup of the database is written to storage/backups/ first. The script is
idempotent: re-running it on an already-migrated database is a no-op.

ROLLBACK
--------
Restore the backup this script writes, or re-run the rebuild with the original CHECK text.
No row is deleted or modified by this migration.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

DB_DEFAULT = "storage/parsed_dataset.db"
BACKUP_DIR = "storage/backups"
TABLE = "claim_provenance"

NEW_TABLE_SQL = """
CREATE TABLE claim_provenance_ce_new (
    claim_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES question_item(item_id),
    axis TEXT NOT NULL CHECK (
        axis GLOB 'Axis_[1-8]'
        OR axis GLOB '[a-z][a-z0-9_]*.[a-z][a-z0-9_]*'
    ),
    json_pointer TEXT NOT NULL,
    statement TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (claim_type IN ('FACT','INFERENCE','ESTIMATE','OPINION')),
    source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_refs_json)),
    derived_by_json TEXT NOT NULL CHECK (json_valid(derived_by_json)),
    confidence_score REAL,
    counter_evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(counter_evidence_json)),
    human_review_status TEXT NOT NULL DEFAULT 'UNREVIEWED'
        CHECK (human_review_status IN ('UNREVIEWED','REVIEW_REQUIRED','HUMAN_VERIFIED','HUMAN_REJECTED')),
    human_review_event_id TEXT REFERENCES teacher_review_event(event_id),
    created_at TEXT NOT NULL
)
"""

COLUMNS = (
    "claim_id, item_id, axis, json_pointer, statement, claim_type, source_refs_json, "
    "derived_by_json, confidence_score, counter_evidence_json, human_review_status, "
    "human_review_event_id, created_at"
)


def current_ddl(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
    ).fetchone()
    return row[0] if row else None


def already_migrated(ddl):
    return ddl is not None and "GLOB" in ddl


def backup(db_path):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"parsed_dataset.pre-ce-provenance.{stamp}.db")
    shutil.copy2(db_path, dest)
    return dest


def migrate(db_path, dry_run=False):
    conn = sqlite3.connect(db_path)
    ddl = current_ddl(conn)
    if ddl is None:
        print(f"FAIL: table {TABLE} not found in {db_path}")
        return 1
    if already_migrated(ddl):
        print("no-op: claim_provenance.axis already carries the format check")
        return 0

    before = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    print(f"rows before: {before}")
    if dry_run:
        print("dry run: no changes written")
        return 0

    dest = backup(db_path)
    print(f"backup: {dest}")
    conn.close()

    # Stage through the local filesystem: see ENVIRONMENT NOTE above.
    staging = os.path.join(tempfile.mkdtemp(prefix="ce_provenance_"), "staged.db")
    shutil.copy2(db_path, staging)
    journal = db_path + "-journal"
    if os.path.exists(journal) and os.path.getsize(journal) > 0:
        shutil.copy2(journal, staging + "-journal")
    print(f"staging: {staging}")
    conn = sqlite3.connect(staging)

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(NEW_TABLE_SQL)
        conn.execute(
            f"INSERT INTO claim_provenance_ce_new ({COLUMNS}) SELECT {COLUMNS} FROM {TABLE}"
        )
        conn.execute(f"DROP TABLE {TABLE}")
        conn.execute(f"ALTER TABLE claim_provenance_ce_new RENAME TO {TABLE}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_claim_provenance_item "
            f"ON {TABLE}(item_id)"
        )
        after = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        if after != before:
            raise RuntimeError(f"row count changed: {before} -> {after}")
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise RuntimeError(f"foreign key violations after rebuild: {fk}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        conn.execute("PRAGMA foreign_keys=ON")
        raise
    conn.execute("PRAGMA foreign_keys=ON")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"integrity_check failed on staged database: {integrity}")
    conn.close()

    shutil.copy2(staging, db_path)
    if os.path.exists(journal):
        # The mount may forbid unlink; a zero-length journal is not a hot journal.
        with open(journal, "wb"):
            pass
    print(f"rows after: {before} (preserved)")
    print("migrated: claim_provenance.axis now accepts Axis_1..Axis_8 and <family>.<name>")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return migrate(args.db, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
