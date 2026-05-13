import os
import json
import time
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")
# 날짜 비교가 까다로우니, 일단 수집 후 필터링을 위해 기준을 넉넉히 잡습니다.
START_DATE_STR = os.environ.get("START_DATE", "2026-01-01")

def parse_date(date_str):
    now = datetime.now()
    if not date_str: return now
    # 숫자가 포함된 "X일/주/달/년 전" 형식 추출
    match = re.search(r'(\d+)', date_str)
    if not match: return now
    
    num = int(match.group(1))
    if '일' in date_str: return now - timedelta(days=num)
    elif '주' in date_str: return now - timedelta(weeks=num)
    elif '달' in date_str or '개월' in date_str: return now - timedelta(days=num * 30)
    elif '년' in date_str: return now - timedelta(days=num * 365)
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
            except: pass

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            
            review_tab = page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first
            if review_tab.is_visible():
                review_tab.click()
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)

            all_collected = []
            processed_texts = set()
            
            print("⏳ 데이터 수집 시작 (스크롤 10회 고정)...")
            
            for i in range(10): # 16건 정도면 10번 스크롤로 충분합니다.
                items = page.locator("div[role='article']").all()
                for item in items:
                    try:
                        text_el = item.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        text = text_el.inner_text().strip()
                        
                        if not text or text in processed_texts: continue
                        
                        date_el = item.locator(".rsqaWe")
                        date_str = date_el.first.inner_text() if date_el.count() > 0 else "오늘"
                        
                        # 일단 수집! 날짜 필터링은 저장 직전에 합니다.
                        all_collected.append({
                            "author": "고객",
                            "text": text,
                            "date_raw": date_str,
                            "date": parse_date(date_str).strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                    except: continue

                print(f"🔄 회차 {i+1}: 현재 {len(all_collected)}건 발견")

                page.evaluate("""
                    const scrollable = document.querySelector('div[role="main"] div.m67qrb') || 
                                     document.querySelector('.DxyBCb') || 
                                     document.querySelector('.m67qrb');
                    if (scrollable) scrollable.scrollTop = scrollable.scrollHeight;
                """)
                page.wait_for_timeout(3000)

            # [마지막 필터링] 2026-01-01 이후 데이터만 남기기
            final_reviews = [r for r in all_collected if r["date"] >= START_DATE_STR]
            
            # 3. 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(final_reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 필터링 완료! 총 {len(final_reviews)}건 저장 (전체 수집: {len(all_collected)}건)")

        except Exception as e:
            print(f"❌ 에러: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
