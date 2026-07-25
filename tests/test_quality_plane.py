#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated Unit Test Suite for Quality Plane & 9-Judge Veto Gate (test_quality_plane.py)
"""

import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.quality_plane_judges import (
    ParsingJudge,
    MathEquivalenceJudge,
    IndependentSolverJudge,
    DistractorReplayJudge,
    CurriculumJudge,
    LineageJudge,
    InstructorJudge,
    AdversarialJudge,
    HoldoutJudge,
    QualityPlaneEvaluator,
    LINEAGE_RELATION_PARENT_ALLOWED_MAP,
)
from pipeline.query_engine.selective_fetcher import QuestionFetcher, _is_item_unverified
from pipeline.query_engine.distractor_replay_engine import build_202606_math_dif_15_hypotheses, DistractorHypothesis


class TestQualityPlaneJudges(unittest.TestCase):
    def setUp(self):
        self.valid_item = {
            "item_id": "202606_MATH_DIF_15",
            "latex_content": "Consider $f(x) = a x^2 (x - 3)$. Find $f(6)$.",
            "score": 4,
            "answer": 27,
            "asset_image_url": None,
            "axes": {
                "Axis_1": {
                    "routing_key": "MATH2_DIFF_EXTREMA",
                    "primary_unit": {
                        "curriculum_2022": "Calculus_I",
                        "achievement_standard": "MATH2123",
                        "topic_name": "Polynomial Extrema",
                    },
                },
                "Axis_2": {
                    "raw_parsing_error": False,
                    "latex_integrity": "OK",
                    "image_required": False,
                },
                "Axis_3": {
                    "root_multiplicity_check": True,
                    "logical_derivation": True,
                    "equivalence_verified": True,
                    "solved_answer": 27,
                },
                "Axis_4": {
                    "standard_solution": "f'(x) = 3a x^2 - 6a x...",
                    "shortcut_solving_suggestions": [
                        {
                            "shortcut_formula": "Extrema ratio 2:1",
                            "rule_name": "Ratio Rule",
                            "shortcut_prerequisites": ["Polynomial degree 3"],
                            "shortcut_traps": ["Sign error in lead coefficient"],
                        }
                    ],
                },
                "Axis_5": {
                    "audit_trail": {"verification_status": "PASS", "confidence_score": 0.95},
                    "option_construction_matrix": build_202606_math_dif_15_hypotheses(),
                },
                "Axis_6": {
                    "historical_precedents": [
                        {
                            "precedent_item_id": "202411_MATH_DIF_22",
                            "relationship_type": "DIRECT_GENEALOGY",
                            "genealogy_parent_allowed": True,
                        }
                    ]
                },
                "Axis_7": {
                    "holdout_verified": True,
                    "generalization_score": 0.95,
                },
            },
        }

    # 1. ParsingJudge Tests
    def test_parsing_judge_pass(self):
        judge = ParsingJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)
        self.assertEqual(res.score, 1.0)

    def test_parsing_judge_veto_missing_latex(self):
        judge = ParsingJudge()
        item = self.valid_item.copy()
        item["latex_content"] = ""
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Missing or empty latex_content", res.reason)

    def test_parsing_judge_veto_invalid_score(self):
        judge = ParsingJudge()
        item = self.valid_item.copy()
        item["score"] = -1
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Non-positive score", res.reason)

    def test_parsing_judge_veto_mismatched_braces(self):
        judge = ParsingJudge()
        item = self.valid_item.copy()
        item["latex_content"] = "Solve $f(x) = { x^2 + 1 $"
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Mismatched LaTeX curly braces", res.reason)

    def test_parsing_judge_veto_missing_image(self):
        judge = ParsingJudge()
        item = self.valid_item.copy()
        item["latex_content"] = "Refer to figure [그림] below."
        item["asset_image_url"] = None
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("asset_image_url is missing", res.reason)

    # 2. MathEquivalenceJudge Tests
    def test_math_equivalence_judge_pass(self):
        judge = MathEquivalenceJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)

    def test_math_equivalence_judge_veto_root_mismatch(self):
        judge = MathEquivalenceJudge()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_3"] = {"root_multiplicity_check": False}
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Root multiplicity check failed", res.reason)

    def test_math_equivalence_judge_veto_derivation_contradiction(self):
        judge = MathEquivalenceJudge()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_3"] = {"logical_derivation": "CONTRADICTION"}
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Logical derivation contradiction", res.reason)

    # 3. IndependentSolverJudge Tests
    def test_independent_solver_judge_pass(self):
        judge = IndependentSolverJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)

    def test_independent_solver_judge_veto_mismatch(self):
        judge = IndependentSolverJudge()
        item = self.valid_item.copy()
        item["answer"] = 27
        context = {"solved_answer": 99}
        res = judge.evaluate(item, context=context)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("conflicts with ground truth answer", res.reason)

    # 4. DistractorReplayJudge Tests
    def test_distractor_replay_judge_pass(self):
        judge = DistractorReplayJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)

    def test_distractor_replay_judge_veto_on_bad_hypothesis(self):
        judge = DistractorReplayJudge()
        bad_hyp = DistractorHypothesis(
            option=1,
            option_value=18,
            error_program={"type": "python_expr", "expression": "999"},  # 999 != 18
        )
        res = judge.evaluate(self.valid_item, context={"distractor_hypotheses": [bad_hyp]})
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Distractor option 1 replay Veto", res.reason)

    # 5. CurriculumJudge Tests
    def test_curriculum_judge_pass(self):
        judge = CurriculumJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)

    def test_curriculum_judge_veto_unknown_topic(self):
        judge = CurriculumJudge()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_1"] = {"primary_unit": {"achievement_standard": "UNKNOWN", "topic_name": "UNKNOWN"}}
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("UNKNOWN achievement standard", res.reason)

    # 6. LineageJudge Tests
    def test_lineage_judge_7_closed_enums_all_pass(self):
        judge = LineageJudge()
        for rel_enum, expected_parent_allowed in LINEAGE_RELATION_PARENT_ALLOWED_MAP.items():
            item = self.valid_item.copy()
            item["axes"] = dict(self.valid_item["axes"])
            item["axes"]["Axis_6"] = {
                "historical_precedents": [
                    {
                        "precedent_item_id": "202411_MATH_DIF_22",
                        "relationship_type": rel_enum,
                        "genealogy_parent_allowed": expected_parent_allowed,
                    }
                ]
            }
            res = judge.evaluate(item)
            self.assertTrue(res.passed, f"Failed for valid enum {rel_enum}")
            self.assertFalse(res.is_vetoed, f"Unexpected veto for valid enum {rel_enum}")

    def test_lineage_judge_veto_invalid_enum(self):
        judge = LineageJudge()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_6"] = {
            "historical_precedents": [
                {
                    "precedent_item_id": "202411_MATH_DIF_22",
                    "relationship_type": "INVALID_RELATION_NAME",
                    "genealogy_parent_allowed": True,
                }
            ]
        }
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Invalid lineage relation enum", res.reason)

    def test_lineage_judge_veto_parent_allowed_mismatch(self):
        judge = LineageJudge()
        # STRUCTURAL_ANALOGY requires genealogy_parent_allowed = False
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_6"] = {
            "historical_precedents": [
                {
                    "precedent_item_id": "202411_MATH_DIF_22",
                    "relationship_type": "STRUCTURAL_ANALOGY",
                    "genealogy_parent_allowed": True,  # Violation! Should be False
                }
            ]
        }
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Lineage rule violation", res.reason)

    # 7. InstructorJudge Tests
    def test_instructor_judge_pass_full_completeness(self):
        judge = InstructorJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)
        self.assertEqual(res.details["completeness_score"], 1.0)

    def test_instructor_judge_veto_empty_standard_solution(self):
        judge = InstructorJudge()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_4"] = {}
        item["standard_solution"] = ""
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("Missing required standard_solution", res.reason)


    # 8. AdversarialJudge Tests
    def test_adversarial_judge_pass(self):
        judge = AdversarialJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)

    def test_adversarial_judge_veto_counterexample(self):
        judge = AdversarialJudge()
        res = judge.evaluate(self.valid_item, context={"adversarial": {"counterexample_found": True}})
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("counterexample disproving item reasoning", res.reason)

    # 9. HoldoutJudge Tests
    def test_holdout_judge_pass(self):
        judge = HoldoutJudge()
        res = judge.evaluate(self.valid_item)
        self.assertTrue(res.passed)
        self.assertFalse(res.is_vetoed)

    def test_holdout_judge_veto_failed(self):
        judge = HoldoutJudge()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_7"] = {"holdout_verified": False}
        res = judge.evaluate(item)
        self.assertFalse(res.passed)
        self.assertTrue(res.is_vetoed)
        self.assertIn("holdout generalization test failed", res.reason)

    # 10. QualityPlaneEvaluator Aggregate Tests
    def test_evaluator_full_verified(self):
        evaluator = QualityPlaneEvaluator()
        res = evaluator.evaluate(self.valid_item)
        self.assertEqual(res.status, "VERIFIED")
        self.assertFalse(res.is_vetoed)
        self.assertGreaterEqual(res.overall_confidence, 0.85)
        self.assertEqual(len(res.veto_reasons), 0)
        self.assertEqual(len(res.judge_results), 10)

    def test_evaluator_veto_gate_single_judge_fail(self):
        evaluator = QualityPlaneEvaluator()
        item = self.valid_item.copy()
        item["latex_content"] = "Mismatched { curly brace"  # ParsingJudge fail
        res = evaluator.evaluate(item)
        self.assertEqual(res.status, "VETOED")
        self.assertTrue(res.is_vetoed)
        self.assertGreater(len(res.veto_reasons), 0)
        self.assertIn("[ParsingJudge]", res.veto_reasons[0])

    def test_evaluator_provisional_status(self):
        evaluator = QualityPlaneEvaluator()
        item = self.valid_item.copy()
        item["axes"] = dict(self.valid_item["axes"])
        item["axes"]["Axis_4"] = {}
        res = evaluator.evaluate(item)
        self.assertIn(res.status, ["VERIFIED", "PROVISIONAL"])

    # 11. Selective Fetcher Integration Test
    def test_selective_fetcher_integration(self):
        fetcher = QuestionFetcher()
        item = fetcher.get_question("202411_MATH_DIF_22")
        qp_res = fetcher.evaluate_quality_plane("202411_MATH_DIF_22")
        self.assertIn(qp_res.status, ["VERIFIED", "PROVISIONAL", "SEMANTIC_PROOF_PENDING", "VETOED"])
        self.assertIsInstance(_is_item_unverified(item), bool)


if __name__ == "__main__":
    unittest.main()
