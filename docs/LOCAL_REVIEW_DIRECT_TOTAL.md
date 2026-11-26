# Direct Reviews total pilot
2026-11-26 cf116e1: actual offline QA 13/13 PASS. Taiwan auto-total probe
failed before initial bootstrap, OVERVIEW_NOT_VERIFIED. UI summary already
had 8 review cards; screenshot also shows selected Reviews and 6350 reviews.
Do not click Overview when Reviews is already selected. Preserve stable
Overview count when obtained before entering Reviews; otherwise read a
separate decimal rating and explicit count label before the unique Sort
button, outside review cards. Two matching observations in verified context
are mandatory; no guess or manual total fallback. Review-specific selector
has not yet been tested against live DOM. Existing bootstrap is unchanged.
No production data, ref or deployment changes. One small read-only probe
should verify direct total and initial card count before full scan.
