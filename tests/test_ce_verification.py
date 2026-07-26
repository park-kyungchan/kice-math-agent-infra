# -*- coding: utf-8 -*-
"""Tests for pipeline/axis_eval/ce_verification.py.

The barrier exists because this repository already shipped a "verification_protocol" that
verified nothing -- it asserted the answer it was handed. These tests pin the properties that
distinguish real verification from that: a false node is caught even when the set as a whole
still determines the right answer, a fabricated set is caught, and a leak is caught in prose as
well as in a JSON field.
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine import conclusion_form as cf          # noqa: E402
from pipeline.axis_eval import ce_verification as vb             # noqa: E402

AMBIENT = {'family': 'POLYNOMIAL', 'degree': 3, 'fixed_coefficients': {'c0': 0}}


def node(nid, schema, binding):
    return cf.Conclusion(schema, binding, AMBIENT, node_id=nid)


N1 = node('N1', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0), 'MULT': ('GROUND', 2)})
N2 = node('N2', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 3), 'MULT': ('GROUND', 1)})
N4 = node('N4', 'EXTREMUM_VALUE', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 2),
                                   'VALUE': ('GROUND', -1), 'KIND': ('GROUND', 'LOCAL_MIN')})
FALSE_NODE = node('NX', 'ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 5),
                                      'MULT': ('GROUND', 1)})


class TestSufficiencyAndSoundness(unittest.TestCase):
    def test_real_set_determines_the_target(self):
        status, value = vb.sufficiency([N1, N2, N4], AMBIENT, 6)
        self.assertEqual(status, 'DETERMINED')
        self.assertEqual(value, 27)

    def test_cross_checkable_nodes_are_true_and_the_keystone_is_reported_unchecked(self):
        """Leave-one-out is the only non-circular check available from inside the set. N1 and
        N2 are each confirmed against the function the others determine. N4 is the keystone --
        the rest cannot pin down a function without it -- so it is reported UNCHECKED rather
        than given a green tick that would mean nothing."""
        rows = {r['node']: r['verdict'] for r in vb.soundness([N1, N2, N4], AMBIENT)}
        self.assertEqual(rows['N1'], 'TRUE')
        self.assertEqual(rows['N2'], 'TRUE')
        self.assertEqual(rows['N4'], 'UNCHECKED')

    def test_a_false_node_is_caught_by_leaving_it_out(self):
        """A checked-against-the-whole-set implementation would pass this fabrication, because
        the function it checks against was solved for using the fabrication itself."""
        rows = {r['node']: r['verdict']
                for r in vb.soundness([N1, N2, N4, FALSE_NODE], AMBIENT)}
        self.assertEqual(rows['NX'], 'FALSE')
        result = vb.barrier([N1, N2, N4, FALSE_NODE], AMBIENT, 6, answer_values=[27])
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertTrue(any('unsound node NX' in f for f in result['failures']), result['failures'])


class TestMinimality(unittest.TestCase):
    def test_reports_the_disjunctive_structure_rather_than_demanding_it_away(self):
        mini = vb.minimality([N1, N2, N4], AMBIENT, 6)
        self.assertEqual(sorted(mini['minimal_sufficient_subsets']),
                         [['N1', 'N4'], ['N2', 'N4']])
        self.assertEqual(mini['keystone'], ['N4'])
        self.assertEqual(mini['structure'], 'disjunctive')

    def test_redundancy_flags_but_does_not_fail(self):
        result = vb.barrier([N1, N2, N4], AMBIENT, 6, answer_values=[27])
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['minimality']['non_contributing'], [])


class TestLeakDetection(unittest.TestCase):
    def test_name_detector_catches_the_historical_leak_shape(self):
        found = vb.leak_scan([('payload', '{"calculated_value": {"f_6": 99}}')], [27])
        self.assertTrue(any(f['detector'] == 'NAME' for f in found), found)

    def test_value_detector_catches_the_answer_hidden_in_prose(self):
        """The next place a leak hides after a name-based scan is deployed."""
        found = vb.leak_scan([('rationale', 'substituting gives 27 by direct evaluation')], [27])
        self.assertTrue(any(f['detector'] == 'VALUE' for f in found), found)

    def test_value_detector_catches_the_spelled_form(self):
        found = vb.leak_scan([('rationale', 'this yields twenty-seven at x=6')], [27])
        self.assertTrue(any(f['detector'] == 'VALUE' for f in found), found)

    def test_clean_reasoning_is_not_flagged(self):
        clean = 'Condition (가) forces a double root at the origin and a simple root at x=3.'
        self.assertEqual(vb.leak_scan([('rationale', clean)], [27]), [])

    def test_a_fabricated_stub_set_cannot_pass(self):
        """The gaming path an adversarial reviewer demonstrated against the acceptance criteria."""
        result = vb.barrier([], AMBIENT, 6, answer_values=[27])
        self.assertEqual(result['verdict'], 'FAIL')


class TestStageOrder(unittest.TestCase):
    def test_derived_stage_before_the_barrier_is_caught(self):
        events = [{'stage': 'ce.segmentation'}, {'stage': 'ce.canonical'},
                  {'stage': 'VERIFICATION_BARRIER'}]
        self.assertTrue(any('before the verification barrier' in p
                            for p in vb.stage_order_audit(events)))

    def test_missing_barrier_is_caught(self):
        events = [{'stage': 'ce.segmentation'}, {'stage': 'ce.variance'}]
        self.assertTrue(any('no verification barrier' in p
                            for p in vb.stage_order_audit(events)))

    def test_correct_order_passes(self):
        events = [{'stage': 'ce.segmentation'}, {'stage': 'ce.semantics'},
                  {'stage': 'ce.relation'}, {'stage': 'VERIFICATION_BARRIER'},
                  {'stage': 'ce.canonical'}, {'stage': 'ce.variance'}]
        self.assertEqual(vb.stage_order_audit(events), [])


if __name__ == '__main__':
    unittest.main()
