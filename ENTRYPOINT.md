# Zero-Context AI Agent Infra Entrypoint Guide (ENTRYPOINT.md)

Welcome to the **CSAT Mathematics Zero-Context Agent Infrastructure** inside `kice-math-agent-infra/`.
This document is your **Loading Order 1 Entrypoint Guide**.

---

## 1. Quick Project Summary
- **Target Domain**: 2027 KICE Mock & CSAT Mathematics (Common: Algebra/Calculus I, Elective: Calculus II, Geometry, Prob & Stat).
- **Target User Personas**: Zero-Context Autonomous AI Agents & **Math Instructors / Professional Educators**.
- **Core Purpose**: End-to-end infrastructure allowing zero-context AI agents and Math Instructors to retrieve, reason, verify, and link math questions using the **3-Layer 8-Axis Taxonomy Architecture** (v2.7.0).
- **Dataset Scale**: **1,350 CSAT/KICE exam questions** across 45 PDF papers (2021~2026) and **1,350 high-res 300 DPI diagram PNG assets** loaded into a 4-Tier SQLite DB (`storage/parsed_dataset.db`).

---

## 2. Recommended Context Loading Protocol (Loading Order 1 ~ 4)

```mermaid
graph TD
    LO1["Loading Order 1: ENTRYPOINT.md & MANIFEST.json<br/>- Project Summary, Directory Map, DB Location"] --> LO2["Loading Order 2: docs/Taxonomy_Spec.md<br/>- 3-Layer 8-Axis Schema & 4-Tier DB DDL"]
    LO2 --> LO3["Loading Order 3: pipeline/agents_spec/router_orchestrator_agent.md<br/>- Master Router Protocol & 100% English Agent Specs"]
    LO3 --> LO4["Loading Order 4: pipeline/query_engine/selective_fetcher.py<br/>- Python 1-line DB & Batch Fetcher Helper"]
```

- **Loading Order 1 (This File & MANIFEST.json)**: High-level overview & entrypoints (v2.7.0 - 3-Layer Taxonomy & Semantic Eval Harness).
- **Loading Order 2 ([docs/Taxonomy_Spec.md](file:///c:/Users/packr/Claude/kice-math-agent-infra/docs/Taxonomy_Spec.md))**: Master 3-Layer 8-Axis Schema & 4-Tier DB Table DDLs.
- **Loading Order 3 ([pipeline/agents_spec/router_orchestrator_agent.md](file:///c:/Users/packr/Claude/kice-math-agent-infra/pipeline/agents_spec/router_orchestrator_agent.md))**: 100% English Master Router & 8 Axis Agent Specs.
- **Loading Order 4 ([pipeline/query_engine/selective_fetcher.py](file:///c:/Users/packr/Claude/kice-math-agent-infra/pipeline/query_engine/selective_fetcher.py))**: High-performance batch fetcher helper (`get_questions_batch()`, latency $<10\text{ ms}$).

---

## 3. Directory Layout & Key File Map

```
kice-math-agent-infra/
├── ENTRYPOINT.md                       <-- [You are here] Order 1 Entrypoint Guide (v2.7.0)
├── MANIFEST.json                       <-- Structured System Manifest (3-Layer 8-Axis Spec)
├── docs/                               <-- Master Specifications & Plans
│   ├── Taxonomy_Spec.md                <-- Order 2: Master 3-Layer 8-Axis Schema & DB DDLs
│   ├── Korean_Math_Glossary.json       <-- Korean-English Math Lexicon
│   ├── Master_Blueprint.md             <-- System Architecture Roadmap
│   └── Walkthrough_Report.md           <-- Phase Completion Report
├── pipeline/                           <-- Source Code & Agent Specifications
│   ├── query_engine/                   <-- Order 4: Query Helpers
│   │   ├── selective_fetcher.py        <-- Batch & 8-Axis Selective Fetcher
│   │   └── routing_index.json          <-- Keyword to Routing Key Index
│   ├── agents_spec/                    <-- Order 3: 9 100% English Agent Prompts
│   │   ├── router_orchestrator_agent.md
│   │   ├── axis1_curriculum_agent.md
│   │   ├── axis2_raw_parsing_agent.md
│   │   ├── axis3_symbolic_modeling_agent.md
│   │   ├── axis4_contextual_tree_agent.md
│   │   ├── axis5_traps_verification_agent.md
│   │   ├── axis6_genealogy_agent.md
│   │   ├── axis7_mutation_agent.md
│   │   └── axis8_knowledge_graph_agent.md
│   └── migrate_db_8axis.py             <-- DB Migration Engine
├── storage/                            <-- 4-Tier Database & Assets
│   ├── parsed_dataset.db               <-- 1,350 Items SQLite DB (8 Flat Columns across 3 Layers)
│   ├── kice_math_concept_map.json      <-- Ground-Truth Math Concept Map Dataset
│   └── assets/                         <-- 1,350 High-Res Diagram PNGs
└── tests/                              <-- Automated Verification Test Suite
    ├── test_db_migration.py            <-- DB Migration Integrity Test
    ├── test_selective_fetcher.py       <-- Batch Fetch & Latency SLA Test (<10ms)
    └── test_concept_map.py             <-- KaTeX & Concept Map Test
```

---

## 4. Quick 1-Line Python Query Snippet for Agents

```python
from pipeline.query_engine.selective_fetcher import QuestionFetcher

fetcher = QuestionFetcher()
# Fetch question item with selected axes in single batch query (<10ms)
data = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_3', 'Axis_4'])
print(data['item_id'], data['answer'], data['axes'])
```
