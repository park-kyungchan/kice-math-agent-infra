"""W0 — AC7/AC8 teeth probe.

Given a set of conclusion nodes plus ambient premises, attempt to determine the target value
by symbolic solving alone. The item's answer never appears on the solving path; it is read from
the database only at the comparison step.
"""
import json, sqlite3, sys
import sympy as sp

X = sp.Symbol('x')

def build_function(ambient):
    """Ambient premises fix the shape of the unknown function."""
    deg = ambient["degree"]
    coeffs = sp.symbols(f'c0:{deg+1}')          # c0 + c1 x + ... + cdeg x^deg
    f = sum(coeffs[i] * X**i for i in range(deg + 1))
    cons = []
    if ambient.get("constant_term") == 0:
        cons.append(sp.Eq(coeffs[0], 0))
    cons.append(sp.Ne(coeffs[deg], 0))           # genuinely of that degree
    return f, list(coeffs), cons

def node_to_constraints(node, f, coeffs):
    """Translate one conclusion node into symbolic constraints. Schema-generic."""
    s, b = node.get("schema"), node.get("binding", {})
    fp, fpp = sp.diff(f, X), sp.diff(f, X, 2)
    if s == "ROOT_MULT":
        x0, m = b["x"], b["mult"]
        c = [sp.Eq(f.subs(X, x0), 0)]
        for k in range(1, m):                    # multiplicity m => first m-1 derivatives vanish
            c.append(sp.Eq(sp.diff(f, X, k).subs(X, x0), 0))
        return c
    if s == "EXTREMUM_VALUE":
        x0, v = b["x"], b["value"]
        return [sp.Eq(fp.subs(X, x0), 0), sp.Eq(f.subs(X, x0), v)]
    if s == "COEFF_SIGN":
        return []                                # inequality: no equality information
    if s == "EVAL":
        return [sp.Eq(f.subs(X, b["x"]), b["value"])]
    if s == "STUB":
        return []
    raise ValueError(f"unknown schema {s}")

def recover(nodes, ambient, target_x):
    f, coeffs, cons = build_function(ambient)
    eqs = [c for c in cons if isinstance(c, sp.Equality)]
    for n in nodes:
        eqs += node_to_constraints(n, f, coeffs)
    sols = sp.solve(eqs, coeffs, dict=True)
    vals = set()
    for s in sols:
        g = f.subs(s)
        if g.free_symbols - {X}:                 # unresolved coefficients remain
            continue
        if sp.simplify(sp.Poly(g, X).degree()) != ambient["degree"]:
            continue                             # degenerate: violates the degree premise
        vals.add(sp.nsimplify(g.subs(X, target_x)))
    if len(vals) == 1:
        return ("DETERMINED", vals.pop())
    return ("UNDETERMINED", sorted(map(str, vals)))

N1 = {"id":"N1","schema":"ROOT_MULT","binding":{"x":0,"mult":2,"sign_change":False}}
N2 = {"id":"N2","schema":"ROOT_MULT","binding":{"x":3,"mult":1,"sign_change":True}}
N3 = {"id":"N3","schema":"COEFF_SIGN","binding":{"coeff":"leading","sign":"POS"}}
N4 = {"id":"N4","schema":"EXTREMUM_VALUE","binding":{"x":2,"kind":"MIN","value":-1}}
N5 = {"id":"N5","schema":"EVAL","binding":{"x":6,"value":None}}   # value filled from DB only in the leak case
STUB = [{"id":f"S{i}","schema":"STUB","binding":{}} for i in range(5)]
AMBIENT = {"degree":3, "constant_term":0}
TARGET_X = 6

def main():
    cases = [
        ("SPEC declared independent set {N1,N2,N4}", [N1,N2,N4]),
        ("FABRICATED stub set (5 stubs)",            STUB),
        ("ablation: drop N1",                        [N2,N4]),
        ("ablation: drop N2",                        [N1,N4]),
        ("ablation: drop N4",                        [N1,N2]),
        ("with entailment N3 added",                 [N1,N2,N3,N4]),
    ]
    rows = []
    for name, nodes in cases:
        status, val = recover(nodes, AMBIENT, TARGET_X)
        rows.append((name, status, val))
        print(f"{status:14s} | {str(val):24s} | {name}")

    con = sqlite3.connect('storage/parsed_dataset.db')
    ans = json.loads(con.execute(
        "SELECT canonical_answer_json FROM question_item WHERE item_id='202606_MATH_DIF_15'"
    ).fetchone()[0])["correct_value"]
    print(f"\n[comparison, read from DB after solving] correct_value = {ans}")

    full = rows[0]; stub = rows[1]
    ac7 = full[1] == "DETERMINED" and int(full[2]) == int(ans) and stub[1] == "UNDETERMINED"
    ablations = rows[2:5]
    ac8 = all(r[1] == "UNDETERMINED" for r in ablations)
    print(f"\nAC7 (real set recovers, stub does not): {'PASS' if ac7 else 'FAIL'}")
    print(f"AC8 (every single-node ablation breaks recovery): {'PASS' if ac8 else 'FAIL'}")
    for r in ablations:
        if r[1] != "UNDETERMINED":
            print(f"   AC8 counterexample -> {r[0]} still recovers {r[2]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())


def minimality_report(nodes, ambient, target_x):
    """Every minimal subset that still determines the target."""
    from itertools import combinations
    suff = []
    for r in range(1, len(nodes) + 1):
        for combo in combinations(nodes, r):
            if any(set(s).issubset({n["id"] for n in combo}) for s in suff):
                continue                                   # not minimal
            status, _ = recover(list(combo), ambient, target_x)
            if status == "DETERMINED":
                suff.append({n["id"] for n in combo})
    return suff
