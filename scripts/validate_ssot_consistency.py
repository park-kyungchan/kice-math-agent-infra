# -*- coding: utf-8 -*-
"""
SSoT Consistency Validator (drift gate)
=======================================
Fails (exit 1) on any drift between declared SSoT documents and reality:

  1. DDL drift      — docs/Taxonomy_Spec.md CREATE TABLE column sets vs the
                      live storage/parsed_dataset.db schema (PRAGMA).
  2. State drift    — MANIFEST.json must reference PROJECT_STATE.json
                      (project_state_ref) and must NOT duplicate dynamic
                      eval/proof state (eval_gate_score / eval_status keys).
  3. Version drift  — version strings across PROJECT_STATE.json, MANIFEST.json,
                      docs/Taxonomy_Spec.md, docs/SSOT_MAP.md must agree.
  4. Matrix drift   — the transition table documented in Taxonomy_Spec.md must
                      match review_state.ALLOWED_TRANSITIONS (code is source).
  5. ci_evidence    — PROJECT_STATE.json ci_status claims must be bound to a
                      structured, internally-consistent ci_evidence object.

Content-completeness drift (the structural checks above are silent about
whether the DATA behind those structures is real, so they can pass on a
database that is 99.8% placeholder rows — "true-by-construction and
meaningless". These checks close that hole):

  6. PUA drift      — question_item.latex_content AND analysis_derivation.
                      payload (JSON-decoded before scanning -- payloads are
                      stored via json.dumps(ensure_ascii=True), so a PUA
                      codepoint sits in the DB as the literal ASCII escape
                      sequence \\uXXXX, invisible to a raw-text scan) must
                      contain no Unicode Private-Use-Area codepoints
                      (U+E000-U+F8FF, plus the Supplementary PUA planes and
                      U+FFFD); their presence means the HWP equation-font
                      extraction defect has regressed past the repair table.
  7. Stub drift     — axis_analysis payloads must be real per-item analysis,
                      not single-key placeholder sentinels or mass-duplicated
                      boilerplate copy-pasted across rows.
  8. Answer drift   — question_item.answer / canonical_answer_json must encode
                      real, item-specific grading data, not a uniform/degenerate
                      placeholder value or a SHORT_ANSWER mislabel on an item
                      that is visibly multiple-choice.

  9. Routing drift  — ROUTING.md must be exactly what tools/generate_routing.py
                      would produce right now (regenerated to an in-memory
                      buffer and diffed byte-for-byte against the committed
                      file). ROUTING.md is a GENERATED artifact (measured DB/
                      repo facts + the editorial judgments in
                      tools/routing_editorial.py); this closes the same hole
                      check 6/7/8 closed for axis_analysis -- a hand-edited or
                      stale ROUTING.md would otherwise pass every other check
                      in this file while confidently routing agents to a
                      layout, environment claim, or data-health figure that no
                      longer matches reality.

LIMITATIONS (read before trusting a green gate) -----------------------------
This gate is a STATIC / STRUCTURAL / STATISTICAL check. It proves the
*shape* of the data is not degenerate; it does NOT and CANNOT prove the
data is semantically correct. Concretely:

  - check_answer_sanity can only detect that answers are NOT uniform,
    NOT dominated by one placeholder value, and NOT mislabeled/out-of-range
    for items it recognizes as multiple-choice. A well-distributed but
    entirely FABRICATED answer key (e.g. a deterministic hash standing in
    for real grading data) is statistically indistinguishable from a real
    one to this check and WILL pass. "Answer sanity: OK" means "the answer
    column is not a degenerate placeholder" — it never means "the answers
    are correct." Verifying actual correctness requires grading against a
    real answer key (human review / an external oracle), which is out of
    scope for a repo-structure drift gate.
  - The multiple-choice-specific sub-checks (SHORT_ANSWER mislabel,
    out-of-range answer) key off the literal CHOICE_MARKER constant
    ('[CHOICE_1]'). If the upstream extractor's choice-marker convention
    ever changes (different tag, different case, circled-digit glyphs,
    etc.) those two sub-checks silently stop firing for the affected rows
    — see the CHOICE_MARKER definition below for the exact contract this
    depends on.
  - check_axis_stub_sentinels and check_pua_free_text are heuristic
    pattern/statistics detectors (opaque-scalar shape, payload-value
    entropy, Unicode Private-Use-Area ranges). They are tuned against the
    specific defect classes this repo has actually hit and adversarially
    hardened against several evasions (case games, non-string placeholder
    values, sub-threshold/bucketed duplication, non-BMP PUA planes,
    U+FFFD mojibake) — see AXIS_ENTROPY_RATIO_THRESHOLD and STUB_TOKEN_RE
    below. They are not proofs of realness; a sufficiently rich-looking
    fabricated payload (long, multi-key, varied per row, no PUA
    codepoints) can still pass.

In short: a green run of this gate proves "the data is not an obviously
degenerate placeholder by any pattern we know to check for" — never
"the data is correct." Treat every PASS as necessary, not sufficient.
-------------------------------------------------------------------------

Usage: python scripts/validate_ssot_consistency.py [--db PATH]
"""
import argparse
import collections
import json
import math
import os
import re
import sqlite3
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

TAXONOMY_SPEC = os.path.join(BASE_DIR, 'docs', 'Taxonomy_Spec.md')
SSOT_MAP = os.path.join(BASE_DIR, 'docs', 'SSOT_MAP.md')
MANIFEST = os.path.join(BASE_DIR, 'MANIFEST.json')
PROJECT_STATE = os.path.join(BASE_DIR, 'PROJECT_STATE.json')
DEFAULT_DB = os.path.join(BASE_DIR, 'storage', 'parsed_dataset.db')

GOVERNED_TABLES = ('question_item', 'teacher_review_event', 'claim_provenance', 'axis_analysis')

# --- content-completeness policy knobs -------------------------------------
# Private-Use-Area codepoints HWP dumps its custom equation-font glyphs into,
# PLUS the other "unmapped glyph" corruption shapes the same extraction
# defect class can take:
#   -       BMP Private Use Area (the originally-observed shape;
#                       verified as the sole shape in today's live DB).
#   �              REPLACEMENT CHARACTER -- the standard Unicode
#                       fallback most text pipelines (browsers, DB drivers,
#                       subprocess encoding mismatches) emit for an
#                       unmappable glyph, distinct from PUA but structurally
#                       the same failure class (mission Hole E).
#   \U000F0000-\U000FFFFD   Supplementary Private Use Area-A (Plane 15).
#   \U00100000-\U0010FFFD   Supplementary Private Use Area-B (Plane 16).
#                       Not yet observed in this pipeline's live data, but a
#                       latent gap for any future extractor/font-embedding
#                       path that dumps glyphs into the supplementary planes
#                       instead of the BMP block (mission Hole D).
PUA_RE = re.compile(
    '[-�\U000f0000-\U000ffffd\U00100000-\U0010fffd]'
)

# axis_analysis columns governed by the stub-sentinel scan. Sourced from the
# axis registry (pipeline/query_engine/axis_registry.py) -- the single
# source of axis identity as of the I2 axis-agnostic storage refactor --
# instead of hand-listing the 8 names a second time here.
from pipeline.query_engine.axis_registry import AXIS_COLUMNS, AXIS_BY_KEY  # noqa: E402
# A short, whitespace-free, identifier/number-like token -- the shape a
# hand-written placeholder sentinel takes, e.g. "OBJ_UNDERSTAND",
# "obj_understand_837", "SKILL_BASIC", or a bare numeric id "837". Real,
# per-item analysis text is natural language: it contains spaces (it is a
# sentence/phrase), so it never matches this pattern regardless of length.
# Deliberately case-insensitive by construction (the character class covers
# both cases) and unbothered by embedded/trailing digits -- closes the
# "lowercase the token and append a row index" evasion (mission Hole A),
# which defeated an earlier ALL-CAPS-only version of this pattern.
STUB_TOKEN_RE = re.compile(r'^[A-Za-z0-9_]+$')
# Fallback/robustness net: even if a future placeholder generator stops
# using the single-key/bare-token shape, byte-identical payloads copy-pasted
# across a large fraction of rows for the same axis are still not "real,
# item-specific analysis" -- flag mass duplication directly.
AXIS_DUP_RATIO_THRESHOLD = 0.30
# Second, independent robustness net (mission Hole C): AXIS_DUP_RATIO_THRESHOLD
# is a single fixed cutoff on the single MOST common value, which is
# trivially sittable -- e.g. one dominant placeholder held at 29.9% (just
# under the 30% cutoff) with the remainder uniquified, or boilerplate
# round-robin-split across >=4 near-identical buckets each individually
# under 30%. Neither trips the single-dominant-value rule even though the
# whole column is still low-information filler. This net instead looks at
# the SHAPE of the entire value distribution via normalized Shannon entropy:
# genuinely real, independently-authored per-item analysis is close to
# maximally diverse (entropy ratio ~1.0 -- every row differs meaningfully
# from every other row), while templated/bucketed/near-duplicate filler
# concentrates probability mass on a small number of distinct payloads even
# when no single value clears the dominance cutoff, which drags the
# normalized entropy well below 1.0. Only evaluated when the dominance rule
# above did NOT already fire (it is a supplement, not a replacement, and
# firing both on the same axis for the same underlying defect would just be
# double-reporting one root cause).
AXIS_ENTROPY_RATIO_THRESHOLD = 0.85
# An axis column must carry real (non-stub, non-empty) analysis for at least
# this fraction of the corpus to be considered governance-complete.
AXIS_REAL_RATIO_THRESHOLD = 0.95

# question_item.answer must not be dominated by a single placeholder value.
ANSWER_DOMINANCE_THRESHOLD = 0.90
MC_ANSWER_RANGE = (1, 2, 3, 4, 5)
# The literal substring the HWP extractor normalizes multiple-choice options
# to (verified: 100% of this pipeline's live MC items use this exact tag
# today). check_answer_sanity's two MC-specific sub-checks (SHORT_ANSWER
# mislabel, out-of-range answer) can ONLY see an item as multiple-choice by
# finding this literal substring in latex_content -- there is no fallback
# heuristic. If the upstream extractor's marker convention ever changes
# (different tag text, different case/spacing, circled-digit glyphs like
# "① ② ③", etc.) those two sub-checks go silently dark for every row using
# the new convention, with zero partial credit or warning (mission Hole F).
# The dominance/uniformity sub-check is marker-agnostic and is NOT affected.
CHOICE_MARKER = '[CHOICE_1]'


def _read(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def spec_table_columns(spec_text: str, table: str):
    """Extract column names for a CREATE TABLE block in the markdown DDL."""
    m = re.search(
        rf'CREATE TABLE "?{table}"?\s*\((.*?)\n\);', spec_text, re.S
    )
    if not m:
        return None
    cols = []
    depth = 0
    for raw_line in m.group(1).splitlines():
        line = raw_line.split('--')[0].strip()
        if not line:
            continue
        if depth == 0:
            first = line.split()[0].strip(',')
            if first and first.upper() not in (
                'CHECK', 'FOREIGN', 'PRIMARY', 'UNIQUE', 'CONSTRAINT', ')'
            ):
                cols.append(first)
        depth += line.count('(') - line.count(')')
    return cols


def db_table_columns(conn, table: str):
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return [r[1] for r in rows] or None


def check_ddl(errors, db_path):
    spec = _read(TAXONOMY_SPEC)
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    for table in GOVERNED_TABLES:
        spec_cols = spec_table_columns(spec, table)
        live_cols = db_table_columns(conn, table)
        if spec_cols is None:
            errors.append(f'DDL: table {table} missing from Taxonomy_Spec.md DDL')
            continue
        if live_cols is None:
            errors.append(f'DDL: table {table} missing from live DB {db_path}')
            continue
        if set(spec_cols) != set(live_cols):
            errors.append(
                f'DDL drift on {table}: spec-only={sorted(set(spec_cols) - set(live_cols))} '
                f'db-only={sorted(set(live_cols) - set(spec_cols))}'
            )
    # CHECK constraint presence on live DB
    ddl_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='question_item'"
    ).fetchone()
    if ddl_row and 'review_status IN' not in (ddl_row[0] or '').replace('\n', ' '):
        errors.append('DDL: live question_item lacks review_status CHECK constraint')

    # P1-1: verify the append-only triggers exist on the live DB (drift gate
    # for the audit-immutability invariant, not just column sets).
    trigger_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='teacher_review_event'"
    ).fetchall()
    trigger_names = {r[0] for r in trigger_rows}
    for required in ('teacher_review_event_no_update', 'teacher_review_event_no_delete'):
        if required not in trigger_names:
            errors.append(f'DDL: live DB missing append-only trigger {required} on teacher_review_event')

    conn.close()


def check_manifest_vs_state(errors):
    manifest = json.loads(_read(MANIFEST))
    if manifest.get('project_state_ref') != 'PROJECT_STATE.json':
        errors.append('MANIFEST.json missing project_state_ref -> PROJECT_STATE.json')
    flat = json.dumps(manifest)
    for forbidden in ('eval_gate_score', 'eval_status'):
        if f'"{forbidden}"' in flat:
            errors.append(
                f'MANIFEST.json duplicates dynamic state key {forbidden!r} '
                '(PROJECT_STATE.json is the only authority)'
            )


def check_versions(errors):
    state = json.loads(_read(PROJECT_STATE))
    version = state.get('version', '')
    if not re.fullmatch(r'v\d+\.\d+\.\d+(-[a-z0-9\.]+)?', version):
        errors.append(f'PROJECT_STATE.json version malformed: {version!r}')
        return
    manifest = json.loads(_read(MANIFEST))
    if manifest.get('version') != version:
        errors.append(
            f'Version drift: MANIFEST.json={manifest.get("version")!r} vs PROJECT_STATE.json={version!r}'
        )
    for path in (TAXONOMY_SPEC, SSOT_MAP):
        text = _read(path)
        if version not in text:
            errors.append(f'Version drift: {os.path.relpath(path, BASE_DIR)} does not mention {version}')


def check_transition_matrix(errors):
    from pipeline.query_engine.review_state import ALLOWED_TRANSITIONS, REVIEW_STATES
    spec = _read(TAXONOMY_SPEC)
    for state in REVIEW_STATES:
        if f'`{state}`' not in spec:
            errors.append(f'Matrix drift: state {state} not documented in Taxonomy_Spec.md')
    # Every documented "From | Allowed To" row must match code
    for m in re.finditer(r'^\|\s*`(\w+)`\s*\|\s*([^|]*)\|', spec, re.M):
        frm, to_cell = m.group(1), m.group(2)
        if frm not in ALLOWED_TRANSITIONS:
            continue
        doc_targets = set(re.findall(r'`(\w+)`', to_cell))
        code_targets = ALLOWED_TRANSITIONS[frm]
        if doc_targets and doc_targets != code_targets:
            errors.append(
                f'Matrix drift on {frm}: doc={sorted(doc_targets)} code={sorted(code_targets)}'
            )


def check_ci_evidence(errors):
    state = json.loads(_read(PROJECT_STATE))
    evidence = state.get('ci_evidence', {})
    if not isinstance(evidence, dict) or not evidence:
        errors.append('ci_evidence: missing or invalid ci_evidence object in PROJECT_STATE.json')
        return

    for key in ('workflow', 'run_id', 'tested_head_sha', 'conclusion', 'verified_at'):
        if key not in evidence:
            errors.append(f'ci_evidence: missing required key {key!r}')

    conclusion = evidence.get('conclusion')
    run_id = evidence.get('run_id')
    sha = evidence.get('tested_head_sha')
    verified_at = evidence.get('verified_at')

    if conclusion == 'success':
        if not isinstance(run_id, int) or run_id <= 0:
            errors.append(f'ci_evidence: conclusion is success but run_id must be > 0, got {run_id!r}')
        if not isinstance(sha, str) or not re.fullmatch(r'^[0-9a-f]{40}$', sha) or sha == '0' * 40:
            errors.append(f'ci_evidence: conclusion is success but tested_head_sha must be 40 non-zero hex chars, got {sha!r}')
        if not isinstance(verified_at, str) or not re.fullmatch(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', verified_at):
            errors.append(f'ci_evidence: conclusion is success but verified_at must be RFC 3339 timestamp, got {verified_at!r}')
        if state.get('ci_status') != 'GOVERNANCE_CI_GREEN':
            errors.append(f"ci_evidence: conclusion is success but ci_status must be 'GOVERNANCE_CI_GREEN', got {state.get('ci_status')!r}")
        if state.get('teacher_governance_loop') not in ('ACTIVE', 'ACTIVE_TRUSTED_LOCAL'):
            errors.append(f"ci_evidence: conclusion is success but teacher_governance_loop must be 'ACTIVE' or 'ACTIVE_TRUSTED_LOCAL', got {state.get('teacher_governance_loop')!r}")
    else:
        if state.get('teacher_governance_loop') == 'ACTIVE':
            errors.append(f"ci_evidence: non-success conclusion {conclusion!r} cannot permit teacher_governance_loop 'ACTIVE'")


def _iter_json_strings(obj):
    """Recursively yield every string leaf inside a decoded JSON value
    (dict/list/str/number/bool/None). Numbers/bools/None contribute no
    strings and are skipped; this is the traversal that lets a PUA/U+FFFD
    scan see INSIDE a JSON structure rather than only at its top level."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_json_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_json_strings(v)


def check_pua_free_text(errors, db_path):
    """Content-completeness (6): both question_item.latex_content AND
    analysis_derivation.payload must contain no unmapped-glyph corruption
    codepoints: the BMP Private Use Area (U+E000-U+F8FF), the Supplementary
    Private Use Areas A/B (U+F0000-U+FFFFD, U+100000-U+10FFFD), or U+FFFD
    REPLACEMENT CHARACTER (see PUA_RE above for the full range list and
    rationale). Their presence means the HWP equation-font extraction defect
    (glyphs dumped into an unmapped/private-use codepoint instead of being
    mapped to real Unicode/LaTeX) has regressed past the repair table at
    pipeline/dataset_parser/hwp_pua_map.json.

    SCOPE (post-mortem fix): this function used to scan ONLY
    question_item.latex_content. After the I2 axis-agnostic storage refactor,
    axis analysis text lives in analysis_derivation.payload -- a column this
    function never looked at. Worse, that column is written via
    json.dumps(..., ensure_ascii=True), so a PUA codepoint is persisted as
    the 6 literal ASCII characters `\\uE035`, not as the codepoint itself; a
    raw regex scan over the column text (the same technique that is correct
    for latex_content) finds nothing there. Both defects compounded: 1,345
    of 1,350 axis2_raw_parsing payloads were PUA-corrupted while this check
    reported the database clean. The fix is two-fold: (a) also query
    analysis_derivation.payload, and (b) json.loads() each payload FIRST so
    \\uXXXX escapes become real codepoints, then scan every string leaf of
    the decoded structure (via _iter_json_strings) -- never the raw column
    text for this column.

    A payload that is NULL/empty is skipped (nothing to scan). A payload
    that fails to JSON-decode is not silently ignored either: it is scanned
    as raw text instead (no escaping could have applied to non-JSON text,
    so a direct scan is correct there), which is also how this function
    never crashes on malformed payloads."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    rows = conn.execute('SELECT item_id, latex_content FROM question_item').fetchall()

    has_derivation_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_derivation'"
    ).fetchone() is not None
    payload_rows = []
    if has_derivation_table:
        payload_rows = conn.execute(
            'SELECT item_id, axis_key, payload FROM analysis_derivation'
        ).fetchall()
    conn.close()

    # --- source 1: question_item.latex_content ---------------------------
    # This column is stored as plain text (never JSON-escaped), so a direct
    # regex scan over the raw column value is correct as-is.
    offenders = []
    total_pua_chars = 0
    for item_id, latex in rows:
        if not latex:
            continue
        n = len(PUA_RE.findall(latex))
        if n:
            offenders.append(item_id)
            total_pua_chars += n

    if offenders:
        sample = ', '.join(offenders[:20])
        more = f', ... and {len(offenders) - 20} more' if len(offenders) > 20 else ''
        errors.append(
            f'PUA: {len(offenders)}/{len(rows)} question_item.latex_content rows contain '
            f'unmapped-glyph corruption codepoints (BMP/Supplementary Private-Use-Area or '
            f'U+FFFD REPLACEMENT CHARACTER -- see PUA_RE), {total_pua_chars} chars total '
            f'-- HWP equation-font extraction defect has regressed. Offending item_ids: {sample}{more}'
        )

    # --- source 2: analysis_derivation.payload (JSON-escaped storage) -----
    # See the docstring above: must JSON-decode before scanning, or an
    # escaped `` sequence in the stored bytes is invisible to PUA_RE.
    payload_offenders = []
    payload_pua_chars = 0
    for item_id, axis_key, payload in payload_rows:
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except (TypeError, ValueError):
            # Not valid JSON (or not a string at all) -- no \uXXXX escaping
            # could apply, so fall back to scanning the raw text directly
            # rather than silently skipping a malformed payload.
            strings_to_scan = [payload] if isinstance(payload, str) else []
        else:
            strings_to_scan = list(_iter_json_strings(obj))
        n = sum(len(PUA_RE.findall(s)) for s in strings_to_scan if s)
        if n:
            payload_offenders.append(f'{item_id}:{axis_key}')
            payload_pua_chars += n

    if payload_offenders:
        sample = ', '.join(payload_offenders[:20])
        more = f', ... and {len(payload_offenders) - 20} more' if len(payload_offenders) > 20 else ''
        errors.append(
            f'PUA: {len(payload_offenders)}/{len(payload_rows)} analysis_derivation.payload rows '
            f'contain unmapped-glyph corruption codepoints (BMP/Supplementary Private-Use-Area or '
            f'U+FFFD REPLACEMENT CHARACTER -- see PUA_RE), {payload_pua_chars} chars total '
            f'-- JSON-decoded before scanning (payloads are stored with json.dumps('
            f'ensure_ascii=True), so a raw-text scan would miss escaped \\uXXXX sequences) -- '
            f'HWP equation-font extraction defect has regressed. Offending item_id:axis_key: '
            f'{sample}{more}'
        )


_OPAQUE_CONTAINER_MAX_LEN = 5
_OPAQUE_CONTAINER_MAX_DEPTH = 3


def _is_opaque_scalar(value, _depth=0):
    """True if `value` is a "short opaque scalar" -- the real signal a
    placeholder sentinel carries is not "the value is an ALL-CAPS string",
    it is "the value is a single meaningless atom", which is exactly as
    vacuous whether that atom is a bare string token, a bare number, a
    bool, null, or a small container built from nothing but such atoms
    (mission Hole B: {"objective_code": 3}, {"raw": null},
    {"lineage_id": [7]}, {"tree": {"a": {"b": {}}}}, {"kg_ref": "323"} are
    all just as content-free as {"objective": "OBJ_UNDERSTAND"}).

    Real, natural-language analysis text is never mistaken for this: it
    contains whitespace (STUB_TOKEN_RE has none), and real rich structures
    are either deeper/larger than _OPAQUE_CONTAINER_MAX_DEPTH/_MAX_LEN or
    contain at least one non-opaque (real text) leaf."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(STUB_TOKEN_RE.match(value))
    if _depth >= _OPAQUE_CONTAINER_MAX_DEPTH:
        return False
    if isinstance(value, dict):
        if not value:
            return True
        return all(_is_opaque_scalar(v, _depth + 1) for v in value.values())
    if isinstance(value, list):
        if not value:
            return True
        if len(value) > _OPAQUE_CONTAINER_MAX_LEN:
            return False
        return all(_is_opaque_scalar(v, _depth + 1) for v in value)
    return False


def _is_stub_shape(obj):
    """A JSON object with exactly one key whose value is a short opaque
    scalar (see _is_opaque_scalar), e.g. {"objective": "OBJ_UNDERSTAND"} or
    {"objective_code": 3}. This is the shape a hand-written placeholder
    sentinel takes: axis analysis is a rich, multi-field structure, so a
    single opaque-scalar field is never a real result of the analysis
    pipeline -- regardless of the scalar's Python/JSON type."""
    if not isinstance(obj, dict) or len(obj) != 1:
        return False
    (value,) = obj.values()
    return _is_opaque_scalar(value)


def _normalized_value_entropy(nonnull_vals):
    """Normalized Shannon entropy (0..1) of the literal-value distribution.
    1.0 means every value is distinct (maximally diverse); 0.0 means every
    value is identical. Returns 1.0 for the degenerate n<=1 case (nothing to
    compare, so "not low-diversity" by default -- avoids false positives on
    tiny fixtures/columns)."""
    n = len(nonnull_vals)
    if n <= 1:
        return 1.0
    counts = collections.Counter(nonnull_vals)
    entropy = -sum((c / n) * math.log2(c / n) for c in counts.values())
    max_entropy = math.log2(n)
    return (entropy / max_entropy) if max_entropy > 0 else 1.0


def _registry_claims_trustworthy(axis_key):
    """Escalation policy: does the project CLAIM this axis is trustworthy?

    Separating this from the detector matters. `check_axis_stub_sentinels` decides whether an
    axis's payloads are real -- a question about data. Whether that finding should fail the
    build is a different question, about what the project has asserted, and it belongs to the
    caller who owns the build outcome. Fusing the two is what made the gate permanently red
    when axes were retired, and it is also why the detector's own tests must keep seeing the
    detector escalate everything by default.
    """
    defn = AXIS_BY_KEY.get(axis_key)
    return defn is None or defn.status == 'active'


def check_axis_stub_sentinels(errors, db_path, escalate=None):
    """Content-completeness (7): axis_analysis payloads must be real,
    per-item analysis rather than placeholder sentinels. Three independent
    detection rules (any one is sufficient to flag an axis as non-real):

      (i)   shape rule       -- a single-key JSON object whose value is a
                                 short opaque scalar (_is_opaque_scalar:
                                 STUB_TOKEN_RE string, number, bool, null, or
                                 a small container of nothing but such
                                 values), e.g. {"heuristics": "skill_basic_7"}
                                 or {"objective_code": 3}.
      (ii)  duplication rule -- a byte-identical payload shared by >= 30%
                                 (AXIS_DUP_RATIO_THRESHOLD) of non-null rows
                                 for that axis column. A robustness net
                                 independent of rule (i)'s shape assumption:
                                 it also catches mass-copied multi-field
                                 boilerplate that isn't a bare token.
      (iii) distribution rule -- normalized Shannon entropy of the axis
                                 column's value distribution falls below
                                 AXIS_ENTROPY_RATIO_THRESHOLD. A fixed
                                 single-value dominance cutoff like (ii) is
                                 inherently sittable (one value held just
                                 under the threshold, or boilerplate content
                                 partitioned across several near-equal
                                 buckets each individually under the
                                 threshold); low aggregate entropy catches
                                 "this whole column is low-information
                                 filler" regardless of how the filler is
                                 partitioned. Only evaluated when rule (ii)
                                 did not already fire for the same column
                                 (supplement, not double-counting the same
                                 root cause).

    The real-analysis ratio and diagnostic stats (distinct count, entropy)
    per axis are always printed (pass or fail) so the completeness state is
    visible even when the gate is green.

    STORAGE MODEL (I2 axis-agnostic refactor): axis identity moved from 8
    hardcoded `axis_analysis` DDL columns to a generic key-value table,
    `analysis_derivation(item_id, axis_key, schema_version, payload, ...)`
    -- see pipeline/migrate_db_axis_agnostic.py. This function is repointed
    at that new table: it derives `total` from `question_item` (the
    corpus size, not a specific axis table's row count) and scans
    `axis_key IN (AXIS_COLUMNS union whatever axis_keys actually exist in
    analysis_derivation)`, so a brand-new axis_key written by some future
    analyser is automatically covered with zero code change here too.
    `axis_analysis` itself still exists as a read-only compatibility VIEW
    over `analysis_derivation` for other readers (selective_fetcher.py,
    claim_provenance.py); this scan does not need it.

    TRANSITIONAL FALLBACK: if `analysis_derivation` does not exist yet
    (i.e. this DB has not had pipeline/migrate_db_axis_agnostic.py applied),
    this function transparently falls back to reading the legacy flat
    `axis_analysis` columns directly, so the gate keeps working correctly
    against both a pre-migration and a post-migration database."""
    if escalate is None:
        # Default: escalate every finding, i.e. the behaviour this function has always had.
        # Callers that own the build outcome (main()) inject a policy; callers testing the
        # DETECTOR get the detector, unchanged.
        def escalate(_axis_key):
            return True

    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)

    has_derivation_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_derivation'"
    ).fetchone() is not None

    total = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
    # DENOMINATOR WARNING. `total` counts ROWS, not distinct items. Items 1-22 of every
    # session are common across the DIF/GEO/PRO tracks and are stored once per track, so
    # the row count overstates the distinct corpus by roughly a factor of two. A reader
    # who sees "3/1350" naturally reads it as corpus coverage; it is not. Both figures are
    # printed so the difference cannot be misread.
    distinct_items = conn.execute(
        'SELECT COUNT(DISTINCT latex_content) FROM question_item'
    ).fetchone()[0]

    report_lines = []
    axis_failures = []
    axis_observations = []
    low_diversity_axes = []

    if has_derivation_table:
        existing_keys = {
            r[0] for r in conn.execute('SELECT DISTINCT axis_key FROM analysis_derivation').fetchall()
        }
        scan_keys = list(AXIS_COLUMNS) + [k for k in sorted(existing_keys) if k not in AXIS_COLUMNS]
    else:
        scan_keys = list(AXIS_COLUMNS)

    for col in scan_keys:
        if has_derivation_table:
            raw_vals = [
                r[0] for r in conn.execute(
                    'SELECT d.payload FROM question_item q '
                    'LEFT JOIN analysis_derivation d '
                    '  ON d.item_id = q.item_id AND d.axis_key = ? AND d.schema_version = 1 '
                    'ORDER BY q.item_id',
                    (col,),
                ).fetchall()
            ]
        else:
            raw_vals = [r[0] for r in conn.execute(f'SELECT {col} FROM axis_analysis').fetchall()]
        nonnull_vals = [v for v in raw_vals if v not in (None, '', 'null')]

        dup_flagged_value = None
        if nonnull_vals:
            dominant_value, dominant_count = collections.Counter(nonnull_vals).most_common(1)[0]
            if dominant_count > 1 and (dominant_count / len(nonnull_vals)) >= AXIS_DUP_RATIO_THRESHOLD:
                dup_flagged_value = dominant_value

        # Rule (iii): only meaningful as a *supplement* to rule (ii) -- skip
        # it when the dominant-value net already caught this column so we
        # don't double-report the same underlying defect.
        distinct_count = len(set(nonnull_vals))
        normalized_entropy = 1.0
        if dup_flagged_value is None and len(nonnull_vals) > 1:
            normalized_entropy = _normalized_value_entropy(nonnull_vals)

        real_count = 0
        stub_count = 0
        for v in raw_vals:
            if v in (None, '', 'null'):
                continue
            if dup_flagged_value is not None and v == dup_flagged_value:
                stub_count += 1
                continue
            try:
                obj = json.loads(v)
            except (TypeError, ValueError):
                real_count += 1
                continue
            if isinstance(obj, dict) and not obj:
                continue
            if _is_stub_shape(obj):
                stub_count += 1
            else:
                real_count += 1

        empty_count = total - len(nonnull_vals)
        real_ratio = (real_count / total) if total else 0.0
        report_lines.append(
            f'  {col}: real={real_count}/{total} ({real_ratio:.1%}) '
            f'stub={stub_count} empty={empty_count} distinct={distinct_count} '
            f'entropy={normalized_entropy:.2f}'
        )
        if real_ratio < AXIS_REAL_RATIO_THRESHOLD:
            _defn = AXIS_BY_KEY.get(col)
            (axis_failures if escalate(col) else axis_observations).append(
                (col, real_count, total, real_ratio,
                 _defn.status if _defn else 'unregistered')
            )
        if dup_flagged_value is None and len(nonnull_vals) > 1 and normalized_entropy < AXIS_ENTROPY_RATIO_THRESHOLD:
            low_diversity_axes.append((col, distinct_count, len(nonnull_vals), normalized_entropy))

    conn.close()

    print(
        f'AXIS ANALYSIS COMPLETENESS (stub-sentinel scan, real-ratio threshold='
        f'{AXIS_REAL_RATIO_THRESHOLD:.0%}, entropy-ratio threshold={AXIS_ENTROPY_RATIO_THRESHOLD}):'
    )
    print(
        f'  DENOMINATOR: ratios below are per ROW ({total} rows). The distinct corpus is '
        f'{distinct_items} items -- items 1-22 are stored once per DIF/GEO/PRO track, so a row '
        f'ratio is NOT a corpus-coverage ratio.'
    )
    for line in report_lines:
        print(line)
    if axis_observations:
        print(
            '  NOT ESCALATED (the registry makes no trustworthiness claim for these axes; '
            'see check_axis_status_honesty, which escalates the same shortfall wherever a '
            'claim does exist):'
        )
        for col, real_count, axis_total, real_ratio, status in axis_observations:
            print(
                f'    {col}: real={real_count}/{axis_total} ({real_ratio:.1%}) '
                f'below threshold, status={status}'
            )

    for col, real_count, axis_total, real_ratio, _status in axis_failures:
        errors.append(
            f'Stub sentinel: analysis_derivation.{col} has real analysis in only '
            f'{real_count}/{axis_total} rows ({real_ratio:.1%}, threshold '
            f'{AXIS_REAL_RATIO_THRESHOLD:.0%}) -- majority are placeholder/duplicated/empty payloads'
        )
    for col, distinct_count, n_nonnull, normalized_entropy in low_diversity_axes:
        errors.append(
            f'Stub sentinel: analysis_derivation.{col} shows abnormally low payload diversity '
            f'(normalized value entropy={normalized_entropy:.2f}, threshold '
            f'{AXIS_ENTROPY_RATIO_THRESHOLD}) across {n_nonnull} non-null rows -- '
            f'{distinct_count} distinct value(s) -- this axis reads as templated/boilerplate '
            f'content even though no single literal value alone clears the '
            f'{AXIS_DUP_RATIO_THRESHOLD:.0%} duplication threshold (e.g. a dominant value sitting '
            f'just under that threshold, or boilerplate content split across multiple near-equal '
            f'buckets)'
        )


def check_axis_status_honesty(errors, db_path):
    """Content-completeness (10): the axis registry's CLAIM must match the data.

    WHY THIS EXISTS -- the root cause it addresses
    ----------------------------------------------
    `check_axis_stub_sentinels` measures how much real analysis each axis carries. That is a
    STATE OBSERVATION, not a drift violation: every other check in this file detects two
    sources of truth disagreeing, whereas a completeness ratio just reports how far along
    the work is. Escalating a state observation to a gate failure has a specific, fatal
    consequence: the gate goes permanently red for reasons nobody can act on. Deprecating an
    axis makes it red (a retired axis will never reach the threshold -- that is what
    retirement means). Introducing a new axis makes it red on day one (it starts empty). The
    only available responses become "lower the threshold" or "ignore the gate", and both
    destroy the signal. A permanently red gate is not a gate.

    This check restores the teeth in the form the rest of the file uses -- as drift between a
    declared source of truth and observed reality. The registry's `status` field is the
    declaration: `active` means the project asserts the axis is trustworthy. That assertion is
    falsifiable against the data, and this check falsifies it.

    RELATIONSHIP TO check_axis_stub_sentinels -- this is not a weakening
    -------------------------------------------------------------------
    That function's DETECTION is unchanged; every rule still runs and every result is still
    printed. What changed is which detections are escalated. A shortfall is escalated where
    the registry claims trustworthiness, and reported without escalation where it does not,
    because there is no claim for it to contradict. The escalation moved here, and here it is
    strictly stronger: it also fails on an `active` axis holding no rows at all, and on an
    axis_key carrying real data that no registry entry documents -- neither of which the
    stub-sentinel scan ever detected.

    RULES
      R1  an axis_key carrying real analysis that is registered nowhere -- data exists with
          no documented identity, owner, or trust status
      R2  an axis whose status is `active` but whose real-analysis ratio is below threshold
      R3  an axis whose status is `active` but which holds no rows at all
    """
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_derivation'"
    ).fetchone() is None:
        conn.close()
        return

    total = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
    real_by_key = {}
    for key, payload in conn.execute(
        'SELECT axis_key, payload FROM analysis_derivation'
    ):
        bucket = real_by_key.setdefault(key, [0, 0])
        bucket[1] += 1
        if payload in (None, '', 'null'):
            continue
        try:
            obj = json.loads(payload)
        except (TypeError, ValueError):
            bucket[0] += 1
            continue
        if isinstance(obj, dict) and not obj:
            continue
        if not _is_stub_shape(obj):
            bucket[0] += 1
    conn.close()

    for key, (real, _rows) in sorted(real_by_key.items()):
        if key not in AXIS_BY_KEY and real > 0:
            errors.append(
                f'Axis status honesty (R1): analysis_derivation.{key} carries {real} rows of real '
                f'analysis but is registered nowhere in pipeline/query_engine/axis_registry.py -- '
                f'data with no documented identity, owner or trust status'
            )

    for key, defn in sorted(AXIS_BY_KEY.items()):
        if defn.status != 'active':
            continue
        real, rows = real_by_key.get(key, (0, 0))
        if rows == 0:
            errors.append(
                f'Axis status honesty (R3): axis_registry declares {key} status=active, but it '
                f'holds no rows in analysis_derivation -- an axis cannot be trustworthy and empty'
            )
            continue
        ratio = (real / total) if total else 0.0
        if ratio < AXIS_REAL_RATIO_THRESHOLD:
            errors.append(
                f'Axis status honesty (R2): axis_registry declares {key} status=active, but only '
                f'{real}/{total} rows ({ratio:.1%}) carry real analysis (threshold '
                f'{AXIS_REAL_RATIO_THRESHOLD:.0%}). Either the analysis is incomplete or the '
                f'status is wrong -- fix one of them, do not lower the threshold'
            )


def check_answer_sanity(errors, db_path):
    """Content-completeness (8): question_item.answer / canonical_answer_json
    must encode real, item-specific grading data.

      - fails if question_item.answer is uniformly one value across the
        corpus, or so dominated by one value (>= 90% of rows) that it is
        functionally a placeholder default rather than real grading data.
      - fails if canonical_answer_json.response_type is SHORT_ANSWER for an
        item whose latex_content clearly presents multiple-choice options
        (contains the CHOICE_MARKER '[CHOICE_1]' marker) -- a response-type
        mislabel.
      - fails if a multiple-choice item's question_item.answer falls outside
        1..5 (the only valid KICE option indices, MC_ANSWER_RANGE).

    KNOWN, PERMANENT LIMITATION (do not mistake a green result here for
    "the answers are correct" -- see also the module docstring):
    this check is purely statistical/structural. It can prove the answer
    column is NOT uniform/dominated/mislabeled/out-of-range; it CANNOT
    prove any individual answer is semantically correct. A well-distributed
    but entirely fabricated answer key (e.g. a deterministic hash used as a
    stand-in for real grading data) satisfies every rule below and will
    pass cleanly -- that is architecturally unverifiable by a
    reference-free static check, not a bug in this implementation. Verifying
    real correctness requires grading against a genuine answer key (human
    review / an external oracle), which is out of scope for a repo-drift
    gate. Additionally, the two MC-specific sub-checks are gated on the
    literal CHOICE_MARKER substring (see its definition above): they go
    dark for any row using a different choice-marker convention."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    rows = conn.execute(
        'SELECT item_id, answer, canonical_answer_json, latex_content FROM question_item'
    ).fetchall()
    conn.close()

    print(
        'ANSWER SANITY LIMITATIONS (always true, printed regardless of pass/fail): this check '
        'detects STATISTICAL degeneracy only (uniform/dominant/mislabeled/out-of-range answer '
        'data). It CANNOT verify that any answer is semantically CORRECT -- a well-distributed '
        f'but entirely fabricated answer key will pass. The multiple-choice sub-checks fire only '
        f'for rows containing the literal marker {CHOICE_MARKER!r}; a different choice-marker '
        f'convention silently narrows this check to zero for those rows.'
    )

    total = len(rows)
    if total == 0:
        return

    answer_counter = collections.Counter(r[1] for r in rows)
    dominant_answer, dominant_count = answer_counter.most_common(1)[0]
    dominant_ratio = dominant_count / total

    if len(answer_counter) <= 1:
        errors.append(
            f'Answer sanity: question_item.answer is uniformly {dominant_answer!r} '
            f'across all {total} items -- no real grading data present'
        )
    elif dominant_ratio >= ANSWER_DOMINANCE_THRESHOLD:
        errors.append(
            f'Answer sanity: question_item.answer is degenerate -- {dominant_count}/{total} '
            f'({dominant_ratio:.1%}) items share value {dominant_answer!r} '
            f'(>= {ANSWER_DOMINANCE_THRESHOLD:.0%} dominance threshold); '
            f'distinct value counts={dict(answer_counter)}'
        )

    short_answer_with_choices = []
    mc_answer_out_of_range = []
    for item_id, answer, canonical_json, latex in rows:
        has_choice_marker = bool(latex and CHOICE_MARKER in latex)

        response_type = None
        if canonical_json:
            try:
                response_type = json.loads(canonical_json).get('response_type')
            except (TypeError, ValueError):
                response_type = None

        if has_choice_marker and response_type == 'SHORT_ANSWER':
            short_answer_with_choices.append(item_id)
        if has_choice_marker and answer not in MC_ANSWER_RANGE:
            mc_answer_out_of_range.append(item_id)

    if short_answer_with_choices:
        sample = ', '.join(short_answer_with_choices[:20])
        more = f', ... and {len(short_answer_with_choices) - 20} more' if len(short_answer_with_choices) > 20 else ''
        errors.append(
            f'Answer sanity: {len(short_answer_with_choices)}/{total} items present '
            f"'{CHOICE_MARKER}' options in latex_content but canonical_answer_json.response_type="
            f"'SHORT_ANSWER' -- {sample}{more}"
        )
    if mc_answer_out_of_range:
        sample = ', '.join(mc_answer_out_of_range[:20])
        more = f', ... and {len(mc_answer_out_of_range) - 20} more' if len(mc_answer_out_of_range) > 20 else ''
        errors.append(
            f'Answer sanity: {len(mc_answer_out_of_range)}/{total} multiple-choice items '
            f"(present '{CHOICE_MARKER}') have question_item.answer outside "
            f'{{{",".join(str(x) for x in MC_ANSWER_RANGE)}}} -- {sample}{more}'
        )


def check_routing_regeneration(errors, routing_md_path=None):
    """Content-completeness (9): ROUTING.md must be exactly what
    tools/generate_routing.py produces right now -- a regeneration-diff gate
    in the same spirit as checks 6/7/8 above, but for the routing SURFACE
    itself rather than the underlying data: a routing doc can be perfectly
    hand-written today and silently wrong tomorrow the moment the DB, the
    axis registry, or the repo tree changes under it (this is exactly what
    happened to the 2026-07-25 hand-written ROUTING.md and to ENTRYPOINT.md's
    "Loading Order", both of which confidently pointed at facts that had
    stopped being true).

    Regenerates to an in-memory string via tools.generate_routing.render()
    (never a subprocess -- render() itself only calls the 8 ORIGINAL check_*
    functions above directly, so there is zero risk of this check
    recursively invoking itself) and fails if that string differs from the
    committed ROUTING.md on disk, byte-for-byte.

    NOTE ON DETERMINISM: this comparison is only meaningful because
    tools/generate_routing.py's render() embeds no wall-clock timestamp or
    other run-to-run-varying value -- see the DETERMINISM CONTRACT in that
    module's docstring. If that contract is ever violated, this check will
    permanently fail even immediately after a correct `--write`, which is
    itself a useful tripwire for the contract being broken.

    `routing_md_path` defaults to the real committed ROUTING.md; tests may
    override it with a throwaway path so they can exercise a deliberately
    drifted fixture without ever touching the real committed file."""
    tools_dir = os.path.join(BASE_DIR, 'tools')
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import generate_routing
    except ImportError as exc:
        errors.append(f'Routing drift: could not import tools/generate_routing.py: {exc}')
        return

    try:
        expected = generate_routing.render()
    except Exception as exc:  # noqa: BLE001 - surface any generator failure as a gate failure
        errors.append(f'Routing drift: tools/generate_routing.py render() raised {exc!r}')
        return

    if routing_md_path is None:
        routing_md_path = os.path.join(BASE_DIR, 'ROUTING.md')
    if not os.path.isfile(routing_md_path):
        errors.append('Routing drift: ROUTING.md is missing')
        return

    with open(routing_md_path, 'r', encoding='utf-8') as f:
        actual = f.read()

    if actual != expected:
        # Minimal, useful diff signal without dumping two full documents.
        actual_lines = actual.splitlines()
        expected_lines = expected.splitlines()
        first_diff = None
        for i, (a_line, e_line) in enumerate(zip(actual_lines, expected_lines)):
            if a_line != e_line:
                first_diff = (i + 1, a_line, e_line)
                break
        if first_diff is None and len(actual_lines) != len(expected_lines):
            first_diff = (
                min(len(actual_lines), len(expected_lines)) + 1,
                '<end of file>' if len(actual_lines) < len(expected_lines) else '<extra content>',
                '<extra content>' if len(actual_lines) < len(expected_lines) else '<end of file>',
            )
        detail = ''
        if first_diff:
            lineno, a_line, e_line = first_diff
            detail = (
                f' First difference at line {lineno}: '
                f'committed={a_line!r} generated={e_line!r}.'
            )
        errors.append(
            'Routing drift: ROUTING.md does not match tools/generate_routing.py output -- '
            'regenerate with `python3 tools/generate_routing.py --write` and commit the '
            f'result.{detail}'
        )


# ---------------------------------------------------------------------------
# THE GATE, AS DATA -- the single canonical list of what this gate runs.
#
# This list existed in two hand-maintained places: main() here, and _ORIGINAL_CHECKS in
# tools/generate_routing.py, which mirrors the gate so ROUTING.md can publish its measured
# result. Nothing forced them to agree, and they stopped agreeing silently the moment a check
# was added or its arguments changed -- ROUTING.md then published a "measured gate result"
# that the gate itself would not produce. Two independently maintained copies of one fact is
# exactly the drift this repository forbids everywhere else.
#
# check_routing_regeneration is deliberately EXCLUDED: the generator consumes this list, so
# including it would recurse.
GATE_CHECKS = (
    ('check_ddl', lambda errors, db: check_ddl(errors, db)),
    ('check_manifest_vs_state', lambda errors, db: check_manifest_vs_state(errors)),
    ('check_versions', lambda errors, db: check_versions(errors)),
    ('check_transition_matrix', lambda errors, db: check_transition_matrix(errors)),
    ('check_ci_evidence', lambda errors, db: check_ci_evidence(errors)),
    ('check_pua_free_text', lambda errors, db: check_pua_free_text(errors, db)),
    ('check_axis_stub_sentinels',
     lambda errors, db: check_axis_stub_sentinels(
         errors, db, escalate=_registry_claims_trustworthy)),
    ('check_axis_status_honesty', lambda errors, db: check_axis_status_honesty(errors, db)),
    ('check_answer_sanity', lambda errors, db: check_answer_sanity(errors, db)),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DEFAULT_DB)
    args = parser.parse_args()

    errors = []
    for _name, _run in GATE_CHECKS:
        _run(errors, args.db)
    check_routing_regeneration(errors)

    if errors:
        print('SSoT CONSISTENCY: FAIL')
        for e in errors:
            print(f'  - {e}')
        return 1
    print(
        'SSoT CONSISTENCY: OK (DDL, manifest/state, versions, transition matrix, '
        'ci_evidence, PUA-free text, axis stub-sentinels, axis status honesty, answer sanity, '
        'routing regeneration)'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
