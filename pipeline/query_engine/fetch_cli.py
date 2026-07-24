#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent-Agnostic CLI Fetcher & Routing Helper (fetch_cli.py)
Prevents PowerShell string escaping, CP949 encoding errors, and multi-turn token waste.
"""
import sys
import io
import json
import argparse
import os

# Base path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from pipeline.query_engine.selective_fetcher import QuestionFetcher

# Force UTF-8 output streams on Windows PowerShell
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description="Zero-Context Agent-Agnostic CLI Fetcher")
    parser.add_argument("--item", type=str, help="Specific item_id to fetch (e.g. 202606_MATH_DIF_15)")
    parser.add_argument("--exam", type=str, help="Exam ID or pattern (e.g. 202606)")
    parser.add_argument("--number", type=int, help="Item number (e.g. 15)")
    parser.add_argument("--axes", type=str, help="Comma-separated list of axes (e.g. Axis_1,Axis_3)")
    parser.add_argument("--summary", action="store_true", help="Output short summary instead of full JSON")

    args = parser.parse_args()
    fetcher = QuestionFetcher()

    selected_axes = args.axes.split(',') if args.axes else None

    if args.item:
        item = fetcher.get_question(args.item, axes=selected_axes)
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
            items = fetcher.get_questions_batch(item_ids, axes=selected_axes)
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return

    parser.print_help()

if __name__ == "__main__":
    main()
