"""Read-only diagnostic report health; never authorize production collection."""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SUCCESS = {"fields": ("ALL_SAMPLES_PASSED", "sample_passed"),
           "adapter": ("ALL_SAMPLES_PASSED", "sample_passed"),
           "body": ("ALL_SAMPLES_PASSED", "sample_passed"),
           "db": ("ALL_SAMPLES_PASSED", "sample_passed"),
           "count": ("ALL_EXPECTED_COUNTS_MATCHED", "count_matched"),
           "count-db": ("ALL_COUNT_DB_COMPARED", "count_db_compared"),
           "count-body-db": ("ALL_COUNT_DB_COMPARED", "count_db_compared")}


def timestamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return stamp


def classify(report):
    if report.get("database_writes") is not False or report.get("write_approved") is not False:
        return "INVALID_REPORT"
    if report.get("run_state") == "RUNNING":
        return "RUNNING_OR_INTERRUPTED"
    if report.get("run_state") != "FINISHED":
        return "LEGACY_OR_UNVERIFIED_REPORT"
    mode = report.get("mode")
    if mode not in SUCCESS:
        return "INVALID_REPORT"
    summary = report.get("summary")
    rows = report.get("stores")
    if not isinstance(summary, dict) or not isinstance(rows, list):
        return "INVALID_REPORT"
    requested = summary.get("requested")
    if (type(requested) is not int or requested <= 0 or len(rows) != requested
            or summary.get("recorded") != requested or report.get("active_store") is not None):
        return "INVALID_REPORT"
    status, field = SUCCESS[mode]
    expected_outcome = {"sample_passed": "SAMPLE_PASSED", "count_matched": "COUNT_MATCHED",
                        "count_db_compared": "COUNT_DB_COMPARED"}[field]
    if (summary.get("status") == status and summary.get(field) == requested
            and all(isinstance(row, dict) and row.get("outcome") == expected_outcome for row in rows)
            and all(summary.get(k) == 0 for k in ("partial_sample", "failed", "held", "not_attempted"))
            and not report.get("stop_reason")):
        return "DIAGNOSTIC_PASSED"
    return "DIAGNOSTIC_NOT_PASSED"


def health(reports, now):
    results, invalid = [], 0
    for report in reports:
        try:
            started = timestamp(report["started_at"])
            verdict = classify(report)
            ended = timestamp(report["finished_at"]) if report.get("run_state") == "FINISHED" else None
            if started > now or (ended is not None and not started <= ended <= now):
                raise ValueError("INVALID_TIME_ORDER")
            if verdict == "INVALID_REPORT":
                invalid += 1
            results.append((started, verdict, ended, report.get("mode")))
        except (KeyError, TypeError, ValueError, AttributeError):
            invalid += 1
    results.sort(key=lambda item: item[0], reverse=True)
    latest = results[0] if results else None
    last_pass = {}
    for _, verdict, ended, mode in results:
        if verdict == "DIAGNOSTIC_PASSED" and mode not in last_pass:
            last_pass[mode] = ended.astimezone(KST).isoformat()
    current = latest[1] if latest else "NO_REPORTS"
    if invalid:
        current = "REPORT_REVIEW_REQUIRED"
    elif latest and latest[1] == "DIAGNOSTIC_PASSED" and latest[2].astimezone(KST).date() != now.astimezone(KST).date():
        current = "NO_SUCCESSFUL_DIAGNOSTIC_TODAY"
    return {"status": current, "latest_mode": latest[3] if latest else None,
            "latest_started_kst": latest[0].astimezone(KST).isoformat() if latest else None,
            "latest_result": latest[1] if latest else None,
            "last_diagnostic_pass_by_mode_kst": last_pass, "invalid_reports": invalid,
            "production_ready": False, "database_writes": False, "automatic_retry": False}


def self_test():
    now = timestamp("2026-11-25T09:00:00+09:00")
    sample = dict(run_state="FINISHED", mode="fields", database_writes=False,
                  write_approved=False, started_at="2026-11-25T08:00:00+09:00",
                  finished_at="2026-11-25T08:01:00+09:00", active_store=None,
                  stores=[{"outcome": "SAMPLE_PASSED"}],
                  summary=dict(requested=1, recorded=1, sample_passed=1,
                               status="ALL_SAMPLES_PASSED", partial_sample=0, failed=0, held=0, not_attempted=0))
    assert health([sample], now)["status"] == "DIAGNOSTIC_PASSED"
    assert health([], now)["status"] == "NO_REPORTS"
    old = dict(sample, started_at="2026-11-24T08:00:00+09:00", finished_at="2026-11-24T08:01:00+09:00")
    assert health([old], now)["status"] == "NO_SUCCESSFUL_DIAGNOSTIC_TODAY"
    interrupted = dict(sample, run_state="RUNNING", started_at="2026-11-25T08:30:00+09:00")
    assert health([sample, interrupted], now)["status"] == "RUNNING_OR_INTERRUPTED"
    failed = dict(sample, started_at="2026-11-25T08:30:00+09:00", finished_at="2026-11-25T08:31:00+09:00", stores=[{"outcome": "FAILED"}])
    assert health([sample, failed], now)["status"] == "DIAGNOSTIC_NOT_PASSED"
    assert health([sample, failed], now)["last_diagnostic_pass_by_mode_kst"]["fields"] == sample["finished_at"]
    assert health([sample, {}], now)["status"] == "REPORT_REVIEW_REQUIRED"
    assert health([dict(sample, database_writes=True)], now)["status"] == "REPORT_REVIEW_REQUIRED"
    assert health([dict(sample, finished_at="2026-11-25T10:00:00+09:00")], now)["invalid_reports"] == 1
    assert health([sample], now)["production_ready"] is False
    assert health([dict(sample, active_store={"store": "fixture"})], now)["status"] == "REPORT_REVIEW_REQUIRED"
    print("LOCAL_REVIEW_HEALTH_SELF_TEST_PASS: 11 checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        print("LOCALAPPDATA_REQUIRED")
        return 2
    reports = []
    for path in (Path(root) / "SVReviewMaster" / "reports").glob("sample-*.json"):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValueError):
            reports.append({})
    result = health(reports, datetime.now(timezone.utc))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "DIAGNOSTIC_PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
