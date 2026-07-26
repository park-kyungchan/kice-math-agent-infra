# -*- coding: utf-8 -*-
"""
Secondary, CLEARLY WEAK correlation check against the 17 ESTIMATED outcome
values staged by Agent I1 (scratch/staging/I1/outcome_data.json).

This is explicitly NOT the primary M4 measure (informational validity
against the OFFICIAL answer is primary -- see m4_informational_validity.py
and the settled constraint recorded in ROUTING.md / I1's REPORT.txt: KICE
never publishes item-level 정답률, so only 17/1,350 estimates exist, all of
them third-party, all of them "killer item" outliers, none of them
official). Every result this module returns carries that warning verbatim
so it cannot be quoted out of context downstream.
"""
import json
import math
import os
from typing import Any, Callable, Dict, List, Optional

from pipeline.axis_eval.canonicalize import canonical_value

WARNING = (
    "WEAK SIGNAL: n=17/1350 (1.26% of corpus), every value is a 'killer item' "
    "outlier selected because it was newsworthy/hardest, every value is "
    "ESTIMATED (EBSi via news-article citation) and NOT an official KICE "
    "statistic, and estimates are known to disagree across commercial "
    "sources by several points (see scratch/staging/I1/REPORT.txt sec.1.4). "
    "This correlation is insufficient ALONE to accept or reject any axis, "
    "in either direction."
)


def load_estimated_outcomes(outcome_json_path: str) -> Dict[str, float]:
    """Loads {item_id: correct_rate} from I1's staged outcome_data.json,
    skipping the '_meta' key."""
    if not os.path.exists(outcome_json_path):
        return {}
    with open(outcome_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        item_id: entry["correct_rate"]
        for item_id, entry in data.items()
        if item_id != "_meta" and isinstance(entry, dict) and "correct_rate" in entry
    }


def _default_feature_fn(raw_payload: Optional[str]) -> Optional[float]:
    """Generic, axis-agnostic numeric proxy: length of the canonicalized
    JSON payload string. Not a claim of relevance -- just the only feature
    that can be extracted uniformly from an arbitrary axis_key's payload
    without axis-specific knowledge. Returns None for NULL payloads (point
    excluded, not coerced to 0)."""
    if raw_payload is None:
        return None
    return float(len(canonical_value(raw_payload)))


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / math.sqrt(var_x * var_y)


def correlate_against_estimated_outcomes(
    payload_map: Dict[str, Optional[str]],
    outcomes: Dict[str, float],
    feature_fn: Callable[[Optional[str]], Optional[float]] = _default_feature_fn,
) -> Dict[str, Any]:
    xs: List[float] = []
    ys: List[float] = []
    used_item_ids: List[str] = []
    for item_id, correct_rate in outcomes.items():
        if item_id not in payload_map:
            continue
        feat = feature_fn(payload_map[item_id])
        if feat is None:
            continue
        xs.append(feat)
        ys.append(correct_rate)
        used_item_ids.append(item_id)

    n = len(xs)
    if n < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "n": n,
            "reason": f"only {n} of the 17 outcome-labeled items have a non-null payload for this axis",
            "warning": WARNING,
        }

    r = _pearson(xs, ys)
    if r is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "n": n,
            "reason": "zero variance in payload feature or outcome across the available items "
                      "(e.g. all outcome-labeled items share the same placeholder payload)",
            "warning": WARNING,
        }

    return {
        "status": "OK_BUT_WEAK",
        "n": n,
        "item_ids_used": used_item_ids,
        "pearson_r": r,
        "feature": "len(canonical_json_payload)" if feature_fn is _default_feature_fn else "custom",
        "warning": WARNING,
    }
