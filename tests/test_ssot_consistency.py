# -*- coding: utf-8 -*-
"""
Acceptance tests for SSoT consistency (v2.8.1).
Covers: test_ssot_ddl_matches_live_database,
        test_manifest_does_not_contradict_project_state, version coherence,
        transition-matrix doc/code coherence.
These run against the REAL repo documents and the REAL live database —
they are the drift gate the external review required.
"""
import json
import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))

import validate_ssot_consistency as v


class TestSsotConsistency(unittest.TestCase):
    def test_ssot_ddl_matches_live_database(self):
        errors = []
        v.check_ddl(errors, v.DEFAULT_DB)
        self.assertEqual(errors, [])

    def test_manifest_does_not_contradict_project_state(self):
        errors = []
        v.check_manifest_vs_state(errors)
        self.assertEqual(errors, [])
        manifest = json.loads(open(v.MANIFEST, encoding='utf-8').read())
        self.assertEqual(manifest.get('project_state_ref'), 'PROJECT_STATE.json')
        self.assertNotIn('eval_gate_score', json.dumps(manifest))

    def test_version_strings_coherent(self):
        errors = []
        v.check_versions(errors)
        self.assertEqual(errors, [])

    def test_documented_matrix_matches_code(self):
        errors = []
        v.check_transition_matrix(errors)
        self.assertEqual(errors, [])

    def test_project_state_does_not_overclaim(self):
        state = json.loads(open(v.PROJECT_STATE, encoding='utf-8').read())
        self.assertEqual(state.get('teacher_governance_loop'), 'ACTIVE',
                         'ACTIVE expected after remote-CI Acceptance Gate merge')

    def test_validator_cli_green(self):
        import subprocess
        res = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, 'scripts', 'validate_ssot_consistency.py')],
            capture_output=True, text=True, cwd=BASE_DIR,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == '__main__':
    unittest.main()
