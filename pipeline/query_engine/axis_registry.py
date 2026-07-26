# -*- coding: utf-8 -*-
"""
Axis Registry (I2 axis-agnostic storage refactor)
===================================================
Single source of truth for axis IDENTITY: which axis keys exist, what they
are called, whether they are currently trustworthy (`active`), being
reconsidered (`under_review`), or retired (`deprecated`), what payload
schema_version they are currently on, and whether they ANALYSE an existing
item, GENERATE a new one, or are DERIVED from other axes.

WHY THIS EXISTS
---------------
The 8-axis taxonomy (`axis1_curriculum` .. `axis8_knowledge_graph`) is under
owner review — it may be redefined, reduced, or replaced — but it was
hard-committed into `axis_analysis` as 8 named DDL columns, so changing one
axis used to cost a migration + spec edit + gate edit + ~91 scattered code
edits (see ROUTING.md, "Open, unfixed" #3). This registry decouples axis
IDENTITY from schema: axes are now DATA (rows in the generic
`analysis_derivation` table, see pipeline/migrate_db_axis_agnostic.py), not
DDL. A brand-new axis needs a new `analysis_derivation` row with a new
`axis_key` string — no ALTER TABLE, no registry entry required either (the
storage layer is deliberately open-world; see `is_registered` below). A
registry entry is *governance metadata* (documentation of what an axis
means, its trust status, its category), never a write-time gate.

Multiple call sites in this codebase independently hand-wrote the same
"Axis_N <-> axisN_whatever" mapping (pipeline/query_engine/selective_fetcher.py
RAW_AXES dict, pipeline/query_engine/claim_provenance.py AXIS_COLUMN dict,
scripts/validate_ssot_consistency.py AXIS_COLUMNS tuple) — three
independently-maintained copies of one fact is exactly the drift risk this
module removes. Those three call sites now import from here.

KNOWN CATEGORY FINDINGS (recorded as governance metadata, never silently
normalised away — see each AxisDefinition.notes below for detail):
  - axis7_mutation is a GENERATOR, not an analyser: it produces mutated
    condition-representation variants rather than describing the item as
    given.
  - axis8_knowledge_graph is DERIVED from axes 1-7 (graph topology computed
    over their output) and carries no independent signal of its own.
  - axis4_contextual_tree records AGENT REASONING (backtrack telemetry),
    not a property of the item itself.
  - axis3_symbolic_modeling depends on storage/kice_math_concept_map.json,
    which holds only 3 concepts — structurally dead for the rest of the
    1,350-item corpus regardless of analysis effort.
"""
from typing import Dict, List, NamedTuple, Optional

STATUS_VALUES = ("active", "under_review", "deprecated")
KIND_VALUES = ("analyser", "generator", "derived")


class AxisDefinition(NamedTuple):
    axis_key: str
    """Canonical machine key. Stored verbatim in
    `analysis_derivation.axis_key`; also the name of the legacy flat
    column of the same name (still exposed read-only through the
    `axis_analysis` compatibility view — see
    pipeline/migrate_db_axis_agnostic.py)."""

    dict_key: str
    """Legacy dict-key convention used throughout the codebase's Python
    payloads / public API surface, e.g. 'Axis_1'
    (pipeline/query_engine/selective_fetcher.py item['axes'] keys,
    quality_plane_judges.py, independent_solver.py,
    report_generator/html_builder.py, ...). Unrelated to DB storage; this
    output CONTRACT is preserved byte-for-byte by this refactor."""

    human_name: str
    status: str            # one of STATUS_VALUES
    schema_version: int    # payload schema version this axis is currently on
    kind: str               # one of KIND_VALUES
    layer: int               # 1, 2, or 3 -- matches Taxonomy_Spec.md 3-Layer grouping
    notes: str = ""

    family: str = "legacy"
    """Which taxonomy this axis belongs to. "legacy" = the original eight, each
    backed by a flat `axis_analysis` column and by the byte-for-byte
    Axis_1..Axis_8 public output contract. "ce" = the conclusion-encoding
    redesign, which has NO flat column and MUST NOT enter AXIS_COLUMNS,
    AXIS_COLUMN_BY_DICT_KEY or DICT_KEY_BY_AXIS_COLUMN -- those three are the
    legacy contract and their consumers (selective_fetcher, claim_provenance,
    validate_ssot_consistency, migrate_db_axis_agnostic, generate_routing) all
    assume exactly eight entries."""


# Ordered axis1..axis8 -- order is load-bearing. scripts/validate_ssot_consistency.py
# (AXIS_COLUMNS), the axis_analysis compatibility view's column order, and
# pipeline/migrate_db_axis_agnostic.py all depend on this exact sequence
# matching the legacy DDL column order.
AXIS_DEFINITIONS: List[AxisDefinition] = [
    AxisDefinition(
        axis_key="axis1_curriculum", dict_key="Axis_1",
        human_name="Curriculum & Construct",
        status="deprecated", schema_version=1, kind="analyser", layer=1,
        notes=(
            "2022 revised curriculum achievement standards, cross-unit coupling "
            "matrix, prerequisite graph. As of 2026-07-25, 3/1350 items "
            "(202606_MATH_{DIF,GEO,PRO}_15) carry real per-item analysis; the "
            "remaining 1,347 are the single-key placeholder sentinel "
            "{'objective': 'OBJ_UNDERSTAND'}."
        ),
    ),
    AxisDefinition(
        axis_key="axis2_raw_parsing", dict_key="Axis_2",
        human_name="Literal Parsing & KaTeX Normalization",
        status="active", schema_version=1, kind="analyser", layer=1,
        notes=(
            "The one axis with genuinely 100% real, per-item analysis "
            "(1350/1350, normalized value entropy 0.89 as of 2026-07-25) -- "
            "the drift gate's most important false-positive control. Must "
            "never be flagged as a stub axis."
        ),
    ),
    AxisDefinition(
        axis_key="axis3_symbolic_modeling", dict_key="Axis_3",
        human_name="Symbolic Modeling (Standard vs Shortcut Solutions)",
        status="deprecated", schema_version=1, kind="analyser", layer=2,
        notes=(
            "Concept Map Integration depends on storage/kice_math_concept_map.json, "
            "which holds only 3 concepts -- this axis is structurally dead for "
            "the other 1,347 items regardless of analysis effort (ROUTING.md "
            "data-health note). 3/1350 items carry real analysis."
        ),
    ),
    AxisDefinition(
        axis_key="axis4_contextual_tree", dict_key="Axis_4",
        human_name="All-Domain Contextual Interpretation & Backtrack Tree",
        status="deprecated", schema_version=1, kind="analyser", layer=2,
        notes=(
            "Records AGENT REASONING (backtrack_log trial-and-error telemetry), "
            "not a property of the item itself -- a category difference from "
            "the other analyser axes; do not treat it as item metadata. "
            "0/1350 real; 1,347 are NULL (no stub JSON was ever written for "
            "this axis, unlike axis1/3/5/6)."
        ),
    ),
    AxisDefinition(
        axis_key="axis5_traps_verification", dict_key="Axis_5",
        human_name="Distractor Traps & Verification Protocol",
        status="deprecated", schema_version=1, kind="analyser", layer=2,
        notes=(
            "16 student error codes, is_simulated_hypothesis / "
            "review_required / confidence_score. 3/1350 items carry real "
            "analysis."
        ),
    ),
    AxisDefinition(
        axis_key="axis6_genealogy", dict_key="Axis_6",
        human_name="10-Year Core Mathematical Idea Genealogy",
        status="deprecated", schema_version=1, kind="analyser", layer=3,
        notes=(
            "7 closed lineage relation enums, precedent_item_id foreign "
            "keys. 3/1350 items carry real analysis."
        ),
    ),
    AxisDefinition(
        axis_key="axis7_mutation", dict_key="Axis_7",
        human_name="Condition Representation Mutation Chain",
        status="deprecated", schema_version=1, kind="generator", layer=3,
        notes=(
            "GENERATOR, not analyser: it tracks/produces mutated phrasing "
            "variants of an item's conditions rather than describing "
            "properties of the item as given. Classifying it as an analyser "
            "like the other 7 axes is a known category error in the current "
            "taxonomy. 0/1350 real; 1,347 NULL."
        ),
    ),
    AxisDefinition(
        axis_key="axis8_knowledge_graph", dict_key="Axis_8",
        human_name="Knowledge Graph Topology",
        status="deprecated", schema_version=1, kind="derived", layer=3,
        notes=(
            "DERIVED from axes 1-7 (graph node/edge topology, degree "
            "centrality, cluster IDs computed over the other axes' output) "
            "and carries no independent signal of its own -- a second known "
            "category error. 0/1350 real; 1,347 NULL."
        ),
    ),
    AxisDefinition(
        axis_key="ce.segmentation", dict_key="CE_Segmentation",
        human_name="Encoding Segmentation",
        status="under_review", schema_version=1, kind="analyser", layer=1,
        family="ce",
        notes=(
            "Cuts the item into atomic encoding units, including unlabelled global premises that sit outside the (가)/(나) markers but are load-bearing."
        ),
    ),
    AxisDefinition(
        axis_key="ce.semantics", dict_key="CE_Semantics",
        human_name="Unit Semantics",
        status="under_review", schema_version=1, kind="analyser", layer=1,
        family="ce",
        notes=(
            "What each unit constrains and which concept it attaches to. Fused deliberately: splitting object from concept reproduces the drift pattern this registry exists to remove. Runs concurrently per unit under a negative-context rule -- an instance may not see other units."
        ),
    ),
    AxisDefinition(
        axis_key="ce.relation", dict_key="CE_Relation",
        human_name="Unit Relation",
        status="under_review", schema_version=1, kind="analyser", layer=2,
        family="ce",
        notes=(
            "Relations among units: SEQUENTIAL_REFINEMENT, INDEPENDENT, IMPLICATION, MUTUAL_EXCLUSION, DUPLICATION, BACKGROUND_CONSTRAINT. Background constraints never become conclusion nodes or relatedness edges -- that classification is the primary defence against hub explosion."
        ),
    ),
    AxisDefinition(
        axis_key="ce.canonical", dict_key="CE_Canonical",
        human_name="Canonical Convergence",
        status="under_review", schema_version=1, kind="derived", layer=3,
        family="ce",
        notes=(
            "Whether differently-expressed conclusions converge. DERIVED: consumes verified conclusions, so it must not be scheduled concurrently with the stages that produce them."
        ),
    ),
    AxisDefinition(
        axis_key="ce.variance", dict_key="CE_Variance",
        human_name="Observed Variance",
        status="under_review", schema_version=1, kind="derived", layer=3,
        family="ce",
        notes=(
            "How the same conclusion is encoded differently across the corpus. DERIVED, same scheduling constraint as ce.canonical."
        ),
    ),
    AxisDefinition(
        axis_key="ce.altgen", dict_key="CE_AltGen",
        human_name="Alternative-Encoding Generator",
        status="under_review", schema_version=1, kind="generator", layer=3,
        family="ce",
        notes=(
            "GENERATOR, not an analyser: produces conditions that would force a given conclusion but were not observed. Every payload carries provenance_class SYNTHETIC and is excluded by default from variance and relatedness results."
        ),
    ),
]

LEGACY_AXIS_DEFINITIONS: List[AxisDefinition] = [d for d in AXIS_DEFINITIONS if d.family == "legacy"]
CE_AXIS_DEFINITIONS: List[AxisDefinition] = [d for d in AXIS_DEFINITIONS if d.family == "ce"]

AXIS_BY_KEY: Dict[str, AxisDefinition] = {d.axis_key: d for d in AXIS_DEFINITIONS}
AXIS_BY_DICT_KEY: Dict[str, AxisDefinition] = {d.dict_key: d for d in AXIS_DEFINITIONS}

# Backward-compatible ordered tuple of legacy column names, axis1..axis8 --
# the exact sequence the original `axis_analysis` DDL declared them in.
# scripts/validate_ssot_consistency.py imports this instead of hand-listing
# the 8 names a second time.
# LEGACY CONTRACT -- exactly the eight flat-column axes. See AxisDefinition.family.
AXIS_COLUMNS = tuple(d.axis_key for d in LEGACY_AXIS_DEFINITIONS)

# Backward-compatible {'Axis_1': 'axis1_curriculum', ...} / reverse mapping.
# pipeline/query_engine/claim_provenance.py and selective_fetcher.py import
# these instead of each hand-writing the same 8-entry dict independently.
AXIS_COLUMN_BY_DICT_KEY: Dict[str, str] = {d.dict_key: d.axis_key for d in LEGACY_AXIS_DEFINITIONS}
DICT_KEY_BY_AXIS_COLUMN: Dict[str, str] = {d.axis_key: d.dict_key for d in LEGACY_AXIS_DEFINITIONS}


def get_axis(axis_key: str) -> Optional[AxisDefinition]:
    return AXIS_BY_KEY.get(axis_key)


def get_axis_by_dict_key(dict_key: str) -> Optional[AxisDefinition]:
    return AXIS_BY_DICT_KEY.get(dict_key)


def all_axis_keys() -> List[str]:
    return [d.axis_key for d in AXIS_DEFINITIONS]


def is_registered(axis_key: str) -> bool:
    """False for an axis_key that has never been declared in this registry.
    This is NOT an error and must never be used to reject a write: a new,
    not-yet-registered axis_key is exactly the case
    `analysis_derivation` is designed to accept with zero DDL/registry
    change (mission requirement). `is_registered` exists for governance
    tooling (e.g. an audit that wants to flag "this axis_key has data but
    no documented identity yet") — the storage layer itself stays
    open-world."""
    return axis_key in AXIS_BY_KEY
