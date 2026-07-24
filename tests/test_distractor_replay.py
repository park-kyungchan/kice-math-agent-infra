#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated Unit Test Suite for Distractor Replay & SymPy Solver Engine (test_distractor_replay.py)
"""

import os
import sys
import unittest
import sympy as sp

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.query_engine.distractor_replay_engine import (
    DistractorReplayEngine,
    DistractorHypothesis,
    ReplayResult,
    build_202606_math_dif_15_hypotheses,
)


class TestDistractorReplayEngine(unittest.TestCase):
    def setUp(self):
        self.engine = DistractorReplayEngine()

    def test_202606_math_dif_15_option3_pass(self):
        """
        Verify Option 3 (value 24) of 202606_MATH_DIF_15 with error program a=2/9 -> f(6)=24.
        Should result in is_vetoed = False (VERIFIED).
        """
        hypotheses = build_202606_math_dif_15_hypotheses()
        opt3_hyp = next(h for h in hypotheses if h.option == 3)
        
        self.assertEqual(opt3_hyp.option_value, 24)
        
        result = self.engine.verify_hypothesis(opt3_hyp)
        
        self.assertFalse(result.is_vetoed)
        self.assertEqual(result.replay_status, "VERIFIED")
        self.assertEqual(result.replayed_result, 24)
        self.assertIsNone(result.veto_reason)

    def test_202606_math_dif_15_option3_veto_on_mismatch(self):
        """
        Verify that if Option 3 error program produces a wrong value (e.g. 36 != 24),
        is_vetoed is set to True (VETOED).
        """
        bad_hyp = DistractorHypothesis(
            option=3,
            option_value=24,
            error_code="DIST_CALC_ERROR",
            cause="Wrong calculation resulting in a=1/3",
            error_program={
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "1/3"},
                    {"var": "f6", "expr": "a * 6**2 * (6 - 3)"}
                ],
                "return_var": "f6"
            }
        )
        
        result = self.engine.verify_hypothesis(bad_hyp)
        
        self.assertTrue(result.is_vetoed)
        self.assertEqual(result.replay_status, "VETOED")
        self.assertEqual(result.replayed_result, 36)
        self.assertIsNotNone(result.veto_reason)
        self.assertIn("does not match option value", result.veto_reason)

    def test_full_202606_math_dif_15_matrix(self):
        """
        Verify all 5 choices for 202606_MATH_DIF_15 pass verification cleanly.
        """
        hypotheses = build_202606_math_dif_15_hypotheses()
        results = self.engine.verify_matrix(hypotheses)
        
        self.assertEqual(len(results), 5)
        for res in results:
            self.assertFalse(res.is_vetoed, f"Option {res.option} was unexpectedly vetoed: {res.veto_reason}")
            self.assertEqual(res.replay_status, "VERIFIED")

    def test_sympy_expression_execution(self):
        """
        Test SymPy expression evaluation with symbol substitution.
        """
        expr = "a * x**2 * (x - 3)"
        symbols = {"a": "2/9", "x": 6}
        res = self.engine.execute_sympy_expression(expr, symbols)
        self.assertEqual(res, 24)

    def test_python_expr_and_callable(self):
        """
        Test python_expr and python callable error program types.
        """
        # Python expr dict
        hyp_py = DistractorHypothesis(
            option=1,
            option_value=18,
            error_program={"type": "python_expr", "expression": "(1/6) * (6**2) * (6 - 3)"}
        )
        res_py = self.engine.verify_hypothesis(hyp_py)
        self.assertFalse(res_py.is_vetoed)
        self.assertEqual(res_py.replayed_result, 18)

        # Callable function
        hyp_fn = DistractorHypothesis(
            option=2,
            option_value=21,
            error_program=lambda: (7 / 36) * (6 ** 2) * (6 - 3)
        )
        res_fn = self.engine.verify_hypothesis(hyp_fn)
        self.assertFalse(res_fn.is_vetoed)
        self.assertEqual(res_fn.replayed_result, 21)

    def test_faulty_and_missing_error_programs(self):
        """
        Test error handling when error program raises an exception or is missing.
        """
        # Missing error program
        hyp_missing = DistractorHypothesis(option=1, option_value=10, error_program=None)
        res_missing = self.engine.verify_hypothesis(hyp_missing)
        self.assertTrue(res_missing.is_vetoed)
        self.assertEqual(res_missing.replay_status, "EXECUTION_ERROR")

        # Zero division error
        hyp_div_zero = DistractorHypothesis(
            option=1,
            option_value=10,
            error_program={"type": "python_expr", "expression": "1 / 0"}
        )
        res_zero = self.engine.verify_hypothesis(hyp_div_zero)
        self.assertTrue(res_zero.is_vetoed)
        self.assertEqual(res_zero.replay_status, "EXECUTION_ERROR")

    def test_dict_hypothesis_input(self):
        """
        Test passing dictionary format to verify_hypothesis.
        """
        dict_hyp = {
            "option": 3,
            "value": 24,
            "error_code": "DIST_CALC_ERROR",
            "cause": "Ratio error",
            "error_program": {
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "2/9"},
                    {"var": "res", "expr": "a * 6**2 * (6-3)"}
                ]
            }
        }
        res = self.engine.verify_hypothesis(dict_hyp)
        self.assertFalse(res.is_vetoed)
        self.assertEqual(res.replayed_result, 24)
        self.assertEqual(res.to_dict()["replay_status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
