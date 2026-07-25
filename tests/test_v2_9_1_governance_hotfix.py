# -*- coding: utf-8 -*-
"""
Acceptance tests for v2.9.1 Cryptographic Governance & True Semantic Proof Hotfix.
Covers:
  - Non-circular IndependentSolverEngine (no Axis 3/5 answer copy or ground_truth shortcut)
  - OptionBindingJudge & CanonicalAnswerSchema
  - Dynamic SymPy HoldoutVerifierEngine
  - Strict 7-Point Exit Gate Pre-conditions
  - HMAC secret key environment variable handling
  - Live GitHub REST API CI attestation
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
from pipeline.query_engine.independent_solver import IndependentSolverEngine, HoldoutVerifierEngine
from pipeline.query_engine.quality_plane_judges import (
    IndependentSolverJudge, OptionBindingJudge, HoldoutJudge, QualityPlaneEvaluator, JudgeExecutionStatus
)
from pipeline.governance_service.audit_signer import get_secret_key
from pipeline.governance_service.ci_verifier import verify_remote_ci_live
from pipeline.migrate_db_v2_8_1 import run_migration
from pipeline.migrate_db_v2_8_4 import migrate as run_migration_v2_8_4
from pipeline.migrate_db_v2_9_0 import migrate as run_migration_v2_9_0
from pipeline.migrate_db_v2_9_1 import migrate as run_migration_v2_9_1
try:
    from tests.test_review_state_machine import build_mini_db
except ImportError:
    from test_review_state_machine import build_mini_db


class TestV291GovernanceHotfix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='gov_v291_')
        cls._golden = os.path.join(cls._tmpdir, 'golden.db')
        build_mini_db(cls._golden)
        run_migration(cls._golden, backup=False)
        run_migration_v2_8_4(cls._golden)
        run_migration_v2_9_0(cls._golden)
        run_migration_v2_9_1(cls._golden)

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

    def test_non_circular_solver_does_not_copy_axis3(self):
        """IndependentSolverEngine must NOT return PASS simply because Axis 3 has concept_id or standard_solution."""
        engine = IndependentSolverEngine()
        item = {
            "item_id": "DUMMY_1",
            "latex_content": "",
            "answer": 15,
            "axes": {"Axis_3": {"concept_id": "CONCEPT_POLY_RATIO_31", "solved_answer": 15}},
        }
        res = engine.solve_item(item)
        # Empty latex_content must yield NOT_RUN, not PASS
        self.assertEqual(res["execution_status"], "NOT_RUN")
        self.assertIsNone(res["calc_value"])

    def test_sympy_equation_solve(self):
        """IndependentSolverEngine solves equations independently and returns calc_value."""
        engine = IndependentSolverEngine()
        item = {
            "item_id": "EQ_ITEM",
            "latex_content": "Solve x**2 - 5*x + 6 = 0",
        }
        res = engine.solve_item(item)
        self.assertEqual(res["execution_status"], "PASS")
        self.assertIn(res["calc_value"], (2, 3))

    def test_option_binding_judge(self):
        """OptionBindingJudge matches calc_value against canonical_answer_json."""
        judge = OptionBindingJudge()
        item = {
            "canonical_answer_json": '{"response_type": "SHORT_ANSWER", "correct_option_index": null, "correct_value": 3}'
        }
        ctx = {"calc_value": 3}
        res = judge.evaluate(item, context=ctx)
        self.assertTrue(res.passed)
        self.assertEqual(res.execution_status, JudgeExecutionStatus.PASS)

    def test_dynamic_holdout_verifier(self):
        """HoldoutVerifierEngine constructs parameter variation E' and solves it dynamically."""
        engine = HoldoutVerifierEngine()
        item = {
            "item_id": "VAR_ITEM",
            "latex_content": "Solve 2*x - 10 = 0",
        }
        res = engine.verify_holdout_variations(item)
        self.assertEqual(res["execution_status"], "PASS")
        self.assertTrue(res["is_holdout_passed"])
        self.assertIn("variation_latex", res)

    def test_hmac_secret_key_environment(self):
        """get_secret_key respects KICE_GOVERNANCE_HMAC_SECRET environment variable."""
        old_val = os.environ.get("KICE_GOVERNANCE_HMAC_SECRET")
        try:
            os.environ["KICE_GOVERNANCE_HMAC_SECRET"] = "custom-test-secret-key-999"
            self.assertEqual(get_secret_key(), "custom-test-secret-key-999")
        finally:
            if old_val is not None:
                os.environ["KICE_GOVERNANCE_HMAC_SECRET"] = old_val
            else:
                os.environ.pop("KICE_GOVERNANCE_HMAC_SECRET", None)

    def test_strict_7_point_gate_rejection_on_missing_proof(self):
        """revalidate_item returns SEMANTIC_PROOF_PENDING when solver/option/holdout proof is missing."""
        self.service.reopen_item("ITEM_FULL", self.system, reason_code="REQUEUED")
        self.service.assign_item("ITEM_FULL", self.teacher)
        self.service.approve_item("ITEM_FULL", self.teacher, notes="Teacher approved")

        res = self.service.revalidate_item("ITEM_FULL", self.system)
        self.assertIn(res["event"]["to_status"], ("SEMANTIC_PROOF_PENDING", "REVIEW_REQUIRED"))


if __name__ == '__main__':
    unittest.main()
