# -*- coding: utf-8 -*-
"""
M3 — Non-redundancy (conditional entropy / mutual information).

mutual_information(payload_map_a, payload_map_b) computes:
  MI(A;B) = H(A) + H(B) - H(A,B)   (bits, over the shared item_id set)
  normalized_mi = MI / min(H(A), H(B))   (0..1; 1.0 == B is a deterministic
                                           function of A or vice versa)

This is the number that turns "axis8 is just a function of axes 1-7" from
a prose claim into a measurement: if axis8's payload is truly derived from
axis1..7's outputs, conditional entropy H(axis8 | axis_k) should be at or
near 0 (normalized_mi near 1.0) for the axis_k it depends on.

HONESTY GUARD: min_n gates every pairwise computation. Below min_n the
function refuses to return a redundancy number and returns
status=INSUFFICIENT_DATA instead -- this matters a great deal for this
corpus because axis4/7/8 have exactly 3 non-NULL rows, and those 3 rows are
NOT three independent samples: they are the SAME underlying item (202606
item 15) replicated across the DIF/GEO/PRO tracks (items 1-22 are common
across tracks per ROUTING.md sec.1), i.e. n_unique_underlying_items=1. Any
MI/entropy number computed on n=3 is reported with n AND a unique_items_note
so it is never mistaken for a corpus-scale finding.
"""
from typing import Any, Dict, List, Optional

from pipeline.axis_eval.canonicalize import canonical_value, shannon_entropy_bits

DEFAULT_MIN_N = 5


def mutual_information(payload_map_a: Dict[str, Optional[str]],
                        payload_map_b: Dict[str, Optional[str]],
                        min_n: int = DEFAULT_MIN_N,
                        unique_items_hint: Optional[int] = None) -> Dict[str, Any]:
    common_ids = sorted(set(payload_map_a) & set(payload_map_b))
    n = len(common_ids)
    if n < min_n:
        return {
            "status": "INSUFFICIENT_DATA",
            "n": n,
            "reason": f"only {n} shared item_ids (< min_n={min_n}); refusing to compute a redundancy score",
        }

    a_vals = [canonical_value(payload_map_a[i]) for i in common_ids]
    b_vals = [canonical_value(payload_map_b[i]) for i in common_ids]
    joint = list(zip(a_vals, b_vals))

    from collections import Counter
    a_counts = Counter(a_vals)
    b_counts = Counter(b_vals)
    joint_counts = Counter(joint)

    h_a = shannon_entropy_bits(a_counts, n)
    h_b = shannon_entropy_bits(b_counts, n)
    h_joint = shannon_entropy_bits(joint_counts, n)
    mi = h_a + h_b - h_joint
    # Numerical noise can push mi slightly negative/over min(h_a,h_b); clamp.
    mi = max(0.0, min(mi, min(h_a, h_b) if min(h_a, h_b) > 0 else mi))

    denom = min(h_a, h_b)
    if denom > 1e-12:
        normalized_mi = mi / denom
    else:
        normalized_mi = 0.0

    result = {
        "status": "OK",
        "n": n,
        "h_a_bits": h_a,
        "h_b_bits": h_b,
        "h_joint_bits": h_joint,
        "mutual_information_bits": mi,
        "normalized_mi": normalized_mi,
    }
    if denom <= 1e-12:
        result["note"] = (
            "one or both sides are constant on this shared sample (H<=0); "
            "mutual information is trivially ~0 here, which reflects the "
            "absence of measurable variation, NOT independence -- do not "
            "read this as 'these two axes carry different information'."
        )
    if unique_items_hint is not None and unique_items_hint < n:
        result["unique_items_note"] = (
            f"n={n} shared item_ids collapse to only {unique_items_hint} unique "
            f"underlying item(s) (cross-track replicate rows) -- this is an "
            f"existence-proof-scale measurement, not a corpus-scale one."
        )
    return result


def pairwise_redundancy_matrix(payloads_by_axis: Dict[str, Dict[str, Optional[str]]],
                                min_n: int = DEFAULT_MIN_N,
                                unique_items_by_axis: Optional[Dict[str, int]] = None) -> Dict[str, Dict[str, Any]]:
    """{axis_a: {axis_b: mutual_information(...) result}} for every
    unordered pair (diagonal included as a sanity self-check: MI(A;A) should
    equal H(A))."""
    axes = sorted(payloads_by_axis.keys())
    matrix: Dict[str, Dict[str, Any]] = {a: {} for a in axes}
    for i, a in enumerate(axes):
        for b in axes[i:]:
            hint = None
            if unique_items_by_axis is not None:
                ha = unique_items_by_axis.get(a)
                hb = unique_items_by_axis.get(b)
                candidates = [x for x in (ha, hb) if x is not None]
                hint = min(candidates) if candidates else None
            res = mutual_information(payloads_by_axis[a], payloads_by_axis[b], min_n=min_n,
                                      unique_items_hint=hint)
            matrix[a][b] = res
            matrix[b][a] = res
    return matrix
