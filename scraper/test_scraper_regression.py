import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock
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


if __name__ == "__main__":
    unittest.main()
