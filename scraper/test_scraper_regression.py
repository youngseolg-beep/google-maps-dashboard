import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch


playwright_module = types.ModuleType("playwright")
playwright_sync_api = types.ModuleType("playwright.sync_api")
playwright_sync_api.sync_playwright = None
sys.modules.setdefault("playwright", playwright_module)
sys.modules.setdefault("playwright.sync_api", playwright_sync_api)

MODULE_PATH = Path(__file__).with_name("scraper.py")
SPEC = importlib.util.spec_from_file_location("review_scraper", MODULE_PATH)
scraper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scraper)
SEED_SPEC = importlib.util.spec_from_file_location("seed_supabase", MODULE_PATH.with_name("seed_supabase.py"))
seed = importlib.util.module_from_spec(SEED_SPEC)
SEED_SPEC.loader.exec_module(seed)


STORE = {
    "store_name": "Bornga Bangkok Sukhumvit",
    "sv": "SV A",
    "country": "Thailand",
    "city": "Bangkok",
}


def review(text, **overrides):
    value = {
        "store_name": STORE["store_name"],
        "author": "Duangkamol L.",
        "rating": 5,
        "date": "2 weeks ago",
        "review_date": "2026-10-28",
        "text": text,
    }
    value.update(overrides)
    return value


class FakeTextLocator:
    def __init__(self, text):
        self.text = text
        self.first = self

    def count(self):
        return 1 if self.text else 0

    def inner_text(self):
        return self.text


class FakeCard:
    def __init__(self, texts):
        self.texts = texts

    def locator(self, selector):
        return FakeTextLocator(self.texts.get(selector, ""))


class FakeSortLocator:
    def __init__(self, checked):
        self.checked = checked
        self.first = self

    def count(self):
        return 1

    def get_attribute(self, attribute):
        return "true" if attribute == "aria-checked" and self.checked else "false"


class FakeSortPage:
    def __init__(self, checked):
        self.checked = checked

    def get_by_role(self, role, name=None):
        return FakeSortLocator(self.checked if role == "menuitemradio" else False)


class PromptElement:
    def __init__(self, state, kind):
        self.state, self.kind = state, kind

    def count(self):
        return 1 if self.state["present"] else 0

    def nth(self, index):
        return self

    def is_visible(self):
        return self.state["present"]

    def locator(self, selector):
        return PromptElement(self.state, "overlay")

    def get_by_role(self, role, name, exact=False):
        return PromptElement(self.state, name)

    def click(self, timeout):
        if self.kind != "Dismiss":
            raise AssertionError("Unexpected button clicked")
        if self.state.get("fail"):
            raise RuntimeError("dismiss failed")
        self.state["present"] = False

    def wait_for(self, state, timeout):
        if self.state["present"]:
            raise RuntimeError("prompt remains visible")


class PromptPage:
    def __init__(self, present=True, fail=False):
        self.state = {"present": present, "fail": fail}

    def get_by_text(self, text, exact=False):
        if text != "Sign-in to get the best of Google Maps" or not exact:
            raise AssertionError("Unexpected prompt search")
        return PromptElement(self.state, "heading")


class ReviewCrawlerRegressionTests(unittest.TestCase):
    def test_confirmed_prompt_is_dismissed_and_absent_prompt_is_ignored(self):
        page = PromptPage()
        with patch("builtins.print"):
            self.assertEqual(scraper.dismiss_confirmed_maps_sign_in_prompt(page), "dismissed")
        self.assertFalse(page.state["present"])
        self.assertEqual(scraper.dismiss_confirmed_maps_sign_in_prompt(PromptPage(False)), "absent")

    def test_prompt_dismiss_failure_fails_closed(self):
        with patch("builtins.print"):
            self.assertEqual(scraper.dismiss_confirmed_maps_sign_in_prompt(PromptPage(fail=True)), "failed")

    def test_sort_retry_after_dismissal_requires_verified_newest(self):
        for verified in (True, False):
            with self.subTest(verified=verified), patch("builtins.print"), \
                 patch.object(scraper, "close_reviews_sort_menu"), \
                 patch.object(scraper, "open_reviews_sort_menu", return_value=True) as open_menu, \
                 patch.object(scraper, "dismiss_confirmed_maps_sign_in_prompt", side_effect=["dismissed", "absent", "absent"]), \
                 patch.object(scraper, "newest_sort_is_selected", side_effect=[False, verified] if verified else [False] * 4), \
                 patch.object(scraper, "click_newest_sort_option", return_value=True) as click_newest, \
                 patch.object(scraper, "newest_sort_order_is_verified", return_value=False):
                self.assertEqual(scraper.set_reviews_sort_to_newest(Mock()), verified)
                self.assertGreaterEqual(open_menu.call_count, 2)
                self.assertGreaterEqual(click_newest.call_count, 1)

    def test_collapsed_and_expanded_review_are_one_candidate_with_full_text(self):
        collapsed = review("The staff were very helpful and the food was excellent")
        expanded = review("The staff were very helpful and the food was excellent during our family dinner. We will return soon.")

        self.assertTrue(scraper.are_expanded_text_variants(collapsed, expanded))
        self.assertTrue(scraper.find_existing_review_match(expanded, [collapsed]))

        merged = scraper.merge_reviews([], [collapsed, expanded])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], expanded["text"])
        _, rows_to_insert = scraper.get_new_reviews_to_insert([collapsed], [expanded])
        self.assertEqual(rows_to_insert, [])

    def test_same_author_rating_and_date_with_distinct_texts_are_preserved(self):
        first = review("The noodles were excellent and the broth was rich")
        second = review("The dining room was quiet and the service was quick")

        self.assertFalse(scraper.are_expanded_text_variants(first, second))
        self.assertFalse(scraper.find_existing_review_match(second, [first]))
        self.assertEqual(len(scraper.merge_reviews([], [first, second])), 2)

    def test_longest_available_text_is_selected_after_expansion(self):
        card = FakeCard({
            ".wiI7pd": "Short preview",
            ".MyEned": "Short preview with the full expanded review text available",
        })
        self.assertEqual(
            scraper.get_review_text(card),
            "Short preview with the full expanded review text available",
        )

    def test_recent_collection_refuses_unverified_newest_sort(self):
        with self.assertRaisesRegex(RuntimeError, "최신순 정렬 검증"):
            scraper.extract_reviews(None, STORE, [review("Existing full review text that is long enough")], newest_verified=False)

    def test_newest_sort_verification_requires_aria_checked_true(self):
        self.assertFalse(scraper.newest_sort_is_selected(FakeSortPage(False)))
        self.assertTrue(scraper.newest_sort_is_selected(FakeSortPage(True)))

    def test_sort_diagnostic_only_recognizes_sort_option_labels(self):
        self.assertTrue(scraper.is_sort_option_text("Newest"))
        self.assertTrue(scraper.is_sort_option_text("관련성순"))
        self.assertTrue(scraper.is_sort_option_text("Highest rating"))
        self.assertFalse(scraper.is_sort_option_text("A reviewer name or review body is not a sort option"))

    def test_sort_artifact_name_and_clip_are_limited_to_sort_controls(self):
        self.assertEqual(
            scraper.sort_diagnostic_stem("Bornga Bangkok Sukhumvit", 1),
            "sort-after-click-bornga-bangkok-sukhumvit-attempt-01",
        )
        button = {"bounding_box": {"x": 100, "y": 40, "width": 40, "height": 30}}
        broad_popup = {"bounding_box": {"x": 0, "y": 0, "width": 1400, "height": 900}}
        clip = scraper.bounded_sort_screenshot_clip(button, [broad_popup], {"width": 1440, "height": 1000})
        self.assertEqual(clip["width"], 64)
        self.assertEqual(clip["height"], 54)

    def test_diagnostic_label_allowlist_and_screenshot_redaction(self):
        self.assertTrue(scraper.is_safe_sort_label("Newest"))
        self.assertTrue(scraper.is_safe_sort_label("Sort reviews"))
        self.assertFalse(scraper.is_safe_sort_label("Reviewer: newest restaurant experience"))
        self.assertIn("-webkit-text-fill-color: transparent", scraper.SORT_CAPTURE_STYLE)
        self.assertIn("background-image: none", scraper.SORT_CAPTURE_STYLE)
        self.assertIn("visibility: hidden", scraper.SORT_CAPTURE_STYLE)

    def test_overlay_diagnostic_passes_only_preclick_ids_and_keeps_result(self):
        page = Mock()
        expected = {"status": "captured", "heading": {"text": "Notice"},
                    "list_items": [{"text": "one"}, {"text": "two"}, {"text": "three"}],
                    "buttons": [{"text": "Continue"}, {"text": "Cancel"}]}
        page.evaluate.return_value = expected
        self.assertEqual(scraper.capture_centered_overlay_metadata(page, [12, 13]), expected)
        script, prior_ids = page.evaluate.call_args.args
        self.assertEqual(prior_ids, [12, 13])
        self.assertIn("smallest.length !== 1", script)
        self.assertIn("[data-review-id]", script)
        self.assertIn("querySelectorAll('button').length === 2", script)

    def test_rendered_relative_dates_can_verify_newest_order_without_radio_metadata(self):
        self.assertTrue(scraper.review_dates_are_newest_first(["2 hours ago", "1 day ago", "3 weeks ago"]))
        self.assertFalse(scraper.review_dates_are_newest_first(["3 weeks ago", "1 day ago", "2 hours ago"]))
        self.assertFalse(scraper.review_dates_are_newest_first(["Unknown", "1 day ago", "2 weeks ago"]))

    def test_recent_stop_requires_verified_depth_and_consecutive_existing_reviews(self):
        self.assertFalse(scraper.should_stop_recent_collection(1, 20, 6))
        self.assertFalse(scraper.should_stop_recent_collection(2, 9, 6))
        self.assertFalse(scraper.should_stop_recent_collection(2, 12, 2))
        self.assertTrue(scraper.should_stop_recent_collection(2, 12, 3))

    def test_feed_growth_prevents_false_stall_when_no_new_candidates_are_found(self):
        self.assertTrue(scraper.feed_grew(10, 20, 10, 20))
        self.assertTrue(scraper.feed_grew(20, 20, 10, 15))
        self.assertFalse(scraper.feed_grew(20, 20, 15, 15))

    def test_target_store_mode_is_exact_and_all_failed_result_is_fatal(self):
        stores = [
            {"store_name": "Bornga Bangkok Sukhumvit"},
            {"store_name": "Other Store"},
        ]
        with patch("builtins.print"):
            selected = scraper.select_target_stores(stores, "bornga bangkok sukhumvit")
        self.assertEqual(selected, [stores[0]])
        with self.assertRaisesRegex(RuntimeError, "정확히 일치"):
            scraper.select_target_stores(stores, "Bornga")
        self.assertTrue(scraper.all_crawl_results_failed([{"ok": False}]))
        self.assertFalse(scraper.all_crawl_results_failed([{"ok": True}, {"ok": False}]))

    def test_verified_requires_independent_completeness_evidence(self):
        classify = scraper.classify_collection_status
        self.assertEqual(classify(attempted=True, observed_review_count=42), "PARTIAL")
        self.assertEqual(classify(attempted=True, independent_completeness_confirmed=True), "VERIFIED")
        self.assertEqual(classify(attempted=False), "NOT_CHECKED")
        self.assertEqual(classify(attempted=True), "FAILED")
        row = scraper.collection_status_row(STORE, attempted=True, independent_completeness_confirmed=True)
        self.assertEqual((row["collection_status"], row["collection_reason"]),
                         ("VERIFIED", "independent_completeness_confirmed"))

    def test_existing_review_observation_is_partial_even_with_no_new_candidates(self):
        text = "Existing review."
        existing = review(text)
        cards = Mock()
        cards.count.return_value = 1
        evidence = {"observed_review_count": 0}
        with (
            patch("builtins.print"),
            patch.object(scraper, "click_more_buttons"),
            patch.object(scraper, "click_original_review_buttons"),
            patch.object(scraper, "get_review_cards", return_value=(cards, ".jftiEf")),
            patch.object(scraper, "expand_review_text"),
            patch.object(scraper, "get_review_text", return_value=text),
            patch.object(scraper, "get_review_date", return_value=existing["date"]),
            patch.object(scraper, "get_review_author", return_value=existing["author"]),
            patch.object(scraper, "get_review_rating", return_value=existing["rating"]),
            patch.object(scraper, "should_stop_recent_collection", return_value=True),
        ):
            candidates = scraper.extract_reviews(Mock(), STORE, [existing], newest_verified=True,
                                                 collection_evidence=evidence)
        self.assertEqual(candidates, [])
        row = scraper.collection_status_row(STORE, attempted=True, **evidence, result={
            "ok": True, "collected_count": len(candidates), "error": "", "crawled_at": "",
        })
        self.assertEqual(row["observed_review_count"], 1)
        self.assertEqual(row["collection_status"], "PARTIAL")
        self.assertEqual(row["collected_count"], 0)

    def test_legacy_execution_success_with_no_reviews_observed_is_not_verified(self):
        row = scraper.collection_status_row(STORE, attempted=True, result={
            "ok": True, "collected_count": 0, "error": "", "crawled_at": "",
        })
        self.assertTrue(row["ok"])
        self.assertEqual(row["collection_status"], "FAILED")
        self.assertEqual(row["collection_reason"], "no_usable_reviews_observed")

    def test_sort_gate_failure_preserves_its_reason(self):
        row = scraper.collection_status_row(STORE, attempted=True, result={
            "ok": False, "collected_count": 0, "error": "sort failed", "crawled_at": "",
            "collection_issue": "newest_verification_failed",
        })
        self.assertEqual(row["collection_status"], "FAILED")
        self.assertEqual(row["collection_reason"], "newest_verification_failed")

    def test_interrupted_attempt_retains_observations_and_later_stores_stay_unattempted(self):
        first = scraper.collection_status_row(STORE)
        later = scraper.collection_status_row({**STORE, "store_name": "Later store"})

        def fail_after_observing(*args, collection_evidence):
            collection_evidence["observed_review_count"] = 2
            raise RuntimeError("mock browser failed")

        with patch.object(scraper, "scrape_store", side_effect=fail_after_observing):
            with self.assertRaisesRegex(RuntimeError, "mock browser failed"):
                scraper.scrape_store_with_reporting(Mock(), STORE, [], first)
        self.assertEqual(first["collection_status"], "PARTIAL")
        self.assertEqual(first["collection_reason"], "attempt_interrupted")
        self.assertFalse(first["ok"])
        self.assertEqual(later["collection_status"], "NOT_CHECKED")
        self.assertIsNone(later["ok"])

    def test_crawl_run_metadata_retains_plan_and_excludes_unattempted_from_legacy_failures(self):
        planned = scraper.collection_status_row(STORE)
        blocked = scraper.collection_status_row({**STORE, "store_name": "Blocked"}, attempted=True)
        with patch.object(scraper, "supabase_request", return_value=[{"id": 123}]) as request, patch("builtins.print"):
            self.assertEqual(scraper.create_crawl_run(2), 123)
            self.assertEqual(request.call_args.kwargs["body"]["stores"], [])
            self.assertEqual(request.call_args.kwargs["body"]["total_stores"], 2)
            scraper.finish_crawl_run(123, [planned, blocked], scraper.now_kst())
        self.assertEqual(request.call_args.args, ("PATCH", "crawl_runs"))
        payload = request.call_args.kwargs["body"]
        self.assertEqual(payload["total_stores"], 2)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["failed_stores"], [blocked])
        self.assertEqual(payload["stores"][0]["collection_status"], "NOT_CHECKED")

    def test_execution_summary_does_not_promote_partial_to_verified(self):
        row = scraper.collection_status_row(STORE, attempted=True, observed_review_count=5)
        with patch.dict(scraper.os.environ, {"GITHUB_STEP_SUMMARY": ""}), patch("builtins.print") as log:
            scraper.report_collection_status([row], "COMPLETED")
        record = next(call.args[0] for call in log.call_args_list if call.args[0].startswith("COLLECTION_STATUS "))
        data = json.loads(record.removeprefix("COLLECTION_STATUS "))
        self.assertEqual(data["execution"], "COMPLETED")
        self.assertEqual(data["counts"], {"VERIFIED": 0, "PARTIAL": 1, "FAILED": 0, "NOT_CHECKED": 0})


class ReviewPersistenceRegressionTests(unittest.TestCase):
    def test_both_review_writers_send_conflict_ignore_for_duplicate_keys(self):
        # Two candidates can share a key, or the key can already exist on the server.
        rows = [{"review_key": "shared", "rating": 5}, {"review_key": "shared", "rating": 3}]
        for module, writer in ((scraper, scraper.upsert_review_batch), (seed, seed.upload_reviews)):
            with self.subTest(writer=writer.__name__), patch.multiple(
                module, SUPABASE_URL="https://example.invalid", SUPABASE_SERVICE_ROLE_KEY="test-only"
            ), patch.object(module, "urlopen") as open_url, patch("builtins.print"):
                open_url.return_value.__enter__.return_value.read.return_value = b""
                writer(rows)
                open_url.assert_called_once()
                request = open_url.call_args.args[0]
                self.assertEqual(request.get_method(), "POST")
                self.assertTrue(request.full_url.endswith("/reviews?on_conflict=review_key"))
                self.assertEqual(request.get_header("Prefer"), "resolution=ignore-duplicates,return=minimal")
                self.assertEqual(json.loads(request.data), rows)

    def test_review_updates_deletes_and_merge_upserts_are_blocked_before_network(self):
        for module in (scraper, seed):
            with self.subTest(module=module.__name__), patch.object(module, "urlopen") as open_url:
                for method in ("PATCH", "DELETE", "PUT", "POST"):
                    with self.subTest(method=method), self.assertRaisesRegex(ValueError, "신규 삽입만"):
                        module.supabase_request(
                            method, "reviews", query={"on_conflict": "review_key"},
                            prefer="resolution=merge-duplicates,return=minimal",
                        )
                open_url.assert_not_called()

    def test_partial_run_can_submit_new_rows_without_touching_saved_reviews(self):
        existing = review("already saved", id="saved", rating=5)
        found = review("new review from the store that could be scanned")
        with (
            patch.object(scraper, "load_store_id_map", return_value={STORE["store_name"].casefold(): "store"}),
            patch.object(scraper, "supabase_request") as request,
            patch("builtins.print"),
        ):
            # A failed store contributes no candidates. A repeat in another store's results is skipped.
            scraper.save_reviews([dict(existing, rating=1), found], 42, [existing])
        request.assert_called_once()
        self.assertEqual(request.call_args.args, ("POST", "reviews"))
        rows = request.call_args.kwargs["body"]
        self.assertEqual([row["review_key"] for row in rows], [scraper.canonical_review_hash(found)])
        self.assertEqual(rows[0]["first_seen_run_id"], 42)
        self.assertEqual(existing["rating"], 5)

    def test_interrupted_review_batch_stops_without_retries_or_rollback(self):
        rows = [{"review_key": key} for key in ("first", "second", "third")]
        interruption = TimeoutError("response lost")
        with patch.object(scraper, "supabase_request", side_effect=[None, interruption]) as request:
            with self.assertRaisesRegex(RuntimeError, "배치 2.*후보 1건") as failure:
                scraper.upsert_review_batch(rows, batch_size=1)
        self.assertIs(failure.exception.__cause__, interruption)
        self.assertEqual(request.call_args_list, [
            call("POST", "reviews", query={"on_conflict": "review_key"}, body=rows[:1],
                 prefer=scraper.REVIEW_INSERT_PREFERENCE),
            call("POST", "reviews", query={"on_conflict": "review_key"}, body=rows[1:2],
                 prefer=scraper.REVIEW_INSERT_PREFERENCE),
        ])

    def test_repair_only_reads_and_reports_duplicate_candidates_without_mutating_rows(self):
        current = review("same text", id="a", store_name="Paik's Noodle Sila")
        current["review_key"] = scraper.canonical_review_hash(current)
        legacy = dict(current, id="b", store_name="Paiks Noodle Mongolia", review_key="legacy")
        ungrouped = review("missing store", id="c", store_name="")
        rows = [current, legacy, ungrouped]
        before = [dict(row) for row in rows]
        with (
            patch.object(scraper, "supabase_request", return_value=rows) as request,
            patch.object(scraper, "sync_playwright") as browser,
            patch("builtins.print") as log,
        ):
            scraper.run_repair_only()
        request.assert_called_once()
        self.assertEqual(request.call_args.args, ("GET", "reviews"))
        browser.assert_not_called()
        self.assertEqual(rows, before)
        record = next(args.args[0] for args in log.call_args_list if args.args[0].startswith("REVIEW_INTEGRITY_AUDIT "))
        self.assertEqual(json.loads(record.removeprefix("REVIEW_INTEGRITY_AUDIT ")), {
            "review_rows": 3, "possible_duplicate_groups": 1, "noncanonical_keys": 1, "missing_store_names": 1,
        })

    def test_repair_read_failure_propagates_without_fallback_writes(self):
        with (
            patch.object(scraper, "supabase_request", side_effect=RuntimeError("read interrupted")) as request,
            patch("builtins.print"),
            self.assertRaisesRegex(RuntimeError, "read interrupted"),
        ):
            scraper.run_repair_only()
        request.assert_called_once()
        self.assertEqual(request.call_args.args, ("GET", "reviews"))

    def test_seed_stops_if_schema_cache_does_not_expose_review_key(self):
        rows = [{"review_key": "key", "rating": 4}]
        error = RuntimeError("Could not find the 'review_key' column of 'reviews' in the schema cache")
        with patch.object(seed, "supabase_request", side_effect=error) as request, self.assertRaises(RuntimeError) as failure:
            seed.upload_reviews(rows)
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["body"], rows)
        self.assertIs(failure.exception, error)


if __name__ == "__main__":
    unittest.main()
