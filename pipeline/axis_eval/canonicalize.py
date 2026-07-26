# -*- coding: utf-8 -*-
"""
Canonicalization + entropy primitives shared by M1/M2/M3.

Kept dependency-free (stdlib only: json, math, collections) so this harness
runs in the sandbox without numpy/scipy (scipy is NOT installed here --
confirmed by probe; see scratch/staging/I3/REPORT.txt "Environment" section).
"""
import json
import math
from collections import Counter
from typing import Any, Dict, Hashable, List, Optional

NULL_TOKEN = "__NULL__"


def canonical_value(raw: Optional[str]) -> str:
    """Canonicalizes a raw `analysis_derivation.payload` cell (a JSON text
    column, or SQL NULL/Python None) into a hashable, order-independent
    string so that two payloads with the same keys in different orders
    compare equal, and NULL is a distinct, explicit bucket (never conflated
    with any real value -- same discipline ROUTING.md already requires for
    canonical_answer_json.correct_value: null means not-extracted, never a
    real value)."""
    if raw is None:
        return NULL_TOKEN
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        # Not valid JSON (shouldn't happen given the `analysis_derivation`
        # CHECK(payload IS NULL OR json_valid(payload)) constraint, but a
        # pluggable-extraction-fn caller could hand us anything) -- fall
        # back to the literal string as its own bucket.
        return f"__UNPARSEABLE__:{raw}"
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def canonical_repr(value: Any) -> str:
    """Canonicalizes an arbitrary in-memory Python value (e.g. the return
    value of a pluggable M1 extraction_fn) the same way, without requiring
    it to already be a JSON string."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return repr(value)


def value_counts(values: List[Hashable]) -> Counter:
    return Counter(values)


def shannon_entropy_bits(counts: Dict[Hashable, int], n: Optional[int] = None) -> float:
    """H(X) in bits over the empirical distribution implied by `counts`."""
    if n is None:
        n = sum(counts.values())
    if n == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / n
        h -= p * math.log2(p)
    return h
