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

    def test_scroll_target_falls_back_to_review_card_ancestor_without_feed_role(self):
        page = Mock()
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.is_visible.return_value = False
        ancestor = Mock()
        page.locator.return_value.first.evaluate_handle.return_value.as_element.return_value = ancestor
        with patch("builtins.print"):
            target = scraper.get_scroll_target(page)
        self.assertIs(target, ancestor)
        script = page.locator.return_value.first.evaluate_handle.call_args.args[0]
        self.assertIn("card.parentElement", script)
        self.assertIn("scrollHeight > el.clientHeight + 30", script)
        self.assertIn("rect.width > 0", script)

    def test_scroll_target_rejects_non_scrollable_review_ancestor(self):
        page = Mock()
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.is_visible.return_value = False
        page.locator.return_value.first.evaluate_handle.return_value.as_element.return_value = None
        with patch("builtins.print"):
            self.assertIsNone(scraper.get_scroll_target(page))

    def test_scroll_target_without_review_cards_does_not_select_place_pane(self):
        page = Mock()
        page.locator.return_value.count.return_value = 0
        with patch("builtins.print"):
            self.assertIsNone(scraper.get_scroll_target(page))
        page.locator.return_value.first.evaluate_handle.assert_not_called()

    def test_scroll_target_ignores_visible_non_scrollable_feed(self):
        page = Mock()
        ancestor = Mock()
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.first.evaluate_handle.return_value.as_element.return_value = ancestor
        self.assertIs(scraper.get_scroll_target(page), ancestor)
        page.locator.return_value.is_visible.assert_not_called()

    def test_hover_timeout_uses_original_mouse_fallback(self):
        page = Mock()
        target = Mock()
        target.hover.side_effect = TimeoutError("not hoverable")
        target.bounding_box.return_value = {"x": 10, "y": 20, "width": 100, "height": 80}
        with patch.object(scraper, "get_scroll_target", return_value=target), patch("builtins.print"):
            self.assertTrue(scraper.scroll_reviews(page))
        page.mouse.move.assert_called_once_with(60, 60)
        page.mouse.wheel.assert_called_once_with(0, 8000)
        page.keyboard.press.assert_called_once_with("PageDown")

    def test_scroll_targets_review_feed_with_legacy_wheel_and_page_down(self):
        page = Mock()
        feed = Mock()
        with patch.object(scraper, "get_scroll_target", return_value=feed):
            self.assertTrue(scraper.scroll_reviews(page))
        feed.hover.assert_called_once_with(timeout=2000)
        page.mouse.wheel.assert_called_once_with(0, 8000)
        page.keyboard.press.assert_called_once_with("PageDown")
        self.assertEqual(page.wait_for_timeout.call_args_list, [call(900), call(1400)])

    def test_scroll_without_review_feed_uses_original_mouse_fallback(self):
        page = Mock()
        with patch.object(scraper, "get_scroll_target", return_value=None), patch("builtins.print"):
            self.assertFalse(scraper.scroll_reviews(page))
        page.mouse.wheel.assert_not_called()
        page.keyboard.press.assert_not_called()

    def test_failed_scroll_records_partial_evidence_and_stops_retrying(self):
        class EmptyCards:
            def count(self):
                return 0

        evidence = {}
        with patch("builtins.print"), \
             patch.object(scraper, "click_more_buttons"), \
             patch.object(scraper, "click_original_review_buttons"), \
             patch.object(scraper, "get_review_cards", return_value=(EmptyCards(), ".jftiEf")), \
             patch.object(scraper, "scroll_reviews", return_value=False) as scroll:
            found = scraper.extract_reviews(
                Mock(), STORE, [], newest_verified=False, collection_evidence=evidence
            )
        self.assertEqual(found, [])
        self.assertEqual(scroll.call_count, 1)
        self.assertTrue(evidence["scroll_target_missing"])
        self.assertFalse(evidence["full_coverage_verified"])

    def test_empty_review_feed_stops_after_stall_threshold(self):
        class EmptyCards:
            def count(self):
                return 0

        evidence = {}
        with (
            patch("builtins.print"),
            patch.object(scraper, "click_more_buttons"),
            patch.object(scraper, "click_original_review_buttons"),
            patch.object(scraper, "get_review_cards", return_value=(EmptyCards(), ".jftiEf")),
            patch.object(scraper, "scroll_reviews", return_value=True) as scroll,
            patch.object(scraper, "diagnose_review_access") as diagnose,
        ):
            found = scraper.extract_reviews(
                Mock(), STORE, [], newest_verified=False, collection_evidence=evidence
            )
        self.assertEqual(found, [])
        self.assertEqual(scroll.call_count, scraper.STOP_STALLED_ROUNDS - 1)
        self.assertTrue(evidence["feed_stalled"])
        self.assertFalse(evidence["full_coverage_verified"])
        diagnose.assert_called_once()

    def test_stalled_review_feed_is_reported_as_partial(self):
        class OneCardList:
            def count(self):
                return 1

            def nth(self, index):
                return Mock()

        evidence = {}
        with patch("builtins.print"), \
             patch.object(scraper, "click_more_buttons"), \
             patch.object(scraper, "click_original_review_buttons"), \
             patch.object(scraper, "get_review_cards", return_value=(OneCardList(), ".jftiEf")), \
             patch.object(scraper, "expand_review_text"), \
             patch.object(scraper, "get_review_text", return_value="A complete and useful review"), \
             patch.object(scraper, "get_review_date", return_value="2 weeks ago"), \
             patch.object(scraper, "get_review_author", return_value="Reviewer A"), \
             patch.object(scraper, "get_review_rating", return_value=5), \
             patch.object(scraper, "scroll_reviews", return_value=True), \
             patch.object(scraper, "diagnose_review_access") as diagnose:
            found = scraper.extract_reviews(
                Mock(), STORE, [], newest_verified=False, collection_evidence=evidence
            )
        self.assertEqual(len(found), 1)
        self.assertTrue(evidence["feed_stalled"])
        self.assertFalse(evidence["full_coverage_verified"])
        self.assertEqual(evidence["observed_review_count"], 1)
        diagnose.assert_called_once()

    def test_successful_scroll_does_not_mark_target_missing(self):
        class EmptyCards:
            def count(self):
                return 0

        evidence = {}
        with patch("builtins.print"), \
             patch.object(scraper, "click_more_buttons"), \
             patch.object(scraper, "click_original_review_buttons"), \
             patch.object(scraper, "get_review_cards", return_value=(EmptyCards(), ".jftiEf")), \
             patch.object(scraper, "scroll_reviews", return_value=True) as scroll:
            scraper.extract_reviews(
                Mock(), STORE, [], newest_verified=False, collection_evidence=evidence
            )
        self.assertEqual(scroll.call_count, scraper.STOP_STALLED_ROUNDS - 1)
        self.assertFalse(evidence["scroll_target_missing"])

    def test_selected_reviews_tab_without_feed_is_partial(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/test"
        page.get_by_role.return_value.first.count.return_value = 1
        page.locator.return_value.filter.return_value.count.side_effect = [0, 1]
        page.locator.return_value.count.return_value = 5
        with patch("builtins.print"):
            self.assertFalse(scraper.open_reviews_panel(page))
        page.locator.assert_any_call("[role='tab'][aria-selected='true']")
        page.get_by_role.return_value.first.click.assert_called_once()
        self.assertFalse(any(
            "a[href" in str(item.args[0]) for item in page.locator.call_args_list
        ))

    def test_reviews_panel_aborts_if_click_leaves_maps(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/test"
        page.get_by_role.return_value.first.count.return_value = 1

        def navigate(*args, **kwargs):
            page.url = "https://www.google.com/search?q=unrelated"

        page.get_by_role.return_value.first.click.side_effect = navigate
        with patch("builtins.print"):
            self.assertFalse(scraper.open_reviews_panel(page))
        page.locator.assert_not_called()

    def test_reviews_feed_confirms_full_panel_without_link_fallback(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/test"
        page.get_by_role.return_value.first.count.return_value = 1
        page.locator.return_value.filter.return_value.count.return_value = 1
        with patch("builtins.print"):
            self.assertTrue(scraper.open_reviews_panel(page))
        page.get_by_role.return_value.first.click.assert_called_once()

    def test_unselected_reviews_tab_does_not_confirm_panel(self):
        page = Mock()
        page.get_by_role.return_value.first.count.return_value = 1
        page.locator.return_value.filter.return_value.count.return_value = 0
        with patch("builtins.print"):
            self.assertFalse(scraper.open_reviews_panel(page))

    def test_overview_preview_feed_never_bypasses_reviews_click(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/test"
        # A review feed/preview is visible even though Overview is selected.
        page.locator.return_value.filter.return_value.count.return_value = 1
        evidence = {}
        with (
            patch("builtins.print"),
            patch.object(scraper, "build_url_candidates", return_value=[page.url]),
            patch.object(scraper, "click_cookie_buttons"),
            patch.object(scraper, "is_valid_google_maps_place_page", return_value=True),
            patch.object(scraper, "is_reviews_tab_selected", return_value=False),
            patch.object(scraper, "open_reviews_panel", return_value=False) as open_panel,
            patch.object(scraper, "wait_for_reviews") as wait,
            patch.object(scraper, "extract_reviews") as extract,
        ):
            result = scraper.scrape_store(
                page, {**STORE, "url": page.url},
                collection_evidence=evidence,
            )
        open_panel.assert_called_once_with(page)
        wait.assert_not_called()
        extract.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["collected_count"], 0)
        self.assertEqual(result["collection_issue"], "review_panel_unverified_partial")
        self.assertTrue(evidence["review_panel_unverified"])

    def test_unopened_reviews_panel_is_recorded_as_partial(self):
        page = Mock()
        page.locator.return_value.filter.return_value.count.return_value = 0
        existing = review("Existing full review text that is long enough")
        evidence = {}
        with (
            patch("builtins.print"),
            patch.object(scraper, "build_url_candidates", return_value=["https://maps.google.com/example"]),
            patch.object(scraper, "click_cookie_buttons"),
            patch.object(scraper, "is_valid_google_maps_place_page", return_value=True),
            patch.object(scraper, "open_reviews_panel", return_value=False),
            patch.object(scraper, "wait_for_reviews", return_value=True),
            patch.object(scraper, "extract_reviews", return_value=[]),
        ):
            result = scraper.scrape_store(
                page, {**STORE, "url": "https://maps.google.com/example"},
                [existing], collection_evidence=evidence
            )
        self.assertTrue(result["ok"])
        self.assertTrue(evidence["review_panel_unverified"])
        self.assertEqual(result["collection_issue"], "review_panel_unverified_partial")

    def test_store_scan_does_not_invoke_google_sort(self):
        page = Mock()
        page.locator.return_value.filter.return_value.count.return_value = 1
        existing = review("Existing full review text that is long enough")
        evidence = {"observed_review_count": 0}
        with (
            patch("builtins.print"),
            patch.object(scraper, "build_url_candidates", return_value=["https://maps.google.com/example"]),
            patch.object(scraper, "click_cookie_buttons"),
            patch.object(scraper, "is_valid_google_maps_place_page", return_value=True),
            patch.object(scraper, "wait_for_reviews", return_value=True),
            patch.object(scraper, "set_reviews_sort_to_newest") as google_sort,
            patch.object(scraper, "extract_reviews", return_value=[]) as extract,
        ):
            result = scraper.scrape_store(
                page, {**STORE, "url": "https://maps.google.com/example"},
                [existing], collection_evidence=evidence
            )
        self.assertTrue(result["ok"])
        google_sort.assert_not_called()
        self.assertFalse(extract.call_args.kwargs["newest_verified"])

    def test_legacy_scroll_uses_wheel_and_pagedown_on_review_pane(self):
        page = Mock()
        target = Mock()
        with patch.object(scraper, "get_scroll_target", return_value=target):
            self.assertTrue(scraper.scroll_reviews(page))
        target.hover.assert_called_once_with(timeout=2000)
        page.mouse.wheel.assert_called_once_with(0, 8000)
        page.keyboard.press.assert_called_once_with("PageDown")

    def test_original_scroll_falls_back_when_pane_missing(self):
        page = Mock()
        with patch.object(scraper, "get_scroll_target", return_value=None), patch("builtins.print"):
            self.assertFalse(scraper.scroll_reviews(page))
        page.mouse.wheel.assert_not_called()
        page.keyboard.press.assert_not_called()

    def test_unverified_sort_falls_back_to_bounded_scan(self):
        class EmptyCards:
            def count(self):
                return 0
        with patch.object(scraper, "click_more_buttons"), \
             patch.object(scraper, "click_original_review_buttons"), \
             patch.object(scraper, "get_review_cards", return_value=(EmptyCards(), ".jftiEf")), \
             patch.object(scraper, "scroll_reviews") as scroll:
            result = scraper.extract_reviews(
                Mock(), STORE, [review("Existing full review text that is long enough")],
                newest_verified=False
            )
        self.assertEqual(result, [])
        self.assertEqual(scroll.call_count, scraper.STOP_STALLED_ROUNDS - 1)

    def test_unsorted_existing_store_keeps_only_new_review_candidates(self):
        saved = review("Existing full review text that is long enough")
        fresh = review("New review with completely different content", author="New Reviewer")
        cards = Mock()
        cards.count.return_value = 2
        evidence = {"observed_review_count": 0}

        def text_for_card(card):
            return saved["text"] if card is cards.nth.return_value else fresh["text"]

        # Mock nth() with stable distinct card objects, so each visible card is checked.
        old_card, new_card = Mock(), Mock()
        cards.nth.side_effect = [old_card, new_card] * scraper.MAX_SCROLL_ROUNDS
        with (
            patch("builtins.print"),
            patch.object(scraper, "click_more_buttons"),
            patch.object(scraper, "click_original_review_buttons"),
            patch.object(scraper, "get_review_cards", return_value=(cards, ".jftiEf")),
            patch.object(scraper, "expand_review_text"),
            patch.object(scraper, "get_review_text", side_effect=lambda card: saved["text"] if card is old_card else fresh["text"]),
            patch.object(scraper, "get_review_date", return_value=saved["date"]),
            patch.object(scraper, "get_review_author", side_effect=lambda card: saved["author"] if card is old_card else fresh["author"]),
            patch.object(scraper, "get_review_rating", return_value=5),
            patch.object(scraper, "scroll_reviews"),
            patch.object(scraper, "should_stop_recent_collection", return_value=True) as recent_stop,
        ):
            found = scraper.extract_reviews(Mock(), STORE, [saved], newest_verified=False, collection_evidence=evidence)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["author"], fresh["author"])
        self.assertEqual(evidence["observed_review_count"], 2)
        recent_stop.assert_not_called()

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

    def test_collection_reporting_accepts_scroll_and_stall_evidence(self):
        result = {"ok": True, "collected_count": 0, "error": "",
                  "crawled_at": "2026-11-16 16:00:00",
                  "collection_issue": "review_scroll_unavailable_partial"}
        for evidence, expected in (
            ({"observed_review_count": 5, "scroll_target_missing": True,
              "feed_stalled": False, "full_coverage_verified": False},
             "review_scroll_unavailable_partial"),
            ({"observed_review_count": 5, "scroll_target_missing": False,
              "feed_stalled": True, "full_coverage_verified": False},
             "review_feed_stalled_partial"),
        ):
            with self.subTest(expected=expected):
                row = scraper.collection_status_row(
                    STORE, attempted=True, result=result, **evidence
                )
                self.assertEqual(row["collection_status"], "PARTIAL")
                self.assertEqual(row["collection_reason"], expected)
                self.assertEqual(row["observed_review_count"], 5)

    def test_collection_reporting_does_not_upgrade_diagnostic_coverage_to_verified(self):
        row = scraper.collection_status_row(
            STORE, attempted=True, observed_review_count=5,
            full_coverage_verified=True,
            result={"ok": True, "collected_count": 5, "error": "",
                    "crawled_at": "2026-11-16 16:00:00"},
        )
        self.assertEqual(row["collection_status"], "PARTIAL")

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

    def test_auth_state_omitted_preserves_anonymous_browser_context(self):
        self.assertIsNone(scraper.load_dedicated_google_auth_state(raw=""))
        browser = Mock()
        scraper.new_crawler_context(browser, auth_state=None)
        self.assertNotIn("storage_state", browser.new_context.call_args.kwargs)

    def test_auth_state_filters_expired_and_non_google_cookies_without_logging(self):
        import base64
        state = {"cookies": [
            {"name": "SESSION", "value": "secret", "domain": ".google.com", "path": "/", "expires": 1999999999, "sameSite": "Lax", "partitionKey": "https://example.com"},
            {"name": "EXPIRED", "value": "x", "domain": ".google.com", "path": "/", "expires": 100},
            {"name": "UNRELATED", "value": "y", "domain": "example.com", "path": "/"},
        ], "origins": [{"origin": "https://example.com", "localStorage": []}]}
        raw = base64.b64encode(json.dumps(state).encode("utf-8")).decode("ascii")
        restored = scraper.load_dedicated_google_auth_state(raw=raw, now_seconds=1000)
        self.assertEqual(len(restored["cookies"]), 1)
        self.assertEqual(restored["cookies"][0]["name"], "SESSION")
        self.assertNotIn("partitionKey", restored["cookies"][0])
        self.assertEqual(restored["origins"], [])
        browser = Mock()
        scraper.new_crawler_context(browser, auth_state=restored)
        self.assertEqual(browser.new_context.call_args.kwargs["storage_state"], restored)

    def test_invalid_auth_state_fails_closed_without_secret_leak(self):
        invalid = "sensitive-but-not-base64"
        with self.assertRaises(RuntimeError) as error:
            scraper.load_dedicated_google_auth_state(raw=invalid)
        self.assertNotIn(invalid, str(error.exception))
        browser = Mock()
        browser.new_context.side_effect = RuntimeError("secret-cookie-value")
        with self.assertRaises(RuntimeError) as error:
            scraper.new_crawler_context(browser, auth_state={"cookies": []})
        self.assertNotIn("secret-cookie-value", str(error.exception))

    def test_auth_account_ui_required_before_crawling_any_stores(self):
        page = Mock()
        page.evaluate.return_value = False
        self.assertFalse(scraper.verify_dedicated_google_login(page))
        page.evaluate.return_value = True
        self.assertTrue(scraper.verify_dedicated_google_login(page))

    def test_explicit_full_reviews_control_is_used_without_generic_links(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/example"
        page.evaluate.return_value = 0
        page.locator.return_value.count.return_value = 7
        self.assertTrue(scraper.open_all_reviews_control(page))
        page.locator.return_value.nth.assert_called_once_with(0)
        page.locator.return_value.nth.return_value.click.assert_called_once()

    def test_review_more_control_ignores_untyped_mock_or_missing_control(self):
        page = Mock()
        page.evaluate.return_value = None
        self.assertFalse(scraper.open_all_reviews_control(page))
        page.locator.assert_not_called()

    def test_scroll_progress_defers_stall_while_pane_moves(self):
        class OneCardList:
            def count(self): return 1
            def nth(self, index): return Mock()
        with (
            patch("builtins.print"),
            patch.object(scraper, "click_more_buttons"),
            patch.object(scraper, "click_original_review_buttons"),
            patch.object(scraper, "get_review_cards", return_value=(OneCardList(), ".jftiEf")),
            patch.object(scraper, "expand_review_text"),
            patch.object(scraper, "get_review_text", return_value="Review body for a scrolling regression"),
            patch.object(scraper, "get_review_date", return_value="2 weeks ago"),
            patch.object(scraper, "get_review_author", return_value="Tester"),
            patch.object(scraper, "get_review_rating", return_value=4),
            patch.object(scraper, "review_pane_progress", side_effect=[
                (0, 8000), (1200, 8000), (2400, 8000), (3600, 8000), (4800, 8000)
            ]),
            patch.object(scraper, "scroll_reviews", return_value=True) as wheel,
            patch.object(scraper, "MAX_SCROLL_ROUNDS", 5),
        ):
            rows = scraper.extract_reviews(Mock(), STORE, [], newest_verified=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(wheel.call_count, 5)

    def test_cached_google_review_id_skips_repeat_parsing_without_skipping_new_ids(self):
        class CardCollection:
            def __init__(self, cards): self.cards = cards
            def count(self): return len(self.cards)
            def nth(self, index): return self.cards[index]
        first, second = Mock(), Mock()
        first.get_attribute.return_value = "same-review-id"
        second.get_attribute.return_value = "new-review-id"
        # Rounds 1/2 show the same single card; round 3 introduces a new ID.
        collections = [CardCollection([first]), CardCollection([first]),
                       CardCollection([first, second]), CardCollection([first, second])]
        evidence = {}
        with (
            patch("builtins.print"),
            patch.object(scraper, "MAX_SCROLL_ROUNDS", 4),
            patch.object(scraper, "click_more_buttons"),
            patch.object(scraper, "click_original_review_buttons"),
            patch.object(scraper, "get_review_cards", side_effect=[
                (cards, ".jftiEf") for cards in collections
            ]),
            patch.object(scraper, "get_review_text", return_value="A good restaurant and service"),
            patch.object(scraper, "get_review_date", return_value="2 weeks ago"),
            patch.object(scraper, "get_review_rating", return_value=4),
            patch.object(scraper, "get_review_author", side_effect=lambda card:
                         "Author One" if card is first else "Author Two"),
            patch.object(scraper, "expand_review_text") as expand,
            patch.object(scraper, "scroll_reviews", return_value=True),
            patch.object(scraper, "review_pane_progress", side_effect=[
                (0, 10000), (1200, 10000), (2400, 10000), (3600, 10000)
            ]),
        ):
            found = scraper.extract_reviews(Mock(), STORE, [],
                                            newest_verified=False, collection_evidence=evidence)
        self.assertEqual(len(found), 2)
        self.assertEqual(expand.call_count, 2)
        self.assertGreaterEqual(evidence["repeat_dom_cards_skipped"], 2)
        self.assertEqual(evidence["observed_review_count"], 2)

    def test_maps_url_candidates_never_create_invalid_review_suffix(self):
        short = "https://maps.app.goo.gl/AbCd1234"
        self.assertEqual(scraper.build_url_candidates(short), [short, short])
        original = ("https://www.google.com/maps/place/Test+Store/@0,0,15z/"
                    "data=!4m1!9m1!1b1?entry=ttu")
        candidates = scraper.build_url_candidates(original)
        self.assertEqual(candidates[0], original)
        self.assertTrue(any("/data=" not in u for u in candidates[1:]))
        self.assertTrue(any("!9m1!1b1" not in u for u in candidates[1:]))
        self.assertTrue(all("/maps/place/" in u for u in candidates))
        self.assertTrue(all(not u.endswith("/reviews/") for u in candidates))

    def test_english_maps_rejects_generic_page_after_navigation(self):
        page = Mock()
        page.url = "https://www.google.com/maps/@0,0,15z"
        page.locator.return_value.count.return_value = 0
        with patch.object(scraper, "is_valid_google_maps_place_page", return_value=False):
            self.assertFalse(scraper.force_google_maps_english_ui(page))

    def test_hash_uses_immutable_store_scope_to_survive_rename(self):
        store_id = "949dfe3a-782d-4142-b25d-94c650a1a7d4"
        raw_review_id = "review-id"
        original = dict(STORE, id=store_id)
        renamed = dict(original, store_name="Renamed Store")
        # The extractor passes the immutable store ID as hash scope.
        self.assertEqual(
            scraper.hash_google_source_review_id(str(original["id"]), raw_review_id),
            scraper.hash_google_source_review_id(str(renamed["id"]), raw_review_id),
        )

    def test_force_maps_english_url_uses_google_place_only(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/sample?entry=ttu&hl=ko"
        def navigate(url, **kwargs):
            page.url = url
        page.goto.side_effect = navigate
        with patch("builtins.print"):
            self.assertTrue(scraper.force_google_maps_english_ui(page))
        next_url = page.goto.call_args.args[0]
        self.assertIn("hl=en", next_url)
        self.assertIn("gl=us", next_url)
        self.assertNotIn("hl=ko", next_url)
        self.assertIn("entry=ttu", next_url)

    def test_force_maps_english_rejects_short_and_account_pages_without_navigation(self):
        for url in ("https://maps.app.goo.gl/abc123",
                    "https://accounts.google.com/signin",
                    "https://untrusted.example/maps/place/x"):
            page = Mock()
            page.url = url
            self.assertFalse(scraper.force_google_maps_english_ui(page))
            page.goto.assert_not_called()

    def test_force_maps_english_failure_is_sanitized(self):
        page = Mock()
        page.url = "https://www.google.com/maps/place/test"
        page.goto.side_effect = RuntimeError("private-account-data")
        with self.assertRaises(RuntimeError) as raised:
            scraper.force_google_maps_english_ui(page)
        self.assertNotIn("private-account-data", str(raised.exception))

    def test_unknown_rating_never_becomes_fake_five_stars(self):
        self.assertEqual(scraper.parse_rating(""), 0)
        self.assertEqual(scraper.parse_rating("Rating unavailable"), 0)
        self.assertEqual(scraper.parse_rating("4 stars"), 4)

    def test_append_plan_holds_same_author_when_translation_changes_text(self):
        existing = review("Great meals and service", author="Existing User")
        translated = review("훌륭한 음식과 서비스", author="Existing User")
        fresh = review("Very nice dinner", author="Completely New User")
        plan = scraper.plan_safe_review_append([existing], [translated, fresh])
        self.assertEqual([r["author"] for r in plan["ready"]], ["Completely New User"])
        self.assertEqual(len(plan["held"]), 1)
        self.assertEqual(plan["held_reasons"]["prior_author_collision"], 1)

    def test_append_plan_does_not_cross_contaminate_authors_between_stores(self):
        existing = review("Great meals", author="Shared User")
        another_store = review("Another restaurant", author="Shared User", store_name="Another Store")
        plan = scraper.plan_safe_review_append([existing], [another_store])
        self.assertEqual(len(plan["ready"]), 1)
        self.assertEqual(plan["held"], [])

    def test_append_plan_blocks_unknown_author_date_and_rating(self):
        candidates = [
            review("Great food", author="Anonymous"),
            review("Other experience", author="Reviewer B", rating=0),
            review("Helpful staff", author="Reviewer C", date="Unknown"),
        ]
        plan = scraper.plan_safe_review_append([], candidates)
        self.assertEqual(len(plan["held"]), 3)
        self.assertEqual(len(plan["ready"]), 0)

    def test_dry_run_generates_plan_but_never_writes_reviews(self):
        new = review("Fresh feedback", author="New Person")
        with (
            patch.object(scraper, "load_store_id_map", return_value={STORE["store_name"].casefold(): "s1"}),
            patch.object(scraper, "upsert_review_batch") as write,
            patch("builtins.print") as output,
        ):
            scraper.save_reviews([new], None, [], dry_run=True, conservative_dedupe=True)
        write.assert_not_called()
        self.assertTrue(any("REVIEW_APPEND_PLAN" in str(x) for x in output.call_args_list))

    def test_safe_append_only_submits_review_not_on_hold(self):
        old = review("Previously saved", author="Reviewer A")
        translated = review("이전 방문", author="Reviewer A")
        new = review("First time here", author="Reviewer B")
        with (
            patch.object(scraper, "load_store_id_map", return_value={STORE["store_name"].casefold(): "s1"}),
            patch.object(scraper, "upsert_review_batch") as write,
            patch("builtins.print"),
        ):
            scraper.save_reviews([translated, new], 11, [old], conservative_dedupe=True)
        write.assert_called_once()
        rows = write.call_args.args[0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["author"], "Reviewer B")

    def test_expired_google_auth_prevents_any_db_run_or_review_insert(self):
        from unittest.mock import MagicMock
        playwright = MagicMock()
        browser = playwright.return_value.__enter__.return_value.chromium.launch.return_value
        page = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        store = dict(STORE, url="https://www.google.com/maps/place/example", id="store-id")
        with (
            patch.object(scraper, "REVIEW_APPEND_MODE", "append"),
            patch.object(scraper, "load_dedicated_google_auth_state", return_value={"cookies":[{"name":"dummy"}]}),
            patch.object(scraper, "load_stores_from_supabase", return_value=[store]),
            patch.object(scraper, "select_target_stores", return_value=[store]),
            patch.object(scraper, "load_store_id_map", return_value={store["store_name"].casefold():"store-id"}),
            patch.object(scraper, "validate_store_configuration"),
            patch.object(scraper, "load_existing_reviews", return_value=[]),
            patch.object(scraper, "save_migrated_existing_reviews"),
            patch.object(scraper, "sync_playwright", return_value=playwright.return_value),
            patch.object(scraper, "new_crawler_context", return_value=context),
            patch.object(scraper, "verify_dedicated_google_login", return_value=False),
            patch.object(scraper, "create_crawl_run") as create_run,
            patch.object(scraper, "finish_crawl_run") as finish_run,
            patch.object(scraper, "upsert_review_batch") as insert,
            patch.object(scraper, "report_collection_status"),
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "전용 Google 인증 세션"):
                scraper.scrape()
        create_run.assert_not_called()
        finish_run.assert_not_called()
        insert.assert_not_called()

    def test_google_source_identity_hash_stable_and_scoped(self):
        first = scraper.hash_google_source_review_id("Bornga Dunnan Store", "google-review-id")
        repeated = scraper.hash_google_source_review_id(" bornga  dunnan store ", "google-review-id")
        other_store = scraper.hash_google_source_review_id("Saemaeul Seoul St.", "google-review-id")
        self.assertEqual(first, repeated)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, other_store)
        self.assertNotIn("google-review-id", first)

    def test_google_source_identity_hash_rejects_invalid_values(self):
        self.assertIsNone(scraper.hash_google_source_review_id("Store", ""))
        self.assertIsNone(scraper.hash_google_source_review_id("Store", None))
        self.assertIsNone(scraper.hash_google_source_review_id("", "id"))
        self.assertIsNone(scraper.hash_google_source_review_id("Store", "x" * 2049))

    def test_source_identity_metadata_does_not_change_legacy_review_key(self):
        standard = review("Good restaurant")
        tagged = dict(standard, google_source_id_hash="a" * 64)
        self.assertEqual(scraper.canonical_review_hash(standard), scraper.canonical_review_hash(tagged))
        row = scraper.prepare_review_row(
            tagged, {STORE["store_name"].casefold(): "store-id"}, None
        )
        self.assertNotIn("google_source_id_hash", row)
        self.assertNotIn("google-review-id", str(row))



if __name__ == "__main__":
    unittest.main()
