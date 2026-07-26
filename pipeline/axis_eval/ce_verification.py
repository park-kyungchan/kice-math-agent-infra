# -*- coding: utf-8 -*-
"""The verification barrier between conclusion derivation and everything downstream.

WHY A BARRIER EXISTS AT ALL
---------------------------
The one item in this corpus that carried a full analysis turned out to be circular: its
`axis5_traps_verification` payload declared `assert_f6: 27, solvability_status: PASS`, which is
the answer it was handed, asserted back as proof. Nothing downstream could tell the difference,
so a lineage claim built on it inherited the same emptiness -- and two of that item's three
claimed precedents turned out, on reading, to be a sequence problem and an exponential-curve
problem sharing nothing with it.

So the rule is: no conclusion enters convergence, variance or relatedness computation until it
has passed here. This module is what "passed" means.

WHAT IT CHECKS
--------------
  SOUNDNESS    each node checked against the function the OTHER nodes determine -- leave one
               out. Checking a node against a function solved for using that node is circular
               and would pass a fabrication. A node the rest cannot pin down is reported
               UNCHECKED rather than passed.
  SUFFICIENCY  the set determines the target from the nodes and the ambient premises alone,
               with the answer key never on the solving path.
  MINIMALITY   which subsets are minimal and sufficient, which node is the keystone, and which
               node contributes to no minimal subset. A non-contributing node is FLAGGED for
               review, never auto-rejected: redundancy for determination is not falsehood.
  LEAK         the answer never appears in a payload or a rationale trace before the final
               node. Two independent detectors, because the known prior leak in this repository
               passed a name-based scan by hiding in a field called `calculated_value.f_6`.
  STAGE ORDER  nothing derived ran before the barrier it depends on.

HONEST LIMIT ON THE LEAK SCAN
-----------------------------
The value detector covers digits with word boundaries and English number words. It does not
cover every Korean numeral spelling, nor an answer split across tokens, nor one expressed as an
equivalent arithmetic phrase. It raises the cost of leaking; it does not make leaking
impossible. Treat a clean leak scan as evidence, not proof.
"""
import json
import re
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import sympy as sp

from pipeline.query_engine import conclusion_form as cf

_ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
         'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
         'eighteen', 'nineteen']
_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def _english(n: int) -> List[str]:
    """Spellings of a small non-negative integer. Deliberately narrow; see the module docstring."""
    if n < 0 or n > 999:
        return []
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return [_TENS[tens]]
        return [f'{_TENS[tens]}-{_ONES[ones]}', f'{_TENS[tens]} {_ONES[ones]}']
    return []


# --------------------------------------------------------------------------
def _holds(constraint) -> bool:
    """Does a constraint hold once both sides are concrete?

    sympy collapses Eq(0, 0) to BooleanTrue, which has no .lhs -- so a naive lhs/rhs check
    crashes precisely on the constraints that are already decided. Handle the collapsed forms
    explicitly rather than letting an exception read as an unrelated failure.
    """
    if constraint is sp.true:
        return True
    if constraint is sp.false:
        return False
    if isinstance(constraint, sp.Equality):
        return bool(sp.simplify(constraint.lhs - constraint.rhs) == 0)
    return bool(constraint)


def solve_from(nodes: Sequence['cf.Conclusion'], ambient: Dict[str, Any]) -> Optional[sp.Expr]:
    """Recover the function from nodes and ambient premises alone. Returns None when the
    constraints do not pin it down. The answer key is never consulted here."""
    f, coeffs, cons = cf.build_function(ambient)
    eqs = list(cons)
    for node in nodes:
        eqs += node.to_constraints(f)
    for sol in sp.solve(eqs, coeffs, dict=True):
        g = f.subs(sol)
        if g.free_symbols - {cf.X}:
            continue
        if sp.Poly(g, cf.X).degree() != ambient['degree']:
            continue
        return sp.simplify(g)
    return None


def sufficiency(nodes, ambient, target_x) -> Tuple[str, Any]:
    g = solve_from(nodes, ambient)
    if g is None:
        return 'UNDETERMINED', None
    return 'DETERMINED', sp.nsimplify(g.subs(cf.X, target_x))


def soundness(nodes, ambient) -> List[Dict[str, Any]]:
    """Is each node true, checked by LEAVING IT OUT?

    The obvious implementation -- recover the function from the whole set, then check each node
    against it -- is circular: a node is trivially satisfied by a function that was solved for
    using that very node. It would report TRUE for everything, including a fabrication, which is
    exactly the failure mode this barrier exists to prevent.

    So each node is checked against the function the OTHER nodes determine. If they determine
    one and the node does not hold of it, the node is false. If they do not determine one, the
    node is load-bearing and cannot be cross-checked from inside the set: reported UNCHECKED,
    with the reason, rather than quietly passed. For item 15 the keystone N4 lands in exactly
    that state, and saying so is more useful than a green tick that means nothing.
    """
    out = []
    for node in nodes:
        others = [n for n in nodes if n is not node]
        try:
            g = solve_from(others, ambient) if others else None
        except cf.ConclusionError as exc:
            out.append({'node': node.node_id, 'verdict': 'UNCHECKABLE', 'why': str(exc)})
            continue
        if g is None:
            out.append({'node': node.node_id, 'verdict': 'UNCHECKED',
                        'why': 'load-bearing: the remaining nodes do not determine a function to '
                               'check it against, so it cannot be cross-checked from inside the '
                               'set. Needs its derivation or an outside source.'})
            continue
        try:
            holds = all(_holds(c) for c in node.to_constraints(g))
        except cf.ConclusionError as exc:
            out.append({'node': node.node_id, 'verdict': 'UNCHECKABLE', 'why': str(exc)})
            continue
        out.append({'node': node.node_id, 'verdict': 'TRUE' if holds else 'FALSE',
                    'why': 'holds of the function the other nodes determine' if holds
                           else 'does NOT hold of the function the other nodes determine'})
    return out


def minimality(nodes, ambient, target_x) -> Dict[str, Any]:
    ids = [n.node_id for n in nodes]
    minimal: List[set] = []
    for r in range(1, len(nodes) + 1):
        for combo in combinations(nodes, r):
            combo_ids = {n.node_id for n in combo}
            if any(s <= combo_ids for s in minimal):
                continue
            try:
                status, _v = sufficiency(list(combo), ambient, target_x)
            except cf.ConclusionError:
                continue
            if status == 'DETERMINED':
                minimal.append(combo_ids)
    covered = set().union(*minimal) if minimal else set()
    keystone = set.intersection(*minimal) if minimal else set()
    return {
        'minimal_sufficient_subsets': [sorted(s) for s in minimal],
        'keystone': sorted(keystone),
        'non_contributing': sorted(set(ids) - covered),
        'structure': 'disjunctive' if len(minimal) > 1 else 'conjunctive',
    }


def leak_scan(texts: Iterable[Tuple[str, str]], answer_values: Iterable[Any]) -> List[Dict[str, str]]:
    """Two independent detectors over (label, text) pairs.

    (a) NAME  -- a field whose name advertises a computed answer.
    (b) VALUE -- the answer itself, as digits with word boundaries or as an English number word.

    Detector (a) alone is insufficient and this repository has the receipt: a real leak sat in
    `calculated_value.f_6` and passed a name-based scan. Detector (b) alone is insufficient too,
    because a small integer appears innocently everywhere. Both run; both report.
    """
    name_re = re.compile(r'(calculated_value|correct_answer|answer_key|assert_[a-z0-9_]*|'
                         r'correct_value|correct_option)', re.I)
    needles = []
    for v in answer_values:
        s = str(v)
        needles.append(re.compile(rf'(?<![\w.]){re.escape(s)}(?![\w.])'))
        try:
            for word in _english(int(v)):
                needles.append(re.compile(rf'\b{re.escape(word)}\b', re.I))
        except (TypeError, ValueError):
            pass
    findings = []
    for label, text in texts:
        if text is None:
            continue
        for m in name_re.finditer(text):
            findings.append({'detector': 'NAME', 'where': label, 'hit': m.group(0)})
        for rx in needles:
            m = rx.search(text)
            if m:
                findings.append({'detector': 'VALUE', 'where': label, 'hit': m.group(0)})
    return findings


def stage_order_audit(events: Sequence[Dict[str, Any]]) -> List[str]:
    """Nothing derived may run before the barrier it depends on."""
    order = {'ce.segmentation': 1, 'ce.semantics': 2, 'ce.relation': 3,
             'VERIFICATION_BARRIER': 4,
             'ce.canonical': 5, 'ce.variance': 5, 'ce.altgen': 5}
    problems = []
    barrier_at = None
    for i, ev in enumerate(events):
        if ev['stage'] == 'VERIFICATION_BARRIER':
            barrier_at = i
    for i, ev in enumerate(events):
        rank = order.get(ev['stage'])
        if rank is None:
            problems.append(f'unknown stage {ev["stage"]!r}')
            continue
        if rank >= 5:
            if barrier_at is None:
                problems.append(f'{ev["stage"]} ran with no verification barrier recorded')
            elif i < barrier_at:
                problems.append(f'{ev["stage"]} ran before the verification barrier')
    return problems


def barrier(nodes, ambient, target_x, answer_values, texts=(), events=()) -> Dict[str, Any]:
    """Run every check and return a composite verdict.

    A conclusion set passes only if it is sound, sufficient, leak-free and correctly ordered.
    Minimality never fails the barrier -- it reports structure, and a non-contributing node is
    flagged for review, because redundancy is a property of the item, not a defect.
    """
    sound = soundness(nodes, ambient)
    status, value = sufficiency(nodes, ambient, target_x)
    mini = minimality(nodes, ambient, target_x)
    leaks = leak_scan(texts, answer_values)
    order_problems = list(stage_order_audit(events)) if events else []

    failures = []
    for row in sound:
        if row['verdict'] == 'FALSE':
            failures.append(f'unsound node {row["node"]}: {row["why"]}')
    if status != 'DETERMINED':
        failures.append('the node set does not determine the target')
    if leaks:
        failures.append(f'{len(leaks)} answer-key leak finding(s)')
    failures += order_problems

    return {
        'verdict': 'PASS' if not failures else 'FAIL',
        'failures': failures,
        'soundness': sound,
        'sufficiency': {'status': status, 'value': str(value) if value is not None else None},
        'minimality': mini,
        'leaks': leaks,
        'flags': ([f'non-contributing node(s) {mini["non_contributing"]} -- candidate '
                   f'over-derivation, for review, not rejection']
                  if mini['non_contributing'] else []),
    }
