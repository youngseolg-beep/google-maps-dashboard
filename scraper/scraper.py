import os
import json
import time
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# 1. 환경 변수에서 설정값 읽기
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")
# 기본 수집 시작일: 2026-01-01
START_DATE_STR = os.environ.get("START_DATE", "2026-01-01")
try:
    START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
except:
    START_DATE = datetime(2026, 1, 1)

def parse_date(date_str):
    now = datetime.now()
    if not date_str: return now
    # 구글 맵 날짜 형식 대응 (X일 전, X주 전, X개월 전, X년 전)
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
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )

        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                cookies = json.loads(cookies_raw)
                for c in cookies: c['sameSite'] = "Lax"
                context.add_cookies(cookies)
                print("🍪 신분증(쿠키) 장착 완료")
            except: pass

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            
            # 리뷰 탭 클릭
            review_tab = page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first
            if review_tab.is_visible():
                review_tab.click()
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)

            reviews = []
            processed_texts = set()
            should_stop = False # 종료 플래그
            
            print(f"⏳ {START_DATE_STR} 이후 리뷰 수집 시작...")
            
            for i in range(20):
                if should_stop: break
                
                items = page.locator("div[role='article']").all()
                new_in_this_scroll = 0
                
                for item in items:
                    try:
                        # 리뷰 텍스트 추출
                        text_el = item.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        text = text_el.inner_text().strip()
                        
                        if not text or text in processed_texts: continue
                        
                        # 날짜 추출 및 판별
                        date_el = item.locator(".rsqaWe")
                        date_str = date_el.first.inner_text() if date_el.count() > 0 else ""
                        review_date = parse_date(date_str)
                        
                        # [핵심] 설정한 날짜보다 이전(과거) 리뷰를 만나면?
                        if review_date < START_DATE:
                            print(f"🛑 과거 리뷰 발견 ({review_date.strftime('%Y-%m-%d')}). 수집을 중단합니다.")
                            should_stop = True
                            break # 현재 아이템 루프 탈출

                        reviews.append({
                            "author": "고객",
                            "text": text,
                            "date": review_date.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                        new_in_this_scroll += 1
                    except: continue

                print(f"🔄 회차 {i+1}: 누적 {len(reviews)}건 확보")
                if should_stop: break

                # 다음 데이터를 위해 스크롤
                page.evaluate("""
                    const scrollable = document.querySelector('div[role="main"] div.m67qrb') || 
                                     document.querySelector('.DxyBCb') || 
                                     document.querySelector('.m67qrb');
                    if (scrollable) scrollable.scrollTop = scrollable.scrollHeight;
                """)
                page.wait_for_timeout(4000)

            # 3. 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 최종 성공! 총 {len(reviews)}건 저장 완료.")

        except Exception as e:
            print(f"❌ 에러 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
