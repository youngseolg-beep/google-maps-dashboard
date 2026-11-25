"""Sequential, read-only local review sample batch.

No production collection, database mutation, authentication workaround, or
review-content persistence. Explicitly configured active-store discovery uses
the existing GET-only audit client. An access restriction stops the batch.
"""
import argparse
import hashlib
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
    "body": "BODY_SAMPLE_CONTROLS_VERIFIED",
    "db": "LOCAL_DB_SAMPLE_COMPARED",
    "count": "EXPECTED_COUNT_MATCHED",
    "count-db": "LOCAL_COUNT_DB_COMPARED",
    "count-body-db": "LOCAL_COUNT_BODY_DB_COMPARED",
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
    names = Counter(str(row.get("store_name") or "").strip().casefold() for row in rows)
    tasks = []
    for i, (row, pair) in enumerate(zip(rows, pairs), 1):
        name = str(row.get("store_name") or "").strip()
        country = str(row.get("country") or "").strip()
        reason = None
        try:
            store_id = str(UUID(str(row.get("id"))))
        except (ValueError, TypeError, AttributeError):
            store_id = None
        if not name or not country or not store_id:
            reason = "STORE_METADATA_MISSING"
        elif not pair:
            raw_url = row.get("google_maps_url")
            try:
                is_short = isinstance(raw_url, str) and urlsplit(raw_url).hostname == "maps.app.goo.gl"
            except ValueError:
                is_short = False
            reason = "SHORT_LINK_REQUIRES_VERIFIED_CANONICAL_URL" if is_short else "CANONICAL_PLACE_ID_NOT_VERIFIED"
        elif frequencies[pair] > 1:
            reason = "DUPLICATE_PLACE_MAPPING"
        elif names[name.casefold()] > 1:
            reason = "LEGACY_STORE_NAME_COLLISION"
        key = "registered_" + (hashlib.sha256(store_id.encode()).hexdigest()[:24] if store_id else "invalid_" + str(i))
        tasks.append(dict(key=key, name=name or "Unnamed store",
                          country=country, url=row.get("google_maps_url"),
                          pair=pair, store_id=store_id, hold_reason=reason))
    return tasks


def known_plan(keys):
    return [dict(key=key, name=probe.STORE_CONFIG[key]["name"],
                 country=key, url=probe.STORE_CONFIG[key]["url"],
                 pair=canonical_place(probe.STORE_CONFIG[key]["url"]),
                 hold_reason=None if canonical_place(probe.STORE_CONFIG[key]["url"])
                 else "CANONICAL_PLACE_ID_NOT_VERIFIED") for key in keys]


def safe_task_row(task):
    return {"store": task["name"], "country": task["country"],
            "task_key": task["key"]}


def classify(result, mode):
    if result.get("status") == SAMPLE_STATUS[mode]:
        return "COUNT_DB_COMPARED" if mode in {"count-db", "count-body-db"} else ("COUNT_MATCHED" if mode == "count" else "SAMPLE_PASSED")
    if result.get("observed_unique", 0) > 0:
        return "PARTIAL_SAMPLE"
    return "FAILED"


def summarize(rows, requested, mode="fields"):
    counts = Counter(row["outcome"] for row in rows)
    complete = len(rows) == requested
    return {"requested": requested, "recorded": len(rows),
            "sample_passed": counts["SAMPLE_PASSED"],
            "count_matched": counts["COUNT_MATCHED"],
            "count_db_compared": counts["COUNT_DB_COMPARED"],
            "partial_sample": counts["PARTIAL_SAMPLE"],
            "failed": counts["FAILED"], "held": counts["HELD"],
            "not_attempted": counts["NOT_ATTEMPTED"] + requested - len(rows),
            "status": (
                "ALL_COUNT_DB_COMPARED" if mode in {"count-db", "count-body-db"} and complete
                and requested > 0 and counts["COUNT_DB_COMPARED"] == requested else
                "ALL_EXPECTED_COUNTS_MATCHED" if mode == "count" and complete
                and requested > 0 and counts["COUNT_MATCHED"] == requested else
                "ALL_SAMPLES_PASSED" if mode not in {"count", "count-db", "count-body-db"} and complete
                and requested > 0 and counts["SAMPLE_PASSED"] == requested else
                "PARTIAL_OR_FAILED"
            ),
            "database_writes": False, "production_collection": False,
            "full_coverage_verified": False, "write_approved": False}


def retry_plan(rows):
    """Manual fresh-run recommendations only. No saved review IDs or resume cursor."""
    plan = []
    for row in rows:
        outcome = row["outcome"]
        if outcome in {"SAMPLE_PASSED", "COUNT_MATCHED", "COUNT_DB_COMPARED"}:
            continue
        if row.get("status") == "ACCESS_RESTRICTED_STOPPED" or row.get("reason") == "ACCESS_RESTRICTED_STOPPED":
            action = "STOP_AND_REVIEW_ACCESS"
        elif row.get("status") == "REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED" or row.get("reason") == "REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED":
            action = "VERIFY_ENGLISH_DISPLAY_BEFORE_FRESH_RUN"
        elif row.get("reason") == "FRESH_COUNT_TARGET_REQUIRED":
            action = "OBSERVE_FRESH_DISPLAYED_TOTAL"
        elif row.get("status") in {"DISPLAYED_TOTAL_NOT_VERIFIED_OR_OUT_OF_SCOPE", "OVERVIEW_NOT_VERIFIED"}:
            action = "OBSERVE_FRESH_DISPLAYED_TOTAL"
        elif outcome == "HELD":
            action = "VERIFY_STORE_MAPPING"
        elif row.get("status") == "EXPECTED_COUNT_EXCEEDED_RECHECK_TOTAL":
            action = "RECHECK_DISPLAYED_TOTAL"
        elif row.get("status") == "COUNT_MATCHED_FIELD_GAPS":
            action = "REVIEW_FIELD_EXTRACTION"
        else:
            action = "REVIEW_FAILURE_BEFORE_FRESH_RUN"
        plan.append({"task_key": row["task_key"], "store": row["store"],
                     "outcome": outcome, "action": action,
                     "automatic_retry": False, "resume_cursor_available": False})
    return plan


def count_targets(values, keys):
    targets = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or key not in keys or key in targets:
            raise ValueError("INVALID_OR_DUPLICATE_COUNT_TARGET")
        number = int(value)
        if not 1 <= number <= probe.MAX_EXPECTED_COUNT:
            raise ValueError("COUNT_TARGET_OUT_OF_SCOPE")
        targets[key] = number
    if set(targets) != set(keys):
        raise ValueError("COUNT_TARGET_REQUIRED_FOR_EACH_STORE")
    return targets


def registered_count_plan(tasks, values):
    """Bind explicit operator-observed totals to stable registered task keys.

    Missing counts are held, not silently skipped or inferred from history.
    A target for a held mapping is rejected. Preserve all registered stores in
    the report so an eligible subset cannot look like complete store coverage.
    """
    by_key = {t["key"]: t for t in tasks}
    if len(by_key) != len(tasks):
        raise ValueError("REGISTERED_TASK_KEY_CONFLICT")
    targets = {}
    for value in values:
        key, sep, count = value.partition("=")
        if not sep or key not in by_key or key in targets or by_key[key]["hold_reason"]:
            raise ValueError("REGISTERED_COUNT_TARGET_INVALID")
        if not re.fullmatch(r"[0-9]{1,5}", count):
            raise ValueError("REGISTERED_COUNT_TARGET_INVALID")
        number = int(count)
        if not 1 <= number <= probe.MAX_EXPECTED_COUNT:
            raise ValueError("COUNT_TARGET_OUT_OF_SCOPE")
        targets[key] = number
    return [dict(t, expected_total=targets.get(t["key"]),
                 hold_reason=t["hold_reason"] or
                 (None if t["key"] in targets else "FRESH_COUNT_TARGET_REQUIRED"))
            for t in tasks]


def checkpoint(path, report):
    """Atomic aggregate-only local log; no source IDs, credentials or bodies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def run_batch(tasks, launch, mode, persist, *, maps_language="profile"):
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "mode": mode, "maps_language_requested": maps_language,
              "stores": [], "database_writes": False,
              "full_coverage_verified": False, "write_approved": False}
    stopped = None
    report.update(run_state="RUNNING", active_store=None,
                  planned_stores=[safe_task_row(t) for t in tasks],
                  summary=summarize([], len(tasks), mode),
                  stop_reason=None, manual_retry_plan=[])
    persist(report)
    for task in tasks:
        row = safe_task_row(task)
        report["active_store"] = dict(row)
        persist(report)
        if task["hold_reason"]:
            row.update(outcome="HELD", reason=task["hold_reason"], expected_total=task.get("expected_total"))
        elif stopped:
            row.update(outcome="NOT_ATTEMPTED", reason=stopped)
        else:
            # Isolate each store in a fresh launch of the same dedicated
            # local profile. Do not run concurrent profile sessions.
            try:
                result, restriction = launch(task, mode)
                if maps_language == "en" and result.get("maps_ui_language") != "ENGLISH" and not restriction and result.get("status") not in {"ACCESS_RESTRICTED_STOPPED", "PLACE_NOT_VERIFIED"}:
                    result = dict(result, status="REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED")
                row.update(outcome=classify(result, mode),
                           maps_ui_language=result.get("maps_ui_language", "UNVERIFIED"),
                           status=result.get("status", "UNKNOWN"),
                           phase=result.get("phase"),
                           observed_unique=result.get("observed_unique", 0),
                           elapsed_seconds=result.get("elapsed_seconds"),
                           expected_total=result.get("expected_total_user_observed"),
                           expected_total_source=result.get("expected_total_source"),
                           count_round_limit=result.get("count_round_limit"),
                           count_second_limit=result.get("count_second_limit"),
                           elapsed_scroll_seconds=result.get("elapsed_scroll_seconds"),
                           scroll_rounds=result.get("scroll_rounds"),
                           overview_total=result.get("overview_total"),
                           overview_total_recheck=result.get("overview_total_recheck"),
                           stop_reason=result.get("stop_reason"),
                           count_gap=result.get("count_gap"),
                           field_audit=result.get("field_audit"),
                           integration_sample=result.get("integration_sample"),
                           body_sample=result.get("body_sample"),
                           count_body_evidence=result.get("count_body_evidence"),
                           db_sample=result.get("db_sample"))
                if result.get("status") in {"DISPLAYED_TOTAL_NOT_VERIFIED_OR_OUT_OF_SCOPE", "OVERVIEW_NOT_VERIFIED"}:
                    row["outcome"] = "HELD"
                if restriction or result.get("status") == "ACCESS_RESTRICTED_STOPPED":
                    row["outcome"] = "FAILED"
                    stopped = "ACCESS_RESTRICTED_STOPPED"
                elif result.get("status") == "REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED":
                    row["outcome"] = "FAILED"
                    stopped = "REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED"
            except Exception as exc:
                row.update(outcome="FAILED", reason="BROWSER_OR_BATCH_ERROR",
                           error_type=type(exc).__name__)
                # Infrastructure/launch failure may affect every store.
                stopped = "BROWSER_OR_BATCH_ERROR"
        report["stores"].append(row)
        report["active_store"] = None
        report["summary"] = summarize(report["stores"], len(tasks), mode)
        report["stop_reason"] = stopped
        report["manual_retry_plan"] = retry_plan(report["stores"])
        persist(report)
        print("LOCAL_BATCH_STORE: " + json.dumps(row, ensure_ascii=False), flush=True)
    report["run_state"] = "FINISHED"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = summarize(report["stores"], len(tasks), mode)
    persist(report)
    return report


def live_launcher(profile, count_round_limit=240, count_second_limit=600, *, maps_language="profile", scale_count_budget=False):
    from playwright.sync_api import sync_playwright

    def launch(task, mode):
        key = task["key"]
        # Preserve original verified configurations for the known two stores.
        # Registered entries support bounded field, body, adapter and DB samples.
        original = probe.STORE_CONFIG.get(key)
        if original is None:
            probe.STORE_CONFIG[key] = {"name": task["name"], "url": task["url"],
                                       "tokens": (task["pair"],),
                                       "registered_store": {"id": task["store_id"],
                                                            "name": task["name"],
                                                            "country": task["country"]}}
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],
                    **({"locale": "en-US"} if maps_language == "en" else {}),
                )
                try:
                    result = probe.run_once(
                        context, store_key=key, field_sample=mode == "fields",
                        adapter_sample=mode == "adapter", db_sample=mode == "db",
                        body_sample=mode == "body",
                        expected_total=task.get("expected_total") if mode in {"count", "count-db", "count-body-db"} else None,
                        auto_total=mode == "count" and task.get("auto_total") is True,
                        scroll_mode="adaptive" if mode in {"count", "count-db", "count-body-db"} else "baseline",
                        audit_fields=mode in {"count", "count-db", "count-body-db"},
                        count_db_audit=mode in {"count-db", "count-body-db"},
                        count_body_audit=mode == "count-body-db",
                        count_round_limit=count_round_limit, count_second_limit=count_second_limit,
                        maps_language=maps_language, scale_count_budget=scale_count_budget,
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
    for i, row in enumerate(rows, 1):
        row["id"] = str(UUID(int=i))
    tasks = build_registered_plan(rows)
    assert tasks[0]["hold_reason"] == tasks[1]["hold_reason"] == "DUPLICATE_PLACE_MAPPING"
    assert tasks[2]["hold_reason"] == "SHORT_LINK_REQUIRES_VERIFIED_CANONICAL_URL"
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
    assert classify({"status": "EXPECTED_COUNT_MATCHED"}, "count") == "COUNT_MATCHED"
    assert classify({"status": "COUNT_MATCHED_FIELD_GAPS", "observed_unique": 167}, "count") == "PARTIAL_SAMPLE"
    assert count_targets(["thailand=167", "taiwan=6332"], ["thailand", "taiwan"]) == {"thailand": 167, "taiwan": 6332}
    assert retry_plan([dict(task_key="a", store="A", outcome="COUNT_MATCHED")]) == []
    assert retry_plan([dict(task_key="b", store="B", outcome="FAILED", status="ACCESS_RESTRICTED_STOPPED")])[0]["action"] == "STOP_AND_REVIEW_ACCESS"
    assert summarize([{"outcome":"COUNT_MATCHED"}], 1, "count")["status"] == "ALL_EXPECTED_COUNTS_MATCHED"
    assert classify({"status": "LOCAL_COUNT_DB_COMPARED"}, "count-db") == "COUNT_DB_COMPARED"
    assert summarize([{"outcome":"COUNT_DB_COMPARED"}], 1, "count-db")["status"] == "ALL_COUNT_DB_COMPARED"
    assert tasks[3]["key"] == build_registered_plan(list(reversed(rows)))[0]["key"]
    assert classify({"status": "BODY_SAMPLE_CONTROLS_VERIFIED"}, "body") == "SAMPLE_PASSED"
    assert classify({"status": "LOCAL_COUNT_BODY_DB_COMPARED"}, "count-body-db") == "COUNT_DB_COMPARED"
    assert classify({"status": "LOCAL_COUNT_BODY_DB_EVIDENCE_LIMITED", "observed_unique": 167}, "count-body-db") == "PARTIAL_SAMPLE"
    from copy import deepcopy
    snapshots = []
    def interrupted(task, mode):
        raise KeyboardInterrupt()
    try:
        run_batch(known, interrupted, "fields", lambda value: snapshots.append(deepcopy(value)))
    except KeyboardInterrupt:
        pass
    assert snapshots[0]["run_state"] == "RUNNING"
    assert snapshots[0]["active_store"] is None
    assert snapshots[-1]["active_store"]["task_key"] == known[0]["key"]
    assert snapshots[-1]["summary"]["not_attempted"] == 2
    assert "finished_at" not in snapshots[-1]
    assert report["run_state"] == "FINISHED"
    calls.clear()
    def wrong_language(task, mode):
        calls.append(task["key"])
        return {"status":"FIELD_SAMPLE_VERIFIED", "observed_unique":8, "maps_ui_language":"KOREAN"}, False
    report = run_batch(known, wrong_language, "fields", lambda _: None, maps_language="en")
    assert len(calls) == 1
    assert report["maps_language_requested"] == "en"
    assert report["stores"][0]["maps_ui_language"] == "KOREAN"
    assert report["stores"][0]["status"] == "REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED"
    assert report["summary"]["failed"] == 1 and report["summary"]["not_attempted"] == 1
    assert report["manual_retry_plan"][0]["action"] == "VERIFY_ENGLISH_DISPLAY_BEFORE_FRESH_RUN"
    report = run_batch(known, lambda t,m: ({"status":"FIELD_SAMPLE_VERIFIED","observed_unique":8,"maps_ui_language":"ENGLISH"},False),
                       "fields", lambda _: None, maps_language="en")
    assert report["summary"]["sample_passed"] == 2
    assert report["summary"]["write_approved"] is False
    plan = registered_count_plan(tasks, [])
    assert len(plan) == len(tasks)
    assert plan[3]["hold_reason"] == "FRESH_COUNT_TARGET_REQUIRED"
    assert plan[0]["hold_reason"] == "DUPLICATE_PLACE_MAPPING"
    key = tasks[3]["key"]
    plan = registered_count_plan(tasks, [key+"=167"])
    assert plan[3]["expected_total"] == 167 and plan[3]["hold_reason"] is None
    assert tasks[3].get("expected_total") is None
    for invalid in (["unknown=5"], [key+"=0"], [key+"=10001"], [key+"=5",key+"=6"], [tasks[0]["key"]+"=5"], [key+"=+5"]):
        try:
            registered_count_plan(tasks, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("INVALID_REGISTERED_TARGET_ACCEPTED")
    def counted(task, mode):
        assert task["key"] == key and task["expected_total"] == 167
        return {"status":"EXPECTED_COUNT_MATCHED","observed_unique":167,"maps_ui_language":"ENGLISH"}, False
    report = run_batch(plan, counted, "count", lambda _: None, maps_language="en")
    assert report["summary"]["count_matched"] == 1
    assert report["summary"]["held"] == 3 and report["summary"]["status"] == "PARTIAL_OR_FAILED"
    assert retry_plan([dict(task_key=key,store="D",outcome="HELD",reason="FRESH_COUNT_TARGET_REQUIRED")])[0]["action"] == "OBSERVE_FRESH_DISPLAYED_TOTAL"
    auto = [dict(t, auto_total=True) for t in known]
    def auto_result(task, mode):
        assert task["auto_total"] and task.get("expected_total") is None
        return ({"status":"DISPLAYED_TOTAL_NOT_VERIFIED_OR_OUT_OF_SCOPE","maps_ui_language":"ENGLISH"},False) if task["key"] == "thailand" else ({"status":"EXPECTED_COUNT_MATCHED","observed_unique":167,"expected_total_user_observed":167,"expected_total_source":"overview_rating_summary_rechecked","maps_ui_language":"ENGLISH"},False)
    report = run_batch(auto, auto_result, "count", lambda _: None, maps_language="en")
    assert report["summary"]["held"] == 1 and report["summary"]["count_matched"] == 1
    assert report["manual_retry_plan"][0]["action"] == "OBSERVE_FRESH_DISPLAYED_TOTAL"
    assert report["stores"][1]["expected_total_source"] == "overview_rating_summary_rechecked"
    print("BATCH_SELF_TEST_PASS: language, registered count and auto-total gates")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("known", "registered"), default="known")
    parser.add_argument("--mode", choices=tuple(SAMPLE_STATUS), default="fields")
    parser.add_argument("--maps-language", choices=("en", "profile"), default="en",
                        help="English display required by default; profile is a diagnostic opt-out.")
    parser.add_argument("--store", choices=("thailand", "taiwan"), action="append")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--auto-total", action="store_true", help="Read and recheck the Overview total for each count-only store.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected", action="append", default=[],
                        metavar="STORE=COUNT", help="Fresh observed total keyed by known store or registered task key.")
    parser.add_argument("--scale-count-budget", action="store_true", help="Opt into bounded size-based count-only scroll budgets.")
    parser.add_argument("--count-round-limit", type=int, default=240)
    parser.add_argument("--count-second-limit", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.count_round_limit <= probe.MAX_COUNT_ROUNDS or not 1 <= args.count_second_limit <= probe.MAX_COUNT_SECONDS:
        parser.error("count budget outside diagnostic limits")
    if args.scale_count_budget and args.mode != "count":
        parser.error("--scale-count-budget requires count-only mode")
    if args.auto_total and (args.mode != "count" or args.expected or args.maps_language != "en"):
        parser.error("--auto-total requires count mode, English display, and no manual totals")
    if args.expected and args.mode not in {"count", "count-db", "count-body-db"}:
        parser.error("--expected is only for count mode")
    if args.self_test:
        self_test()
        return 0
    if args.scope == "registered" and (args.store or args.mode in {"count-db", "count-body-db"}):
        parser.error("registered scope supports count-only and existing sample modes; full DB audit remains limited to known stores")
    try:
        if args.scope == "registered":
            tasks = build_registered_plan(load_active_stores(probe.read_only_db_config()))
            if args.mode == "count":
                tasks = [dict(t, auto_total=True) for t in tasks] if args.auto_total else registered_count_plan(tasks, args.expected)
                if not args.plan_only and not any(not t["hold_reason"] for t in tasks):
                    raise ValueError("NO_REGISTERED_COUNT_TARGET_READY")
        else:
            tasks = known_plan(list(dict.fromkeys(args.store or ["thailand", "taiwan"])))
            if args.mode in {"db", "count-db", "count-body-db"} and not args.plan_only:
                probe.read_only_db_config()
            if args.auto_total:
                tasks = [dict(t, auto_total=True) for t in tasks]
            elif args.mode in {"count", "count-db", "count-body-db"}:
                targets = count_targets(args.expected, [t["key"] for t in tasks])
                if args.mode in {"count-db", "count-body-db"} and any(n > (probe.MAX_COUNT_BODY_AUDIT if args.mode == "count-body-db" else probe.MAX_COUNT_DB_AUDIT) for n in targets.values()):
                    raise ValueError("COUNT_DB_AUDIT_PILOT_LIMIT")
                for task in tasks:
                    task["expected_total"] = targets[task["key"]]
    except Exception as exc:
        print("LOCAL_BATCH_PREFLIGHT_FAILED: " + type(exc).__name__)
        return 2
    if args.plan_only:
        print("LOCAL_BATCH_PLAN: " + json.dumps({
            "scope": args.scope, "mode": args.mode, "requested": len(tasks),
            "maps_language_requested": args.maps_language,
            "automatic_total_requested": args.auto_total,
            "scale_count_budget_requested": args.scale_count_budget,
            "history_visibility": "CALLER_VISIBLE_ONLY" if args.scope == "registered" else "NOT_READ",
            "stores": [dict(safe_task_row(t), hold_reason=t["hold_reason"], expected_total=t.get("expected_total")) for t in tasks],
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
            report = run_batch(tasks, live_launcher(profile, args.count_round_limit, args.count_second_limit,
                                                     maps_language=args.maps_language, scale_count_budget=args.scale_count_budget), args.mode,
                               lambda data: checkpoint(path, data), maps_language=args.maps_language)
            print("LOCAL_BATCH_FINAL: " + json.dumps(report["summary"], ensure_ascii=False))
            print("LOCAL_BATCH_REPORT: " + str(path))
            return 0 if report["summary"]["status"] in {"ALL_SAMPLES_PASSED", "ALL_EXPECTED_COUNTS_MATCHED", "ALL_COUNT_DB_COMPARED"} else 2
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    sys.exit(main())
