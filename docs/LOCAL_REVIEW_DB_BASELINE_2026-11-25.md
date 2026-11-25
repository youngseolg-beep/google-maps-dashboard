# Supabase read-only baseline — 2026-11-25 KST

Aggregate SELECT via connected project sv-review-master. No write, DDL, role or policy changes.
- Saemaeul Central Eastville, Thailand: active, 111 saved rows, 111 distinct review keys, 109 current text present, 2 marked no text, latest collected_at 2026-10-08 UTC.
- Bornga Dunnan Store, Taiwan: active, 849 saved rows, 849 distinct keys, 735 current text present, 114 marked no text, latest collected_at 2026-10-28 UTC.
- Both: zero non-null ratings outside 1–5, zero legacy-only text or date, zero conflicts between nonblank text and review_text.
- Both registered full place pairs match repository URLs. RLS enabled on stores and reviews; SELECT policies for stores public and reviews anon observed. SQL connector visibility does not prove local Data API visibility.
- Actual Google Maps observation on c149c9e: 167 unique Thai reviews. Difference 56 is not a proven new-row count.
- Local audit now has standalone credential/identity/history read preflight. It does not launch Chrome or authorize writes. Full record reconciliation remains pending local GET access and scoped-body validation.
