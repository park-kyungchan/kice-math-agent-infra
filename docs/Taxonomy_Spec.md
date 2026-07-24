# CSAT Mathematics Multi-Dimensional Analysis Architecture Specification (Taxonomy_Spec.md)

This specification defines the **Master 8-Axis Taxonomy Schema** and 4-Tier SQLite Database DDL for zero-context agent reasoning across **1,350 CSAT/KICE Mathematics questions (2015–2026)**.

---

## 1. Standardized 8-Axis Flat Architecture

```mermaid
graph TD
    Item[Question Item / LaTeX] --> A1[Axis 1: Curriculum & Multi-Unit Integration]
    Item --> A2[Axis 2: Literal Parsing & KaTeX Normalization]
    Item --> A3[Axis 3: Symbolic Modeling & Concept Map Matching]
    Item --> A4[Axis 4: All-Domain Contextual Interpretation Tree]
    Item --> A5[Axis 5: Distractor Matrix & Verification Protocol]
    
    subgraph Macro Lineage Engine (Data-Driven Graph Topology)
        A1 & A2 & A3 & A4 & A5 --> A6[Axis 6: 10-Year Core Mathematical Idea Genealogy]
        A6 --> A7[Axis 7: Condition Representation Mutation Chain]
        A7 --> A8[Axis 8: Knowledge Graph & Topological Indexing]
    end
```

### [Axis 1] Curriculum & Multi-Unit Integration (`axis1_curriculum`)
- **Primary & Secondary Units**: 2022 revised curriculum achievement standards (`12CALC1-02-03`, etc.).
- **Cross-Unit Coupling Matrix**: Maps interlock between distinct mathematical units.
- **Prerequisite Graph**: Directed prerequisite concept dependency graph.

### [Axis 2] Literal Parsing & Normalization (`axis2_raw_parsing`)
- **KaTeX Normalization**: Converts legacy TeX syntax to standard KaTeX/AMS-Math delimiters.
- **Literal Extraction**: Separates raw Korean text conditions `(가)`, `(나)`, `(다)` without inference.

### [Axis 3] Symbolic Modeling & Concept Map Matching (`axis3_symbolic_modeling`)
- **Concept Map Integration**: Matches LaTeX expressions to `storage/kice_math_concept_map.json`.
- **Shortcut Suggestions**: Embeds supplementary polynomial ratio rules and area formulas.

### [Axis 4] All-Domain Contextual Interpretation Tree (`axis4_contextual_tree`)
- **All-Domain Coverage**: Covers Sequences/Discrete, Algebra/Trig, Geometry/Vectors, ProbStat, Calculus/Functions.
- **Backtrack Telemetry**: Records explicit trial-and-error reasoning and contradiction resolution in `backtrack_log`.

### [Axis 5] Distractor Matrix & Verification Protocol (`axis5_traps_verification`)
- **16 Student Error Codes**: Catalogs student error patterns (`DIST_CASE_SIGN`, `DIST_SMOOTH_TRIPLE_ROOT`, etc.).
- **4-Phase Verification**: Pre-assertions $\to$ Limit checks $\to$ Distractor collision test $\to$ Sanity check.

### [Axis 6] 10-Year Core Mathematical Idea Genealogy (`axis6_genealogy`)
- **Deep-Dive Item Routing**: Stores precedents using exact database foreign keys (`precedent_item_id`).

### [Axis 7] Condition Representation Mutation Chain (`axis7_mutation`)
- **Evolutionary Tracking**: Tracks historical shifts in textual phrasing and symbolic notation.

### [Axis 8] Knowledge Graph Topology (`axis8_knowledge_graph`)
- **Graph Topology**: 1,350-item graph node/edge topology, degree centrality, and cluster IDs.

---

## 2. 4-Tier SQLite Entity Schema DDL (`storage/parsed_dataset.db`)

```sql
-- Tier 1: Exam Event
CREATE TABLE exam_event (
    exam_id TEXT PRIMARY KEY,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    track TEXT NOT NULL,
    is_kice INTEGER NOT NULL
);

-- Tier 2: Question Item
CREATE TABLE question_item (
    item_id TEXT PRIMARY KEY,
    exam_id TEXT REFERENCES exam_event(exam_id),
    track TEXT NOT NULL,
    item_number INTEGER NOT NULL,
    score INTEGER NOT NULL,
    answer INTEGER NOT NULL DEFAULT 0,
    correct_rate REAL,
    latex_content TEXT NOT NULL,
    asset_image_url TEXT,
    rect_json TEXT
);

-- Tier 3: Axis Analysis (8 Flat JSON Columns)
CREATE TABLE axis_analysis (
    item_id TEXT PRIMARY KEY REFERENCES question_item(item_id) ON DELETE CASCADE,
    axis1_curriculum TEXT,          -- JSON string (Axis 1)
    axis2_raw_parsing TEXT,          -- JSON string (Axis 2)
    axis3_symbolic_modeling TEXT,   -- JSON string (Axis 3)
    axis4_contextual_tree TEXT,     -- JSON string (Axis 4)
    axis5_traps_verification TEXT,  -- JSON string (Axis 5)
    axis6_genealogy TEXT,           -- JSON string (Axis 6)
    axis7_mutation TEXT,            -- JSON string (Axis 7)
    axis8_knowledge_graph TEXT,     -- JSON string (Axis 8)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tier 4: Source Attribution
CREATE TABLE source_attribution (
    attribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT REFERENCES question_item(item_id),
    source_name TEXT,
    pdf_path TEXT,
    png_path TEXT
);
```

---

## 3. Quick Python Fetcher Usage

```python
from pipeline.query_engine.selective_fetcher import QuestionFetcher

fetcher = QuestionFetcher()

# Single Item Fetch with Selective Axes
item = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_3', 'Axis_4'])
print(item['item_id'], item['answer'], item['axes'].keys())

# Batch Item Fetch (<10ms SLA)
batch = fetcher.get_questions_batch(['202411_MATH_DIF_22', '202506_MATH_DIF_22'])
print(f"Fetched {len(batch)} items in single batch query.")
```
