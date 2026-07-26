# Spec — Conclusion-Encoding Axis (`ce.*`) and Agent Set, piloted on 202606 item 15
Run: 20260726-1148--202606-item-15 | Tier: T2 DEEP | Status: FROZEN (owner-accepted 2026-07-26 — see sections 19 and 20)
Workspace: .intent/runs/20260726-1148--202606-item-15
Language: artifacts English; interview conducted in Korean.

## 1. Mission
Replace the 8-axis taxonomy with a single conclusion-centred axis family `ce.*`, executed by six
specialist agents, and prove it on one item plus its lineage. The analytical unit stops being the
stated condition and becomes the CONCLUSION the condition forces; conditions are ENCODINGS, many
to one onto a conclusion. Item relatedness then falls out as a derived query over shared
conclusions rather than being separately authored.

## 2. Operating situation
Repository `kice-math-agent-infra`, git-managed, HEAD 28ce655 at freeze. Storage is SQLite
(`storage/parsed_dataset.db`), append-only for analysis. Owner is the sole governor and reviewer.
Consumers: (a) zero-context agents reading structured payloads, (b) the owner and math
instructors reading rationale traces to give feedback.

## 3. Problem statement (verified)
FACT   The corpus holds 690 distinct items, not 1,350; items 1–22 of each session are stored once
       per track (330/330 triples byte-identical; control 0/120 on items 23–30).
FACT   Exactly one distinct item carries non-stub 8-axis analysis: 202606 item 15.
FACT   That analysis is circular. `axis5.verification_protocol` asserts the supplied answer
       (`assert_f6: 27`, `solvability_status: PASS`). The repo's own
       `pipeline/axis_eval/m4_informational_validity.py` and `docs/decisions.md` (2026-07-26)
       already record this as an answer-leak.
FACT   Its genealogy is 1-for-3. `202411_MATH_DIF_22` is a sequence problem and `202506_MATH_DIF_22`
       is an exponential-curve intersection problem; neither shares a conclusion with item 15.
       The one defensible edge (`202106_MATH_DIF_22`) carries a false justification string.
FACT   Recomputation shows condition (가) alone forces {x=0 double root, x=3 simple root} but
       leaves sign(a) undetermined; `a>0` requires condition (나). The incumbent conflated these.
FACT   `axis2_raw_parsing` is reported 100% real but only 3 rows carry a parsed `conditions[]`
       array; the other 1,347 hold raw text including page numbers and copyright notices.
FACT   Every axis in the incumbent taxonomy is keyed on the item. All three owner concerns
       (condition decomposition, condition-to-concept mapping, cross-item variation of meaning)
       are keyed on something finer. The missing thing was a granularity level, not an axis.
FACT   30 distinct items mention a cubic function — a coarse conclusion vocabulary would connect
       4.3% of the corpus into one meaningless clique.

## 4. Root cause
Item-level granularity plus unverified generation. Analysis was authored at the item level and
accepted without provenance (`claim_provenance` 0 rows), without human review
(`teacher_review_event` 0 rows), and without outcome data (`correct_rate` null for all rows), so
nothing could detect that a lineage claim was false or that a verification verified nothing.

## 5. Selected design
One axis family, six agent specs, six `axis_key` strings under the `ce.` namespace.

| axis_key | Agent | Kind | Stage |
|---|---|---|---|
| `ce.segmentation` | A1 Encoding Segmentation (incl. unlabelled global premises) | analyser | 1 |
| `ce.semantics`    | A2 Unit Semantics (object + concept, fused)                  | analyser | 2 (concurrent per unit) |
| `ce.relation`     | A3 Relation, 6 classes (below)                                | analyser | 3 |

A3 relation classes, each with its discriminating check:
`SEQUENTIAL_REFINEMENT` (removing A leaves B non-unique) | `INDEPENDENT` (removing either leaves the
other's solution set unchanged) | `IMPLICATION` (A true makes B automatic; B redundant) |
`MUTUAL_EXCLUSION` (A and B jointly unsatisfiable) | `DUPLICATION` (same solution set) |
`BACKGROUND_CONSTRAINT` (an ambient premise such as "f is cubic" — never a conclusion node, and
never an edge in derived relatedness; this class is the primary defence against hub explosion).
| `ce.canonical`    | A4 Canonical Convergence Matcher                             | derived  | 5 |
| `ce.variance`     | A5 Observed Variance across corpus                           | derived  | 5 |
| `ce.altgen`       | A6 Alternative-Encoding Generator                            | generator| 5 |

Rejected alternatives: nesting perspectives inside one payload (kills independent execution and
independent verification); keeping the 8 axes and appending (owner directed removal); running A4/A5/A6
concurrently with A2 (they consume verified conclusions and would receive empty input, reproducing
the dead-axis failure the registry already records for axis8).

## 6. Core value path
problem text -> A1 encoding units -> A2 unit semantics (concurrent) -> A3 relations
-> VERIFICATION BARRIER -> conclusion nodes -> {A4 canonical, A5 variance, A6 alternatives}
-> derived relatedness edges -> owner feedback on rationale -> corrected dataset.

## 7. Scope
CORE      Item 15 (one distinct item, three rows) end to end through all six agents, plus
          re-adjudication of its three claimed precedents.
PROOF     The pipeline independently reproduces the dry-run adjudication: accept 202106_MATH_DIF_22,
          reject 202411_MATH_DIF_22 and 202506_MATH_DIF_22, each with cited evidence; and derives
          the three independent conclusion nodes for item 15 (section 8) without reading the
          answer key, and shows N3 and N5 as entailments rather than as nodes.
EXPANSION All 690 distinct items; re-parsing the 1,347 raw-text axis2 rows (DEFERRED, not excluded).
NON-GOALS Not building a general theorem prover. Not using national-curriculum achievement
          standards as the decomposition unit (owner-excluded). Not deleting any existing row.
          Not producing difficulty or correct-rate estimates. Not implementing anything in this
          run — this spec ends at design freeze.

## 8. Conclusion representation and granularity
Closed-world sorts and predicate schemas; conclusion = (schema, binding, ambient typing) with a
canonical normal-form hash. Relations between conclusions: IDENTICAL, EQUIVALENT (via a curated
finite lemma library, not a prover), IMPLIES, OVERLAP, DISTINCT, UNDECIDED. UNDECIDED is explicit
and routes to human review so that a never-firing equality test is visible rather than silent.

STOPPING RULE (intrinsic, owner-directed to avoid curriculum standards): a conclusion node is the
smallest single-schema, fully-bound claim that is independently falsifiable — a hypothetical
variant item could change this node alone while the rest of the chain holds.

Applied to item 15 the chain resolves to THREE independent nodes plus two entailments:
  N1 double root at x=0 (no sign change)
  N2 simple root at x=3 (sign change)
  N4 local minimum f(2) = -1
  -- entailed, NOT independent nodes --
  N3 a>0     : given N1,N2 the closed form is f=a x^2 (x-3), so f(2) = -4a; N4 fixes a = 1/4,
               which fixes the sign. No variant item can change N3 alone while N1,N2,N4 hold.
  N5 f(6)=27 : f(6) = 108a = 27 follows from the same binding. N5 is the target value, not a
               structural conclusion; recording it as a node is over-derivation.
`f(x)=1/4 x^2 (x-3)` is likewise a re-serialisation, not a node.

An earlier draft of this spec listed five nodes. That was wrong by this spec's own stopping rule
and was caught by independent verification; the rule stands and the example is corrected. Node
independence is not derivation order — the derivation may pass through a>0 as an intermediate
lemma while a>0 is still not an independent node.

## 9. Architecture, interfaces and data
Storage is open-world: a new axis needs only a new `axis_key` string in `analysis_derivation`.
Rationale is stored separately (section 10) and never inside an analytical payload — the incumbent
`axis4_contextual_tree` made exactly that category error and the registry records it.
Concurrency in stage 2 is enforced by a negative-context rule: an A2 instance may not see other
units. Stage 3 and the verification barrier are hard sequential barriers justified by data
dependency, not by preference.

## 10. Rationale ledger (owner requirement, 2026-07-26)
Every agent emits a human-readable reasoning trace, anchored and gated:
- Stored as append-only rows, `kind: telemetry`, never as an axis; rendered to human-readable form
  by the existing `pipeline/report_generator`, never hand-authored.
- Every step cites a `claim_provenance.json_pointer` into the payload field it justifies.
  Gate A: every payload field has at least one rationale step. Gate B: every citation resolves.
- Mandatory step sections: CONSIDERED / REJECTED-with-reason / EVIDENCE / UNCERTAINTY / FALSIFIER.
- Steps are individually addressable; owner feedback binds at step granularity through the existing
  hash-chained `teacher_review_event`, with verdicts ACCEPT, REJECT_CONCLUSION,
  REJECT_REASONING (right answer reached by invalid reasoning), NEEDS_EVIDENCE.
- Because a trace must cite what it consumed, a trace citing the answer key is mechanically
  detectable. The ledger is therefore the standing detector for the circularity of section 3.
- Cost tiering: full traces during the pilot; at corpus scale full traces only for low confidence,
  agent disagreement, or first use of a schema; compressed otherwise.

## 10a. File and storage locations
Agent specs: `pipeline/agents_spec/ce_{segmentation,semantics,relation,canonical,variance,altgen}_agent.md`
Conclusion representation (W1): `pipeline/query_engine/conclusion_form.py`; lemma library
  `storage/ce_lemma_library.json` (curated, append-only, each entry citing the pair that triggered it;
  curation owner = the reviewing teacher, growth by discovery only).
Verification barrier (W3): `pipeline/axis_eval/ce_verification.py` (a NEW file; the existing
  modules under that directory are unchanged — see section 18)
Rationale ledger (W5): new append-only table `rationale_step` — columns `step_id`, `item_id`,
  `axis_key`, `run_id`, `seq`, `json_pointer`, `section` (CONSIDERED|REJECTED|EVIDENCE|UNCERTAINTY|
  FALSIFIER), `body_md`, `inputs_cited_json`, `prev_step_hash`, `step_hash`, `created_at`.
  Rendered by a NEW renderer added to `pipeline/report_generator/`; the existing
  `html_builder.py` is a generic payload dumper with no step, section, or hash-chain awareness and
  cannot render this table as-is. Never hand-authored.
Derived relatedness query (W8a): `pipeline/query_engine/ce_relatedness.py`

## 11. Acceptance criteria
| id | statement (observable) | how observed | judge |
|---|---|---|---|
| AC1 | The node set of section 8 derived for item 15 — three independent nodes, with N3 and N5 recorded as entailments, not nodes — and no answer-key leak | TWO detectors, both required: (a) citation scan for answer-key sources; (b) value scan for the final answer appearing in any payload OR in `rationale_step.body_md` free
text, in digit or spelled form, before the final node. A leaf-key scan is not sufficient: the known
prior leak hid in `calculated_value.f_6`, and prose is the next place it will hide. Detector (a) alone is insufficient — the repo's own history shows a leak that passed a name-based scan by hiding in `calculated_value.f_6` | automated |
| AC2 | Adjudication reproduces 1 accept / 2 reject on the claimed precedents, with cited evidence | Compare against `.intent/runs/<run>/C-criteria/ADJUDICATION_REFERENCE.md`, which MUST be committed and hash-recorded BEFORE implementation begins and must contain the evidence, not merely the verdicts. An implementer-authored reference is void. | automated |
| AC7 | SUBSTANCE ANCHOR — an independent solver, given ONLY the independent conclusion nodes and the item's ambient premises, and NOT the item's answer, recomputes f(6)=27 | run the solver; compare to the sealed answer key afterwards | automated |
| AC8a | SOUNDNESS — every node is independently verified true against the item, node by node, not merely as a set | per-node check | automated |
| AC8b | MINIMALITY REPORT — the minimal sufficient subsets, the keystone nodes, and any non-contributing node are computed and recorded. A node in no minimal sufficient subset is FLAGGED as a candidate over-derivation, not rejected: redundancy for determination is not the same as being untrue | exhaustive subset search | automated |

AC8 (retired 2026-07-26 by W0): it required that deleting any one node break recovery, which assumes a
minimal conjunctive basis. Item 15 has none — its structure is `N4 AND (N1 OR N2)`. The criterion
conflated "independently falsifiable fact" (the stopping rule) with "necessary for determination".
Over-determination is a property the exam writer put there and is analytical content worth recording.
| AC9 | Generated payloads carry `provenance_class: SYNTHETIC` and are excluded by default from variance and relatedness results | query with and without the filter; results must differ | automated |
| AC3 | Every payload field has a resolving rationale citation | Gate A + Gate B | automated |
| AC4 | Two independent runs of A1..A3 on item 15 yield the same node SET — identical normal-form hashes, not merely the same count | normal-form hash set diff | automated |
| AC5 | Owner accepts the rationale trace as feedback-usable | At least one `teacher_review_event` with `actor_type='TEACHER'`, a verdict of ACCEPT, and a resolving reference to a specific `rationale_step.step_id`. Bare row existence does not satisfy this. | owner |
| AC6 | No conclusion enters A4/A5 before passing the verification barrier | stage-order audit in trace | automated |

## 12. Veto conditions (owner-confirmed sufficient, 2026-07-26)
1. Verification that asserts its own input (circularity).
2. Decomposition with no stopping rule, i.e. non-reproducible node counts.
3. A lineage edge asserted without cited evidence.
4. Copyright notices, page numbers or exam boilerplate entering an analytical payload.
5. A derived axis scheduled concurrently with a stage that produces its own inputs. (Derived
   axes MAY run concurrently with each other once their shared inputs are verified — `ce.canonical`
   and `ce.variance` both run in stage 5 and that is permitted.)
6. A conclusion entering convergence computation before verification.
7. Generated alternative encodings (A6) stored indistinguishably from observed corpus data.
   Enforced structurally, not by convention: every `ce.altgen` payload carries a required
   `provenance_class: SYNTHETIC` field, and `ce.variance` and the derived relatedness query
   (section 10a, W8) filter on it by default. Relatedness is a query, not a seventh axis_key. A free-text origin note is not sufficient enforcement.
Any one of these rejects the result regardless of every other score.

## 13. Assumptions in force
| assumption | invalidation condition | source |
|---|---|---|
| `202509_MATH_DIF_15` is a lineage candidate, not a confirmed edge | conclusion comparison separates them | agent |
| `axis2_raw_parsing` is exempt from retirement | owner includes it in "all axes" | agent |
| Re-parsing the 1,347 raw rows is deferred, not cancelled | owner intends permanent exclusion | user, round 3 |
| Non-goals in section 7 are correct | owner names an excluded item as in scope | agent |

## 14. Open risks
- Hub explosion if conclusion vocabulary is too coarse; mitigated by classifying background premises
  as relations rather than conclusions. Unproven until run at scale.
- Lemma library incompleteness yields UNDECIDED verdicts; monotone but permanently incomplete.
- Owner authorised optimisation of "everything affected", which is broader than the minimal DDL
  change; blast radius is bounded by archive-over-delete and git but is larger than T2 triage assumed.
- Discrete/sequence and synthetic-geometry conclusions are not expressible in the current sort set.

## 15. Work decomposition
W1 Conclusion representation module | W2 A1..A3 agent specs | W3 verification barrier and proof
obligations | W4 A4..A6 agent specs | W5 rationale ledger and gates | W6 registry retirement and
DDL relaxation of `claim_provenance.axis` | W8a derived relatedness query | W8b pilot run and
adjudication.
W7 (documentation regeneration) is RETIRED as a work unit. Regenerating a generated artifact is an
obligation of every wave that changes that artifact's source, discharged in the same wave, not
batched at the end -- W6a proved the regeneration-diff gate goes red immediately. Every unit
contract must carry this obligation. The seven-part contract for each unit (files it may touch, files it
must not, interfaces preserved, definition of done, checks to run, retry limit, actions requiring
owner approval) is NOT yet written — it is the first deliverable of implementation, not a property
this spec already supplies. Do not begin a unit before its contract exists.

## 16. Stop conditions and budget
PASS / BLOCKED / BUDGET_EXHAUSTED / HUMAN_DECISION_REQUIRED. Holdout: the owner seals ONE item, chosen by
him and named nowhere in this document or any artifact the implementer can read, used once after
the pilot passes to test whether the derived relatedness query surfaces it unprompted. NOTE: an
earlier draft named a candidate in section 13, which would have destroyed the holdout by
disclosure; that candidate is therefore disqualified as a holdout and remains only a lineage
candidate.

## 17. Security and exposure constraints
No secrets involved. Exam text is copyrighted third-party material: it may be stored and analysed
in-repo but boilerplate and copyright strings must not enter analytical payloads (veto 4).

## 18. Known blockers
- `claim_provenance.axis` carries `CHECK (axis IN ('Axis_1'..'Axis_8'))` — provenance for `ce.*`
  cannot be recorded until this is relaxed. Owner approved.
- `tests/test_axis_registry.py` asserts a length of 8 and will fail; must change in the same commit.
- `teacher_review_event` has no verdict column matching ACCEPT / REJECT_CONCLUSION /
  REJECT_REASONING / NEEDS_EVIDENCE, and no reference to a rationale step; both need adding. The
  blocker list in this section is NOT asserted to be exhaustive — W6 must begin with a survey.
- `ROUTING.md` is generated with a regeneration-diff gate — regenerate, never hand-edit.
  `docs/Taxonomy_Spec.md`, `docs/SSOT_MAP.md`, `MANIFEST.json`, `PROJECT_STATE.json`,
  `ENTRYPOINT.md` are hand-maintained and must be edited. Existing `pipeline/axis_eval/*` modules
  need no change; W3 adds one new file to that directory.

## 19. Freeze record
Residual Risk: 8 (S08 non-goals). Patch-induced regression risk is NOT included in that figure.
Rounds used: 5/5 (T2). Gates reopened: A2/A3 reopened at round 4 by owner scope change.
Verification history (independent subagents, ladder rung 1 — stronger than T2 requires):
  Pass 1: EXECUTABLE_WITH_GAPS, 8 defects, all patched.
  Pass 2: two independent reviewers. Execution rehearsal returned EXECUTABLE_WITH_GAPS and
    demonstrated a complete path to satisfying every acceptance criterion and every veto with
    fabricated stub content; it also proved, by computation, that this spec's own worked example
    violated its own stopping rule. Patch regression audit returned RESIDUAL_DEFECTS: 6/8 patches
    clean, 1 unenforced, 1 introducing three new inconsistencies.
  All pass-2 findings are patched above, including three substance-anchor criteria (AC7-AC9) that a
  fabricated pipeline cannot satisfy, and the correction of the node set from five to three.
  The pass-2 patches have NOT themselves been re-verified.
Pass 3 (targeted, not a full re-verification): after the 5-to-3 node correction, a stale-reference
  sweep found two places still asserting five nodes (section 7 PROOF and AC1). Both corrected.

OWNER DECISION, 2026-07-26: accept with residual risks open rather than run a third full
verification pass. Rationale recorded by the owner: promotion is incremental — this pilot covers
one item and is iterated on, so AC7/AC8 are exercised on the first implementation run rather than
becoming the unverified gate of a 1,347-item batch. The cost of a toothless AC is therefore bounded
by one pilot item, not by the corpus.

STATUS: FROZEN (owner-accepted, with section 14 risks open and section 20 conditions binding).

## 19a. Implementation record — 2026-07-26
All work units are built and green. The gate is exit=0 and every test suite in the repository
passes.

| unit | outcome |
|---|---|
| W0  (inserted) | AC7 proved to have teeth; AC8 proved malformed and replaced by AC8a/AC8b |
| W6a | ce.* registered as a separate family; the legacy Axis_1..Axis_8 contract preserved by construction and pinned by a new regression test |
| W6b | claim_provenance.axis relaxed from a closed enum to a format check, via a migration that stages through the local filesystem |
| W1  | conclusion_form.py — closed vocabulary, binding kinds, ambient typing, normal-form hash, six-way relation verdict, seeded lemma library |
| W3  | ce_verification.py — leave-one-out soundness, sufficiency, minimality, two-detector leak scan, stage-order audit |
| W5  | rationale_ledger.py — hash-chained steps, five mandatory sections, Gate A/B, four teacher verdicts including REJECT_REASONING |
| W8a | ce_relatedness.py — relatedness as a derived query, background constraints excluded |
| W8b | pilot run: barrier PASS, adjudication 1 ACCEPT / 1 REJECT / 1 NOT_EXPRESSIBLE, matching the sealed reference |
| W2/W4 | six ce_*_agent.md specs, written after the pilot so they describe what worked |
| GATE | the SSoT gate's own root cause fixed: detection separated from escalation, escalation rebound to the registry claim, denominator made honest, check list canonicalised |

Corrections the work forced on this spec, each logged in DECISION_LOG.md:
- the node set for item 15 is three, not five; N3 and N5 are entailed (W0)
- AC8 was malformed and is retired in favour of AC8a soundness and AC8b minimality (W0)
- soundness must be leave-one-out; checking a node against a function solved for using that
  node is circular and would pass a fabrication (W3)
- W7 is retired; regenerating a generated artifact is an obligation of every wave (W6a)
- NOT_EXPRESSIBLE is kept distinct from REJECT, so a coverage gap cannot masquerade as a
  finding about mathematics (W8a)

Acceptance criteria: AC1, AC2, AC4, AC6, AC7, AC8a, AC8b PASS. AC3 and AC5 are not scored --
AC3 needs the ledger populated by a real agent run rather than the hand-authored trace used to
exercise the leak scan, and AC5 is the owner's verdict and cannot be self-awarded.

## 20. Conditions binding on the first implementation session
These carry the verification debt that pass 3 did not discharge. They are not optional.
1. AC7 and AC8 are run FIRST, before any other acceptance criterion, on item 15. If a stub node set
   passes AC7, the substance anchor is toothless and implementation stops until it is redesigned.
2. `ADJUDICATION_REFERENCE.md` is committed and hash-recorded BEFORE any adjudication code runs.
   An implementer-authored reference voids AC2.
3. The answer-key value scan covers `rationale_step.body_md` free text, in digit and spelled form,
   not only JSON leaves.
4. No promotion beyond item 15 until the owner has read at least one full rationale trace and
   returned a verdict through `teacher_review_event`.
5. Any defect found in this spec during implementation reopens the named gate and is recorded in
   `DECISION_LOG.md`; it is not patched silently.

Status of these conditions as of 2026-07-26: (1) DISCHARGED -- W0 ran before anything was built
and proved a stub set cannot pass AC7. (2) DISCHARGED -- the reference was committed and
sha256-recorded before the adjudicator ran. (3) DISCHARGED -- the value detector covers prose and
English number words, with its limits stated. (4) OPEN, and correctly so: it is the owner's act.
(5) DISCHARGED -- five spec corrections were logged rather than patched silently.
