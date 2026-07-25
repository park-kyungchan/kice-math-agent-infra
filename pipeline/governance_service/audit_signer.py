# -*- coding: utf-8 -*-
"""
Cryptographic Audit Signer & Chain Verifier (v2.8.4)
====================================================
Implements HMAC-SHA-256 tamper-evident event signing, per-item hash chaining,
and full verification of teacher_review_event records.
"""
import hashlib
import hmac
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

import os

GENESIS_PREV_HASH = "0" * 64
DEFAULT_SERVICE_KEY = "kice-governance-service-hmac-secret-key-v1"
DEFAULT_KEY_ID = "v1-service-key"


class AuditKeyError(Exception):
    """Raised when HMAC secret key is missing or unconfigured."""
    pass


def get_secret_key(fallback_ok: bool = True) -> str:
    key = os.environ.get("KICE_GOVERNANCE_HMAC_SECRET")
    if key:
        return key
    if fallback_ok:
        return DEFAULT_SERVICE_KEY
    raise AuditKeyError("KICE_GOVERNANCE_HMAC_SECRET environment variable is missing")


def canonical_event_bytes(event: Dict[str, Any]) -> bytes:
    """Canonical JSON representation of immutable event fields for hashing."""
    keys = (
        "event_id", "item_id", "from_status", "to_status", "actor_type", "actor_id",
        "action", "reason_code", "notes", "evidence_json", "item_version", "created_at",
        "principal_id", "principal_type", "request_id", "prev_event_hash", "signature_key_id",
    )
    payload = {}
    for k in keys:
        val = event.get(k)
        if k == "evidence_json":
            if val is None:
                val = []
            elif isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    val = []
        payload[k] = val
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_event_hash(event: Dict[str, Any], prev_event_hash: str) -> str:
    evt_copy = dict(event)
    evt_copy["prev_event_hash"] = prev_event_hash
    data = canonical_event_bytes(evt_copy)
    return hashlib.sha256(data).hexdigest()


def compute_event_hmac(event_hash: str, secret_key: Optional[str] = None) -> str:
    key_str = secret_key or get_secret_key()
    key_bytes = key_str.encode("utf-8")
    msg_bytes = event_hash.encode("utf-8")
    return hmac.new(key_bytes, msg_bytes, hashlib.sha256).hexdigest()


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sign_and_chain_event(
    conn: sqlite3.Connection,
    event: Dict[str, Any],
    principal_id: str,
    principal_type: str,
    request_id: Optional[str] = None,
    secret_key: str = DEFAULT_SERVICE_KEY,
    key_id: str = DEFAULT_KEY_ID,
) -> Dict[str, Any]:
    """Attach cryptographic HMAC audit chain metadata to an event dictionary before insertion."""
    item_id = event["item_id"]
    row = conn.execute(
        """SELECT event_hash FROM teacher_review_event
           WHERE item_id = ? AND event_hash IS NOT NULL AND event_hash != ''
           ORDER BY item_version DESC, created_at DESC LIMIT 1""",
        (item_id,),
    ).fetchone()
    prev_hash = row[0] if (row and row[0]) else GENESIS_PREV_HASH

    req_id = request_id or f"REQ-{uuid.uuid4()}"
    signed_evt = dict(event)
    if "created_at" not in signed_evt or not signed_evt["created_at"]:
        signed_evt["created_at"] = _utcnow()
    signed_evt["evidence_json"] = signed_evt.get("evidence_json") or []
    signed_evt["principal_id"] = principal_id
    signed_evt["principal_type"] = principal_type
    signed_evt["request_id"] = req_id
    signed_evt["prev_event_hash"] = prev_hash
    signed_evt["signature_key_id"] = key_id

    evt_hash = compute_event_hash(signed_evt, prev_hash)
    evt_hmac = compute_event_hmac(evt_hash, secret_key)

    signed_evt["event_hash"] = evt_hash
    signed_evt["event_hmac"] = evt_hmac
    return signed_evt


def verify_audit_chain(
    conn: sqlite3.Connection,
    item_id: Optional[str] = None,
    secret_key: str = DEFAULT_SERVICE_KEY,
) -> List[Dict[str, Any]]:
    """Verify integrity of teacher_review_event records.
    Detects mutations, deletions, unsigned inserts, broken ordering, duplicate versions, and invalid HMACs.
    Returns list of violation dictionaries (empty if 100% valid)."""
    violations = []
    if item_id:
        sql = """SELECT event_id, item_id, from_status, to_status, actor_type, actor_id,
                        action, reason_code, notes, evidence_json, item_version, created_at,
                        principal_id, principal_type, request_id, prev_event_hash, event_hash,
                        signature_key_id, event_hmac
                 FROM teacher_review_event WHERE item_id = ?
                 ORDER BY item_version ASC, created_at ASC"""
        params: Tuple[Any, ...] = (item_id,)
    else:
        sql = """SELECT event_id, item_id, from_status, to_status, actor_type, actor_id,
                        action, reason_code, notes, evidence_json, item_version, created_at,
                        principal_id, principal_type, request_id, prev_event_hash, event_hash,
                        signature_key_id, event_hmac
                 FROM teacher_review_event ORDER BY item_id ASC, item_version ASC, created_at ASC"""
        params = ()

    rows = conn.execute(sql, params).fetchall()
    cols = (
        "event_id", "item_id", "from_status", "to_status", "actor_type", "actor_id",
        "action", "reason_code", "notes", "evidence_json", "item_version", "created_at",
        "principal_id", "principal_type", "request_id", "prev_event_hash", "event_hash",
        "signature_key_id", "event_hmac",
    )

    per_item_events: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        evt = dict(zip(cols, r))
        per_item_events.setdefault(evt["item_id"], []).append(evt)

    for i_id, events in per_item_events.items():
        expected_prev = GENESIS_PREV_HASH
        seen_versions = set()

        for idx, evt in enumerate(events):
            v = evt["item_version"]
            if v in seen_versions:
                violations.append({
                    "event_id": evt["event_id"],
                    "item_id": i_id,
                    "violation_type": "DUPLICATE_ITEM_VERSION",
                    "message": f"Duplicate item_version {v} detected",
                })
            seen_versions.add(v)

            # Check legacy vs signed
            key_id = evt.get("signature_key_id")
            hmac_val = evt.get("event_hmac")

            if key_id == "LEGACY" or hmac_val == "LEGACY_UNSIGNED":
                if hmac_val != "LEGACY_UNSIGNED":
                    violations.append({
                        "event_id": evt["event_id"],
                        "item_id": i_id,
                        "violation_type": "INVALID_LEGACY_LABEL",
                        "message": f"Legacy row has invalid hmac label: {hmac_val!r}",
                    })
                # Legacy rows update expected_prev if they carry a hash
                if evt.get("event_hash"):
                    expected_prev = evt["event_hash"]
                continue

            if not key_id or not hmac_val or not evt.get("event_hash"):
                violations.append({
                    "event_id": evt["event_id"],
                    "item_id": i_id,
                    "violation_type": "UNSIGNED_INSERT",
                    "message": f"Event {evt['event_id']} lacks cryptographic signature",
                })
                continue

            # Verify prev_event_hash chain
            actual_prev = evt.get("prev_event_hash")
            if actual_prev != expected_prev:
                violations.append({
                    "event_id": evt["event_id"],
                    "item_id": i_id,
                    "violation_type": "BROKEN_HASH_CHAIN",
                    "message": f"prev_event_hash mismatch: expected {expected_prev}, got {actual_prev}",
                })

            # Recompute event_hash
            recomputed_hash = compute_event_hash(evt, actual_prev or GENESIS_PREV_HASH)
            if recomputed_hash != evt["event_hash"]:
                violations.append({
                    "event_id": evt["event_id"],
                    "item_id": i_id,
                    "violation_type": "EVENT_MUTATION",
                    "message": f"event_hash mismatch: payload modified (recomputed {recomputed_hash}, stored {evt['event_hash']})",
                })

            # Recompute HMAC
            recomputed_hmac = compute_event_hmac(evt["event_hash"], secret_key)
            if recomputed_hmac != hmac_val:
                violations.append({
                    "event_id": evt["event_id"],
                    "item_id": i_id,
                    "violation_type": "INVALID_HMAC_SIGNATURE",
                    "message": f"HMAC signature invalid for key {key_id!r}",
                })

            expected_prev = evt["event_hash"]

    return violations
