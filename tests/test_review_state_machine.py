# -*- coding: utf-8 -*-
"""
Acceptance tests for the v2.8.1 Teacher Review State Machine.
Covers the external review's required gate tests:
  test_review_required_enters_queue, test_teacher_approve_removes_from_queue,
  test_invalid_transition_is_rejected, test_revision_request_does_not_claim_revised,
  test_review_history_is_append_only, test_migration_is_idempotent, CLI exit codes,
  optimistic locking / concurrent reviewers.
All tests run on a throwaway copy of a synthetic mini-DB — never the production DB.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from pipeline.migrate_db_v2_8_1 import run_migration
from pipeline.query_engine import review_state as rs
from pipeline.query_engine.selective_fetcher import QuestionFetcher

CLI = os.path.join(BASE_DIR, 'pipeline', 'query_engine', 'fetch_cli.py')


def build_mini_db(path: str) -> None:
    """Synthetic pre-v2.8.1 DB: 2 items, one with axes, one with NULL axes."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE exam_event (
        exam_id TEXT PRIMARY KEY, year INTEGER NOT NULL, month INTEGER NOT NULL,
        track TEXT NOT NULL, is_kice INTEGER NOT NULL)""")
    cur.execute("""CREATE TABLE question_item (
        item_id TEXT PRIMARY KEY, exam_id TEXT REFERENCES exam_event(exam_id),
        track TEXT NOT NULL, item_number INTEGER NOT NULL, score INTEGER NOT NULL,
        latex_content TEXT NOT NULL, asset_image_url TEXT, rect_json TEXT,
        answer INTEGER DEFAULT 0, correct_rate REAL,
        review_status TEXT DEFAULT 'AUTO_ANALYSIS_COMPLETED',
        reviewer_id TEXT DEFAULT NULL, review_history_json TEXT DEFAULT '[]')""")
    cur.execute("""CREATE TABLE axis_analysis (
        item_id TEXT PRIMARY KEY REFERENCES question_item(item_id) ON DELETE CASCADE,
        axis1_curriculum TEXT, axis2_raw_parsing TEXT, axis3_symbolic_modeling TEXT,
        axis4_contextual_tree TEXT, axis5_traps_verification TEXT, axis6_genealogy TEXT,
        axis7_mutation TEXT, axis8_knowledge_graph TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE source_attribution (
        attribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT REFERENCES question_item(item_id),
        source_name TEXT, pdf_path TEXT, png_path TEXT)""")
    cur.execute("INSERT INTO exam_event VALUES ('202606', 2026, 6, 'MATH_DIF', 1)")
    cur.execute(
        "INSERT INTO question_item (item_id, exam_id, track, item_number, score, latex_content) "
        "VALUES ('ITEM_FULL', '202606', 'MATH_DIF', 15, 4, 'f(x)=x^3')"
    )
    cur.execute(
        "INSERT INTO question_item (item_id, exam_id, track, item_number, score, latex_content) "
        "VALUES ('ITEM_NULL_AXES', '202606', 'MATH_DIF', 22, 4, 'g(x)=x^2')"
    )
    axis3 = json.dumps({"review_required": True, "confidence_score": 0.5})
    cur.execute(
        "INSERT INTO axis_analysis (item_id, axis3_symbolic_modeling, axis6_genealogy) "
        "VALUES ('ITEM_FULL', ?, ?)",
        (axis3, json.dumps({"historical_precedents": []})),
    )
    # ITEM_NULL_AXES: row with every axis column NULL
    cur.execute("INSERT INTO axis_analysis (item_id) VALUES ('ITEM_NULL_AXES')")
    conn.commit()
    conn.close()


class ReviewStateMachineTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='review_sm_')
        cls._golden = os.path.join(cls._tmpdir, 'golden.db')
        build_mini_db(cls._golden)
        run_migration(cls._golden, backup=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        self.db = os.path.join(self._tmpdir, f'{self._testMethodName}.db')
        shutil.copy2(self._golden, self.db)
        self.fetcher = QuestionFetcher(db_path=self.db)

    def conn(self):
        return self.fetcher.get_connection()


class TestMigration(ReviewStateMachineTestBase):
    def test_migration_is_idempotent(self):
        conn = self.conn()
        before_schema = {
            r[0]: r[1] for r in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        }
        before_rows = conn.execute("SELECT COUNT(*) FROM question_item").fetchone()[0]
        conn.close()
        run_migration(self.db, backup=False)  # second run
        conn = self.conn()
        after_schema = {
            r[0]: r[1] for r in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        }
        after_rows = conn.execute("SELECT COUNT(*) FROM question_item").fetchone()[0]
        self.assertEqual(before_schema, after_schema)
        self.assertEqual(before_rows, after_rows)

    def test_migrated_schema_has_governance_objects(self):
        conn = self.conn()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn('teacher_review_event', tables)
        self.assertIn('claim_provenance', tables)
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='question_item'").fetchone()[0]
        self.assertIn('review_version', ddl)
        self.assertIn('review_status IN', ddl.replace('\n', ' '))

    def test_db_check_constraint_rejects_garbage_state(self):
        conn = self.conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE question_item SET review_status='GARBAGE' WHERE item_id='ITEM_FULL'")
            conn.commit()


class TestTransitions(ReviewStateMachineTestBase):
    def test_invalid_transition_is_rejected(self):
        conn = self.conn()
        before = conn.execute(
            "SELECT review_status, review_version FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()
        with self.assertRaises(rs.TransitionError):
            rs.transition(conn, 'ITEM_FULL', 'TEACHER_APPROVED', actor_id='t-kim')
        after = conn.execute(
            "SELECT review_status, review_version FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()
        self.assertEqual(tuple(before), tuple(after), "illegal transition must write NOTHING")
        events = rs.get_item_events(conn, 'ITEM_FULL')
        self.assertEqual(events, [], "illegal transition must not append events")

    def test_terminal_state_rejected_has_no_exits(self):
        conn = self.conn()
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        rs.transition(conn, 'ITEM_FULL', 'REJECTED', actor_id='t-kim')
        for target in rs.REVIEW_STATES:
            with self.assertRaises(rs.TransitionError):
                rs.transition(conn, 'ITEM_FULL', target, actor_id='t-kim')

    def test_review_required_enters_queue(self):
        conn = self.conn()
        self.assertEqual(rs.get_review_queue(conn), [])
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        queue = rs.get_review_queue(conn)
        self.assertEqual([q['item_id'] for q in queue], ['ITEM_FULL'])

    def test_teacher_approve_removes_from_queue(self):
        conn = self.conn()
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_ASSIGNED', actor_id='t-kim')
        self.assertIn('ITEM_FULL', [q['item_id'] for q in rs.get_review_queue(conn)])
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_APPROVED', actor_id='t-kim')
        self.assertNotIn('ITEM_FULL', [q['item_id'] for q in rs.get_review_queue(conn)])

    def test_revision_request_does_not_claim_revised(self):
        conn = self.conn()
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_ASSIGNED', actor_id='t-kim')
        rs.transition(conn, 'ITEM_FULL', 'REVISION_REQUESTED', actor_id='t-kim',
                      notes='fix axis3 derivation')
        status = conn.execute(
            "SELECT review_status FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()[0]
        self.assertEqual(status, 'REVISION_REQUESTED')
        self.assertNotEqual(status, 'TEACHER_REVISED')
        # TEACHER_REVISED is reachable only from REVISION_REQUESTED
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_REVISED', actor_id='t-kim',
                      notes='revision applied')
        status = conn.execute(
            "SELECT review_status FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()[0]
        self.assertEqual(status, 'TEACHER_REVISED')

    def test_review_history_is_append_only(self):
        conn = self.conn()
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        first = rs.get_item_events(conn, 'ITEM_FULL')
        self.assertEqual(len(first), 1)
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_ASSIGNED', actor_id='t-kim')
        second = rs.get_item_events(conn, 'ITEM_FULL')
        self.assertEqual(len(second), 2)
        self.assertEqual(first[0], second[0], "earlier events must be immutable")
        self.assertEqual([e['item_version'] for e in second], [1, 2])
        # deprecated JSON snapshot column is no longer written
        hist = conn.execute(
            "SELECT review_history_json FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()[0]
        self.assertEqual(json.loads(hist), [])

    def test_concurrent_reviewer_stale_version_rejected(self):
        conn = self.conn()
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        version_seen = conn.execute(
            "SELECT review_version FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()[0]
        # reviewer A moves the item forward
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_ASSIGNED', actor_id='t-a',
                      expected_version=version_seen)
        # reviewer B still holds the old version -> must fail, no double-write
        with self.assertRaises(rs.ConcurrencyError):
            rs.transition(conn, 'ITEM_FULL', 'REJECTED', actor_id='t-b',
                          expected_version=version_seen)

    def test_empty_actor_id_rejected(self):
        conn = self.conn()
        with self.assertRaises(rs.TransitionError):
            rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='  ',
                          actor_type='SYSTEM')

    def test_unknown_item_raises_not_found(self):
        conn = self.conn()
        with self.assertRaises(rs.ItemNotFoundError):
            rs.transition(conn, 'NOPE', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')

    def test_sync_persists_quality_findings_as_events(self):
        """Quality-Plane 'unverified' computed state must enter the workflow
        ONLY as an explicit, event-recorded REVIEW_REQUIRED transition."""
        result = rs.sync_review_states(self.fetcher)
        self.assertIn('ITEM_FULL', result['moved_to_review_required'],
                      'axis3 review_required=true item must be queued by sync')
        conn = self.conn()
        events = rs.get_item_events(conn, 'ITEM_FULL')
        self.assertEqual(events[-1]['to_status'], 'REVIEW_REQUIRED')
        self.assertEqual(events[-1]['actor_type'], 'SYSTEM')
        self.assertEqual(events[-1]['reason_code'], 'QUALITY_PLANE_UNRESOLVED')
        self.assertIn('ITEM_FULL', [q['item_id'] for q in rs.get_review_queue(conn)])


class TestCliExitCodes(ReviewStateMachineTestBase):
    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, CLI, '--db', self.db, *argv],
            capture_output=True, text=True, cwd=BASE_DIR,
        )

    def test_cli_illegal_transition_exits_3_and_writes_nothing(self):
        res = self.run_cli('--review-approve', '--item', 'ITEM_FULL', '--reviewer', 't-kim')
        self.assertEqual(res.returncode, 3, res.stderr)
        conn = self.conn()
        status = conn.execute(
            "SELECT review_status FROM question_item WHERE item_id='ITEM_FULL'"
        ).fetchone()[0]
        self.assertEqual(status, 'AUTO_ANALYSIS_COMPLETED')

    def test_cli_not_found_exits_4(self):
        res = self.run_cli('--review-approve', '--item', 'NOPE', '--reviewer', 't')
        self.assertEqual(res.returncode, 4, res.stderr)

    def test_cli_usage_error_exits_2(self):
        res = self.run_cli('--review-assign', '--item', 'ITEM_FULL')
        self.assertEqual(res.returncode, 2, res.stderr)

    def test_cli_full_happy_path(self):
        conn = self.conn()
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        conn.close()
        res = self.run_cli('--review-assign', '--item', 'ITEM_FULL', '--reviewer', 't-kim')
        self.assertEqual(res.returncode, 0, res.stderr)
        res = self.run_cli('--review-approve', '--item', 'ITEM_FULL', '--reviewer', 't-kim',
                           '--reason', 'MATHEMATICALLY_VALID')
        self.assertEqual(res.returncode, 0, res.stderr)
        event = json.loads(res.stdout)
        self.assertEqual(event['to_status'], 'TEACHER_APPROVED')
        res = self.run_cli('--review-queue')
        self.assertEqual(res.returncode, 0)
        self.assertEqual(json.loads(res.stdout), [])


if __name__ == '__main__':
    unittest.main()
