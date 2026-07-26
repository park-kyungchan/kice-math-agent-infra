# -*- coding: utf-8 -*-
"""
M2 — Discriminative power.

Given {item_id: raw_payload} for one axis_key, computes:
  - distinct: number of distinct canonical payload values (NULL is its own
    bucket, never conflated with a real value)
  - normalized_entropy: Shannon entropy of the payload distribution,
    normalized to [0, 1] by dividing by log2(distinct) (0 when distinct<=1)
  - largest_bucket_share: the single most common value's share of all items
  - degenerate: bool, True when the axis carries near-zero real signal

DEGENERATE THRESHOLD (documented, not hidden): distinct <= 2, OR
largest_bucket_share >= 0.5. This is deliberately generous (a genuinely
healthy 1,350-item axis should have far more than 2 distinct values and no
single value anywhere near half the corpus) so that it cannot accidentally
flag a borderline-healthy axis while still cleanly catching the known
degenerate case. Verified on real data (scratch/staging/I3/REPORT.txt):
  axis1_curriculum:   distinct=2,   largest_bucket_share=0.9978 -> DEGENERATE
  axis2_raw_parsing:  distinct=690, largest_bucket_share=0.0022 -> OK
"""
import math
from collections import Counter
from typing import Any, Dict, Optional

from pipeline.axis_eval.canonicalize import canonical_value, shannon_entropy_bits

DEGENERATE_DISTINCT_MAX = 2
DEGENERATE_SHARE_MIN = 0.5


def discriminative_power(payload_map: Dict[str, Optional[str]]) -> Dict[str, Any]:
    n = len(payload_map)
    if n == 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": "no items supplied",
            "n": 0,
        }

    values = [canonical_value(v) for v in payload_map.values()]
    counts = Counter(values)
    distinct = len(counts)
    entropy = shannon_entropy_bits(counts, n)
    max_entropy = math.log2(distinct) if distinct > 1 else 0.0
    normalized_entropy = (entropy / max_entropy) if max_entropy > 0 else 0.0
    top_value, top_count = counts.most_common(1)[0]
    largest_bucket_share = top_count / n

    degenerate = (distinct <= DEGENERATE_DISTINCT_MAX) or (largest_bucket_share >= DEGENERATE_SHARE_MIN)

    return {
        "status": "DEGENERATE" if degenerate else "OK",
        "n": n,
        "distinct": distinct,
        "entropy_bits": entropy,
        "normalized_entropy": normalized_entropy,
        "largest_bucket_share": largest_bucket_share,
        "largest_bucket_preview": top_value[:120],
        "degenerate": degenerate,
        "reason": (
            f"distinct={distinct} (threshold <= {DEGENERATE_DISTINCT_MAX}) or "
            f"largest_bucket_share={largest_bucket_share:.4f} (threshold >= {DEGENERATE_SHARE_MIN})"
            if degenerate else ""
        ),
    }
