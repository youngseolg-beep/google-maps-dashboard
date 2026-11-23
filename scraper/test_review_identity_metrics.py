import unittest
from review_identity_metrics import script_counts, source_identity_counts


class IdentityLanguageMetricsTests(unittest.TestCase):
    def test_source_ids_are_counted_without_leaking_them(self):
        reviews = [
            {"google_source_id_hash": "a" * 64, "text": "An excellent visit."},
            {"google_source_id_hash": "b" * 64, "text": "Great noodles."},
            {"google_source_id_hash": None, "text": "리뷰"},
            {"google_source_id_hash": "not-a-hash", "text": "Other"},
        ]
        result = source_identity_counts(reviews)
        self.assertEqual(result["hashed_source_ids_valid"], 2)
        self.assertEqual(result["hashed_source_ids_missing"], 1)
        self.assertEqual(result["hashed_source_ids_invalid"], 1)
        self.assertNotIn("a" * 64, str(result))
        self.assertNotIn("An excellent visit", str(result))

    def test_repeated_source_hash_and_changed_body_counted(self):
        reviews = [
            {"google_source_id_hash": "a" * 64, "text": "English"},
            {"google_source_id_hash": "a" * 64, "text": "English"},
            {"google_source_id_hash": "a" * 64, "text": "한국어"},
        ]
        result = source_identity_counts(reviews)
        self.assertEqual(result["hashed_source_ids_duplicate"], 2)
        self.assertEqual(result["source_id_reused_with_distinct_text"], 1)

    def test_scripts_are_nonexclusive_counts(self):
        reviews = [
            {"text": "Delicious food"},
            {"text": "맛있어요"},
            {"text": "Korean 맛집"},
            {"text": "很好"},
            {"text": "อร่อย"},
            {"text": "Очень вкусно"},
            {"text": ""},
            {"review_text": "Original saved body"},
        ]
        counts = script_counts(reviews)
        self.assertEqual(counts["total"], 8)
        self.assertEqual(counts["empty"], 1)
        self.assertEqual(counts["latin"], 3)
        self.assertEqual(counts["hangul"], 2)
        self.assertEqual(counts["mixed_hangul_latin"], 1)
        self.assertEqual(counts["han"], 1)
        self.assertEqual(counts["thai"], 1)
        self.assertEqual(counts["cyrillic"], 1)

    def test_empty_and_missing_values_are_safe(self):
        self.assertEqual(source_identity_counts([])["candidates"], 0)
        self.assertEqual(script_counts([{}, {"text": None}])["empty"], 2)


if __name__ == "__main__":
    unittest.main()
