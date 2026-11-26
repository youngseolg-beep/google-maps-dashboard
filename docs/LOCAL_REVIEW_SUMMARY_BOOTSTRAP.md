# Initial review summary scroll bootstrap
2026-11-26 Taiwan screenshot: selected Reviews, 6350 reviews, rating summary,
Gemini summary and visible Sort button/keyword chips. Prior 45s timeout had
zero cards, zero feed, zero busy nodes. Hypothesis: actual cards are lazily
created below the summary; not confirmed from screenshot alone.
The old scroll pane requires a card to exist, so add a bounded bootstrap
anchored to a unique visible Sort button and its scrollable ancestor. Use
normal mouse wheel only, no sorting or filtering clicks, no reload, at most
six 600px wheel actions at 3s intervals. Preserve verified place/tab and
access gates. Stop bootstrap when exact cards appear. Evidence in aggregate
report; no extra selectors accepted as reviews. Initial wheel rounds separate
from count-scroll rounds. New fixtures staged, not executed. Next small
Taiwan probe with 1 count scroll round to verify initial card visibility.
No production DB, deployment or branch change.
