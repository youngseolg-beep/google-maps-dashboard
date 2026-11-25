# Source-aware append/replay QA (staged)
- No new DB schema or write path. Existing 111 rows remain read-only.
- A source registry supplied to the pure preview must be valid and unique
  in both directions. Linked IDs are excluded before legacy matching.
- Unlinked IDs still require legacy matching and append preflight.
- Actual comparison optionally simulates only the hypothetical first append,
  assigns transient synthetic row IDs, and replays both identical and modified
  payloads. No historical links are proposed as approved.
- Replay success does not establish that the first hypothetical append is
  correct, complete or approved. Body-scope holds and legacy collisions remain.
- Added both source modules to offline runner compile and individual suites.
