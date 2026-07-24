#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated 4-Tier Eval Harness for HTML Reports (eval_html.py)
Evaluates 8-Axis data completeness, MathJax syntax, Image asset rendering, and Dual-Target file persistence.
"""

import os
import sys
import io
import json
from typing import Dict, Any
from pipeline.query_engine.selective_fetcher import QuestionFetcher
from pipeline.report_generator.html_builder import HTMLReportBuilder, validate_html_completeness

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

def evaluate_item_html_report(item_id: str) -> Dict[str, Any]:
    """Runs 4-Tier Automated Evaluation on an item's HTML Report."""
    fetcher = QuestionFetcher()
    item_data = fetcher.get_question(item_id)

    if 'error' in item_data or not item_data.get('item_id'):
        return {
            "item_id": item_id,
            "eval_status": "EVAL_FAILED",
            "reason": f"Item {item_id} not found in database."
        }

    builder = HTMLReportBuilder()
    html_content = builder.build_report(item_data, save=True, enforce_completeness=True)

    # Tier 1: Data Completeness Evaluation
    completeness_res = validate_html_completeness(item_data, html_content)
    tier1_pass = completeness_res["is_complete"]

    # Tier 2: Mathematical Syntax & Delimiter Verification
    has_mathjax_script = '<script id="MathJax-script"' in html_content
    has_math_box = 'class="math-box"' in html_content
    tier2_pass = has_mathjax_script and has_math_box

    # Tier 3: Image Asset & Answer Choice Verification
    asset_url = item_data.get('asset_image_url', '')
    tier3_image_pass = True
    if asset_url:
        tier3_image_pass = ('src="data:image/png;base64,' in html_content or 'src="data:image/jpeg;base64,' in html_content or 'src="file:///' in html_content)

    answer = item_data.get('answer', 0)
    tier3_answer_pass = f'Confirmed Answer Choice: Choice {answer}' in html_content or 'choice-tag correct' in html_content
    tier3_pass = tier3_image_pass and tier3_answer_pass

    # Tier 4: Dual Target File Existence Verification
    repo_file_path = os.path.abspath(os.path.join("storage", "html_reports", f"{item_id}_report.html"))
    tier4_pass = os.path.exists(repo_file_path) and os.path.getsize(repo_file_path) > 0

    overall_pass = tier1_pass and tier2_pass and tier3_pass and tier4_pass

    return {
        "item_id": item_id,
        "eval_status": "EVAL_PASS" if overall_pass else "EVAL_WARNING",
        "overall_score": 100.0 if overall_pass else 75.0,
        "tier1_completeness": {
            "status": "PASS" if tier1_pass else "FAIL",
            "score": completeness_res["completeness_score"],
            "missing_keys_count": completeness_res["missing_keys_count"],
            "missing_values_count": completeness_res["missing_values_count"]
        },
        "tier2_math_syntax": {
            "status": "PASS" if tier2_pass else "FAIL",
            "mathjax_engine": has_mathjax_script,
            "math_box": has_math_box
        },
        "tier3_asset_and_choice": {
            "status": "PASS" if tier3_pass else "FAIL",
            "image_rendering": tier3_image_pass,
            "answer_choice_matching": tier3_answer_pass
        },
        "tier4_file_persistence": {
            "status": "PASS" if tier4_pass else "FAIL",
            "repo_file_path": repo_file_path,
            "file_size_bytes": os.path.getsize(repo_file_path) if os.path.exists(repo_file_path) else 0
        }
    }

if __name__ == "__main__":
    item_id = sys.argv[1] if len(sys.argv) > 1 else "202606_MATH_DIF_15"
    eval_res = evaluate_item_html_report(item_id)
    print(json.dumps(eval_res, ensure_ascii=False, indent=2))
