# Stakeholder Intent Artifacts

This document defines the core intents, pain points, expected workflows, and review criteria for the two primary stakeholders of the `kice-math-agent-infra` system.

## 1. Stakeholder: Math Instructor / Professional Educator

### 1.1 Objectives
* Efficiently source historically and mathematically linked CSAT/KICE items for curriculum development.
* Discover hidden structural analogies and parameter shifts between items spanning a 10-year period.
* Authoritatively verify or reject provisional AI-generated mathematical lineages.

### 1.2 Pain Points
* Manual traversal of thousands of items to find exact precedents is time-consuming and error-prone.
* Existing tagging systems rely on superficial surface similarities rather than deep mathematical core genes.
* Distinguishing between identical concepts and structural analogies is currently ambiguous.

### 1.3 Trusted Evidence
* Verifiable `DIRECT_GENEALOGY` and `MUTATION_TRANSFORM` linkages with historical precedent context.
* Clearly annotated distractor matrices (Axis 5) detailing standard errors.
* Precise mathematical notation adhering to KaTeX AMS-Math standards.

### 1.4 Feared Failures
* AI hallucinations presenting superficial similarities as deep mathematical genealogies (`REJECTED_RELATION`).
* Omission of critical contextual nuances (e.g., specific graph behaviors or shortcut logic).
* Opaque reasoning paths that educators cannot independently verify.

### 1.5 Expected Workflows
* **Query & Fetch:** Use standard API or CLI tools to retrieve item bundles based on `axis6_genealogy` genes.
* **Governance Loop:** Review `PROVISIONAL` lineage claims, mutating them to verified states or rejecting them based on mathematical rigor.
* **Curriculum Design:** Leverage verified precedent chains to construct diagnostic assessments.

### 1.6 Review Criteria
* Pedagogical accuracy and exactness in symbolic modeling.
* Clear distinction between standard solutions and prerequisite shortcuts.

---

## 2. Stakeholder: Autonomous Zero-Context AI Agent

### 2.1 Objectives
* Seamlessly ingest and navigate the 3-Layer 8-Axis dataset without relying on opaque conversational context.
* Independently execute tasks (e.g., query, reasoning, classification) using deterministic APIs and structural schemas.
* Contribute provisional knowledge graphs (e.g., new analogies) back into the dataset for human review.

### 2.2 Pain Points
* Token waste and context degradation when parsing massive raw documents or traversing poorly structured directories.
* Syntax errors from executing unstructured OS commands or complex shell scripts.
* Lack of deterministic data schemas leading to inconsistent tool usage.

### 2.3 Trusted Evidence
* Standardized, machine-readable schemas (`Taxonomy_Spec.md`, `PROJECT_STATE.json`).
* Flat DB queries allowing instant filtering of required axes.
* 100% agent-agnostic prompt specifications (`pipeline/agents_spec/`).

### 2.4 Feared Failures
* Being trapped in complex quote-escaping or shell-encoding bugs (e.g., CP949 errors).
* Recursive context bloat leading to execution collapse.
* Lack of clear entry points resulting in speculative and hallucinated tool calls.

### 2.5 Expected Workflows
* **Bootstrap:** Read `ENTRYPOINT.md` and `MANIFEST.json`.
* **Understand Bounds:** Read `docs/Taxonomy_Spec.md` and `docs/SSOT_MAP.md`.
* **Execute:** Utilize `pipeline/query_engine/fetch_cli.py` for deterministic data retrieval.
* **Report:** Output strictly formatted JSON or markdown reports based on retrieved DB axes.

### 2.6 Review Criteria
* Performance SLA (single definition — all other docs reference this table):

| Operation | p95 target | Measurement condition |
|---|---|---|
| Cold DB batch fetch (6 items) | < 10 ms | fresh connection, no in-process cache |
| Warm cache batch fetch (6 items) | < 0.1 ms | in-process cache hit after warm-up |
| Review queue scan (1,350 items) | < 500 ms | persisted `review_status` index query |
| Lineage traversal (depth 3) | < 100 ms | recursive precedent walk |

* Adherence to zero-context anti-pattern rules (e.g., no inline shell scripts).
* Strict compliance with the 7 closed lineage relation enums.
* Review workflow actions go through the state machine CLI; illegal transitions must fail with a non-zero exit code and zero DB writes.
