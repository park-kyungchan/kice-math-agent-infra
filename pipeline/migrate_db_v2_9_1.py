# -*- coding: utf-8 -*-
"""
Migration v2.9.1 — Canonical Answer Schema & Strict Governance (idempotent)
========================================================================
1. Create content-addressed backup under storage/backups/.
2. Adds canonical_answer_json column to question_item table.
3. Populates canonical_answer_json for existing question items.
4. Runs foreign_key_check and integrity_check.
"""
import hashlib
import json
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


def make_backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(db_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:16]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"parsed_dataset_v2_9_1_{timestamp}_{digest}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    shutil.copy2(db_path, backup_path)
    print(f"  - Backup created: {backup_path}")
    return backup_path


def migrate(db_path: str = DEFAULT_DB_PATH) -> bool:
    print(f"=== Starting Migration v2.9.1 for: {db_path} ===")
    if not os.path.exists(db_path):
        print(f"Error: DB file not found: {db_path}")
        return False

    backup_path = make_backup(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(question_item)").fetchall()]
    if 'canonical_answer_json' in cols:
        print("  - question_item already has canonical_answer_json column.")
    else:
        conn.execute("ALTER TABLE question_item ADD COLUMN canonical_answer_json TEXT;")
        print("  - Added canonical_answer_json column to question_item.")

    # Populate canonical_answer_json for null rows
    rows = conn.execute("SELECT item_id, answer FROM question_item WHERE canonical_answer_json IS NULL").fetchall()
    if rows:
        conn.execute("BEGIN IMMEDIATE;")
        for item_id, ans in rows:
            canonical = {
                "response_type": "SHORT_ANSWER",
                "correct_option_index": None,
                "correct_value": ans,
            }
            conn.execute(
                "UPDATE question_item SET canonical_answer_json = ? WHERE item_id = ?",
                (json.dumps(canonical, ensure_ascii=False), item_id),
            )
        conn.commit()
        print(f"  - Backfilled canonical_answer_json for {len(rows)} items.")

    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()

    if integrity != 'ok' or fk_errors:
        print(f"Migration check FAILED: integrity={integrity}, fk_errors={fk_errors}")
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
        return False

    print(f"[Complete v2.9.1] integrity={integrity}, fk_errors={len(fk_errors)}")
    return True


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    success = migrate(target)
    sys.exit(0 if success else 1)
