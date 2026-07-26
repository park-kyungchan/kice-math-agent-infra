# -*- coding: utf-8 -*-
"""
M1 — Reproducibility.

Runs a pluggable extraction_fn(item_id) -> Any twice per item and measures
agreement. Accepts ANY callable, so the same harness can (a) be demonstrated
on synthetic stub extractors (this module's own tests) or (b) be pointed at
a real, deterministic-in-this-sandbox extraction step in the future (e.g. a
pure-Python re-parse of raw_dataset text), the moment one exists.

HONESTY NOTE (see scratch/staging/I3/REPORT.txt "M1" section): this repo's
real axis1..axis8 payloads were produced by an agent-based pipeline that is
NOT re-invocable from this sandbox (no LLM calls available here). M1 is
therefore demonstrated on synthetic stubs only, per the mission brief's
explicit instruction ("demonstrate on a deterministic stub and a
deliberately noisy stub") -- it is NOT run against the 8 real axes, and the
scorecard reports that honestly as INSUFFICIENT_DATA / NOT_RE-INVOCABLE
rather than fabricating a reproducibility number for real axis production.
"""
import random
from typing import Any, Callable, Dict, List

from pipeline.axis_eval.canonicalize import canonical_repr


def measure_reproducibility(item_ids: List[str],
                             extraction_fn: Callable[[str], Any]) -> Dict[str, Any]:
    """Runs extraction_fn(item_id) twice per item_id and reports agreement.

    Returns:
        {
          "n_items": int,
          "n_agree": int,
          "n_disagree": int,
          "agreement_rate": float,
          "disagreeing_item_ids": [item_id, ...],
        }
    """
    disagreeing: List[str] = []
    n_agree = 0
    for item_id in item_ids:
        run1 = extraction_fn(item_id)
        run2 = extraction_fn(item_id)
        if canonical_repr(run1) == canonical_repr(run2):
            n_agree += 1
        else:
            disagreeing.append(item_id)
    n = len(item_ids)
    return {
        "n_items": n,
        "n_agree": n_agree,
        "n_disagree": len(disagreeing),
        "agreement_rate": (n_agree / n) if n else 0.0,
        "disagreeing_item_ids": disagreeing,
    }


# ---------------------------------------------------------------------------
# Stub extractors used by tests/test_axis_eval.py to demonstrate M1 itself
# is correct, per the mission brief's explicit requirement.
# ---------------------------------------------------------------------------

def deterministic_stub_extractor(item_id: str) -> Dict[str, int]:
    """A pure function of item_id -- same input always yields the same
    output. Expected M1 result: agreement_rate == 1.0, zero disagreements."""
    return {"value": sum(ord(c) for c in item_id) % 5}


def noisy_stub_extractor(item_id: str) -> Dict[str, int]:
    """Deliberately non-deterministic (ignores item_id, draws fresh
    randomness every call) -- models a flaky/non-reproducible extraction
    step. Expected M1 result: agreement_rate well below 1.0 (converges to
    the chance of two independent draws from the same 5-way distribution
    landing on the same value, 1/5 = 0.20, for a large enough sample)."""
    return {"value": random.randint(0, 4)}
