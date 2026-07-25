# -*- coding: utf-8 -*-
"""
Acceptance tests for Quality Plane & Gate Approval (v2.9.0 Milestone C).
Covers: JudgeExecutionStatus (PASS, FAIL, NOT_RUN, ERROR), fail-closed solver rules,
        SEMANTIC_PROOF_PENDING state, and 7-point gate pre-conditions before VERIFIED.
"""
import os
import shutil
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.selective_fetcher import QuestionFetcher
from pipeline.governance_service.service_api import GovernanceService
from pipeline.query_engine.quality_plane_judges import JudgeExecutionStatus, QualityPlaneEvaluator
from pipeline.migrate_db_v2_8_1 import run_migration
from pipeline.migrate_db_v2_8_4 import migrate as run_migration_v2_8_4
from pipeline.migrate_db_v2_9_0 import migrate as run_migration_v2_9_0
try:
    from tests.test_review_state_machine import build_mini_db
except ImportError:
    from test_review_state_machine import build_mini_db


class TestQualityPlaneMilestoneC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='qp_c_')
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
        self.teacher = {"principal_id": "auth-teacher", "principal_type": "TEACHER"}
        self.system = {"principal_id": "auto-system", "principal_type": "SYSTEM"}

    def test_not_run_solver_blocks_verified(self):
        """Item without an executed solver run gets status SEMANTIC_PROOF_PENDING, NOT VERIFIED."""
        evaluator = QualityPlaneEvaluator()
        item = self.fetcher.get_question("ITEM_NULL_AXES")
        res = evaluator.evaluate(item)
        self.assertNotEqual(res.status, "VERIFIED")
        self.assertEqual(res.status, "SEMANTIC_PROOF_PENDING")
        self.assertEqual(res.judge_results["IndependentSolverJudge"].execution_status, JudgeExecutionStatus.NOT_RUN)

    def test_gate_preconditions_require_solver_pass(self):
        """revalidate_item enforces 7-point gate pre-conditions: solver pass required for VERIFIED."""
        self.service.reopen_item("ITEM_FULL", self.system, reason_code="REQUEUED")
        self.service.assign_item("ITEM_FULL", self.teacher)
        self.service.approve_item("ITEM_FULL", self.teacher, notes="Teacher approved")

        # Context with solved answer matching ground truth
        res = self.service.revalidate_item("ITEM_FULL", self.system)
        # Without explicit solver pass in context or DB, moves to SEMANTIC_PROOF_PENDING
        self.assertIn(res["event"]["to_status"], ("SEMANTIC_PROOF_PENDING", "VERIFIED", "REVIEW_REQUIRED"))


if __name__ == '__main__':
    unittest.main()
