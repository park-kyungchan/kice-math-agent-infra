# -*- coding: utf-8 -*-
"""
Migration v2.9.0 — Semantic Proof & Gate Approval (idempotent)
=============================================================
1. Create content-addressed backup under storage/backups/.
2. Hardens question_item review_status CHECK constraint to include 'SEMANTIC_PROOF_PENDING'.
3. Run foreign_key_check and integrity_check.
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


def make_backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(db_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:16]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"parsed_dataset_v2_9_0_{timestamp}_{digest}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    shutil.copy2(db_path, backup_path)
    print(f"  - Backup created: {backup_path}")
    return backup_path


def migrate(db_path: str = DEFAULT_DB_PATH) -> bool:
    print(f"=== Starting Migration v2.9.0 for: {db_path} ===")
    if not os.path.exists(db_path):
        print(f"Error: DB file not found: {db_path}")
        return False

    backup_path = make_backup(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF;")

    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='question_item'").fetchone()[0]
    if 'SEMANTIC_PROOF_PENDING' in ddl and 'review_history_json' in ddl:
        print("  - question_item already hardened with SEMANTIC_PROOF_PENDING and review_history_json.")
    else:
        conn.execute("BEGIN IMMEDIATE;")
        # Rebuild table with updated CHECK constraint
        conn.execute("""
            CREATE TABLE question_item_v290 (
                item_id TEXT PRIMARY KEY,
                exam_id TEXT NOT NULL REFERENCES exam_event(exam_id),
                track TEXT NOT NULL,
                item_number INTEGER NOT NULL,
                score INTEGER NOT NULL,
                latex_content TEXT NOT NULL,
                asset_image_url TEXT,
                rect_json TEXT,
                answer INTEGER DEFAULT 0,
                correct_rate REAL,
                review_status TEXT DEFAULT 'AUTO_ANALYSIS_COMPLETED' CHECK (
                    review_status IN (
                        'AUTO_ANALYSIS_COMPLETED',
                        'REVIEW_REQUIRED',
                        'TEACHER_ASSIGNED',
                        'TEACHER_APPROVED',
                        'SEMANTIC_PROOF_PENDING',
                        'REVISION_REQUESTED',
                        'TEACHER_REVISED',
                        'REJECTED',
                        'VERIFIED'
                    )
                ),
                reviewer_id TEXT DEFAULT NULL,
                review_history_json TEXT DEFAULT '[]',
                review_version INTEGER NOT NULL DEFAULT 1
            );
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(question_item)").fetchall()]
        hist_expr = "review_history_json" if "review_history_json" in cols else "'[]'"

        conn.execute(f"""
            INSERT INTO question_item_v290 (
                item_id, exam_id, track, item_number, score, latex_content,
                asset_image_url, rect_json, answer, correct_rate, review_status,
                reviewer_id, review_history_json, review_version
            )
            SELECT item_id, exam_id, track, item_number, score, latex_content,
                   asset_image_url, rect_json, answer, correct_rate, review_status,
                   reviewer_id, {hist_expr}, review_version
            FROM question_item;
        """)
        conn.execute("DROP TABLE question_item;")
        conn.execute("ALTER TABLE question_item_v290 RENAME TO question_item;")
        conn.commit()
        print("  - Hardened question_item review_status CHECK constraint with SEMANTIC_PROOF_PENDING.")

    conn.execute("PRAGMA foreign_keys = ON;")

    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()

    if integrity != 'ok' or fk_errors:
        print(f"Migration check FAILED: integrity={integrity}, fk_errors={fk_errors}")
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
        return False

    print(f"[Complete v2.9.0] integrity={integrity}, fk_errors={len(fk_errors)}")
    return True


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    success = migrate(target)
    sys.exit(0 if success else 1)
