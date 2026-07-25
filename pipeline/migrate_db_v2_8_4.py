# -*- coding: utf-8 -*-
"""
Migration v2.8.4 — Adversarial Write Boundary & Audit Authenticity (idempotent)
================================================================================
1. Create content-addressed backup under storage/backups/.
2. Add immutable cryptographic audit columns to `teacher_review_event`:
   - principal_id TEXT
   - principal_type TEXT
   - request_id TEXT
   - prev_event_hash TEXT
   - event_hash TEXT
   - signature_key_id TEXT DEFAULT 'LEGACY'
   - event_hmac TEXT DEFAULT 'LEGACY_UNSIGNED'
3. Backfill existing legacy events with signature_key_id='LEGACY', event_hmac='LEGACY_UNSIGNED'.
4. Run foreign_key_check and integrity_check.

Safe to run multiple times: checks column existence before altering schema.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

STORAGE_DIR = os.path.join(BASE_DIR, 'storage')
DEFAULT_DB_PATH = os.path.join(STORAGE_DIR, 'parsed_dataset.db')
BACKUP_DIR = os.path.join(STORAGE_DIR, 'backups')


class MigrationError(Exception):
    pass


def make_backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(db_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:16]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"parsed_dataset_v2_8_4_{timestamp}_{digest}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    shutil.copy2(db_path, backup_path)
    print(f"  - Backup created: {backup_path}")
    return backup_path


def get_existing_columns(conn: sqlite3.Connection, table: str) -> set:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def add_audit_columns(conn: sqlite3.Connection):
    existing = get_existing_columns(conn, "teacher_review_event")
    new_cols = [
        ("principal_id", "TEXT"),
        ("principal_type", "TEXT"),
        ("request_id", "TEXT"),
        ("prev_event_hash", "TEXT"),
        ("event_hash", "TEXT"),
        ("signature_key_id", "TEXT DEFAULT 'LEGACY'"),
        ("event_hmac", "TEXT DEFAULT 'LEGACY_UNSIGNED'"),
    ]
    added = 0
    for col_name, col_def in new_cols:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE teacher_review_event ADD COLUMN {col_name} {col_def}")
            added += 1
    
    # Backfill legacy rows
    conn.execute("""UPDATE teacher_review_event
                    SET signature_key_id = 'LEGACY', event_hmac = 'LEGACY_UNSIGNED'
                    WHERE event_hmac IS NULL OR event_hmac = ''""")
    print(f"  - Added {added} audit columns to teacher_review_event and backfilled legacy rows.")


def migrate(db_path: str = DEFAULT_DB_PATH) -> bool:
    print(f"=== Starting Migration v2.8.4 for: {db_path} ===")
    if not os.path.exists(db_path):
        print(f"Error: DB file not found: {db_path}")
        return False

    backup_path = make_backup(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        conn.execute("BEGIN IMMEDIATE;")
        add_audit_columns(conn)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Migration FAILED: {e}")
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
            print(f"  - Restored DB from backup: {backup_path}")
        raise

    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()

    if integrity != 'ok' or fk_errors:
        print(f"Migration check FAILED: integrity={integrity}, fk_errors={fk_errors}")
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
        return False

    print(f"[Complete v2.8.4] integrity={integrity}, fk_errors={len(fk_errors)}")
    return True


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    success = migrate(target)
    sys.exit(0 if success else 1)
