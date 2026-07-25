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
        row = conn.execute("SELECT latex_content FROM question_item WHERE item_id='ITEM_FULL'").fetchone()
        h_exam = cp.content_hash(row[0], mode="utf8")
        return cp.record_claim(
            conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
            'ITEM_X is a direct genealogy parent', 'INFERENCE',
            source_refs=[{
                'schema_version': 1,
                'source_type': 'ORIGINAL_EXAM_TEXT',
                'item_id': 'ITEM_FULL',
                'field': 'latex_content',
                'content_hash': h_exam,
            }],
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
        self.assertEqual(stored['source_refs'][0]['item_id'], 'ITEM_FULL')
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


class TestClaimProvenanceValidation(ClaimProvenanceTestBase):
    """v2.8.3 closed v1 schema and fail-closed acceptance tests."""

    def test_claim_requires_nonempty_source_refs(self):
        conn = self.fetcher.get_connection()
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=[],
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=None,
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )

    def test_claim_actor_type_is_closed_enum(self):
        conn = self.fetcher.get_connection()
        row = conn.execute("SELECT latex_content FROM question_item WHERE item_id='ITEM_FULL'").fetchone()
        h_exam = cp.content_hash(row[0], mode="utf8")
        ref = {
            'schema_version': 1,
            'source_type': 'ORIGINAL_EXAM_TEXT',
            'item_id': 'ITEM_FULL',
            'field': 'latex_content',
            'content_hash': h_exam,
        }
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE',
                source_refs=[ref],
                derived_by={'actor_type': 'HUMAN', 'actor_id': 'a'},
            )

    def test_v1_source_refs_closed_schema_validation(self):
        conn = self.fetcher.get_connection()
        row = conn.execute("SELECT latex_content FROM question_item WHERE item_id='ITEM_FULL'").fetchone()
        h_exam = cp.content_hash(row[0], mode="utf8")

        # 1. Valid ORIGINAL_EXAM_TEXT
        ref_valid = {
            'schema_version': 1,
            'source_type': 'ORIGINAL_EXAM_TEXT',
            'item_id': 'ITEM_FULL',
            'field': 'latex_content',
            'content_hash': h_exam,
        }
        claim = cp.record_claim(
            conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
            'stmt', 'INFERENCE', source_refs=[ref_valid],
            derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
        )
        self.assertTrue(claim['claim_id'].startswith('CLM-'))

        # 2. Hash mismatch
        ref_bad_hash = dict(ref_valid, content_hash='sha256:' + '0'*64)
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=[ref_bad_hash],
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )

        # 3. Unknown key in dict
        ref_unknown_key = dict(ref_valid, extra_field='forbidden')
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=[ref_unknown_key],
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )

        # 4. Non-existent target item
        ref_fake_item = dict(ref_valid, item_id='NON_EXISTENT_ITEM')
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=[ref_fake_item],
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )

        # 5. Valid QUESTION_ITEM_FIELD
        ans = conn.execute("SELECT answer FROM question_item WHERE item_id='ITEM_FULL'").fetchone()[0]
        h_ans = cp.content_hash(ans, mode="json")
        ref_qif = {
            'schema_version': 1,
            'source_type': 'QUESTION_ITEM_FIELD',
            'item_id': 'ITEM_FULL',
            'field': 'answer',
            'content_hash': h_ans,
        }
        claim2 = cp.record_claim(
            conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
            'stmt', 'INFERENCE', source_refs=[ref_qif],
            derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
        )
        self.assertTrue(claim2['claim_id'].startswith('CLM-'))

        # 6. Valid AXIS_ANALYSIS
        h_axis = cp.content_hash("DIRECT_GENEALOGY", mode="json")
        ref_axis = {
            'schema_version': 1,
            'source_type': 'AXIS_ANALYSIS',
            'item_id': 'ITEM_FULL',
            'field': 'axis6_genealogy',
            'json_pointer': '/historical_precedents/0/relation_type',
            'content_hash': h_axis,
        }
        claim3 = cp.record_claim(
            conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
            'stmt', 'INFERENCE', source_refs=[ref_axis],
            derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
        )
        self.assertTrue(claim3['claim_id'].startswith('CLM-'))

        # 7. AXIS_ANALYSIS invalid pointer
        ref_axis_bad_pointer = dict(ref_axis, json_pointer='/non_existent_pointer', content_hash=h_axis)
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=[ref_axis_bad_pointer],
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )

        # 8. Duplicate source reference
        with self.assertRaises(cp.ProvenanceError):
            cp.record_claim(
                conn, 'ITEM_FULL', 'Axis_6', '/historical_precedents/0/relation_type',
                'stmt', 'INFERENCE', source_refs=[ref_valid, ref_valid],
                derived_by={'actor_type': 'AGENT', 'actor_id': 'a'},
            )


if __name__ == '__main__':
    unittest.main()
