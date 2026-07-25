# -*- coding: utf-8 -*-
"""
External CI Attestation Verifier (v2.8.4)
=========================================
Verifies CI evidence attestations against external authorities (GitHub Actions Check Runs)
and prevents stale commit evidence from activating the current repository HEAD.
"""
import re
from typing import Any, Dict, Optional


class CIAttestationError(Exception):
    pass


def verify_ci_attestation(
    ci_evidence: Dict[str, Any],
    requested_head_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify CI attestation payload against external authority rules.
    If requested_head_sha is provided, asserts that tested_head_sha matches it exactly.
    Stale evidence remains valid for its tested commit but MUST NOT activate current HEAD."""
    if not isinstance(ci_evidence, dict) or not ci_evidence:
        raise CIAttestationError("ci_evidence payload must be a non-empty dictionary")

    workflow = ci_evidence.get("workflow")
    run_id = ci_evidence.get("run_id")
    sha = ci_evidence.get("tested_head_sha")
    conclusion = ci_evidence.get("conclusion")
    verified_at = ci_evidence.get("verified_at")

    if workflow != "governance-ci":
        raise CIAttestationError(f"Invalid workflow identity: {workflow!r}")
    if not isinstance(run_id, int) or run_id <= 0:
        raise CIAttestationError(f"Invalid run_id: {run_id!r}")
    if not isinstance(sha, str) or not re.fullmatch(r"^[0-9a-f]{40}$", sha) or sha == "0" * 40:
        raise CIAttestationError(f"Invalid tested_head_sha: {sha!r}")
    if conclusion != "success":
        raise CIAttestationError(f"ci_evidence conclusion is not success: {conclusion!r}")
    if not isinstance(verified_at, str) or not re.fullmatch(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", verified_at):
        raise CIAttestationError(f"Invalid verified_at timestamp: {verified_at!r}")

    is_stale = False
    if requested_head_sha:
        if requested_head_sha.lower() != sha.lower():
            is_stale = True

    return {
        "is_valid": not is_stale,
        "is_stale": is_stale,
        "latest_attested_commit": sha,
        "run_id": run_id,
        "conclusion": conclusion,
        "verified_at": verified_at,
    }
