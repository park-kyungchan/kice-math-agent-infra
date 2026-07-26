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
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# SSoT for the closed actor_type enum: defined once in review_state.py and
# imported here rather than duplicated. Verified non-circular: review_state.py
# only imports claim_provenance lazily, inside function bodies, never at
# module load time (see review_state._write_transition_in_txn()).
from pipeline.query_engine.review_state import ACTOR_TYPES

# Single source of axis identity (I2 axis-agnostic storage refactor): the
# 'Axis_1'..'Axis_8' <-> axisN_whatever column mapping used to be
# hand-written a second time here (independently of the identical dict in
# selective_fetcher.py); both now resolve through
# pipeline/query_engine/axis_registry.py. NOTE: claim_provenance's `axis`
# CHECK constraint (see docs/Taxonomy_Spec.md) is still closed to exactly
# these 8 legacy Axis_N labels -- claim-level provenance was NOT extended
# to arbitrary new axis_key values as part of the I2 refactor; see the I2
# migration report for that explicitly-flagged limitation.
from pipeline.query_engine.axis_registry import AXIS_COLUMN_BY_DICT_KEY

import hashlib

CLAIM_TYPES = ("FACT", "INFERENCE", "ESTIMATE", "OPINION")
AXES = tuple(f"Axis_{i}" for i in range(1, 9))
HUMAN_REVIEW_STATUSES = ("UNREVIEWED", "REVIEW_REQUIRED", "HUMAN_VERIFIED", "HUMAN_REJECTED")

AXIS_COLUMN: Dict[str, str] = dict(AXIS_COLUMN_BY_DICT_KEY)

QUESTION_ITEM_FIELDS = {
    "exam_id", "track", "item_number", "score", "answer", "correct_rate", "asset_image_url", "rect_json"
}


class ProvenanceError(Exception):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='claim_provenance'"
    ).fetchone()
    return row is not None


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(value: Any, mode: str = "json") -> str:
    if mode in ("raw", "utf8"):
        if not isinstance(value, str):
            value = str(value)
        data = value.encode("utf-8")
    else:
        data = canonical_json_bytes(value)
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _resolve_json_pointer(document: Any, pointer: str) -> Tuple[bool, Any]:
    """RFC 6901 JSON Pointer resolution helper.
    Returns (True, resolved_value) iff pointer resolves inside document."""
    if pointer == "":
        return True, document
    if not pointer.startswith("/"):
        return False, None
    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if token == "0" or re.fullmatch(r"[1-9][0-9]*", token):
                idx = int(token)
            else:
                return False, None
            if idx >= len(current):
                return False, None
            current = current[idx]
        else:
            return False, None
    return True, current


def _json_pointer_resolves(document: Any, pointer: str) -> bool:
    ok, _ = _resolve_json_pointer(document, pointer)
    return ok


def validate_source_ref(conn: sqlite3.Connection, ref: Any) -> Dict[str, Any]:
    """Validate one source reference according to the closed v1 schema.
    Raises ProvenanceError on invalid input, unknown keys, missing targets, or hash mismatches."""
    if not isinstance(ref, dict) or not ref:
        raise ProvenanceError("Every item in source_refs must be a non-empty dictionary")

    if ref.get("schema_version") != 1:
        raise ProvenanceError(f"source_ref schema_version must be 1, got {ref.get('schema_version')!r}")

    source_type = ref.get("source_type")
    if source_type not in ("ORIGINAL_EXAM_TEXT", "QUESTION_ITEM_FIELD", "AXIS_ANALYSIS"):
        raise ProvenanceError(f"Unknown or unsupported source_type: {source_type!r}")

    hash_val = ref.get("content_hash")
    if not isinstance(hash_val, str) or not re.fullmatch(r"^sha256:[0-9a-f]{64}$", hash_val):
        raise ProvenanceError(f"content_hash must be 'sha256:<64 hex chars>', got {hash_val!r}")

    item_id = ref.get("item_id")
    if not item_id or not isinstance(item_id, str):
        raise ProvenanceError("source_ref item_id must be a non-empty string")

    if source_type == "ORIGINAL_EXAM_TEXT":
        allowed_keys = {"schema_version", "source_type", "item_id", "field", "content_hash"}
        extra_keys = set(ref.keys()) - allowed_keys
        if extra_keys:
            raise ProvenanceError(f"Unknown key(s) in ORIGINAL_EXAM_TEXT source_ref: {sorted(extra_keys)}")
        if ref.get("field") != "latex_content":
            raise ProvenanceError(f"ORIGINAL_EXAM_TEXT field must be 'latex_content', got {ref.get('field')!r}")
        
        row = conn.execute("SELECT latex_content FROM question_item WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise ProvenanceError(f"Referenced item {item_id!r} not found in question_item")
        if row[0] is None:
            raise ProvenanceError(f"Stored field latex_content for item {item_id!r} is null")
        
        expected_hash = content_hash(row[0], mode="utf8")
        if hash_val != expected_hash:
            raise ProvenanceError(f"content_hash mismatch for ORIGINAL_EXAM_TEXT: expected {expected_hash}, got {hash_val}")

    elif source_type == "QUESTION_ITEM_FIELD":
        allowed_keys = {"schema_version", "source_type", "item_id", "field", "content_hash"}
        extra_keys = set(ref.keys()) - allowed_keys
        if extra_keys:
            raise ProvenanceError(f"Unknown key(s) in QUESTION_ITEM_FIELD source_ref: {sorted(extra_keys)}")
        field = ref.get("field")
        if field not in QUESTION_ITEM_FIELDS:
            raise ProvenanceError(f"QUESTION_ITEM_FIELD field must be one of {sorted(QUESTION_ITEM_FIELDS)}, got {field!r}")
        
        row = conn.execute(f"SELECT {field} FROM question_item WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise ProvenanceError(f"Referenced item {item_id!r} not found in question_item")
        if row[0] is None:
            raise ProvenanceError(f"Stored field {field!r} for item {item_id!r} is null")

        val = row[0]
        if field == "rect_json" and isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                pass
        expected_hash = content_hash(val, mode="json")
        if hash_val != expected_hash:
            raise ProvenanceError(f"content_hash mismatch for QUESTION_ITEM_FIELD {field!r}: expected {expected_hash}, got {hash_val}")

    elif source_type == "AXIS_ANALYSIS":
        allowed_keys = {"schema_version", "source_type", "item_id", "field", "json_pointer", "content_hash"}
        extra_keys = set(ref.keys()) - allowed_keys
        if extra_keys:
            raise ProvenanceError(f"Unknown key(s) in AXIS_ANALYSIS source_ref: {sorted(extra_keys)}")
        field = ref.get("field")
        col_name = AXIS_COLUMN.get(field, field)
        if col_name not in AXIS_COLUMN.values():
            raise ProvenanceError(f"AXIS_ANALYSIS field must be an axis column, got {field!r}")
        
        json_pointer = ref.get("json_pointer")
        if not isinstance(json_pointer, str) or (json_pointer != "" and not json_pointer.startswith("/")):
            raise ProvenanceError(f"AXIS_ANALYSIS json_pointer must be an RFC 6901 pointer, got {json_pointer!r}")

        row = conn.execute(f"SELECT {col_name} FROM axis_analysis WHERE item_id = ?", (item_id,)).fetchone()
        if row is None or row[0] is None:
            raise ProvenanceError(f"Referenced axis {col_name!r} analysis for item {item_id!r} not found or null")

        try:
            axis_document = json.loads(row[0])
        except Exception as e:
            raise ProvenanceError(f"Stored axis {col_name!r} for item {item_id!r} is not valid JSON: {e}")

        ok, target_val = _resolve_json_pointer(axis_document, json_pointer)
        if not ok:
            raise ProvenanceError(f"json_pointer {json_pointer!r} failed to resolve inside axis {col_name!r} for item {item_id!r}")

        expected_hash = content_hash(target_val, mode="json")
        if hash_val != expected_hash:
            raise ProvenanceError(f"content_hash mismatch for AXIS_ANALYSIS {field!r} pointer {json_pointer!r}: expected {expected_hash}, got {hash_val}")

    return ref


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
    if not source_refs or not isinstance(source_refs, list):
        raise ProvenanceError(
            "source_refs must be a non-empty list — a claim without a source is not a claim"
        )
    seen_refs = set()
    validated_refs = []
    for ref in source_refs:
        norm_ref = validate_source_ref(conn, ref)
        ref_key = json.dumps(norm_ref, sort_keys=True)
        if ref_key in seen_refs:
            raise ProvenanceError("Duplicate source reference found in source_refs")
        seen_refs.add(ref_key)
        validated_refs.append(norm_ref)
    source_refs = validated_refs

    if not derived_by or "actor_type" not in derived_by or "actor_id" not in derived_by:
        raise ProvenanceError("derived_by must include actor_type and actor_id")
    if derived_by["actor_type"] not in ACTOR_TYPES:
        raise ProvenanceError(
            f"derived_by.actor_type must be one of {ACTOR_TYPES}, got {derived_by['actor_type']!r}"
        )
    if confidence_score is not None:
        if isinstance(confidence_score, bool) or not isinstance(confidence_score, (int, float)):
            raise ProvenanceError(f"confidence_score must be a number in [0.0, 1.0], got {confidence_score!r}")
        if not (0.0 <= float(confidence_score) <= 1.0):
            raise ProvenanceError(f"confidence_score must be within [0.0, 1.0], got {confidence_score!r}")

    item_row = conn.execute(
        "SELECT 1 FROM question_item WHERE item_id = ?", (item_id,)
    ).fetchone()
    if item_row is None:
        raise ProvenanceError(f"Item {item_id} not found")

    axis_column = AXIS_COLUMN[axis]
    axis_row = conn.execute(
        f"SELECT {axis_column} FROM axis_analysis WHERE item_id = ?", (item_id,)
    ).fetchone()
    if axis_row is None or axis_row[0] is None:
        raise ProvenanceError(
            f"Axis {axis} has no recorded analysis for item {item_id}; cannot attach "
            "a claim's json_pointer to a field that does not exist yet"
        )
    try:
        axis_document = json.loads(axis_row[0])
    except (json.JSONDecodeError, TypeError) as e:
        raise ProvenanceError(f"Axis {axis} analysis for item {item_id} is not valid JSON: {e}")
    if not _json_pointer_resolves(axis_document, json_pointer):
        raise ProvenanceError(
            f"json_pointer {json_pointer!r} does not resolve inside axis {axis} "
            f"analysis for item {item_id}"
        )

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


def _set_human_review_in_txn(
    conn: sqlite3.Connection,
    item_id: str,
    status: str,
    event_id: Optional[str] = None,
) -> int:
    """Same UPDATE as set_human_review(), but operates on the CALLER's
    already-open transaction and never calls conn.commit()/rollback() itself
    (P0-3 fix). Used by review_state.transition() so the claim-provenance
    linkage is folded into the SAME BEGIN IMMEDIATE transaction as the event
    insert and question_item snapshot update, instead of a second,
    separately-committed transaction that could leave the two durably
    inconsistent if this write ever failed."""
    if status not in HUMAN_REVIEW_STATUSES:
        raise ProvenanceError(f"Unknown human_review_status: {status!r}")
    if not _table_exists(conn):
        raise ProvenanceError("claim_provenance table missing — fail-closed requirement")
    cur = conn.execute(
        """UPDATE claim_provenance
           SET human_review_status = ?, human_review_event_id = ?
           WHERE item_id = ?""",
        (status, event_id, item_id),
    )
    return cur.rowcount


def set_human_review(
    conn: sqlite3.Connection,
    item_id: str,
    status: str,
    event_id: Optional[str] = None,
) -> int:
    """Link a teacher review outcome to all claims of an item, committing
    immediately. Standalone public entry point — review_state.transition()
    does NOT call this; it calls _set_human_review_in_txn() directly so the
    write joins its own transaction instead of committing here (P0-3)."""
    rowcount = _set_human_review_in_txn(conn, item_id, status, event_id)
    conn.commit()
    return rowcount
