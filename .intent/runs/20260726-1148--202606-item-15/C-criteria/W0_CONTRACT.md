# W0 contract — AC7/AC8 teeth probe
Inserted 2026-07-26 by owner approval (D2). Not present in the frozen spec; recorded in DECISION_LOG
as a D3 gate reopening.

1. OBJECTIVE
   Determine, before any implementation is invested, whether acceptance criteria AC7 and AC8 have
   teeth: i.e. whether a fabricated stub node set can satisfy AC7, and whether AC8's ablation claim
   holds for the node set the spec declares independent.

2. ARTIFACTS IT MAY CREATE
   .intent/runs/20260726-1148--202606-item-15/C-criteria/w0_ac7_probe.py
   .intent/runs/20260726-1148--202606-item-15/C-criteria/W0_RESULT.md

3. ARTIFACTS IT MUST NOT TOUCH
   Everything under pipeline/, tests/, scripts/, docs/, storage/, and every file at the repo root.
   This unit ships no production code. It writes nothing into storage/parsed_dataset.db.

4. INTERFACES IT MUST PRESERVE
   None — nothing depends on this unit. It may read storage/parsed_dataset.db read-only.

5. DEFINITION OF DONE
   A probe exists that, given a node set plus ambient premises and WITHOUT the item's answer
   anywhere on the solving path, either recovers f(6) or reports UNDETERMINED; and it has been run
   over: the spec's declared independent set, a fabricated stub set, every single-node ablation of
   the declared set, and an entailment-contaminated set. Results recorded with the verdict on
   whether AC7 and AC8 hold as written.

6. CHECKS IT MUST RUN
   The answer value must be read from the database only AFTER solving, for comparison, and must not
   appear as a literal in the solving path. Grep the probe for the literal answer to confirm.

7. RETRY LIMIT / APPROVAL
   One implementation attempt, then report. Any change to the acceptance criteria arising from this
   result requires owner approval and reopens gate C1.
