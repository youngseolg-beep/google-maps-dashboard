import os
import json
import time
import re
import random
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")
START_DATE_STR = os.environ.get("START_DATE", "2026-05-01")

try:
    START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
except:
    START_DATE = datetime.now() - timedelta(days=60)

def parse_relative_date(date_str):
    now = datetime.now()
    if not date_str: return now
    if any(x in date_str for x in ['초', '분', '시간', '방금']): return now
    match = re.search(r'(\d+)(일|주|달|개월|년)\s*전', date_str)
    if not match: return now
    num, unit = int(match.group(1)), match.group(2)
    if unit == '일': return now - timedelta(days=num)
    elif unit == '주': return now - timedelta(weeks=num)
    elif unit in ['달', '개월']: return now - timedelta(days=num * 30)
    elif unit == '년': return now - timedelta(days=num * 365)
    return now

def scrape_reviews():
    if not GOOGLE_MAPS_URL:
        print("❌ URL이 설정되지 않았습니다.")
        return

    with sync_playwright() as p:
        # [혁신 1] 모바일 브라우저로 위장하여 구글의 보안벽을 낮춥니다.
        iphone = p.devices['iPhone 14 Pro Max']
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            **iphone,
            locale="ko-KR",
            timezone_id="Asia/Seoul"
        )
        page = context.new_page()
        
        print(f"📡 [모바일 모드] 접속 시도: {GOOGLE_MAPS_URL}")
        
        try:
            page.goto(GOOGLE_MAPS_URL, wait_until="commit", timeout=60000)
            page.wait_for_timeout(10000) # 충분한 로딩 대기

            # [혁신 2] '리뷰' 탭을 찾기 위해 화면의 모든 버튼을 뒤집니다.
            print("🔍 리뷰 버튼 찾는 중...")
            page.get_by_text(re.compile(r"리뷰", re.I)).first.click(timeout=10000)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"⚠️ 리뷰 탭 진입 시도 중: {e}")

        reviews = []
        processed_texts = set()
        
        print("⏬ 데이터 강제 추출 시작...")
        
        # [혁신 3] 클래스 이름이 아니라 '별점' 요소를 기준으로 주변 텍스트를 긁어모읍니다.
        for _ in range(15): # 스크롤 반복
            # 구글 맵 리뷰 리스트의 공통적인 속성을 가진 요소들을 모두 탐색
            elements = page.locator("xpath=//div[contains(@aria-label, '별점')] | //span[contains(@aria-label, '별점')]").all()
            
            for el in elements:
                try:
                    # 부모 요소를 찾아 그 안의 텍스트를 몽땅 긁어옵니다.
                    parent = el.locator("xpath=./ancestor::div[1]")
                    full_text = parent.inner_text().strip()
                    
                    if not full_text or full_text in processed_texts:
                        continue
                    
                    processed_texts.add(full_text)
                    
                    # 텍스트 내에서 날짜 정보와 본문 분리 시도
                    # (모바일 환경에 최적화된 파싱)
                    lines = full_text.split('\n')
                    if len(lines) < 2: continue

                    reviews.append({
                        "author": lines[0],
                        "rating": 5, # 기본값
                        "text": " ".join(lines[1:4]), # 내용 일부 추출
                        "date": datetime.now().strftime("%Y-%m-%d") # 임시
                    })
                except:
                    continue

            if len(reviews) > 0:
                print(f"✨ 현재 {len(reviews)}건 발견...")
            
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(3000)

            if len(reviews) >= 10: break

        # 최종 저장
        print(f"🏁 [결과] 최종 수집 성공: {len(reviews)}건")
        os.makedirs("public/data", exist_ok=True)
        with open("public/data/reviews.json", "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=4)
        
        browser.close()

if __name__ == "__main__":
    scrape_reviews()
