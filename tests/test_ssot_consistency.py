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
        teacher_governance_loop must track ci_evidence honestly: ACTIVE is
        only legitimate once ci_evidence.conclusion is a real 'success';
        anything else (including the PENDING_VERIFICATION placeholder) must
        report the pre-Acceptance-Gate IMPLEMENTED_LOCAL_VERIFIED status.
        This is checked as a live invariant tied to ci_evidence, not a fixed
        string -- v2.8.2's first release cut this test against the
        pre-merge placeholder state and hardcoded the placeholder-era
        expectation, which broke the instant the Acceptance Gate was
        legitimately satisfied post-merge. Re-fixed here so it never goes
        stale again in either direction."""
        state = json.loads(open(v.PROJECT_STATE, encoding='utf-8').read())
        evidence = state.get('ci_evidence', {})
        expected = 'ACTIVE' if evidence.get('conclusion') == 'success' else 'IMPLEMENTED_LOCAL_VERIFIED'
        self.assertEqual(
            state.get('teacher_governance_loop'), expected,
            f"teacher_governance_loop must be {expected!r} given ci_evidence.conclusion="
            f"{evidence.get('conclusion')!r}; ACTIVE without a bound green run would overclaim"
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
        self.assertIn(evidence['conclusion'], ('success', 'failure', 'PENDING_VERIFICATION'))
        if evidence['conclusion'] == 'success':
            self.assertGreater(evidence['run_id'], 0, 'run_id must be > 0 on success conclusion')
            self.assertNotEqual(evidence['tested_head_sha'], '0' * 40, 'tested_head_sha must not be null SHA on success')
            self.assertRegex(evidence['verified_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', 'verified_at must be RFC 3339 timestamp')
            self.assertEqual(state.get('ci_status'), 'GOVERNANCE_CI_GREEN')

    def test_validator_cli_structural_checks_green(self):
        """The five *structural* checks (DDL, manifest/state, versions,
        transition matrix, ci_evidence) must stay green on today's repo --
        this is what v2.8.1 originally asserted end-to-end via CLI exit
        code. That end-to-end assertion no longer holds as of the v2.9.x
        content-completeness checks below (see
        test_validator_cli_fails_on_content_completeness_defects): the CLI
        now correctly reports FAIL because the live database is 99.8%
        placeholder analysis. So this test pins the structural sub-checks
        directly, in isolation, rather than the CLI exit code."""
        errors = []
        v.check_ddl(errors, v.DEFAULT_DB)
        v.check_manifest_vs_state(errors)
        v.check_versions(errors)
        v.check_transition_matrix(errors)
        v.check_ci_evidence(errors)
        self.assertEqual(errors, [])

    def test_validator_cli_fails_on_content_completeness_defects(self):
        """v2.9.x: the drift gate was structurally green while being
        content-blind -- axis analysis was 99.8% single-key placeholder
        sentinels, question_item.answer was a near-uniform 0, and
        latex_content was 100% corrupted by unmapped HWP Private-Use-Area
        codepoints, yet the old gate (DDL/manifest/version/matrix/ci_evidence
        only) reported OK. An audit that lies is worse than no audit.

        2026-07-25 update: the PUA corruption and the answer data were
        actually repaired, so the gate correctly STOPPED emitting 'PUA:' and
        'Answer sanity:' lines. Asserting on those strings would now pin the
        gate to a defect that no longer exists -- i.e. it would demand the
        audit keep lying in the opposite direction. Those assertions are
        therefore replaced by the two invariants that still hold and that we
        actually want enforced:
          1. the CLI must still FAIL, because the axis analysis IS still
             placeholder for 1,347/1,350 items, and
          2. the failure must remain diagnostic, naming the stub defect.
        The repaired checks are pinned positively in
        tests/test_content_completeness.py instead, which asserts they detect
        their defects against synthetic fixtures rather than against whatever
        state the live DB happens to be in.

        2026-07-26 update: the same trap sprang again, one level up. The owner
        retired seven of the eight legacy axes, so their placeholder payloads
        stopped being a defect and became a deliberate, recorded state. Pinning
        `returncode == 1` to that state would demand the gate stay red for a
        choice the project made on purpose -- and a gate that is permanently red
        for unactionable reasons is not a gate, because the only responses left
        are to lower the threshold or to ignore it. Escalation therefore moved to
        check_axis_status_honesty, which fires on drift between the registry's
        `status` claim and the data, exactly as every other check in the
        validator fires on drift between two sources of truth.

        What this test now pins, following its own 2025-07-25 precedent, is the
        invariant that actually matters and cannot be satisfied by a lying audit:
        the gate must not be content-BLIND, and must not HIDE the stub state.
        Whether that state fails the build is a question about claims, and it is
        proven against synthetic fixtures in TestAxisStatusHonesty below --
        including the case of an axis declared active while its data is
        placeholder, which still fails."""
        import subprocess
        res = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, 'scripts', 'validate_ssot_consistency.py')],
            capture_output=True, text=True, cwd=BASE_DIR,
        )
        combined = res.stdout + res.stderr
        # 1. The gate must not be content-blind: the completeness scan still runs.
        self.assertIn('AXIS ANALYSIS COMPLETENESS', combined)
        # 2. It must not hide the state it declines to escalate.
        self.assertIn('NOT ESCALATED', combined)
        self.assertIn('status=deprecated', combined)
        # 3. It must not let a row count be mistaken for corpus coverage.
        self.assertIn('DENOMINATOR', combined)
        # 4. Regression guard: the repaired defects must NOT reappear.
        self.assertNotIn('PUA:', combined)
        self.assertNotIn('Answer sanity:', combined)
        # 5. Escalation is a question about claims, not raw state, and is pinned
        #    against synthetic fixtures in TestAxisStatusHonesty.


if __name__ == '__main__':
    unittest.main()


class TestAxisStatusHonesty(unittest.TestCase):
    """check_axis_status_honesty must FAIL on a known-broken fixture and PASS on a
    healthy one -- the standard this repository sets for every data-quality gate.

    Background. The stub-sentinel scan measures how complete each axis is. That is a state
    observation, and escalating it to a gate failure made the gate permanently red: a
    deprecated axis can never reach the threshold, and a newly introduced axis starts empty.
    A permanently red gate trains people to ignore it. The escalation therefore moved here,
    where it takes the same form as every other check in the validator -- drift between a
    declared source of truth (the registry's `status`) and observed reality.
    """

    def _fixture(self, rows, registry_status):
        """Build a throwaway DB plus a patched registry view of the world."""
        import sqlite3
        import tempfile
        from collections import namedtuple

        path = os.path.join(tempfile.mkdtemp(prefix='axis_honesty_'), 'fixture.db')
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE question_item (item_id TEXT PRIMARY KEY, latex_content TEXT)')
        conn.execute(
            'CREATE TABLE analysis_derivation ('
            ' item_id TEXT, axis_key TEXT, payload TEXT)'
        )
        for i in range(10):
            conn.execute('INSERT INTO question_item VALUES (?,?)', (f'i{i}', f'content {i}'))
        for item_id, axis_key, payload in rows:
            conn.execute('INSERT INTO analysis_derivation VALUES (?,?,?)',
                         (item_id, axis_key, payload))
        conn.commit()
        conn.close()

        Defn = namedtuple('Defn', 'axis_key status')
        return path, {k: Defn(k, s) for k, s in registry_status.items()}

    def _run(self, rows, registry_status):
        original = v.AXIS_BY_KEY
        path, patched = self._fixture(rows, registry_status)
        errors = []
        try:
            v.AXIS_BY_KEY = patched
            v.check_axis_status_honesty(errors, path)
        finally:
            v.AXIS_BY_KEY = original
        return errors

    REAL = json.dumps({'a': 1, 'b': [2, 3], 'c': {'d': 'rich structure'}})
    STUB = json.dumps({'objective': 'OBJ_UNDERSTAND'})

    def test_healthy_active_axis_passes(self):
        rows = [(f'i{i}', 'ce.semantics', self.REAL) for i in range(10)]
        self.assertEqual(self._run(rows, {'ce.semantics': 'active'}), [])

    def test_r2_active_axis_below_threshold_fails(self):
        """An axis the registry calls trustworthy while its data is mostly placeholder."""
        rows = [('i0', 'ce.semantics', self.REAL)]
        rows += [(f'i{i}', 'ce.semantics', self.STUB) for i in range(1, 10)]
        errors = self._run(rows, {'ce.semantics': 'active'})
        self.assertTrue(any('R2' in e for e in errors), errors)
        self.assertTrue(any('status=active' in e for e in errors), errors)

    def test_r3_active_axis_with_no_rows_fails(self):
        """An axis cannot be trustworthy and empty at the same time."""
        errors = self._run([], {'ce.semantics': 'active'})
        self.assertTrue(any('R3' in e for e in errors), errors)

    def test_r1_unregistered_axis_with_real_data_fails(self):
        """Real analysis exists under an axis_key nobody has documented."""
        rows = [(f'i{i}', 'ce.ghost', self.REAL) for i in range(10)]
        errors = self._run(rows, {})
        self.assertTrue(any('R1' in e for e in errors), errors)
        self.assertTrue(any('ce.ghost' in e for e in errors), errors)

    def test_deprecated_axis_below_threshold_does_not_fail(self):
        """The regression this whole change exists to prevent: a retired axis must not
        hold the gate red forever. It is still reported by the stub-sentinel scan."""
        rows = [(f'i{i}', 'axis1_curriculum', self.STUB) for i in range(10)]
        self.assertEqual(self._run(rows, {'axis1_curriculum': 'deprecated'}), [])

    def test_under_review_axis_below_threshold_does_not_fail(self):
        """A newly introduced axis starts empty; that must not be a gate failure on day one."""
        rows = [('i0', 'ce.canonical', self.REAL)]
        self.assertEqual(self._run(rows, {'ce.canonical': 'under_review'}), [])
