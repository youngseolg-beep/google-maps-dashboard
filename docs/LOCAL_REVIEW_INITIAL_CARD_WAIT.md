# Taiwan automatic count initial-load failure
Observed on 2026-11-26 at 123bffc: verified English, exact store, automatic
Overview total 6350 on both observations. Zero reviews, zero scroll rounds;
wait_for_review_cards failed after the prior 12-second selector timeout.
Cause of empty UI is unconfirmed; do not infer access block or slow loading.
Replace single selector timeout with up to 45 one-second waits, checking
access and place/tab context each observation. Count only existing exact
visible review-card selector; other visible ID/class/feed/busy counts are
diagnostic, not fallback extraction. No reload or retries. Batch retains
aggregate evidence and UI summary. Report size-based count budget before
initial wait so pre-scroll failures reflect effective limits. Self-test
fixtures staged, not executed. No production DB or refs changed.
