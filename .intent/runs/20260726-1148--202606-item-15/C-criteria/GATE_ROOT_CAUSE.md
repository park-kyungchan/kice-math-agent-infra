# Root cause and remedy — the SSoT gate

## Problem definition
The gate returned exit=1 on seven stub-sentinel errors that no one could act on, and the
condition producing them was one the owner had deliberately chosen (retiring seven legacy axes).

## Root cause
`check_axis_stub_sentinels` fused two different questions into one function:

  DETECTION   are this axis's payloads real?          -- a question about DATA
  ESCALATION  should that finding fail the build?     -- a question about CLAIMS

Every other check in the validator detects DRIFT: two declared sources of truth disagreeing.
The stub-sentinel check instead measured data volume against an aspirational threshold and
escalated the result. A completeness ratio is a STATE, not a violation. Escalating state has a
specific consequence: retiring an axis makes the gate red forever (a retired axis will never
reach the threshold -- that is what retirement means), and introducing an axis makes it red on
day one (it starts empty). The only responses left are to lower the threshold or ignore the
gate, and both destroy the signal. A permanently red gate is not a gate.

## Secondary defect found while fixing it
`total` counted ROWS (1,350), not distinct items (690) -- items 1-22 are stored once per
DIF/GEO/PRO track. Every published coverage figure was computed against a denominator that
overstates the corpus, and readers take "3/1350" to mean corpus coverage. It does not.

## Third defect found while fixing it
The gate's check list was hand-maintained in TWO places: `main()` in the validator, and
`_ORIGINAL_CHECKS` in `tools/generate_routing.py`, which mirrors the gate so ROUTING.md can
publish its measured result. Nothing forced them to agree. They diverged the moment a check was
added, and ROUTING.md began publishing a "measured gate result" the gate would not produce --
an audit artefact lying about the audit.

## Remedy
1. DETECTION AND ESCALATION SEPARATED. `check_axis_stub_sentinels` keeps every rule and every
   report line, and by DEFAULT still escalates everything -- so its own tests exercise the
   detector unchanged. Callers that own the build outcome inject a policy. `main()` injects
   `_registry_claims_trustworthy`. Not a weakening: the detector is untouched.
2. ESCALATION REBOUND TO A CLAIM, in `check_axis_status_honesty` (a NEW check, as
   ROUTING.md requires rather than weakening an existing one). It fires on drift between the
   registry's `status` and the data:
     R1 an axis_key carrying real analysis that is registered nowhere
     R2 an axis declared `active` whose real ratio is below threshold
     R3 an axis declared `active` holding no rows at all
   Strictly stronger than what it replaced: R1 and R3 were never detected before.
3. DENOMINATOR MADE HONEST. Row and distinct-item counts are both printed, with a note that a
   row ratio is not a coverage ratio.
4. THE CHECK LIST BECAME DATA. `GATE_CHECKS` is now the one canonical list; the generator
   imports it instead of re-declaring it, so the two cannot drift again.

## Verification
- Gate: exit=0, all ten checks reported.
- New fixtures prove the escalation rule both ways: an `active` axis with placeholder data
  FAILS (R2), an `active` axis with no rows FAILS (R3), an unregistered axis with real data
  FAILS (R1), a healthy `active` axis PASSES, and `deprecated` / `under_review` axes below
  threshold do NOT fail -- the regression this change exists to prevent.
- The pre-existing CLI test was re-pinned from "the gate must exit 1" to the invariants that
  actually matter: the gate must not be content-blind, must not hide the state it declines to
  escalate, and must not let a row count read as coverage. This follows that test's own
  2026-07-25 precedent, which had already refused to pin the gate to a defect that no longer
  existed.
- Suites green: test_ssot_consistency, test_content_completeness, test_routing_generation,
  test_axis_registry, test_claim_provenance, test_axis_eval.

## Note for whoever commits this
A regression appeared mid-fix and is worth recording: the first attempt put the status check
INSIDE the detector, which broke five fixture tests in test_content_completeness that exercise
the detector using legacy axis names as labels. That was the same conflation of detection and
policy, one level down. The separation in remedy (1) is what fixed it.
