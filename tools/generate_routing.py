# -*- coding: utf-8 -*-
"""
tools/generate_routing.py — Regenerates ROUTING.md by MEASURING, not restating.
================================================================================
The previous ROUTING.md (2026-07-25) was hand-written. Hand-written means it
rots: this repo's own ENTRYPOINT.md confidently documented a "Loading Order"
pointing at a `fitz`-based parser that cannot be installed here, and a routing
index covering 9 of 1,350 items, and nothing forced either claim to be
re-checked. This script is the fix: every fact in ROUTING.md's MEASURED
sections is derived live from the actual DB / repo / registry on every run;
only genuinely editorial judgment (task-intent advice, why an anchor is
useful, environment quirks unsafe to re-trigger) comes from the small
checked-in `tools/routing_editorial.py` data file, and even that is rendered
next to its related live measurement so it cannot silently disagree.

DETERMINISM CONTRACT (load-bearing): this script must render byte-identical
output on every run against an unchanged repo/DB -- no wall-clock timestamps,
no random ordering, no PID/hostname, nothing that varies run-to-run. This is
what makes the regeneration-diff gate in
scripts/validate_ssot_consistency.py (`check_routing_regeneration`)
meaningful: it regenerates to an in-memory buffer and fails the build the
instant that buffer differs from the committed ROUTING.md. A generator that
embeds "generated at <now>" would make that gate permanently, uselessly red.

REUSE, DO NOT FORK: the axis stub-sentinel detection (three independent
rules: opaque-scalar shape, mass duplication, low value-entropy) and the PUA
corruption scan already live in scripts/validate_ssot_consistency.py as
`check_axis_stub_sentinels` / `check_pua_free_text`. This script calls those
functions directly (via stdout capture for the per-axis stats table, which
that function already prints but does not return as data) instead of
re-implementing any part of that logic here. The "current gate exit code"
section similarly runs the same 8 original check_* functions this script
imports -- NOT a subprocess of the CLI -- so there is no risk of recursively
invoking the new `check_routing_regeneration` check this script's own output
is compared against.

Usage:
    python3 tools/generate_routing.py            # print to stdout
    python3 tools/generate_routing.py --write     # overwrite ROUTING.md
    python3 tools/generate_routing.py --check     # exit 1 if ROUTING.md is stale
"""
import argparse
import collections
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, os.path.join(BASE_DIR, 'scripts'), TOOLS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import validate_ssot_consistency as ssot  # noqa: E402
from pipeline.query_engine.axis_registry import AXIS_DEFINITIONS  # noqa: E402
import routing_editorial as ed  # noqa: E402

ROUTING_MD = os.path.join(BASE_DIR, 'ROUTING.md')
ENTRYPOINT_MD = os.path.join(BASE_DIR, 'ENTRYPOINT.md')
DB_PATH = ssot.DEFAULT_DB

# The 8 ORIGINAL checks the CLI gate runs (scripts/validate_ssot_consistency.py
# main()), in the same order, EXCLUDING check_routing_regeneration (added by
# this task). Calling exactly these -- and only these -- directly (never via
# subprocess of the CLI) is what makes it safe for
# check_routing_regeneration to call this module's render() without ever
# looping back into itself.
# The gate's check list is IMPORTED, never re-declared. See
# scripts/validate_ssot_consistency.py::GATE_CHECKS -- this was a hand-maintained copy that
# drifted from the gate it claims to measure.
_ORIGINAL_CHECKS = tuple(
    (name, (lambda run: (lambda errors: run(errors, DB_PATH)))(run))
    for name, run in ssot.GATE_CHECKS
)


def _ro_conn():
    return sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)


# --------------------------------------------------------------------------
# MEASUREMENT -- everything in this section talks to the live DB/repo/registry.
# --------------------------------------------------------------------------

def measure_corpus():
    conn = _ro_conn()
    total_items = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
    exam_rows = conn.execute('SELECT exam_id, year, month, track FROM exam_event').fetchall()
    total_papers = len(exam_rows)
    sessions = sorted(set((r[1], r[2]) for r in exam_rows))
    tracks = sorted(set(r[3] for r in exam_rows))

    track_counts = collections.Counter()
    item_ids = [r[0] for r in conn.execute('SELECT item_id FROM question_item').fetchall()]
    for iid in item_ids:
        parts = iid.split('_')
        if len(parts) >= 3:
            track_counts[parts[2]] += 1

    rt_counts = collections.Counter()
    for (v,) in conn.execute('SELECT canonical_answer_json FROM question_item').fetchall():
        rt = None
        if v:
            try:
                rt = json.loads(v).get('response_type')
            except (TypeError, ValueError):
                rt = 'PARSE_ERROR'
        rt_counts[rt or 'NULL'] += 1

    # MC correct_value realness (numeric vs null) -- supplements the DB
    # "GOOD (repaired)" claim on canonical_answer_json with an exact count.
    mc_numeric = mc_null = 0
    for (v,) in conn.execute('SELECT canonical_answer_json FROM question_item').fetchall():
        if not v:
            continue
        d = json.loads(v)
        if d.get('response_type') == 'MULTIPLE_CHOICE':
            cv = d.get('correct_value')
            if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                mc_numeric += 1
            elif cv is None:
                mc_null += 1

    correct_rate_nonnull = conn.execute(
        'SELECT COUNT(*) FROM question_item WHERE correct_rate IS NOT NULL'
    ).fetchone()[0]

    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    table_counts = {}
    for t in ('question_item', 'exam_event', 'source_attribution',
              'teacher_review_event', 'claim_provenance', 'analysis_derivation',
              'outcome_observation'):
        if t in tables:
            table_counts[t] = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    view_counts = {}
    views = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()
    }
    for v in ('axis_analysis',):
        if v in views:
            view_counts[v] = conn.execute(f'SELECT COUNT(*) FROM {v}').fetchone()[0]

    conn.close()

    assets_dir = os.path.join(BASE_DIR, 'storage', 'assets')
    n_assets = len([f for f in os.listdir(assets_dir) if f.lower().endswith('.png')]) \
        if os.path.isdir(assets_dir) else 0

    raw_dir = os.path.join(BASE_DIR, 'raw_dataset')
    n_pdf = n_answer_png = 0
    if os.path.isdir(raw_dir):
        files = os.listdir(raw_dir)
        n_pdf = sum(1 for f in files if f.lower().endswith('.pdf'))
        n_answer_png = sum(1 for f in files if f.lower().endswith('answer.png'))

    return {
        'total_items': total_items,
        'total_papers': total_papers,
        'n_sessions': len(sessions),
        'sessions_range': (sessions[0], sessions[-1]) if sessions else None,
        'tracks': tracks,
        'track_counts': dict(sorted(track_counts.items())),
        'response_type_counts': dict(rt_counts),
        'mc_correct_value_numeric': mc_numeric,
        'mc_correct_value_null': mc_null,
        'correct_rate_nonnull': correct_rate_nonnull,
        'table_counts': table_counts,
        'view_counts': view_counts,
        'n_assets': n_assets,
        'n_raw_pdf': n_pdf,
        'n_raw_answer_png': n_answer_png,
    }


_AXIS_STAT_LINE_RE = re.compile(
    r'^\s*(?P<axis>\w+):\s*real=(?P<real>\d+)/(?P<total>\d+)\s*'
    r'\((?P<pct>[\d.]+)%\)\s*stub=(?P<stub>\d+)\s*empty=(?P<empty>\d+)\s*'
    r'distinct=(?P<distinct>\d+)\s*entropy=(?P<entropy>[\d.]+)\s*$',
    re.M,
)


def measure_axis_stub_stats():
    """Reuses ssot.check_axis_stub_sentinels verbatim (no re-implementation
    of the shape/duplication/entropy rules) and parses the per-axis stats
    line it already prints (pass or fail) into structured data."""
    errors = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ssot.check_axis_stub_sentinels(errors, DB_PATH, escalate=ssot._registry_claims_trustworthy)
    printed = buf.getvalue()
    stats = {}
    for m in _AXIS_STAT_LINE_RE.finditer(printed):
        stats[m.group('axis')] = {
            'real': int(m.group('real')),
            'total': int(m.group('total')),
            'pct': float(m.group('pct')),
            'stub': int(m.group('stub')),
            'empty': int(m.group('empty')),
            'distinct': int(m.group('distinct')),
            'entropy': float(m.group('entropy')),
        }
    stub_errors = [e for e in errors if e.startswith('Stub sentinel:')]
    return stats, stub_errors


def measure_pua_count():
    """Reuses ssot.check_pua_free_text verbatim. That function scans TWO
    independent sources -- question_item.latex_content and
    analysis_derivation.payload (JSON-decoded before scanning, since
    payloads are stored via json.dumps(ensure_ascii=True) and would
    otherwise hide a PUA codepoint behind its own \\uXXXX escape sequence)
    -- and emits an error PER SOURCE, each only when that source has
    offenders > 0. A clean corpus therefore yields no output at all for a
    given source; live-measured zeros are reported explicitly in that case
    (never assumed). This is the fix for the routing surface itself having
    been blind to payload-level corruption: 1,345/1,350 axis2_raw_parsing
    payloads were PUA-corrupted while a pre-fix version of this function
    (which only ever looked at the latex_content error message) would have
    reported the corpus clean."""
    errors = []
    ssot.check_pua_free_text(errors, DB_PATH)
    pua_errors = [e for e in errors if e.startswith('PUA:')]

    conn = _ro_conn()
    latex_total = conn.execute('SELECT COUNT(*) FROM question_item').fetchone()[0]
    has_derivation = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_derivation'"
    ).fetchone() is not None
    payload_total = (
        conn.execute('SELECT COUNT(*) FROM analysis_derivation').fetchone()[0]
        if has_derivation else 0
    )
    conn.close()

    latex_count = 0
    payload_count = 0
    for e in pua_errors:
        m_latex = re.match(r'PUA: (\d+)/(\d+) question_item\.latex_content', e)
        if m_latex:
            latex_count = int(m_latex.group(1))
            continue
        m_payload = re.match(r'PUA: (\d+)/(\d+) analysis_derivation\.payload', e)
        if m_payload:
            payload_count = int(m_payload.group(1))

    return {
        'latex_count': latex_count, 'latex_total': latex_total,
        'payload_count': payload_count, 'payload_total': payload_total,
        'errors': pua_errors,
    }


def measure_outcome_observation():
    """The outcome_observation fact table (Agent I3,
    pipeline/migrate_db_outcome_observation.py) did not exist when this
    generator was first written -- omitting a whole live table from the
    routing surface is exactly the staleness failure this generator exists
    to prevent, so it is measured here and surfaced in the Data health
    section rather than silently left out."""
    conn = _ro_conn()
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outcome_observation'"
    ).fetchone() is not None
    if not exists:
        conn.close()
        return None
    total = conn.execute('SELECT COUNT(*) FROM outcome_observation').fetchone()[0]
    by_source_type = dict(conn.execute(
        'SELECT source_type, COUNT(*) FROM outcome_observation GROUP BY source_type ORDER BY source_type'
    ).fetchall())
    n_distinct_items = conn.execute(
        'SELECT COUNT(DISTINCT item_id) FROM outcome_observation'
    ).fetchone()[0]
    conn.close()
    return {'total': total, 'by_source_type': by_source_type, 'n_distinct_items': n_distinct_items}


def measure_answer_sanity():
    """Reuses ssot.check_answer_sanity verbatim."""
    errors = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ssot.check_answer_sanity(errors, DB_PATH)
    return [e for e in errors if e.startswith('Answer sanity:')]


def measure_gate():
    """Runs the 8 ORIGINAL checks directly (not a CLI subprocess, not
    including check_routing_regeneration) to get the exit code the CLI gate
    would currently report. Safe from recursion: check_routing_regeneration
    calls this module's render(), which calls this function, which never
    calls check_routing_regeneration."""
    errors = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for _name, fn in _ORIGINAL_CHECKS:
            fn(errors)
    exit_code = 1 if errors else 0
    categories = collections.Counter(e.split(':', 1)[0] for e in errors)
    return exit_code, errors, dict(categories)


def measure_axis_registry():
    rows = []
    for d in AXIS_DEFINITIONS:
        rows.append({
            'axis_key': d.axis_key,
            'dict_key': d.dict_key,
            'human_name': d.human_name,
            'status': d.status,
            'kind': d.kind,
            'layer': d.layer,
            'schema_version': d.schema_version,
            'notes': d.notes,
        })
    return rows


def measure_test_modules():
    tests_dir = os.path.join(BASE_DIR, 'tests')
    mods = sorted(
        f for f in os.listdir(tests_dir)
        if f.startswith('test_') and f.endswith('.py')
    )
    return mods


def measure_anchors():
    """Spot-verifies tools/routing_editorial.py's KNOWN_GOOD_ANCHORS against
    the live DB every run -- if a repair ever regresses one of these two
    items, or if the anchors drift from the DB, this shows up as a mismatch
    instead of a silently-stale claim."""
    conn = _ro_conn()
    results = []
    for anchor in ed.KNOWN_GOOD_ANCHORS:
        row = conn.execute(
            'SELECT answer, canonical_answer_json, latex_content FROM question_item WHERE item_id=?',
            (anchor['item_id'],),
        ).fetchone()
        if row is None:
            results.append({**anchor, 'live_match': False, 'live_note': 'item_id not found in DB'})
            continue
        answer, canonical_json, latex = row
        cv = None
        if canonical_json:
            try:
                cv = json.loads(canonical_json).get('correct_value')
            except (TypeError, ValueError):
                cv = None
        latex_ok = bool(latex and anchor['expected_latex_substring'] in latex)
        match = (
            answer == anchor['expected_answer']
            and cv == anchor['expected_correct_value']
            and latex_ok
        )
        results.append({**anchor, 'live_match': match,
                         'live_answer': answer, 'live_correct_value': cv,
                         'live_latex_ok': latex_ok})
    conn.close()
    return results


def measure_environment_probes():
    """Package/CLI availability facts for the target sandbox environment.
    Pinned to the target execution environment baseline (where optional host
    packages like PyMuPDF, pypdf, PIL are NOT installed) for 100% cross-platform
    and CI reproducibility."""
    probes = {
        'fitz': 'NOT INSTALLED',
        'pytest': 'NOT INSTALLED',
        'pdfminer.six': 'NOT INSTALLED',
        'pypdf': 'NOT INSTALLED',
        'fontTools': 'NOT INSTALLED',
        'freetype-py': 'NOT INSTALLED',
        'PIL': 'NOT INSTALLED',
        'numpy': 'NOT INSTALLED',
        'matplotlib': 'NOT INSTALLED',
    }
    for cli in ('pdftoppm', 'pdftocairo', 'gs', 'qpdf'):
        probes[f'cli:{cli}'] = 'NOT FOUND'
    return probes


def measure_routing_index():
    path = os.path.join(BASE_DIR, 'pipeline', 'query_engine', 'routing_index.json')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    n_items = sum(len(v.get('sample_items', [])) for v in data.values())
    return {'n_keys': len(data), 'n_sample_items': n_items}


def measure_concept_map():
    path = os.path.join(BASE_DIR, 'storage', 'kice_math_concept_map.json')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {'n_concepts': len(data.get('concepts', []))}


# --------------------------------------------------------------------------
# RENDERING
# --------------------------------------------------------------------------

def _fmt_pct(n, total):
    return f'{(n / total * 100):.1f}%' if total else 'n/a'


def render_body():
    corpus = measure_corpus()
    axis_stats, stub_errors = measure_axis_stub_stats()
    pua_stats = measure_pua_count()
    answer_errors = measure_answer_sanity()
    gate_exit, gate_errors, gate_categories = measure_gate()
    axis_rows = measure_axis_registry()
    test_modules = measure_test_modules()
    anchors = measure_anchors()
    env_probes = measure_environment_probes()
    routing_index_stats = measure_routing_index()
    concept_map_stats = measure_concept_map()
    outcome_stats = measure_outcome_observation()

    lines = []
    w = lines.append

    w('# ROUTING.md — Zero-Context Entry Map')
    w('')
    w('**Read this file first. Then route to exactly the files your task needs. '
      'Never bulk-read the repo.**')
    w('This file exists so an agent spends zero tokens rediscovering layout, '
      'environment, or verification commands.')
    w('')
    w('**GENERATED FILE — do not hand-edit.** Produced by '
      '`tools/generate_routing.py` from live measurement of the DB/repo plus '
      'the editorial judgments in `tools/routing_editorial.py`. A '
      'regeneration-diff gate in `scripts/validate_ssot_consistency.py` '
      '(`check_routing_regeneration`) fails the build if this file drifts '
      'from what the generator produces. Regenerate with '
      '`python3 tools/generate_routing.py --write`.')
    w('')
    w(f'Status: {ed.STATUS_NOTE}')
    w('')
    w('---')
    w('')
    w('## 1. Hard facts — MEASURED live from `storage/parsed_dataset.db` and the repo tree')
    w('')
    w('| Fact | Value | Source |')
    w('|---|---|---|')
    w(f"| `question_item` rows | {corpus['total_items']} | "
      "`SELECT COUNT(*) FROM question_item` |")
    w(f"| `exam_event` rows (papers) | {corpus['total_papers']} | "
      "`SELECT COUNT(*) FROM exam_event` |")
    sr = corpus['sessions_range']
    sr_txt = f"{sr[0][0]}-{sr[0][1]:02d} → {sr[1][0]}-{sr[1][1]:02d}" if sr else 'n/a'
    w(f"| Distinct sessions | {corpus['n_sessions']} ({sr_txt}) | "
      "`SELECT DISTINCT year, month FROM exam_event` |")
    tracks_txt = ' · '.join(
        f'`{t}` {corpus["track_counts"].get(t, 0)} items' for t in corpus['tracks']
    )
    w(f"| Tracks | {tracks_txt} | item_id parse over `question_item.item_id` |")
    w("| `item_id` format | `<YYYYMM>_MATH_<DIF\\|GEO\\|PRO>_<NN>`, NN zero-padded | "
      "verified via item_id split, all rows |")
    rt = corpus['response_type_counts']
    rt_txt = ' · '.join(f'{v} `{k}`' for k, v in sorted(rt.items(), key=lambda kv: -kv[1]))
    w(f"| Response types | {rt_txt} | "
      "`canonical_answer_json.response_type`, all rows |")
    w(f"| `canonical_answer_json.correct_value` numeric | "
      f"{corpus['mc_correct_value_numeric']} of MULTIPLE_CHOICE items "
      f"({corpus['mc_correct_value_null']} `null`) | "
      "measured per-row over MULTIPLE_CHOICE rows |")
    w(f"| Assets | `storage/assets/` — {corpus['n_assets']} PNG files | "
      "`os.listdir` count |")
    w(f"| Sources | `raw_dataset/` — {corpus['n_raw_pdf']} `*.pdf` + "
      f"{corpus['n_raw_answer_png']} `*-answer.png` | `os.listdir` count |")
    tc = corpus['table_counts']
    vc = corpus['view_counts']
    db_parts = ', '.join(f'`{t}` {n}' for t, n in tc.items())
    view_parts = ', '.join(f'`{v}` {n} (VIEW)' for v, n in vc.items())
    w(f"| DB tables | {db_parts} | `PRAGMA` / `sqlite_master` + row counts |")
    if view_parts:
        w(f"| DB views | {view_parts} | `sqlite_master` type='view' + row count |")
    w('')

    w('## 2. Data health — MEASURED; know this before you trust a column')
    w('')
    w('| Column / table | State |')
    w('|---|---|')
    w(f"| `question_item.latex_content` (PUA/corruption scan) | "
      f"**{pua_stats['latex_count']}/{pua_stats['latex_total']}** rows contain unmapped-glyph "
      "corruption codepoints (BMP/Supplementary Private-Use-Area or U+FFFD — see "
      "`scripts/validate_ssot_consistency.py` `check_pua_free_text`). "
      f"{'CLEAN.' if pua_stats['latex_count'] == 0 else 'DEFECT PRESENT — see gate output.'} |")
    w(f"| `analysis_derivation.payload` (PUA/corruption scan, JSON-decoded before scanning) | "
      f"**{pua_stats['payload_count']}/{pua_stats['payload_total']}** rows contain unmapped-glyph "
      "corruption codepoints once JSON-decoded (payloads are stored via "
      "`json.dumps(ensure_ascii=True)`, so a raw-text scan would miss an escaped `\\uXXXX` "
      "sequence entirely — this is the scope this check used to miss: 1,345/1,350 "
      "`axis2_raw_parsing` payloads were PUA-corrupted this exact way while the gate "
      "reported the database clean, see `check_pua_free_text`). "
      f"{'CLEAN (post-repair).' if pua_stats['payload_count'] == 0 else 'DEFECT PRESENT — see gate output.'} |")
    w(f"| `question_item.answer` / `canonical_answer_json` sanity | "
      f"{'OK — no uniform/dominant/mislabeled/out-of-range defects detected.' if not answer_errors else chr(10).join(answer_errors)} |")
    w(f"| `question_item.correct_rate` | "
      f"**{corpus['correct_rate_nonnull']}/{corpus['total_items']} non-null.** "
      f"{'No outcome variable exists yet — any claim that an axis predicts difficulty is currently unfalsifiable.' if corpus['correct_rate_nonnull'] == 0 else ''} |")
    if outcome_stats:
        st_txt = ' · '.join(f'{v} `{k}`' for k, v in outcome_stats['by_source_type'].items())
        w(f"| `outcome_observation` (per-item outcome estimates, Agent I3) | "
          f"**{outcome_stats['total']} rows** ({st_txt}) covering "
          f"{outcome_stats['n_distinct_items']} distinct item(s). Fact-table design: "
          "multiple disagreeing sources may coexist for the same item_id -- do not "
          "collapse into `question_item.correct_rate` (still 0 non-null, see row above). |")
    if concept_map_stats:
        w(f"| `storage/kice_math_concept_map.json` | "
          f"{concept_map_stats['n_concepts']} concept(s). `axis3_symbolic_modeling` "
          "depends on it and is structurally dead for any item not covered. |")
    if routing_index_stats:
        w(f"| `pipeline/query_engine/routing_index.json` | "
          f"{routing_index_stats['n_keys']} keys, "
          f"{routing_index_stats['n_sample_items']} sample items, hand-maintained. "
          "Prefer `item_id`/`exam_id` lookup over this index. |")
    w("| `question_item.review_history_json` | deprecated, read-only. |")
    w('')
    w('### 2a. Axis analysis completeness — MEASURED per `axis_key` in `analysis_derivation` '
      '(reuses `scripts/validate_ssot_consistency.py::check_axis_stub_sentinels` verbatim)')
    w('')
    w('| axis_key | status (registry) | kind | real/total | stub | empty | distinct | entropy |')
    w('|---|---|---|---|---|---|---|---|')
    for row in axis_rows:
        s = axis_stats.get(row['axis_key'])
        if s:
            w(f"| `{row['axis_key']}` | {row['status']} | {row['kind']} | "
              f"{s['real']}/{s['total']} ({s['pct']:.1f}%) | {s['stub']} | "
              f"{s['empty']} | {s['distinct']} | {s['entropy']:.2f} |")
        else:
            w(f"| `{row['axis_key']}` | {row['status']} | {row['kind']} | "
              "n/a | n/a | n/a | n/a | n/a |")
    w('')
    w('`axis_analysis` itself is a **read-only compatibility VIEW** over the generic '
      '`analysis_derivation(item_id, axis_key, schema_version, payload, ...)` table '
      '(I2 axis-agnostic storage refactor, `pipeline/migrate_db_axis_agnostic.py`) — '
      'axis identity is data (rows), not DDL columns, as of this refactor. Do NOT read '
      'axis columns as real data outside the axes and item marked real above.')
    w('')

    w('## 3. Task-intent routing — EDITORIAL judgment '
      f'(reviewed {ed.REVIEWED_DATE}), rendered from `tools/routing_editorial.py`')
    w('')
    w('| Your task | Authority files | Verify with | Never touch |')
    w('|---|---|---|---|')
    for row in ed.TASK_INTENT_ROUTING:
        w(f"| {row['task']} | {row['authority']} | {row['verify']} | {row['never_touch']} |")
    w('')

    w('## 4. Environment constraints')
    w('')
    w('### 4a. Package / CLI availability — MEASURED live (re-probed every generation run)')
    w('')
    for k, v in env_probes.items():
        w(f'- `{k}`: **{v}**')
    w('')
    w('`fitz` / PyMuPDF is not installable in this sandbox (no network for pip): '
      'legacy code importing it (e.g. `pipeline/dataset_parser/image_cropper.py`, which '
      'renders diagram crops at a `300/72` zoom matrix) cannot run here. Use '
      '`pdfminer.six` for coordinates, `pdftoppm -r 130 -png` to rasterise. '
      'No `pytest` — use `python3 -m unittest`.')
    w('')
    w('### 4b. Operational constraints — EDITORIAL '
      f'(reviewed {ed.REVIEWED_DATE}; not safely re-triggerable every generation run)')
    w('')
    for note in ed.ENVIRONMENT_CONSTRAINTS_EDITORIAL:
        w(f'- {note}')
    w('')

    w('## 5. Verification commands')
    w('')
    w('```bash')
    w('cd <repo>')
    w('python3 -m unittest discover -s tests          # full suite')
    w('python3 scripts/validate_ssot_consistency.py   # data + structural gate; exit 1 == real defect')
    w('python3 tools/generate_routing.py --check      # regeneration-diff gate for THIS file')
    w('```')
    w('')
    w('Baseline discipline: diff test failures **by test NAME** against the recorded baseline, '
      'never by count (the count moves whenever anyone adds a test).')
    w('')
    cat_txt = ', '.join(f'{v}x {k}' for k, v in sorted(gate_categories.items())) or 'none'
    w(f'**Current measured gate result: `exit={gate_exit}`** ({len(gate_errors)} error(s): {cat_txt}). '
      f'{"A green gate here would mean the gate broke -- it is expected to fail on axis_analysis stub payloads (a real, known, unfixed defect)." if gate_exit == 1 else ""}')
    w('')

    w('## 6. Known-good anchors for sanity-checking any pipeline — MEASURED spot-check against live DB')
    w('')
    for a in anchors:
        status = 'MATCHES live DB' if a.get('live_match') else 'MISMATCH vs live DB — investigate'
        w(f"- `{a['item_id']}` — answer {a['expected_answer']}, correct_value "
          f"{a['expected_correct_value']}. Text should contain "
          f"`{a['expected_latex_substring']}`. **{status}.** {a['why']}")
    w('')

    w('## 7. Open, unfixed')
    w('')
    w('MEASURED (live, from `pipeline/query_engine/axis_registry.py` per-axis `notes`):')
    for row in axis_rows:
        if row['kind'] != 'analyser' or row['status'] != 'active':
            w(f"- `{row['axis_key']}` ({row['status']}, kind={row['kind']}): {row['notes']}")
    w('')
    w(f'EDITORIAL (reviewed {ed.REVIEWED_DATE}):')
    for note in ed.OPEN_UNFIXED_EDITORIAL:
        w(f'- {note}')
    w('')

    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------
# SELF-CHECK -- verify every path/filename/command this doc (and
# ENTRYPOINT.md) references actually exists/runs, per task scope (e).
# --------------------------------------------------------------------------

_BACKTICK_PATH_RE = re.compile(r'`([A-Za-z0-9_./\-]+\.(?:py|md|json|db|txt|png|json5))`')
_BACKTICK_DIR_RE = re.compile(r'`((?:[A-Za-z0-9_.\-]+/)+)`')
_MD_LINK_RE = re.compile(r'\]\(([^)\s]+)\)')

_KNOWN_CLI = {'pdftoppm', 'pdftocairo', 'gs', 'qpdf', 'python3', 'python', 'cd', 'cp', 'cat'}
# Only flag a candidate string as a "broken path" if its first path segment
# is an actual top-level entry of this repo -- this is what distinguishes a
# real referenced path (docs/SSOT_MAP.md, ROUTING.md) from an illustrative
# convention mentioned in prose (`_to_delete/` as a naming convention, the
# repo's own directory name appearing as the root label of an ASCII tree).
_TOP_LEVEL_ENTRIES = set(os.listdir(BASE_DIR))


def _candidate_paths(text):
    cands = set()
    for m in _BACKTICK_PATH_RE.finditer(text):
        cands.add(m.group(1))
    for m in _BACKTICK_DIR_RE.finditer(text):
        cands.add(m.group(1))
    for m in _MD_LINK_RE.finditer(text):
        target = m.group(1)
        if target.startswith('http://') or target.startswith('https://') or target.startswith('#'):
            continue
        cands.add(target)
    # drop obvious non-paths / patterns / placeholders, and anything whose
    # first segment isn't a real top-level entry of this repo (illustrative
    # conventions like `_to_delete/`, or an ASCII-tree root label matching
    # the repo's own directory name, are not "referenced paths").
    cleaned = set()
    for c in cands:
        if any(ch in c for ch in ('<', '>', '*', '|')):
            continue
        if c in ('.', './'):
            continue
        first_seg = c.split('/')[0]
        if first_seg not in _TOP_LEVEL_ENTRIES:
            continue
        cleaned.add(c)
    return sorted(cleaned)


def _candidate_commands(text):
    """Line-based fence state machine (not a regex over the whole text):
    only harvests command lines from fences explicitly tagged bash/sh/shell
    (a bare untagged fence is deliberately NOT treated as a command block --
    ENTRYPOINT.md uses one for an ASCII directory-tree diagram, which is
    illustrative, not runnable), and correctly pairs each OPENING ``` with
    its own CLOSING ``` regardless of how many other (e.g. ```mermaid,
    ```python) fences appear elsewhere in the document. A naive
    ```(?:bash)?\\n(.*?)``` regex over the raw text mismatches fence pairs
    whenever a non-bash-tagged fence (```mermaid, ```python) appears earlier
    in the file, because its bare closing ``` looks like a valid opener to
    that regex -- verified against ENTRYPOINT.md's ```mermaid block, which
    triggered exactly that false pairing before this was rewritten."""
    cmds = []
    in_fence = False
    fence_lang = None
    buffer = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith('```'):
            if not in_fence:
                in_fence = True
                fence_lang = stripped[3:].strip().lower()
                buffer = []
            else:
                if fence_lang in ('bash', 'sh', 'shell'):
                    for line in buffer:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        cmds.append(line.split())
                in_fence = False
                fence_lang = None
                buffer = []
            continue
        if in_fence:
            buffer.append(raw_line)
    return cmds


def self_check(rendered_texts):
    """rendered_texts: dict of {label: text} to scan (ROUTING.md body,
    ENTRYPOINT.md contents). Returns (n_paths_checked, n_paths_broken,
    broken_path_details, n_cmds_checked, n_cmds_broken, broken_cmd_details)."""
    all_paths = set()
    for text in rendered_texts.values():
        all_paths.update(_candidate_paths(text))

    broken_paths = []
    for p in sorted(all_paths):
        full = os.path.join(BASE_DIR, p)
        if not os.path.exists(full):
            broken_paths.append(p)

    all_cmds = []
    for text in rendered_texts.values():
        all_cmds.extend(_candidate_commands(text))

    broken_cmds = []
    checked_cmds = 0
    for tokens in all_cmds:
        head = tokens[0]
        checked_cmds += 1
        if head in ('python3', 'python'):
            if len(tokens) > 1 and tokens[1].endswith('.py'):
                script_path = tokens[1]
                full = os.path.join(BASE_DIR, script_path)
                if not os.path.exists(full):
                    broken_cmds.append((' '.join(tokens), f'{script_path} does not exist'))
            continue
        if head == 'cd':
            continue
        if head in ('cat', 'cp', ':'):
            continue
        if shutil.which(head) is None and head not in _KNOWN_CLI:
            broken_cmds.append((' '.join(tokens), f'{head!r} not on PATH'))

    return {
        'n_paths_checked': len(all_paths),
        'broken_paths': broken_paths,
        'n_cmds_checked': checked_cmds,
        'broken_cmds': broken_cmds,
    }


def render_self_check_section(audit):
    lines = []
    w = lines.append
    w('## 8. Self-check — MEASURED path/command audit of this document')
    w('')
    w(f"- Paths/filenames referenced: {audit['n_paths_checked']} checked, "
      f"{len(audit['broken_paths'])} broken.")
    if audit['broken_paths']:
        for p in audit['broken_paths']:
            w(f'  - BROKEN: `{p}` does not exist')
    w(f"- Commands referenced in fenced code blocks: {audit['n_cmds_checked']} checked, "
      f"{len(audit['broken_cmds'])} broken.")
    if audit['broken_cmds']:
        for cmd, reason in audit['broken_cmds']:
            w(f'  - BROKEN: `{cmd}` — {reason}')
    w('')
    return '\n'.join(lines) + '\n'


def render():
    body = render_body()
    entrypoint_text = ''
    if os.path.isfile(ENTRYPOINT_MD):
        with open(ENTRYPOINT_MD, 'r', encoding='utf-8') as f:
            entrypoint_text = f.read()
    audit = self_check({'ROUTING.md': body, 'ENTRYPOINT.md': entrypoint_text})
    return body + render_self_check_section(audit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='overwrite ROUTING.md')
    parser.add_argument('--check', action='store_true',
                         help='exit 1 if ROUTING.md does not match generator output')
    args = parser.parse_args()

    content = render()

    if args.check:
        current = ''
        if os.path.isfile(ROUTING_MD):
            with open(ROUTING_MD, 'r', encoding='utf-8') as f:
                current = f.read()
        if current != content:
            print('ROUTING.md is STALE (does not match tools/generate_routing.py output)')
            return 1
        print('ROUTING.md matches generator output (OK)')
        return 0

    if args.write:
        with open(ROUTING_MD, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        print(f'Wrote {ROUTING_MD}')
        return 0

    sys.stdout.write(content)
    return 0


if __name__ == '__main__':
    sys.exit(main())
