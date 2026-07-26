# -*- coding: utf-8 -*-
"""Pilot run: item 15 end to end, then re-adjudicate its three claimed precedents.

The answer key is read exactly once, at the very end, to score the acceptance criteria. It is
never on any derivation or solving path -- that is the property AC1 exists to protect and the
one the incumbent analysis failed.
"""
import json
import os
import sqlite3
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, BASE)

from pipeline.query_engine import conclusion_form as cf          # noqa: E402
from pipeline.query_engine import ce_relatedness as rel          # noqa: E402
from pipeline.axis_eval import ce_verification as vb             # noqa: E402

DB = os.path.join(BASE, 'storage', 'parsed_dataset.db')
CUBIC = {'family': 'POLYNOMIAL', 'degree': 3, 'fixed_coefficients': {'c0': 0}}


def node(nid, schema, binding, ambient=CUBIC):
    return cf.Conclusion(schema, binding, ambient, node_id=nid)


# ---- item 15: conclusions derived from the conditions, never from the answer ----------------
N1 = node('N1', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0), 'MULT': ('GROUND', 2)})
N2 = node('N2', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 3), 'MULT': ('GROUND', 1)})
N4 = node('N4', 'EXTREMUM_VALUE', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 2),
                                   'VALUE': ('GROUND', -1), 'KIND': ('GROUND', 'LOCAL_MIN')})
ITEM15 = [N1, N2, N4]

# ---- the three claimed precedents ------------------------------------------------------------
ITEM2021 = [node('P1', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('EXISTENTIAL', 'R'),
                                     'MULT': ('GROUND', 2)}),
            node('P2', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('EXISTENTIAL', 'S'),
                                     'MULT': ('GROUND', 1)})]
ITEM2411 = []          # sequence problem: not expressible in this vocabulary. Not a rejection.
ITEM2506 = [node('Q1', 'AREA_TRIANGLE', {'P1': ('GROUND', 'A'), 'P2': ('GROUND', 'O'),
                                         'P3': ('GROUND', 'B'), 'VALUE': ('GROUND', 16)}, {})]

# Rationale traces. Prose only -- if the answer appears here the leak scan must catch it.
TRACE = [
    ('N1/CONSIDERED', 'Either x=0 or x=3 could be the repeated root of the cubic.'),
    ('N1/REJECTED', 'A repeated root at x=3 forces a negative leading coefficient, which '
                    'contradicts the shift range in the second condition.'),
    ('N1/EVIDENCE', 'The first condition holds for exactly the open interval of shifts of '
                    'length three starting inside the span, which fixes where the sign fails '
                    'to change.'),
    ('N1/UNCERTAINTY', 'Endpoint conventions of the stated open interval were taken as strict.'),
    ('N1/FALSIFIER', 'Recompute the shift range for a cubic with a repeated root elsewhere; if '
                     'it still matches, this node is wrong.'),
    ('N4/EVIDENCE', 'The second condition pins the depth of the dip on the closed span, giving '
                    'the extremum value directly.'),
]

STAGE_EVENTS = [{'stage': 'ce.segmentation'}, {'stage': 'ce.semantics'},
                {'stage': 'ce.relation'}, {'stage': 'VERIFICATION_BARRIER'},
                {'stage': 'ce.canonical'}, {'stage': 'ce.variance'}]


def main():
    out = {}

    # ---- answer read ONLY for scoring, after every derivation is complete -------------------
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    ans = json.loads(conn.execute(
        "SELECT canonical_answer_json FROM question_item WHERE item_id='202606_MATH_DIF_15'"
    ).fetchone()[0])
    conn.close()
    answer_values = [ans['correct_value'], ans.get('correct_option_index')]

    barrier = vb.barrier(ITEM15, CUBIC, target_x=6, answer_values=answer_values,
                         texts=TRACE, events=STAGE_EVENTS)
    out['barrier'] = barrier

    adj = rel.adjudicate('202606_MATH_DIF_15', ITEM15,
                         [('202106_MATH_DIF_22', ITEM2021),
                          ('202411_MATH_DIF_22', ITEM2411),
                          ('202506_MATH_DIF_22', ITEM2506)])
    out['adjudication'] = adj

    recovered = barrier['sufficiency']['value']
    ac = {}
    ac['AC1  no answer-key leak'] = (not barrier['leaks']) and str(recovered) == str(ans['correct_value'])
    ac['AC2  adjudication matches the sealed reference'] = (
        adj['tally'] == {'ACCEPT': 1, 'REJECT': 1, 'UNDECIDED': 0, 'NOT_EXPRESSIBLE': 1})
    ac['AC6  no derived stage before the barrier'] = not vb.stage_order_audit(STAGE_EVENTS)
    ac['AC7  substance anchor: nodes alone recover the target'] = (
        barrier['sufficiency']['status'] == 'DETERMINED'
        and str(recovered) == str(ans['correct_value']))
    stub = vb.barrier([], CUBIC, 6, answer_values)
    ac['AC7b stub set cannot recover'] = stub['sufficiency']['status'] == 'UNDETERMINED'
    ac['AC8a soundness: no node is false'] = all(
        r['verdict'] != 'FALSE' for r in barrier['soundness'])
    ac['AC8b minimality reported'] = bool(barrier['minimality']['minimal_sufficient_subsets'])
    out['acceptance'] = ac
    out['recovered'] = str(recovered)
    out['answer'] = ans
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if all(ac.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
