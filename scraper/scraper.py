import os
import json
import time
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")

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
            page.wait_for_timeout(8000)
            
            # 매장명 수집
            store_name = page.locator("h1.DUwDvf").inner_text() or "알 수 없는 매장"
            print(f"🏢 매장명 확인: {store_name}")

            # 리뷰 탭 클릭
            page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first.click()
            page.wait_for_timeout(3000)

            # 최신순 정렬
            try:
                page.locator("button[aria-label*='정렬'], button[aria-label*='Sort']").first.click()
                page.wait_for_timeout(1000)
                page.locator("text='최신순', text='Newest'").first.click()
                page.wait_for_timeout(2000)
            except: pass

            collected = []
            processed_texts = set()
            
            for i in range(10): # SV용이므로 100개 내외면 충분 (10회 스크롤)
                items = page.locator("div[role='article']").all()
                for item in items:
                    try:
                        # 1. 리뷰 텍스트 (원문/번역본 자동 수집)
                        text_el = item.locator(".wiI7pd")
                        text = text_el.inner_text().strip() if text_el.count() > 0 else ""
                        if not text or text in processed_texts: continue
                        
                        # 2. 별점 수집
                        rating_el = item.locator(".kvMYC")
                        rating_str = rating_el.get_attribute("aria-label") if rating_el.count() > 0 else "0"
                        # "별점 5개" -> 5 추출
                        rating = rating_str.split(" ")[-1].replace("개", "") if "별점" in rating_str else "0"

                        # 3. 날짜
                        date_el = item.locator(".rsqaWe").first
                        date_str = date_el.inner_text() if date_el.count() > 0 else "최근"

                        collected.append({
                            "store_name": store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": text,
                            "rating": int(rating),
                            "date_raw": date_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                    except: continue

                # 스크롤
                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || document.querySelector('.m67qrb');
                    if (s) s.scrollTop = s.scrollHeight;
                """)
                page.wait_for_timeout(2500)

            # 기존 데이터와 병합 (누적 저장)
            data_path = "public/data/reviews.json"
            if os.path.exists(data_path):
                with open(data_path, "r", encoding="utf-8") as f:
                    try:
                        old_data = json.load(f)
                    except:
                        old_data = []
            else:
                old_data = []

            # 중복 제거 병합 (텍스트 기준)
            existing_texts = {d['text'] for d in old_data}
            new_entries = [d for d in collected if d['text'] not in existing_texts]
            final_data = old_data + new_entries

            os.makedirs("public/data", exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=4)
            
            print(f"✨ {store_name} 수집 완료! 새 리뷰 {len(new_entries)}건 추가 (총 {len(final_data)}건)")

        except Exception as e:
            print(f"❌ 에러: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
