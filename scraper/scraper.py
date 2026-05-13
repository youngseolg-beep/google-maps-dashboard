import os
import json
import time
import re
from playwright.sync_api import sync_playwright

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
            
            # 방해 팝업(로그인 유도 등)이 뜰 경우를 대비해 충분히 대기
            page.wait_for_timeout(10000)

            # 1. 매장명 수집 (방해 요소 제외하고 '진짜' 제목만 추출)
            target_store_name = "알 수 없는 매장"
            # 구글 맵 매장명 전용 클래스들
            name_selectors = ["h1.DUwDvf", "h1.fontHeadlineLarge", "div.lMbY9 h1"]
            
            for sel in name_selectors:
                try:
                    el = page.locator(sel).first
                    # 텍스트에 '로그인'이나 '지도 활용'이 포함되어 있으면 매장명이 아님
                    raw_text = el.inner_text().strip()
                    if raw_text and "로그인" not in raw_text and "최대한 활용" not in raw_text:
                        target_store_name = raw_text
                        break
                except: continue
            
            if target_store_name == "알 수 없는 매장":
                target_store_name = "매장_" + GOOGLE_MAPS_URL.split('/')[-1][:10]
            
            print(f"🏢 매장명 확인됨: {target_store_name}")

            # 2. 리뷰 탭 클릭 (안내창 뒤에 숨어있을 수 있으므로 강제 클릭 시도)
            print("🔘 리뷰 탭 진입 시도...")
            try:
                tab = page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first
                tab.click(force=True) # force=True로 가려져 있어도 클릭 시도
                page.wait_for_timeout(5000)
            except:
                print("⚠️ 리뷰 탭을 찾지 못해 현재 화면 수집 시도")

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 시작
            print("⏳ 데이터 수집 시작...")
            for i in range(10):
                articles = page.locator("div[role='article']").all()
                for art in articles:
                    try:
                        text_el = art.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        txt = text_el.inner_text().strip()
                        
                        if not txt or txt in processed_texts: continue
                        
                        rating = 0
                        try:
                            r_el = art.locator(".kvMYC").first
                            r_label = r_el.get_attribute("aria-label") or ""
                            r_match = re.search(r'(\d)', r_label)
                            if r_match: rating = int(r_match.group(1))
                        except: rating = 0

                        d_str = "최근"
                        try:
                            d_el = art.locator(".rsqaWe").first
                            if d_el.count() > 0: d_str = d_el.inner_text()
                        except: pass

                        collected.append({
                            "store_name": target_store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "date_raw": d_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                    except: continue

                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || document.querySelector('.m67qrb');
                    if (s) s.scrollTop = s.scrollHeight;
                """)
                page.wait_for_timeout(3000)

            # 4. 저장 및 병합
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                try:
                    with open(data_path, "r", encoding="utf-8") as f:
                        all_data = json.load(f)
                except: all_data = []

            existing_keys = {f"{d.get('store_name')}_{d.get('text')}" for d in all_data}
            new_added = 0
            for item in collected:
                if f"{item['store_name']}_{item['text']}" not in existing_keys:
                    all_data.append(item)
                    new_added += 1

            os.makedirs("public/data", exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=4)
            
            print(f"✨ {target_store_name} 완료! 신규 {new_added}건 추가 (누적 {len(all_data)}건)")

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
