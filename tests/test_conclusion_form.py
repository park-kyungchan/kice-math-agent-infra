# -*- coding: utf-8 -*-
"""Tests for pipeline/query_engine/conclusion_form.py.

The load-bearing property is that "are these two conclusions the same?" is decidable and
honest: identical spellings collapse, different facts do not, and anything the procedure
cannot prove comes back UNDECIDED rather than being rounded to a confident answer.
"""
import os
import sys
import unittest

import sympy as sp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine import conclusion_form as cf  # noqa: E402

AMBIENT = {'family': 'POLYNOMIAL', 'degree': 3, 'fixed_coefficients': {'c0': 0}}

N1 = cf.Conclusion('ROOT_MULT',
                   {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0), 'MULT': ('GROUND', 2)},
                   AMBIENT, node_id='N1')
N2 = cf.Conclusion('ROOT_MULT',
                   {'F': ('GROUND', 'f'), 'X0': ('GROUND', 3), 'MULT': ('GROUND', 1)},
                   AMBIENT, node_id='N2')
N4 = cf.Conclusion('EXTREMUM_VALUE',
                   {'F': ('GROUND', 'f'), 'X0': ('GROUND', 2), 'VALUE': ('GROUND', -1),
                    'KIND': ('GROUND', 'LOCAL_MIN')},
                   AMBIENT, node_id='N4')


def _recover(nodes, target_x=6):
    """Solve for f from nodes alone and evaluate at target_x. The answer key is never read."""
    f, coeffs, cons = cf.build_function(AMBIENT)
    eqs = list(cons)
    for n in nodes:
        eqs += n.to_constraints(f)
    for sol in sp.solve(eqs, coeffs, dict=True):
        g = f.subs(sol)
        if g.free_symbols - {cf.X}:
            continue
        if sp.Poly(g, cf.X).degree() != AMBIENT['degree']:
            continue
        return sp.nsimplify(g.subs(cf.X, target_x))
    return None


class TestReproducesW0(unittest.TestCase):
    """The W0 probe established these facts empirically; the module must reproduce them."""

    def test_independent_node_set_recovers_the_target(self):
        self.assertEqual(_recover([N1, N2, N4]), 27)

    def test_both_minimal_sufficient_subsets_recover(self):
        """The structure is disjunctive -- N4 AND (N1 OR N2) -- not a flat conjunction."""
        self.assertEqual(_recover([N1, N4]), 27)
        self.assertEqual(_recover([N2, N4]), 27)

    def test_the_keystone_is_necessary(self):
        self.assertIsNone(_recover([N1, N2]))


class TestNormalFormHash(unittest.TestCase):
    def test_rational_and_decimal_spellings_collapse(self):
        a = cf.Conclusion('EXTREMUM_VALUE',
                          {'F': ('GROUND', 'f'), 'X0': ('GROUND', 2),
                           'VALUE': ('GROUND', '1/4'), 'KIND': ('GROUND', 'LOCAL_MIN')}, AMBIENT)
        b = cf.Conclusion('EXTREMUM_VALUE',
                          {'F': ('GROUND', 'f'), 'X0': ('GROUND', 2),
                           'VALUE': ('GROUND', '0.25'), 'KIND': ('GROUND', 'LOCAL_MIN')}, AMBIENT)
        self.assertEqual(a.normal_form_hash(), b.normal_form_hash())

    def test_different_multiplicity_is_a_different_fact(self):
        triple = cf.Conclusion('ROOT_MULT',
                               {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0),
                                'MULT': ('GROUND', 3)}, AMBIENT)
        self.assertNotEqual(N1.normal_form_hash(), triple.normal_form_hash())

    def test_bound_variable_letter_does_not_matter(self):
        r = cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('EXISTENTIAL', 'R'),
                                        'MULT': ('GROUND', 2)}, AMBIENT)
        s = cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('EXISTENTIAL', 'S'),
                                        'MULT': ('GROUND', 2)}, AMBIENT)
        self.assertEqual(r.normal_form_hash(), s.normal_form_hash())

    def test_ambient_typing_participates_in_the_hash(self):
        other = dict(AMBIENT, degree=4)
        quartic = cf.Conclusion('ROOT_MULT',
                                {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0),
                                 'MULT': ('GROUND', 2)}, other)
        self.assertNotEqual(N1.normal_form_hash(), quartic.normal_form_hash())

    def test_a_raw_float_is_refused_at_the_boundary(self):
        with self.assertRaises(cf.ConclusionError):
            cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('GROUND', 0.25),
                                        'MULT': ('GROUND', 2)}, AMBIENT)


class TestRelationVerdict(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(cf.relation(N1, N1)[0], 'IDENTICAL')

    def test_ground_implies_its_existential_generalisation(self):
        exists = cf.Conclusion('ROOT_MULT', {'F': ('GROUND', 'f'), 'X0': ('EXISTENTIAL', 'R'),
                                             'MULT': ('GROUND', 2)}, AMBIENT)
        verdict, _reason = cf.relation(N1, exists)
        self.assertEqual(verdict, 'IMPLIES')

    def test_same_schema_incompatible_ground_values_are_distinct(self):
        self.assertEqual(cf.relation(N1, N2)[0], 'DISTINCT')

    def test_schemas_sharing_no_structural_sort_are_distinct(self):
        area = cf.Conclusion('AREA_TRIANGLE',
                             {'P1': ('GROUND', 'A'), 'P2': ('GROUND', 'O'),
                              'P3': ('GROUND', 'B'), 'VALUE': ('GROUND', 16)}, {})
        count = cf.Conclusion('ROOT_COUNT', {'G': ('GROUND', 'f'), 'N': ('GROUND', 2)}, {})
        self.assertEqual(cf.relation(area, count)[0], 'DISTINCT')

    def test_a_shared_scalar_sort_does_not_make_two_schemas_comparable(self):
        """Almost every schema mentions a real number. 'the area is 16' and 'the local minimum
        is -1' are plainly different conclusions, and a rule that called them merely UNDECIDED
        because both involve a real value would never prove anything distinct."""
        area = cf.Conclusion('AREA_TRIANGLE',
                             {'P1': ('GROUND', 'A'), 'P2': ('GROUND', 'O'),
                              'P3': ('GROUND', 'B'), 'VALUE': ('GROUND', 16)}, {})
        verdict, reason = cf.relation(area, N4)
        self.assertEqual(verdict, 'DISTINCT')
        self.assertIn('structural sort', reason)

    def test_unprovable_pairs_return_undecided_not_a_guess(self):
        verdict, reason = cf.relation(N1, N4)
        self.assertEqual(verdict, 'UNDECIDED')
        self.assertIn('human review', reason)


class TestHonestyAboutLimits(unittest.TestCase):
    """An untranslatable schema must fail loudly. Returning no constraints would let it read
    as satisfied, which is how a system comes to look more capable than it is."""

    def test_untranslatable_schema_raises_rather_than_returning_nothing(self):
        f, _c, _cons = cf.build_function(AMBIENT)
        sign = cf.Conclusion('COEFF_SIGN', {'F': ('GROUND', 'f'), 'C': ('GROUND', 'leading'),
                                            'SIGN': ('GROUND', 'POS')}, AMBIENT)
        with self.assertRaises(cf.ConclusionError):
            sign.to_constraints(f)

    def test_inequality_relation_raises(self):
        f, _c, _cons = cf.build_function(AMBIENT)
        gt = cf.Conclusion('DERIV_EVAL',
                           {'F': ('GROUND', 'f'), 'ORDER': ('GROUND', 1), 'X0': ('GROUND', 0),
                            'VALUE': ('GROUND', 1), 'REL': ('GROUND', 'GT')}, AMBIENT)
        with self.assertRaises(cf.ConclusionError):
            gt.to_constraints(f)

    def test_unimplemented_ambient_family_raises(self):
        with self.assertRaises(cf.ConclusionError):
            cf.build_function({'family': 'EXPONENTIAL_COMBINATION'})

    def test_unknown_schema_is_refused_the_vocabulary_is_closed(self):
        with self.assertRaises(cf.ConclusionError):
            cf.Conclusion('SEQUENCE_RECURRENCE', {}, {})


class TestLemmaLibrary(unittest.TestCase):
    def test_seed_lemmas_load_and_carry_their_provenance(self):
        lemmas = cf.load_lemmas()
        self.assertGreaterEqual(len(lemmas), 2)
        for lem in lemmas:
            self.assertTrue(lem['citing_item_ids'], f'{lem["lemma_id"]} cites no real item')
            self.assertTrue(lem['proof_sketch'], f'{lem["lemma_id"]} has no proof sketch')


if __name__ == '__main__':
    unittest.main()
