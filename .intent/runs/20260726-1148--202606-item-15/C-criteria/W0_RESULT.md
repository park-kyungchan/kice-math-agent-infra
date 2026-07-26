# W0 result — AC7/AC8 teeth probe
Run 2026-07-26. Probe: `w0_ac7_probe.py`. Solving path verified free of the answer literal
(`grep 27` on the probe returns nothing); the answer is read from the database only for comparison,
after solving. Method: ambient premises fix f as a degree-3 polynomial with zero constant term;
each conclusion node is translated to symbolic constraints by a schema-generic translator; sympy
solves for the coefficients; f(6) is evaluated only if the coefficients are fully pinned.

## Results

| case | outcome | f(6) |
|---|---|---|
| declared independent set {N1,N2,N4} | DETERMINED | 27 |
| fabricated stub set (5 stubs) | UNDETERMINED | — |
| ablation: drop N1 | DETERMINED | 27 |
| ablation: drop N2 | DETERMINED | 27 |
| ablation: drop N4 | UNDETERMINED | — |
| with entailment N3 added | DETERMINED | 27 |

Database comparison after solving: `canonical_answer_json.correct_value` = 27.

## AC7 — PASS. The substance anchor has teeth.
The real node set recovers the answer; the fabricated stub set recovers nothing. A stubbed pipeline
cannot pass AC7. This discharges the principal residual risk recorded in spec section 20.1: the
gaming path demonstrated during verification is closed by AC7 as written.

## AC8 — FAIL. The criterion is malformed, not the node set.
AC8 requires that deleting any one independent node breaks recovery. Two counterexamples: dropping
N1 still recovers 27, and dropping N2 still recovers 27.

Minimal sufficient subsets, computed exhaustively over {N1,N2,N3,N4}:

    {N1, N4}   and   {N2, N4}
    keystone (present in every minimal subset): N4
    non-contributing (present in no minimal subset): N3

The logical structure is therefore `N4 AND (N1 OR N2)` — disjunctive. A flat node set cannot express
it, and AC8 silently assumed a minimal conjunctive basis that does not exist for this item.

## Root cause of the AC8 defect
The spec conflated two different properties:
  - the STOPPING RULE tests whether a node is an independently falsifiable FACT;
  - AC8 tests whether a node is NECESSARY to determine the target.
A fact can be true, independently meaningful, and still redundant for determination. Redundancy is
not the same as non-independence. AC8 tested the second property while the granularity rule that
produced the node set tested the first.

## Analytical significance — this is content, not noise
The redundancy is a property of the item, not an artefact. The exam writer over-determined the
problem: a solver may reach f through the double root at 0, or through the simple root at 3, both
in combination with the local minimum. That is precisely the multiple-encodings-one-conclusion
structure the axis exists to capture, appearing one level up — multiple conclusion routes to the
same determination. Recording it is valuable; requiring it not to exist was the error.

## Proposed replacement, requiring owner approval (reopens gate C1)
Retire AC8 and replace with:
  AC8a SOUNDNESS  — every node in the set is independently verified true against the item, node by
                    node, not merely the set as a whole.
  AC8b MINIMALITY — the minimal sufficient subsets are computed and recorded, together with the
                    keystone nodes and any non-contributing node. A node in no minimal sufficient
                    subset is FLAGGED as a candidate over-derivation for review; it is not
                    automatically rejected, because it may still be a true and useful fact.

Under this replacement the item-15 pilot yields: keystone N4; alternative routes N1 and N2; N3
flagged non-contributing, which is consistent with the spec already classifying N3 as an entailment
rather than a node.
