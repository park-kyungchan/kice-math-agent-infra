import unittest
import os
import sys

# Inject base path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.query_engine.selective_fetcher import QuestionFetcher
from pipeline.report_generator.html_builder import HTMLReportBuilder, validate_html_completeness

class TestHTMLBuilder(unittest.TestCase):
    def setUp(self):
        self.fetcher = QuestionFetcher()
        self.builder = HTMLReportBuilder()

    def test_html_completeness_validation(self):
        item = self.fetcher.get_question("202606_MATH_DIF_15")
        self.assertIsNotNone(item)
        self.assertEqual(item["item_id"], "202606_MATH_DIF_15")

        html_content = self.builder.build_report(item, save=False, enforce_completeness=True)
        self.assertIn("202606_MATH_DIF_15", html_content)
        self.assertIn("15", html_content)

        # Run validate_html_completeness directly
        res = validate_html_completeness(item, html_content)
        self.assertTrue(res["is_complete"], f"Incomplete HTML: missing keys {res['missing_keys']}, values {res['missing_values']}")
        self.assertEqual(res["completeness_score"], 100.0)

if __name__ == "__main__":
    unittest.main()
