# Large-store count budget pilot
Opt-in batch --scale-count-budget applies only to count-only mode. Estimate
two new IDs per round plus 40 rounds of margin, four seconds per planned round.
Never shorten existing 1800 ms scroll waits, alter wheel sizes, or increase
hard caps (5000 rounds / 10800 seconds / 10000 IDs). Default remains unchanged.
For 6332 displayed reviews the default 240/600 becomes 3206/10800 when enabled;
this is a planning budget, not a speed or full coverage guarantee. Explicit
higher input budgets are retained within hard limits. Reports include the
effective limits and measured elapsed scroll time. Dispose per-round pane
handles and recheck place/tab/access immediately before counting new IDs.
No DB changes. New tests staged, not yet executed. Next: run offline suite,
then one auto-total Thailand count pilot; large-store benchmark separately.
