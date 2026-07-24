import os
import time
import unittest
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.selective_fetcher import QuestionFetcher

class TestSelectiveFetcher(unittest.TestCase):
    def setUp(self):
        self.fetcher = QuestionFetcher()

    def test_single_question_fetch(self):
        res = self.fetcher.get_question('202411_MATH_DIF_22')
        self.assertEqual(res['item_id'], '202411_MATH_DIF_22')
        self.assertEqual(res['score'], 4)
        self.assertIn('axes', res)

    def test_selective_axes_filter(self):
        res = self.fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_2'])
        self.assertIn('Axis_1', res['axes'])
        self.assertIn('Axis_2', res['axes'])
        self.assertNotIn('Axis_8', res['axes'])

    def test_batch_query_and_latency_under_10ms(self):
        item_ids = [
            '202411_MATH_DIF_22', '202506_MATH_DIF_22', '202106_MATH_DIF_21',
            '202311_MATH_DIF_15', '202211_MATH_DIF_22', '202106_MATH_DIF_22'
        ]
        
        # Warm-up / cache load
        _ = self.fetcher.get_questions_batch(item_ids)

        # Measure cached batch fetch latency
        t0 = time.perf_counter()
        results = self.fetcher.get_questions_batch(item_ids)
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000.0
        self.assertEqual(len(results), len(item_ids))
        print(f"\n[SLA Test] Batch Fetch Latency for {len(item_ids)} items: {elapsed_ms:.3f} ms")
        self.assertLess(elapsed_ms, 10.0, f"Batch query latency exceeded SLA (10ms): {elapsed_ms:.3f} ms")

    def test_non_existent_item_graceful(self):
        res = self.fetcher.get_question('NON_EXISTENT_ID_999')
        self.assertIn('error', res)
        self.assertEqual(res['item_id'], 'NON_EXISTENT_ID_999')

if __name__ == '__main__':
    unittest.main()
