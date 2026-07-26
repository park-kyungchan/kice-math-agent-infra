# -*- coding: utf-8 -*-
"""
Tests for pipeline/migrate_db_axis_agnostic.py (I2 axis-agnostic storage
refactor). Never touches the real, read-only storage/parsed_dataset.db --
every test builds or copies a throwaway temp-directory database.

Covers:
  - lossless migration of a synthetic legacy-shaped axis_analysis table
    (mirrors the real DB's shape exactly, including NULL cells) into
    analysis_derivation + a compatibility view;
  - idempotency (running twice is a safe no-op the second time);
  - a brand-new, unregistered axis_key can be inserted and read back with
    zero DDL change (the mission's core storage-layer proof);
  - byte-for-byte equivalence against the REAL live database when copied to
    a temp file and migrated there (this is the one test class that reads
    storage/parsed_dataset.db, and only ever via a `cp`'d temp copy -- it
    never opens the real file for writing).
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

from pipeline import migrate_db_axis_agnostic as mig
from pipeline.query_engine.axis_registry import AXIS_COLUMNS

REAL_DB = os.path.join(BASE_DIR, 'storage', 'parsed_dataset.db')


def _build_legacy_fixture_db(path, n_items=10):
    """A synthetic DB whose schema mirrors the REAL pre-migration DB's
    axis_analysis table exactly (same 8 flat columns + PK + updated_at),
    with a realistic mix of real payloads, stub placeholders, and NULLs --
    the three cell shapes the real corpus actually contains."""
    conn = sqlite3.connect(path)
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
    conn.execute("""
        CREATE TABLE axis_analysis (
            item_id TEXT PRIMARY KEY REFERENCES question_item(item_id) ON DELETE CASCADE,
            axis1_curriculum TEXT,
            axis2_raw_parsing TEXT,
            axis3_symbolic_modeling TEXT,
            axis4_contextual_tree TEXT,
            axis5_traps_verification TEXT,
            axis6_genealogy TEXT,
            axis7_mutation TEXT,
            axis8_knowledge_graph TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX idx_axis_analysis_item ON axis_analysis(item_id);")

    for i in range(1, n_items + 1):
        item_id = f'FIX_{i:03d}'
        conn.execute(
            'INSERT INTO question_item (item_id, exam_id, track, item_number, score, latex_content) '
            'VALUES (?,?,?,?,?,?)',
            (item_id, 'EXAM_FIX', 'MATH', i, 2, f'{i}. stem'),
        )
        # Item 1 is "real" (like 202606_MATH_{DIF,GEO,PRO}_15); the rest get
        # the stub placeholder for axis1/3/5/6 and NULL for axis4/7/8,
        # exactly mirroring the real corpus's two defect shapes.
        if i == 1:
            axis1 = json.dumps({'objective_code': 'OBJ_ANALYZE', 'unit': 'CALC2', 'detail': 'real analysis text'})
            axis3 = json.dumps({'standard_solution': {'steps': ['a', 'b']}, 'concept_id': 'C1'})
            axis4 = json.dumps({'backtrack_log': ['step1', 'step2']})
            axis5 = json.dumps({'distractors': [{'option_number': 2, 'error_code': 'DIST_X'}]})
            axis6 = json.dumps({'precedent_item_id': 'FIX_000', 'relation': 'DIRECT_GENEALOGY'})
            axis7 = json.dumps({'mutation_chain': ['v1', 'v2']})
            axis8 = json.dumps({'degree_centrality': 0.5, 'cluster_id': 'CL1'})
        else:
            axis1 = json.dumps({'objective': 'OBJ_UNDERSTAND'})
            axis3 = json.dumps({'objective': 'OBJ_UNDERSTAND'})
            axis4 = None
            axis5 = json.dumps({'objective': 'OBJ_UNDERSTAND'})
            axis6 = json.dumps({'objective': 'OBJ_UNDERSTAND'})
            axis7 = None
            axis8 = None
        conn.execute(
            'INSERT INTO axis_analysis (item_id, axis1_curriculum, axis2_raw_parsing, '
            'axis3_symbolic_modeling, axis4_contextual_tree, axis5_traps_verification, '
            'axis6_genealogy, axis7_mutation, axis8_knowledge_graph, updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (item_id, axis1, json.dumps({'condition': f'real free text body {i}'}), axis3, axis4, axis5, axis6, axis7, axis8,
             f'2026-07-2{i % 5} 00:00:00'),
        )
    conn.commit()
    conn.close()


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix='migrate_axis_agnostic_fixture_')
        self.db_path = os.path.join(self._tmpdir, 'fixture.db')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestLosslessMigration(TempDbTestCase):
    def setUp(self):
        super().setUp()
        _build_legacy_fixture_db(self.db_path, n_items=10)

    def test_analysis_derivation_created_with_correct_row_count(self):
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        count = conn.execute('SELECT COUNT(*) FROM analysis_derivation').fetchone()[0]
        conn.close()
        self.assertEqual(count, 10 * 8)  # 10 items x 8 axes, including NULL cells

    def test_axis_analysis_becomes_a_view(self):
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        obj_type = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='axis_analysis'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(obj_type, 'view')

    def test_row_counts_preserved(self):
        conn = sqlite3.connect(self.db_path)
        before_q = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
        before_a = conn.execute('SELECT COUNT(*) FROM axis_analysis').fetchone()[0]
        conn.close()

        mig.run_migration(self.db_path)

        conn = sqlite3.connect(self.db_path)
        after_q = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
        after_a = conn.execute('SELECT COUNT(*) FROM axis_analysis').fetchone()[0]
        conn.close()
        self.assertEqual(before_q, after_q)
        self.assertEqual(before_a, after_a)

    def test_placeholder_rows_preserved_verbatim(self):
        """The 9 stub-placeholder items (FIX_002..FIX_010) must survive the
        migration byte-for-byte -- they are the evidence the drift gate's
        stub-sentinel check depends on."""
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT axis1_curriculum FROM axis_analysis WHERE item_id = 'FIX_002'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], json.dumps({'objective': 'OBJ_UNDERSTAND'}))

    def test_null_cells_preserved_as_null(self):
        """axis4/7/8-shaped NULL cells (mirrors the real corpus's
        axis4_contextual_tree / axis7_mutation / axis8_knowledge_graph,
        which are NULL rather than stub JSON for 1,347/1,350 items) must
        stay NULL, not become empty string or 'null'."""
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT axis4_contextual_tree FROM axis_analysis WHERE item_id = 'FIX_002'"
        ).fetchone()
        conn.close()
        self.assertIsNone(row[0])

    def test_real_row_byte_identical_across_all_8_axes(self):
        conn_before = sqlite3.connect(self.db_path)
        cols = ', '.join(AXIS_COLUMNS)
        before = conn_before.execute(f'SELECT {cols} FROM axis_analysis WHERE item_id = ?', ('FIX_001',)).fetchone()
        conn_before.close()

        mig.run_migration(self.db_path)

        conn_after = sqlite3.connect(self.db_path)
        after = conn_after.execute(f'SELECT {cols} FROM axis_analysis WHERE item_id = ?', ('FIX_001',)).fetchone()
        conn_after.close()
        self.assertEqual(before, after)

    def test_updated_at_preserved_through_view(self):
        conn_before = sqlite3.connect(self.db_path)
        before = conn_before.execute(
            "SELECT updated_at FROM axis_analysis WHERE item_id = 'FIX_003'"
        ).fetchone()[0]
        conn_before.close()

        mig.run_migration(self.db_path)

        conn_after = sqlite3.connect(self.db_path)
        after = conn_after.execute(
            "SELECT updated_at FROM axis_analysis WHERE item_id = 'FIX_003'"
        ).fetchone()[0]
        conn_after.close()
        self.assertEqual(before, after)

    def test_foreign_key_check_clean_after_migration(self):
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA foreign_keys = ON;')
        fk_errors = conn.execute('PRAGMA foreign_key_check;').fetchall()
        conn.close()
        self.assertEqual(fk_errors, [])

    def test_analysis_derivation_has_unique_constraint(self):
        """UNIQUE(item_id, axis_key, schema_version) must reject a literal
        duplicate -- this is what makes re-running the migration (or a
        future analyser re-deriving the same axis at the same
        schema_version) idempotent rather than silently duplicating rows."""
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO analysis_derivation (item_id, axis_key, schema_version, payload, derived_at) "
                "VALUES ('FIX_001', 'axis1_curriculum', 1, '{}', '2026-01-01T00:00:00Z')"
            )
        conn.close()


class TestIdempotency(TempDbTestCase):
    def setUp(self):
        super().setUp()
        _build_legacy_fixture_db(self.db_path, n_items=10)

    def test_running_twice_is_a_safe_noop_second_time(self):
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        count_1 = conn.execute('SELECT COUNT(*) FROM analysis_derivation').fetchone()[0]
        conn.close()

        mig.run_migration(self.db_path)  # second run: must not duplicate or error
        conn = sqlite3.connect(self.db_path)
        count_2 = conn.execute('SELECT COUNT(*) FROM analysis_derivation').fetchone()[0]
        conn.close()

        self.assertEqual(count_1, count_2)

    def test_running_twice_view_still_readable(self):
        mig.run_migration(self.db_path)
        mig.run_migration(self.db_path)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT axis1_curriculum FROM axis_analysis WHERE item_id = 'FIX_001'").fetchone()
        conn.close()
        self.assertIsNotNone(row[0])


class TestNewAxisKeyRequiresNoDDLChange(TempDbTestCase):
    """The mission's core storage-layer proof: an arbitrary new axis_key --
    including one never declared in pipeline/query_engine/axis_registry.py
    -- must be insertable and readable with zero schema change."""

    def setUp(self):
        super().setUp()
        _build_legacy_fixture_db(self.db_path, n_items=3)
        mig.run_migration(self.db_path)

    def test_insert_and_read_back_hypothetical_new_axis(self):
        conn = sqlite3.connect(self.db_path)
        schema_before = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='analysis_derivation'"
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO analysis_derivation (item_id, axis_key, schema_version, payload, derived_by, confidence, derived_at) "
            "VALUES ('FIX_001', 'x_pilot_difficulty', 1, ?, 'AGENT:pilot_v0', 0.5, '2026-07-26T00:00:00Z')",
            (json.dumps({'pilot_score': 0.73}),),
        )
        conn.commit()

        schema_after = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='analysis_derivation'"
        ).fetchone()[0]
        self.assertEqual(schema_before, schema_after, 'inserting a new axis_key must not require a DDL change')

        row = conn.execute(
            "SELECT axis_key, payload, derived_by, confidence FROM analysis_derivation "
            "WHERE item_id = 'FIX_001' AND axis_key = 'x_pilot_difficulty'"
        ).fetchone()
        conn.close()
        self.assertEqual(row, ('x_pilot_difficulty', json.dumps({'pilot_score': 0.73}), 'AGENT:pilot_v0', 0.5))

    def test_new_axis_key_is_unregistered_but_still_writable(self):
        from pipeline.query_engine.axis_registry import is_registered
        self.assertFalse(is_registered('x_pilot_difficulty'))
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO analysis_derivation (item_id, axis_key, schema_version, payload, derived_at) "
            "VALUES ('FIX_002', 'x_pilot_difficulty', 1, '{}', '2026-07-26T00:00:00Z')"
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM analysis_derivation WHERE axis_key = 'x_pilot_difficulty'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_new_axis_key_does_not_appear_in_legacy_compat_view(self):
        """The axis_analysis compatibility view is pinned to the 8 legacy
        axis_key values -- a new axis_key correctly stays invisible to old
        readers until/unless it graduates into the documented taxonomy."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO analysis_derivation (item_id, axis_key, schema_version, payload, derived_at) "
            "VALUES ('FIX_001', 'x_pilot_difficulty', 1, '{}', '2026-07-26T00:00:00Z')"
        )
        conn.commit()
        cols = [r[1] for r in conn.execute('PRAGMA table_info(axis_analysis)').fetchall()]
        conn.close()
        self.assertNotIn('x_pilot_difficulty', cols)


class TestBackupCreation(TempDbTestCase):
    def setUp(self):
        super().setUp()
        _build_legacy_fixture_db(self.db_path, n_items=2)

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


@unittest.skipUnless(os.path.exists(REAL_DB), 'real storage/parsed_dataset.db not present')
class TestEquivalenceAgainstRealDatabaseCopy(unittest.TestCase):
    """The one test class that reads the real live database -- always via a
    `cp`'d temp copy, never opened for writing. Proves the migration is
    lossless against the ACTUAL corpus, not just a synthetic fixture."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='migrate_axis_agnostic_realcopy_')
        cls.copy_path = os.path.join(cls._tmpdir, 'real_copy.db')
        shutil.copy2(REAL_DB, cls.copy_path)
        mig.run_migration(cls.copy_path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_row_counts_match_known_corpus_size(self):
        conn_orig = sqlite3.connect(f'file:{REAL_DB}?mode=ro', uri=True)
        conn_mig = sqlite3.connect(self.copy_path)
        q_orig = conn_orig.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
        a_mig = conn_mig.execute('SELECT COUNT(*) FROM axis_analysis').fetchone()[0]
        d_mig = conn_mig.execute('SELECT COUNT(*) FROM analysis_derivation').fetchone()[0]
        conn_orig.close()
        conn_mig.close()
        self.assertEqual(q_orig, 1350)
        self.assertEqual(a_mig, 1350)
        self.assertEqual(d_mig, 1350 * 8)

    def test_three_real_analyses_byte_identical(self):
        cols = ', '.join(AXIS_COLUMNS)
        conn_orig = sqlite3.connect(f'file:{REAL_DB}?mode=ro', uri=True)
        conn_mig = sqlite3.connect(self.copy_path)
        for item_id in ('202606_MATH_DIF_15', '202606_MATH_GEO_15', '202606_MATH_PRO_15'):
            before = conn_orig.execute(f'SELECT item_id, {cols} FROM axis_analysis WHERE item_id=?', (item_id,)).fetchone()
            after = conn_mig.execute(f'SELECT item_id, {cols} FROM axis_analysis WHERE item_id=?', (item_id,)).fetchone()
            self.assertEqual(before, after, f'{item_id} not byte-identical after migration')
        conn_orig.close()
        conn_mig.close()

    def test_placeholder_rows_still_present_and_still_detectable(self):
        """axis1_curriculum's 1,347 placeholder rows survive migration and
        the drift gate (against analysis_derivation now) still detects
        them."""
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
        import validate_ssot_consistency as v
        errors = []
        v.check_axis_stub_sentinels(errors, self.copy_path)
        axis1_errors = [e for e in errors if 'axis1_curriculum' in e]
        self.assertEqual(len(axis1_errors), 1, errors)
        self.assertIn('3/1350', axis1_errors[0])

    def test_axis2_raw_parsing_not_flagged(self):
        """The most important false-positive control: axis2 is legitimately
        100% real and must never be flagged, pre- or post-migration."""
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
        import validate_ssot_consistency as v
        errors = []
        v.check_axis_stub_sentinels(errors, self.copy_path)
        axis2_errors = [e for e in errors if 'axis2_raw_parsing' in e]
        self.assertEqual(axis2_errors, [])

    def test_selective_fetcher_output_identical_pre_and_post_migration(self):
        from pipeline.query_engine.selective_fetcher import QuestionFetcher
        f_orig = QuestionFetcher(db_path=REAL_DB)
        f_mig = QuestionFetcher(db_path=self.copy_path)
        sample = [
            '202411_MATH_DIF_22', '202606_MATH_DIF_15', '202606_MATH_GEO_15',
            '202606_MATH_PRO_15', '202106_MATH_GEO_22',
        ]
        for item_id in sample:
            self.assertEqual(f_orig.get_question(item_id), f_mig.get_question(item_id), item_id)


if __name__ == '__main__':
    unittest.main()
