# Zero-Context AI Agent Infra Entrypoint Guide (ENTRYPOINT.md)

Welcome to the **CSAT Mathematics Zero-Context Agent Infrastructure** inside `kice-math-agent-infra/`.

> **Loading Order 0 — read [`ROUTING.md`](ROUTING.md) first.** It is the task-intent route table:
> measured data-health per column, environment constraints, verification commands, and known-good
> anchors. Route from there to the specific files your task needs. Do not bulk-read this repo.
>
> **Data-health warning:** `axis_analysis` is placeholder for 1,347 of 1,350 items and the 8-axis
> taxonomy described below is **under review**. `question_item.latex_content` / `answer` /
> `canonical_answer_json` were repaired 2026-07-25 and are trustworthy; `correct_rate` is empty.

This document is the **Loading Order 1 Entrypoint Guide**.

---

## 1. Quick Project Summary
- **Target Domain**: 2027 KICE Mock & CSAT Mathematics (Common: Algebra/Calculus I, Elective: Calculus II, Geometry, Prob & Stat).
- **Target User Personas**: Zero-Context Autonomous AI Agents & **Math Instructors / Professional Educators**.
- **Core Purpose**: End-to-end infrastructure allowing zero-context AI agents and Math Instructors to retrieve, reason, verify, and link math questions using the **3-Layer 8-Axis Taxonomy Architecture** (current version: see `PROJECT_STATE.json` / `MANIFEST.json` — do not assume any version number written in this prose stays current; those two files are the SSoT).
- **Dataset Scale**: **1,350 CSAT/KICE exam questions** across 45 PDF papers (2021~2026) and **1,350 high-res 300 DPI diagram PNG assets** loaded into a 4-Tier SQLite DB (`storage/parsed_dataset.db`). Question text and official answers are complete and verified; **8-axis analysis is not** (3/1,350 real — see `ROUTING.md` §2a for the live per-axis ratio).

---

## 2. Recommended Context Loading Protocol (Loading Order 1 ~ 4)

```mermaid
graph TD
    LO1["Loading Order 1: ENTRYPOINT.md & MANIFEST.json<br/>- Project Summary, Directory Map, DB Location"] --> LO2["Loading Order 2: docs/SSOT_MAP.md & docs/Taxonomy_Spec.md<br/>- SSoT Governance & 3-Layer 8-Axis Schema"]
    LO2 --> LO3["Loading Order 3: pipeline/agents_spec/router_orchestrator_agent.md<br/>- Master Router Protocol & English-authored Agent Specs"]
    LO3 --> LO4["Loading Order 4: pipeline/query_engine/selective_fetcher.py<br/>- Python 1-line DB & Batch Fetcher Helper"]
```

- **Loading Order 1 (This File & MANIFEST.json)**: High-level overview & entrypoints (see `PROJECT_STATE.json` for the current version).
- **Loading Order 2 ([docs/SSOT_MAP.md](docs/SSOT_MAP.md) & [docs/Taxonomy_Spec.md](docs/Taxonomy_Spec.md))**: SSoT Governance rules and Master 3-Layer 8-Axis Schema. The 8-axis taxonomy is **under owner review** — do not extend it before that review concludes (see `ROUTING.md` §2a / §7).
- **Loading Order 3 ([pipeline/agents_spec/router_orchestrator_agent.md](pipeline/agents_spec/router_orchestrator_agent.md))**: Master Router Protocol & English-authored Agent Specs (the two `axis2_*` specs quote Korean source-text examples by necessity — the domain is Korean-language exam conditions being converted to LaTeX/formal notation; every other spec is 100% English).
- **Loading Order 4 ([pipeline/query_engine/selective_fetcher.py](pipeline/query_engine/selective_fetcher.py))**: High-performance batch fetcher helper (`get_questions_batch()`; SLA table: `docs/STAKEHOLDER_INTENT.md` §2.6).

---

## 3. Directory Layout & Key File Map

```
kice-math-agent-infra/
├── PROJECT_STATE.json                  <-- System Status SSoT (Machine Readable State)
├── ENTRYPOINT.md                       <-- [You are here] Order 1 Entrypoint Guide
├── MANIFEST.json                       <-- Structured System Manifest (version SSoT: PROJECT_STATE.json)
├── docs/                               <-- Master Specifications & Plans
│   ├── SSOT_MAP.md                     <-- Taxonomy & Domain SSoT Declarations
│   ├── STAKEHOLDER_INTENT.md           <-- Value SSoT for Educators & Agents
│   ├── Taxonomy_Spec.md                <-- Order 2: Master 3-Layer 8-Axis Schema
│   ├── Master_Blueprint.md             <-- System Architecture Roadmap
│   └── Backlog.md                      <-- Milestone & Task Planning
├── pipeline/                           <-- Source Code & Agent Specifications
│   ├── query_engine/                   <-- Order 4: Query Helpers
│   │   ├── selective_fetcher.py        <-- Batch & 8-Axis Selective Fetcher
│   │   └── routing_index.json          <-- Keyword index; only 3 keys (~9 items). Prefer item_id/exam_id lookup.
│   ├── agents_spec/                    <-- Order 3: Agent Prompts
│   │   ├── router_orchestrator_agent.md
│   │   ├── axis1_curriculum_agent.md
│   │   ├── ...
│   │   └── axis8_knowledge_graph_agent.md
│   ├── migrate_db_8axis.py             <-- Historical migration: created the original 8-flat-column DDL
│   └── migrate_db_axis_agnostic.py     <-- I2 refactor: moved axis storage to analysis_derivation (current model)
├── storage/                            <-- 4-Tier Database & Assets
│   ├── parsed_dataset.db               <-- 1,350 Items SQLite DB. Axis data lives in the generic
│   │                                       `analysis_derivation(item_id, axis_key, schema_version,
│   │                                       payload, ...)` table (I2 axis-agnostic storage refactor);
│   │                                       `axis_analysis` is now a READ-ONLY COMPATIBILITY VIEW over
│   │                                       it, not 8 hardcoded flat columns. 99.8% of rows are still
│   │                                       placeholder analysis (3/1,350 real) -- see `ROUTING.md` §2a.
│   ├── kice_math_concept_map.json      <-- Ground-Truth Math Concept Map Dataset
│   └── assets/                         <-- 1,350 High-Res Diagram PNGs
└── tests/                              <-- Automated Verification Test Suite
```

---

## 4. Quick 1-Line Python Query Snippet for Agents

```python
from pipeline.query_engine.selective_fetcher import QuestionFetcher

fetcher = QuestionFetcher()
# Fetch question item with selected axes in single batch query (cold DB p95 < 10ms)
data = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_3', 'Axis_4'])
print(data['item_id'], data['answer'], data['axes'])
```
