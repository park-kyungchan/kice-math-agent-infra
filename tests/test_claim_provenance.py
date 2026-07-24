# -*- coding: utf-8 -*-
"""
Acceptance tests for claim-level provenance (v2.8.1).
Covers: test_claim_provenance_round_trip, test_missing_axis_remains_missing,
human_verified linkage to teacher review events, and the no-synthesis invariant.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine import claim_provenance as cp
from pipeline.query_engine import review_state as rs
from pipeline.query_engine.selective_fetcher import QuestionFetcher
try:
    from tests.test_review_state_machine import build_mini_db
except ImportError:  # unittest discovery uses tests/ as top-level
    from test_review_state_machine import build_mini_db
from pipeline.migrate_db_v2_8_1 import run_migration


class ClaimProvenanceTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='claim_prov_')
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

    def record_sample_claim(self, conn):
        return cp.record_claim(
            conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
            'ITEM_X is a direct genealogy parent', 'INFERENCE',
            source_refs=[{'source_type': 'ORIGINAL_EXAM_TEXT', 'item_id': 'ITEM_X',
                          'field': 'latex_content'}],
            derived_by={'actor_type': 'AGENT', 'actor_id': 'axis6-genealogy-agent',
                        'model': 'any-vendor-model'},
            confidence_score=0.74,
        )


class TestClaimProvenance(ClaimProvenanceTestBase):
    def test_claim_provenance_round_trip(self):
        conn = self.fetcher.get_connection()
        claim = self.record_sample_claim(conn)
        self.assertTrue(claim['claim_id'].startswith('CLM-'))
        self.fetcher.clear_cache()
        item = self.fetcher.get_question('ITEM_FULL')
        self.assertIn('Axis_6', item['claim_provenance'])
        stored = item['claim_provenance']['Axis_6'][0]
        self.assertEqual(stored['statement'], 'ITEM_X is a direct genealogy parent')
        self.assertEqual(stored['claim_type'], 'INFERENCE')
        self.assertEqual(stored['json_pointer'], '/historical_precedents/0/relation_type')
        self.assertEqual(stored['derived_by']['actor_id'], 'axis6-genealogy-agent')
        self.assertEqual(stored['source_refs'][0]['item_id'], 'ITEM_X')
        # mirrored into the axis dict because Axis_6 analysis exists
        self.assertEqual(len(item['axes']['Axis_6']['provenance']), 1)

    def test_missing_axis_remains_missing(self):
        """A NULL axis column must NOT be synthesized into an empty dict —
        absence of analysis must be observable (P0-4)."""
        self.fetcher.clear_cache()
        item = self.fetcher.get_question('ITEM_NULL_AXES')
        self.assertEqual(item['axes'], {},
                         "NULL axis columns must not appear in axes")
        self.assertNotIn('claim_provenance', item)

    def test_no_empty_provenance_is_synthesized(self):
        """An axis WITH analysis but WITHOUT recorded claims gets no
        'provenance' key — empty is never presented as present."""
        self.fetcher.clear_cache()
        item = self.fetcher.get_question('ITEM_FULL')
        self.assertIn('Axis_3', item['axes'])
        self.assertNotIn('provenance', item['axes']['Axis_3'])

    def test_claim_without_sources_or_actor_rejected(self):
        conn = self.fetcher.get_connection()
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(conn, 'ITEM_FULL', 'Axis_6', '/x', 'stmt', 'INFERENCE',
                            derived_by=None)
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(conn, 'ITEM_FULL', 'Axis_9', '/x', 'stmt', 'INFERENCE',
                            derived_by={'actor_type': 'AGENT', 'actor_id': 'a'})
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(conn, 'ITEM_FULL', 'Axis_6', 'no-slash', 'stmt', 'INFERENCE',
                            derived_by={'actor_type': 'AGENT', 'actor_id': 'a'})

    def test_teacher_approval_links_human_verified(self):
        conn = self.fetcher.get_connection()
        self.record_sample_claim(conn)
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        rs.transition(conn, 'ITEM_FULL', 'TEACHER_ASSIGNED', actor_id='t-kim')
        event = rs.transition(conn, 'ITEM_FULL', 'TEACHER_APPROVED', actor_id='t-kim')
        row = conn.execute(
            "SELECT human_review_status, human_review_event_id FROM claim_provenance "
            "WHERE item_id='ITEM_FULL'"
        ).fetchone()
        self.assertEqual(row[0], 'HUMAN_VERIFIED')
        self.assertEqual(row[1], event['event_id'])

    def test_teacher_rejection_links_human_rejected(self):
        conn = self.fetcher.get_connection()
        self.record_sample_claim(conn)
        rs.transition(conn, 'ITEM_FULL', 'REVIEW_REQUIRED', actor_id='sys', actor_type='SYSTEM')
        event = rs.transition(conn, 'ITEM_FULL', 'REJECTED', actor_id='t-kim',
                              reason_code='MATH_ERROR')
        row = conn.execute(
            "SELECT human_review_status, human_review_event_id FROM claim_provenance "
            "WHERE item_id='ITEM_FULL'"
        ).fetchone()
        self.assertEqual(row[0], 'HUMAN_REJECTED')
        self.assertEqual(row[1], event['event_id'])


if __name__ == '__main__':
    unittest.main()
