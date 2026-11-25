# Registered-store count-only pilot
The prior 13-stage offline result at caf60de remains valid. This change extends
the existing registered-store sample launcher to explicit count-only checks.
Use --scope registered --mode count --plan-only to list stable task keys and
holds, without launching Chrome. Supply fresh visible totals via repeated
--expected registered_<key>=COUNT. Untargeted stores remain in the report
as held; invalid, duplicate or mapping-held keys are rejected. Count-only
does not authorize full coverage, DB append, or automatic scheduling. English
and exact place identity gates remain in place. Full body/DB audit still has
known-store limits. New code and fixtures staged, not executed at this ref.
No production DB mutation or branch update.
