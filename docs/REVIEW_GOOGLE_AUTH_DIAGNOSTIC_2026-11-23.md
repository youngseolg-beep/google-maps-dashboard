# Google Maps 전용 계정 인증 진단 — 2026-11-23

## 검증 조건
- 대상 매장: Saemaeul Central Eastville (Thailand)
- 개발 브랜치: `test/review-collection-without-sort`
- 사용자는 로그인된 일반 Chrome에서 6건 이상 리뷰를 확인했음
- 시크릿 모드에서는 5건까지만 표시되고 '리뷰 더보기'에서 Google 로그인을 요청함
- 운영 `main` 및 Supabase 데이터 수정 없음; 모든 진단은 읽기 전용

## 이번 검증의 실제 결과
1. Google 인증 개발 브랜치 `test/github-actions-google-auth`에는 로컬 인증 상태 추출 도구와 `GOOGLE_MAPS_STORAGE_STATE_B64` 기반 테스트가 존재함. 해당 브랜치의 성공한 인증 실행 기록은 확인되지 않았음.
2. GitHub Actions에 `GOOGLE_MAPS_STORAGE_STATE_B64` Secret이 존재하고 base64 JSON 형식이 정상임.
3. 익명 테스트는 고유 리뷰 5건, 저장된 전용 계정 인증 상태 적용 테스트도 5건. 6건 이상 테스트는 FAIL.
4. 오프라인 Secret 상태 검사: Google 범위 쿠키 29개, 만료 전 26개, 인증 관련 이름으로 보이는 쿠키 14개(모두 만료 전). 쿠키의 존재 및 유효기간은 서버 인증 성공을 의미하지 않음.
5. 브라우저에서 `myaccount.google.com` 접속 비교: 익명 컨텍스트는 Google 페이지에서 로그인 UI를 표시했고, 전용 계정 저장 상태 컨텍스트는 `accounts.google.com` 로그인 경로로 이동함. 따라서 GitHub Actions에서 전용 계정 로그인 세션이 정상 수용되었다는 증거가 없음.
6. Google 로그인 거절의 정확한 원인(세션 교체, 장치/네트워크/지역 정책, 추가 인증 등)은 아직 확정되지 않음.

## 재개 기준 및 다음 작업
- 기존 전용 Chrome 프로필만 사용하며 새 계정 생성이나 파트너사 Business Profile 권한 요구를 하지 않음.
- PC에서 기존 `scraper/export_existing_auth_state.py` 도구로 현재 로그인 상태를 안전하게 다시 추출할 수 있음. 사용자가 직접 GitHub Repository Actions Secret `GOOGLE_MAPS_STORAGE_STATE_B64`에 갱신해야 함.
- **쿠키/토큰/비밀번호/내보내기 파일은 채팅, Git, Actions artifact 또는 로그에 절대 전달·저장하지 않음.**
- Secret 갱신 후 읽기 전용 `review-google-session-acceptance`와 `review-authenticated-depth-verification`만 수동 재실행.
- 로그인 상태 검증 PASS와 6건 이상 고유 리뷰 로딩 PASS를 각각 구분해서 판정함. 둘 중 하나라도 실패하면 운영 크롤러에 반영하지 않음.
- 새로 추출한 상태도 GitHub Actions에서 거절되면 반복적으로 쿠키를 덮어쓰거나 로그인 시도하지 않고 인증 방식 및 실행 환경을 다시 설계·검토함.

## 진단 링크
- [전용 인증 상태 적용 후 리뷰 깊이 비교](https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45093592382)
- [Google 쿠키 유효기간 검사](https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45093872702)
- [Google 계정 서버 세션 수용 여부 검사](https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45093992501)


## 인증 상태 기반 전체 리뷰 스크롤 검증 (추가: 2026-11-23)

### 수행 및 확인
- GitHub Actions 인증 비교: 익명 5건, 전용 계정 적용 8건 관측 PASS.
- 첫 전체 목록 스크롤: 18건 관측. 목록 끝에 도달하기 전에 10회 신규 없음 조건으로 종료한 오류 확인.
- 조기 종료 조건 수정 후: 91회 스크롤, 최종 리뷰 카드 167개, 실제 목록 하단 도달 후 추가 로딩 중단.
- 검증 재실행 최종 DOM 감사: 리뷰 카드 167개, 명시적 data-review-id 167개, 중복 ID 0개, 작성자 표시 요소 167개, 평점 표시 요소 167개.
- Google 관련 Fetch/XHR 응답 174건; HTTP 4xx/5xx 0건.
- 앞선 비로그인 교차 매장 검사에서 화면 총수 162를 읽었지만, 인증 세션의 최신 총수는 현재 신뢰성 있게 추출하지 못함. 시점이 다른 표시 수와 관찰 카드 수의 차이를 신규 리뷰 증가로 단정하지 말 것.
- 이 결과는 브라우저에서 167개 구분 가능한 리뷰 카드 확인을 뜻하며, DB 신규 건수나 실제 저장 성공을 의미하지 않음.
- 인증 정보/리뷰 내용/작성자/ID는 결과 로그와 artifact에 저장하지 않음.

### 완료 게이트
1. 같은 시점 Google Maps 총 리뷰 수와 관측 고유 ID 수를 대사.
2. 기존 리뷰 DB와 중복 여부 및 날짜·평점·본문 파싱을 읽기 전용 검증.
3. 검증 후 별도 승인 없이 운영 main 또는 Supabase 저장을 활성화하지 않음.

### 실행 기록
- [첫 18건 테스트](https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45098890899)
- [167건 확보 테스트](https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45099155930)
- [167개 ID·평점·작성자 검증](https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45099556771)
