# -*- coding: utf-8 -*-
"""
Reproducible test-run evidence recorder.
Runs the unittest suite and writes a machine-verifiable summary that binds the
result to a specific commit, command, and environment — replacing the old
unverifiable storage/logs/ci_test_run.json (renamed: local_test_summary.json,
because a locally produced log is NOT CI evidence; CI evidence is the GitHub
Actions workflow run for the same commit SHA).

Usage: python scripts/run_local_tests.py [--output PATH]
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_OUT = os.path.join(BASE_DIR, 'storage', 'logs', 'local_test_summary.json')


def git(*args):
    try:
        return subprocess.run(['git', *args], capture_output=True, text=True,
                              cwd=BASE_DIR).stdout.strip()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=DEFAULT_OUT)
    args = parser.parse_args()

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(BASE_DIR, 'tests'))
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stderr, resultclass=unittest.TextTestResult)
    t0 = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - t0

    summary = {
        "kind": "local_test_summary",
        "note": "Local evidence only. Authoritative CI evidence = GitHub Actions "
                "'governance-ci' run for the same commit_sha.",
        "commit_sha": git('rev-parse', 'HEAD'),
        "branch": git('rev-parse', '--abbrev-ref', 'HEAD'),
        "working_tree_dirty": bool(git('status', '--porcelain')),
        "command": "python -m unittest discover -s tests",
        "python_version": sys.version,
        "platform": platform.platform(),
        "tests_run": result.testsRun,
        "failures": [str(t) for t, _ in result.failures],
        "errors": [str(t) for t, _ in result.errors],
        "skipped": [str(t) for t, _ in getattr(result, 'skipped', [])],
        "ok": result.wasSuccessful(),
        "time_seconds": round(elapsed, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: summary[k] for k in
                      ('commit_sha', 'tests_run', 'ok', 'time_seconds')}, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
