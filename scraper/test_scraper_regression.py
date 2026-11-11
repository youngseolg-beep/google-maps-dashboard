import importlib.util
from pathlib import Path
import sys
import types
import unittest


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


class ReviewCrawlerRegressionTests(unittest.TestCase):
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

    def test_recent_stop_requires_verified_depth_and_consecutive_existing_reviews(self):
        self.assertFalse(scraper.should_stop_recent_collection(1, 20, 6))
        self.assertFalse(scraper.should_stop_recent_collection(2, 9, 6))
        self.assertFalse(scraper.should_stop_recent_collection(2, 12, 2))
        self.assertTrue(scraper.should_stop_recent_collection(2, 12, 3))

    def test_feed_growth_prevents_false_stall_when_no_new_candidates_are_found(self):
        self.assertTrue(scraper.feed_grew(10, 20, 10, 20))
        self.assertTrue(scraper.feed_grew(20, 20, 10, 15))
        self.assertFalse(scraper.feed_grew(20, 20, 15, 15))


if __name__ == "__main__":
    unittest.main()
