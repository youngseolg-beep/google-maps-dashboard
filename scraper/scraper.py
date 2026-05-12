import os
import json
import time
import re
import random
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# [1] GitHub Actions 또는 환경 변수에서 URL과 날짜 읽기
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "https://maps.google.com/?cid=YOUR_PLACE_ID")
START_DATE_STR = os.environ.get("START_DATE", "2026-05-01")

try:
    START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
except ValueError:
    START_DATE = datetime.now()

def parse_relative_date(date_str):
    """
    [2] 상대 날짜 변환기 (예: '2일 전', '3달 전', '1년 전' -> 실제 날짜 계산)
    """
    now = datetime.now()
    if not date_str:
        return now

    # 숫자와 단위(일, 주, 달, 개월, 년) 추출
    match = re.search(r'(\d+)(일|주|달|개월|년)\s*전', date_str)
    if not match:
        return now  # '1시간 전', '방금 전' 등은 오늘로 취급
    
    num = int(match.group(1))
    unit = match.group(2)
    
    if unit == '일':
        return now - timedelta(days=num)
    elif unit == '주':
        return now - timedelta(weeks=num)
    elif unit in ['달', '개월']:
        return now - timedelta(days=num * 30)
    elif unit == '년':
        return now - timedelta(days=num * 365)
    
    return now

def scrape_reviews():
    with sync_playwright() as p:
        # [3] 봇 차단 탐지 우회 및 헤드리스(백그라운드) 모드 실행
        browser = p.chromium.launch(headless=True)
        # 사용자 에이전트를 모바일/모던 브라우저로 흉내냄
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print(f"🌐 접속 중... URL: {GOOGLE_MAPS_URL}")
        # 접속 대기 시간을 60초로 늘리고, 로딩 기준을 완화합니다.
page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
# 페이지가 안정될 때까지 5초만 더 기다려줍니다.
page.wait_for_timeout(5000)
        page.wait_for_timeout(random.randint(3000, 5000)) # 랜덤 지연 
        
        # '리뷰' 탭 클릭 시도
        try:
            tab_btn = page.locator("button[role='tab']:has-text('리뷰')")
            if tab_btn.count() > 0:
                tab_btn.first.click()
                page.wait_for_timeout(random.randint(2000, 3000))
        except Exception as e:
            print("리뷰 탭을 클릭할 수 없거나 이미 리뷰 탭입니다.")
        
        # 정렬 버튼 찾아 '최신순' 클릭 
        try:
            sort_button = page.locator("button[aria-label='리뷰 정렬']")
            if sort_button.count() > 0:
                sort_button.first.click()
                page.wait_for_timeout(1000)
                # '최신순' 클릭 (일반적으로 두 번째 라디오 버튼)
                page.locator("div[role='menuitemradio']:has-text('최신순')").click()
                page.wait_for_timeout(random.randint(3000, 4000))
        except Exception:
            print("최신순 정렬 설정을 건너뜁니다.")

        reviews = []
        processed_ids = set()
        stop_crawling = False
        
        print("⏬ 무한 스크롤 및 데이터 수집 시작...")
        
        while not stop_crawling:
            # 구글 맵 최신 리뷰 클래스 타겟팅
            review_elements = page.locator(".jftiEf").all()
            if not review_elements:
                print("리뷰 요소를 찾을 수 없습니다. 페이지 구조 변경 여부를 확인하세요.")
                break
                
            new_reviews_found = False
            
            for el in review_elements:
                review_id = el.get_attribute("data-review-id")
                if review_id in processed_ids:
                    continue
                    
                processed_ids.add(review_id)
                new_reviews_found = True
                
                # "더보기" 버튼이 있다면 클릭 (본문 전체 확보)
                try:
                    more_btn = el.locator("button.w8nwRe.kyuRq")
                    if more_btn.count() > 0:
                        more_btn.first.click()
                except Exception:
                    pass
                
                # 데이터 파싱
                author_el = el.locator(".d4r55")
                author = author_el.inner_text().strip() if author_el.count() > 0 else "익명 사용자"
                
                rating_el = el.locator(".kvMYJc")
                rating = 0
                if rating_el.count() > 0:
                    aria_label = rating_el.get_attribute("aria-label") or ""
                    match = re.search(r'\d+', aria_label) # "별표 5개 중 4개"에서 숫자 추출
                    if match:
                        rating = int(match.group())
                
                text_el = el.locator(".wiI7pd")
                text = text_el.inner_text().strip() if text_el.count() > 0 else ""
                
                date_el = el.locator(".rsqaWe")
                date_str = date_el.inner_text().strip() if date_el.count() > 0 else ""
                
                # 상대 날짜를 실제 날짜로 변환
                actual_date = parse_relative_date(date_str)
                
                # [4] 중단 로직: 수집된 리뷰 날짜가 기준일보다 과거인지 확인
                if actual_date < START_DATE:
                    print(f"🛑 [중단] 기준 날짜 이전 리뷰에 도달했습니다. (리뷰 날짜: {actual_date.strftime('%Y-%m-%d')} < 기준 날짜: {START_DATE_STR})")
                    stop_crawling = True
                    break
                    
                reviews.append({
                    "id": review_id,
                    "author": author,
                    "rating": rating,
                    "text": text,
                    "date": actual_date.strftime("%Y-%m-%d"),
                })
            
            if stop_crawling:
                break
                
            # [5] 스크롤 내리기 
            if review_elements:
                try:
                    # 화면의 마지막 리뷰 요소로 포커스 이동 후 조금 더 내리기
                    review_elements[-1].scroll_into_view_if_needed()
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(random.randint(2000, 4000)) # 데이터 로딩을 충분히 기다림
                except Exception:
                    break
            
            if not new_reviews_found:
                print("더 이상 새로운 리뷰가 없습니다. 스크롤 끝 도달.")
                break

        print(f"✅ 총 {len(reviews)}개의 최신 리뷰를 수집했습니다.")

        # Vite/React에서 사용할 수 있도록 public/data/ 폴더에 저장
        os.makedirs("public/data", exist_ok=True)
        with open("public/data/reviews.json", "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=4)
        
        browser.close()

if __name__ == "__main__":
    scrape_reviews()
