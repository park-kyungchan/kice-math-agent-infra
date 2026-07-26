# -*- coding: utf-8 -*-
"""Relatedness between exam items, derived rather than authored.

THE CLAIM THIS IMPLEMENTS
-------------------------
If conclusions are the analytical unit, two items are related because they share a conclusion --
even when their surface conditions look nothing alike. Lineage stops being a separately authored
axis and becomes a query. That is the whole reason the redesign is worth doing.

THE CLAIM WAS TESTED BEFORE IT WAS BUILT, AND IT FALSIFIED THE INCUMBENT
-----------------------------------------------------------------------
The incumbent `axis6_genealogy` asserted three precedents for 202606_MATH_DIF_15. Reading them:
202411_MATH_DIF_22 is a sequence problem and 202506_MATH_DIF_22 is an exponential-curve problem;
neither shares a conclusion with a cubic. Only 202106_MATH_DIF_22 survives, and even its stored
justification text described an integral the item does not contain. A conclusion-sharing model
run honestly rejects two of the three. That is the mechanism working, not failing.

HUB EXPLOSION, AND THE THING THAT PREVENTS IT
---------------------------------------------
Thirty distinct items in this corpus mention a cubic function. If "both involve a cubic" counted
as a shared conclusion, those thirty would collapse into one meaningless clique and the graph
would say nothing. The defence is structural rather than a tuned threshold: a premise that types
the unknown is ambient typing, and a premise that constrains without discriminating is a
BACKGROUND_CONSTRAINT relation. Neither is a conclusion, so neither can carry an edge.

WHAT AN EDGE MEANS, AND WHAT IT DOES NOT
----------------------------------------
An edge says two items share a specific conclusion, names it, and says how strongly. It does not
say the items are pedagogically similar, equally hard, or that one influenced the other. And an
absent edge is not evidence of unrelatedness while coverage is partial: with most of the corpus
unanalysed, this graph is a map of analysis effort as much as of mathematics. `coverage_note`
carries that caveat with every result so it cannot be quietly dropped.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pipeline.query_engine import conclusion_form as cf

EDGE_STRENGTH = {
    'IDENTICAL': 1.0,
    'EQUIVALENT': 0.9,
    'IMPLIES': 0.6,
    'OVERLAP': 0.3,
}
EDGE_VERDICTS = tuple(EDGE_STRENGTH)


def _is_background(node: 'cf.Conclusion') -> bool:
    """A conclusion carrying no discriminating information cannot carry an edge.

    Concretely: a claim that merely restates the ambient typing. "f is a cubic" is not a
    conclusion about this item, it is the type of the unknown -- and it is exactly the claim
    that would connect thirty unrelated items into one clique.
    """
    return bool(node.binding.get('_background'))


def item_edges(item_a: str, nodes_a: Sequence['cf.Conclusion'],
               item_b: str, nodes_b: Sequence['cf.Conclusion'],
               lemmas: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Every conclusion-level edge between two items, with its evidence."""
    edges = []
    for a in nodes_a:
        if _is_background(a):
            continue
        for b in nodes_b:
            if _is_background(b):
                continue
            verdict, reason = cf.relation(a, b, lemmas)
            if verdict in EDGE_VERDICTS:
                edges.append({
                    'from_item': item_a, 'from_node': a.node_id,
                    'to_item': item_b, 'to_node': b.node_id,
                    'verdict': verdict,
                    'strength': EDGE_STRENGTH[verdict],
                    'shared_conclusion': a.schema,
                    'evidence': reason,
                    'falsified_by': (
                        f'exhibit a function satisfying {a.node_id} but not {b.node_id} '
                        f'(or the reverse for a symmetric verdict)'
                    ),
                })
    return edges


def relate(item_a: str, nodes_a, item_b: str, nodes_b, lemmas=None) -> Dict[str, Any]:
    """Item-level verdict, rolled up from the conclusion-level edges."""
    edges = item_edges(item_a, nodes_a, item_b, nodes_b, lemmas)
    undecided = []
    for a in nodes_a:
        for b in nodes_b:
            if _is_background(a) or _is_background(b):
                continue
            verdict, reason = cf.relation(a, b, lemmas)
            if verdict == 'UNDECIDED':
                undecided.append({'from_node': a.node_id, 'to_node': b.node_id, 'why': reason})

    if edges:
        best = max(edges, key=lambda e: e['strength'])
        related = 'RELATED'
        basis = f'{best["verdict"]} on {best["shared_conclusion"]}'
    elif undecided:
        related = 'UNDECIDED'
        basis = f'{len(undecided)} node pair(s) unresolved; needs review, not a guess'
    else:
        related = 'NOT_RELATED'
        basis = 'no shared conclusion between any pair of non-background nodes'

    return {
        'items': [item_a, item_b],
        'verdict': related,
        'basis': basis,
        'edges': edges,
        'undecided': undecided,
        'coverage_note': (
            'Absence of an edge is not evidence of unrelatedness while corpus coverage is '
            'partial: an unanalysed item cannot be related to anything, so this graph is a map '
            'of analysis effort as much as of mathematics.'
        ),
    }


def adjudicate(subject: str, subject_nodes, claimed: Iterable[Tuple[str, Sequence]],
               lemmas=None) -> Dict[str, Any]:
    """Re-adjudicate a set of previously asserted lineage claims.

    Returns ACCEPT / REJECT / UNDECIDED per claim with its evidence. Rejecting an inherited
    claim is the expected outcome when the claim was never derived in the first place, and
    recording the rejection is more valuable than quietly dropping it.
    """
    results = []
    for other, other_nodes in claimed:
        if not other_nodes:
            # A distinct outcome, deliberately not folded into REJECT. "We looked and found no
            # shared conclusion" and "this item cannot be stated in our vocabulary at all" are
            # different facts, and collapsing them would let a coverage gap masquerade as a
            # finding about mathematics.
            results.append({
                'claimed_precedent': other,
                'verdict': 'NOT_EXPRESSIBLE',
                'basis': 'no conclusion of this item can be stated in the current vocabulary, '
                         'so the claim can be neither confirmed nor refuted here',
                'edges': [],
            })
            continue
        rel = relate(subject, subject_nodes, other, other_nodes, lemmas)
        results.append({
            'claimed_precedent': other,
            'verdict': {'RELATED': 'ACCEPT', 'NOT_RELATED': 'REJECT',
                        'UNDECIDED': 'UNDECIDED'}[rel['verdict']],
            'basis': rel['basis'],
            'edges': rel['edges'],
        })
    tally = {v: sum(1 for r in results if r['verdict'] == v)
             for v in ('ACCEPT', 'REJECT', 'UNDECIDED', 'NOT_EXPRESSIBLE')}
    return {'subject': subject, 'results': results, 'tally': tally}
