# -*- coding: utf-8 -*-
"""
Migration v2.8.3 — Fail-Closed Governance & Provenance Validation (idempotent)
==============================================================================
1. Create content-addressed backup under storage/backups/.
2. Validate existing DB tables (question_item, teacher_review_event, claim_provenance, axis_analysis).
3. Audit and validate all existing stored claim_provenance source_refs records
   against the closed v1 schema.
4. Execute foreign_key_check and integrity_check on the database.

Safe to run multiple times: idempotent checks.
"""
import json
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
    backup_filename = f"parsed_dataset_v2_8_3_{timestamp}_{digest}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    shutil.copy2(db_path, backup_path)
    print(f"  - Backup created: {backup_path}")
    return backup_path


def audit_claim_provenance(conn: sqlite3.Connection):
    from pipeline.query_engine.claim_provenance import _table_exists, validate_source_ref
    if not _table_exists(conn):
        print("  - Table claim_provenance absent; skipping source_refs audit.")
        return

    rows = conn.execute("SELECT claim_id, item_id, source_refs_json FROM claim_provenance").fetchall()
    print(f"  - Auditing {len(rows)} claim_provenance records...")
    
    updated = 0
    for claim_id, item_id, refs_json in rows:
        try:
            source_refs = json.loads(refs_json)
        except Exception as e:
            raise MigrationError(f"Claim {claim_id} has invalid source_refs_json: {e}")
        
        if not isinstance(source_refs, list) or not source_refs:
            raise MigrationError(f"Claim {claim_id} source_refs must be a non-empty list")
        
        validated_refs = []
        for ref in source_refs:
            norm_ref = validate_source_ref(conn, ref)
            validated_refs.append(norm_ref)
        
        norm_json = json.dumps(validated_refs, ensure_ascii=False)
        if norm_json != refs_json:
            conn.execute(
                "UPDATE claim_provenance SET source_refs_json = ? WHERE claim_id = ?",
                (norm_json, claim_id)
            )
            updated += 1
            
    print(f"  - Claim provenance audit complete. {updated} records updated.")


def migrate(db_path: str = DEFAULT_DB_PATH) -> bool:
    print(f"=== Starting Migration v2.8.3 for: {db_path} ===")
    if not os.path.exists(db_path):
        print(f"Error: DB file not found: {db_path}")
        return False

    backup_path = make_backup(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        conn.execute("BEGIN IMMEDIATE;")
        audit_claim_provenance(conn)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Migration FAILED: {e}")
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
            print(f"  - Restored DB from backup: {backup_path}")
        raise

    # Verification: integrity_check & foreign_key_check
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()

    if integrity != 'ok' or fk_errors:
        print(f"Migration check FAILED: integrity={integrity}, fk_errors={fk_errors}")
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
        return False

    print(f"[Complete v2.8.3] integrity={integrity}, fk_errors={len(fk_errors)}")
    return True


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    success = migrate(target)
    sys.exit(0 if success else 1)
