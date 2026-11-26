"""Single-store live capture -> existing append-only Supabase writer.

Default is dry-run. No migrations or historical mutations. Explicit --commit
is a bounded, operator-approved pilot, not an unattended scheduler. Uses
existing backend credentials; never exports Chrome cookies or review text.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import local_review_profile_probe as probe
import scraper as production
from review_append_preflight import build_append_preview


def backend_config(target):
    base = production.SUPABASE_URL or target.rstrip("/")
    key = production.SUPABASE_SERVICE_ROLE_KEY
    u = urlsplit(base)
    if (base != target.rstrip("/") or u.scheme != "https"
            or not u.hostname or not u.hostname.endswith(".supabase.co")
            or u.path or u.query or u.fragment or u.username or u.password or u.port):
        raise ValueError("PILOT_BACKEND_TARGET_UNVERIFIED")
    # Existing backend credential stays in memory only. No secret in CLI,
    # shell history, files or logs; refuse an echoed-input fallback.
    if not key:
        import getpass
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Supabase service_role key (hidden): ").strip()
    # Current writer expects a legacy backend JWT, never a public audit key.
    import base64
    if key.count(".") != 2:
        raise ValueError("PILOT_BACKEND_ROLE_UNVERIFIED")
    payload = key.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    if claims.get("role") != "service_role" or claims.get("ref") != u.hostname.split(".")[0]:
        raise ValueError("PILOT_BACKEND_ROLE_UNVERIFIED")
    production.SUPABASE_URL = base
    production.SUPABASE_SERVICE_ROLE_KEY = key
    return base, key, key


def history_snapshot(config, store):
    rows = probe.load_visible_history(config, store)
    keys = {}
    for row in rows:
        key = row.get("review_key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("PILOT_HISTORY_KEY_UNVERIFIED")
        keys[key] = row
    return keys


def plan_rows(store, history, records, evidence):
    partition = probe.body_evidence_partition(records, evidence)
    if not partition["exact_audit_scope"]:
        raise ValueError("PILOT_BODY_SCOPE_UNVERIFIED")
    candidates, gaps = probe.adapt_local_records(
        records, store["store_name"], production.now_kst().date(),
        production, store_id=store["id"])
    # Use the existing planner on ALL candidates, not a filtered subset.
    # A held card must not conceal a same-author collision.
    preview, proposed = build_append_preview(store, list(history.values()), candidates, production)
    raw_authors = Counter(production.normalize_spaces(r.get("author") or "").casefold()
                          for r in records)
    verified = set()
    for raw in records:
        identity = raw.get("source_id")
        body = raw.get("body")
        if not isinstance(identity, str) or not identity or not isinstance(body, str) or not body.strip():
            continue
        e = evidence.get(hashlib.sha256(identity.encode("utf-8")).hexdigest(), {})
        author = production.normalize_spaces(raw.get("author") or "").casefold()
        if (raw.get("body_scope") == e.get("scope") == "PRIMARY"
                and e.get("fingerprint") == hashlib.sha256(body.encode("utf-8")).digest()
                and e.get("click_error") is False and e.get("more_remaining") == 0
                and e.get("original_remaining") == 0
                and e.get("more_verified") is True and e.get("original_verified") is True
                and author and raw_authors[author] == 1):
            verified.add(production.hash_google_source_review_id(store["id"], identity))
    allowed_keys = {production.canonical_review_hash(r) for r in candidates
                    if r.get("google_source_id_hash") in verified}
    rows = [r for r in proposed if r["review_key"] in allowed_keys]
    if (len(rows) > probe.MAX_COUNT_BODY_AUDIT
            or len({r["review_key"] for r in rows}) != len(rows)
            or any(r["store_id"] != store["id"] or r["review_key"] in history for r in rows)):
        raise ValueError("PILOT_ROW_SCOPE_INVALID")
    report = dict(observed=len(records), existing=len(history), ready=len(rows),
                  adapter_gaps=sum(gaps.values()), legacy_matched=preview["legacy_matched"],
                  legacy_held=preview["legacy_held"]+preview["additional_held"],
                  body_or_author_held=len(proposed)-len(rows),
                  classification=partition["counts"],
                  full_coverage_verified=False, source_registry_persisted=False)
    return report, rows


def execute_append(config, store, history, rows, *, commit):
    if not commit or not rows:
        return dict(status="DRY_RUN" if not commit else "NO_READY_ROWS",
                    database_writes=False, confirmed_new=0)
    # A second GET snapshot detects intervening changes. It is not a lock.
    if history_snapshot(config, store) != history:
        raise ValueError("PILOT_HISTORY_CHANGED")
    # One POST request is one PostgREST transaction; no multi-batch partial
    # commit. Reuse the existing ignore-duplicate writer; never update/delete.
    # The pilot is intentionally not a scheduled writer and requires an
    # exclusive operator-controlled window.
    if os.environ.get("SV_REVIEW_PILOT_EXCLUSIVE") != "1":
        raise ValueError("PILOT_EXCLUSIVE_WINDOW_REQUIRED")
    try:
        production.upsert_review_batch(rows, batch_size=probe.MAX_COUNT_BODY_AUDIT)
        acknowledged = True
    except Exception:
        acknowledged = False
    # Always reconcile a possibly committed request. Never blindly retry.
    after = history_snapshot(config, store)
    if any(after.get(k) != v for k, v in history.items()):
        raise ValueError("PILOT_HISTORICAL_DATA_CHANGED")
    def matches(row):
        saved = after.get(row["review_key"])
        return bool(saved and all(saved.get(k) == row.get(k) for k in
                                  ("store_id", "author", "rating", "text", "review_date", "has_text")))
    confirmed = sum(matches(r) for r in rows)
    if confirmed != len(rows):
        return dict(status="APPEND_OUTCOME_UNCONFIRMED", database_writes="UNKNOWN",
                    confirmed_new=confirmed, acknowledged=acknowledged)
    return dict(status="APPEND_CONFIRMED", database_writes=True, confirmed_new=confirmed,
                acknowledged=acknowledged)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", choices=("thailand", "taiwan"), default="thailand")
    p.add_argument("--expected-total", type=int, help="Optional known total; otherwise read current Maps total twice.")
    p.add_argument("--target-url", required=True)
    p.add_argument("--commit", action="store_true")
    args = p.parse_args()
    if args.expected_total is not None and not 1 <= args.expected_total <= probe.MAX_COUNT_BODY_AUDIT:
        p.error("expected total outside bounded body audit")
    if os.name != "nt":
        print("WINDOWS_ONLY")
        return 2
    if args.commit and os.environ.get("SV_REVIEW_PILOT_EXCLUSIVE") != "1":
        print("PILOT_EXCLUSIVE_WINDOW_REQUIRED")
        return 2
    config = backend_config(args.target_url)
    store = probe.verified_db_store(config, args.store)
    UUID(str(store["id"]))
    root = Path(os.environ["LOCALAPPDATA"]) / "SVReviewMaster"
    profile = root / "GoogleMapsSortProfile"
    if not (profile / "Default" / "Network" / "Cookies").is_file():
        print("DEDICATED_PROFILE_NOT_FOUND")
        return 2
    import msvcrt
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True, exist_ok=True)
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
            captured = []
            def receive(records, evidence):
                if captured:
                    raise ValueError("PILOT_MULTIPLE_CAPTURES")
                captured.append((records, evidence))
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"], locale="en-US")
                try:
                    result = probe.run_once(context, args.expected_total, args.store,
                                            auto_total=args.expected_total is None,
                                            scroll_mode="adaptive", count_body_audit=True,
                                            maps_language="en", capture_sink=receive)
                finally:
                    context.close()
            verified_total = result.get("expected_total_user_observed")
            if (result.get("status") not in {"LOCAL_COUNT_BODY_CONTROLS_CHECKED", "LOCAL_COUNT_BODY_CONTROL_GAPS", "LOCAL_COUNT_BODY_EVIDENCE_LIMITED"}
                    or type(verified_total) is not int or not 1 <= verified_total <= probe.MAX_COUNT_BODY_AUDIT
                    or result.get("observed_unique") != verified_total or len(captured) != 1):
                print("PILOT_CAPTURE_HELD: "+str(result.get("status")))
                return 2
            # Fresh privileged, store-scoped history; do not rely on public
            # RLS-limited audit results for an insertion decision.
            history = history_snapshot(config, store)
            report, rows = plan_rows(store, history, *captured[0])
            captured.clear()
            outcome = execute_append(config, store, history, rows, commit=args.commit)
            print("LOCAL_APPEND_PILOT: "+json.dumps(dict(report, **outcome), ensure_ascii=False))
            return 0 if outcome["status"] in {"DRY_RUN", "APPEND_CONFIRMED", "NO_READY_ROWS"} else 2
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Do not print HTTP response bodies, credentials, or review payloads.
        reason = str(exc) if type(exc) is ValueError and str(exc).startswith("PILOT_") else type(exc).__name__
        print("LOCAL_APPEND_PILOT_FAILED: "+reason)
        raise SystemExit(2)
