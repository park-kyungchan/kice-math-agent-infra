#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated Unit Test Suite for Deterministic Condition Parser (test_condition_parser.py)
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.report_generator.condition_parser import parse_item_conditions_deterministic

class TestConditionParser(unittest.TestCase):
    def test_parse_item_conditions(self):
        sample_text = (
            "15. 삼차함수 f(x)가 다음 조건을 만족시킨다.\n"
            "(가) int_{p}^{p+3} |f(x)| dx != |int f| (0 < p < 3)\n"
            "(나) int_{0}^{3} |f(x)+q| dx != |int (f+q)| (0 < q < 1)\n"
            "f(6)의 값은? [4점]\n"
            "[CHOICE_1] 18\n[CHOICE_2] 21\n[CHOICE_3] 24\n[CHOICE_4] 27\n[CHOICE_5] 30"
        )
        parsed = parse_item_conditions_deterministic(sample_text)
        
        self.assertIn("삼차함수", parsed["intro"])
        self.assertEqual(len(parsed["conditions"]), 2)
        self.assertEqual(parsed["conditions"][0]["label"], "(가)")
        self.assertEqual(parsed["conditions"][1]["label"], "(나)")
        self.assertIn("f(6)", parsed["target_expr"])
        self.assertEqual(len(parsed["choices"]), 5)
        self.assertEqual(parsed["choices"][3]["value"], "27")

if __name__ == "__main__":
    unittest.main()
