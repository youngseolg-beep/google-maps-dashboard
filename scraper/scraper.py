import os
import json
import time
import re
from playwright.sync_api import sync_playwright

# 환경 변수 설정
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL:
        print("❌ GOOGLE_MAPS_URL이 설정되지 않았습니다.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )

        # 쿠키 장착
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
            
            # 1. 매장명 수집 (여러 시도)
            current_store_name = "알 수 없는 매장"
            name_selectors = ["h1.DUwDvf", "h1.fontHeadlineLarge", "h1"]
            for sel in name_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible():
                        current_store_name = el.inner_text().strip()
                        break
                except: continue
            
            # 매장명을 정말 못 찾으면 URL 뒷부분이라도 활용
            if current_store_name == "알 수 없는 매장":
                current_store_name = GOOGLE_MAPS_URL.split('/')[-1] or "매장"
            
            print(f"🏢 매장명: {current_store_name}")

            # 2. 리뷰 탭 클릭
            print("🔘 리뷰 탭 진입 시도...")
            try:
                page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first.click()
                page.wait_for_timeout(5000)
            except:
                print("⚠️ 리뷰 탭 클릭 실패, 화면에 보이는 대로 수집 시도")

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 및 스크롤
            print("⏳ 데이터 수집 시작...")
            for i in range(10): # SV용 3개월치는 10회면 충분
                # 모든 리뷰 아티클 탐색
                articles = page.locator("div[role='article']").all()
                
                for art in articles:
                    try:
                        # 리뷰 텍스트
                        text_el = art.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        txt = text_el.inner_text().strip()
                        
                        if not txt or txt in processed_texts: continue
                        
                        # 별점 (aria-label에서 숫자 추출)
                        rating = 0
                        try:
                            r_el = art.locator(".kvMYC").first
                            r_label = r_el.get_attribute("aria-label") or ""
                            r_match = re.search(r'(\d)', r_label)
                            if r_match: rating = int(r_match.group(1))
                        except: rating = 0

                        # 날짜
                        try:
                            d_el = art.locator(".rsqaWe").first
                            d_str = d_el.inner_text() if d_el.count() > 0 else "최근"
                        except: d_str = "최근"

                        collected.append({
                            "store_name": current_store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "date_raw": d_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                    except: continue

                # 스크롤 명령
                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || document.querySelector('.m67qrb');
                    if (s) s.scrollTop = s.scrollHeight;
                """)
                page.wait_for_timeout(3000)

            # 4. 파일 저장 및 병합
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                try:
                    with open(data_path, "r", encoding="utf-8") as f:
                        all_data = json.load(f)
                except: all_data = []

            # 신규 데이터 합치기 (텍스트 중복 방지)
            existing_texts = {f"{d['store_name']}_{d['text']}" for d in all_data}
            new_added = 0
            for item in collected:
                if f"{item['store_name']}_{item['text']}" not in existing_texts:
                    all_data.append(item)
                    new_added += 1

            os.makedirs("public/data", exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=4)
            
            print(f"✨ {current_store_name} 완료! 신규 {new_added}건 추가 (누적 {len(all_data)}건)")

        except Exception as e:
            print(f"❌ 전체 공정 중 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
