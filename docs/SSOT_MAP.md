# SSoT (Single Source of Truth) Governance Map

This document establishes the authoritative sources of truth for all domains within the `kice-math-agent-infra` system (v2.10.0). Any conflict between documents must be resolved by referring to the designated SSoT for that domain.

> **Drift gate:** `scripts/validate_ssot_consistency.py` mechanically checks (1) Taxonomy_Spec DDL == live DB schema, (2) MANIFEST.json references and never duplicates PROJECT_STATE.json, (3) version-string coherence across root docs, (4) the documented transition matrix == `review_state.ALLOWED_TRANSITIONS`. CI runs it on every PR.

## 1. Taxonomy & DDL SSoT
**Document:** [`docs/Taxonomy_Spec.md`](Taxonomy_Spec.md)
* **Domain:** 3-Layer 8-Axis Architecture, Database Schema, Enums, and Constraints.
* **Governance:** Any changes to database schema or structural representation of mathematical concepts must be approved and reflected here first.
* **Axis identity (I2 axis-agnostic storage refactor):** the 8-axis taxonomy is under owner review;
  axis IDENTITY (key, human name, status `active`/`under_review`/`deprecated`, payload schema_version,
  `analyser`/`generator`/`derived` kind) is governed by
  [`pipeline/query_engine/axis_registry.py`](../pipeline/query_engine/axis_registry.py), not by DDL —
  a new or redefined axis needs a registry entry + `analysis_derivation` rows, never a migration. Axis
  DATA is stored in the generic `analysis_derivation` table (see Taxonomy_Spec.md §2); `axis_analysis`
  is retained as a read-only compatibility VIEW over it so existing readers are unaffected. See
  `pipeline/migrate_db_axis_agnostic.py`.

## 2. Stakeholder Value SSoT
**Document:** [`docs/STAKEHOLDER_INTENT.md`](STAKEHOLDER_INTENT.md)
* **Domain:** Core intents, value propositions, and success criteria for human educators and autonomous AI agents.
* **Governance:** Feature proposals and architectural shifts must align with the intent artifacts defined in this document.

## 3. System Status SSoT
**Document:** [`PROJECT_STATE.json`](../PROJECT_STATE.json)
* **Domain:** Current phase, version, and execution proof status of the project.
* **Governance:** Machine-readable definitive state tracker. Automated processes and external reporting tools must ingest this file.

## 4. Agent Specification SSoT
**Document:** [`pipeline/agents_spec/`](../pipeline/agents_spec/)
* **Domain:** AI agent prompts, orchestrator routing logic, and system behavior instructions.
* **Governance:** Any modification to agent behavior, tool access, or standard operating procedures must be committed within these specification files.

## 5. Data & Governance SSoT
**Document:** [`storage/parsed_dataset.db`](../storage/parsed_dataset.db)
* **Domain:** The actual indexed repository of all processed 2021-2026 KICE math items, metadata, and linkage codes.
* **Governance:** The SQLite database is the ultimate authority on item metadata, bypassing any outdated or disconnected text summaries.

## 6. Review Workflow & Audit SSoT
**Authority:** `question_item.review_status` (current state snapshot) + [`teacher_review_event`](Taxonomy_Spec.md) (append-only audit log), mutated ONLY through `pipeline/query_engine/review_state.py`.
* **Domain:** Teacher review workflow states, transitions, and their full audit history.
* **Governance:** No code path may UPDATE `review_status` directly; every change goes through the transition function (matrix-validated, event-recorded, optimistically locked). `review_history_json` is deprecated and read-only.

## 7. Claim Provenance SSoT
**Authority:** [`claim_provenance`](Taxonomy_Spec.md) table, served by `pipeline/query_engine/claim_provenance.py`.
* **Domain:** Per-claim provenance (claim type, sources, derivation actor, confidence, counter-evidence, human verification).
* **Governance:** Provenance exists only if persisted; readers must never synthesize provenance or axis payloads. Teacher approval/rejection links claims to the deciding `teacher_review_event`.
