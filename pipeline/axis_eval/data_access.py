# -*- coding: utf-8 -*-
"""
Read-only data access for the axis-eval harness.

MISSION CONSTRAINT (ROUTING.md sec.4 / brief sec.4): NEVER open
storage/parsed_dataset.db directly for anything in this package. Every
caller must pass an explicit db_path that already points at a throwaway
copy (e.g. /tmp/eval.db). connect_readonly() opens sqlite3 in `mode=ro`
URI form as a second layer of protection against an accidental write.
"""
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Opens `db_path` strictly read-only (sqlite3 URI `mode=ro`) -- any
    accidental INSERT/UPDATE/DDL against the connection raises
    `sqlite3.OperationalError: attempt to write a readonly database`
    instead of silently succeeding against the wrong file."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all_axis_keys(conn: sqlite3.Connection) -> List[str]:
    """All distinct axis_key values actually present in analysis_derivation
    -- this harness scores whatever is there, including a brand-new
    axis_key nobody has registered in axis_registry.py yet (open-world
    storage, per axis_registry.py's own docstring)."""
    cur = conn.execute("SELECT DISTINCT axis_key FROM analysis_derivation ORDER BY axis_key")
    return [r[0] for r in cur.fetchall()]


def fetch_axis_payloads(conn: sqlite3.Connection, axis_key: str,
                         schema_version: Optional[int] = None) -> Dict[str, Optional[str]]:
    """Returns {item_id: raw_payload_json_str_or_None} for every
    `question_item` row (LEFT JOIN so an item with zero analysis_derivation
    rows for this axis_key still appears, payload=None). If schema_version
    is None, uses the MAX schema_version present per item_id for this axis
    (so a partially-migrated axis with mixed schema versions still yields
    one payload per item -- the newest)."""
    if schema_version is not None:
        cur = conn.execute(
            """
            SELECT q.item_id AS item_id, d.payload AS payload
            FROM question_item q
            LEFT JOIN analysis_derivation d
              ON d.item_id = q.item_id AND d.axis_key = ? AND d.schema_version = ?
            """,
            (axis_key, schema_version),
        )
    else:
        cur = conn.execute(
            """
            SELECT q.item_id AS item_id, d.payload AS payload
            FROM question_item q
            LEFT JOIN (
                SELECT item_id, payload,
                       ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY schema_version DESC) AS rn
                FROM analysis_derivation
                WHERE axis_key = ?
            ) d ON d.item_id = q.item_id AND d.rn = 1
            """,
            (axis_key,),
        )
    return {r["item_id"]: r["payload"] for r in cur.fetchall()}


def fetch_item_truth(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    """Returns {item_id: {"answer": int, "response_type": str,
    "correct_value": Optional[float], "correct_option_index": Optional[int],
    "item_number": int, "track": str}} for all 1,350 items -- the
    official-answer ground truth used by M4. Never includes latex_content
    (raw question text) -- callers that need M4's non-circular solver input
    must go through m4_informational_validity.sanitize_payload /
    build_solver_item, which are the only places allowed to combine axis
    payload + truth, and only for SCORING (never as solver input)."""
    cur = conn.execute(
        "SELECT item_id, item_number, track, answer, canonical_answer_json FROM question_item"
    )
    out: Dict[str, Dict[str, Any]] = {}
    for row in cur.fetchall():
        canon_raw = row["canonical_answer_json"]
        response_type = None
        correct_value = None
        correct_option_index = None
        if canon_raw:
            try:
                canon = json.loads(canon_raw)
                response_type = canon.get("response_type")
                correct_value = canon.get("correct_value")
                correct_option_index = canon.get("correct_option_index")
            except (TypeError, ValueError):
                pass
        if response_type is None:
            # Fallback derivation per ROUTING.md sec.1: items 1-15,23-28 are
            # MULTIPLE_CHOICE; 16-22,29-30 are SHORT_ANSWER.
            n = row["item_number"]
            if (1 <= n <= 15) or (23 <= n <= 28):
                response_type = "MULTIPLE_CHOICE"
            elif (16 <= n <= 22) or n in (29, 30):
                response_type = "SHORT_ANSWER"
        out[row["item_id"]] = {
            "answer": row["answer"],
            "response_type": response_type,
            "correct_value": correct_value,
            "correct_option_index": correct_option_index,
            "item_number": row["item_number"],
            "track": row["track"],
        }
    return out


def row_counts(conn: sqlite3.Connection) -> Tuple[int, int]:
    """(question_item count, analysis_derivation count) -- used by the
    migration idempotency test to prove row preservation."""
    q = conn.execute("SELECT COUNT(*) FROM question_item").fetchone()[0]
    d = conn.execute("SELECT COUNT(*) FROM analysis_derivation").fetchone()[0]
    return q, d
