# -*- coding: utf-8 -*-
"""
Tests for pipeline/migrate_db_outcome_observation.py (Agent I3), which
implements Agent I1's schema recommendation (scratch/staging/I1/REPORT.txt
sec.3) for storing per-item outcome estimates with provenance instead of
collapsing them into `question_item.correct_rate REAL`.

Never touches the real, read-only storage/parsed_dataset.db directly --
TestRealCorpusMigration is the one class that reads it, always via a
`cp`'d temp copy, matching the pattern in tests/test_migrate_axis_agnostic.py.

Covers:
  - table creation is idempotent (safe to run twice)
  - loading the 17 staged I1 values is idempotent (rerun inserts 0 new rows)
  - multiple disagreeing sources CAN coexist for the same item_id (the
    entire point of the fact-table design -- I1's finding that EBSi/
    Megastudy/이투스 disagree by several points must not be collapsed)
  - question_item (1,350) and analysis_derivation (10,800) row counts are
    untouched by this migration
  - source_type CHECK constraint rejects a value outside OFFICIAL/ESTIMATED
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline import migrate_db_outcome_observation as mig
from pipeline import migrate_db_axis_agnostic as axis_mig

REAL_DB = os.path.join(BASE_DIR, 'storage', 'parsed_dataset.db')
REAL_OUTCOME_JSON = os.path.join(BASE_DIR, 'scratch', 'staging', 'I1', 'outcome_data.json')


def _build_fixture_db_with_outcome_data(db_path, outcome_json_path, n_items=5):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE question_item (
            item_id TEXT PRIMARY KEY,
            exam_id TEXT NOT NULL,
            track TEXT NOT NULL,
            item_number INTEGER NOT NULL,
            score INTEGER NOT NULL,
            latex_content TEXT NOT NULL,
            asset_image_url TEXT,
            rect_json TEXT,
            answer INTEGER DEFAULT 0,
            correct_rate REAL,
            review_status TEXT DEFAULT 'AUTO_ANALYSIS_COMPLETED',
            reviewer_id TEXT,
            review_history_json TEXT DEFAULT '[]',
            review_version INTEGER NOT NULL DEFAULT 1,
            canonical_answer_json TEXT
        )
    """)
    item_ids = []
    for i in range(1, n_items + 1):
        item_id = f'FIX_{i:03d}'
        item_ids.append(item_id)
        conn.execute(
            'INSERT INTO question_item (item_id, exam_id, track, item_number, score, latex_content) '
            'VALUES (?,?,?,?,?,?)',
            (item_id, 'EXAM_FIX', 'MATH', i, 2, f'{i}. stem'),
        )
    conn.commit()
    conn.close()

    outcome_data = {
        "_meta": {"generated_by": "test fixture", "n_items_covered": 2},
        item_ids[0]: {
            "correct_rate": 14.5, "source": "FixtureSourceA", "source_type": "ESTIMATED",
            "url": "https://example.com/a", "retrieved_at": "2026-07-25", "distractor_distribution": None,
            "note": "fixture row A",
        },
        item_ids[1]: {
            "correct_rate": 7.0, "source": "FixtureSourceB", "source_type": "ESTIMATED",
            "url": "https://example.com/b", "retrieved_at": "2026-07-25", "distractor_distribution": None,
            "note": "fixture row B",
        },
    }
    with open(outcome_json_path, 'w', encoding='utf-8') as f:
        json.dump(outcome_data, f, ensure_ascii=False)
    return item_ids


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix='outcome_observation_fixture_')
        self.db_path = os.path.join(self._tmpdir, 'fixture.db')
        self.outcome_json_path = os.path.join(self._tmpdir, 'outcome_data.json')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestTableCreation(TempDbTestCase):
    def setUp(self):
        super().setUp()
        _build_fixture_db_with_outcome_data(self.db_path, self.outcome_json_path, n_items=5)

    def test_table_created(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        obj_type = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='outcome_observation'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(obj_type, 'table')

    def test_running_twice_is_idempotent_no_op_for_table_creation(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        mig.run_migration(self.db_path, self.outcome_json_path)  # must not raise
        conn = sqlite3.connect(self.db_path)
        obj_type = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='outcome_observation'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(obj_type, 'table')

    def test_source_type_check_constraint_rejects_invalid_value(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO question_item (item_id, exam_id, track, item_number, score, latex_content) "
                     "VALUES ('FIX_099','EXAM_FIX','MATH',99,2,'stem')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO outcome_observation (item_id, source_name, source_type, retrieved_at) "
                "VALUES ('FIX_099', 'BadSource', 'RUMOR', '2026-07-26')"
            )
        conn.close()

    def test_foreign_key_check_clean_after_migration(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA foreign_keys = ON;')
        fk_errors = conn.execute('PRAGMA foreign_key_check;').fetchall()
        conn.close()
        self.assertEqual(fk_errors, [])


class TestDataLoad(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.item_ids = _build_fixture_db_with_outcome_data(self.db_path, self.outcome_json_path, n_items=5)

    def test_loads_exactly_the_staged_rows(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        count = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_source_type_and_correct_rate_preserved(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT correct_rate, source_name, source_type FROM outcome_observation WHERE item_id=?",
            (self.item_ids[0],),
        ).fetchone()
        conn.close()
        self.assertEqual(row, (14.5, 'FixtureSourceA', 'ESTIMATED'))

    def test_rerun_does_not_duplicate_rows(self):
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        count_1 = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
        conn.close()

        mig.run_migration(self.db_path, self.outcome_json_path)  # second run
        conn = sqlite3.connect(self.db_path)
        count_2 = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
        conn.close()

        self.assertEqual(count_1, 2)
        self.assertEqual(count_1, count_2)

    def test_multiple_disagreeing_sources_coexist_for_same_item(self):
        """The entire point of the fact-table design: a second, DIFFERENT
        source for the SAME item_id must be insertable alongside the
        first, not overwrite or collide with it."""
        mig.run_migration(self.db_path, self.outcome_json_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO outcome_observation
               (item_id, correct_rate, source_name, source_type, source_url, retrieved_at, respondent_basis)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.item_ids[0], 22.0, 'DisagreeingSourceC', 'ESTIMATED',
             'https://example.com/c', '2026-07-26', 'a different self-selected pool'),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT correct_rate, source_name FROM outcome_observation WHERE item_id=? ORDER BY correct_rate",
            (self.item_ids[0],),
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[1] for r in rows}, {'FixtureSourceA', 'DisagreeingSourceC'})

    def test_row_counts_of_question_item_untouched(self):
        conn = sqlite3.connect(self.db_path)
        before = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
        conn.close()

        mig.run_migration(self.db_path, self.outcome_json_path)

        conn = sqlite3.connect(self.db_path)
        after = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
        conn.close()
        self.assertEqual(before, after)

    def test_missing_outcome_json_creates_empty_table_without_error(self):
        missing_path = os.path.join(self._tmpdir, 'does_not_exist.json')
        mig.run_migration(self.db_path, missing_path)  # must not raise
        conn = sqlite3.connect(self.db_path)
        count = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)


class TestBackupCreation(TempDbTestCase):
    def setUp(self):
        super().setUp()
        _build_fixture_db_with_outcome_data(self.db_path, self.outcome_json_path, n_items=2)

    def test_create_physical_backup_writes_a_distinct_file(self):
        backup_dir = os.path.join(self._tmpdir, 'backups')
        orig_backup_dir = mig.BACKUP_DIR
        mig.BACKUP_DIR = backup_dir
        try:
            backup_path = mig.create_physical_backup(self.db_path)
            self.assertTrue(os.path.exists(backup_path))
            self.assertNotEqual(backup_path, self.db_path)
            with open(backup_path, 'rb') as f:
                backup_bytes = f.read()
            with open(self.db_path, 'rb') as f:
                orig_bytes = f.read()
            self.assertEqual(backup_bytes, orig_bytes)
        finally:
            mig.BACKUP_DIR = orig_backup_dir

    def test_backup_missing_db_raises(self):
        with self.assertRaises(FileNotFoundError):
            mig.create_physical_backup(os.path.join(self._tmpdir, 'does_not_exist.db'))


@unittest.skipUnless(os.path.exists(REAL_DB) and os.path.exists(REAL_OUTCOME_JSON),
                      'real storage/parsed_dataset.db or I1 outcome_data.json not present')
class TestRealCorpusMigration(unittest.TestCase):
    """Runs against a `cp`'d copy of the REAL database with the REAL 17
    staged I1 values -- never opens storage/parsed_dataset.db for writing."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='outcome_observation_realcopy_')
        cls.copy_path = os.path.join(cls._tmpdir, 'real_copy.db')
        shutil.copy2(REAL_DB, cls.copy_path)
        # Apply I2's axis-agnostic migration first so analysis_derivation
        # exists on this copy exactly as it does on the (already-migrated,
        # per Agent I2) intended target -- this test proves I3's migration
        # coexists cleanly with I2's, not just in isolation.
        axis_mig.run_migration(cls.copy_path)
        mig.run_migration(cls.copy_path, REAL_OUTCOME_JSON)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_question_item_row_count_preserved(self):
        conn = sqlite3.connect(self.copy_path)
        count = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
        conn.close()
        self.assertEqual(count, 1350)

    def test_analysis_derivation_row_count_preserved(self):
        conn = sqlite3.connect(self.copy_path)
        count = conn.execute('SELECT COUNT(*) FROM analysis_derivation').fetchone()[0]
        conn.close()
        self.assertEqual(count, 1350 * 8)

    def test_seventeen_outcome_rows_loaded_all_estimated(self):
        conn = sqlite3.connect(self.copy_path)
        count = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
        by_type = dict(conn.execute(
            'SELECT source_type, COUNT(*) FROM outcome_observation GROUP BY source_type'
        ).fetchall())
        conn.close()
        self.assertEqual(count, 17)
        self.assertEqual(by_type, {'ESTIMATED': 17})

    def test_known_killer_item_value_present(self):
        """Cross-check against a value directly readable in I1's REPORT.txt
        sec.2: 202311_MATH_DIF_22 correct_rate 1.4%, EBSi-attributed."""
        conn = sqlite3.connect(self.copy_path)
        row = conn.execute(
            "SELECT correct_rate, source_type FROM outcome_observation WHERE item_id='202311_MATH_DIF_22'"
        ).fetchone()
        conn.close()
        self.assertEqual(row, (1.4, 'ESTIMATED'))

    def test_rerun_idempotent_on_real_copy(self):
        mig.run_migration(self.copy_path, REAL_OUTCOME_JSON)  # rerun
        conn = sqlite3.connect(self.copy_path)
        count = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
        conn.close()
        self.assertEqual(count, 17)


if __name__ == '__main__':
    unittest.main()
