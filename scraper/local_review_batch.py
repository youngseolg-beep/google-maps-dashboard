"""Sequential, read-only local review sample batch.

No production collection, database mutation, authentication workaround, or
review-content persistence. Explicitly configured active-store discovery uses
the existing GET-only audit client. An access restriction stops the batch.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import local_review_profile_probe as probe

SAMPLE_STATUS = {
    "fields": "FIELD_SAMPLE_VERIFIED",
    "adapter": "LOCAL_ADAPTER_SAMPLE_PASSED",
    "db": "LOCAL_DB_SAMPLE_COMPARED",
}


def canonical_place(url):
    """Require a full Maps place link with a stable place ID pair."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        path = unquote(parts.path).lower()
        if (parts.scheme != "https" or parts.hostname not in
                {"google.com", "www.google.com", "maps.google.com"}
                or parts.username or parts.password or parts.port is not None
                or not path.startswith("/maps/place/")):
            return None
        pairs = re.findall(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)(?=!|/|$)", path)
        return pairs[0] if len(set(pairs)) == 1 else None
    except ValueError:
        return None


def load_active_stores(config):
    """All caller-visible active stores; fail closed on pagination drift."""
    rows, seen, expected = [], set(), None
    while True:
        batch, total = probe.audit_db_get(config, "stores", {
            "select": "id,store_name,country,google_maps_url,is_active",
            "is_active": "eq.true", "order": "id.asc",
            "limit": "200", "offset": str(len(rows)),
        })
        if expected is None:
            expected = total
        if total != expected or not 0 <= total <= 2000:
            raise ValueError("ACTIVE_STORE_COUNT_CHANGED_OR_LIMIT")
        for row in batch:
            key = str(UUID(str(row.get("id"))))
            if key in seen or row.get("is_active") is not True:
                raise ValueError("ACTIVE_STORE_IDENTITY_CONFLICT")
            seen.add(key)
            rows.append(row)
        if len(rows) == expected:
            return rows
        if not batch or len(rows) > expected:
            raise ValueError("ACTIVE_STORE_LIST_INCOMPLETE")


def build_registered_plan(rows):
    """Hold short links and duplicate canonical place mappings for review."""
    pairs = [canonical_place(row.get("google_maps_url")) for row in rows]
    frequencies = Counter(pair for pair in pairs if pair)
    tasks = []
    for i, (row, pair) in enumerate(zip(rows, pairs), 1):
        name = str(row.get("store_name") or "").strip()
        country = str(row.get("country") or "").strip()
        reason = None
        if not name or not country:
            reason = "STORE_METADATA_MISSING"
        elif not pair:
            reason = "CANONICAL_PLACE_ID_NOT_VERIFIED"
        elif frequencies[pair] > 1:
            reason = "DUPLICATE_PLACE_MAPPING"
        tasks.append(dict(key="registered_" + str(i), name=name or "Unnamed store",
                          country=country, url=row.get("google_maps_url"),
                          pair=pair, hold_reason=reason))
    return tasks


def known_plan(keys):
    return [dict(key=key, name=probe.STORE_CONFIG[key]["name"],
                 country=key, url=probe.STORE_CONFIG[key]["url"],
                 pair=canonical_place(probe.STORE_CONFIG[key]["url"]),
                 hold_reason=None if canonical_place(probe.STORE_CONFIG[key]["url"])
                 else "CANONICAL_PLACE_ID_NOT_VERIFIED") for key in keys]


def safe_task_row(task):
    return {"store": task["name"], "country": task["country"]}


def classify(result, mode):
    if result.get("status") == SAMPLE_STATUS[mode]:
        return "SAMPLE_PASSED"
    if result.get("observed_unique", 0) > 0:
        return "PARTIAL_SAMPLE"
    return "FAILED"


def summarize(rows, requested):
    counts = Counter(row["outcome"] for row in rows)
    complete = len(rows) == requested
    return {"requested": requested, "recorded": len(rows),
            "sample_passed": counts["SAMPLE_PASSED"],
            "partial_sample": counts["PARTIAL_SAMPLE"],
            "failed": counts["FAILED"], "held": counts["HELD"],
            "not_attempted": counts["NOT_ATTEMPTED"] + requested - len(rows),
            "status": ("ALL_SAMPLES_PASSED" if complete and requested > 0
                       and counts["SAMPLE_PASSED"] == requested else "PARTIAL_OR_FAILED"),
            "database_writes": False, "production_collection": False,
            "full_coverage_verified": False, "write_approved": False}


def checkpoint(path, report):
    """Atomic aggregate-only local log; no source IDs, credentials or bodies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def run_batch(tasks, launch, mode, persist):
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "mode": mode, "stores": [], "database_writes": False,
              "full_coverage_verified": False, "write_approved": False}
    stopped = None
    for task in tasks:
        row = safe_task_row(task)
        if task["hold_reason"]:
            row.update(outcome="HELD", reason=task["hold_reason"])
        elif stopped:
            row.update(outcome="NOT_ATTEMPTED", reason=stopped)
        else:
            # Isolate each store in a fresh launch of the same dedicated
            # local profile. Do not run concurrent profile sessions.
            try:
                result, restriction = launch(task, mode)
                row.update(outcome=classify(result, mode),
                           status=result.get("status", "UNKNOWN"),
                           phase=result.get("phase"),
                           observed_unique=result.get("observed_unique", 0),
                           elapsed_seconds=result.get("elapsed_seconds"),
                           field_audit=result.get("field_audit"),
                           integration_sample=result.get("integration_sample"),
                           db_sample=result.get("db_sample"))
                if restriction or result.get("status") == "ACCESS_RESTRICTED_STOPPED":
                    row["outcome"] = "FAILED"
                    stopped = "ACCESS_RESTRICTED_STOPPED"
            except Exception as exc:
                row.update(outcome="FAILED", reason="BROWSER_OR_BATCH_ERROR",
                           error_type=type(exc).__name__)
                # Infrastructure/launch failure may affect every store.
                stopped = "BROWSER_OR_BATCH_ERROR"
        report["stores"].append(row)
        report["summary"] = summarize(report["stores"], len(tasks))
        report["stop_reason"] = stopped
        persist(report)
        print("LOCAL_BATCH_STORE: " + json.dumps(row, ensure_ascii=False), flush=True)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = summarize(report["stores"], len(tasks))
    persist(report)
    return report


def live_launcher(profile):
    from playwright.sync_api import sync_playwright

    def launch(task, mode):
        key = task["key"]
        # Preserve original verified configurations for the known two stores.
        # Registered entries are only used for field/adapter sampling.
        original = probe.STORE_CONFIG.get(key)
        if original is None:
            probe.STORE_CONFIG[key] = {"name": task["name"], "url": task["url"],
                                       "tokens": (task["pair"],)}
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],
                )
                try:
                    result = probe.run_once(
                        context, store_key=key, field_sample=mode == "fields",
                        adapter_sample=mode == "adapter", db_sample=mode == "db",
                    )
                    # Stop the entire batch if a challenge is visible even
                    # when the inner diagnostic returned a generic error.
                    restriction = result.get("status") == "ACCESS_RESTRICTED_STOPPED"
                    for page in context.pages:
                        if not page.is_closed() and probe.blocked(page):
                            restriction = True
                            break
                    return result, restriction
                finally:
                    context.close()
        finally:
            if original is None:
                probe.STORE_CONFIG.pop(key, None)

    return launch


def self_test():
    url = probe.PLACE_URL
    assert canonical_place(url)
    assert not canonical_place("https://maps.app.goo.gl/example")
    assert not canonical_place("https://example.com/maps/place/a/!1s0x1:0x2")
    assert not canonical_place("https://www.google.com/maps/search/a/!1s0x1:0x2")
    rows = [
        {"store_name": "A", "country": "T", "google_maps_url": url},
        {"store_name": "B", "country": "T", "google_maps_url": url},
        {"store_name": "C", "country": "T", "google_maps_url": "https://maps.app.goo.gl/x"},
        {"store_name": "D", "country": "T", "google_maps_url": probe.STORE_CONFIG["taiwan"]["url"]},
    ]
    tasks = build_registered_plan(rows)
    assert tasks[0]["hold_reason"] == tasks[1]["hold_reason"] == "DUPLICATE_PLACE_MAPPING"
    assert tasks[2]["hold_reason"] == "CANONICAL_PLACE_ID_NOT_VERIFIED"
    assert tasks[3]["hold_reason"] is None
    assert classify({"status": "FIELD_SAMPLE_VERIFIED"}, "fields") == "SAMPLE_PASSED"
    assert classify({"status": "PROBE_ERROR", "observed_unique": 8}, "fields") == "PARTIAL_SAMPLE"
    assert classify({"status": "PROBE_ERROR"}, "fields") == "FAILED"
    known = known_plan(["thailand", "taiwan"])
    calls = []
    def fake(task, mode):
        calls.append(task["key"])
        if len(calls) == 1:
            return {"status": "PROBE_ERROR", "observed_unique": 0}, False
        return {"status": "FIELD_SAMPLE_VERIFIED", "observed_unique": 8}, False
    report = run_batch(known, fake, "fields", lambda _: None)
    assert len(calls) == 2 and report["summary"]["failed"] == 1
    assert report["summary"]["sample_passed"] == 1
    calls.clear()
    def restricted(task, mode):
        calls.append(task["key"])
        return {"status": "ACCESS_RESTRICTED_STOPPED"}, True
    report = run_batch(known, restricted, "fields", lambda _: None)
    assert len(calls) == 1 and report["summary"]["not_attempted"] == 1
    assert report["summary"]["write_approved"] is False
    assert summarize([], 0)["status"] == "PARTIAL_OR_FAILED"
    print("BATCH_SELF_TEST_PASS: 15 checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("known", "registered"), default="known")
    parser.add_argument("--mode", choices=tuple(SAMPLE_STATUS), default="fields")
    parser.add_argument("--store", choices=("thailand", "taiwan"), action="append")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.scope == "registered" and (args.store or args.mode == "db"):
        parser.error("registered scope supports field/adapter samples only")
    try:
        if args.scope == "registered":
            tasks = build_registered_plan(load_active_stores(probe.read_only_db_config()))
        else:
            tasks = known_plan(list(dict.fromkeys(args.store or ["thailand", "taiwan"])))
            if args.mode == "db" and not args.plan_only:
                probe.read_only_db_config()
    except Exception as exc:
        print("LOCAL_BATCH_PREFLIGHT_FAILED: " + type(exc).__name__)
        return 2
    if args.plan_only:
        print("LOCAL_BATCH_PLAN: " + json.dumps({
            "scope": args.scope, "mode": args.mode, "requested": len(tasks),
            "history_visibility": "CALLER_VISIBLE_ONLY" if args.scope == "registered" else "NOT_READ",
            "stores": [dict(safe_task_row(t), hold_reason=t["hold_reason"]) for t in tasks],
            "database_writes": False, "write_approved": False,
        }, ensure_ascii=False))
        return 0
    if os.name != "nt":
        print("WINDOWS_ONLY")
        return 2
    root = Path(os.environ["LOCALAPPDATA"]) / "SVReviewMaster"
    profile = root / "GoogleMapsSortProfile"
    if not (profile / "Default" / "Network" / "Cookies").is_file():
        print("DEDICATED_PROFILE_NOT_FOUND")
        return 2
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    # Windows releases the OS file lock on termination, avoiding stale locks.
    with (root / "local-review-batch.lock").open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("LOCAL_BATCH_ALREADY_RUNNING")
            return 2
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = root / "reports" / ("sample-" + stamp + "-" + uuid4().hex[:8] + ".json")
            report = run_batch(tasks, live_launcher(profile), args.mode,
                               lambda data: checkpoint(path, data))
            print("LOCAL_BATCH_FINAL: " + json.dumps(report["summary"], ensure_ascii=False))
            print("LOCAL_BATCH_REPORT: " + str(path))
            return 0 if report["summary"]["status"] == "ALL_SAMPLES_PASSED" else 2
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    sys.exit(main())
