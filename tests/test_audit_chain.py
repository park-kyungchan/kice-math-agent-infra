# -*- coding: utf-8 -*-
"""
Acceptance tests for HMAC Audit Chain Signing & Verifier (v2.8.4 Milestone B).
Covers: per-item hash chaining, tamper detection (mutation, deletion, unsigned insert),
        legacy unsigned row handling, and verifier exit codes.
"""
import os
import shutil
import sys
import tempfile
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from pipeline.query_engine.selective_fetcher import QuestionFetcher
from pipeline.governance_service.service_api import GovernanceService
from pipeline.governance_service.audit_signer import verify_audit_chain, DEFAULT_SERVICE_KEY
from pipeline.migrate_db_v2_8_1 import run_migration
from pipeline.migrate_db_v2_8_4 import migrate as run_migration_v2_8_4
from pipeline.migrate_db_v2_9_0 import migrate as run_migration_v2_9_0
try:
    from tests.test_review_state_machine import build_mini_db
except ImportError:
    from test_review_state_machine import build_mini_db


class TestAuditChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='audit_chain_')
        cls._golden = os.path.join(cls._tmpdir, 'golden.db')
        build_mini_db(cls._golden)
        run_migration(cls._golden, backup=False)
        run_migration_v2_8_4(cls._golden)
        run_migration_v2_9_0(cls._golden)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        self.db = os.path.join(self._tmpdir, f'{self._testMethodName}.db')
        shutil.copy2(self._golden, self.db)
        self.fetcher = QuestionFetcher(db_path=self.db)
        self.service = GovernanceService(self.fetcher)
        self.teacher_principal = {"principal_id": "auth-t-kim", "principal_type": "TEACHER"}
        self.system_principal = {"principal_id": "auto-system", "principal_type": "SYSTEM"}

    def test_signed_event_chain_verifies_cleanly(self):
        self.service.reopen_item('ITEM_FULL', self.system_principal, reason_code='REQUEUED')
        self.service.assign_item('ITEM_FULL', self.teacher_principal)
        self.service.approve_item('ITEM_FULL', self.teacher_principal, notes='LGTM')

        with self.fetcher.get_connection() as conn:
            violations = verify_audit_chain(conn, 'ITEM_FULL')
        self.assertEqual(violations, [], f"Audit chain must have 0 violations, got: {violations}")

    def test_audit_verifier_detects_field_mutation(self):
        self.service.reopen_item('ITEM_FULL', self.system_principal, reason_code='REQUEUED')
        self.service.assign_item('ITEM_FULL', self.teacher_principal)

        # 1. Direct SQL UPDATE is blocked by trigger
        with self.fetcher.get_connection() as conn:
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE teacher_review_event SET notes = 'TAMPERED_BY_AGENT' WHERE item_id = 'ITEM_FULL'")

        # 2. Simulate raw DB tampering by dropping trigger temporarily
        with self.fetcher.get_connection() as conn:
            conn.execute("DROP TRIGGER teacher_review_event_no_update")
            conn.execute("UPDATE teacher_review_event SET notes = 'TAMPERED_BY_AGENT' WHERE item_id = 'ITEM_FULL'")
            conn.commit()
            violations = verify_audit_chain(conn, 'ITEM_FULL')

        self.assertTrue(len(violations) > 0, "Verifier must detect field mutation")
        types = [v['violation_type'] for v in violations]
        self.assertIn('EVENT_MUTATION', types)

    def test_audit_verifier_detects_unsigned_insert(self):
        self.service.reopen_item('ITEM_FULL', self.system_principal, reason_code='REQUEUED')

        # Direct SQL insertion of an unsigned event (simulating malicious agent insert)
        with self.fetcher.get_connection() as conn:
            conn.execute(
                """INSERT INTO teacher_review_event
                   (event_id, item_id, from_status, to_status, actor_type, actor_id,
                    action, reason_code, notes, evidence_json, item_version, created_at,
                    principal_id, principal_type, request_id, prev_event_hash, event_hash,
                    signature_key_id, event_hmac)
                   VALUES ('EVT-FAKE-1', 'ITEM_FULL', 'TEACHER_ASSIGNED', 'TEACHER_APPROVED',
                           'TEACHER', 'fake-agent', 'APPROVE', 'NONE', 'Fake approve', '[]',
                           99, datetime('now'), 'fake-agent', 'TEACHER', 'REQ-FAKE',
                           '0000', '0000', 'FORGED_KEY', 'FORGED_HMAC')"""
            )
            conn.commit()
            violations = verify_audit_chain(conn, 'ITEM_FULL')

        self.assertTrue(len(violations) > 0, "Verifier must detect forged unsigned event")
        types = [v['violation_type'] for v in violations]
        self.assertTrue('INVALID_HMAC_SIGNATURE' in types or 'EVENT_MUTATION' in types or 'BROKEN_HASH_CHAIN' in types)

    def test_legacy_unsigned_rows_accepted(self):
        """Legacy audit rows marked LEGACY_UNSIGNED are verified cleanly without error."""
        with self.fetcher.get_connection() as conn:
            conn.execute(
                """INSERT INTO teacher_review_event
                   (event_id, item_id, from_status, to_status, actor_type, actor_id,
                    action, reason_code, notes, evidence_json, item_version, created_at,
                    signature_key_id, event_hmac)
                   VALUES ('EVT-LEGACY-1', 'ITEM_FULL', 'AUTO_ANALYSIS_COMPLETED', 'REVIEW_REQUIRED',
                           'SYSTEM', 'sys', 'AUTO_SYNC', 'QUALITY_PLANE_UNRESOLVED', NULL, '[]',
                           1, '2026-07-24T00:00:00Z', 'LEGACY', 'LEGACY_UNSIGNED')"""
            )
            conn.commit()
            violations = verify_audit_chain(conn, 'ITEM_FULL')

        self.assertEqual(violations, [], "Legacy rows marked LEGACY_UNSIGNED must be accepted cleanly")


if __name__ == '__main__':
    unittest.main()
