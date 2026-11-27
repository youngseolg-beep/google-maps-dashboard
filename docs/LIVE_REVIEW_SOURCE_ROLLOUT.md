# Live writer rollout

The actual `local_review_append_batch.py` and single-store append entry point
now use `SourceWriter` in `local_review_append_pilot.py`. The source-identity
migration was reported applied before this acceptance fix, preserving all 11,071
pre-existing production reviews. This fix executes no migration or production
write. The old single-POST helper remains for existing compatibility
tests, and is no longer called by either live append entry point.

## Database approval

For a new environment, review `migrations/20261127_review_source_append.sql` before applying it separately.
The already migrated production environment needs no additional SQL for this fix.
It adds store-scoped source links, immutable request receipts, a versioned recent
boundary, one supporting index, and the `SECURITY INVOKER` append RPC. New tables
have RLS enabled. Only `service_role` receives RPC execution and table access.
The RPC explicitly allowlists review columns and never updates/deletes reviews.
It serializes writes for a store and commits review inserts, source links, and
the receipt in one PostgREST transaction. Existing keys and review rows remain
unchanged. New review keys are derived from the immutable store/source hash.

Recheck the actual reviews column types, constraints, triggers, inherited grants,
and service-role permissions before approval. The fixture uses UUID review IDs,
numeric ratings, text review dates, nullable dates, and timestamptz capture fields.
The service credential is still privileged outside this RPC. Existing collectors
that do not use source links must not write concurrently during the rollout.
No automatic legacy rekeying or historical row enrichment takes place.

## Recovery and coverage

The user-private `%LOCALAPPDATA%\SVReviewMaster\review-source-requests.sqlite3`
contains original request payloads, including review text and author names. Keep
it outside Git, restrict access to the executing Windows account, retain it on
persistent storage, and back it up securely. It never contains the API credential
or Chrome cookies. Receipt checks happen before every replay with the same
operation ID and payload. The journal is bound to its Supabase project URL and
refuses recovery into a different project. A lost response leaves a pending local request;
the next process reconciles/replays it before collecting that store again.

During scrolling, only previously unaudited IDs have their metadata/body read.
Verified batches are persisted immediately. Restarting still opens the listing
at the top. Stored source IDs avoid repeating their body audits or insertion.
This does not provide direct restoration of a Google Maps scroll position.

`--mode recent` requires explicit Newest UI verification and stable ordered IDs.
It stops on a previously committed 30-ID boundary or a separately tracked local
observed frontier, not after 100 cards. The latter is explicitly not a committed
collection baseline or a claim of complete coverage.
Already inserted prefixes from a partial run are supported. Without a boundary,
the first recent run must reach the displayed total before bootstrap. Any missing
link, held review, unverified sort, changed order, incomplete coverage, or version
conflict preserves the previous boundary. Stores with fewer than 30 reviews scan
their full bounded feed each time and do not establish a 30-ID boundary.
Hard scan/time limits still apply and are reported as incomplete/backlog unknown.
`--recent-limit` and `--max-body-batches` are accepted as deprecated compatibility
options; they no longer decide when the live streaming writer stops.

The same SQLite journal retains outstanding historical source hashes/reasons
in `historical_backlog` and a versioned daily observation head in `daily_frontiers`.
These are local runtime tables; production schema and RPC are unchanged.
Backlog persistence and observation-head advancement occur atomically. The
initial observation head requires verified Newest, a stable ordered prefix,
at least 30 IDs, and a finished bounded scan. Partial initial coverage is marked
unknown. Subsequent heads require an exact 30-ID overlap or a full scan; a
timeout before the previous head does not discard that previous head. Unverified
sorting, failed context checks or pending write receipts cannot advance it.
Daily runs can therefore append new reviews without re-scanning the entire old
backlog. They still report PARTIAL, `historical_backlog`, and
`historical_coverage_unknown`. Separate backfill runs revisit outstanding IDs.
The database committed baseline remains blocked while local backlog exists.

Legacy text rows are linked only after a unique whitespace-normalized full-body/rating match
with a whitespace/case-normalized author. Relative date labels may drift.
Multiple matching historical rows stay held even if one current date label
matches; conflicting explicit calendar dates also stay held. Empty-body legacy
matches still require the date label to agree. The writer sends the selected
historical author/date/text as an immutable preimage to the existing RPC, which
revalidates equality against that row. This changes no historical fields and
requires no SQL update. Ambiguous legacy identities remain held. Same-author
distinct source IDs are accepted once there is no unresolved same-author legacy
row. A changed display name on an unlinked legacy record cannot be reliably
reconciled automatically. Review IDs establish identity, not completeness.

Rating-only insertion requires two stable structural checks, a rating/author
control, no customer text container, no unresolved More/original control, and no
unrecognized visible text. Hidden, blank, or changed body markup stays held.
Visible star labels on spans are accepted without requiring `role=img`.
Live Eastville DOM exposed structured details under `.RfDO5c`, including
`<b>Food:</b>`, Service and Atmosphere labels. These details and owner-response
controls are excluded from the rating-only customer-text absence check.
Hidden loading indicators do not count as an active customer-body load.
The details-only More button is associated with that observed region when
there is no customer body; owner's More buttons remain excluded.
More/original resolution requires the control to disappear, a valid scoped
body, unchanged card identity and the final body fingerprint binding. Text
length or fingerprint changes are recorded as observations, not mandatory gates.
Each held source has one primary reason: missing author/rating/audit, failed
click, unresolved More/original, unverified resolution, missing body, unverified
rating-only state, unverified customer-body scope, changed body fingerprint,
or a specific legacy/source identity conflict. Other valid sources in the same
window still persist while held sources prevent boundary advancement.
Unknown dates are stored with `review_date=NULL`, `review_date_source=unknown`
and the visible date label or `Unknown`. They do not silently disappear or become
today's date. Dashboard date-dependent analytics may exclude them.

## Tests and next gate

Run existing `local_review_offline_qa.py`, `unittest` regressions, and dashboard
tests. `test_live_source_writer.py` tests actual writer planning without a DB.
For all storage tests, start a NEW disposable local PostgreSQL/PostgREST instance,
apply `review_source_writer_fixture.sql` then the migration, insert a random
marker into `sv_writer_fixture`, and set `SV_WRITER_TEST_API` to its loopback URL,
`SV_WRITER_TEST_TOKEN` to its temporary service-role JWT, and
`SV_WRITER_TEST_MARKER` to the marker. The suite checks the marker before writing.
Never point the fixture at an existing database. The suite exercises actual RPCs,
including receipt loss and recovery in a fresh Python process.

For the already migrated project, re-run the existing Eastville single-store
append command and compare inserted/linked/held counts and primary hold reasons.
Then repeat it for deduplication. Validate rating-only structure and unknown dates
against live Maps before treating those cases as accepted live evidence.
Only approve a wider daily run after observing boundary establishment and the
next incremental run. No Google session export or access-restriction bypass is
part of this change. A browser action or displayed count alone never establishes
independently complete newest-review coverage.

## Eastville read-only acceptance evidence

Using the dedicated local profile, public GET-only store/review reads and 81
locally confirmed source receipts, the pre-fix preview reproduced 167 observed,
36 legacy ambiguity, 32 rating-only, 17 More resolution and one unresolved More.
Production review rows were equal before and after. Live DOM confirmed `.CDe7pd`
is the owner's reply, `.RfDO5c` is the structured-details region and detail scores
use B tags. Whitespace-only differences explained 13 of the 36 legacy holds;
20 had different bodies/languages and three only a prefix relationship. Those
remaining relationships are deliberately not forced into identity matches.

The widest post-fix preview observed 148 of 167: 80 already linked, 20 ready new,
13 ready legacy links, and 35 held (31 legacy ambiguity, two empty-body legacy
date uncertainty, one click failure and one missing audit). Nineteen were not
rechecked before the budget ended. A bounded retry observed only 38 after an
execution gap of 4564 seconds exhausted its budget. Therefore the final full-store
rejection count is unknown. These are acceptance proposals, not actual inserts.
Production row snapshots remained unchanged and every production write path in
the preview was disabled. No body/author/raw source IDs were exported. Database
regressions use an independent disposable PostgreSQL/PostgREST with synthetic data.


## Newest state missing from Maps

Eastville's live authenticated menu exposed four menuitemradio options with
aria-checked=false, even after Newest replaced the list. The recent streaming
path now accepts either explicit selection or NEWEST_SORT_BEHAVIOR_VERIFIED.
The latter requires all of: an ordinary click on the exact Newest option and
menu closure; an observed pre-sort chronological inversion; a different first
ID after the action; an append-stable 30-ID head over consecutive observations
after scrolling; every sampled date readable, no clear inversions and at least
three displayed-age bands with unambiguously newer/older pairs. The normal
menu reopen check must retain the same unmarked four-option structure. No
arbitrary classes or successful click returns are treated as selection proof.
Behavioral verification does not establish exact publication timestamps,
ordering within ambiguous relative-date ties or full-store completeness.

Sampling is bounded to 12 scroll rounds / 45 seconds, using normal wheel input
only. Displayed chronology is rechecked before streamed batches and final flush.
Insufficient or lost evidence falls back to bounded backfill using the caller's
unscaled round/time caps. Neither the database baseline nor the local incremental
frontier may advance in fallback. Unsorted backfill ignores overlap boundaries.
An access restriction, lost place context or unresolved open menu stops safely.
Source identity, historical backlog, insert-only RPC and recovery are unchanged.

Read-only live validation used the actual batch -> SourceWriter -> stream path
with commit=False, all backend requests disabled, public GET-only history and
81 locally confirmed source receipts. Eastville reached 167/167 observed in
102.4 scrolling seconds: pre-sort 8 readable dates / 2 clear inversions; post-sort
30 readable dates / 0 inversions / 252 clearly ordered age pairs, stable ID head.
Result: NEWEST_SORT_BEHAVIOR_VERIFIED, no production inserts or boundary
advancement, existing 163 review rows identical before/after. This is browser
execution evidence; fallback persistence and frontier guards are separately
tested with synthetic PostgreSQL/PostgREST data.

After the final fallback callback change, another fresh Chrome process passed
the same behavioral verification in the actual recent writer path. A configured
three-scroll cap stopped normally at 60/167 after 24.4 scrolling seconds with
ROUND_LIMIT, coverage_incomplete=true, backlog_unknown=true and no boundary
advancement. The 163 database rows again remained identical. Both browser runs
were dry-run acceptance only; no insertion or source-table baseline query was
performed. The previously confirmed local source receipts were a conservative
read-only substitute for privileged source-link reads, not a new production
source registry snapshot.


## 운영 전환 준비 — 매일 22:00 KST (아직 활성화 금지)

수집 엔진/RPC/프로덕션 스키마는 변경하지 않는다. 정확한 등록 매장명을
--store-name으로 여러 번 지정할 수 있다. 중복 이름, 오타, 보류 매핑은
실행 전에 거부된다. 필터 없이 실행하면 전체 등록 목록을 사용한다.

매장별 처리는 순차 실행하며 3초 간격을 둔다. 매장 종료 시 이전 페이지를
닫고 빈 탭 하나만 유지한다. 로그의 JS heap은 페이지 추정치이며 Chrome 전체
프로세스 RSS 측정은 아니다. 일반적인 매장 관측 실패는 다음 매장으로 진행한다.
접근 제한, 브라우저 단절, 미확정 쓰기는 전체 실행을 중단한다. 미확정 POST는
기존 journal과 영수증으로만 복구하고 즉시 재삽입하거나 삭제하지 않는다.
강제 종료 전후에 journal을 지우지 말고, 같은 PC/사용자/백엔드로 재실행한다.

일일 완료는 검증된 Newest + 이전 일일/DB 경계 도달 + 신규 구간 미해결 0 +
미확정 요청 0일 때만 인정한다. 이전 경계 이후의 과거 backlog가 남아 있어도
일일 완료로 표시하며 전체 역사 완전성 검증으로 격상하지 않는다.
새 구간의 보류, 정렬 미확인/backfill, cap 도달은 PARTIAL이다.

커밋 실행은 필터 유무와 관계없이 먼저 crawl_runs를 생성한다. 모든 새 리뷰의
first_seen_run_id는 이 실행 ID를 사용한다. 대시보드 stores JSON에는 필터 밖의
등록 매장도 NOT_CHECKED로 포함한다. 기존 리뷰의 first_seen_run_id는 수정하지
않는다. 실패/중단 실행도 최종 집계하며 로컬 checkpoint는 DB 집계 실패 시에도
남긴다. 비정상 종료로 DB 집계가 남지 않을 수 있으므로 로컬 보고서도 확인한다.

### Windows에서 승인 전 준비

검증된 개발 checkout에서 같은 Windows 사용자로 실행한다. 아래 작업은 이번
개발 검증 중 실행하지 않았다. 실제 backend key 입력/태스크 등록은 사용자
승인 후 로컬 PowerShell에서 수행한다.

    powershell.exe -NoProfile -File scraper/local_review_scheduler.ps1 -Action AppendPlan
    powershell.exe -NoProfile -File scraper/local_review_scheduler.ps1 -Action PrepareAppend -TargetUrl "https://PROJECT.supabase.co" -PythonPath "C:\Python\python.exe"
    powershell.exe -NoProfile -File scraper/local_review_scheduler.ps1 -Action ProtectAppendCredential
    powershell.exe -NoProfile -File scraper/local_review_scheduler.ps1 -Action RegisterAppendDisabled

PROJECT와 Python 경로는 실제 검증된 값으로 바꾼다. credential 입력은 숨김
프롬프트 한 번뿐이다. 키를 명령행, 문서, GitHub Secrets에 붙이지 않는다.
credential XML은 Windows DPAPI CurrentUser 암호화이고, 설정/로그 디렉터리 ACL은
현재 사용자와 SYSTEM만 허용한다. 런처는 비대화식으로 복호화하여 자식 Python
프로세스 환경에만 전달하고 종료 시 부모 환경을 복원한다. 메모리 내 평문과
자식 프로세스 환경 노출 위험은 남으므로 같은 사용자 계정도 보호해야 한다.
다른 PC나 사용자로 암호화 XML을 복사해서 쓰지 않는다.

로컬 파일은 LOCALAPPDATA/SVReviewMaster/append-automation 아래에 있으며
프로필과 review-source-requests.sqlite3는 기존 경로를 유지한다. 설정은 최초
approved=false, legacy_writer_disabled_confirmed=false이고 덮어쓰기를 거부한다.
태스크 XML도 Enabled=false이다. 활성화 액션은 구현하지 않았다.
비활성 태스크를 실수로 수동 실행해도 위 두 승인 값이 true가 아니면 종료 3으로
차단한다. 태스크는 InteractiveToken, LeastPrivilege, IgnoreNew를 사용하며
Python의 기존 byte-range lock이 수동 실행 간 중복도 막는다.

PC는 켜져 있고 네트워크에 연결되어 있어야 한다. 같은 Windows 사용자로
로그인한 대화형 데스크톱과 기존 Chrome 프로필 인증이 필요하다. 절전/전원 종료
상태에서 깨우지 않으며 로그인/네트워크 복구 뒤 StartWhenAvailable로 지연 실행될
수 있다. 로그아웃, 인증 만료, CAPTCHA, Google 접근 제한은 사람의 확인이 필요하다.
전용 프로필을 수동 Chrome이나 다른 태스크에서 동시에 사용하지 않는다.
작업 제한 4시간에 의해 종료되면 다음 실행이 journal에서 복구하며 직접 스크롤
위치 복원을 보장하지 않는다.

### 기존 GitHub writer 전환 순서 — 지금 실행하지 않음

1. 사용자가 새 버전과 cutover를 승인한다.
2. GitHub의 scrape-and-update workflow를 먼저 비활성화한다.
   승인 후 수동 명령 예: gh workflow disable scrape.yml --repo youngseolg-beep/google-maps-dashboard
3. 기존 실행 중인 GitHub crawl/repair가 모두 종료됐는지 확인한다.
   다른 Windows staging/collector 태스크도 같은 프로필을 쓰지 않는지 확인한다.
4. Windows 보호 저장소의 대상 프로젝트와 journal 백엔드가 일치하는지 확인한다.
5. 로컬 settings.json의 approved와 legacy_writer_disabled_confirmed를 사용자가
   확인 후 true로 바꾼다. 그 전에는 RunAppend가 쓰기를 실행할 수 없다.
6. 비활성 태스크의 22:00 KST, 사용자, Python, checkout 경로를 검토한 후에만
   Enable-ScheduledTask -TaskName "SVReviewMaster-Daily-2200-APPEND"를 실행한다.
7. 첫 실행의 daily 상태/backlog/미확정 쓰기/NEW 리뷰를 점검한다.
   문제가 생기면 새 태스크부터 비활성화하고 journal을 보존한다.
   구 writer 재활성화도 별도 승인 후 진행하며 두 writer를 겹쳐 실행하지 않는다.

이번 변경은 scrape.yml의 cron, workflow 활성 상태, 프로덕션 데이터 또는
스키마를 바꾸지 않았다. 기존 cron은 UTC 22:00 (= KST 07:00)이고 새 Windows
태스크의 KST 22:00와 다르다.

### 실제 읽기 전용 3매장 검증

동일 전용 Chrome 컨텍스트에서 매장 사이에 DOM을 해제하며 순차 실행했다.
세 매장 모두 각 3회 스크롤/60초의 관측 예산으로 제한하고 commit=False를
사용했다. 모든 privileged backend 호출을 차단했다. 공개 GET history와 로컬
확정 source 영수증을 사용했고 원본 SQLite는 읽기 전용으로 열어 임시 복제본에서
검증했다. 이는 최신 privileged source table 전체를 읽은 검증은 아니다.

- Eastville: 30/167 관측, Newest 행동 검증, OBSERVED_FRONTIER_REACHED,
  일일 완료 / 신규 구간 미해결 0. 기존 DB 200행 전후 동일.
- Ratchada: 60/195 관측, Newest 행동 검증, ROUND_LIMIT, PARTIAL.
  기존 DB 147행 전후 동일.
- Siam Discovery: 60개 관측, 정렬 근거 부족으로 bounded_backfill,
  ROUND_LIMIT, PARTIAL. 기존 DB 99행 전후 동일.

실제 신규 삽입 0, 접근 제한 없음, 매장마다 정리 후 빈 탭 1개,
페이지 heap 정리 전 약 46.7/68.2/58.2 MB였다. 이는 장시간 60매장 메모리
지속성 검증이 아니다. 원본 journal integrity_check=ok, Chrome 정상 종료,
증분 경계 갱신 0이었다. DB 저장/복구 및 crawl_runs 연동은 별도 합성
PostgreSQL/PostgREST 회귀 테스트로 검증한다.


### 이 PC의 준비 결과와 수동 설정 명령

SVReviewMaster-Daily-2200-APPEND를 현재 Windows 사용자용으로 비활성 등록했다.
StartBoundary는 KST 22:00, Interactive 로그온, Enabled=false이며,
RunAppend 직접 호출도 승인 전 gate exit 3으로 차단됨을 확인했다.
실제 backend 자격 증명 파일은 아직 없고 두 승인 플래그도 false다.
준비한 작업 디렉터리는 검증된 개발 worktree를 가리킨다.

아래 명령은 그 개발 checkout에서 실행한다. 이 PC의 PrepareAppend 및
RegisterAppendDisabled는 이미 완료했으므로 다시 실행하거나 덮어쓰지 않는다.
다른 PC에서 준비할 때만 정확한 프로젝트 URL과 Python 경로를 명시한다.

    powershell.exe -NoProfile -File .\scraper\local_review_scheduler.ps1 -Action AppendPlan
    # 다른 PC에서만:
    powershell.exe -NoProfile -File .\scraper\local_review_scheduler.ps1 -Action PrepareAppend -TargetUrl 'https://PROJECT.supabase.co' -PythonPath 'C:\PATH\python.exe'
    powershell.exe -NoProfile -File .\scraper\local_review_scheduler.ps1 -Action RegisterAppendDisabled
    # 키 소유자가 로컬 숨김 입력으로 직접 보호 저장할 때만:
    powershell.exe -NoProfile -File .\scraper\local_review_scheduler.ps1 -Action ProtectAppendCredential

settings.json 및 backend.credential.xml은 LOCALAPPDATA/SVReviewMaster/
append-automation에만 보관한다. 사용자+SYSTEM ACL로 상속을 차단하고
credential XML은 Windows DPAPI current-user 보호를 사용한다. 스케줄 실행은
같은 사용자로 비대화형 복호화한 키를 Python 자식 프로세스 환경에만 전달하며,
명령행/로그에 키를 넣지 않고 실행 후 기존 환경을 복원한다. 같은 사용자 권한의
악성 프로세스나 관리자 침해까지 방어하는 저장소는 아니다. PC/계정 변경이나
키 교체 시 소유자가 다시 설정해야 하며 Git/이메일/채팅으로 파일을 보내지 않는다.

최종 승인과 기존 writer 중단 확인 후에만, 사용자가 로컬 두 플래그를 바꾸고
Enable-ScheduledTask -TaskName 'SVReviewMaster-Daily-2200-APPEND'를 실행한다.
그 명령과 workflow disable은 이번 작업에서 실행하지 않았다.
