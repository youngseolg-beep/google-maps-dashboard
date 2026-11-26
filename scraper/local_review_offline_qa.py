"""Run the staged local-review self-tests without browser or DB access."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SUITES = {
    "probe": ("local_review_profile_probe.py", ["--self-test"]),
    "batch": ("local_review_batch.py", ["--self-test"]),
    "health": ("local_review_health.py", ["--self-test"]),
    "invariants": ("review_audit_invariants.py", []),
    "preflight": ("review_append_preflight.py", []),
    "snapshot": ("review_append_snapshot.py", []),
    "writer": ("review_append_execution_qa.py", []),
    "source_identity": ("review_source_identity.py", []),
    "source_append_replay": ("review_source_append_preview.py", []),
    "source_storage_fixture": ("review_source_storage_qa.py", []),
    "source_recovery": ("review_source_recovery.py", []),
    "source_attempt_journal": ("review_source_attempt_journal.py", []),
    "incremental_boundary": ("review_incremental_boundary.py", []),
    "incremental_baseline": ("review_incremental_baseline.py", []),
    "incremental_capture": ("review_incremental_capture.py", []),
    "incremental_transaction": ("review_incremental_transaction_qa.py", []),
    "source_reconciliation": ("review_source_reconcile.py", []),
    "postgres_native_guard": ("review_postgres_native_guard.py", []),
    "postgres_launcher": ("review_postgres_launcher.py", []),
}


def block_external_io(event, args):
    # A Python-level guard, not an OS security sandbox. All tests are trusted
    # repository fixtures; unexpected browser launches or network calls fail.
    if event.startswith("socket.") or event in {
        "subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
        "os.startfile", "os.startfile/2",
    }:
        raise RuntimeError("OFFLINE_QA_EXTERNAL_IO_BLOCKED: " + event)


def run_child(name):
    filename, args = SUITES[name]
    if not __debug__:
        raise RuntimeError("ASSERTIONS_DISABLED")
    sys.addaudithook(block_external_io)
    sys.argv = [str(ROOT / filename), *args]
    runpy.run_path(str(ROOT / filename), run_name="__main__")
    return 0


def sanitized_env():
    # Retain OS and Python runtime requirements, not application credentials.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
               "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
               "SYSTEMDRIVE", "HOMEDRIVE", "HOMEPATH", "LANG", "LC_ALL", "TZ",
               "LD_LIBRARY_PATH"}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


def run_suite():
    results = []
    # Compile without creating .pyc or executing any project module.
    filenames = [filename for filename, _ in SUITES.values()] + ["scraper.py", "review_source_postgres_native_qa.py", Path(__file__).name]
    for filename in filenames:
        try:
            compile((ROOT / filename).read_bytes(), filename, "exec")
        except (OSError, SyntaxError) as exc:
            results.append({"stage": "compile", "file": filename, "status": "FAIL",
                            "error_type": type(exc).__name__})
    if results:
        return results
    results.append({"stage": "compile", "files": len(filenames), "status": "PASS"})
    for name in SUITES:
        try:
            completed = subprocess.run(
                [sys.executable, "-E", "-B", str(Path(__file__).resolve()), "--child", name],
                cwd=ROOT, env=sanitized_env(), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=90,
            )
            result = {"stage": name, "status": "PASS" if completed.returncode == 0 else "FAIL",
                      "exit_code": completed.returncode}
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"stage": name, "status": "FAIL", "error_type": type(exc).__name__}
        results.append(result)
        print("OFFLINE_QA_STAGE: " + json.dumps(result), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=tuple(SUITES), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return run_child(args.child)
    results = run_suite()
    passed = all(row["status"] == "PASS" for row in results) and len(results) == len(SUITES) + 1
    print("OFFLINE_QA_FINAL: " + json.dumps({
        "status": "OFFLINE_QA_PASSED" if passed else "OFFLINE_QA_FAILED",
        "results": results, "browser_tested": False, "database_tested": False,
        "database_writes": False, "production_ready": False,
    }), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
