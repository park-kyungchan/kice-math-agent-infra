# -*- coding: utf-8 -*-
"""Tests for pipeline/query_engine/ce_relatedness.py."""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine import conclusion_form as cf       # noqa: E402
from pipeline.query_engine import ce_relatedness as rel       # noqa: E402

CUBIC = {'family': 'POLYNOMIAL', 'degree': 3, 'fixed_coefficients': {'c0': 0}}

ITEM15 = [
    cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0),
                                'MULT': ('GROUND', 2)}, CUBIC, node_id='N1'),
    cf.Conclusion('EXTREMUM_VALUE', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 2),
                                     'VALUE': ('GROUND', -1),
                                     'KIND': ('GROUND', 'LOCAL_MIN')}, CUBIC, node_id='N4'),
]
ITEM2021 = [
    cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('EXISTENTIAL', 'R'),
                                'MULT': ('GROUND', 2)}, CUBIC, node_id='P1'),
]
ITEM2025 = [
    cf.Conclusion('AREA_TRIANGLE', {'P1': ('GROUND', 'A'), 'P2': ('GROUND', 'O'),
                                    'P3': ('GROUND', 'B'), 'VALUE': ('GROUND', 16)},
                  {}, node_id='Q1'),
]


class TestRelatedness(unittest.TestCase):
    def test_a_shared_conclusion_creates_an_edge_across_different_surfaces(self):
        out = rel.relate('202606_MATH_DIF_15', ITEM15, '202106_MATH_DIF_22', ITEM2021)
        self.assertEqual(out['verdict'], 'RELATED')
        self.assertTrue(out['edges'])
        self.assertEqual(out['edges'][0]['verdict'], 'IMPLIES')

    def test_no_shared_conclusion_means_not_related(self):
        out = rel.relate('202606_MATH_DIF_15', ITEM15, '202506_MATH_DIF_22', ITEM2025)
        self.assertEqual(out['verdict'], 'NOT_RELATED')

    def test_every_result_carries_the_coverage_caveat(self):
        """An absent edge is not evidence of unrelatedness while most of the corpus is
        unanalysed, and the caveat must travel with the result rather than live in a doc."""
        out = rel.relate('a', ITEM15, 'b', ITEM2025)
        self.assertIn('map of analysis effort', out['coverage_note'])

    def test_edges_carry_their_own_falsifier(self):
        out = rel.relate('202606_MATH_DIF_15', ITEM15, '202106_MATH_DIF_22', ITEM2021)
        self.assertIn('exhibit a function', out['edges'][0]['falsified_by'])


class TestHubExplosionDefence(unittest.TestCase):
    def test_a_background_premise_cannot_carry_an_edge(self):
        """Thirty distinct items in this corpus mention a cubic. If that counted as a shared
        conclusion they would collapse into one meaningless clique."""
        bg = cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0),
                                         'MULT': ('GROUND', 2)}, CUBIC, node_id='BG')
        bg.binding['_background'] = ('GROUND', True)
        out = rel.relate('a', [bg], 'b', ITEM2021)
        self.assertEqual(out['edges'], [])


class TestAdjudication(unittest.TestCase):
    def test_reproduces_one_accept_two_not_accepted(self):
        out = rel.adjudicate(
            '202606_MATH_DIF_15', ITEM15,
            [('202106_MATH_DIF_22', ITEM2021),
             ('202411_MATH_DIF_22', []),
             ('202506_MATH_DIF_22', ITEM2025)])
        by_item = {r['claimed_precedent']: r['verdict'] for r in out['results']}
        self.assertEqual(by_item['202106_MATH_DIF_22'], 'ACCEPT')
        self.assertEqual(by_item['202506_MATH_DIF_22'], 'REJECT')
        self.assertEqual(by_item['202411_MATH_DIF_22'], 'NOT_EXPRESSIBLE')

    def test_inexpressible_is_not_folded_into_reject(self):
        """A coverage gap must not be able to masquerade as a finding about mathematics."""
        out = rel.adjudicate('x', ITEM15, [('sequence_item', [])])
        self.assertEqual(out['results'][0]['verdict'], 'NOT_EXPRESSIBLE')
        self.assertEqual(out['tally']['REJECT'], 0)


if __name__ == '__main__':
    unittest.main()
