# Source append mapping safety — 2026-11-26
After c76c0b4 newest-head behavioral match (30/30 twice) and staged
fa6ba38 GET-only ordered comparison, harden the detached preview before
actual storage integration. Check canonical key and normalized author
collisions across all observed candidates, including linked records with
changed metadata and malformed/duplicate source IDs. Do not silently
overwrite a source-to-key association in a dict. Report held mapping
counts separately; legacy preview sees only remaining eligible rows.
Reject malformed candidate containers/text and guard unhashable source
IDs during simulated replay. Additional synthetic self-tests staged.
These checks operate on adapted candidates, not all raw reviews; held
adaptation records still require separate evidence at a real write gate.
No write authority, no production schema changes, no branch ref updates.
Full offline QA and real newest ordered DB comparison still unverified
at this commit. Real PostgreSQL transaction QA remains outstanding.
