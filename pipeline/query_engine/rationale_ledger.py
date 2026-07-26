# -*- coding: utf-8 -*-
"""The rationale ledger: why an agent concluded what it concluded, in a form a human can read.

WHY IT IS NOT AN AXIS
---------------------
This repository already tried recording agent reasoning once, in `axis4_contextual_tree`, and
its own registry records the verdict: that axis "records AGENT REASONING (backtrack telemetry),
not a property of the item itself". Reasoning is a property of the ANALYSIS ACT, not of the
exam question. Mixed into an analytical payload it corrupts the payload; kept separate it is
one of the most useful artefacts in the system. So it lives here, as telemetry, and never as an
axis_key.

WHY EVERY STEP MUST CITE A POINTER
----------------------------------
Prose and structured payloads drift apart the moment they are authored separately. Requiring
every step to name the payload field it justifies makes drift detectable rather than gradual:
Gate A asks whether every field has a reason, Gate B asks whether every reason points at
something real.

WHY IT DOUBLES AS A CIRCULARITY DETECTOR
----------------------------------------
A step has to declare what it consumed. A derivation that quietly used the answer key therefore
has to either declare it -- and be caught -- or lie about its inputs, which is a different and
much harder thing to do by accident. That is why the ledger is worth its cost even before
anyone reads it for feedback.

THE FIVE SECTIONS
-----------------
CONSIDERED  what was on the table
REJECTED    what was ruled out and why  <- the highest-value section, and the one usually missing
EVIDENCE    what in the item forced this
UNCERTAINTY what is shaky, and how much
FALSIFIER   the observation that would overturn this step

REJECTED is emphasised deliberately. A trace that records only the path taken teaches a reviewer
nothing about the paths not taken, which is where the reasoning actually happened.
"""
import hashlib
import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence

SECTIONS = ('CONSIDERED', 'REJECTED', 'EVIDENCE', 'UNCERTAINTY', 'FALSIFIER')

VERDICTS = ('ACCEPT', 'REJECT_CONCLUSION', 'REJECT_REASONING', 'NEEDS_EVIDENCE')
# REJECT_REASONING is the one no existing schema in this repository could express: a right
# answer reached by invalid reasoning. It is invisible to every check that only looks at
# outcomes, and it is exactly what a teacher notices first.

DDL = """
CREATE TABLE IF NOT EXISTS rationale_step (
    step_id          TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    item_id          TEXT NOT NULL,
    axis_key         TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    json_pointer     TEXT NOT NULL,
    section          TEXT NOT NULL CHECK (section IN
                       ('CONSIDERED','REJECTED','EVIDENCE','UNCERTAINTY','FALSIFIER')),
    body_md          TEXT NOT NULL,
    inputs_cited_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(inputs_cited_json)),
    prev_step_hash   TEXT,
    step_hash        TEXT NOT NULL,
    created_at       TEXT NOT NULL
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(DDL)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_rationale_item ON rationale_step(item_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_rationale_run ON rationale_step(run_id)')


def step_hash(prev: Optional[str], payload: Dict[str, Any]) -> str:
    """Hash-chained so a step cannot be silently rewritten after review."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(((prev or '') + blob).encode('utf-8')).hexdigest()


def append_step(conn, run_id, item_id, axis_key, seq, json_pointer, section, body_md,
                inputs_cited: Sequence[str], created_at: str) -> str:
    if section not in SECTIONS:
        raise ValueError(f'unknown section {section!r}')
    prev = conn.execute(
        'SELECT step_hash FROM rationale_step WHERE run_id=? ORDER BY seq DESC, rowid DESC LIMIT 1',
        (run_id,),
    ).fetchone()
    prev_hash = prev[0] if prev else None
    payload = {'run_id': run_id, 'item_id': item_id, 'axis_key': axis_key, 'seq': seq,
               'json_pointer': json_pointer, 'section': section, 'body_md': body_md,
               'inputs_cited': list(inputs_cited)}
    h = step_hash(prev_hash, payload)
    sid = f'rs-{item_id}-{axis_key}-{seq:04d}-{section.lower()}'
    conn.execute(
        'INSERT INTO rationale_step (step_id, run_id, item_id, axis_key, seq, json_pointer, '
        'section, body_md, inputs_cited_json, prev_step_hash, step_hash, created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (sid, run_id, item_id, axis_key, seq, json_pointer, section, body_md,
         json.dumps(list(inputs_cited), ensure_ascii=True), prev_hash, h, created_at),
    )
    return sid


# --------------------------------------------------------------------------
# GATES
# --------------------------------------------------------------------------
def _leaf_pointers(obj: Any, prefix: str = '') -> List[str]:
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            out += _leaf_pointers(v, f'{prefix}/{k}')
        return out or [prefix or '/']
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj):
            out += _leaf_pointers(v, f'{prefix}/{i}')
        return out or [prefix or '/']
    return [prefix or '/']


def _resolve(obj: Any, pointer: str) -> bool:
    cur = obj
    for token in [t for t in pointer.split('/') if t != '']:
        if isinstance(cur, dict) and token in cur:
            cur = cur[token]
        elif isinstance(cur, list) and token.isdigit() and int(token) < len(cur):
            cur = cur[int(token)]
        else:
            return False
    return True


def gate_a(payload: Dict[str, Any], steps: Iterable[Dict[str, Any]]) -> List[str]:
    """Every payload field must have at least one rationale step behind it."""
    cited = {s['json_pointer'] for s in steps}
    return [f'Gate A: payload field {p} has no rationale step'
            for p in _leaf_pointers(payload) if p not in cited]


def gate_b(payload: Dict[str, Any], steps: Iterable[Dict[str, Any]]) -> List[str]:
    """Every rationale step must point at something that exists."""
    return [f'Gate B: rationale step {s.get("step_id", "?")} cites {s["json_pointer"]}, '
            f'which does not resolve in the payload'
            for s in steps if not _resolve(payload, s['json_pointer'])]


def gate_sections(steps: Iterable[Dict[str, Any]]) -> List[str]:
    """All five sections must be present for each json_pointer that has any step at all.

    A trace with EVIDENCE but no REJECTED records the path taken and nothing about the paths
    not taken, which is where the reasoning was.
    """
    by_pointer: Dict[str, set] = {}
    for s in steps:
        by_pointer.setdefault(s['json_pointer'], set()).add(s['section'])
    problems = []
    for pointer, present in sorted(by_pointer.items()):
        missing = [s for s in SECTIONS if s not in present]
        if missing:
            problems.append(f'Gate SECTIONS: {pointer} is missing {missing}')
    return problems


def run_gates(payload: Dict[str, Any], steps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    problems = gate_a(payload, steps) + gate_b(payload, steps) + gate_sections(steps)
    return {'verdict': 'PASS' if not problems else 'FAIL', 'problems': problems}


def render_markdown(steps: Sequence[Dict[str, Any]]) -> str:
    """Human-readable rendering. The canonical record is the table; this is a generated view and
    must never be hand-edited back into the ledger."""
    lines = ['# Rationale trace', '']
    for pointer in sorted({s['json_pointer'] for s in steps}):
        lines.append(f'## {pointer}')
        for section in SECTIONS:
            for s in [x for x in steps if x['json_pointer'] == pointer and x['section'] == section]:
                lines.append(f'**{section}** — {s["body_md"].strip()}')
                if s.get('inputs_cited'):
                    lines.append(f'  <sub>inputs: {", ".join(s["inputs_cited"])}</sub>')
        lines.append('')
    return '\n'.join(lines)
