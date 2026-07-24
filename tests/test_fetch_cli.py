import unittest
import subprocess
import json
import sys

class TestFetchCLI(unittest.TestCase):
    def test_cli_item_summary(self):
        cmd = [sys.executable, "pipeline/query_engine/fetch_cli.py", "--item", "202606_MATH_DIF_15", "--summary"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["item_id"], "202606_MATH_DIF_15")
        self.assertEqual(data["item_number"], 15)

    def test_cli_exam_and_number(self):
        cmd = [sys.executable, "pipeline/query_engine/fetch_cli.py", "--exam", "202606", "--number", "15"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(res.returncode, 0)
        items = json.loads(res.stdout)
        self.assertGreaterEqual(len(items), 1)
    def test_cli_layer(self):
        cmd = [sys.executable, "pipeline/query_engine/fetch_cli.py", "--item", "202606_MATH_DIF_15", "--layer", "item_reasoning"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["item_id"], "202606_MATH_DIF_15")
        for k in data["axes"].keys():
            self.assertIn(k, ["Axis_3", "Axis_4", "Axis_5"])
        self.assertNotIn("Axis_1", data["axes"])

    def test_cli_lineage(self):
        cmd = [sys.executable, "pipeline/query_engine/fetch_cli.py", "--item", "202606_MATH_DIF_15", "--lineage"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["item_id"], "202606_MATH_DIF_15")
        self.assertIn("precedents", data)

    def test_cli_unverified(self):
        cmd = [sys.executable, "pipeline/query_engine/fetch_cli.py", "--unverified", "--summary"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIsInstance(data, list)

if __name__ == "__main__":
    unittest.main()
