# -*- coding: utf-8 -*-
"""Create the rationale_step table.

The ledger module shipped before its table did, so an analysis run had nowhere to write its
reasoning. This closes that gap.

Staged through the local filesystem for the reason recorded in migrate_db_ce_provenance.py: the
mount this repository is usually opened from supports whole-file copies but not SQLite's
page-level writes or journal locking, and a direct write fails at COMMIT leaving a hot journal
the mount cannot roll back.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.query_engine import rationale_ledger as rl  # noqa: E402

DB_DEFAULT = 'storage/parsed_dataset.db'
BACKUP_DIR = 'storage/backups'


def migrate(db_path, dry_run=False):
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rationale_step'").fetchone()
    conn.close()
    if exists:
        print('no-op: rationale_step already present')
        return 0
    if dry_run:
        print('dry run: would create rationale_step and its two indexes')
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    backup = os.path.join(BACKUP_DIR, f'parsed_dataset.pre-rationale.{stamp}.db')
    shutil.copy2(db_path, backup)
    print(f'backup: {backup}')

    staging = os.path.join(tempfile.mkdtemp(prefix='rationale_'), 'staged.db')
    shutil.copy2(db_path, staging)
    conn = sqlite3.connect(staging)
    rl.ensure_schema(conn)
    conn.commit()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    fk = conn.execute('PRAGMA foreign_key_check').fetchall()
    conn.close()
    if integrity != 'ok' or fk:
        raise RuntimeError(f'staged database unhealthy: integrity={integrity} fk={fk}')

    shutil.copy2(staging, db_path)
    journal = db_path + '-journal'
    if os.path.exists(journal):
        with open(journal, 'wb'):
            pass
    print('migrated: rationale_step created')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB_DEFAULT)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sys.exit(migrate(a.db, a.dry_run))
