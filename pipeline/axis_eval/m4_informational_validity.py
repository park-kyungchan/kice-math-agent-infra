# -*- coding: utf-8 -*-
"""
M4 — Informational validity, tested against the OFFICIAL ANSWER (never
per-item 정답률, which is unobtainable at corpus scale -- settled constraint,
see ROUTING.md and scratch/staging/I1/REPORT.txt).

Question: given ONLY an axis's payload -- never the raw question text,
never the answer, never a payload field restating the answer -- can a
solver recover `question_item.answer` / `canonical_answer_json` better than
chance?
  - MULTIPLE_CHOICE (945 items): chance = 1/5 (fixed, per brief).
  - SHORT_ANSWER (405 items): chance = empirical mode frequency / n (NOT
    assumed uniform -- see `short_answer_chance_baseline`).

NON-CIRCULARITY -- THE CORE OF THIS MODULE
-------------------------------------------
This repo has a documented history of circular solver "proofs"
(pipeline/query_engine/independent_solver.py's own IndependentSolverEngine
falls back to literally returning `item.get("answer")` as its "calc_value"
whenever SymPy parsing fails -- confirmed by direct code read, see
independent_solver.py lines ~86-105). Verified empirically in this pass:
even the mission's own known-good anchors (202606_MATH_DIF_15,
202109_MATH_DIF_07) with fully-repaired latex_content and the answer
correctly stripped return NOT_RUN from that solver -- i.e. its apparent
"success" in this repo's history was ENTIRELY the circular fallback, not
real solving power. See scratch/staging/I3/REPORT.txt for the transcript.

This module therefore:
  1. NEVER passes `answer`, `canonical_answer_json`, `solved_answer`, or any
     axis field matching a name- or value-based leak pattern into the
     solver's input (`guard_non_circular` / `sanitize_payload` below).
  2. Re-verifies the guard on the EXACT dict handed to
     IndependentSolverEngine.solve_item (defense in depth: even if
     sanitize_payload is skipped, guard_non_circular(strict=True) raises).
  3. Compares the solver's output against the true answer OUTSIDE the
     solver's input path -- the true answer is only ever visible to the
     scoring function, never smuggled into the item dict solve_item sees.

tests/test_axis_eval.py includes a test built directly from this corpus's
own real leak case (axis5_traps_verification's 3 real rows literally
contain `{"correct_option": 4, "correct_answer_value": 27, ...}` -- read
directly off /tmp/eval.db during this pass) and axis3's less obvious leak
(`{"calculated_value": {"f_6": 27}}`, where 27 IS the correct_value for
that item) to prove the guard actually catches real leaks, not just
contrived ones.
"""
import copy
import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from pipeline.query_engine.independent_solver import IndependentSolverEngine

# --- leak detection -----------------------------------------------------

# Name-based: any dict key (at any depth) matching this pattern is assumed
# to restate the answer and is never allowed into solver input.
_LEAK_KEY_PATTERN = re.compile(
    r"(answer|correct_value|correct_option|solved_answer|ground_truth|is_correct|correct_rate)",
    re.IGNORECASE,
)

# Value-based secondary check: a key merely *hinting* at being a computed
# final quantity (broader net than the name pattern above), combined with a
# leaf value that numerically matches the item's true answer/value. This is
# what catches axis3_symbolic_modeling's real leak
# ({"calculated_value": {"f_6": 27}} where 27 is the true correct_value) --
# "calculated_value" does not match _LEAK_KEY_PATTERN but does match this
# broader hint pattern, and only fires when the leaf value also matches the
# true answer, so it does not blanket-forbid legitimate numeric fields.
_VALUE_HINT_KEY_PATTERN = re.compile(
    r"(value|result|calc|final|solve|answer)", re.IGNORECASE,
)


class CircularityViolation(Exception):
    """Raised when a payload destined for the solver still contains a
    field that names or restates the official answer."""


def _walk(obj: Any, path: str = "$"):
    """Yields (path, key_or_None, value) for every scalar leaf and every
    dict key encountered, depth-first."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield (f"{path}.{k}", k, v)
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    # scalars yield nothing further (already yielded by the parent dict, if any)


def find_leak_keys(payload: Any) -> List[str]:
    """Returns dotted paths of every key matching the name-based leak
    pattern, anywhere in the payload."""
    hits = []
    for path, key, _value in _walk(payload):
        if key is not None and _LEAK_KEY_PATTERN.search(key):
            hits.append(path)
    return hits


def _numeric_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def find_leak_values(payload: Any, true_value: Optional[Any] = None,
                      true_option_index: Optional[Any] = None) -> List[str]:
    """Returns dotted paths of leaf values that (a) sit somewhere under a
    key (itself OR any ancestor) hinting at a computed/final quantity, AND
    (b) numerically match the item's true correct_value or true option
    index. Requires BOTH conditions so this does not blanket-flag every
    coincidental small integer (e.g. MC option indices 1-5 are common,
    unrelated integers elsewhere in a payload).

    Checks the FULL dotted path (not just the immediate leaf key) against
    the hint pattern -- this is what catches axis3_symbolic_modeling's real
    leak `{"calculated_value": {"f_6": 27}}`: the leaf key is "f_6" (no
    hint), but its parent key "calculated_value" does hint, and 27 IS that
    item's true correct_value."""
    hits = []
    targets = [t for t in (true_value, true_option_index) if t is not None]
    if not targets:
        return hits
    for path, _key, value in _walk(payload):
        if isinstance(value, (dict, list)):
            continue
        if not _VALUE_HINT_KEY_PATTERN.search(path):
            continue
        for t in targets:
            if _numeric_equal(value, t):
                hits.append(path)
                break
    return hits


def guard_non_circular(payload_for_solver: Any, true_value: Optional[Any] = None,
                        true_option_index: Optional[Any] = None,
                        strict: bool = True) -> Dict[str, Any]:
    """The explicit non-circularity guard. With strict=True (the default,
    and the mode used on the actual solver-input path), raises
    CircularityViolation the instant any leak is found -- this is the
    "test that fails if the answer leaks in" the mission requires; see
    tests/test_axis_eval.py::test_guard_raises_on_real_axis5_leak and
    ::test_guard_raises_on_real_axis3_leak."""
    name_leaks = find_leak_keys(payload_for_solver)
    value_leaks = find_leak_values(payload_for_solver, true_value, true_option_index)
    leaked = bool(name_leaks or value_leaks)
    if leaked and strict:
        raise CircularityViolation(
            f"answer leak detected before solver call: name_leaks={name_leaks} value_leaks={value_leaks}"
        )
    return {"leaked": leaked, "name_leaks": name_leaks, "value_leaks": value_leaks}


def sanitize_payload(payload: Any, true_value: Optional[Any] = None,
                      true_option_index: Optional[Any] = None) -> Tuple[Any, Dict[str, Any]]:
    """Deep-copies payload and strips every leaking key (name- and
    value-based), returning (clean_payload, stripped_report). Used ahead of
    guard_non_circular(strict=True) so the normal path degrades to
    "nothing leaked" rather than raising -- the raise path is reserved for
    proving the guard works and for defense-in-depth if sanitize is ever
    bypassed."""
    clean = copy.deepcopy(payload)
    # Computed on the ORIGINAL (pre-mutation) payload; deep copy preserves
    # identical structure/paths so these paths remain valid against `clean`.
    name_leaks = find_leak_keys(payload)
    value_leaks = find_leak_values(payload, true_value, true_option_index)
    value_leak_paths = set(value_leaks)

    def _strip(obj, path):
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                child_path = f"{path}.{k}"
                if _LEAK_KEY_PATTERN.search(k):
                    del obj[k]
                    continue
                v = obj[k]
                if isinstance(v, (dict, list)):
                    _strip(v, child_path)
                elif child_path in value_leak_paths:
                    del obj[k]
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                child_path = f"{path}[{i}]"
                if isinstance(v, (dict, list)):
                    _strip(v, child_path)
                elif child_path in value_leak_paths:
                    # Cannot delete a list element in place without shifting
                    # every later index (which would silently corrupt any
                    # OTHER path reference); null it out instead so the
                    # leaking value is gone but structure/length is stable.
                    obj[i] = None

    _strip(clean, "$")
    return clean, {"name_leaks_stripped": name_leaks, "value_leaks_stripped": value_leaks}


# --- solver wrapper -------------------------------------------------------

def build_solver_item(sanitized_axis_payload: Any) -> Dict[str, Any]:
    """Maps a SANITIZED axis payload into the shape
    IndependentSolverEngine.solve_item expects, without ever setting
    'answer', 'axes', or 'solved_answer'.

    Deliberately does NOT read question_item.latex_content (the canonical,
    repaired raw question text) -- that would violate "never the raw
    question text". The one exception: if the axis payload ITSELF carries a
    text-shaped field (this is axis2_raw_parsing's case -- its payload IS
    the axis's own literal parse of the item, under key "condition"), that
    field is passed through as-is, because it is not an ADDITIONAL raw-text
    channel bolted on top of the axis payload -- it *is* the axis payload.
    Passing axis2's payload alone (nothing else) is the fairest possible
    test of what axis2 specifically contributes.
    """
    text_field = ""
    if isinstance(sanitized_axis_payload, dict):
        for candidate_key in ("condition", "text", "content", "latex"):
            v = sanitized_axis_payload.get(candidate_key)
            if isinstance(v, str) and v.strip():
                text_field = v
                break
    return {"latex_content": text_field}


def solve_axis_payload(raw_payload: Optional[str], true_value: Optional[Any],
                        true_option_index: Optional[Any]) -> Dict[str, Any]:
    """End-to-end guarded solve for one item's one-axis payload. Returns the
    IndependentSolverEngine result dict plus a `_leak_report` key."""
    if raw_payload is None:
        return {"execution_status": "NOT_RUN", "calc_value": None,
                "reason": "null payload", "_leak_report": None}
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return {"execution_status": "NOT_RUN", "calc_value": None,
                "reason": "payload not valid JSON", "_leak_report": None}

    clean, leak_report = sanitize_payload(payload, true_value, true_option_index)
    guard_non_circular(clean, true_value, true_option_index, strict=True)

    solver_item = build_solver_item(clean)
    guard_non_circular(solver_item, true_value, true_option_index, strict=True)

    result = IndependentSolverEngine().solve_item(solver_item)
    result = dict(result)
    result["_leak_report"] = leak_report
    return result


# --- chance baselines ------------------------------------------------------

MC_CHANCE = 0.20  # fixed per brief: 1/5 for the 945 MULTIPLE_CHOICE items


def short_answer_chance_baseline(true_values: List[Any]) -> Dict[str, Any]:
    """Empirical "always guess the mode" baseline for SHORT_ANSWER items --
    per brief, do NOT assume uniform (the true value space is open-ended
    integers, not a fixed 5-way choice)."""
    counts = Counter(str(v) for v in true_values if v is not None)
    n = sum(counts.values())
    if n == 0:
        return {"n": 0, "mode_value": None, "mode_count": 0, "chance": 0.0}
    mode_value, mode_count = counts.most_common(1)[0]
    return {"n": n, "mode_value": mode_value, "mode_count": mode_count, "chance": mode_count / n}


# --- top-level M4 evaluation ------------------------------------------------

def evaluate_informational_validity(payload_map: Dict[str, Optional[str]],
                                     truth_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Runs the guarded solver over every item's payload for one axis and
    scores recovery of the official answer vs. chance, split by
    response_type. Never called on a DEGENERATE axis by the scorecard
    (mission #3: do not manufacture a score over placeholder data) -- this
    function itself has no placeholder-awareness; that policy lives in
    scorecard.py, which decides whether to call this at all.
    """
    mc_scoreable = 0
    mc_correct = 0
    mc_not_scoreable = 0
    sa_scoreable = 0
    sa_correct = 0
    sa_not_run = 0
    mc_not_run = 0
    sa_true_values = []

    per_item_detail: Dict[str, Any] = {}

    for item_id, truth in truth_map.items():
        raw_payload = payload_map.get(item_id)
        response_type = truth.get("response_type")
        true_value = truth.get("correct_value")
        true_option_index = truth.get("correct_option_index")
        true_answer = truth.get("answer")

        if response_type == "SHORT_ANSWER":
            sa_true_values.append(true_answer)

        result = solve_axis_payload(raw_payload, true_value, true_option_index)
        status = result.get("execution_status")
        calc_value = result.get("calc_value")

        if response_type == "MULTIPLE_CHOICE":
            if true_value is None:
                mc_not_scoreable += 1
                per_item_detail[item_id] = {"status": "NOT_SCOREABLE_LATEX_OPTION"}
                continue
            if status != "PASS" or calc_value is None:
                mc_not_run += 1
                per_item_detail[item_id] = {"status": status}
                continue
            mc_scoreable += 1
            if _values_match(calc_value, true_value):
                mc_correct += 1
            per_item_detail[item_id] = {"status": status, "calc_value": calc_value, "true_value": true_value}
        elif response_type == "SHORT_ANSWER":
            if status != "PASS" or calc_value is None:
                sa_not_run += 1
                per_item_detail[item_id] = {"status": status}
                continue
            sa_scoreable += 1
            if _values_match(calc_value, true_answer):
                sa_correct += 1
            per_item_detail[item_id] = {"status": status, "calc_value": calc_value, "true_value": true_answer}

    sa_baseline = short_answer_chance_baseline(sa_true_values)

    return {
        "status": "OK",
        "mc": {
            "n_total": mc_scoreable + mc_not_scoreable + mc_not_run,
            "n_scoreable": mc_scoreable,
            "n_not_scoreable_latex_option": mc_not_scoreable,
            "n_solver_not_run": mc_not_run,
            "n_correct": mc_correct,
            "recovery_rate_of_scoreable": (mc_correct / mc_scoreable) if mc_scoreable else None,
            "recovery_rate_of_all_mc": mc_correct / (mc_scoreable + mc_not_scoreable + mc_not_run)
                if (mc_scoreable + mc_not_scoreable + mc_not_run) else None,
            "chance": MC_CHANCE,
            "beats_chance": (mc_correct / (mc_scoreable + mc_not_scoreable + mc_not_run)) > MC_CHANCE
                if (mc_scoreable + mc_not_scoreable + mc_not_run) else None,
        },
        "short_answer": {
            "n_total": sa_scoreable + sa_not_run,
            "n_scoreable": sa_scoreable,
            "n_solver_not_run": sa_not_run,
            "n_correct": sa_correct,
            "recovery_rate_of_scoreable": (sa_correct / sa_scoreable) if sa_scoreable else None,
            "recovery_rate_of_all_sa": sa_correct / (sa_scoreable + sa_not_run) if (sa_scoreable + sa_not_run) else None,
            "chance_baseline": sa_baseline,
            "beats_chance": (sa_correct / (sa_scoreable + sa_not_run)) > sa_baseline["chance"]
                if (sa_scoreable + sa_not_run) else None,
        },
        "note": (
            "MC 'chance' is the brief's fixed 1/5 option-index model; this harness actually tests "
            "recovery of the numeric correct_value quantity (available for 555/945 MC items per "
            "ROUTING.md), not the option letter itself, because no plain-text option-value table "
            "exists in this corpus for the 390 LaTeX-expression-option MC items -- see "
            "scratch/staging/I3/REPORT.txt limitations section for the full caveat."
        ),
    }


def _values_match(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) < tol
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()
