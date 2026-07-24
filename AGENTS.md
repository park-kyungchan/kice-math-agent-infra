# Agent-Agnostic Infrastructure Context Deposit (AGENTS.md)

> **Deposit Metadata**  
> - **Deposit Timestamp**: 2026-07-24  
> - **Infrastructure Version**: `v2.5.0` (Deterministic Condition Parser, 4-Tier Automated Eval Harness & Clean Git Workflow)
> - **Target Repository**: [kice-math-agent-infra](https://github.com/park-kyungchan/kice-math-agent-infra.git)  
> - **Workspace Path**: `C:\Users\packr\Claude\kice-math-agent-infra`  
> - **Compatibility**: 100% Agent-Agnostic (Claude Code, OpenAI Codex, Antigravity/AGY, Gemini, Cursor, etc.)

---

## 1. System Environment & Tooling Deposit

- **OS / Shell**: Windows 11 / PowerShell
- **Database Engine**: SQLite 3 (`storage/parsed_dataset.db` with 8 Flat Columns & persistent indexing)
- **Python Runtime**: Python 3.10+ (`pipeline/query_engine/selective_fetcher.py`)
- **Automated Test Suite**: 17 Unit Tests in `tests/` (100.0% PASS, 0.004ms Batch SLA)
- **GitHub Synchronization**:
  - Account: `park-kyungchan`
  - Repository: `https://github.com/park-kyungchan/kice-math-agent-infra.git`
  - Active Branch: `main`

---

## 2. Dataset & Storage Infrastructure Deposit

- **Target Domain**: 2027 CSAT/KICE Mathematics (Common: Algebra/Calculus I, Elective: Calculus II, Geometry, Prob & Stat)
- **Primary Database**: `storage/parsed_dataset.db` (4-Tier SQLite Schema with `answer`, `correct_rate`, and 8 flat axis columns)
- **Parsed Questions Scale**: 1,350 CSAT/KICE Exam Items across 45 PDF papers (2021~2026)
- **Diagram Assets**: 1,350 cropped 300 DPI diagram PNG assets in `storage/assets/`
- **Concept Map Dataset**: `storage/kice_math_concept_map.json` (Ground-truth math ontology)
- **Terminology Lexicon**: `docs/Korean_Math_Glossary.json` (Korean-English math lexicon)

---

## 3. Master 8-Axis Flat Routing Map & Schema Summary

Any AI Agent initiating a new session should refer to the following **8 Flat Axes**:

| Axis ID | DB Column Name | Primary Functional Domain | Core Schema / Features |
| :--- | :--- | :--- | :--- |
| **Axis 1** | `axis1_curriculum` | Curriculum & Multi-Unit Integration | 2022 achievement standards, primary/secondary units, cross-unit coupling matrix, prerequisite concept graph. |
| **Axis 2** | `axis2_raw_parsing` | Literal Parsing & Normalization | KaTeX AMS-Math normalized syntax, 1:1 raw Korean condition extraction, target expression isolation. |
| **Axis 3** | `axis3_symbolic_modeling` | Symbolic Modeling & Concept Map | `storage/kice_math_concept_map.json` matching, difference functions, embedded shortcut solving suggestions. |
| **Axis 4** | `axis4_contextual_tree` | All-Domain Contextual Interpretation | **All 5 CSAT domains** (Sequences, Algebra, Geometry, ProbStat, Calculus) dynamic interpretation tree & Scratchpad `backtrack_log`. |
| **Axis 5** | `axis5_traps_verification` | Distractor Matrix & Verification | 16 student error codes (`DIST_CASE_SIGN`, etc.), ①~⑤ option matrix, 4-phase AI verification protocol (`ASSERT`, limit check, sanity). |
| **Axis 6** | `axis6_genealogy` | Core Idea Genealogy & Deep-Dive | 10-year mathematical gene codes (`GENE_ABS_DIFF_SMOOTH`), precedent linking via **`precedent_item_id` foreign keys** for instant deep-dive fetching. |
| **Axis 7** | `axis7_mutation` | Condition Representation Mutation | 10-year evolutionary chain of textual phrasing and symbolic representation shifts. |
| **Axis 8** | `axis8_knowledge_graph` | Knowledge Graph Topology | 1,350-item graph node/edge topology, degree centrality, and cluster IDs. |

---

## 4. Recommended Protocol for New AI Agent Sessions (Loading Order 1 ~ 4)

To minimize context token consumption while achieving 100% precision in new agent sessions:

1. **Order 1 (Entrypoint Overview)**: Read [ENTRYPOINT.md](ENTRYPOINT.md) and [MANIFEST.json](MANIFEST.json).
2. **Order 2 (Taxonomy Spec & DDL)**: Read [docs/Taxonomy_Spec.md](docs/Taxonomy_Spec.md).
3. **Order 3 (Master Router Spec)**: Read [pipeline/agents_spec/router_orchestrator_agent.md](pipeline/agents_spec/router_orchestrator_agent.md) & 100% English agent prompt specs in `pipeline/agents_spec/`.
4. **Order 4 (Python Selective & Batch Fetcher)**: Use `fetch_cli.py` or `QuestionFetcher` in `pipeline.query_engine.selective_fetcher`.

---

## 5. Quick Python Execution & Query Interface Code Snippet

```python
# Agent-Agnostic Python Fetcher Snippet for Item Analysis Pilot
from pipeline.query_engine.selective_fetcher import QuestionFetcher

fetcher = QuestionFetcher()

# 1. Single Item 8-Axis Fetch (< 0.01ms)
item = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_3', 'Axis_4'])
print("Item ID:", item['item_id'], "Score:", item['score'], "Answer:", item['answer'])
print("Fetched Axes:", list(item['axes'].keys()))

# 2. Batch Query API for Multi-Item Analysis
batch_items = fetcher.get_questions_batch(['202411_MATH_DIF_22', '202506_MATH_DIF_22'])
print(f"Successfully fetched {len(batch_items)} items in batch.")

# 3. Precedent Deep-Dive Fetching
precedent_id = item['axes'].get('Axis_6', {}).get('historical_precedents', [{}])[0].get('precedent_item_id')
if precedent_id:
    deep_dive_item = fetcher.get_question(precedent_id)
    print("Deep-Dive Precedent Item:", deep_dive_item['item_id'])
```

---

## 6. Critical Zero-Context Anti-Pattern Rules (Mandatory Enforcement)

To prevent multi-turn delays, token waste, and encoding errors:

1. **STRICTLY PROHIBITED**: Never execute inline shell commands (`python -c "..."`) with nested quotes or SQL strings in Windows PowerShell. This leads to quote escaping crashes (`SyntaxError`), CP949 encoding errors, user approval prompts, and token waste.
2. **MANDATORY CLI TOOL**: Always use the standardized CLI fetcher `pipeline/query_engine/fetch_cli.py`:
   ```powershell
   # Instant 1-line item query without quote escaping (0.005ms SLA)
   python pipeline/query_engine/fetch_cli.py --item 202606_MATH_DIF_15 --summary
   python pipeline/query_engine/fetch_cli.py --exam 202606 --number 15
   ```
3. **ZERO TOKEN WASTE**: Rely on `fetch_cli.py` or script imports. Do NOT attempt raw shell DB exploration.

```powershell
# Run Automated Test Suite
python -m unittest discover -s tests -p "test_*.py"

# Git / GitHub Synchronization Check
git status
gh auth status
```

