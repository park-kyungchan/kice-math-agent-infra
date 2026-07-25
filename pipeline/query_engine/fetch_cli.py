#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent-Agnostic CLI Fetcher & Teacher Review Governance CLI (fetch_cli.py)
Prevents PowerShell string escaping, CP949 encoding errors, and multi-turn token waste.

Review workflow commands go through the review state machine
(pipeline/query_engine/review_state.py). Illegal transitions perform ZERO
database writes and exit non-zero.

Exit codes:
  0 success | 1 unexpected error | 2 usage error
  3 illegal state transition / concurrency conflict | 4 item not found
"""
import sys
import io
import json
import argparse
import os

# Base path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from pipeline.query_engine.selective_fetcher import QuestionFetcher
from pipeline.query_engine import review_state
from pipeline.query_engine.review_state import TransitionError, ConcurrencyError, ItemNotFoundError
from pipeline.governance_service.service_api import GovernanceService, GovernanceServiceError
from pipeline.governance_service.audit_signer import verify_audit_chain

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_TRANSITION = 3
EXIT_NOT_FOUND = 4


def fail(message: str, code: int) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def require(args, names) -> None:
    missing = [n for n in names if not getattr(args, n.replace('-', '_'), None)]
    if missing:
        fail(f"missing required argument(s): {', '.join('--' + n for n in missing)}", EXIT_USAGE)


def do_service_transition(service, method_name, args, notes_required=False):
    require(args, ['item', 'reviewer'])
    if notes_required:
        require(args, ['notes'])
    principal = {"principal_id": args.reviewer, "principal_type": "TEACHER"}
    method = getattr(service, method_name)
    try:
        if method_name in ('request_revision', 'record_revision'):
            event = method(args.item, principal, notes=args.notes, expected_version=args.expected_version)
        elif method_name == 'reject_item':
            event = method(args.item, principal, reason_code=args.reason, notes=args.notes, expected_version=args.expected_version)
        elif method_name == 'approve_item':
            event = method(args.item, principal, notes=args.notes, expected_version=args.expected_version)
        else:
            event = method(args.item, principal, expected_version=args.expected_version)
        print(json.dumps(event, ensure_ascii=False, indent=2))
        sys.exit(EXIT_OK)
    except ItemNotFoundError as e:
        fail(str(e), EXIT_NOT_FOUND)
    except (TransitionError, ConcurrencyError, GovernanceServiceError) as e:
        fail(str(e), EXIT_TRANSITION)


def main():
    parser = argparse.ArgumentParser(description="Zero-Context Agent-Agnostic CLI Fetcher & Review Governance")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite DB (default: storage/parsed_dataset.db)")
    parser.add_argument("--item", type=str, help="Specific item_id to fetch (e.g. 202606_MATH_DIF_15)")
    parser.add_argument("--exam", type=str, help="Exam ID or pattern (e.g. 202606)")
    parser.add_argument("--number", type=int, help="Item number (e.g. 15)")
    parser.add_argument("--axes", type=str, help="Comma-separated list of axes (e.g. Axis_1,Axis_3)")
    parser.add_argument("--layer", type=str, help="Layer name (data_infrastructure, item_reasoning, corpus_lineage)")
    parser.add_argument("--lineage", action="store_true", help="Display full precedent genealogy chain for a given item")
    parser.add_argument("--unverified", action="store_true", help="[Computed] Items failing axis heuristics / Quality Plane (diagnostic view; NOT the review queue)")
    parser.add_argument("--summary", action="store_true", help="Output short summary instead of full JSON")
    parser.add_argument("--html", action="store_true", help="Generate 100% complete HTML report artifact")
    parser.add_argument("--eval", action="store_true", help="Run 4-Tier Automated Eval Harness on HTML report")
    # --- Review governance (persisted state machine & Governance Service) ---
    parser.add_argument("--review-queue", action="store_true", help="[Persisted] Items in REVIEW_REQUIRED / TEACHER_ASSIGNED / REVISION_REQUESTED")
    parser.add_argument("--review-proof-queue", action="store_true", help="[Persisted] Items in SEMANTIC_PROOF_PENDING waiting for solver proof")
    parser.add_argument("--review-sync", action="store_true", help="Persist Quality-Plane findings: AUTO_ANALYSIS_COMPLETED->REVIEW_REQUIRED; requeue TEACHER_REVISED")
    parser.add_argument("--review-assign", action="store_true", help="REVIEW_REQUIRED -> TEACHER_ASSIGNED (requires --item --reviewer)")
    parser.add_argument("--review-approve", action="store_true", help="TEACHER_ASSIGNED -> TEACHER_APPROVED (requires --item --reviewer)")
    parser.add_argument("--review-request-revision", action="store_true", help="TEACHER_ASSIGNED -> REVISION_REQUESTED (requires --item --reviewer --notes)")
    parser.add_argument("--review-revise", action="store_true", help="REVISION_REQUESTED -> TEACHER_REVISED after revision applied (requires --item --reviewer --notes)")
    parser.add_argument("--review-reject", action="store_true", help="REVIEW_REQUIRED/TEACHER_ASSIGNED -> REJECTED (requires --item --reviewer)")
    parser.add_argument("--review-verify", action="store_true", help="TEACHER_APPROVED -> VERIFIED via independent Quality-Plane revalidation (requires --item)")
    parser.add_argument("--verify-audit-chain", action="store_true", help="Verify HMAC audit chain integrity for teacher_review_event records")
    parser.add_argument("--review-status", action="store_true", help="State counts; with --item also prints the item's full event history")
    parser.add_argument("--reviewer", type=str, help="Reviewer ID for review actions")
    parser.add_argument("--notes", type=str, help="Notes for review actions")
    parser.add_argument("--reason", type=str, help="Reason code for review actions (e.g. MATHEMATICALLY_VALID)")
    parser.add_argument("--expected-version", type=int, default=None, help="Optimistic-locking guard: fail if item version differs")

    args = parser.parse_args()
    fetcher = QuestionFetcher(db_path=args.db)
    service = GovernanceService(fetcher)

    selected_axes = args.axes.split(',') if args.axes else None

    if args.verify_audit_chain:
        with fetcher.get_connection() as conn:
            violations = verify_audit_chain(conn, args.item)
        if violations:
            print(json.dumps({"status": "AUDIT_CHAIN_VIOLATION", "violations": violations}, ensure_ascii=False, indent=2))
            sys.exit(EXIT_TRANSITION)
        print(json.dumps({"status": "AUDIT_CHAIN_VALID", "item_id": args.item}, ensure_ascii=False, indent=2))
        sys.exit(EXIT_OK)

    if args.unverified:
        unverified_items = fetcher.get_unverified_questions()
        if args.summary:
            summary_list = [
                {
                    "item_id": item.get("item_id"),
                    "exam_id": item.get("exam_id"),
                    "track": item.get("track"),
                    "item_number": item.get("item_number"),
                    "score": item.get("score"),
                    "axes_present": list(item.get("axes", {}).keys())
                }
                for item in unverified_items
            ]
            print(json.dumps(summary_list, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(unverified_items, ensure_ascii=False, indent=2))
        return

    if args.review_queue:
        with fetcher.get_connection() as conn:
            queue = review_state.get_review_queue(conn)
        print(json.dumps(queue, ensure_ascii=False, indent=2))
        return

    if args.review_proof_queue:
        with fetcher.get_connection() as conn:
            queue = review_state.get_proof_queue(conn)
        print(json.dumps(queue, ensure_ascii=False, indent=2))
        return

    if args.review_sync:
        result = review_state.sync_review_states(fetcher)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.review_assign:
        do_service_transition(service, "assign_item", args)

    if args.review_approve:
        do_service_transition(service, "approve_item", args)

    if args.review_request_revision:
        do_service_transition(service, "request_revision", args, notes_required=True)

    if args.review_revise:
        do_service_transition(service, "record_revision", args, notes_required=True)

    if args.review_reject:
        do_service_transition(service, "reject_item", args)

    if args.review_verify:
        require(args, ['item'])
        principal = {"principal_id": args.reviewer or "independent-revalidator", "principal_type": "SYSTEM"}
        try:
            result = service.revalidate_item(args.item, principal, expected_version=args.expected_version)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(EXIT_OK)
        except ItemNotFoundError as e:
            fail(str(e), EXIT_NOT_FOUND)
        except (TransitionError, ConcurrencyError, GovernanceServiceError) as e:
            fail(str(e), EXIT_TRANSITION)

    if args.review_status:
        with fetcher.get_connection() as conn:
            payload = {"state_counts": review_state.get_status_counts(conn)}
            if args.item:
                payload["item_id"] = args.item
                payload["events"] = review_state.get_item_events(conn, args.item)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.item:
        if args.lineage:
            lineage_data = fetcher.get_question_lineage(args.item)
            print(json.dumps(lineage_data, ensure_ascii=False, indent=2))
            return

        item = fetcher.get_question(args.item, layer=args.layer, axes=selected_axes)

        if args.eval:
            from pipeline.report_generator.eval_html import evaluate_item_html_report
            eval_res = evaluate_item_html_report(args.item)
            print(json.dumps(eval_res, ensure_ascii=False, indent=2))
            return

        if args.html:
            from pipeline.report_generator.html_builder import HTMLReportBuilder
            builder = HTMLReportBuilder()
            builder.build_report(item, save=True, enforce_completeness=True)
            report_path = os.path.abspath(os.path.join("storage", "html_reports", f"{args.item}_report.html"))
            # Backslash handled outside the f-string for Python < 3.12 compatibility (PEP 701).
            report_posix = report_path.replace("\\", "/")
            print(json.dumps({
                "item_id": args.item,
                "status": "HTML_REPORT_GENERATED",
                "html_report_path": report_path,
                "file_uri": f"file:///{report_posix}"
            }, ensure_ascii=False, indent=2))
            return

        if args.summary:
            print(json.dumps({
                "item_id": item.get("item_id"),
                "exam_id": item.get("exam_id"),
                "track": item.get("track"),
                "item_number": item.get("item_number"),
                "score": item.get("score"),
                "answer": item.get("answer"),
                "axes_present": list(item.get("axes", {}).keys())
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        return

    if args.exam and args.number:
        with fetcher.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT item_id FROM question_item WHERE (exam_id LIKE ? OR item_id LIKE ?) AND item_number=?",
                (f"%{args.exam}%", f"%{args.exam}%", args.number)
            )
            rows = cur.fetchall()
            item_ids = [r[0] for r in rows]

            if args.lineage:
                lineage_results = [fetcher.get_question_lineage(i_id) for i_id in item_ids]
                print(json.dumps(lineage_results, ensure_ascii=False, indent=2))
                return

            items = fetcher.get_questions_batch(item_ids, layer=args.layer, axes=selected_axes)
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return

    parser.print_help()


if __name__ == "__main__":
    main()
