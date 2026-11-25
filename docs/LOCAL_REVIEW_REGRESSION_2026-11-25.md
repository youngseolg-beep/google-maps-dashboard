# Local Chrome regression check — 2026-11-25 (KST)

Manual user-supplied PowerShell result. Existing Windows checkout; exact local
commit was not reported. This is not a test of the staged development bundle.

- Store: Saemaeul Central Eastville (Thailand).
- Explicit expected count: 167 (previous observation, not freshly read Overview).
- Initial 8 unique cards, 159 additional, 167 observed.
- 68 adaptive wheel rounds; 130.3 seconds scrolling, 136.4 seconds total.
- Retained DOM: true; 167 visible cards at finish.
- Review tab selected, no unexpected context/page closure or crash.
- Result: LOCAL_EXPECTED_COUNT_MATCHED, one attempt.
- Database writes: false. Field/body audit: not run.
- Login state, full content, all-store stability, current Overview count and
  production readiness remain unverified.

Previous observed adaptive check on Nov 24: 167/167, 67 rounds, 128.2 seconds
scrolling (prior manual test record). Overnight recurrence was not observed
in this one store on Nov 25. Do not infer general reliability from this sample.

Deployment policy: retain existing test/production branch refs until combined
QA bundle is ready. Do not activate the 08:00 KST scheduled task before final
manual production acceptance. Do not reset the existing browser profile.
