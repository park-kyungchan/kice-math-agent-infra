# -*- coding: utf-8 -*-
"""
pipeline/axis_eval — Axis Evaluation Harness (Agent I3)
========================================================
Scores ANY `axis_key` present in `analysis_derivation` against four
independent metrics (M1 reproducibility, M2 discriminative power,
M3 non-redundancy, M4 informational validity) plus a secondary, clearly
weak correlation against the 17 ESTIMATED outcome values staged by Agent I1.

Design constraint (mission #3): this harness must REFUSE to manufacture a
score over placeholder/degenerate data. Every metric function returns an
explicit status string (`"OK"`, `"DEGENERATE"`, or `"INSUFFICIENT_DATA"`)
alongside its numbers; callers must check status before trusting a number.
See `scorecard.py` for the orchestration policy that wires this together,
and `scratch/staging/I3/REPORT.txt` for the full run against the real 8
axes with literal numbers.

This harness is axis-agnostic by construction: nothing here hardcodes
`axis1..axis8`. It reads whatever `axis_key` strings actually exist in
`analysis_derivation` (see pipeline/query_engine/axis_registry.py for the
identity/governance layer this harness deliberately does not depend on for
correctness -- only for optional human-readable labeling).
"""
from pipeline.axis_eval.data_access import (
    connect_readonly,
    fetch_axis_payloads,
    fetch_all_axis_keys,
    fetch_item_truth,
)
from pipeline.axis_eval.m1_reproducibility import measure_reproducibility
from pipeline.axis_eval.m2_discriminative import discriminative_power
from pipeline.axis_eval.m3_redundancy import mutual_information, pairwise_redundancy_matrix
from pipeline.axis_eval.m4_informational_validity import (
    CircularityViolation,
    find_leak_keys,
    find_leak_values,
    guard_non_circular,
    sanitize_payload,
    evaluate_informational_validity,
)
from pipeline.axis_eval.outcome_correlation import correlate_against_estimated_outcomes
from pipeline.axis_eval.scorecard import build_scorecard, score_axis

__all__ = [
    "connect_readonly",
    "fetch_axis_payloads",
    "fetch_all_axis_keys",
    "fetch_item_truth",
    "measure_reproducibility",
    "discriminative_power",
    "mutual_information",
    "pairwise_redundancy_matrix",
    "CircularityViolation",
    "find_leak_keys",
    "find_leak_values",
    "guard_non_circular",
    "sanitize_payload",
    "evaluate_informational_validity",
    "correlate_against_estimated_outcomes",
    "build_scorecard",
    "score_axis",
]
