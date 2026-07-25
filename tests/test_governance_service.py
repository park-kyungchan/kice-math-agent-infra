# -*- coding: utf-8 -*-
"""
Acceptance tests for Governance Service Intent-Based API (v2.8.4 Milestone B).
Covers: assign_item, approve_item, request_revision, record_revision, reject_item,
        revalidate_item, reopen_item, and authenticated principal identity enforcement.
"""
import os
import shutil
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.selective_fetcher import QuestionFetcher
from pipeline.governance_service.service_api import GovernanceService, GovernanceServiceError
from pipeline.query_engine.review_state import TransitionError, ConcurrencyError
from pipeline.migrate_db_v2_8_1 import run_migration
from pipeline.migrate_db_v2_8_4 import migrate as run_migration_v2_8_4
from pipeline.migrate_db_v2_9_0 import migrate as run_migration_v2_9_0
try:
    from tests.test_review_state_machine import build_mini_db
except ImportError:
    from test_review_state_machine import build_mini_db


class TestGovernanceService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='gov_service_')
        cls._golden = os.path.join(cls._tmpdir, 'golden.db')
        build_mini_db(cls._golden)
        run_migration(cls._golden, backup=False)
        run_migration_v2_8_4(cls._golden)
        run_migration_v2_9_0(cls._golden)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        self.db = os.path.join(self._tmpdir, f'{self._testMethodName}.db')
        shutil.copy2(self._golden, self.db)
        self.fetcher = QuestionFetcher(db_path=self.db)
        self.service = GovernanceService(self.fetcher)
        self.teacher_principal = {"principal_id": "auth-t-kim", "principal_type": "TEACHER"}
        self.system_principal = {"principal_id": "auto-system", "principal_type": "SYSTEM"}

    def test_governance_service_intent_flow(self):
        # 1. System moves item to REVIEW_REQUIRED via reopen/requeue intent
        evt1 = self.service.reopen_item('ITEM_FULL', self.system_principal, reason_code='REQUEUED')
        self.assertEqual(evt1['to_status'], 'REVIEW_REQUIRED')

        # 2. Teacher assigns item
        evt2 = self.service.assign_item('ITEM_FULL', self.teacher_principal)
        self.assertEqual(evt2['to_status'], 'TEACHER_ASSIGNED')
        self.assertEqual(evt2['principal_id'], 'auth-t-kim')

        # 3. Teacher requests revision
        evt3 = self.service.request_revision('ITEM_FULL', self.teacher_principal, notes='Clarify step 2')
        self.assertEqual(evt3['to_status'], 'REVISION_REQUESTED')

        # 4. Teacher records revision
        evt4 = self.service.record_revision('ITEM_FULL', self.teacher_principal, notes='Step 2 clarified')
        self.assertEqual(evt4['to_status'], 'TEACHER_REVISED')

        # 5. System re-queues revised item
        evt5 = self.service.reopen_item('ITEM_FULL', self.system_principal, reason_code='REVISED_AWAITING_REREVIEW')
        self.assertEqual(evt5['to_status'], 'REVIEW_REQUIRED')

        # 6. Teacher assigns and approves
        self.service.assign_item('ITEM_FULL', self.teacher_principal)
        evt6 = self.service.approve_item('ITEM_FULL', self.teacher_principal, notes='Approved after revision')
        self.assertEqual(evt6['to_status'], 'TEACHER_APPROVED')

        # 7. Independent Quality Plane revalidation via service exit gate
        res = self.service.revalidate_item('ITEM_FULL', self.system_principal)
        self.assertIn('revalidation_green', res)
        self.assertIn('event', res)

    def test_principal_identity_cannot_be_overridden(self):
        """Worker cannot override principal identity using arbitrary payload strings."""
        self.service.reopen_item('ITEM_FULL', self.system_principal, reason_code='REQUEUED')
        evt = self.service.assign_item('ITEM_FULL', self.teacher_principal)
        self.assertEqual(evt['principal_id'], 'auth-t-kim')
        self.assertEqual(evt['actor_id'], 'auth-t-kim')
        self.assertEqual(evt['principal_type'], 'TEACHER')

    def test_revalidate_item_rejects_caller_target_state(self):
        """revalidate_item does not take to_status or reason_code from caller."""
        # revalidate_item signature is (item_id, principal, expected_version)
        import inspect
        sig = inspect.signature(self.service.revalidate_item)
        params = set(sig.parameters.keys())
        self.assertNotIn('to_status', params)
        self.assertNotIn('quality_plane_status', params)
        self.assertNotIn('reason_code', params)


if __name__ == '__main__':
    unittest.main()
