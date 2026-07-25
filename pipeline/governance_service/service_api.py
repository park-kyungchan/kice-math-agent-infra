# -*- coding: utf-8 -*-
"""
Governance Service API (v2.8.4)
===============================
Authoritative service boundary for review state mutations, permission verification,
Quality Plane revalidation, and cryptographic audit event creation.
"""
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from pipeline.query_engine.review_state import (
    ALLOWED_TRANSITIONS, ACTOR_TYPES, REVIEW_STATES, TRANSITION_POLICIES,
    ConcurrencyError, ItemNotFoundError, ReviewStateError, TransitionError,
    _has_column, ensure_event_schema, _write_transition_in_txn
)
from pipeline.governance_service.audit_signer import sign_and_chain_event, DEFAULT_SERVICE_KEY


class GovernanceServiceError(Exception):
    pass


class GovernanceService:
    def __init__(self, fetcher, hmac_key: str = DEFAULT_SERVICE_KEY):
        self.fetcher = fetcher
        self.hmac_key = hmac_key

    def _get_connection(self) -> sqlite3.Connection:
        return self.fetcher.get_connection()

    def _validate_principal(self, principal: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(principal, dict):
            raise GovernanceServiceError("Principal context must be a dictionary")
        p_id = principal.get("principal_id")
        p_type = principal.get("principal_type")
        if not p_id or not isinstance(p_id, str) or not p_id.strip():
            raise GovernanceServiceError("principal_id must be a non-empty string")
        if p_type not in ACTOR_TYPES:
            raise GovernanceServiceError(f"principal_type must be one of {ACTOR_TYPES}, got {p_type!r}")
        return p_id, p_type

    def _execute_service_transition(
        self,
        conn: sqlite3.Connection,
        item_id: str,
        to_status: str,
        principal: Dict[str, Any],
        action: str,
        reason_code: Optional[str] = None,
        notes: Optional[str] = None,
        evidence: Optional[List[Any]] = None,
        expected_version: Optional[int] = None,
        request_id: Optional[str] = None,
        skip_actor_policy: bool = False,
    ) -> Dict[str, Any]:
        p_id, p_type = self._validate_principal(principal)

        if to_status not in REVIEW_STATES:
            raise TransitionError(f"Unknown target state: {to_status!r}")

        if not _has_column(conn, "question_item", "review_version"):
            raise ReviewStateError("Schema not migrated: question_item.review_version missing.")
        ensure_event_schema(conn)

        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT review_status, review_version FROM question_item WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ItemNotFoundError(f"Item {item_id} not found")
            from_status, current_version = row[0], row[1]

            if from_status not in ALLOWED_TRANSITIONS:
                raise TransitionError(f"Item {item_id} is in unknown state {from_status!r}")
            if to_status not in ALLOWED_TRANSITIONS[from_status]:
                raise TransitionError(
                    f"Illegal transition {from_status} -> {to_status} for item {item_id}. "
                    f"Allowed: {sorted(ALLOWED_TRANSITIONS[from_status]) or 'none'}"
                )
            if expected_version is not None and expected_version != current_version:
                raise ConcurrencyError(
                    f"Item {item_id} version mismatch: expected {expected_version}, actual {current_version}"
                )

            # Check per-edge actor policy using authenticated principal_type
            policy = TRANSITION_POLICIES.get((from_status, to_status))
            if not skip_actor_policy:
                if policy is None or not policy:
                    raise TransitionError(
                        f"{from_status} -> {to_status} is reserved for the independent Quality-Plane revalidation exit gate."
                    )
                if p_type not in policy:
                    raise TransitionError(
                        f"principal_type {p_type!r} may not perform {from_status} -> {to_status} (allowed: {sorted(policy)})"
                    )

            # Build raw event
            event = {
                "event_id": f"EVT-{item_id}-v{current_version + 1}",
                "item_id": item_id,
                "from_status": from_status,
                "to_status": to_status,
                "actor_type": p_type,
                "actor_id": p_id,  # Authenticated principal identity, NOT caller payload override
                "action": action,
                "reason_code": reason_code,
                "notes": notes,
                "evidence_json": evidence,
                "item_version": current_version + 1,
            }

            # Cryptographically sign and chain the event
            signed_event = sign_and_chain_event(
                conn, event, principal_id=p_id, principal_type=p_type,
                request_id=request_id, secret_key=self.hmac_key,
            )

            # Perform DB writes: update question_item, insert signed event, link claim_provenance
            sql_item = """UPDATE question_item
                          SET review_status = ?, reviewer_id = ?, review_version = review_version + 1
                          WHERE item_id = ? AND review_version = ?"""
            cur = conn.execute(sql_item, (to_status, p_id if p_type == "TEACHER" else None, item_id, current_version))
            if cur.rowcount != 1:
                raise ConcurrencyError(f"Concurrent modification detected for item {item_id}")

            # Insert signed event into teacher_review_event
            import json as _json
            conn.execute(
                """INSERT INTO teacher_review_event
                   (event_id, item_id, from_status, to_status, actor_type, actor_id,
                    action, reason_code, notes, evidence_json, item_version, created_at,
                    principal_id, principal_type, request_id, prev_event_hash, event_hash,
                    signature_key_id, event_hmac)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signed_event["event_id"], signed_event["item_id"], signed_event["from_status"],
                    signed_event["to_status"], signed_event["actor_type"], signed_event["actor_id"],
                    signed_event["action"], signed_event["reason_code"], signed_event["notes"],
                    _json.dumps(signed_event["evidence_json"] or []), signed_event["item_version"],
                    signed_event["created_at"],
                    signed_event["principal_id"], signed_event["principal_type"],
                    signed_event["request_id"], signed_event["prev_event_hash"],
                    signed_event["event_hash"], signed_event["signature_key_id"],
                    signed_event["event_hmac"],
                ),
            )

            if to_status in ("TEACHER_APPROVED", "REJECTED"):
                from pipeline.query_engine.claim_provenance import _set_human_review_in_txn
                _set_human_review_in_txn(
                    conn, item_id,
                    status="HUMAN_VERIFIED" if to_status == "TEACHER_APPROVED" else "HUMAN_REJECTED",
                    event_id=signed_event["event_id"],
                )

            conn.commit()
            return signed_event
        except Exception:
            conn.rollback()
            raise

    # --- Intent-based Public Service API Methods ---

    def assign_item(self, item_id: str, principal: Dict[str, Any], expected_version: Optional[int] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            return self._execute_service_transition(
                conn, item_id, "TEACHER_ASSIGNED", principal, "ASSIGN", expected_version=expected_version
            )

    def approve_item(self, item_id: str, principal: Dict[str, Any], expected_version: Optional[int] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            return self._execute_service_transition(
                conn, item_id, "TEACHER_APPROVED", principal, "APPROVE", notes=notes, expected_version=expected_version
            )

    def request_revision(self, item_id: str, principal: Dict[str, Any], notes: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            return self._execute_service_transition(
                conn, item_id, "REVISION_REQUESTED", principal, "REQUEST_REVISION", notes=notes, expected_version=expected_version
            )

    def record_revision(self, item_id: str, principal: Dict[str, Any], notes: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            return self._execute_service_transition(
                conn, item_id, "TEACHER_REVISED", principal, "REVISE", notes=notes, expected_version=expected_version
            )

    def reject_item(self, item_id: str, principal: Dict[str, Any], reason_code: Optional[str] = None, notes: Optional[str] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            return self._execute_service_transition(
                conn, item_id, "REJECTED", principal, "REJECT", reason_code=reason_code, notes=notes, expected_version=expected_version
            )

    def revalidate_item(self, item_id: str, principal: Dict[str, Any], expected_version: Optional[int] = None) -> Dict[str, Any]:
        """Reevaluate Quality Plane independently and apply 7-point gate pre-conditions.
        Does NOT accept to_status, quality_plane_status, or reason_code from caller."""
        self.fetcher.clear_cache()
        qp = self.fetcher.evaluate_quality_plane(item_id)

        solver_res = qp.judge_results.get("IndependentSolverJudge")
        solver_pass = solver_res and solver_res.execution_status == "PASS"
        conf_pass = qp.overall_confidence >= 0.90 and not qp.is_vetoed

        with self._get_connection() as conn:
            from pipeline.governance_service.audit_signer import verify_audit_chain
            audit_violations = verify_audit_chain(conn, item_id)
        audit_pass = len(audit_violations) == 0

        if solver_pass and conf_pass and audit_pass:
            to_status = "VERIFIED"
            reason_code = "GOVERNANCE_GATE_APPROVED"
            green = True
        elif not solver_pass:
            to_status = "SEMANTIC_PROOF_PENDING"
            reason_code = "SEMANTIC_PROOF_PENDING"
            green = False
        else:
            to_status = "REVIEW_REQUIRED"
            reason_code = "GOVERNANCE_GATE_FAILED"
            green = False

        evidence = [
            {
                "quality_plane_status": qp.status,
                "is_vetoed": qp.is_vetoed,
                "overall_confidence": qp.overall_confidence,
                "audit_chain_valid": audit_pass,
                "solver_passed": solver_pass,
            }
        ]

        system_principal = {"principal_id": principal.get("principal_id", "independent-revalidator"), "principal_type": "SYSTEM"}

        with self._get_connection() as conn:
            event = self._execute_service_transition(
                conn, item_id, to_status, system_principal, "REVALIDATE",
                reason_code=reason_code, evidence=evidence, expected_version=expected_version,
                skip_actor_policy=True,
            )
        return {"item_id": item_id, "revalidation_green": green, "event": event}

    def reopen_item(self, item_id: str, principal: Dict[str, Any], reason_code: str, evidence_refs: Optional[List[Any]] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            return self._execute_service_transition(
                conn, item_id, "REVIEW_REQUIRED", principal, "REOPEN",
                reason_code=reason_code, evidence=evidence_refs, expected_version=expected_version
            )
