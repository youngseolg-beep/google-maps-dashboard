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
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import local_review_profile_probe as probe
import scraper as production
from review_append_preflight import build_append_preview
from review_source_attempt_journal import AttemptJournal
from review_source_identity import valid_hash
from review_incremental_boundary import preview_boundary, MIN_OVERLAP, observed_frontier_reached
from review_incremental_baseline import committed_baseline
from review_source_reconcile import legacy_target


def acceptance_rejection(raw, evidence):
    """One primary reason per held source; order is deliberate and stable."""
    if not production.normalize_spaces(raw.get('author') or ''):
        return 'author_missing'
    if type(raw.get('rating')) is not int or not 1 <= raw['rating'] <= 5:
        return 'rating_missing_or_invalid'
    if not evidence:
        return 'body_audit_missing'
    if evidence.get('click_error') is not False:
        return 'body_control_click_failed'
    if evidence.get('more_remaining') != 0:
        return 'more_control_unresolved'
    if evidence.get('original_remaining') != 0:
        return 'original_control_unresolved'
    if evidence.get('more_verified') is not True:
        return 'more_resolution_unverified'
    if evidence.get('original_verified') is not True:
        return 'original_resolution_unverified'
    body = raw.get('body')
    if not isinstance(body,str):
        return 'body_extraction_missing'
    if not body.strip():
        return None if body == '' and evidence.get('rating_only_verified') is True else 'rating_only_unverified'
    if raw.get('body_scope') != 'PRIMARY' or evidence.get('scope') != 'PRIMARY':
        return 'customer_body_scope_unverified'
    if evidence.get('fingerprint') != hashlib.sha256(body.encode()).digest():
        return 'body_changed_after_audit'
    return None


class SourceWriter:
    """Actual append path: atomic source links/rows/receipts, durable retries."""
    def __init__(self, config, store, journal_path, *, commit, run_id=None):
        self.store, self.commit, self.run_id = store, commit, run_id
        self.journal = AttemptJournal(journal_path)
        self.outcomes = Counter()
        self.recovered_outcomes = Counter()
        self.recovered_operations = 0
        self.held = {}
        self.config = config
        try:
            if config is not None:
                self.journal.bind_backend(config[0])
            self.recover()
            self.history = history_snapshot(config, store)
            self.links = self.read_rows('review_source_links', 'source_hash,review_id', 'source_hash.asc')
            self.known = {row['source_hash'] for row in self.links}
            self.linked_rows = {row['review_id'] for row in self.links}
            bases = self.read_rows('review_source_baselines', 'generation,head', 'store_id.asc')
            if len(bases) > 1:
                raise ValueError('SOURCE_BASELINE_INVALID')
            self.baseline = committed_baseline(store['id'], **bases[0]) if bases else None
            self.daily_frontier = self.journal.frontier(store['id'])
        except BaseException:
            self.journal.close()
            raise
        self.observed = []
        self.raw_seen = set()
        self.previous_order = []

    def collect_window(self, page, reviews, store_key, *, recent):
        ids = page.locator('.jftiEf').evaluate_all(
            "cards => cards.map(c => c.getAttribute('data-review-id'))")
        if any(not isinstance(identity,str) or not identity for identity in ids) or len(set(ids)) != len(ids):
            raise ValueError('STREAM_DUPLICATE_DOM_IDS')
        if recent and self.previous_order and not probe.ordered_extension(self.previous_order, ids):
            raise ValueError('STREAM_ORDER_CHANGED')
        self.previous_order = ids
        fresh = [identity for identity in ids if identity not in self.raw_seen]
        for identity in fresh:
            self.observed.append(production.hash_google_source_review_id(self.store['id'], identity))
        # Re-read already committed IDs only as boundary evidence. Their bodies
        # and history need no repeat audit after a browser/process restart.
        pending = [identity for identity in fresh if production.hash_google_source_review_id(self.store['id'],identity) not in self.known]
        for offset in range(0,len(pending),250):
            chosen = set(pending[offset:offset+250])
            _, before = probe.audit_loaded_fields(page,len(chosen),include_records=True,selected_ids=chosen)
            evidence = {}
            audit = probe.audit_body_sample(page,store_key,reviews,limit=len(chosen),
                deadline=time.monotonic()+probe.COUNT_BODY_SECONDS,evidence_sink=evidence,selected_ids=chosen)
            if audit['context_lost'] or audit['identity_mismatch']:
                raise ValueError('STREAM_CONTEXT_LOST')
            _, after = probe.audit_loaded_fields(page,len(chosen),include_records=True,selected_ids=chosen)
            original_meta = {r['source_id']:(r['author'],r['rating'],r['date_label']) for r in before}
            actual_meta = {r['source_id']:(r['author'],r['rating'],r['date_label']) for r in after}
            if set(original_meta) != chosen or original_meta != actual_meta:
                raise ValueError('STREAM_METADATA_CHANGED')
            self.append(after,evidence)
        self.raw_seen.update(fresh)
        return dict(observed=len(self.observed), committed=sum(h in self.known for h in self.observed),
                    unresolved=sum(h not in self.known for h in self.observed),
                    boundary_reached=recent and (self.boundary(self.observed) or self.frontier_reached()),
                    boundary_kind='committed' if self.boundary(self.observed) else 'observed_with_backlog')

    def frontier_reached(self):
        frontier=getattr(self,'daily_frontier',None)
        return bool(frontier and observed_frontier_reached(frontier['head'],self.observed))

    def save_progress(self, *, newest_verified=False, complete=False, finished=False):
        if not self.commit:
            return {}
        frontier=getattr(self,'daily_frontier',None)
        reached=self.frontier_reached() or self.boundary(self.observed)
        advance=(finished and newest_verified and len(self.observed)>=MIN_OVERLAP
                 and not self.journal.pending_requests(self.store['id'])
                 and (complete or reached or (frontier is None and self.baseline is None)))
        self.journal.record_progress(self.store['id'],self.observed,self.known,self.held,
            frontier_generation=(frontier['generation'] if frontier else 0) if advance else None,
            unknown_history=not complete and (not reached or not frontier or frontier['unknown_history']))
        return dict(historical_backlog=len(self.journal.backlog(self.store['id'])),
                    historical_coverage_unknown=(self.journal.frontier(self.store['id']) or {}).get('unknown_history',not complete),
                    observed_frontier_saved=advance)

    def read_rows(self, table, columns, order):
        rows = []
        while True:
            page = production.supabase_request('GET', table, query={
                'store_id':'eq.'+self.store['id'], 'select':columns,
                'order':order, 'limit':'500', 'offset':str(len(rows))})
            if not isinstance(page, list):
                raise ValueError('SOURCE_READ_UNCONFIRMED')
            rows.extend(page)
            if len(page) < 500:
                return rows

    def request(self, request):
        operation = self.journal.prepare_request(request)
        # Reconcile the receipt before retrying the identical transactional RPC.
        receipts = production.supabase_request('GET', 'review_source_receipts', query={
            'operation_id':'eq.'+operation, 'store_id':'eq.'+self.store['id'], 'select':'request,result'})
        if not isinstance(receipts, list) or len(receipts) > 1:
            raise ValueError('SOURCE_RECEIPT_UNCONFIRMED')
        if receipts:
            expected = dict(items=request['p_items'], finalize=request['p_finalize'])
            if receipts[0]['request'] != expected:
                raise ValueError('SOURCE_RECEIPT_CONFLICT')
            result = receipts[0]['result']
        else:
            result = production.supabase_request('POST', 'rpc/append_review_sources', body=request)
        self.journal.confirm_request(request, result)
        return result

    def recover(self):
        pending = self.journal.pending_requests(self.store['id'])
        if pending and not self.commit:
            raise ValueError('SOURCE_RECOVERY_REQUIRES_COMMIT')
        for request in pending:
            result = self.request(request)
            self.recovered_operations += 1
            self.recovered_outcomes.update(item['status'] for item in result['outcomes'])

    def plan(self, records, evidence):
        items = []
        seen = set()
        variants = {}
        for raw in records:
            source = production.hash_google_source_review_id(self.store['id'],raw.get('source_id'))
            shape = repr(tuple(raw.get(k) for k in ('author','rating','body','body_scope','date_label')))
            variants.setdefault(source,set()).add(shape)
        for raw in records:
            source = production.hash_google_source_review_id(self.store['id'], raw.get('source_id'))
            if not valid_hash(source) or source in seen:
                continue
            seen.add(source)
            if source in self.known:
                continue
            if len(variants[source]) > 1:
                self.held[source] = 'duplicate_source_conflict'
                continue
            e = evidence.get(hashlib.sha256(raw['source_id'].encode()).hexdigest(), {})
            body = raw.get('body')
            rejection = acceptance_rejection(raw,e)
            if rejection:
                self.held[source] = rejection
                continue
            date_value, date_source = probe.local_date_value(raw.get('date_label'), production.now_kst().date(), production)
            review = dict(store_name=self.store['store_name'], sv=self.store['sv'], country=self.store['country'],
                          city=self.store.get('city',''), author=raw['author'], text=body, rating=raw['rating'],
                          has_text=bool(body.strip()), date=raw.get('date_label') or 'Unknown',
                          review_date=date_value, review_date_source=date_source or 'unknown')
            row = production.prepare_review_row(review, {production.normalize_store_lookup_key(self.store['store_name']):self.store['id']}, self.run_id)
            target, hold = legacy_target(self.history.values(),self.linked_rows,row,production)
            if hold:
                self.held[source] = hold
                continue
            # New IDs may represent distinct same-author reviews with identical text.
            # Keep historical keys intact; scope new keys to the durable source ID.
            row['review_key'] = hashlib.sha256(('google-source-v1:'+self.store['id']+':'+source).encode()).hexdigest()
            item = dict(source_hash=source, row=row)
            if target:
                item['legacy_id'] = target
                # The RPC compares an immutable historical preimage. Date drift
                # is resolved by the unique signature above, never by changing
                # the historical row or weakening the server's equality check.
                legacy = next(old for old in self.history.values() if old['id'] == target)
                row['author'] = legacy['author']
                row['date'] = legacy.get('_stored_date_for_link',legacy.get('date') or '')
                row['text'] = legacy.get('text') or ''
            items.append(item)
        targets = Counter(item.get('legacy_id') for item in items if item.get('legacy_id'))
        accepted = []
        for item in items:
            if item.get('legacy_id') and targets[item['legacy_id']] > 1:
                self.held[item['source_hash']] = 'legacy_target_collision'
            else:
                accepted.append(item)
        return accepted

    def append(self, records, evidence):
        items = self.plan(records, evidence)
        if not self.commit:
            return dict(status='DRY_RUN', ready=len(items), held=len(self.held))
        self.journal.record_progress(self.store['id'],list(self.held),self.known,self.held)
        for offset in range(0,len(items),250):
            result = self.request(dict(p_operation_id=str(uuid4()), p_store_id=self.store['id'],
                                       p_items=items[offset:offset+250], p_finalize=None))
            for outcome in result['outcomes']:
                source, status = outcome['source_hash'], outcome['status']
                self.outcomes[status] += 1
                if status == 'unresolved':
                    self.held[source] = status
                else:
                    self.known.add(source)
                    self.linked_rows.add(outcome['review_id'])
                    self.held.pop(source, None)
        self.journal.record_progress(self.store['id'],list(self.held),self.known,self.held)
        return dict(status='APPEND_CONFIRMED', held=len(self.held))

    def boundary(self, observed):
        if self.baseline is None:
            return False
        return preview_boundary(self.store['id'], self.baseline, observed, self.known,
            newest_verified=True, registry_verified=True, context_verified=True)['status'] == 'INCREMENTAL_BOUNDARY_CANDIDATE'

    def finish(self, observed, *, newest_verified, complete):
        if (not self.commit or not newest_verified or len(observed) < MIN_OVERLAP
                or self.held or self.journal.backlog(self.store['id']) or self.journal.pending_requests(self.store['id'])
                or not set(observed).issubset(self.known)
                or (self.baseline is None and not complete) or (self.baseline and not self.boundary(observed))):
            return False
        request = dict(p_operation_id=str(uuid4()), p_store_id=self.store['id'], p_items=[],
                       p_finalize=dict(generation=self.baseline['generation'] if self.baseline else 0,
                           observed=observed, newest_verified=True, resolved=True, initial_complete=complete))
        return self.request(request)['boundary_advanced']


def backend_config(target):
    base = production.SUPABASE_URL or target.rstrip("/")
    key = production.SUPABASE_SERVICE_ROLE_KEY
    u = urlsplit(base)
    if (base != target.rstrip("/") or u.scheme != "https"
            or not u.hostname or not u.hostname.endswith(".supabase.co")
            or u.path or u.query or u.fragment or u.username or u.password or u.port):
        raise ValueError("PILOT_BACKEND_TARGET_UNVERIFIED")
    # Accept the current secret key or the legacy service_role JWT.
    # The target's privileged API root independently validates the credential.
    if not key:
        import getpass
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Supabase secret key (hidden): ").strip()
    key = key.strip()
    if not key:
        raise ValueError("PILOT_KEY_EMPTY")
    if key.startswith("sb_secret_"):
        token = ""
    elif key.count(".") == 2:
        import base64
        try:
            payload = key.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (ValueError, TypeError):
            raise ValueError("PILOT_KEY_INVALID_JWT") from None
        if claims.get("role") != "service_role":
            raise ValueError("PILOT_KEY_NOT_SERVICE_ROLE")
        if claims.get("ref") not in (None, u.hostname.split(".")[0]):
            raise ValueError("PILOT_KEY_PROJECT_MISMATCH")
        token = key
    else:
        raise ValueError("PILOT_KEY_NOT_SECRET_OR_SERVICE_ROLE")
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from urllib.error import HTTPError
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    headers = {"apikey": key, "Accept": "application/openapi+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(base + "/rest/v1/", headers=headers, method="GET")
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200:
                raise ValueError("PILOT_KEY_SERVER_REJECTED")
    except HTTPError as exc:
        raise ValueError("PILOT_KEY_SERVER_HTTP_" + str(exc.code)) from None
    production.SUPABASE_URL = base
    production.SUPABASE_SERVICE_ROLE_KEY = key
    print("PILOT_BACKEND_AUTH_VERIFIED", flush=True)
    return base, key, token


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
    audited = [r for r in records if isinstance(r.get("source_id"), str) and
               hashlib.sha256(r["source_id"].encode("utf-8")).hexdigest() in evidence]
    partition = probe.body_evidence_partition(audited, evidence)
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
    evidence_rejections = Counter()
    for raw in records:
        identity = raw.get("source_id")
        body = raw.get("body")
        if not isinstance(identity, str) or not identity or not isinstance(body, str) or not body.strip():
            continue
        e = evidence.get(hashlib.sha256(identity.encode("utf-8")).hexdigest(), {})
        author = production.normalize_spaces(raw.get("author") or "").casefold()
        if not e:
            continue
        if (raw.get("body_scope") == e.get("scope") == "PRIMARY"
                and e.get("fingerprint") == hashlib.sha256(body.encode("utf-8")).digest()
                and e.get("click_error") is False and e.get("more_remaining") == 0
                and e.get("original_remaining") == 0
                and e.get("more_verified") is True and e.get("original_verified") is True
                and author and raw_authors[author] == 1):
            verified.add(production.hash_google_source_review_id(store["id"], identity))
        else:
            if e.get("more_verified") is not True: evidence_rejections["expansion_not_verified"] += 1
            if e.get("original_verified") is not True: evidence_rejections["original_not_verified"] += 1
            if e.get("click_error") is not False: evidence_rejections["control_error"] += 1
            if raw_authors[author] != 1: evidence_rejections["author_collision"] += 1
            if e.get("fingerprint") != hashlib.sha256(body.encode("utf-8")).digest(): evidence_rejections["fingerprint_changed"] += 1
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
                  body_audited=len(audited), classification=partition["counts"],
                  evidence_rejections=dict(evidence_rejections), verified_source_count=len(verified),
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
            writer = SourceWriter(config,store,root/'review-source-requests.sqlite3',commit=args.commit)
            try:
                outcome = writer.append(*captured[0])
                captured.clear()
                print('LOCAL_APPEND_PILOT: '+json.dumps(dict(outcome,outcomes=dict(writer.outcomes),
                    full_coverage_verified=False, boundary_advanced=False)))
                return 0 if not writer.held else 2
            finally:
                writer.journal.close()
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
