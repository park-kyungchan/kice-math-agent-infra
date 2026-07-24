# -*- coding: utf-8 -*-
"""
Teacher Review State Machine (v2.8.1)
=====================================
Single authority for review workflow state transitions.

Design invariants (see docs/Taxonomy_Spec.md §Review State Machine):
- ALLOWED_TRANSITIONS is the only legal transition surface. An illegal
  transition raises TransitionError and performs ZERO database writes.
- Every successful transition atomically:
    1. validates the current persisted state,
    2. appends one immutable row to `teacher_review_event` (append-only audit),
    3. updates the `question_item` snapshot (review_status, reviewer_id,
       review_version) with optimistic locking (review_version).
- `teacher_review_event` is the audit SSoT. `question_item.review_history_json`
  is DEPRECATED (retained for backward compatibility, no longer written).
- LLM/agent-agnostic: actors are data (`actor_type` in {'TEACHER','SYSTEM','AGENT'},
  free-form `actor_id`), never a vendor assumption.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# --- States ----------------------------------------------------------------

REVIEW_STATES = (
    "AUTO_ANALYSIS_COMPLETED",
    "REVIEW_REQUIRED",
    "TEACHER_ASSIGNED",
    "TEACHER_APPROVED",
    "REVISION_REQUESTED",
    "TEACHER_REVISED",
    "REJECTED",
    "VERIFIED",
)

# Persisted-workflow-state transition matrix. Quality Plane results NEVER
# mutate state directly; they enter only through sync_review_states() /
# revalidate_item(), which perform explicit transitions recorded as events.
ALLOWED_TRANSITIONS: Dict[str, set] = {
    "AUTO_ANALYSIS_COMPLETED": {"REVIEW_REQUIRED"},
    "REVIEW_REQUIRED": {"TEACHER_ASSIGNED", "REJECTED"},
    "TEACHER_ASSIGNED": {"TEACHER_APPROVED", "REVISION_REQUESTED", "REJECTED"},
    "REVISION_REQUESTED": {"TEACHER_REVISED"},
    "TEACHER_REVISED": {"REVIEW_REQUIRED"},
    "TEACHER_APPROVED": {"VERIFIED", "REVIEW_REQUIRED"},
    "REJECTED": set(),
    "VERIFIED": {"REVIEW_REQUIRED"},
}

# Queue membership is defined ONLY by persisted state.
QUEUE_STATES = ("REVIEW_REQUIRED", "TEACHER_ASSIGNED", "REVISION_REQUESTED")

ACTOR_TYPES = ("TEACHER", "SYSTEM", "AGENT")

# Per-edge actor policy (P0-1 fix, v2.8.2). An edge mapped to an EMPTY set is
# reserved for a private write path never reachable through transition():
#   - TEACHER_APPROVED -> VERIFIED / REVIEW_REQUIRED: the independent
#     Quality-Plane revalidation exit gate (see revalidate_item() /
#     _revalidation_write()). The doc table (Taxonomy_Spec.md §2b) gates BOTH
#     of TEACHER_APPROVED's outgoing edges on "independent Quality-Plane
#     revalidation" — so neither may be performed by a generic caller, even a
#     TEACHER, through the public API.
# Judgment call (flagged for owner): VERIFIED -> REVIEW_REQUIRED ("reopened on
# new evidence" per the doc table) has no current caller anywhere in the
# codebase; TEACHER-only was chosen as the conservative default since VERIFIED
# is the hardest-won state. Revisit if an automated reopening flow is added.
TRANSITION_POLICIES: Dict[Tuple[str, str], Set[str]] = {
    ("AUTO_ANALYSIS_COMPLETED", "REVIEW_REQUIRED"): {"SYSTEM"},
    ("REVIEW_REQUIRED", "TEACHER_ASSIGNED"): {"TEACHER"},
    ("REVIEW_REQUIRED", "REJECTED"): {"TEACHER"},
    ("TEACHER_ASSIGNED", "TEACHER_APPROVED"): {"TEACHER"},
    ("TEACHER_ASSIGNED", "REVISION_REQUESTED"): {"TEACHER"},
    ("TEACHER_ASSIGNED", "REJECTED"): {"TEACHER"},
    ("REVISION_REQUESTED", "TEACHER_REVISED"): {"TEACHER"},
    ("TEACHER_REVISED", "REVIEW_REQUIRED"): {"SYSTEM"},
    ("TEACHER_APPROVED", "VERIFIED"): set(),          # revalidate_item() only
    ("TEACHER_APPROVED", "REVIEW_REQUIRED"): set(),   # revalidate_item() only
    ("VERIFIED", "REVIEW_REQUIRED"): {"TEACHER"},     # manual reopen on new evidence
}

# Fail-closed coverage guard: every edge in ALLOWED_TRANSITIONS must have an
# explicit actor policy, or a future edge added there without a matching
# policy would silently fall through rather than being caught at import time.
assert all(
    (frm, to) in TRANSITION_POLICIES
    for frm, targets in ALLOWED_TRANSITIONS.items()
    for to in targets
), "TRANSITION_POLICIES is missing coverage for an ALLOWED_TRANSITIONS edge"


class ReviewStateError(Exception):
    """Base class for review workflow errors."""


class TransitionError(ReviewStateError):
    """Raised when a transition violates ALLOWED_TRANSITIONS. No DB write occurs."""


class ConcurrencyError(ReviewStateError):
    """Raised when optimistic locking detects a concurrent modification."""


class ItemNotFoundError(ReviewStateError):
    """Raised when the target item does not exist."""


# --- Schema ----------------------------------------------------------------

EVENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS teacher_review_event (
    event_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES question_item(item_id),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('TEACHER','SYSTEM','AGENT')),
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason_code TEXT,
    notes TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_json)),
    item_version INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

EVENT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_review_event_item ON teacher_review_event(item_id, created_at);"
)

# P1-1 fix: teacher_review_event is documented as the append-only audit SSoT
# (docs/SSOT_MAP.md §6) but nothing previously enforced that in the schema.
EVENT_NO_UPDATE_TRIGGER_DDL = """
CREATE TRIGGER IF NOT EXISTS teacher_review_event_no_update
BEFORE UPDATE ON teacher_review_event
BEGIN
    SELECT RAISE(ABORT, 'teacher_review_event is append-only: UPDATE forbidden');
END;
"""

EVENT_NO_DELETE_TRIGGER_DDL = """
CREATE TRIGGER IF NOT EXISTS teacher_review_event_no_delete
BEFORE DELETE ON teacher_review_event
BEGIN
    SELECT RAISE(ABORT, 'teacher_review_event is append-only: DELETE forbidden');
END;
"""


def ensure_event_schema(conn: sqlite3.Connection) -> None:
    conn.execute(EVENT_TABLE_DDL)
    conn.execute(EVENT_INDEX_DDL)
    conn.execute(EVENT_NO_UPDATE_TRIGGER_DDL)
    conn.execute(EVENT_NO_DELETE_TRIGGER_DDL)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return column in [r[1] for r in cur.fetchall()]


# --- Core transition -------------------------------------------------------

def _write_transition_in_txn(
    conn: sqlite3.Connection,
    item_id: str,
    from_status: str,
    to_status: str,
    current_version: int,
    actor_id: str,
    actor_type: str,
    action: Optional[str],
    reason_code: Optional[str],
    notes: Optional[str],
    evidence: Optional[List[Any]],
) -> Dict[str, Any]:
    """Atomic DB-write core: append one teacher_review_event row and update the
    question_item snapshot with optimistic locking. Caller owns the
    transaction (BEGIN IMMEDIATE / commit / rollback) and must have already
    validated the edge is legal. No commit happens here (P0-3: the caller
    commits exactly once, after this AND the claim-provenance linkage below
    have both been applied in the same transaction)."""
    event = {
        "event_id": str(uuid.uuid4()),
        "item_id": item_id,
        "from_status": from_status,
        "to_status": to_status,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action or to_status,
        "reason_code": reason_code,
        "notes": notes,
        "evidence_json": json.dumps(evidence or [], ensure_ascii=False),
        "item_version": current_version + 1,
        "created_at": _utcnow(),
    }
    conn.execute(
        """INSERT INTO teacher_review_event
           (event_id, item_id, from_status, to_status, actor_type, actor_id,
            action, reason_code, notes, evidence_json, item_version, created_at)
           VALUES (:event_id, :item_id, :from_status, :to_status, :actor_type,
                   :actor_id, :action, :reason_code, :notes, :evidence_json,
                   :item_version, :created_at)""",
        event,
    )

    # P1-2 fix: reviewer_id cannot be correctly expressed by a single
    # COALESCE(?, reviewer_id) prepared statement — it cannot write an
    # explicit NULL on one path while preserving the existing value on
    # another path with the SAME statement shape — so branch the SQL.
    if to_status == "REVIEW_REQUIRED":
        sql = """UPDATE question_item
                 SET review_status = ?, reviewer_id = NULL, review_version = review_version + 1
                 WHERE item_id = ? AND review_version = ?"""
        params: Tuple[Any, ...] = (to_status, item_id, current_version)
    elif actor_type == "TEACHER":
        sql = """UPDATE question_item
                 SET review_status = ?, reviewer_id = ?, review_version = review_version + 1
                 WHERE item_id = ? AND review_version = ?"""
        params = (to_status, actor_id, item_id, current_version)
    else:
        sql = """UPDATE question_item
                 SET review_status = ?, review_version = review_version + 1
                 WHERE item_id = ? AND review_version = ?"""
        params = (to_status, item_id, current_version)
    cur = conn.execute(sql, params)
    if cur.rowcount != 1:
        raise ConcurrencyError(f"Concurrent modification detected for item {item_id}")

    # P0-3 fix: fold the claim-provenance human-review linkage into the SAME
    # transaction as the event insert + snapshot update, so a failure here
    # rolls back the WHOLE transition instead of leaving a durably-committed
    # review-state change with un-linked (or wrongly-linked) provenance.
    if to_status in ("TEACHER_APPROVED", "REJECTED"):
        try:
            from pipeline.query_engine.claim_provenance import _set_human_review_in_txn
        except ImportError:
            pass
        else:
            _set_human_review_in_txn(
                conn, item_id,
                status="HUMAN_VERIFIED" if to_status == "TEACHER_APPROVED" else "HUMAN_REJECTED",
                event_id=event["event_id"],
            )
    return event


def transition(
    conn: sqlite3.Connection,
    item_id: str,
    to_status: str,
    actor_id: str,
    actor_type: str = "TEACHER",
    action: Optional[str] = None,
    reason_code: Optional[str] = None,
    notes: Optional[str] = None,
    evidence: Optional[List[Any]] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Perform one validated state transition through the PUBLIC API surface.

    Atomic: event insert + snapshot update + claim-provenance linkage happen
    in a single IMMEDIATE transaction (P0-3). On any validation failure
    nothing is written.

    P0-1: to_status='VERIFIED' can NEVER be written here — VERIFIED is only
    reachable via revalidate_item() (independent Quality-Plane revalidation).
    Every (from_status, to_status) edge additionally requires the calling
    actor_type to be permitted by TRANSITION_POLICIES; edges reserved for
    revalidate_item() are refused outright, no matter what actor_type/action
    the caller passes.

    Returns the recorded event as a dict.
    """
    if to_status not in REVIEW_STATES:
        raise TransitionError(f"Unknown target state: {to_status!r}")
    if actor_type not in ACTOR_TYPES:
        raise TransitionError(f"Unknown actor_type: {actor_type!r}")
    if not actor_id or not str(actor_id).strip():
        raise TransitionError("actor_id must be a non-empty string")
    if to_status == "VERIFIED":
        raise TransitionError(
            "transition() cannot write to_status='VERIFIED' directly. "
            "VERIFIED is only reachable via revalidate_item() (independent "
            "Quality-Plane revalidation exit gate)."
        )
    if not _has_column(conn, "question_item", "review_version"):
        raise ReviewStateError(
            "Schema not migrated: question_item.review_version missing. "
            "Run pipeline/migrate_db_v2_8_1.py first."
        )
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
                f"Allowed: {sorted(ALLOWED_TRANSITIONS[from_status]) or 'none (terminal state)'}"
            )
        if expected_version is not None and expected_version != current_version:
            raise ConcurrencyError(
                f"Item {item_id} version mismatch: expected {expected_version}, "
                f"actual {current_version}"
            )

        # P0-1: per-edge actor policy, enforced with ZERO writes so far.
        policy = TRANSITION_POLICIES.get((from_status, to_status))
        if not policy:
            raise TransitionError(
                f"{from_status} -> {to_status} is reserved for the independent "
                "Quality-Plane revalidation exit gate; call revalidate_item() "
                "instead of transition()."
            )
        if actor_type not in policy:
            raise TransitionError(
                f"actor_type {actor_type!r} may not perform {from_status} -> {to_status} "
                f"(allowed: {sorted(policy)})"
            )

        event = _write_transition_in_txn(
            conn, item_id, from_status, to_status, current_version,
            actor_id, actor_type, action, reason_code, notes, evidence,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return event


# --- Queries ---------------------------------------------------------------

def get_review_queue(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Queue = persisted workflow states only (P0-2 fix)."""
    placeholders = ",".join("?" for _ in QUEUE_STATES)
    rows = conn.execute(
        f"""SELECT item_id, review_status, reviewer_id, review_version
            FROM question_item
            WHERE review_status IN ({placeholders})
            ORDER BY item_id""",
        QUEUE_STATES,
    ).fetchall()
    return [
        {
            "item_id": r[0],
            "review_status": r[1],
            "reviewer_id": r[2],
            "review_version": r[3],
        }
        for r in rows
    ]


def get_item_events(conn: sqlite3.Connection, item_id: str) -> List[Dict[str, Any]]:
    ensure_event_schema(conn)
    rows = conn.execute(
        """SELECT event_id, item_id, from_status, to_status, actor_type, actor_id,
                  action, reason_code, notes, evidence_json, item_version, created_at
           FROM teacher_review_event WHERE item_id = ?
           ORDER BY item_version ASC, created_at ASC""",
        (item_id,),
    ).fetchall()
    cols = (
        "event_id", "item_id", "from_status", "to_status", "actor_type", "actor_id",
        "action", "reason_code", "notes", "evidence_json", "item_version", "created_at",
    )
    return [dict(zip(cols, r)) for r in rows]


def get_status_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT review_status, COUNT(*) FROM question_item GROUP BY review_status"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# --- Quality-Plane -> state synchronization (computed state enters here) ---

def sync_review_states(fetcher, actor_id: str = "quality-plane-sync") -> Dict[str, Any]:
    """Persist Quality-Plane/heuristic 'unverified' findings as explicit
    AUTO_ANALYSIS_COMPLETED -> REVIEW_REQUIRED transitions, and requeue
    TEACHER_REVISED items for re-review. This is the ONLY bridge between
    computed semantic state and persisted workflow state.
    """
    from pipeline.query_engine.selective_fetcher import _is_item_unverified

    moved: List[str] = []
    requeued: List[str] = []
    with fetcher.get_connection() as conn:
        ensure_event_schema(conn)
        auto_ids = [
            r[0]
            for r in conn.execute(
                "SELECT item_id FROM question_item WHERE review_status = 'AUTO_ANALYSIS_COMPLETED'"
            ).fetchall()
        ]
        revised_ids = [
            r[0]
            for r in conn.execute(
                "SELECT item_id FROM question_item WHERE review_status = 'TEACHER_REVISED'"
            ).fetchall()
        ]

    for item_id in auto_ids:
        item = fetcher.get_question(item_id)
        if "error" in item:
            continue
        if _is_item_unverified(item):
            with fetcher.get_connection() as conn:
                transition(
                    conn, item_id, "REVIEW_REQUIRED",
                    actor_id=actor_id, actor_type="SYSTEM", action="AUTO_SYNC",
                    reason_code="QUALITY_PLANE_UNRESOLVED",
                )
            moved.append(item_id)

    for item_id in revised_ids:
        with fetcher.get_connection() as conn:
            transition(
                conn, item_id, "REVIEW_REQUIRED",
                actor_id=actor_id, actor_type="SYSTEM", action="AUTO_REQUEUE",
                reason_code="REVISED_AWAITING_REREVIEW",
            )
        requeued.append(item_id)

    return {
        "scanned": len(auto_ids) + len(revised_ids),
        "moved_to_review_required": moved,
        "requeued_after_revision": requeued,
    }


def _revalidation_write(
    fetcher, item_id: str, to_status: str, actor_id: str,
    reason_code: str, evidence: List[Any],
) -> Dict[str, Any]:
    """Private write path used ONLY by revalidate_item() (P0-1). Writes the
    TEACHER_APPROVED -> VERIFIED / REVIEW_REQUIRED exit-gate edge, which is
    UNREACHABLE through the public transition() API no matter what
    actor_type/action a caller passes. actor_type is hardcoded to 'SYSTEM'
    here — it is never taken from an external caller."""
    if to_status not in ("VERIFIED", "REVIEW_REQUIRED"):
        raise ReviewStateError(f"_revalidation_write: unsupported to_status {to_status!r}")
    with fetcher.get_connection() as conn:
        if not _has_column(conn, "question_item", "review_version"):
            raise ReviewStateError(
                "Schema not migrated: question_item.review_version missing. "
                "Run pipeline/migrate_db_v2_8_1.py first."
            )
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
            if from_status != "TEACHER_APPROVED":
                raise TransitionError(
                    f"revalidate_item() requires item {item_id} to be in "
                    f"TEACHER_APPROVED, found {from_status!r}"
                )
            if to_status not in ALLOWED_TRANSITIONS[from_status]:
                raise TransitionError(f"Illegal transition {from_status} -> {to_status}")
            event = _write_transition_in_txn(
                conn, item_id, from_status, to_status, current_version,
                actor_id, "SYSTEM", "REVALIDATE", reason_code, None, evidence,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return event


def revalidate_item(fetcher, item_id: str, actor_id: str = "independent-revalidator") -> Dict[str, Any]:
    """TEACHER_APPROVED -> VERIFIED only if an independent Quality-Plane pass
    is green; otherwise TEACHER_APPROVED -> REVIEW_REQUIRED. Exit gate of the
    review loop (P0-1/P0-2/P0-3 fix). This is the ONLY code path that can ever
    write VERIFIED, or move an item out of TEACHER_APPROVED — see
    _revalidation_write()."""
    fetcher.clear_cache()
    qp = fetcher.evaluate_quality_plane(item_id)
    green = (not qp.is_vetoed) and qp.status == "VERIFIED"
    to_status = "VERIFIED" if green else "REVIEW_REQUIRED"
    event = _revalidation_write(
        fetcher, item_id, to_status, actor_id,
        reason_code="QUALITY_PLANE_GREEN" if green else "QUALITY_PLANE_UNRESOLVED",
        evidence=[{"quality_plane_status": qp.status, "is_vetoed": qp.is_vetoed}],
    )
    return {"item_id": item_id, "revalidation_green": green, "event": event}
