# Agent-Agnostic Infrastructure Context Deposit (AGENTS.md)

> **Deposit Metadata**  
> - **Deposit Timestamp**: 2026-07-24  
> - **Target Repository**: [kice-math-agent-infra](https://github.com/park-kyungchan/kice-math-agent-infra.git)  
> - **Workspace Path**: `C:\Users\packr\Claude\kice-math-agent-infra`  
> - **Compatibility**: Agent-Agnostic (Claude Code, OpenAI Codex, Antigravity/AGY, Gemini, Cursor, etc.)

---

## 1. System Environment & Tooling State

- **OS / Shell**: Windows 11 / PowerShell
- **GitHub CLI (`gh`) Setup**:
  - Global Authentication: Active (`park-kyungchan`)
  - Remote Repository: `https://github.com/park-kyungchan/kice-math-agent-infra.git`
  - Active Branch: `main` (Fully synchronized with `origin/main`)
  - Config Protocol: `HTTPS` (Keyring/Token authenticated)

---

## 2. Dataset & Storage Deposit

- **Target Domain**: 2027 CSAT/KICE Mathematics (Common + Calculus, Geometry, Probability & Statistics)
- **Primary Database**: `storage/parsed_dataset.db` (SQLite 4-Tier Schema)
- **Parsed Questions Scale**: 1,350 Items across 45 PDF papers (2021~2026)
- **Diagram Assets**: 1,350 300 DPI diagram PNG assets in `storage/assets/`
- **Schema Design**: 6-Axis Multi-Dimensional Taxonomy Schema (Detailed in `docs/Taxonomy_Spec.md`)

---

## 3. Recommended Protocol for AI Agents

Any AI Agent (Claude, Codex, Antigravity, etc.) interacting with this workspace should follow the token-efficient 4-step loading order:

1. **Order 1 (Entrypoint Overview)**: Read [ENTRYPOINT.md](ENTRYPOINT.md) and [MANIFEST.json](MANIFEST.json).
2. **Order 2 (Taxonomy & DDL)**: Read [docs/Taxonomy_Spec.md](docs/Taxonomy_Spec.md) for 6-Axis DB Schema.
3. **Order 3 (Router Specification)**: Read [pipeline/agents_spec/router_orchestrator_agent.md](pipeline/agents_spec/router_orchestrator_agent.md).
4. **Order 4 (Python Fetcher Helper)**: Execute `pipeline.query_engine.selective_fetcher.QuestionFetcher` for selective 1-line queries.

---

## 4. Quick Execution & Query Interface

```python
# Agent-agnostic Python fetcher snippet
from pipeline.query_engine.selective_fetcher import QuestionFetcher

fetcher = QuestionFetcher()
question_data = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_2'])
print(question_data['item_id'], question_data['latex_content'])
```

```powershell
# Git / GitHub synchronization check
git status
gh auth status
```
