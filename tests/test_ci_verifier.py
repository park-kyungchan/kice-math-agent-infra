# -*- coding: utf-8 -*-
"""
Acceptance tests for External CI Attestation Verifier (v2.8.4 Milestone B).
Covers: attestation schema verification, stale commit evidence rejection.
"""
import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from pipeline.governance_service.ci_verifier import verify_ci_attestation, CIAttestationError


class TestCIVerifier(unittest.TestCase):
    def setUp(self):
        self.valid_evidence = {
            "workflow": "governance-ci",
            "run_id": 30098554007,
            "tested_head_sha": "03aec751aa153b91e4e680487cfb33f060541ef1",
            "conclusion": "success",
            "verified_at": "2026-07-24T13:51:41Z",
        }

    def test_valid_ci_attestation_verifies_cleanly(self):
        res = verify_ci_attestation(self.valid_evidence, requested_head_sha="03aec751aa153b91e4e680487cfb33f060541ef1")
        self.assertTrue(res["is_valid"])
        self.assertFalse(res["is_stale"])

    def test_stale_ci_evidence_rejected_for_current_head(self):
        """Stale evidence remains valid for tested commit but MUST NOT activate a different requested HEAD."""
        res = verify_ci_attestation(self.valid_evidence, requested_head_sha="7b3e53692283d0e49e3ee8e1b63623d789809dc6")
        self.assertFalse(res["is_valid"])
        self.assertTrue(res["is_stale"])
        self.assertEqual(res["latest_attested_commit"], "03aec751aa153b91e4e680487cfb33f060541ef1")

    def test_invalid_evidence_payload_raises(self):
        bad_evidence = dict(self.valid_evidence, conclusion="failure")
        with self.assertRaises(CIAttestationError):
            verify_ci_attestation(bad_evidence)


if __name__ == '__main__':
    unittest.main()
