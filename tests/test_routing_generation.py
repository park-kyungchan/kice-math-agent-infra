# -*- coding: utf-8 -*-
"""
Acceptance tests for the ROUTING.md regeneration pipeline (task P3).

Covers three things:
  1. The committed ROUTING.md matches tools/generate_routing.py's live output
     exactly (the same invariant scripts/validate_ssot_consistency.py's
     check_routing_regeneration enforces at gate time -- pinned here too so a
     plain `python3 -m unittest` run catches drift without needing the CLI).
  2. The regeneration-diff gate actually discriminates: mutating a throwaway
     copy of ROUTING.md by one character must make check_routing_regeneration
     report an error; the unmodified repo must not.
  3. The generator's self-check (path/command audit) finds zero broken
     references against the real repo -- if this ever regresses, ROUTING.md
     or ENTRYPOINT.md started pointing somewhere that does not exist, which
     is exactly the failure mode this task was commissioned to prevent.

These run against the REAL repo tree and the REAL live database, same as
tests/test_ssot_consistency.py.
"""
import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for _p in (BASE_DIR, os.path.join(BASE_DIR, 'scripts'), os.path.join(BASE_DIR, 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import validate_ssot_consistency as ssot  # noqa: E402
import generate_routing  # noqa: E402

ROUTING_MD = os.path.join(BASE_DIR, 'ROUTING.md')


class TestRoutingGeneration(unittest.TestCase):
    def test_routing_md_matches_generator_output(self):
        """The committed ROUTING.md must be byte-identical to what
        tools/generate_routing.py produces right now. This is the same
        assertion check_routing_regeneration makes inside the CLI gate,
        pinned directly here so it is visible in a plain unittest run."""
        with open(ROUTING_MD, 'r', encoding='utf-8') as f:
            committed = f.read()
        generated = generate_routing.render()
        self.assertEqual(
            committed, generated,
            'ROUTING.md has drifted from tools/generate_routing.py output -- '
            'regenerate with `python3 tools/generate_routing.py --write` and commit the result.'
        )

    def test_generator_is_deterministic_across_runs(self):
        """render() must not embed wall-clock time, PID, or any other
        run-to-run-varying value -- otherwise the regeneration-diff gate
        could never pass twice in a row. Calling it twice in the same
        process must yield identical strings."""
        first = generate_routing.render()
        second = generate_routing.render()
        self.assertEqual(first, second)

    def test_regeneration_diff_gate_catches_one_character_drift(self):
        """check_routing_regeneration must FAIL when ROUTING.md disagrees
        with the generator by even one character, and must NOT fail against
        the real, currently-committed file. Exercised via a throwaway
        temp-file fixture (routing_md_path override) -- never touches the
        real committed ROUTING.md at all. The fixture is written under the
        system temp directory (NOT the mounted repo): `rm`/os.remove is not
        permitted on the mount in this sandbox (see ROUTING.md §4b), so
        a fixture that needs deleting belongs outside it from the start."""
        import tempfile

        # Sanity: gate is clean against the real, unmodified committed file.
        clean_errors = []
        ssot.check_routing_regeneration(clean_errors)
        self.assertEqual(
            clean_errors, [],
            'check_routing_regeneration should be clean against the committed '
            'ROUTING.md'
        )

        with open(ROUTING_MD, 'r', encoding='utf-8') as f:
            original = f.read()
        mutated = original.replace('question_item` rows |', 'question_item`` rows |', 1)
        self.assertNotEqual(mutated, original, 'fixture mutation did not change anything to diff against')

        fd, tmp_path = tempfile.mkstemp(suffix='.md')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(mutated)
            dirty_errors = []
            ssot.check_routing_regeneration(dirty_errors, routing_md_path=tmp_path)
            self.assertEqual(len(dirty_errors), 1)
            self.assertTrue(dirty_errors[0].startswith('Routing drift:'))

            # A byte-identical (unmutated) copy at the same override path
            # must come back clean -- proves the check discriminates on
            # content, not merely on "is this the default path".
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(original)
            clean_override_errors = []
            ssot.check_routing_regeneration(clean_override_errors, routing_md_path=tmp_path)
            self.assertEqual(clean_override_errors, [])
        finally:
            os.remove(tmp_path)

    def test_generator_self_check_finds_zero_broken_references(self):
        """Every path/filename/command tools/generate_routing.py's own
        self-check scans for in ROUTING.md + ENTRYPOINT.md must actually
        exist/run against the real repo -- this is the automated version of
        scope requirement (e): verify every referenced path/command."""
        with open(generate_routing.ENTRYPOINT_MD, 'r', encoding='utf-8') as f:
            entrypoint_text = f.read()
        body = generate_routing.render_body()
        audit = generate_routing.self_check({
            'ROUTING.md': body,
            'ENTRYPOINT.md': entrypoint_text,
        })
        self.assertEqual(
            audit['broken_paths'], [],
            f"generator self-check found broken paths: {audit['broken_paths']}"
        )
        self.assertEqual(
            audit['broken_cmds'], [],
            f"generator self-check found broken commands: {audit['broken_cmds']}"
        )
        # Both counts should be non-trivial -- a check that silently scans
        # zero references would pass vacuously and prove nothing.
        self.assertGreater(audit['n_paths_checked'], 10)
        self.assertGreater(audit['n_cmds_checked'], 0)

    def test_axis2_raw_parsing_is_not_flagged_as_stub(self):
        """False-positive control (also asserted in
        test_content_completeness.py, pinned here too since P3's report
        leans on it): axis2_raw_parsing is the one axis with genuinely 100%
        real per-item analysis and must never appear in the Stub sentinel
        errors emitted by the reused check_axis_stub_sentinels logic."""
        stats, stub_errors = generate_routing.measure_axis_stub_stats()
        self.assertIn('axis2_raw_parsing', stats)
        self.assertEqual(stats['axis2_raw_parsing']['real'], stats['axis2_raw_parsing']['total'])
        for e in stub_errors:
            self.assertNotIn('axis2_raw_parsing', e)


if __name__ == '__main__':
    unittest.main()
