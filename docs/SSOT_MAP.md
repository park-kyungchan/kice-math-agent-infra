# SSoT (Single Source of Truth) Governance Map

This document establishes the authoritative sources of truth for all domains within the `kice-math-agent-infra` system (v2.8.0). Any conflict between documents must be resolved by referring to the designated SSoT for that domain.

## 1. Taxonomy & DDL SSoT
**Document:** [`docs/Taxonomy_Spec.md`](Taxonomy_Spec.md)
* **Domain:** 3-Layer 8-Axis Architecture, Database Schema, Enums, and Constraints.
* **Governance:** Any changes to database schema or structural representation of mathematical concepts must be approved and reflected here first.

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
