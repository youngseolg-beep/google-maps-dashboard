# Newest sort selection diagnostic
2026-11-26: 0986a04 user Windows offline QA 16/16 PASS, 17 files
compiled. Thailand live run: exact Reviews context, 10 DOM cards,
NEWEST_SORT_SELECTION_UNVERIFIED at verify_newest_sort; no head compared.
Existing strict selection check uses aria-checked/aria-selected only.
Do not infer success from click or reorder. Add bounded structural
evidence for known menu options before click, after click, and recheck.
No arbitrary labels, text payloads, credentials, or raw IDs in evidence.
No changes to selection acceptance, scroll cadence, or production code
path (opt-in diagnostic only). On failure --inspect-on-failure preserves
the menu for visual confirmation. New code staged, not run in Chrome.
No branch refs, production database or deployments changed.
