# -*- coding: utf-8 -*-
"""
Tests for pipeline/query_engine/axis_registry.py (I2 axis-agnostic storage
refactor) -- the single source of axis identity: key, human name, review
status, payload schema_version, and analyser/generator/derived kind.
"""
import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.query_engine import axis_registry as reg


EXPECTED_AXIS_COLUMNS = (
    'axis1_curriculum', 'axis2_raw_parsing', 'axis3_symbolic_modeling',
    'axis4_contextual_tree', 'axis5_traps_verification', 'axis6_genealogy',
    'axis7_mutation', 'axis8_knowledge_graph',
)
EXPECTED_DICT_KEYS = tuple(f'Axis_{i}' for i in range(1, 9))


class TestAxisRegistryShape(unittest.TestCase):
    def test_axis_columns_matches_legacy_ddl_order(self):
        """AXIS_COLUMNS must be the exact axis1..axis8 sequence the original
        axis_analysis DDL declared -- several consumers (the compatibility
        view, the migration script, scripts/validate_ssot_consistency.py)
        depend on this exact order."""
        self.assertEqual(reg.AXIS_COLUMNS, EXPECTED_AXIS_COLUMNS)

    def test_eight_legacy_axis_definitions_present(self):
        self.assertEqual(len(reg.LEGACY_AXIS_DEFINITIONS), 8)

    def test_six_ce_axis_definitions_present(self):
        self.assertEqual(len(reg.CE_AXIS_DEFINITIONS), 6)
        self.assertEqual(
            [d.axis_key for d in reg.CE_AXIS_DEFINITIONS],
            ['ce.segmentation', 'ce.semantics', 'ce.relation',
             'ce.canonical', 'ce.variance', 'ce.altgen'],
        )

    def test_ce_axes_never_enter_the_legacy_contract(self):
        """The regression this whole family split exists to prevent.

        AXIS_COLUMNS, AXIS_COLUMN_BY_DICT_KEY and DICT_KEY_BY_AXIS_COLUMN back the
        byte-for-byte Axis_1..Axis_8 public output contract and are consumed by
        selective_fetcher, claim_provenance, validate_ssot_consistency,
        migrate_db_axis_agnostic and generate_routing. A ce.* axis appearing in any
        of them silently changes that contract."""
        for key in reg.AXIS_COLUMNS:
            self.assertFalse(key.startswith('ce.'), f'{key} leaked into AXIS_COLUMNS')
        for dict_key, column in reg.AXIS_COLUMN_BY_DICT_KEY.items():
            self.assertFalse(column.startswith('ce.'), f'{column} leaked into the legacy map')
            self.assertTrue(dict_key.startswith('Axis_'), f'{dict_key} is not a legacy dict key')
        self.assertEqual(len(reg.DICT_KEY_BY_AXIS_COLUMN), 8)

    def test_dict_key_convention_matches_legacy_axis_n(self):
        dict_keys = tuple(d.dict_key for d in reg.LEGACY_AXIS_DEFINITIONS)
        self.assertEqual(dict_keys, EXPECTED_DICT_KEYS)

    def test_every_definition_has_valid_status(self):
        for d in reg.AXIS_DEFINITIONS:
            self.assertIn(d.status, reg.STATUS_VALUES, f'{d.axis_key} has invalid status {d.status!r}')

    def test_every_definition_has_valid_kind(self):
        for d in reg.AXIS_DEFINITIONS:
            self.assertIn(d.kind, reg.KIND_VALUES, f'{d.axis_key} has invalid kind {d.kind!r}')

    def test_every_definition_has_valid_layer(self):
        for d in reg.AXIS_DEFINITIONS:
            self.assertIn(d.layer, (1, 2, 3), f'{d.axis_key} has invalid layer {d.layer!r}')

    def test_axis_keys_are_unique(self):
        keys = [d.axis_key for d in reg.AXIS_DEFINITIONS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_dict_keys_are_unique(self):
        keys = [d.dict_key for d in reg.AXIS_DEFINITIONS]
        self.assertEqual(len(keys), len(set(keys)))


class TestAxisLookupHelpers(unittest.TestCase):
    def test_get_axis_by_key(self):
        d = reg.get_axis('axis2_raw_parsing')
        self.assertIsNotNone(d)
        self.assertEqual(d.dict_key, 'Axis_2')
        self.assertEqual(d.human_name, 'Literal Parsing & KaTeX Normalization')

    def test_get_axis_unknown_key_returns_none(self):
        self.assertIsNone(reg.get_axis('does_not_exist'))

    def test_get_axis_by_dict_key(self):
        d = reg.get_axis_by_dict_key('Axis_7')
        self.assertIsNotNone(d)
        self.assertEqual(d.axis_key, 'axis7_mutation')

    def test_get_axis_by_dict_key_unknown_returns_none(self):
        self.assertIsNone(reg.get_axis_by_dict_key('Axis_99'))

    def test_all_axis_keys_covers_every_registered_family(self):
        """all_axis_keys() means ALL registered axes, legacy and ce alike -- it is a
        governance helper, not the legacy contract. AXIS_COLUMNS is the legacy contract
        and is a strict subset."""
        keys = tuple(reg.all_axis_keys())
        self.assertEqual(keys, tuple(d.axis_key for d in reg.AXIS_DEFINITIONS))
        for column in reg.AXIS_COLUMNS:
            self.assertIn(column, keys)
        self.assertLess(len(reg.AXIS_COLUMNS), len(keys))

    def test_is_registered_true_for_known_axis(self):
        self.assertTrue(reg.is_registered('axis1_curriculum'))

    def test_is_registered_false_for_new_hypothetical_axis(self):
        """A brand-new axis_key (e.g. a pilot axis under evaluation) is NOT
        registered by default -- and that must not be treated as an error
        anywhere in the storage layer: analysis_derivation accepts
        unregistered axis_keys with zero DDL/registry change (see
        tests/test_migrate_axis_agnostic.py for the storage-layer proof)."""
        self.assertFalse(reg.is_registered('x_pilot_difficulty'))


class TestBackwardCompatMappings(unittest.TestCase):
    """These mappings replace the three independently hand-written copies
    that used to live in selective_fetcher.py, claim_provenance.py, and
    scripts/validate_ssot_consistency.py -- pin their shape exactly."""

    def test_axis_column_by_dict_key(self):
        self.assertEqual(reg.AXIS_COLUMN_BY_DICT_KEY['Axis_1'], 'axis1_curriculum')
        self.assertEqual(reg.AXIS_COLUMN_BY_DICT_KEY['Axis_8'], 'axis8_knowledge_graph')
        self.assertEqual(len(reg.AXIS_COLUMN_BY_DICT_KEY), 8)

    def test_dict_key_by_axis_column(self):
        self.assertEqual(reg.DICT_KEY_BY_AXIS_COLUMN['axis1_curriculum'], 'Axis_1')
        self.assertEqual(reg.DICT_KEY_BY_AXIS_COLUMN['axis8_knowledge_graph'], 'Axis_8')
        self.assertEqual(len(reg.DICT_KEY_BY_AXIS_COLUMN), 8)

    def test_mappings_are_mutual_inverses(self):
        for dict_key, column in reg.AXIS_COLUMN_BY_DICT_KEY.items():
            self.assertEqual(reg.DICT_KEY_BY_AXIS_COLUMN[column], dict_key)

    def test_selective_fetcher_imports_this_mapping(self):
        """Regression guard: selective_fetcher.py must resolve axis
        identity through the registry, not a private hand-written dict
        (mission requirement: single source of axis identity)."""
        from pipeline.query_engine import selective_fetcher as sf
        self.assertIs(sf.AXIS_COLUMN_BY_DICT_KEY, reg.AXIS_COLUMN_BY_DICT_KEY)

    def test_claim_provenance_imports_this_mapping(self):
        from pipeline.query_engine import claim_provenance as cp
        self.assertEqual(cp.AXIS_COLUMN, dict(reg.AXIS_COLUMN_BY_DICT_KEY))

    def test_validator_imports_axis_columns_from_registry(self):
        import importlib
        sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
        v = importlib.import_module('validate_ssot_consistency')
        self.assertEqual(v.AXIS_COLUMNS, reg.AXIS_COLUMNS)


class TestKnownCategoryFindings(unittest.TestCase):
    """Mission requirement: the registry must record these findings as
    status metadata rather than silently normalising them away."""

    def test_axis7_mutation_is_a_generator_not_an_analyser(self):
        d = reg.get_axis('axis7_mutation')
        self.assertEqual(d.kind, 'generator')

    def test_axis8_knowledge_graph_is_derived(self):
        d = reg.get_axis('axis8_knowledge_graph')
        self.assertEqual(d.kind, 'derived')
        self.assertIn('DERIVED', d.notes)

    def test_axis4_contextual_tree_notes_agent_reasoning(self):
        d = reg.get_axis('axis4_contextual_tree')
        self.assertIn('AGENT REASONING', d.notes)

    def test_axis3_symbolic_modeling_notes_concept_map_limitation(self):
        d = reg.get_axis('axis3_symbolic_modeling')
        self.assertIn('3 concepts', d.notes)

    def test_axis2_raw_parsing_is_the_one_active_axis(self):
        """axis2 is the one axis with genuinely 100% real data -- the drift
        gate's most important false-positive control (ROUTING.md)."""
        d = reg.get_axis('axis2_raw_parsing')
        self.assertEqual(d.status, 'active')

    def test_other_seven_axes_are_deprecated(self):
        """The owner concluded the taxonomy review on 2026-07-26 and retired the
        legacy axes in favour of the ce.* family. axis2_raw_parsing is spared: it is
        the one genuinely complete legacy axis and is orthogonal to the redesign.
        Retirement is archive-over-delete -- no analysis_derivation row is removed."""
        for key in reg.AXIS_COLUMNS:
            if key == 'axis2_raw_parsing':
                continue
            d = reg.get_axis(key)
            self.assertEqual(d.status, 'deprecated', f'{key} expected deprecated')

    def test_ce_axis_kinds_follow_the_registry_vocabulary(self):
        kinds = {d.axis_key: d.kind for d in reg.CE_AXIS_DEFINITIONS}
        self.assertEqual(kinds['ce.altgen'], 'generator')
        self.assertEqual(kinds['ce.canonical'], 'derived')
        self.assertEqual(kinds['ce.variance'], 'derived')
        for key in ('ce.segmentation', 'ce.semantics', 'ce.relation'):
            self.assertEqual(kinds[key], 'analyser')

    def test_analyser_generator_derived_kinds_partition_correctly(self):
        kinds = {d.axis_key: d.kind for d in reg.LEGACY_AXIS_DEFINITIONS}
        self.assertEqual(kinds['axis7_mutation'], 'generator')
        self.assertEqual(kinds['axis8_knowledge_graph'], 'derived')
        analysers = {k for k, kind in kinds.items() if kind == 'analyser'}
        self.assertEqual(
            analysers,
            {
                'axis1_curriculum', 'axis2_raw_parsing', 'axis3_symbolic_modeling',
                'axis4_contextual_tree', 'axis5_traps_verification', 'axis6_genealogy',
            },
        )


if __name__ == '__main__':
    unittest.main()
