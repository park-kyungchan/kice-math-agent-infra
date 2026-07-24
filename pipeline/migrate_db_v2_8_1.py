# -*- coding: utf-8 -*-
"""
Migration v2.8.1 — Governance Hardening (idempotent)
====================================================
1. Recreate `question_item` with:
   - CHECK constraint enumerating the 8 legal review states (P0-1/P0-3)
   - `review_version` INTEGER for optimistic locking (P1-6)
   - json_valid CHECK on review_history_json (column retained but DEPRECATED;
     the append-only audit SSoT is `teacher_review_event`)
2. Create `teacher_review_event` (append-only audit log, P1-6).
3. Create `claim_provenance` (claim-level provenance, P0-4).
4. Timestamped content-addressed backup under storage/backups/ (P1-5).

Safe to run multiple times: each phase checks current schema first.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
STORAGE_DIR = os.path.join(BASE_DIR, 'storage')
DEFAULT_DB_PATH = os.path.join(STORAGE_DIR, 'parsed_dataset.db')
BACKUP_DIR = os.path.join(STORAGE_DIR, 'backups')

REVIEW_STATE_CHECK = (
    "CHECK (review_status IN ("
    "'AUTO_ANALYSIS_COMPLETED','REVIEW_REQUIRED','TEACHER_ASSIGNED',"
    "'TEACHER_APPROVED','REVISION_REQUESTED','TEACHER_REVISED',"
    "'REJECTED','VERIFIED'))"
)

QUESTION_ITEM_DDL = f"""
CREATE TABLE question_item_new (
    item_id TEXT PRIMARY KEY,
    exam_id TEXT REFERENCES exam_event(exam_id),
    track TEXT NOT NULL,
    item_number INTEGER NOT NULL,
    score INTEGER NOT NULL,
    latex_content TEXT NOT NULL,
    asset_image_url TEXT,
    rect_json TEXT,
    answer INTEGER DEFAULT 0,
    correct_rate REAL,
    review_status TEXT NOT NULL DEFAULT 'AUTO_ANALYSIS_COMPLETED' {REVIEW_STATE_CHECK},
    reviewer_id TEXT,
    review_history_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(review_history_json)),
    review_version INTEGER NOT NULL DEFAULT 0
);
"""

TEACHER_REVIEW_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS teacher_review_event (
    event_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES question_item(item_id),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('TEACHER','SYSTEM','AGENT')),
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason_code TEXT,
    notes TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_json)),
    item_version INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

TEACHER_REVIEW_EVENT_NO_UPDATE_TRIGGER_DDL = """
CREATE TRIGGER IF NOT EXISTS teacher_review_event_no_update
BEFORE UPDATE ON teacher_review_event
BEGIN
    SELECT RAISE(ABORT, 'teacher_review_event is append-only: UPDATE forbidden');
END;
"""

TEACHER_REVIEW_EVENT_NO_DELETE_TRIGGER_DDL = """
CREATE TRIGGER IF NOT EXISTS teacher_review_event_no_delete
BEFORE DELETE ON teacher_review_event
BEGIN
    SELECT RAISE(ABORT, 'teacher_review_event is append-only: DELETE forbidden');
END;
"""

CLAIM_PROVENANCE_DDL = """
CREATE TABLE IF NOT EXISTS claim_provenance (
    claim_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES question_item(item_id),
    axis TEXT NOT NULL CHECK (axis IN ('Axis_1','Axis_2','Axis_3','Axis_4','Axis_5','Axis_6','Axis_7','Axis_8')),
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
);
"""

INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_question_item_exam ON question_item(exam_id);",
    "CREATE INDEX IF NOT EXISTS idx_question_item_track ON question_item(track, item_number);",
    "CREATE INDEX IF NOT EXISTS idx_question_item_review_status ON question_item(review_status);",
    "CREATE INDEX IF NOT EXISTS idx_review_event_item ON teacher_review_event(item_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_claim_provenance_item ON claim_provenance(item_id, axis);",
)


def create_physical_backup(db_path: str) -> str:
    """Backups live NEXT TO the target DB (backups/ sibling dir), so migrating
    a copy (e.g. under /tmp or in tests) never writes into the live repo."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)) or '.', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    with open(db_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:8]
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    base = os.path.splitext(os.path.basename(db_path))[0]
    backup_path = os.path.join(backup_dir, f'{base}_pre_v2.8.1_{ts}_{digest}.db')
    shutil.copy2(db_path, backup_path)
    print(f"[Phase 0] Backup created: {backup_path}")
    return backup_path


def _question_item_needs_rebuild(cur) -> bool:
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='question_item'")
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("question_item table not found — run migrate_db_8axis.py first")
    ddl = row[0] or ''
    return ('review_version' not in ddl) or ('review_status IN' not in ddl.replace('\n', ' '))


def run_migration(db_path: str = DEFAULT_DB_PATH, backup: bool = True) -> dict:
    if backup:
        create_physical_backup(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    result = {"rebuilt_question_item": False, "created_tables": [], "row_counts": {}}

    cur.execute("SELECT COUNT(*) FROM question_item")
    rows_before = cur.fetchone()[0]

    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("BEGIN TRANSACTION;")

        # Phase 1: rebuild question_item with CHECK + review_version
        if _question_item_needs_rebuild(cur):
            cur.execute("PRAGMA table_info(question_item);")
            existing_cols = [r[1] for r in cur.fetchall()]
            cur.execute(QUESTION_ITEM_DDL)
            common = [c for c in (
                'item_id', 'exam_id', 'track', 'item_number', 'score',
                'latex_content', 'asset_image_url', 'rect_json', 'answer',
                'correct_rate', 'review_status', 'reviewer_id', 'review_history_json',
            ) if c in existing_cols]
            col_list = ', '.join(common)
            cur.execute(
                f"INSERT INTO question_item_new ({col_list}) SELECT {col_list} FROM question_item;"
            )
            cur.execute("DROP TABLE question_item;")
            cur.execute("ALTER TABLE question_item_new RENAME TO question_item;")
            result["rebuilt_question_item"] = True
            print("  - question_item rebuilt with review_status CHECK + review_version")
        else:
            print("  - question_item already hardened (CHECK + review_version present)")

        # Phase 2/3: append-only event log + claim provenance
        for name, ddl in (("teacher_review_event", TEACHER_REVIEW_EVENT_DDL),
                          ("claim_provenance", CLAIM_PROVENANCE_DDL)):
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
            if cur.fetchone() is None:
                cur.execute(ddl)
                result["created_tables"].append(name)
                print(f"  - Created table {name}")
            else:
                print(f"  - Table {name} already exists")

        # P1-1 fix: append-only triggers (idempotent; also (re)created lazily
        # by review_state.ensure_event_schema() on first use — created here
        # too so a freshly migrated DB is immutable-audit-safe even before
        # any fetch_cli.py --review-* command has run).
        cur.execute(TEACHER_REVIEW_EVENT_NO_UPDATE_TRIGGER_DDL)
        cur.execute(TEACHER_REVIEW_EVENT_NO_DELETE_TRIGGER_DDL)

        for ddl in INDEX_DDL:
            cur.execute(ddl)

        conn.commit()
        print("  - Migration transaction COMMITTED.")
    except Exception as e:
        conn.rollback()
        print(f"  - [ERROR] Migration failed, ROLLED BACK: {e}")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")

    # Verification gate (never trust the implementer's own transaction)
    cur.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    cur.execute("PRAGMA integrity_check;")
    integrity = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM question_item")
    rows_after = cur.fetchone()[0]
    conn.close()

    result["row_counts"] = {"before": rows_before, "after": rows_after}
    if fk_errors or integrity != 'ok' or rows_before != rows_after:
        raise RuntimeError(
            f"Post-migration verification FAILED: fk_errors={len(fk_errors)}, "
            f"integrity={integrity}, rows {rows_before}->{rows_after}"
        )
    print(f"[Complete] integrity=ok, fk_errors=0, question_item rows preserved: {rows_after}")
    return result


if __name__ == '__main__':
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    run_migration(db)
