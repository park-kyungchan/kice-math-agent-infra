import os
import sys
import unittest
import json
import sympy as sp

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.selective_fetcher import QuestionFetcher, _is_item_unverified
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
from pipeline.query_engine.distractor_replay_engine import (
    DistractorReplayEngine,
    DistractorHypothesis,
    build_202606_math_dif_15_hypotheses,
)


class TestMathematicalEquivalence(unittest.TestCase):
    """
    Tier 1 Semantic Eval: Validates mathematical correctness, symbolic calculation,
    answer verification checksums, and target function values for benchmark items.
    """

    def setUp(self):
        self.fetcher = QuestionFetcher()
        self.benchmark_id = '202606_MATH_DIF_15'

    def test_benchmark_item_symbolic_evaluation_202606_15(self):
        item = self.fetcher.get_question(self.benchmark_id)
        self.assertEqual(item['item_id'], self.benchmark_id)

        axis3 = item['axes'].get('Axis_3', {})
        self.assertIn('coefficients', axis3)
        coeffs = axis3['coefficients']

        # Verify function coefficients f(x) = a*x^3 + b*x^2 + c*x + d = 0.25*x^3 - 0.75*x^2
        a = coeffs.get('a', 0.0)
        b = coeffs.get('b', 0.0)
        c = coeffs.get('c', 0.0)
        d = coeffs.get('d', 0.0)
        self.assertEqual(a, 0.25)
        self.assertEqual(b, -0.75)
        self.assertEqual(c, 0.0)
        self.assertEqual(d, 0.0)

        # SymPy Symbolic Function Construction & Evaluation
        x = sp.Symbol('x')
        f_x = a * (x**3) + b * (x**2) + c * x + d

        # Evaluate f(6)
        val_f6 = float(f_x.subs(x, 6))
        self.assertEqual(val_f6, 27.0, f"Expected f(6) == 27, got {val_f6}")

        # Check Axis_3 calculated_value
        calc_val = axis3.get('calculated_value', {})
        self.assertEqual(calc_val.get('f_6'), 27)

        # Check Roots & Local Extrema
        val_f0 = float(f_x.subs(x, 0))
        val_f3 = float(f_x.subs(x, 3))
        val_f2 = float(f_x.subs(x, 2))
        self.assertEqual(val_f0, 0.0)
        self.assertEqual(val_f3, 0.0)
        self.assertEqual(val_f2, -1.0)

    def test_answer_verification_checksums_and_option_matching(self):
        item = self.fetcher.get_question(self.benchmark_id)

        # Item level answer checks
        self.assertEqual(item.get('answer'), 4)

        # Axis 5 trap & verification matrix
        axis5 = item['axes'].get('Axis_5', {})
        self.assertEqual(axis5.get('correct_option'), 4)
        self.assertEqual(axis5.get('correct_answer_value'), 27)

        # Check distractor matrix option 4 alignment
        dist_matrix = axis5.get('distractor_matrix', [])
        correct_entry = next((opt for opt in dist_matrix if opt.get('option') == 4), None)
        self.assertIsNotNone(correct_entry)
        self.assertEqual(correct_entry.get('value'), 27)
        self.assertEqual(correct_entry.get('error_code'), 'NONE')

        # Check verification protocol checksum
        protocol = axis5.get('verification_protocol', {})
        self.assertEqual(protocol.get('assert_f6'), 27)
        self.assertEqual(protocol.get('solvability_status'), 'PASS')
        self.assertTrue(protocol.get('checksum_match'))


class TestInstructionalUsability(unittest.TestCase):
    """
    Tier 2 Semantic Eval: Validates that Axis_3 and Axis_5 contain textbook standard
    reasoning and speed-up shortcuts (with prerequisite conditions & trap warnings)
    formatted for math instructors, as well as Distractor Replay Engine verification.
    """

    def setUp(self):
        self.fetcher = QuestionFetcher()
        self.benchmark_id = '202606_MATH_DIF_15'
        self.replay_engine = DistractorReplayEngine()

    def test_axis3_textbook_reasoning_and_shortcuts(self):
        item = self.fetcher.get_question(self.benchmark_id)
        axis3 = item['axes'].get('Axis_3', {})

        # Textbook standard modeling
        self.assertEqual(axis3.get('concept_id'), 'POLY_DEG3_INTEGRAL_ABS_SIGN_CHANGE')
        self.assertEqual(axis3.get('function_form'), 'f(x) = a * x^2 * (x - 3)')

        # Speed-up shortcuts formatted for instructors
        shortcuts = axis3.get('shortcuts', [])
        self.assertIsInstance(shortcuts, list)
        self.assertGreaterEqual(len(shortcuts), 1)

        # Check for ratio relation / root placement shortcut descriptions
        shortcut_str = " ".join(shortcuts)
        self.assertTrue(any(kw in shortcut_str for kw in ['비율관계', '2:1', '중근']))

    def test_axis5_distractor_matrix_and_misuse_traps(self):
        item = self.fetcher.get_question(self.benchmark_id)
        axis5 = item['axes'].get('Axis_5', {})

        dist_matrix = axis5.get('distractor_matrix', [])
        self.assertIsInstance(dist_matrix, list)
        self.assertEqual(len(dist_matrix), 5)

        expected_error_codes = {'DIST_CASE_SIGN', 'DIST_INTEGRAL_BOUND', 'DIST_CALC_ERROR', 'NONE', 'DIST_SMOOTH_TRIPLE_ROOT'}
        found_codes = set()

        for entry in dist_matrix:
            self.assertIn('option', entry)
            self.assertIn('value', entry)
            self.assertIn('error_code', entry)
            self.assertIn('cause', entry)
            found_codes.add(entry['error_code'])

            # Every entry must have non-empty instructor-facing cause explanation
            self.assertTrue(len(entry['cause']) > 0)

        self.assertEqual(found_codes, expected_error_codes)

    def test_distractor_replay_engine_verification(self):
        hypotheses = build_202606_math_dif_15_hypotheses()
        self.assertEqual(len(hypotheses), 5)

        # Replay all 5 options: all error programs must deterministically reproduce option values
        results = self.replay_engine.verify_matrix(hypotheses)
        self.assertEqual(len(results), 5)
        for res in results:
            self.assertFalse(res.is_vetoed, f"Option {res.option} unexpectedly vetoed: {res.veto_reason}")
            self.assertEqual(res.replay_status, "VERIFIED")

        # Verify Option 4 (ground truth)
        opt4_res = next(r for r in results if r.option == 4)
        self.assertEqual(opt4_res.replayed_result, 27)
        self.assertEqual(opt4_res.error_code, "NONE")

        # Verify Veto trigger when option value mismatches error program result
        bad_hyp = DistractorHypothesis(
            option=3,
            option_value=24,
            error_code="DIST_CALC_ERROR",
            error_program={"type": "python_expr", "expression": "999"}
        )
        vetoed_res = self.replay_engine.verify_hypothesis(bad_hyp)
        self.assertTrue(vetoed_res.is_vetoed)
        self.assertEqual(vetoed_res.replay_status, "VETOED")
        self.assertIn("does not match option value", vetoed_res.veto_reason)


class TestLineageValidity(unittest.TestCase):
    """
    Tier 3 Semantic Eval: Validates that Axis_6 and Axis_8 maintain valid bidirectional
    relationships, precedent foreign keys, graph topology, 7 closed lineage enums, and
    genealogy parent allowed rules.
    """

    def setUp(self):
        self.fetcher = QuestionFetcher()
        self.benchmark_id = '202606_MATH_DIF_15'
        self.expected_cluster = [
            '202106_MATH_DIF_22',
            '202411_MATH_DIF_22',
            '202506_MATH_DIF_22',
            '202606_MATH_DIF_15'
        ]

    def test_axis6_precedent_foreign_keys_exist(self):
        item = self.fetcher.get_question(self.benchmark_id)
        axis6 = item['axes'].get('Axis_6', {})

        # Foreign key precedent IDs list
        precedent_ids = axis6.get('precedent_item_ids', [])
        self.assertIsInstance(precedent_ids, list)
        self.assertEqual(set(precedent_ids), {'202106_MATH_DIF_22', '202411_MATH_DIF_22', '202506_MATH_DIF_22'})

        # Integrity Check: Each precedent item must physically exist in question_item table
        for pid in precedent_ids:
            p_item = self.fetcher.get_question(pid)
            self.assertNotIn('error', p_item, f"Precedent foreign key item {pid} does not exist in DB")
            self.assertEqual(p_item['item_id'], pid)

        # Detailed historical precedents mapping check
        hist_precedents = axis6.get('historical_precedents', [])
        self.assertEqual(len(hist_precedents), 3)
        hist_ids = [hp['precedent_item_id'] for hp in hist_precedents]
        self.assertEqual(set(hist_ids), {'202106_MATH_DIF_22', '202411_MATH_DIF_22', '202506_MATH_DIF_22'})

    def test_axis8_knowledge_graph_bidirectional_cluster(self):
        item = self.fetcher.get_question(self.benchmark_id)
        axis8 = item['axes'].get('Axis_8', {})

        self.assertEqual(axis8.get('cluster_id'), 'CLUSTER_CALCULUS_INTEGRAL_ABS')
        self.assertGreater(axis8.get('degree_centrality', 0), 0.8)

        connected_nodes = axis8.get('connected_nodes', [])
        self.assertIsInstance(connected_nodes, list)
        self.assertEqual(set(connected_nodes), set(self.expected_cluster))

    def test_get_question_lineage_recursive_structure(self):
        lineage = self.fetcher.get_question_lineage(self.benchmark_id)
        self.assertEqual(lineage['item_id'], self.benchmark_id)
        self.assertIn('precedents', lineage)
        self.assertGreaterEqual(len(lineage['precedents']), 3)

        retrieved_pids = {p['item_id'] for p in lineage['precedents']}
        self.assertTrue({'202106_MATH_DIF_22', '202411_MATH_DIF_22', '202506_MATH_DIF_22'}.issubset(retrieved_pids))

    def test_closed_lineage_enums_and_genealogy_parent_rules(self):
        """
        Validates the 7 closed lineage relation enums and genealogy_parent_allowed rule mapping.
        """
        expected_mapping = {
            "DIRECT_GENEALOGY": True,
            "PROVISIONAL": True,
            "MUTATION_TRANSFORM": True,
            "CONCEPT_PREREQUISITE": True,
            "PARAMETER_SHIFT_ANALOGY": False,
            "STRUCTURAL_ANALOGY": False,
            "REJECTED_RELATION": False,
        }
        self.assertEqual(LINEAGE_RELATION_PARENT_ALLOWED_MAP, expected_mapping)

        # Test LineageJudge enforcement of 7 enums
        judge = LineageJudge()
        for rel_type, parent_allowed in expected_mapping.items():
            mock_item = {
                "axes": {
                    "Axis_6": {
                        "historical_precedents": [
                            {
                                "precedent_item_id": "202411_MATH_DIF_22",
                                "relationship_type": rel_type,
                                "genealogy_parent_allowed": parent_allowed,
                            }
                        ]
                    }
                }
            }
            res = judge.evaluate(mock_item)
            self.assertTrue(res.passed, f"Failed for valid enum {rel_type}")
            self.assertFalse(res.is_vetoed)

        # Test invalid enum triggers Veto
        invalid_item = {
            "axes": {
                "Axis_6": {
                    "historical_precedents": [
                        {
                            "precedent_item_id": "202411_MATH_DIF_22",
                            "relationship_type": "UNDEFINED_ENUM",
                            "genealogy_parent_allowed": True,
                        }
                    ]
                }
            }
        }
        invalid_res = judge.evaluate(invalid_item)
        self.assertTrue(invalid_res.is_vetoed)
        self.assertIn("Invalid lineage relation enum", invalid_res.reason)


class TestHITLReviewFlagging(unittest.TestCase):
    """
    HITL Evaluation: Validates that low confidence scores (<0.85) or unverified
    hypotheses properly trigger review_required = True.
    """

    def setUp(self):
        self.fetcher = QuestionFetcher()
        self.benchmark_id = '202606_MATH_DIF_15'

    def test_clean_verified_item_not_flagged(self):
        item = self.fetcher.get_question(self.benchmark_id)
        self.assertFalse(_is_item_unverified(item))

    def test_low_confidence_score_triggers_review(self):
        # Confidence score in Axis_3 < 0.85
        mock_item_1 = {
            'item_id': 'TEST_ITEM_01',
            'axes': {
                'Axis_3': {'confidence_score': 0.80, 'review_required': False}
            }
        }
        self.assertTrue(_is_item_unverified(mock_item_1))

        # Confidence score in Axis_5 < 0.85
        mock_item_2 = {
            'item_id': 'TEST_ITEM_02',
            'axes': {
                'Axis_5': {'confidence_score': 0.72, 'review_required': False}
            }
        }
        self.assertTrue(_is_item_unverified(mock_item_2))

    def test_review_required_flag_triggers_review(self):
        # Explicit review_required = True (bool)
        mock_item_1 = {
            'item_id': 'TEST_ITEM_04',
            'axes': {
                'Axis_5': {'review_required': True}
            }
        }
        self.assertTrue(_is_item_unverified(mock_item_1))

        # String "true" flag
        mock_item_2 = {
            'item_id': 'TEST_ITEM_05',
            'axes': {
                'Axis_3': {'review_required': "true"}
            }
        }
        self.assertTrue(_is_item_unverified(mock_item_2))

        # Numeric 1 flag
        mock_item_3 = {
            'item_id': 'TEST_ITEM_06',
            'axes': {
                'Axis_5': {'review_required': 1}
            }
        }
        self.assertTrue(_is_item_unverified(mock_item_3))

    def test_unverified_questions_db_fetching(self):
        unverified_items = self.fetcher.get_unverified_questions()
        self.assertIsInstance(unverified_items, list)
        for item in unverified_items:
            self.assertTrue(_is_item_unverified(item))


class TestQualityPlaneAndJudges(unittest.TestCase):
    """
    v2.7.0 Quality Plane & 9-Judge Veto Gate Architecture Tests:
    Validates all 9 independent quality judges and the QualityPlaneEvaluator.
    """

    def setUp(self):
        self.fetcher = QuestionFetcher()
        self.evaluator = QualityPlaneEvaluator()
        self.benchmark_id = '202606_MATH_DIF_15'

    def test_all_9_individual_judges_pass_on_valid_item(self):
        item = self.fetcher.get_question(self.benchmark_id)
        
        parsing_res = ParsingJudge().evaluate(item)
        self.assertTrue(parsing_res.passed)
        self.assertFalse(parsing_res.is_vetoed)

        math_res = MathEquivalenceJudge().evaluate(item)
        self.assertTrue(math_res.passed)
        self.assertFalse(math_res.is_vetoed)

        solver_res = IndependentSolverJudge().evaluate(item)
        self.assertTrue(solver_res.passed)
        self.assertFalse(solver_res.is_vetoed)

        replay_res = DistractorReplayJudge().evaluate(item)
        self.assertTrue(replay_res.passed)
        self.assertFalse(replay_res.is_vetoed)

        curr_res = CurriculumJudge().evaluate(item)
        self.assertTrue(curr_res.passed)
        self.assertFalse(curr_res.is_vetoed)

        lineage_res = LineageJudge().evaluate(item)
        self.assertTrue(lineage_res.passed)
        self.assertFalse(lineage_res.is_vetoed)

        instructor_res = InstructorJudge().evaluate(item)
        self.assertTrue(instructor_res.passed)
        self.assertFalse(instructor_res.is_vetoed)

        adv_res = AdversarialJudge().evaluate(item)
        self.assertTrue(adv_res.passed)
        self.assertFalse(adv_res.is_vetoed)

        holdout_res = HoldoutJudge().evaluate(item)
        self.assertTrue(holdout_res.passed)
        self.assertFalse(holdout_res.is_vetoed)

    def test_quality_plane_evaluator_benchmark_item(self):
        item = self.fetcher.get_question(self.benchmark_id)
        result = self.evaluator.evaluate(item)

        self.assertEqual(result.status, "VERIFIED")
        self.assertFalse(result.is_vetoed)
        self.assertGreaterEqual(result.overall_confidence, 0.85)
        self.assertEqual(len(result.veto_reasons), 0)
        self.assertEqual(len(result.judge_results), 9)

        # Check dictionary export functionality
        res_dict = result.to_dict()
        self.assertEqual(res_dict["status"], "VERIFIED")
        self.assertFalse(res_dict["is_vetoed"])
        self.assertEqual(len(res_dict["judge_results"]), 9)

    def test_quality_plane_veto_gate_enforcement(self):
        # Mismatched curly brace triggers ParsingJudge Veto
        item = self.fetcher.get_question(self.benchmark_id)
        bad_item = dict(item)
        bad_item["latex_content"] = "Solve equation { x + 1 = 0"
        result = self.evaluator.evaluate(bad_item)

        self.assertEqual(result.status, "VETOED")
        self.assertTrue(result.is_vetoed)
        self.assertGreater(len(result.veto_reasons), 0)
        self.assertTrue(any("ParsingJudge" in r for r in result.veto_reasons))


if __name__ == '__main__':
    unittest.main()
