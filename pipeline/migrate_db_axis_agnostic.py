# -*- coding: utf-8 -*-
"""
I2: Axis-Agnostic Storage Migration
====================================
Moves the 8 hardcoded `axis_analysis` flat columns
(`axis1_curriculum` .. `axis8_knowledge_graph`) into a generic key-value
table, `analysis_derivation`, so a taxonomy that is currently *under owner
review* stops being hard-committed into DDL. See ROUTING.md "Open, unfixed"
#3 and pipeline/query_engine/axis_registry.py for the full rationale.

What this script does, in order:
  1. Physical, content-addressed backup of the target DB (never overwrites
     a previous backup) -- matches the style of pipeline/migrate_db_8axis.py.
  2. CREATE TABLE IF NOT EXISTS analysis_derivation (idempotent) with a
     UNIQUE (item_id, axis_key, schema_version) constraint and an index on
     axis_key, so an arbitrary NEW axis_key can be inserted later with zero
     DDL change.
  3. Losslessly copies every (item_id, axis_key) cell out of the legacy
     `axis_analysis` table into `analysis_derivation` at schema_version=1 --
     INCLUDING NULLs and the 1,347 single-key placeholder-sentinel rows.
     Those placeholders are NOT dropped: they are the evidence that the
     dataset is incomplete, and scripts/validate_ssot_consistency.py's
     stub-sentinel gate depends on being able to keep detecting them.
  4. Drops the `axis_analysis` base table and replaces it with a
     same-shaped compatibility VIEW over `analysis_derivation`, so every
     existing reader (pipeline/query_engine/selective_fetcher.py,
     pipeline/query_engine/claim_provenance.py, and any ad-hoc
     `SELECT ... FROM axis_analysis`) keeps working completely unmodified
     -- a plain SELECT cannot distinguish a table from a view.

Idempotent: safe to run twice. If `axis_analysis` is already a VIEW (i.e.
this script already ran), step 3/4 are skipped as a no-op; the
`analysis_derivation` table/indexes are always CREATE ... IF NOT EXISTS and
the row-copy loop uses INSERT OR IGNORE against the UNIQUE constraint.

Usage:
    python3 pipeline/migrate_db_axis_agnostic.py [--db PATH]

MISSION CONSTRAINT: never run this directly against the live, mounted
storage/parsed_dataset.db from an agent sandbox (SQLite writes on the
mounted repo fail with `disk I/O error` -- see ROUTING.md §4). Copy the DB
to a local path first:
    cp storage/parsed_dataset.db /tmp/mig.db
    python3 pipeline/migrate_db_axis_agnostic.py --db /tmp/mig.db
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.axis_registry import AXIS_COLUMNS  # noqa: E402

STORAGE_DIR = os.path.join(BASE_DIR, 'storage')
DB_PATH = os.path.join(STORAGE_DIR, 'parsed_dataset.db')
BACKUP_DIR = os.path.join(STORAGE_DIR, 'backups')


def create_physical_backup(db_path=DB_PATH):
    """Timestamped, content-addressed backup -- never overwrites a previous
    backup. Matches pipeline/migrate_db_8axis.py's create_physical_backup()."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")
    import hashlib
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(db_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:8]
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    backup_path = os.path.join(BACKUP_DIR, f'parsed_dataset_pre_axis_agnostic_{ts}_{digest}.db')
    shutil.copy2(db_path, backup_path)
    print(f"[Phase 0] Backup created: {backup_path}")
    return backup_path


def _object_type(conn, name):
    row = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
    return row[0] if row else None


def run_migration(db_path=DB_PATH):
    print(f"[I2] Starting axis-agnostic storage migration on {db_path} ...")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF;")
    cur = conn.cursor()

    axis_analysis_type = _object_type(conn, 'axis_analysis')
    if axis_analysis_type not in ('table', 'view'):
        conn.close()
        raise RuntimeError(
            f"axis_analysis not found (or unexpected object type {axis_analysis_type!r}) "
            f"in {db_path} -- refusing to run against an unrecognized schema."
        )
    already_migrated = axis_analysis_type == 'view'

    try:
        cur.execute("BEGIN TRANSACTION;")

        # 1. analysis_derivation: idempotent create. UNIQUE(item_id, axis_key,
        #    schema_version) is what lets a brand-new axis_key be inserted
        #    later with zero ALTER TABLE; the axis_key index keeps
        #    per-axis scans (e.g. the drift gate's stub-sentinel check) fast.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analysis_derivation (
                derivation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL REFERENCES question_item(item_id) ON DELETE CASCADE,
                axis_key TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                payload TEXT CHECK (payload IS NULL OR json_valid(payload)),
                derived_by TEXT,
                confidence REAL,
                derived_at TEXT NOT NULL,
                UNIQUE (item_id, axis_key, schema_version)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_derivation_axis_key ON analysis_derivation(axis_key);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_derivation_item ON analysis_derivation(item_id);")
        print("  - analysis_derivation table + indexes ready (idempotent).")

        if already_migrated:
            print("  - axis_analysis is already a compatibility VIEW; migration already applied. "
                  "Skipping data copy and view swap (idempotent no-op).")
        else:
            # 2. Copy every (item_id, axis_key) cell losslessly, INCLUDING
            #    NULLs and stub placeholders (do not drop -- see docstring).
            col_list = ', '.join(AXIS_COLUMNS)
            cur.execute(f"SELECT item_id, {col_list}, updated_at FROM axis_analysis")
            legacy_rows = cur.fetchall()
            n_axes = len(AXIS_COLUMNS)
            print(f"  - Migrating {len(legacy_rows)} axis_analysis rows x {n_axes} axes "
                  f"= up to {len(legacy_rows) * n_axes} analysis_derivation rows...")

            n_inserted = 0
            for row in legacy_rows:
                item_id = row[0]
                axis_values = row[1:1 + n_axes]
                updated_at = row[1 + n_axes]
                derived_at = updated_at or datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                for axis_key, payload in zip(AXIS_COLUMNS, axis_values):
                    cur.execute(
                        """INSERT OR IGNORE INTO analysis_derivation
                           (item_id, axis_key, schema_version, payload, derived_by, confidence, derived_at)
                           VALUES (?, ?, 1, ?, 'LEGACY_8AXIS_MIGRATION', NULL, ?)""",
                        (item_id, axis_key, payload, derived_at),
                    )
                    n_inserted += cur.rowcount
            print(f"  - Inserted {n_inserted} analysis_derivation rows "
                  f"(NULL/placeholder cells preserved verbatim).")

            # 3. Swap axis_analysis: DROP the base table (also drops any
            #    indexes defined on it, e.g. idx_axis_analysis_item), CREATE
            #    a same-shaped compatibility VIEW so existing readers never
            #    notice the change. schema_version=1 is pinned explicitly in
            #    each CASE so a future schema_version=2 payload for the same
            #    axis_key can never leak into this legacy-shaped view.
            cur.execute("DROP TABLE axis_analysis;")
            axis_case_columns = ",\n".join(
                f"    MAX(CASE WHEN axis_key = '{col}' AND schema_version = 1 THEN payload END) AS {col}"
                for col in AXIS_COLUMNS
            )
            axis_in_clause = ', '.join(repr(c) for c in AXIS_COLUMNS)
            cur.execute(f"""
                CREATE VIEW axis_analysis AS
                SELECT
                    item_id,
{axis_case_columns},
                    MAX(CASE WHEN schema_version = 1 THEN derived_at END) AS updated_at
                FROM analysis_derivation
                WHERE axis_key IN ({axis_in_clause})
                GROUP BY item_id;
            """)
            print("  - axis_analysis converted to a compatibility VIEW over analysis_derivation.")

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
            pass  # already closed on the error path above
        conn.close()

    # Reindex & verify
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM question_item;")
    q_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM axis_analysis;")
    a_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM analysis_derivation;")
    d_count = cur.fetchone()[0]
    conn.close()

    print(f"[Complete] FK errors: {len(fk_errors)}, question_item rows: {q_count}, "
          f"axis_analysis(view) rows: {a_count}, analysis_derivation rows: {d_count}")
    return q_count, a_count, d_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=DB_PATH, help='Path to the SQLite DB to migrate (default: live storage/parsed_dataset.db)')
    parser.add_argument('--skip-backup', action='store_true', help='Skip the physical backup step (only for throwaway test copies)')
    args = parser.parse_args()

    if not args.skip_backup:
        create_physical_backup(args.db)
    run_migration(args.db)


if __name__ == '__main__':
    main()
