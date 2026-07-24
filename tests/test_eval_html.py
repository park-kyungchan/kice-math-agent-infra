#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated Unit Test Suite for 4-Tier HTML Report Eval Harness (test_eval_html.py)
"""

import unittest
import os
import sys
import json
import subprocess

# Inject base path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.report_generator.eval_html import evaluate_item_html_report

class TestEvalHTML(unittest.TestCase):
    def setUp(self):
        self.item_id = "202606_MATH_DIF_15"

    def test_evaluate_item_html_report_success(self):
        eval_res = evaluate_item_html_report(self.item_id)
        self.assertEqual(eval_res["item_id"], self.item_id)
        self.assertEqual(eval_res["eval_status"], "EVAL_PASS")
        self.assertEqual(eval_res["overall_score"], 100.0)

        # Assert all 4 tiers
        self.assertEqual(eval_res["tier1_completeness"]["status"], "PASS")
        self.assertEqual(eval_res["tier1_completeness"]["score"], 100.0)
        self.assertEqual(eval_res["tier2_math_syntax"]["status"], "PASS")
        self.assertTrue(eval_res["tier2_math_syntax"]["mathjax_engine"])
        self.assertEqual(eval_res["tier3_asset_and_choice"]["status"], "PASS")
        self.assertTrue(eval_res["tier3_asset_and_choice"]["answer_choice_matching"])
        self.assertEqual(eval_res["tier4_file_persistence"]["status"], "PASS")

    def test_evaluate_nonexistent_item(self):
        eval_res = evaluate_item_html_report("NONEXISTENT_ITEM_9999")
        self.assertEqual(eval_res["eval_status"], "EVAL_FAILED")

    def test_cli_eval_flag(self):
        cmd = [sys.executable, "pipeline/query_engine/fetch_cli.py", "--item", self.item_id, "--eval"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["item_id"], self.item_id)
        self.assertEqual(data["eval_status"], "EVAL_PASS")
        self.assertEqual(data["overall_score"], 100.0)

if __name__ == "__main__":
    unittest.main()
