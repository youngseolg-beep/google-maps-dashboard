import os
import json
import time
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# 설정값 가져오기
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")
START_DATE_STR = os.environ.get("START_DATE", "2026-01-01")
START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")

def parse_date(date_str):
    now = datetime.now()
    if not date_str: return now
    match = re.search(r'(\d+)(일|주|달|개월|년)\s*전', date_str)
    if not match: return now
    num, unit = int(match.group(1)), match.group(2)
    if unit == '일': return now - timedelta(days=num)
    elif unit == '주': return now - timedelta(weeks=num)
    elif unit in ['달', '개월']: return now - timedelta(days=num * 30)
    elif unit == '년': return now - timedelta(days=num * 365)
    return now

def scrape():
    with sync_playwright() as p:
        # 브라우저 실행 (자동화 우회 설정)
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )

        # 🔐 금고(Secrets)에서 신분증(쿠키) 꺼내서 장착
        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                cookies = json.loads(cookies_raw)
                for c in cookies:
                    c['sameSite'] = "Lax"
                context.add_cookies(cookies)
                print("🍪 신분증(쿠키) 장착 및 형식 보정 완료")
            except Exception as e:
                print(f"⚠️ 쿠키 장착 실패: {e}")

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            # 페이지 안정화를 위해 domcontentloaded 사용
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            
            print("⏳ 페이지 안정화 대기 중 (10초)...")
            page.wait_for_timeout(10000)
            
            # 1. 리뷰 탭 클릭 시도
            print("🔘 리뷰 탭 클릭 시도...")
            review_selectors = [
                "button[role='tab']:has-text('리뷰')",
                "button[role='tab']:has-text('Reviews')",
                "text='리뷰'",
                ".hh7dbf"
            ]
            
            clicked = False
            for selector in review_selectors:
                try:
                    target = page.locator(selector).first
                    if target.is_visible():
                        target.click()
                        print(f"✅ 리뷰 탭 클릭 성공 ({selector})")
                        page.wait_for_timeout(5000)
                        clicked = True
                        break
                except: continue
            
            if not clicked:
                print("⚠️ 리뷰 탭을 찾지 못했습니다. 현재 화면에서 수집을 시도합니다.")

            reviews = []
            processed_texts = set()
            
            # 2. 스크롤 및 수집 시작
            print("⏳ 스크롤 및 데이터 수집을 시작합니다...")
            
            # 구글 맵 리뷰 리스트를 담고 있는 스크롤 가능 컨테이너 셀렉터
            scroll_div_selector = ".m67qrb"

            for i in range(15): # 최대 15번 스크롤 시도
                # 현재 로드된 리뷰 아이템들 확보
                items = page.locator(".wiI7pd, .MyE63c").all()
                new_found = 0
                
                for item in items:
                    try:
                        text = item.inner_text().strip()
                        if not text or text in processed_texts: continue
                        
                        # 부모 요소를 찾아 날짜 추출
                        parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                        date_el = parent.locator(".rsqaWe").first
                        date_str = date_el.inner_text() if date_el.count() > 0 else ""
                        review_date = parse_date(date_str)
                        
                        # 설정한 시작일보다 이전 데이터면 건너뜀
                        if review_date < START_DATE:
                            continue

                        reviews.append({
                            "author": "고객",
                            "text": text,
                            "date": review_date.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                        new_found += 1
                    except: continue

                print(f"🔄 스크롤 {i+1}회차: 현재 총 {len(reviews)}건 확보 (이번 회차 +{new_found})")
                
                # [핵심] 리뷰 컨테이너를 조준하여 스크롤
                try:
                    scroll_target = page.locator(scroll_div_selector).first
                    if scroll_target.is_visible():
                        box = scroll_target.bounding_box()
                        if box:
                            # 마우스를 리뷰 리스트 정중앙으로 이동
                            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            # 휠을 아래로 굴림
                            page.mouse.wheel(0, 4000)
                    else:
                        page.mouse.wheel(0, 3000)
                except:
                    page.mouse.wheel(0, 3000)
                
                # 추가 데이터 로딩을 위한 대기
                page.wait_for_timeout(3000)

            # 3. 데이터 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 수집 종료! 총 {len(reviews)}건의 리뷰를 성공적으로 저장했습니다.")

        except Exception as e:
            print(f"❌ 실행 중 오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
