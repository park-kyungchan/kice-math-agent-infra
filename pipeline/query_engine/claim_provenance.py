# -*- coding: utf-8 -*-
"""
Claim-Level Provenance (v2.8.1)
===============================
Provenance is attached to INDIVIDUAL CLAIMS (item x axis x json_pointer),
persisted in the `claim_provenance` table — never synthesized at read time.
An axis with no analysis stays ABSENT; an axis with no recorded claims has
no provenance. Empty is never presented as present (P0-4 fix).

LLM/agent-agnostic: `derived_by` is a JSON document
{"actor_type": "AGENT"|"TEACHER"|"SYSTEM", "actor_id": str, "model": str|null}
— the model/vendor is descriptive data, never a code dependency.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

CLAIM_TYPES = ("FACT", "INFERENCE", "ESTIMATE", "OPINION")
AXES = tuple(f"Axis_{i}" for i in range(1, 9))
HUMAN_REVIEW_STATUSES = ("UNREVIEWED", "REVIEW_REQUIRED", "HUMAN_VERIFIED", "HUMAN_REJECTED")


class ProvenanceError(Exception):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='claim_provenance'"
    ).fetchone()
    return row is not None


def record_claim(
    conn: sqlite3.Connection,
    item_id: str,
    axis: str,
    json_pointer: str,
    statement: str,
    claim_type: str,
    source_refs: Optional[List[Dict[str, Any]]] = None,
    derived_by: Optional[Dict[str, Any]] = None,
    confidence_score: Optional[float] = None,
    counter_evidence: Optional[List[Any]] = None,
    human_review_status: str = "UNREVIEWED",
) -> Dict[str, Any]:
    """Persist one claim with full provenance. Raises on invalid input —
    a claim without a source or derivation record is not a claim."""
    if not _table_exists(conn):
        raise ProvenanceError(
            "claim_provenance table missing — run pipeline/migrate_db_v2_8_1.py first"
        )
    if axis not in AXES:
        raise ProvenanceError(f"Unknown axis: {axis!r}")
    if claim_type not in CLAIM_TYPES:
        raise ProvenanceError(f"Unknown claim_type: {claim_type!r}")
    if human_review_status not in HUMAN_REVIEW_STATUSES:
        raise ProvenanceError(f"Unknown human_review_status: {human_review_status!r}")
    if not statement or not statement.strip():
        raise ProvenanceError("statement must be non-empty")
    if not json_pointer or not json_pointer.startswith("/"):
        raise ProvenanceError("json_pointer must be an RFC 6901 pointer starting with '/'")
    if not derived_by or "actor_type" not in derived_by or "actor_id" not in derived_by:
        raise ProvenanceError("derived_by must include actor_type and actor_id")

    item_row = conn.execute(
        "SELECT 1 FROM question_item WHERE item_id = ?", (item_id,)
    ).fetchone()
    if item_row is None:
        raise ProvenanceError(f"Item {item_id} not found")

    claim = {
        "claim_id": f"CLM-{uuid.uuid4()}",
        "item_id": item_id,
        "axis": axis,
        "json_pointer": json_pointer,
        "statement": statement,
        "claim_type": claim_type,
        "source_refs_json": json.dumps(source_refs or [], ensure_ascii=False),
        "derived_by_json": json.dumps(derived_by, ensure_ascii=False),
        "confidence_score": confidence_score,
        "counter_evidence_json": json.dumps(counter_evidence or [], ensure_ascii=False),
        "human_review_status": human_review_status,
        "human_review_event_id": None,
        "created_at": _utcnow(),
    }
    conn.execute(
        """INSERT INTO claim_provenance
           (claim_id, item_id, axis, json_pointer, statement, claim_type,
            source_refs_json, derived_by_json, confidence_score,
            counter_evidence_json, human_review_status, human_review_event_id, created_at)
           VALUES (:claim_id, :item_id, :axis, :json_pointer, :statement, :claim_type,
                   :source_refs_json, :derived_by_json, :confidence_score,
                   :counter_evidence_json, :human_review_status, :human_review_event_id,
                   :created_at)""",
        claim,
    )
    conn.commit()
    return claim


def _row_to_claim(row) -> Dict[str, Any]:
    cols = (
        "claim_id", "item_id", "axis", "json_pointer", "statement", "claim_type",
        "source_refs_json", "derived_by_json", "confidence_score",
        "counter_evidence_json", "human_review_status", "human_review_event_id",
        "created_at",
    )
    d = dict(zip(cols, row))
    for json_col, plain in (
        ("source_refs_json", "source_refs"),
        ("derived_by_json", "derived_by"),
        ("counter_evidence_json", "counter_evidence"),
    ):
        try:
            d[plain] = json.loads(d.pop(json_col))
        except (json.JSONDecodeError, TypeError):
            d[plain] = None
    return d


def get_claims_for_items(
    conn: sqlite3.Connection, item_ids: List[str]
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Returns {item_id: {axis: [claims]}} for the given items.
    Items or axes with no recorded claims are simply absent."""
    if not item_ids or not _table_exists(conn):
        return {}
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    CHUNK = 500
    for i in range(0, len(item_ids), CHUNK):
        chunk = item_ids[i:i + CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""SELECT claim_id, item_id, axis, json_pointer, statement, claim_type,
                       source_refs_json, derived_by_json, confidence_score,
                       counter_evidence_json, human_review_status, human_review_event_id,
                       created_at
                FROM claim_provenance WHERE item_id IN ({placeholders})
                ORDER BY created_at ASC""",
            chunk,
        ).fetchall()
        for row in rows:
            claim = _row_to_claim(row)
            out.setdefault(claim["item_id"], {}).setdefault(claim["axis"], []).append(claim)
    return out


def set_human_review(
    conn: sqlite3.Connection,
    item_id: str,
    status: str,
    event_id: Optional[str] = None,
) -> int:
    """Link a teacher review outcome to all claims of an item.
    Called by review_state.transition() on TEACHER_APPROVED / REJECTED."""
    if status not in HUMAN_REVIEW_STATUSES:
        raise ProvenanceError(f"Unknown human_review_status: {status!r}")
    if not _table_exists(conn):
        return 0
    cur = conn.execute(
        """UPDATE claim_provenance
           SET human_review_status = ?, human_review_event_id = ?
           WHERE item_id = ?""",
        (status, event_id, item_id),
    )
    conn.commit()
    return cur.rowcount
