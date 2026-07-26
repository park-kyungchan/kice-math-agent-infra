# Pilot result — 202606_MATH_DIF_15 and its three claimed precedents
Run 2026-07-26. Raw output: `PILOT_RAW.json`. Reference sealed and hashed before execution:
`ADJUDICATION_REFERENCE.md` (sha256 4139bc0f1192…), so the adjudication was scored against
evidence written down in advance rather than against its own output.

## The barrier
```
verdict     PASS, no failures
soundness   N1 TRUE   N2 TRUE   N4 UNCHECKED
minimality  minimal sufficient subsets {N1,N4} and {N2,N4}; keystone N4; non-contributing none
leaks       none
recovered   f(6) = 27, from the nodes and the ambient premises alone
```
`N4 UNCHECKED` is the honest answer, not a gap in the run. Soundness is checked by leaving each
node out and testing it against the function the others determine; N4 is the keystone, so the
others determine nothing without it and it cannot be cross-checked from inside the set. A green
tick there would have meant nothing. Establishing N4 needs its derivation or an outside source,
and the run says so rather than implying otherwise.

## The adjudication
| claimed precedent | verdict | basis |
|---|---|---|
| 202106_MATH_DIF_22 | ACCEPT | IMPLIES on ROOT_MULT — item 15's ground double root implies 2021-06's existential one |
| 202411_MATH_DIF_22 | NOT_EXPRESSIBLE | a sequence problem; the vocabulary has no sort for integer recurrences, so the claim can be neither confirmed nor refuted here |
| 202506_MATH_DIF_22 | REJECT | its conclusions are about points and areas, item 15's about a function's roots and extremum; no structural sort in common |

Two of the three inherited claims did not survive. That is the mechanism working. The one that
did survive was, in the incumbent data, justified by a sentence describing an absolute-value
integral that the precedent item does not contain — a defensible edge with an indefensible
reason, which is a distinction only a derivation can draw.

`NOT_EXPRESSIBLE` is deliberately not folded into `REJECT`. "We looked and found no shared
conclusion" and "this item cannot be stated in our vocabulary at all" are different facts, and
collapsing them would let a coverage gap masquerade as a finding about mathematics.

## Acceptance criteria
```
PASS  AC1   no answer-key leak, name and value detectors, prose included
PASS  AC2   adjudication matches the sealed reference exactly
PASS  AC6   no derived stage ran before the verification barrier
PASS  AC7   substance anchor: the nodes alone recover the target
PASS  AC7b  a fabricated stub set recovers nothing
PASS  AC8a  soundness: no node is false
PASS  AC8b  minimality reported, with keystone and non-contributing nodes
```
AC7b is the one that mattered most. Spec section 20.1 made it the first thing to run, because an
independent reviewer had demonstrated a complete path to satisfying every acceptance criterion
with fabricated stub content. A stub set now recovers nothing, so that path is closed.

Not scored here: AC3 (rationale gates) and AC5 (owner verdict). AC3 needs the ledger populated
from a real agent run rather than from the hand-authored trace used to exercise the leak scan;
AC5 is the owner's to give and cannot be self-awarded.

## What the pilot did not prove
- The vocabulary is exercised on one polynomial item. Its exponential predicates are specified
  and hand-verified but never ran through the translator, and its sequence coverage is absent.
- The lemma library has two entries. Its behaviour as it grows is untested.
- The relatedness graph has three edges. Hub explosion is a measured risk (thirty distinct items
  mention a cubic) that the background-constraint rule is designed to prevent, and that design
  has not yet met a corpus.
