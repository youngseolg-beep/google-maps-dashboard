"""Registered-store Windows review append batch using the proven pilot writer.

Default dry-run. With --commit, inserts only verified new reviews and reconciles
each store before continuing. No cookie export, secret files, schema changes,
or historical edits. Run on the dedicated signed-in PC only.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import local_review_profile_probe as probe
import local_review_batch as discovery
import local_review_append_pilot as pilot
import scraper as production


def select_for_body(records, history):
    """Prioritize new unique authors, not already stored or ambiguous reviews."""
    def name(row):
        return production.normalize_spaces(row.get("author") or "").casefold()
    existing = {name(r) for r in history.values()}
    frequencies = Counter(name(r) for r in records)
    today = production.now_kst().date()
    eligible = [r for r in records if name(r) and name(r) not in
                {"anonymous", "unknown"} and name(r) not in existing
                and frequencies[name(r)] == 1 and type(r.get("rating")) is int
                and 1 <= r["rating"] <= 5 and
                probe.local_date_value(r.get("date_label"), today, production)[0]
                and isinstance(r.get("source_id"), str) and r["source_id"]]
    # Prioritize visible customer text. A blank body is NOT rating-only proof.
    eligible.sort(key=lambda r: r.get("body_scope") != "PRIMARY" or not r.get("body"))
    return {r["source_id"] for r in eligible[:probe.MAX_COUNT_BODY_AUDIT]}, len(eligible)


def run_store(context, config, task, commit, run_id):
    key = task["key"]
    if key in probe.STORE_CONFIG:
        raise ValueError("BATCH_STORE_KEY_COLLISION")
    probe.STORE_CONFIG[key] = {"name":task["name"], "url":task["url"],
                               "tokens":(task["pair"],),
                               "registered_store":{"id":task["store_id"],"name":task["name"],
                                                   "country":task["country"]}}
    try:
        store = probe.verified_db_store(config, key)
        before = pilot.history_snapshot(config, store)
        captured = []
        selection = {}
        def select(records):
            chosen, count = select_for_body(records, before)
            selection.update(candidate_count=count, selected_count=len(chosen))
            return chosen
        def receive(records, evidence):
            if captured:
                raise ValueError("BATCH_MULTIPLE_CAPTURES")
            captured.append((records, evidence))
        report = probe.run_once(context, store_key=key, auto_total=True,
                                scroll_mode="adaptive", maps_language="en",
                                count_body_audit=True, scale_count_budget=True,
                                capture_sink=receive, capture_select=select)
        restricted = report.get("status") == "ACCESS_RESTRICTED_STOPPED"
        for page in context.pages:
            if not page.is_closed() and probe.blocked(page):
                restricted = True
                break
        observed = report.get("observed_unique", 0)
        total = report.get("expected_total_user_observed")
        if (restricted or not captured or len(captured) != 1 or
                type(total) is not int or total < 1 or observed != total or
                report.get("status") not in {"LOCAL_COUNT_BODY_CONTROLS_CHECKED",
                    "LOCAL_COUNT_BODY_CONTROL_GAPS", "LOCAL_COUNT_BODY_EVIDENCE_LIMITED"}):
            return dict(status="ACCESS_RESTRICTED_STOPPED" if restricted else report.get("status","CAPTURE_HELD"),
                        observed=observed, expected=total, confirmed_new=0, database_writes=False)
        fresh = pilot.history_snapshot(config, store)
        if fresh != before:
            return dict(status="HISTORY_CHANGED_HELD", observed=observed,
                        expected=total, confirmed_new=0, database_writes=False)
        plan, rows = pilot.plan_rows(store, fresh, *captured[0])
        captured.clear()
        if run_id is not None:
            for row in rows:
                row["first_seen_run_id"] = run_id
        outcome = pilot.execute_append(config, store, fresh, rows, commit=commit)
        return dict(plan, **outcome, **selection, expected=total,
                    selection_backlog=selection["candidate_count"]-selection["selected_count"])
    finally:
        probe.STORE_CONFIG.pop(key, None)


def status_for_run(task, result):
    status = result["status"]
    ok = status in {"APPEND_CONFIRMED", "NO_READY_ROWS"}
    attempted = status not in {"NOT_ATTEMPTED", "MAPPING_HELD"}
    observed = result.get("observed", 0)
    return dict(store_name=task["name"], country=task["country"], sv=task.get("sv",""),
                ok=ok if attempted else (False if status=="MAPPING_HELD" else None),
                collected_count=result.get("confirmed_new", 0),
                observed_review_count=observed, error="" if ok else status,
                crawled_at=production.now_kst().strftime("%Y-%m-%d %H:%M:%S") if attempted else None,
                collection_status="PARTIAL" if observed else ("FAILED" if attempted else "NOT_CHECKED"),
                collection_reason=status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--country", action="append", help="Optional registered country filter")
    parser.add_argument("--limit", type=int, help="Optional number of eligible stores")
    parser.add_argument("--skip-store", action="append", default=[])
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and not 1 <= args.limit <= 2000:
        parser.error("invalid limit")
    if os.name != "nt":
        print("WINDOWS_ONLY")
        return 2
    if args.commit and os.environ.get("SV_REVIEW_PILOT_EXCLUSIVE") != "1":
        print("PILOT_EXCLUSIVE_WINDOW_REQUIRED")
        return 2
    config = pilot.backend_config(args.target_url)
    rows = discovery.load_active_stores(config)
    tasks = discovery.build_registered_plan(rows)
    # Stable country/name order; immutable place and store ID checks remain.
    tasks.sort(key=lambda t:(t["country"],t["name"],t["key"]))
    countries = set(args.country or [])
    if countries - {t["country"] for t in tasks}:
        raise ValueError("BATCH_UNKNOWN_COUNTRY")
    tasks = [t for t in tasks if (not countries or t["country"] in countries)
             and t["name"] not in args.skip_store]
    if args.limit is not None:
        tasks = [t for t in tasks if not t["hold_reason"]][:args.limit]
    if not tasks:
        raise ValueError("BATCH_NO_STORES")
    root = Path(os.environ["LOCALAPPDATA"])/"SVReviewMaster"
    profile = root/"GoogleMapsSortProfile"
    if not (profile/"Default"/"Network"/"Cookies").is_file():
        print("DEDICATED_PROFILE_NOT_FOUND")
        return 2
    from playwright.sync_api import sync_playwright
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root/"local-review-batch.lock").open("a+b") as lock:
        lock.seek(0,2)
        if lock.tell()==0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            print("LOCAL_BATCH_ALREADY_RUNNING")
            return 2
        started = production.now_kst()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = root/"reports"/("append-"+stamp+"-"+uuid4().hex[:8]+".json")
        results = [dict(status="MAPPING_HELD", reason=t["hold_reason"], confirmed_new=0,
                        database_writes=False) if t["hold_reason"] else
                   dict(status="NOT_ATTEMPTED", confirmed_new=0, database_writes=False) for t in tasks]
        run_id = None
        # Record an aggregate-only local checkpoint after every store. Do not
        # overwrite the full dashboard crawl summary for a filtered pilot.
        full_scope = not (args.country or args.limit or args.skip_store)
        if args.commit and full_scope:
            run_id = production.create_crawl_run(len(tasks))
        def checkpoint(state):
            report = dict(state=state, mode="APPEND" if args.commit else "DRY_RUN",
                          full_scope=full_scope, crawl_run_id=run_id,
                          started_at=started.isoformat(),
                          stores=[dict(store=t["name"],country=t["country"],**r)
                                  for t,r in zip(tasks,results)])
            discovery.checkpoint(path,report)
        checkpoint("RUNNING")
        stop = None
        try:
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],locale="en-US")
                try:
                    for i,task in enumerate(tasks):
                        if task["hold_reason"]:
                            continue
                        print("LOCAL_BATCH_STORE: "+json.dumps(dict(index=i+1,total=len(tasks),
                              store=task["name"],country=task["country"]),ensure_ascii=False),flush=True)
                        try:
                            result = run_store(context,config,task,args.commit,run_id)
                        except Exception as exc:
                            # A write may have reached DB; never blindly retry.
                            result = dict(status="STORE_EXECUTION_ERROR",error_type=type(exc).__name__,
                                          confirmed_new=0,database_writes="UNKNOWN" if args.commit else False)
                        results[i]=result
                        checkpoint("RUNNING")
                        print("LOCAL_BATCH_RESULT: "+json.dumps(dict(store=task["name"],**result),ensure_ascii=False),flush=True)
                        if (result["status"] in {"ACCESS_RESTRICTED_STOPPED","APPEND_OUTCOME_UNCONFIRMED",
                                                 "STORE_EXECUTION_ERROR","BROWSER_CONNECTION_LOST"}
                                or result.get("database_writes")=="UNKNOWN"):
                            stop=result["status"]
                            break
                finally:
                    context.close()
        finally:
            try:
                if run_id is not None:
                    production.finish_crawl_run(run_id,[status_for_run(t,r) for t,r in zip(tasks,results)],started)
                checkpoint("STOPPED" if stop or any(r["status"]=="NOT_ATTEMPTED" for r in results) else "FINISHED")
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        counts=Counter(r["status"] for r in results)
        success={"APPEND_CONFIRMED","NO_READY_ROWS"} if args.commit else {"DRY_RUN"}
        print("LOCAL_BATCH_FINAL: "+json.dumps(dict(stores=len(tasks),statuses=dict(counts),
                confirmed_new=sum(r.get("confirmed_new",0) for r in results),stop=stop,
                report=str(path)),ensure_ascii=False),flush=True)
        return 0 if all(r["status"] in success for r in results) else 2


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("LOCAL_BATCH_FAILED: "+type(exc).__name__)
        raise SystemExit(2)
