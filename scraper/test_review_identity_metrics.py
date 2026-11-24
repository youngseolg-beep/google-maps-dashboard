import unittest
from review_identity_metrics import (
    script_counts, source_identity_counts, reconciliation_blockers,
    reconciliation_verdict, should_retry_read_only_store,
)


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


class ReconciliationAcceptanceGateTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "country": "Taiwan",
            "extraction_status": "SCANNED",
            "existing_db_rows": 849,
            "live_candidates": 3,
            "observed_review_count": 3,
            "matching_or_potential_total": 3,
            "source_id_metrics": {
                "candidates": 3,
                "hashed_source_ids_valid": 3,
                "hashed_source_ids_missing": 0,
                "hashed_source_ids_invalid": 0,
                "hashed_source_ids_duplicate": 0,
                "source_id_reused_with_distinct_text": 0,
            },
            "browser_state": {
                "signed_in_maps_ui": True, "page_category": "maps_place"
            },
            "completeness_verified": True,
        }

    def test_retry_only_historical_zero_candidate_store(self):
        self.assertTrue(should_retry_read_only_store(111, 0, 1))
        self.assertTrue(should_retry_read_only_store(111, None, 1))
        self.assertFalse(should_retry_read_only_store(0, 0, 1))
        self.assertFalse(should_retry_read_only_store(111, 96, 1))
        self.assertFalse(should_retry_read_only_store(111, 0, 2))
        self.assertFalse(should_retry_read_only_store(True, 0, 1))

    def test_verified_store_has_no_acceptance_blockers(self):
        self.assertEqual(reconciliation_blockers(self.row), [])

    def test_historical_store_with_zero_cards_cannot_pass(self):
        thai = {
            **self.row, "country": "Thailand",
            "existing_db_rows": 111, "live_candidates": 0,
            "observed_review_count": 0, "matching_or_potential_total": 0,
            "completeness_verified": False,
        }
        blockers = reconciliation_blockers(thai)
        self.assertIn("historical_store_zero_live_reviews", blockers)
        verdict = reconciliation_verdict([self.row, thai], {"Taiwan", "Thailand"})
        self.assertEqual(verdict["status"], "PARTIAL")
        self.assertFalse(verdict["database_writes_approved"])

    def test_unverified_coverage_blocks_pass_despite_valid_ids(self):
        row = {**self.row, "completeness_verified": False}
        self.assertEqual(
            reconciliation_verdict([row], {"Taiwan"})["status"], "PARTIAL"
        )
        self.assertIn("full_feed_coverage_unverified", reconciliation_blockers(row))

    def test_missing_or_duplicate_source_ids_block_pass(self):
        row = {**self.row, "source_id_metrics": {
            **self.row["source_id_metrics"],
            "hashed_source_ids_valid": 2,
            "hashed_source_ids_missing": 1,
            "hashed_source_ids_duplicate": 1,
        }}
        blockers = reconciliation_blockers(row)
        self.assertIn("source_review_id_coverage_incomplete", blockers)
        self.assertIn("source_review_id_collision", blockers)

    def test_missing_store_or_duplicate_country_blocks_pass(self):
        self.assertEqual(
            reconciliation_verdict([self.row], {"Taiwan", "Mongolia"})["status"],
            "PARTIAL"
        )
        repeated = reconciliation_verdict(
            [self.row, self.row], {"Taiwan"}
        )
        self.assertEqual(repeated["status"], "PARTIAL")
        self.assertIn("duplicate_or_unknown_country", repeated["store_gate_reasons"]["scope"])

    def test_mismatched_counts_and_missing_login_block_pass(self):
        row = {**self.row,
               "matching_or_potential_total": 2,
               "browser_state": {"signed_in_maps_ui": False, "page_category": "maps_other"}}
        blockers = reconciliation_blockers(row)
        self.assertIn("review_reconciliation_count_mismatch", blockers)
        self.assertIn("authenticated_maps_ui_unverified", blockers)
        self.assertIn("maps_place_page_unverified", blockers)

    def test_verified_scope_pass_does_not_approve_writes(self):
        verdict = reconciliation_verdict([self.row], {"Taiwan"})
        self.assertEqual(verdict["status"], "PASS")
        self.assertFalse(verdict["database_writes_approved"])


if __name__ == "__main__":
    unittest.main()
