# Zero-Context AI Agent Infra Entrypoint Guide (ENTRYPOINT.md)

Welcome to the **CSAT Mathematics Zero-Context Agent Infrastructure** inside kice-math-agent-infra/.
This document is your **Loading Order 1 Entrypoint**. Read this file first to achieve 100% project understanding while minimizing context token overhead.

---

## 1. Quick Project Summary
- **Target Domain**: 2027학년도 6월 평가원 기출 및 최근 10년+ 수능/평가원 수학 (공통, 미적분, 기하, 확률과통계).
- **Core Purpose**: End-to-end infrastructure allowing zero-context AI agents to retrieve, analyze, and reason about math questions using a 6-Axis Multi-Dimensional Taxonomy Schema without prior context.
- **Dataset Scale**: **1,350 CSAT/KICE exam questions** across 45 PDF papers (2021~2026) and **1,350 high-res 300 DPI diagram PNG assets** loaded into a 4-Tier SQLite DB (storage/parsed_dataset.db).

---

## 2. Recommended Context Loading Protocol (Loading Order 1 ~ 4)

To save tokens, do NOT load all files at once. Follow this 4-step protocol:

`mermaid
graph TD
    LO1[Loading Order 1: ENTRYPOINT.md & MANIFEST.json<br/>- Project Summary, Directory Map, DB Location] --> LO2[Loading Order 2: docs/Taxonomy_Spec.md<br/>- 6-Axis Schema & 4-Tier DB DDL]
    LO2 --> LO3[Loading Order 3: pipeline/agents_spec/router_orchestrator_agent.md<br/>- Master Router Protocol & Selective Fetching]
    LO3 --> LO4[Loading Order 4: pipeline/query_engine/selective_fetcher.py<br/>- Python 1-line DB/Axis Fetcher Helper]
`

- **Loading Order 1 (This File & MANIFEST.json)**: ~800 Tokens ➔ High-level overview & entrypoints.
- **Loading Order 2 ([docs/Taxonomy_Spec.md](file:///c:/Users/packr/Claude/kice-math-agent-infra/docs/Taxonomy_Spec.md))**: ~1,500 Tokens ➔ 6-Axis Schema & 4-Tier DB Table DDLs.
- **Loading Order 3 ([pipeline/agents_spec/router_orchestrator_agent.md](file:///c:/Users/packr/Claude/kice-math-agent-infra/pipeline/agents_spec/router_orchestrator_agent.md))**: ~1,500 Tokens ➔ Routing protocol & axis prompt specs.
- **Loading Order 4 ([pipeline/query_engine/selective_fetcher.py](file:///c:/Users/packr/Claude/kice-math-agent-infra/pipeline/query_engine/selective_fetcher.py))**: On-Demand ➔ 1-line Python DB query helper.

---

## 3. Directory Layout & Key File Map

`
kice-math-agent-infra/
├── ENTRYPOINT.md                       <-- [You are here] Order 1 Entrypoint Guide
├── MANIFEST.json                       <-- Structured System Manifest
├── docs/                               <-- Master Specifications & Plans
│   ├── Taxonomy_Spec.md                <-- Order 2: 6-Axis Schema & DB DDLs
│   ├── Master_Blueprint.md             <-- Overall System Architecture & Roadmap
│   ├── Scrapling_Research_Plan.md      <-- Web Research & Scrapling Integration Spec
│   ├── PDF_Parsing_Plan.md             <-- PDF/PNG Parsing Engine Spec
│   ├── Backlog.md                      <-- Project Backlog Items
│   └── Walkthrough_Report.md           <-- Phase 1 & 2 Completion Report
├── pipeline/                           <-- Source Code & Agent Specifications
│   ├── query_engine/                   <-- Order 4: Helper Modules
│   │   ├── selective_fetcher.py        <-- 1-line DB & Axis Fetcher Helper
│   │   └── routing_index.json          <-- Keyword to Routing Key Index
│   ├── agents_spec/                    <-- Order 3: 7 Agent Spec Prompts
│   │   ├── router_orchestrator_agent.md
│   │   ├── axis1_concept_routing_agent.md
│   │   ├── axis2_condition_parsing_agent.md
│   │   ├── axis3_misconception_trap_agent.md
│   │   ├── axis4a_core_idea_lineage_agent.md
│   │   ├── axis4b_condition_mutation_agent.md
│   │   └── axis5_target_2027_transformation_agent.md
│   ├── research_spiders/               <-- Scrapling Research Spiders
│   └── dataset_parser/                 <-- PDF Segmenter, LaTeX Extractor & Cropper
├── research_data/                      <-- Raw Scraped JSONs & Eval Reports
│   ├── raw/                            <-- Scraped JSON Data
│   └── eval/                           <-- Step 1 & 2 Eval Reports (99.9% Pass)
└── storage/                            <-- 4-Tier Database & Assets
    ├── parsed_dataset.db               <-- 1,350 Items SQLite DB
    └── assets/                         <-- 1,350 High-Res Diagram PNGs
`

---

## 4. Quick 1-Line Python Query Snippet for Agents

To fetch a question and its selected axes without writing raw SQL:

`python
from pipeline.query_engine.selective_fetcher import QuestionFetcher

fetcher = QuestionFetcher()
# Fetch question item with specific axes (saves tokens!)
data = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_2'])
print(data['item_id'], data['latex_content'], data['axes'])
`
