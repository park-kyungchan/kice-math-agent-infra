# Decision Log

Rationale for significant changes, recorded before mutating. Newest first.

---

## 2026-07-26 — Retract `independent_execution_proof` and `semantic_verification`

**Decision.** Demote `PROJECT_STATE.json` from `overall_status: VERIFIED` to `PARTIALLY_VERIFIED`, and
change `independent_execution_proof` and `semantic_verification` from `COMPLETE`/`APPROVED` to
`RETRACTED_CIRCULAR`. Bump to v2.10.0.

**Why.** The axis evaluation harness (`pipeline/axis_eval/`) tested whether an axis payload carries
enough information to recover the official answer. Building its non-circularity guard surfaced two
findings:

1. `independent_solver.py` returns a result only through its circular fallback. With the answer
   properly withheld it returns `NOT_RUN` — even on the pilot anchors, even with fully repaired text.
   It has never independently solved anything.
2. The pilot anchor payloads embed the answer directly. `axis5_traps_verification` for
   `202606_MATH_DIF_15` carries `{"correct_option": 4, "correct_answer_value": 27}`;
   `axis3_symbolic_modeling` carries `{"calculated_value": {"f_6": 27}}`. Any proof consuming those
   payloads is circular by construction.

Together these mean the semantic proof never existed. Leaving the claims in place would be the exact
failure mode this repo is recovering from.

**Evidence.** `scratch/staging/I3/REPORT.txt`; `pipeline/axis_eval/m4_informational_validity.py`
and its `guard_non_circular(strict=True)` tests, which fail on both real leaks above.

**Consequence.** `overall_status` may not return to `VERIFIED` until the stub-sentinel gate passes over
real analysis. The gate exiting 1 is now recorded as `GATE_RED_BY_DESIGN`.

---

## 2026-07-26 — Repair `axis2_raw_parsing` payloads; close the escaped-storage gate hole

**Decision.** Rebuild all 1,347 repairable `axis2_raw_parsing` payloads from the verified
reconstruction output, and extend `check_pua_free_text` to JSON-decode `analysis_derivation.payload`
before scanning.

**Why.** 1,345 of 1,350 payloads were PUA-corrupted while the gate reported the database clean, for two
compounding reasons: the check scanned only `question_item.latex_content`, and payloads are stored
with `ensure_ascii=True` so a PUA codepoint sits in the column as the literal ASCII text ``,
invisible to a raw regex. A gate blind to a live defect is an audit that lies.

**Open item for the taxonomy review.** `axis2_raw_parsing` now duplicates `question_item.latex_content`.
Two copies of the same content is a parallel registry and should be resolved — most likely by
deprecating the axis — but that is a taxonomy decision, deliberately deferred to the owner's review
rather than settled unilaterally here.

---

## 2026-07-25 — Move axis storage out of the schema (I2)

**Decision.** Replace the 8 hardcoded `axis_analysis` columns with a generic
`analysis_derivation(item_id, axis_key, schema_version, payload, derived_by, confidence, derived_at)`
table, keep `axis_analysis` as a read-only compatibility view, and route axis identity through
`pipeline/query_engine/axis_registry.py`.

**Why.** The 8-axis taxonomy is under owner review, yet it was hard-committed into the DDL, into
`docs/Taxonomy_Spec.md`, into the drift gate that enforces DDL-vs-spec, and into ~91 code sites.
A taxonomy under review must not live in the schema, or every candidate revision costs a migration.
Making an axis *data* lets competing taxonomies coexist and be compared.

**Evidence.** Full consumer search in `scratch/staging/I2/REPORT.txt`; migration verified
byte-identical over all 10,800 cells on a copy before the root applied it.

---

## 2026-07-25 — Repair the corpus text and answers before any analysis

**Decision.** Recover all 1,350 items' text and official answers before doing any 기출 analysis.

**Why.** `latex_content` was 100% corrupted by HWP equation-font Private-Use-Area glyphs (22.3% of all
characters), 2D math structure was destroyed for 975 items, and `answer` was 0 for 1,347 of 1,350 while
the official answer keys sat unused in `raw_dataset/`. Analysis stacked on that substrate would have
produced 1,347 more plausible falsehoods.

**Evidence.** `pipeline/dataset_parser/hwp_pua_map.json` (80 glyphs, 0 residual across the corpus);
verification against rendered source pages; independent adversarial verification in
`scratch/staging/verify/`, which rejected the first reconstruction attempt and forced a second pass.
