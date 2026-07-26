# Decision log — 20260726-1148--202606-item-15
Append-only. Format: gate | action | trigger | what changed.

R0  | ENTER A1 | explicit invocation | tier T1 proposed and accepted
R2  | RETIER   | grounding invalidated triage: axis redesign spans 690 items, 10,800 rows | T1 -> T2
R2  | REOPEN B2| owner rejected the 8-axis taxonomy outright | framing regenerated
R3  | DECIDE   | owner excluded curriculum achievement standards as decomposition unit | stopping rule = intrinsic falsifiability
R4  | REOPEN A2/A3 | owner reframed the analytical unit from condition to conclusion | slot board rebuilt
R4  | DECIDE   | owner directed removal of all 8 axes | retirement = deprecate + archive, no row deleted
R4  | DECIDE   | owner authorised optimisation of everything affected, not just minimal DDL | blast radius widened; reversibility retained via git + archive-over-delete
R5  | ADD      | owner required human-readable agent rationale | rationale ledger specified as telemetry, never an axis
R5  | STOP     | zero-context check returned gaps after budget | BUDGET_EXHAUSTED, not frozen
R6  | EXTEND   | owner extended the budget | verification round opened
R6  | FIX      | verification proved the spec's own worked example violated its own stopping rule | node set corrected 5 -> 3
R6  | FIX      | verification demonstrated a complete path to passing every AC with stub content | substance anchors AC7-AC9 added
R6  | FREEZE   | owner accepted residual risk on the grounds of incremental promotion | FROZEN with section 20 conditions binding
W0  | REOPEN C1 | W0 proved AC8 malformed: {N1,N4} and {N2,N4} each determine the target, so no minimal conjunctive basis exists | AC8 retired; AC8a SOUNDNESS + AC8b MINIMALITY approved by owner
W0  | RESULT    | AC7 verified to have teeth: real set recovers 27, stub set recovers nothing | principal residual risk of spec section 20.1 discharged
W6a | AMEND  | regeneration-diff gate went red the moment axis_registry changed; spec placed doc regeneration in W7 at the end | W7 retired; regenerating a generated artifact is now an obligation of every wave that changes its source. Owner approved.
W6a | DONE   | ce.* registered as a separate family; legacy Axis_1..Axis_8 contract preserved by construction | AXIS_COLUMNS/AXIS_COLUMN_BY_DICT_KEY/DICT_KEY_BY_AXIS_COLUMN derived from family=="legacy" only; new regression test pins it
W6b | INCIDENT | migrating claim_provenance directly against the mounted DB failed at COMMIT with disk I/O error and left a hot journal the mount could not roll back; the DB became unopenable in place | recovered from the pre-change state by copying DB+journal to local fs, letting SQLite roll back, verifying integrity and all row counts, then writing the file back. No data lost.
W6b | LEARN  | the mount supports whole-file copies but not SQLite page writes or journal locking | migration script now stages through the local filesystem and verifies integrity before write-back; recorded in the script's ENVIRONMENT NOTE
W6b | DONE   | claim_provenance.axis relaxed from a closed 8-value enum to a format check | accepts Axis_1..Axis_8 and <family>.<name>; rejects Axis_9, bogus, empty, wrong case. docs/Taxonomy_Spec.md DDL updated to match.
W6  | BASELINE | SSoT gate returns rc=1 both before and after W6, with an identical 7-error set, all stub-sentinel on legacy axes | pre-existing, not caused by W6; reported to owner as an open question about how CI is currently green
GATE | FIX | gate was permanently red on a state the owner chose; root cause was detection and escalation fused in one function | detector unchanged and default-escalating; escalation rebound to the registry claim in a NEW check (R1/R2/R3); denominator made honest; GATE_CHECKS canonicalised so the generator cannot drift from the gate. Gate exit=0, six suites green. See C-criteria/GATE_ROOT_CAUSE.md
W1  | DONE | conclusion_form.py implemented: closed sort/predicate vocabulary, binding kinds, ambient typing, normal-form hash, six-way relation verdict, seeded lemma library | 18 tests green; reproduces the W0 result through the module (both minimal sufficient subsets recover 27, dropping the keystone does not); gate stays exit=0
W1  | DESIGN | the pre-W0 vocabulary draft was overturned on six points | node count 5 -> 3 (N3/N5 entailed, not independent); Curve folded into FUNCTION; SIGN_CHANGE removed as a bindable slot (entailed by multiplicity parity); quantifier shape separated from comparison operator; Interval dropped for want of a witness; COEFF_SIGN recorded as untranslatable rather than silently contributing nothing
W1  | LIMIT  | coverage stated honestly rather than claimed | 202606 expressible; 202106 partially (root count of a composition with the unknown is expressible but not uniformly translatable); 202411 NOT expressible (sequence item -- different solver family, not a missing sort); 202506 expressible in principle, unimplemented in the translator
W3  | DONE | verification barrier built | soundness redesigned mid-unit: checking a node against the function the whole set determines is circular and would pass a fabrication, so it is now leave-one-out, and a keystone the rest cannot pin down is reported UNCHECKED rather than passed
W5  | DONE | rationale ledger built | hash-chained steps, five mandatory sections with REJECTED required, Gate A/B anchoring, REJECT_REASONING verdict added -- no existing schema could express a right answer reached by invalid reasoning
W8a | DONE | relatedness as a derived query | background constraints cannot carry an edge (hub-explosion defence); NOT_EXPRESSIBLE kept distinct from REJECT
W8b | DONE | pilot run against a reference sealed and hashed beforehand | barrier PASS; 1 ACCEPT / 1 REJECT / 1 NOT_EXPRESSIBLE, matching the reference exactly; AC1/AC2/AC6/AC7/AC7b/AC8a/AC8b all PASS
W2/W4 | DONE | six ce_*_agent.md specs authored AFTER the pilot | they describe the pipeline that was proven, not the one that was intended
RUN | CLOSE | all work units green; gate exit=0; every repository test suite passes | AC3 and AC5 remain unscored by design; spec section 20 condition 4 remains open because it is the owner's act
