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
            # 타임아웃을 넉넉히 잡고 로딩 대기
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000) # 10초 넉넉히 대기
            
            # 1. 매장명 수집 (에러 방지 처리)
            store_name = "알 수 없는 매장"
            try:
                name_el = page.locator("h1.DUwDvf").first
                if name_el.is_visible():
                    store_name = name_el.inner_text().strip()
            except:
                print("⚠️ 매장명을 찾는 데 실패했습니다. 기본값으로 진행합니다.")
            
            print(f"🏢 매장명: {store_name}")

            # 2. 리뷰 탭 클릭 시도 (다양한 셀렉터 시도)
            print("🔘 리뷰 탭 진입 시도...")
            review_tab = page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first
            if review_tab.is_visible():
                review_tab.click()
                page.wait_for_timeout(5000)
            else:
                # 탭을 못 찾으면 텍스트 기반으로 한 번 더 시도
                page.get_by_text("리뷰", exact=False).first.click()
                page.wait_for_timeout(5000)

            # 3. 최신순 정렬
            try:
                page.locator("button[aria-label*='정렬'], button[aria-label*='Sort']").first.click()
                page.wait_for_timeout(2000)
                page.get_by_role("menuitemradio").filter(has_text=re.compile("최신순|Newest")).click()
                page.wait_for_timeout(3000)
            except: pass

            collected = []
            processed_texts = set()
            
            # 4. 스크롤 및 수집
            print("⏳ 데이터 수집 및 스크롤 시작...")
            for i in range(10):
                # 리뷰 아이템 리스트
                items = page.locator("div[role='article']").all()
                for item in items:
                    try:
                        text_el = item.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        text = text_el.inner_text().strip()
                        
                        if not text or text in processed_texts: continue
                        
                        # 별점 추출
                        rating_el = item.locator(".kvMYC")
                        rating_label = rating_el.get_attribute("aria-label") or ""
                        # "별점 5개" 등에서 숫자만 추출
                        rating = 0
                        if "1" in rating_label: rating = 1
                        elif "2" in rating_label: rating = 2
                        elif "3" in rating_label: rating = 3
                        elif "4" in rating_label: rating = 4
                        elif "5" in rating_label: rating = 5

                        date_el = item.locator(".rsqaWe").first
                        date_str = date_el.inner_text() if date_el.count() > 0 else "최근"

                        collected.append({
                            "store_name": store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": text,
                            "rating": rating,
                            "date_raw": date_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                    except: continue

                # 강제 스크롤
                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || document.querySelector('.m67qrb');
                    if (s) s.scrollTop = s.scrollHeight;
                """)
                page.wait_for_timeout(3000)

            # 5. 데이터 저장 및 병합
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                with open(data_path, "r", encoding="utf-8") as f:
                    try: all_data = json.load(f)
                    except: all_data = []

            # 중복 체크 후 추가
            existing_keys = {f"{d['store_name']}_{d['text']}" for d in all_data}
            new_count = 0
            for item in collected:
                if f"{item['store_name']}_{item['text']}" not in existing_keys:
                    all_data.append(item)
                    new_count += 1

            os.makedirs("public/data", exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=4)
            
            print(f"✨ {store_name} 완료! 새 리뷰 {new_count}건 추가 (누적 총 {len(all_data)}건)")

        except Exception as e:
            print(f"❌ 실행 중 오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
