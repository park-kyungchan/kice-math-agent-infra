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
        "tested_head_sha": sha,
        "latest_attested_commit": sha,
        "run_id": run_id,
        "conclusion": conclusion,
    }


def verify_remote_ci_live(
    run_id: int,
    expected_sha: Optional[str] = None,
    owner: str = "park-kyungchan",
    repo: str = "kice-math-agent-infra",
) -> Dict[str, Any]:
    """Queries live GitHub REST API via gh CLI or urllib to attest remote check run status."""
    import json
    import subprocess

    try:
        cmd = ["gh", "api", f"repos/{owner}/{repo}/actions/runs/{run_id}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            raise CIAttestationError(f"GitHub API query failed: {proc.stderr.strip()}")
        
        data = json.loads(proc.stdout)
        status = data.get("status")
        conclusion = data.get("conclusion")
        head_sha = data.get("head_sha")
        wf_name = data.get("name")

        if wf_name != "governance-ci":
            raise CIAttestationError(f"Remote workflow name mismatch: {wf_name!r}")
        if conclusion != "success":
            raise CIAttestationError(f"Remote CI run conclusion is not success: {conclusion!r}")

        is_stale = False
        if expected_sha and expected_sha.lower() != (head_sha or "").lower():
            is_stale = True

        return {
            "is_valid": not is_stale,
            "is_stale": is_stale,
            "run_id": run_id,
            "head_sha": head_sha,
            "conclusion": conclusion,
            "status": status,
        }
    except Exception as e:
        if isinstance(e, CIAttestationError):
            raise
        raise CIAttestationError(f"Live GitHub attestation error: {e}")
