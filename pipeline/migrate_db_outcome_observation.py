# -*- coding: utf-8 -*-
"""
I3: Outcome Observation Storage Migration
==========================================
Implements Agent I1's schema recommendation (scratch/staging/I1/REPORT.txt
sec.3): `question_item.correct_rate REAL` cannot represent what actually
exists for this domain -- multiple disagreeing per-item estimates from
different third-party sources, each with its own provenance, coexisting
with "no data" (which must stay distinguishable from "0%", same discipline
already required of canonical_answer_json.correct_value per ROUTING.md).

This migration:
  1. Physical, content-addressed backup of the target DB (same pattern as
     pipeline/migrate_db_axis_agnostic.py's create_physical_backup()).
  2. CREATE TABLE IF NOT EXISTS outcome_observation (idempotent), one row
     per (item_id, source, retrieved_at) observation -- a fact table, not a
     single-value-per-item column. UNIQUE(item_id, source_name, source_url,
     retrieved_at) makes reloading the same source idempotent while still
     allowing multiple DIFFERENT sources to coexist for the same item_id
     (the entire point: EBSi vs Megastudy vs KICE disagreeing is itself
     signal, never collapsed to one number).
  3. Loads the 17 ESTIMATED values Agent I1 staged in
     scratch/staging/I1/outcome_data.json (idempotent: INSERT OR IGNORE
     against the UNIQUE constraint, so running this script twice does not
     duplicate rows).

DEPRECATION NOTE (documented here because docs/Taxonomy_Spec.md is outside
this agent's owned files -- see scratch/staging/I3/REPORT.txt "Limitations"
for the explicit flag to whoever owns docs/**): `question_item.correct_rate`
is DEPRECATED as of this migration. It remains in the DDL (dropping/altering
a column outside this agent's scope and unnecessary -- it is already NULL
for 1,350/1,350 rows, see ROUTING.md data-health table) but no reader should
populate or trust it going forward; use `outcome_observation` instead, filtered
by `source_type` to distinguish OFFICIAL from ESTIMATED.

MISSION CONSTRAINT: never run this directly against the live, mounted
storage/parsed_dataset.db from an agent sandbox (SQLite writes on the
mounted repo fail with `disk I/O error` -- see ROUTING.md sec.4). Copy the DB
to a local path first:
    cp storage/parsed_dataset.db /tmp/eval.db
    python3 pipeline/migrate_db_outcome_observation.py --db /tmp/eval.db
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

STORAGE_DIR = os.path.join(BASE_DIR, 'storage')
DB_PATH = os.path.join(STORAGE_DIR, 'parsed_dataset.db')
BACKUP_DIR = os.path.join(STORAGE_DIR, 'backups')
DEFAULT_OUTCOME_JSON = os.path.join(BASE_DIR, 'scratch', 'staging', 'I1', 'outcome_data.json')


def create_physical_backup(db_path=DB_PATH):
    """Timestamped, content-addressed backup -- never overwrites a previous
    backup. Matches pipeline/migrate_db_axis_agnostic.py's
    create_physical_backup()."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(db_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:8]
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    backup_path = os.path.join(BACKUP_DIR, f'parsed_dataset_pre_outcome_observation_{ts}_{digest}.db')
    shutil.copy2(db_path, backup_path)
    print(f"[Phase 0] Backup created: {backup_path}")
    return backup_path


def _table_exists(conn, name):
    row = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
    return row is not None and row[0] == 'table'


def create_outcome_observation_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outcome_observation (
            observation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id          TEXT NOT NULL REFERENCES question_item(item_id) ON DELETE CASCADE,
            correct_rate     REAL,
            distractor_json  TEXT CHECK (distractor_json IS NULL OR json_valid(distractor_json)),
            source_name      TEXT NOT NULL,
            source_type      TEXT NOT NULL CHECK (source_type IN ('OFFICIAL', 'ESTIMATED')),
            source_url       TEXT,
            retrieved_at     TEXT NOT NULL,
            respondent_basis TEXT,
            UNIQUE (item_id, source_name, source_url, retrieved_at)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome_observation_item ON outcome_observation(item_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome_observation_source_type ON outcome_observation(source_type);")


def load_staged_outcomes(conn, outcome_json_path):
    """Loads Agent I1's 17 ESTIMATED values. Idempotent via INSERT OR IGNORE
    against the UNIQUE constraint above. Returns (n_seen, n_inserted)."""
    if not os.path.exists(outcome_json_path):
        print(f"  - [WARN] {outcome_json_path} not found; skipping data load (table created empty).")
        return 0, 0

    with open(outcome_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    n_seen = 0
    n_inserted = 0
    cur = conn.cursor()
    for item_id, entry in data.items():
        if item_id == '_meta' or not isinstance(entry, dict):
            continue
        n_seen += 1
        distractor = entry.get('distractor_distribution')
        distractor_json = json.dumps(distractor, ensure_ascii=False) if distractor is not None else None
        cur.execute(
            """INSERT OR IGNORE INTO outcome_observation
               (item_id, correct_rate, distractor_json, source_name, source_type,
                source_url, retrieved_at, respondent_basis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                entry.get('correct_rate'),
                distractor_json,
                entry.get('source', 'UNKNOWN'),
                entry.get('source_type', 'ESTIMATED'),
                entry.get('url'),
                entry.get('retrieved_at', datetime.utcnow().strftime('%Y-%m-%d')),
                entry.get('note'),
            ),
        )
        n_inserted += cur.rowcount
    return n_seen, n_inserted


def run_migration(db_path=DB_PATH, outcome_json_path=DEFAULT_OUTCOME_JSON):
    print(f"[I3] Starting outcome_observation migration on {db_path} ...")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF;")

    already_existed = _table_exists(conn, 'outcome_observation')

    try:
        conn.execute("BEGIN TRANSACTION;")
        create_outcome_observation_table(conn)
        print(f"  - outcome_observation table + indexes ready (idempotent; "
              f"{'already existed' if already_existed else 'newly created'}).")

        n_seen, n_inserted = load_staged_outcomes(conn, outcome_json_path)
        print(f"  - Loaded {n_seen} staged outcome rows from {outcome_json_path}; "
              f"{n_inserted} newly inserted (idempotent -- reruns insert 0).")

        conn.commit()
        print("  - Migration transaction COMMITTED successfully.")
    except Exception as e:
        conn.rollback()
        print(f"  - [ERROR] Migration failed, transaction ROLLED BACK: {e}")
        conn.close()
        raise
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
        except sqlite3.ProgrammingError:
            pass
        conn.close()

    # Reindex & verify -- proves question_item / analysis_derivation counts
    # are untouched by this migration (mission verification requirement).
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM question_item;")
    q_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM analysis_derivation;") if _table_exists(conn, 'analysis_derivation') else None
    try:
        cur.execute("SELECT COUNT(*) FROM analysis_derivation;")
        d_count = cur.fetchone()[0]
    except sqlite3.OperationalError:
        d_count = None
    cur.execute("SELECT COUNT(*) FROM outcome_observation;")
    o_count = cur.fetchone()[0]
    cur.execute("SELECT source_type, COUNT(*) FROM outcome_observation GROUP BY source_type;")
    by_type = cur.fetchall()
    conn.close()

    print(f"[Complete] FK errors: {len(fk_errors)}, question_item rows: {q_count}, "
          f"analysis_derivation rows: {d_count}, outcome_observation rows: {o_count}, "
          f"by source_type: {by_type}")
    return q_count, d_count, o_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=DB_PATH, help='Path to the SQLite DB to migrate (default: live storage/parsed_dataset.db)')
    parser.add_argument('--outcomes', default=DEFAULT_OUTCOME_JSON, help='Path to I1 staged outcome_data.json')
    parser.add_argument('--skip-backup', action='store_true', help='Skip the physical backup step (only for throwaway test copies)')
    args = parser.parse_args()

    if not args.skip_backup:
        create_physical_backup(args.db)
    run_migration(args.db, args.outcomes)


if __name__ == '__main__':
    main()
