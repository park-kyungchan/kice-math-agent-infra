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

Usage: python scripts/validate_ssot_consistency.py [--db PATH]
"""
import argparse
import json
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
    if not re.fullmatch(r'v\d+\.\d+\.\d+', version):
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
        if state.get('teacher_governance_loop') != 'ACTIVE':
            errors.append(f"ci_evidence: conclusion is success but teacher_governance_loop must be 'ACTIVE', got {state.get('teacher_governance_loop')!r}")
    else:
        if state.get('teacher_governance_loop') == 'ACTIVE':
            errors.append(f"ci_evidence: non-success conclusion {conclusion!r} cannot permit teacher_governance_loop 'ACTIVE'")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DEFAULT_DB)
    args = parser.parse_args()

    errors = []
    check_ddl(errors, args.db)
    check_manifest_vs_state(errors)
    check_versions(errors)
    check_transition_matrix(errors)
    check_ci_evidence(errors)

    if errors:
        print('SSoT CONSISTENCY: FAIL')
        for e in errors:
            print(f'  - {e}')
        return 1
    print('SSoT CONSISTENCY: OK (DDL, manifest/state, versions, transition matrix, ci_evidence)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
