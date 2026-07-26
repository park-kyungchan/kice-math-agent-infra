# -*- coding: utf-8 -*-
"""Tests for pipeline/query_engine/rationale_ledger.py.

The ledger's value rests on three properties, and each is pinned here: prose cannot drift away
from the payload it explains, a trace that records only the path taken is rejected, and a step
cannot be rewritten after it has been reviewed.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine import rationale_ledger as rl  # noqa: E402

PAYLOAD = {'schema': 'ROOT_MULT', 'binding': {'X0': 0, 'MULT': 2}}


def full_steps(pointer):
    return [{'step_id': f's{i}', 'json_pointer': pointer, 'section': sec, 'body_md': 'text'}
            for i, sec in enumerate(rl.SECTIONS)]


class TestGates(unittest.TestCase):
    def test_gate_a_catches_a_field_nobody_explained(self):
        steps = full_steps('/binding/X0')
        problems = rl.gate_a(PAYLOAD, steps)
        self.assertTrue(any('/binding/MULT' in p for p in problems), problems)

    def test_gate_b_catches_a_reason_pointing_at_nothing(self):
        steps = full_steps('/binding/DOES_NOT_EXIST')
        self.assertTrue(rl.gate_b(PAYLOAD, steps))

    def test_gate_b_accepts_a_resolving_pointer(self):
        self.assertEqual(rl.gate_b(PAYLOAD, full_steps('/binding/X0')), [])

    def test_a_trace_without_rejected_is_refused(self):
        """Recording only the path taken teaches a reviewer nothing about the paths not taken."""
        steps = [s for s in full_steps('/binding/X0') if s['section'] != 'REJECTED']
        problems = rl.gate_sections(steps)
        self.assertTrue(any('REJECTED' in p for p in problems), problems)

    def test_a_complete_trace_passes_every_gate(self):
        steps = full_steps('/schema') + full_steps('/binding/X0') + full_steps('/binding/MULT')
        self.assertEqual(rl.run_gates(PAYLOAD, steps)['verdict'], 'PASS')


class TestLedgerStorage(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix='ledger_'), 'l.db')
        self.conn = sqlite3.connect(self.path)
        rl.ensure_schema(self.conn)

    def _append(self, seq, section, body='because the integral changes sign'):
        return rl.append_step(self.conn, 'run-1', '202606_MATH_DIF_15', 'ce.semantics',
                              seq, '/binding/X0', section, body, ['c-001'], '2026-07-26')

    def test_steps_are_hash_chained_so_history_cannot_be_rewritten_quietly(self):
        self._append(1, 'CONSIDERED')
        self._append(2, 'REJECTED')
        rows = self.conn.execute(
            'SELECT prev_step_hash, step_hash FROM rationale_step ORDER BY seq').fetchall()
        self.assertIsNone(rows[0][0])
        self.assertEqual(rows[1][0], rows[0][1])

    def test_rewriting_a_body_breaks_the_chain(self):
        self._append(1, 'CONSIDERED')
        original = self.conn.execute('SELECT step_hash FROM rationale_step').fetchone()[0]
        recomputed = rl.step_hash(None, {
            'run_id': 'run-1', 'item_id': '202606_MATH_DIF_15', 'axis_key': 'ce.semantics',
            'seq': 1, 'json_pointer': '/binding/X0', 'section': 'CONSIDERED',
            'body_md': 'tampered', 'inputs_cited': ['c-001']})
        self.assertNotEqual(original, recomputed)

    def test_an_unknown_section_is_refused(self):
        with self.assertRaises(ValueError):
            self._append(1, 'MUSINGS')

    def test_reject_reasoning_is_an_available_verdict(self):
        """A right answer reached by invalid reasoning is invisible to every outcome-only
        check, and is the first thing a teacher notices."""
        self.assertIn('REJECT_REASONING', rl.VERDICTS)


class TestRendering(unittest.TestCase):
    def test_render_groups_by_pointer_and_orders_sections(self):
        out = rl.render_markdown(full_steps('/binding/X0'))
        self.assertIn('## /binding/X0', out)
        self.assertLess(out.index('**CONSIDERED**'), out.index('**REJECTED**'))
        self.assertLess(out.index('**EVIDENCE**'), out.index('**FALSIFIER**'))


if __name__ == '__main__':
    unittest.main()
