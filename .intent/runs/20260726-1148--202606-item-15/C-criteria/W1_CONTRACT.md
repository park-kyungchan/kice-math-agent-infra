# W1 contract — conclusion representation module
Written before work begins, per the owner's decision D3 (contracts just-in-time, one per unit).

1. OBJECTIVE
   Supply the five things the frozen spec named but never defined, and which an independent
   reviewer had to invent in order to rehearse this unit at all: the sort and predicate
   vocabulary, the binding shape, what "ambient typing" concretely holds, the canonical
   normal-form hash recipe, and the lemma library's entry schema. Then implement them.

2. ARTIFACTS IT MAY CREATE OR MODIFY
   pipeline/query_engine/conclusion_form.py            (new)
   storage/ce_lemma_library.json                       (new, may be empty at first)
   tests/test_conclusion_form.py                       (new)
   .intent/runs/<run>/C-criteria/W1_VOCABULARY.md      (the design record)

3. ARTIFACTS IT MUST NOT TOUCH
   axis_registry.py, validate_ssot_consistency.py, generate_routing.py, ROUTING.md,
   selective_fetcher.py, claim_provenance.py, storage/parsed_dataset.db, docs/*, MANIFEST.json,
   PROJECT_STATE.json. This unit writes no database rows and changes no gate.

4. INTERFACES IT MUST PRESERVE
   The translator contract proved by W0: a node plus ambient premises must translate to
   symbolic constraints that an independent solver can use WITHOUT the answer key. W0's probe
   (.intent/runs/<run>/C-criteria/w0_ac7_probe.py) is the working reference and its behaviour
   on item 15 -- three independent nodes, minimal sufficient subsets {N1,N4} and {N2,N4},
   keystone N4, N3 and N5 entailed -- must be reproducible through the new module.

5. DEFINITION OF DONE
   - The five undefined things are defined, each justified against a real corpus item.
   - conclusion_form.py exposes: node construction, canonical serialisation, the normal-form
     hash, and the relation verdict (IDENTICAL / EQUIVALENT / IMPLIES / OVERLAP / DISTINCT /
     UNDECIDED, with UNDECIDED explicit and routed to review rather than guessed).
   - Coverage is stated honestly: which of the four pilot items the vocabulary can express and
     which it cannot. A sequence item and an exponential-curve item are in the pilot set and
     are the stress cases; failing to express them is an acceptable, recorded limit, but
     pretending to express them is not.
   - Tests: the W0 node set round-trips; two spellings of the same conclusion hash identically;
     two genuinely different conclusions do not; an unresolvable pair returns UNDECIDED.

6. CHECKS IT MUST RUN
   python -m unittest tests.test_conclusion_form
   python scripts/validate_ssot_consistency.py   (must remain exit=0)
   Regeneration obligation: if any generated artifact's source changed, regenerate it in this
   same wave -- W7 was retired for exactly this reason.

7. RETRY LIMIT / APPROVAL
   Two attempts. Any need to touch a file in section 3, or any change to the acceptance
   criteria, requires owner approval and reopens the named gate.
