# -*- coding: utf-8 -*-
"""
Tests for pipeline/axis_eval/** (Agent I3).

Never touches the real, read-only storage/parsed_dataset.db directly --
the one test class that reads real data (TestRealCorpusScorecard) always
does so via a `cp`'d temp copy, exactly like tests/test_migrate_axis_agnostic.py.

Covers:
  - M1 reproducibility, demonstrated on a deterministic stub (perfect
    agreement) and a deliberately noisy stub (well below perfect agreement)
    -- mission's explicit requirement.
  - M2 discriminative power cleanly separates a synthetic degenerate axis
    from a synthetic healthy one, AND (against the real corpus copy)
    reproduces the documented axis1_curriculum (distinct=2) vs
    axis2_raw_parsing (distinct=690) split with the exact numbers.
  - M3 mutual information: a deterministic-function pair (MI==H(A), fully
    redundant), an independent pair (MI~0), and the min_n gate.
  - M4 non-circularity guard: built directly from this repo's OWN real
    leak cases (axis5_traps_verification's real payload literally contains
    {"correct_option": 4, "correct_answer_value": 27, ...}; axis3's real
    payload contains the answer under an innocuous key,
    {"calculated_value": {"f_6": 27}}) -- proves the guard catches leaks
    that actually exist in this corpus, not just contrived ones. Also
    proves guard_non_circular(strict=True) RAISES on an unsanitized leak
    (the "test that fails if the answer leaks in" the mission requires),
    and that IndependentSolverEngine, once the fallback bug's fuel
    (item["answer"]) is removed, cannot silently resurrect it.
  - The scorecard end-to-end against a real DB copy: M2 flags 7/8 axes
    DEGENERATE and axis2 OK; M4 refuses to score any DEGENERATE axis.
"""
import copy
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.axis_eval.canonicalize import canonical_value, shannon_entropy_bits
from pipeline.axis_eval.data_access import connect_readonly, fetch_axis_payloads, fetch_item_truth, fetch_all_axis_keys
from pipeline.axis_eval.m1_reproducibility import (
    measure_reproducibility, deterministic_stub_extractor, noisy_stub_extractor,
)
from pipeline.axis_eval.m2_discriminative import discriminative_power
from pipeline.axis_eval.m3_redundancy import mutual_information, pairwise_redundancy_matrix
from pipeline.axis_eval.m4_informational_validity import (
    CircularityViolation, find_leak_keys, find_leak_values, guard_non_circular,
    sanitize_payload, build_solver_item, solve_axis_payload,
    evaluate_informational_validity, short_answer_chance_baseline, MC_CHANCE,
)
from pipeline.axis_eval.outcome_correlation import load_estimated_outcomes, correlate_against_estimated_outcomes
from pipeline.axis_eval.scorecard import build_scorecard, score_axis
from pipeline.query_engine.independent_solver import IndependentSolverEngine

REAL_DB = os.path.join(BASE_DIR, 'storage', 'parsed_dataset.db')
OUTCOME_JSON = os.path.join(BASE_DIR, 'scratch', 'staging', 'I1', 'outcome_data.json')

# ---------------------------------------------------------------------------
# These two dicts are NOT contrived -- they are the exact, real payloads for
# 202606_MATH_DIF_15 read directly from analysis_derivation during this
# agent's reconnaissance pass (see scratch/staging/I3/REPORT.txt). They are
# hardcoded here (rather than re-read from the DB every test run) so this
# test suite documents the concrete leak shapes independent of DB state.
# ---------------------------------------------------------------------------
REAL_AXIS5_LEAK_PAYLOAD = {
    "correct_option": 4,
    "correct_answer_value": 27,
    "distractor_matrix": [
        {"option": 1, "value": 18, "error_code": "DIST_CASE_SIGN", "cause": "a 계수 계산 시 f(2) = -2/3 착오"},
        {"option": 4, "value": 27, "error_code": "NONE", "cause": "정답 (f(x) = 1/4 * x^2 * (x-3), f(6)=27)"},
    ],
    "verification_protocol": {"assert_f6": 27, "solvability_status": "PASS", "checksum_match": True},
}
REAL_AXIS3_LEAK_PAYLOAD = {
    "concept_id": "POLY_DEG3_INTEGRAL_ABS_SIGN_CHANGE",
    "function_form": "f(x) = a * x^2 * (x - 3)",
    "coefficients": {"a": 0.25, "b": -0.75, "c": 0.0, "d": 0.0},
    "extrema": {"local_min": {"x": 2.0, "y": -1.0}},
    "roots": [0.0, 3.0],
    "calculated_value": {"f_6": 27},
    "shortcuts": ["삼차함수 비율관계 2:1 적용 (x=2에서 극소)"],
}
TRUE_VALUE_202606_DIF_15 = 27
TRUE_OPTION_INDEX_202606_DIF_15 = 4


# ===========================================================================
# M1 -- reproducibility
# ===========================================================================
class TestM1Reproducibility(unittest.TestCase):
    def setUp(self):
        self.item_ids = [f"FAKE_{i:04d}" for i in range(200)]

    def test_deterministic_extractor_perfect_agreement(self):
        result = measure_reproducibility(self.item_ids, deterministic_stub_extractor)
        self.assertEqual(result["agreement_rate"], 1.0)
        self.assertEqual(result["n_disagree"], 0)
        self.assertEqual(result["disagreeing_item_ids"], [])

    def test_noisy_extractor_well_below_perfect_agreement(self):
        random.seed(1234)  # test determinism; the extractor itself stays non-deterministic
        result = measure_reproducibility(self.item_ids, noisy_stub_extractor)
        self.assertLess(result["agreement_rate"], 0.9)
        self.assertGreater(result["n_disagree"], 0)
        # Two independent draws from a 5-way uniform distribution agree
        # ~20% of the time; assert we're in a sane neighborhood (not 0, not 1).
        self.assertGreater(result["agreement_rate"], 0.05)

    def test_disagreeing_item_ids_are_reported(self):
        random.seed(7)
        result = measure_reproducibility(self.item_ids, noisy_stub_extractor)
        self.assertTrue(set(result["disagreeing_item_ids"]).issubset(set(self.item_ids)))
        self.assertEqual(len(result["disagreeing_item_ids"]), result["n_disagree"])


# ===========================================================================
# M2 -- discriminative power
# ===========================================================================
class TestM2DiscriminativePower(unittest.TestCase):
    def test_synthetic_degenerate_axis_is_flagged(self):
        payloads = {f"I{i}": json.dumps({"objective": "OBJ_UNDERSTAND"}) for i in range(1347)}
        payloads.update({
            "REAL1": json.dumps({"unit": "calc"}),
            "REAL2": json.dumps({"unit": "geo"}),
            "REAL3": json.dumps({"unit": "prob"}),
        })
        result = discriminative_power(payloads)
        self.assertEqual(result["status"], "DEGENERATE")
        self.assertTrue(result["degenerate"])
        self.assertEqual(result["distinct"], 4)
        self.assertGreater(result["largest_bucket_share"], 0.99)

    def test_synthetic_healthy_axis_is_not_flagged(self):
        payloads = {f"I{i}": json.dumps({"condition": f"unique text body number {i}"}) for i in range(1350)}
        result = discriminative_power(payloads)
        self.assertEqual(result["status"], "OK")
        self.assertFalse(result["degenerate"])
        self.assertEqual(result["distinct"], 1350)

    def test_null_is_its_own_bucket_not_conflated_with_a_value(self):
        payloads = {"A": None, "B": None, "C": json.dumps({"x": 1})}
        result = discriminative_power(payloads)
        self.assertEqual(result["distinct"], 2)

    def test_empty_input_is_insufficient_data(self):
        result = discriminative_power({})
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")


# ===========================================================================
# M3 -- redundancy / mutual information
# ===========================================================================
class TestM3MutualInformation(unittest.TestCase):
    def test_deterministic_function_pair_is_fully_redundant(self):
        # b is an exact function of a -> normalized_mi should be ~1.0
        a = {f"I{i}": json.dumps({"v": i % 10}) for i in range(200)}
        b = {f"I{i}": json.dumps({"w": (i % 10) * 2}) for i in range(200)}  # bijective function of a
        result = mutual_information(a, b, min_n=5)
        self.assertEqual(result["status"], "OK")
        self.assertAlmostEqual(result["normalized_mi"], 1.0, places=6)

    def test_independent_pair_has_near_zero_normalized_mi(self):
        random.seed(42)
        a = {f"I{i}": json.dumps({"v": random.randint(0, 9)}) for i in range(2000)}
        b = {f"I{i}": json.dumps({"w": random.randint(0, 9)}) for i in range(2000)}
        result = mutual_information(a, b, min_n=5)
        self.assertEqual(result["status"], "OK")
        self.assertLess(result["normalized_mi"], 0.15)

    def test_min_n_gate_refuses_to_score_sparse_overlap(self):
        a = {"I1": json.dumps({"v": 1}), "I2": json.dumps({"v": 2})}
        b = {"I1": json.dumps({"w": 1}), "I2": json.dumps({"w": 2})}
        result = mutual_information(a, b, min_n=5)
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["n"], 2)

    def test_constant_axis_gives_trivial_mi_with_explanatory_note(self):
        a = {f"I{i}": json.dumps({"v": "CONST"}) for i in range(10)}
        b = {f"I{i}": json.dumps({"w": i}) for i in range(10)}
        result = mutual_information(a, b, min_n=5)
        self.assertEqual(result["normalized_mi"], 0.0)
        self.assertIn("note", result)


# ===========================================================================
# M4 -- non-circularity guard (THE core requirement)
# ===========================================================================
class TestNonCircularityGuard(unittest.TestCase):
    """Built from this repo's own real leak cases, not contrived ones."""

    def test_finds_name_based_leak_in_real_axis5_payload(self):
        hits = find_leak_keys(REAL_AXIS5_LEAK_PAYLOAD)
        self.assertIn("$.correct_option", hits)
        self.assertIn("$.correct_answer_value", hits)

    def test_finds_value_based_leak_in_real_axis3_payload(self):
        """axis3's leak is subtler: the key is 'calculated_value.f_6', not
        anything matching the name pattern -- only the value-based check
        (hint key 'calculated_value' + numeric match against true_value=27)
        catches it."""
        name_hits = find_leak_keys(REAL_AXIS3_LEAK_PAYLOAD)
        self.assertEqual(name_hits, [])
        value_hits = find_leak_values(REAL_AXIS3_LEAK_PAYLOAD, true_value=TRUE_VALUE_202606_DIF_15,
                                       true_option_index=TRUE_OPTION_INDEX_202606_DIF_15)
        self.assertIn("$.calculated_value.f_6", value_hits)

    def test_guard_raises_on_real_axis5_leak(self):
        """THE required test: fails (raises) if the answer leaks in."""
        with self.assertRaises(CircularityViolation):
            guard_non_circular(REAL_AXIS5_LEAK_PAYLOAD, true_value=TRUE_VALUE_202606_DIF_15,
                                true_option_index=TRUE_OPTION_INDEX_202606_DIF_15, strict=True)

    def test_guard_raises_on_real_axis3_leak(self):
        with self.assertRaises(CircularityViolation):
            guard_non_circular(REAL_AXIS3_LEAK_PAYLOAD, true_value=TRUE_VALUE_202606_DIF_15,
                                true_option_index=TRUE_OPTION_INDEX_202606_DIF_15, strict=True)

    def test_guard_does_not_raise_on_clean_payload(self):
        clean_payload = {"primary_unit": "수학 II", "achievement_standards": ["12수학II02-03"]}
        result = guard_non_circular(clean_payload, true_value=27, true_option_index=4, strict=True)
        self.assertFalse(result["leaked"])

    def test_sanitize_strips_axis5_leak_and_result_passes_guard(self):
        clean, report = sanitize_payload(copy.deepcopy(REAL_AXIS5_LEAK_PAYLOAD),
                                          true_value=TRUE_VALUE_202606_DIF_15,
                                          true_option_index=TRUE_OPTION_INDEX_202606_DIF_15)
        self.assertNotIn("correct_option", clean)
        self.assertNotIn("correct_answer_value", clean)
        # guard on the sanitized output must NOT raise
        result = guard_non_circular(clean, true_value=TRUE_VALUE_202606_DIF_15,
                                     true_option_index=TRUE_OPTION_INDEX_202606_DIF_15, strict=True)
        self.assertFalse(result["leaked"])
        self.assertIn("$.correct_option", report["name_leaks_stripped"])

    def test_sanitize_strips_axis3_leak_and_result_passes_guard(self):
        clean, report = sanitize_payload(copy.deepcopy(REAL_AXIS3_LEAK_PAYLOAD),
                                          true_value=TRUE_VALUE_202606_DIF_15,
                                          true_option_index=TRUE_OPTION_INDEX_202606_DIF_15)
        self.assertEqual(clean["calculated_value"], {})
        result = guard_non_circular(clean, true_value=TRUE_VALUE_202606_DIF_15,
                                     true_option_index=TRUE_OPTION_INDEX_202606_DIF_15, strict=True)
        self.assertFalse(result["leaked"])

    def test_sanitize_does_not_over_strip_unrelated_numbers(self):
        """A legitimate numeric field that happens to differ from the true
        answer must survive sanitization -- the guard targets leaks, not
        all numbers."""
        payload = {"coupling_matrix": {"calculus_polynom_extrema": 0.95}}
        clean, report = sanitize_payload(payload, true_value=27, true_option_index=4)
        self.assertEqual(clean, payload)
        self.assertEqual(report["name_leaks_stripped"], [])
        self.assertEqual(report["value_leaks_stripped"], [])

    def test_build_solver_item_never_contains_answer_or_axes_keys(self):
        clean, _ = sanitize_payload(copy.deepcopy(REAL_AXIS5_LEAK_PAYLOAD), true_value=27, true_option_index=4)
        solver_item = build_solver_item(clean)
        self.assertNotIn("answer", solver_item)
        self.assertNotIn("axes", solver_item)
        self.assertNotIn("solved_answer", solver_item)
        self.assertNotIn("canonical_answer_json", solver_item)

    def test_independent_solver_cannot_resurrect_answer_once_stripped(self):
        """Direct proof that IndependentSolverEngine's documented circular
        fallback (returns item['answer'] as calc_value when SymPy parsing
        fails -- pipeline/query_engine/independent_solver.py lines ~86-105)
        is inert once 'answer' is absent from its input."""
        item_without_answer = {"latex_content": "그림을 보고 답을 구하시오 (garbled, unparseable)"}
        self.assertNotIn("answer", item_without_answer)
        result = IndependentSolverEngine().solve_item(item_without_answer)
        self.assertNotEqual(result.get("execution_status"), "PASS")
        self.assertIsNone(result.get("calc_value"))

    def test_solve_axis_payload_end_to_end_guarded_on_real_axis5_leak(self):
        """End-to-end: even handed the raw, unsanitized, leaking axis5
        payload as JSON text, solve_axis_payload must sanitize + guard
        before ever calling the solver, and must NOT return the leaked
        answer as its calc_value."""
        raw = json.dumps(REAL_AXIS5_LEAK_PAYLOAD, ensure_ascii=False)
        result = solve_axis_payload(raw, true_value=TRUE_VALUE_202606_DIF_15,
                                     true_option_index=TRUE_OPTION_INDEX_202606_DIF_15)
        self.assertIn("_leak_report", result)
        self.assertIn("$.correct_option", result["_leak_report"]["name_leaks_stripped"])
        # The solver receives no text field for axis5's shape (no
        # condition/text/content/latex key survives sanitization), so it
        # correctly reports NOT_RUN rather than fabricating 27.
        self.assertNotEqual(result.get("calc_value"), 27)


# ===========================================================================
# Chance baselines
# ===========================================================================
class TestChanceBaselines(unittest.TestCase):
    def test_mc_chance_is_fixed_one_fifth(self):
        self.assertEqual(MC_CHANCE, 0.20)

    def test_short_answer_baseline_uses_empirical_mode_not_uniform(self):
        values = [8] * 22 + [2] * 21 + [6] * 19 + list(range(100, 100 + 343))  # mimics real skew
        baseline = short_answer_chance_baseline(values)
        self.assertEqual(baseline["mode_value"], "8")
        self.assertEqual(baseline["mode_count"], 22)
        self.assertAlmostEqual(baseline["chance"], 22 / 405, places=6)


# ===========================================================================
# Outcome correlation (secondary, weak)
# ===========================================================================
@unittest.skipUnless(os.path.exists(OUTCOME_JSON), "I1's staged outcome_data.json not present")
class TestOutcomeCorrelation(unittest.TestCase):
    def test_loads_exactly_17_estimated_values(self):
        outcomes = load_estimated_outcomes(OUTCOME_JSON)
        self.assertEqual(len(outcomes), 17)

    def test_zero_variance_payload_is_insufficient_data(self):
        outcomes = load_estimated_outcomes(OUTCOME_JSON)
        payload_map = {item_id: json.dumps({"objective": "OBJ_UNDERSTAND"}) for item_id in outcomes}
        result = correlate_against_estimated_outcomes(payload_map, outcomes)
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertIn("warning", result)

    def test_warning_always_present_even_when_correlation_computed(self):
        outcomes = load_estimated_outcomes(OUTCOME_JSON)
        payload_map = {item_id: json.dumps({"len_proxy": i}) for i, item_id in enumerate(outcomes)}
        result = correlate_against_estimated_outcomes(payload_map, outcomes)
        self.assertIn("warning", result)
        self.assertIn("n=17", result["warning"])


# ===========================================================================
# Real corpus copy -- proves M2/M4 numbers match the documented findings
# ===========================================================================
@unittest.skipUnless(os.path.exists(REAL_DB), "real storage/parsed_dataset.db not present")
class TestRealCorpusScorecard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='axis_eval_realcopy_')
        cls.copy_path = os.path.join(cls._tmpdir, 'real_copy.db')
        shutil.copy2(REAL_DB, cls.copy_path)  # never opens REAL_DB for writing
        cls.scorecard = build_scorecard(cls.copy_path, i1_outcome_json_path=OUTCOME_JSON)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_axis1_curriculum_flagged_degenerate_with_documented_numbers(self):
        m2 = self.scorecard["per_axis"]["axis1_curriculum"]["m2_discriminative_power"]
        self.assertEqual(m2["status"], "DEGENERATE")
        self.assertEqual(m2["distinct"], 2)
        self.assertEqual(m2["n"], 1350)
        self.assertAlmostEqual(m2["largest_bucket_share"], 1347 / 1350, places=6)

    def test_axis2_raw_parsing_is_ok_with_documented_numbers(self):
        m2 = self.scorecard["per_axis"]["axis2_raw_parsing"]["m2_discriminative_power"]
        self.assertEqual(m2["status"], "OK")
        self.assertEqual(m2["distinct"], 690)
        self.assertFalse(m2["degenerate"])

    def test_seven_of_eight_axes_are_degenerate(self):
        degenerate_count = sum(
            1 for axis in self.scorecard["axis_keys"]
            if self.scorecard["per_axis"][axis]["m2_discriminative_power"]["degenerate"]
        )
        self.assertEqual(degenerate_count, 7)

    def test_m4_refuses_to_score_degenerate_axes(self):
        for axis in self.scorecard["axis_keys"]:
            m2 = self.scorecard["per_axis"][axis]["m2_discriminative_power"]
            m4 = self.scorecard["per_axis"][axis]["m4_informational_validity"]
            if m2["degenerate"]:
                self.assertEqual(m4["status"], "INSUFFICIENT_DATA", axis)

    def test_m4_runs_on_axis2_and_reports_mc_and_short_answer_splits(self):
        m4 = self.scorecard["per_axis"]["axis2_raw_parsing"]["m4_informational_validity"]
        self.assertEqual(m4["status"], "OK")
        self.assertEqual(m4["mc"]["n_total"], 945)
        self.assertEqual(m4["short_answer"]["n_total"], 405)
        self.assertEqual(m4["mc"]["chance"], 0.20)

    def test_degenerate_side_artifact_is_flagged_in_redundancy_matrix(self):
        cell = self.scorecard["m3_redundancy_matrix_corpus_scale"]["axis1_curriculum"]["axis2_raw_parsing"]
        self.assertIn("degenerate_side_artifact_warning", cell)

    def test_m1_reports_insufficient_data_for_every_real_axis(self):
        for axis in self.scorecard["axis_keys"]:
            self.assertEqual(self.scorecard["per_axis"][axis]["m1_reproducibility"]["status"], "INSUFFICIENT_DATA")


if __name__ == '__main__':
    unittest.main()
