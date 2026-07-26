# -*- coding: utf-8 -*-
"""
Orchestrates M1-M4 + secondary outcome correlation into one scorecard per
axis_key, applying the mission's core policy (brief sec.3):

    "Where data is placeholder, return INSUFFICIENT_DATA with a reason.
    Do not manufacture a score over placeholder data."

Concretely: M2 (discriminative power) is the gate. It ALWAYS runs and
ALWAYS reports its real numbers (distinct count, entropy, largest bucket
share) -- that is precisely the diagnostic that proves degeneracy, so M2
itself is never suppressed. If M2 says DEGENERATE, this module does NOT
run M4's solver test or M1's reproducibility test against real corpus data
for that axis (there is no "score" to manufacture -- a solver test against
1,347 copies of the same placeholder string is not a measurement, it's
noise dressed as one) and reports INSUFFICIENT_DATA with the M2 finding as
the reason.

M3 (redundancy) is handled differently and is documented separately below,
because the mission explicitly asks for the axis8-is-derived-from-axes1-7
claim to become a number even though axis8 IS degenerate (see
`existence_proof_redundancy`).
"""
import os
from typing import Any, Dict, List, Optional

from pipeline.axis_eval.canonicalize import canonical_value
from pipeline.axis_eval.data_access import (
    connect_readonly,
    fetch_all_axis_keys,
    fetch_axis_payloads,
    fetch_item_truth,
)
from pipeline.axis_eval.m2_discriminative import discriminative_power
from pipeline.axis_eval.m3_redundancy import mutual_information, pairwise_redundancy_matrix
from pipeline.axis_eval.m4_informational_validity import evaluate_informational_validity
from pipeline.axis_eval.outcome_correlation import correlate_against_estimated_outcomes, load_estimated_outcomes

M1_NOT_REINVOCABLE_REASON = (
    "Real axis1..axis8 payloads were produced by an agent-based extraction pipeline "
    "that cannot be re-invoked from this sandbox (no LLM calls available). M1's "
    "reproducibility harness is fully implemented and demonstrated correct on synthetic "
    "deterministic/noisy stub extractors (tests/test_axis_eval.py); it is not applied to "
    "real production data because doing so would require fabricating a second 'run' of an "
    "extraction that never actually happened twice."
)

UNIQUE_ITEMS_202606_15_TRIPLET = {
    "202606_MATH_DIF_15", "202606_MATH_GEO_15", "202606_MATH_PRO_15",
}


def _unique_underlying_items(payload_map: Dict[str, Optional[str]]) -> int:
    """Counts unique underlying items among the non-null rows of a payload
    map, collapsing the known DIF/GEO/PRO common-section replicate triplet
    (items 1-22 are identical text across tracks per ROUTING.md sec.1) down
    to 1. This is a corpus-specific fact, not a general-purpose dedup --
    documented inline rather than hidden in a heuristic."""
    non_null_ids = {iid for iid, v in payload_map.items() if v is not None}
    if non_null_ids and non_null_ids.issubset(UNIQUE_ITEMS_202606_15_TRIPLET):
        return 1
    return len(non_null_ids)


def score_axis(conn, axis_key: str, truth_map: Dict[str, Dict[str, Any]],
               outcomes: Dict[str, float]) -> Dict[str, Any]:
    """Scores a single axis_key end-to-end (M1 status + M2 + M4 + outcome
    correlation). M3 is corpus-wide/pairwise and is computed separately by
    build_scorecard (needs every axis's payload map at once)."""
    payload_map = fetch_axis_payloads(conn, axis_key)
    m2 = discriminative_power(payload_map)

    m1 = {"status": "INSUFFICIENT_DATA", "reason": M1_NOT_REINVOCABLE_REASON}

    if m2.get("degenerate"):
        m4 = {
            "status": "INSUFFICIENT_DATA",
            "reason": f"M2 flagged this axis DEGENERATE ({m2.get('reason')}); "
                      f"refusing to run the M4 solver test over placeholder-dominated data.",
        }
    else:
        m4 = evaluate_informational_validity(payload_map, truth_map)

    outcome_corr = correlate_against_estimated_outcomes(payload_map, outcomes)

    return {
        "axis_key": axis_key,
        "m1_reproducibility": m1,
        "m2_discriminative_power": m2,
        "m4_informational_validity": m4,
        "outcome_correlation_weak_n17": outcome_corr,
        "unique_underlying_items_non_null": _unique_underlying_items(payload_map),
    }


def build_scorecard(db_path: str, i1_outcome_json_path: Optional[str] = None,
                     m3_min_n: int = 5) -> Dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        axis_keys = fetch_all_axis_keys(conn)
        truth_map = fetch_item_truth(conn)
        outcomes = load_estimated_outcomes(i1_outcome_json_path) if i1_outcome_json_path else {}

        payloads_by_axis = {axis: fetch_axis_payloads(conn, axis) for axis in axis_keys}
        unique_items_by_axis = {axis: _unique_underlying_items(payloads_by_axis[axis]) for axis in axis_keys}

        per_axis = {
            axis: score_axis(conn, axis, truth_map, outcomes)
            for axis in axis_keys
        }

        m3_matrix = pairwise_redundancy_matrix(payloads_by_axis, min_n=m3_min_n,
                                                unique_items_by_axis=unique_items_by_axis)
        _annotate_degenerate_side_artifacts(m3_matrix, per_axis)

        m3_existence_proofs = _existence_proof_redundancy_for_degenerate_axes(
            axis_keys, payloads_by_axis, per_axis
        )

        return {
            "db_path": db_path,
            "axis_keys": axis_keys,
            "per_axis": per_axis,
            "m3_redundancy_matrix_corpus_scale": m3_matrix,
            "m3_existence_proofs_for_sparse_axes": m3_existence_proofs,
        }
    finally:
        conn.close()


def _annotate_degenerate_side_artifacts(m3_matrix: Dict[str, Dict[str, Any]],
                                          per_axis: Dict[str, Any]) -> None:
    """Mutates m3_matrix in place: whenever EITHER axis of a pair is
    DEGENERATE per M2, a high normalized_mi is a mathematical artifact
    (bounded above by min(H_a, H_b), which is near-zero for a degenerate
    axis, so normalized_mi = MI/min(H_a,H_b) trivially approaches 1.0
    whenever the degenerate axis's tiny entropy is fully "explained" by
    the other side -- observed on real data: axis1_curriculum (H~0.023
    bits) vs axis2_raw_parsing gives normalized_mi=0.9999+, which reads
    as "99.99% redundant" but is really just "axis1 has almost no
    information to begin with". This annotation prevents that number
    from being quoted as a genuine redundancy finding without the
    caveat attached -- mission #3: do not manufacture a score."""
    # Cells are aliased both ways (matrix[a][b] IS matrix[b][a], same dict
    # object) -- iterate the upper triangle only (sorted axes, i<=j) so
    # each unique pair is annotated exactly once, with names attributed
    # correctly instead of depending on dict-iteration order.
    axes_sorted = sorted(m3_matrix.keys())
    for i, axis_a in enumerate(axes_sorted):
        deg_a = per_axis.get(axis_a, {}).get("m2_discriminative_power", {}).get("degenerate")
        for axis_b in axes_sorted[i:]:
            cell = m3_matrix.get(axis_a, {}).get(axis_b)
            if cell is None or cell.get("status") != "OK":
                continue
            deg_b = per_axis.get(axis_b, {}).get("m2_discriminative_power", {}).get("degenerate")
            if deg_a or deg_b:
                which = []
                if deg_a:
                    which.append(axis_a)
                if deg_b and axis_b != axis_a:
                    which.append(axis_b)
                cell["degenerate_side_artifact_warning"] = (
                    f"{' & '.join(which)} flagged DEGENERATE by M2 -- a high normalized_mi "
                    f"here is a low-entropy-denominator artifact, NOT evidence these axes "
                    f"carry meaningfully overlapping information. Do not quote this pair's "
                    f"normalized_mi as a redundancy finding."
                )


def _existence_proof_redundancy_for_degenerate_axes(axis_keys: List[str],
                                                      payloads_by_axis: Dict[str, Dict[str, Optional[str]]],
                                                      per_axis: Dict[str, Any]) -> Dict[str, Any]:
    """For axes whose only real signal is a handful (<m3_min_n) of non-null
    rows -- axis4/7/8 in the current corpus, each with exactly 3 non-null
    rows that are all the SAME underlying item replicated across tracks --
    the corpus-scale M3 matrix above correctly reports INSUFFICIENT_DATA
    for every pair involving them. That is honest, but it also throws away
    the one thing the mission explicitly asked M3 to quantify: "axis8 is
    just a function of axes 1-7" as a number. This computes that number
    SEPARATELY, restricted to the non-null intersection (n as small as 1-3),
    and labels it as an existence-proof, never as a corpus-scale finding.
    """
    proofs: Dict[str, Any] = {}
    for axis_key in axis_keys:
        payload_map = payloads_by_axis[axis_key]
        non_null_ids = {iid for iid, v in payload_map.items() if v is not None}
        if not non_null_ids or len(non_null_ids) >= 5:
            continue  # not a sparse axis; corpus-scale matrix already covers it meaningfully
        proofs[axis_key] = {}
        for other_key in axis_keys:
            if other_key == axis_key:
                continue
            other_map = payloads_by_axis[other_key]
            filtered_a = {iid: payload_map[iid] for iid in non_null_ids}
            filtered_b = {iid: other_map.get(iid) for iid in non_null_ids}
            res = mutual_information(filtered_a, filtered_b, min_n=1,
                                      unique_items_hint=_unique_underlying_items(filtered_a))
            proofs[axis_key][other_key] = res
    return proofs
