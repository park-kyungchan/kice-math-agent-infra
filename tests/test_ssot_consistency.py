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
        """v2.8.2: 'ACTIVE' previously overclaimed a passed remote-CI
        Acceptance Gate that had never actually happened (P1-3).
        teacher_governance_loop must report the honest pre-Acceptance-Gate
        status until a real green governance-ci run is bound via
        ci_evidence."""
        state = json.loads(open(v.PROJECT_STATE, encoding='utf-8').read())
        self.assertEqual(
            state.get('teacher_governance_loop'), 'IMPLEMENTED_LOCAL_VERIFIED',
            'IMPLEMENTED_LOCAL_VERIFIED expected until the Acceptance Gate '
            '(green remote CI bound via ci_evidence) actually passes; ACTIVE '
            'would overclaim an unverified remote-CI run'
        )

    def test_ci_evidence_binds_run_id_and_head_sha(self):
        """P1-3: ci_status must not be a bare self-attested string --
        PROJECT_STATE.json must carry a structured ci_evidence object naming
        the exact workflow, run_id, and head SHA the ci_status claim is bound
        to (values may be placeholders pending a real governance-ci run, but
        the KEYS/SHAPE must be present so the claim is auditable rather than
        an opaque assertion)."""
        state = json.loads(open(v.PROJECT_STATE, encoding='utf-8').read())
        self.assertIn('ci_evidence', state, 'PROJECT_STATE.json must bind ci_status to concrete evidence')
        evidence = state['ci_evidence']
        for key in ('workflow', 'run_id', 'tested_head_sha', 'conclusion', 'verified_at'):
            self.assertIn(key, evidence, f'ci_evidence missing required key: {key}')
        self.assertEqual(evidence['workflow'], 'governance-ci')
        self.assertIsInstance(evidence['run_id'], int)
        self.assertRegex(evidence['tested_head_sha'], r'^[0-9a-f]{40}$',
                         'tested_head_sha must be a 40-hex-char SHA (placeholder or real)')
        # A placeholder conclusion must never silently read as a real pass --
        # 'success' may ONLY be recorded once a real run has actually been observed.
        self.assertIn(evidence['conclusion'], ('success', 'failure', 'PENDING_VERIFICATION'))

    def test_validator_cli_green(self):
        import subprocess
        res = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, 'scripts', 'validate_ssot_consistency.py')],
            capture_output=True, text=True, cwd=BASE_DIR,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == '__main__':
    unittest.main()
