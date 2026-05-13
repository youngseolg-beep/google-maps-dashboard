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
            # networkidle 대신 commit 사용 (접속 시작되면 바로 진행)
            page.goto(GOOGLE_MAPS_URL, wait_until="commit", timeout=60000)
            
            # 매장 이름이 나타날 때까지 최대 30초 대기 (나타나면 바로 다음 줄 실행)
            print("⏳ 매장 정보 로딩 대기 중...")
            try:
                page.wait_for_selector("h1", timeout=30000)
            except:
                print("⚠️ 매장 이름 로딩이 지연되어 현재 상태에서 진행합니다.")

            # 1. 매장명 수집
            target_store_name = "알 수 없는 매장"
            name_candidates = ["h1.DUwDvf", "h1.fontHeadlineLarge", "xpath=//h1"]
            for sel in name_candidates:
                try:
                    el = page.locator(sel).first
                    if el.is_visible():
                        name = el.inner_text().strip()
                        if name and "로그인" not in name:
                            target_store_name = name
                            break
                except: continue
            
            if target_store_name == "알 수 없는 매장":
                target_store_name = "매장_" + GOOGLE_MAPS_URL.split('/')[-1][:10]
            
            print(f"🏢 매장명: {target_store_name}")

            # 2. 리뷰 탭 클릭 (강력한 시도)
            print("🔘 리뷰 탭 진입 시도...")
            try:
                # 탭 버튼이 나타날 때까지 잠시 대기
                page.wait_for_selector("button[role='tab']", timeout=10000)
                review_tab = page.get_by_role("tab").filter(has_text=re.compile("리뷰|Reviews")).first
                review_tab.click(force=True)
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)
            except:
                print("⚠️ 리뷰 탭을 찾지 못했습니다. 현재 화면 수집 시도")

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 시작
            print("⏳ 데이터 수집 시작...")
            for i in range(15): # SV용 데이터 확보를 위해 15회 스크롤
                articles = page.locator("div[role='article']").all()
                for art in articles:
                    try:
                        text_el = art.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        txt = text_el.inner_text().strip()
                        
                        if not txt or txt in processed_texts: continue
                        
                        # 별점
                        rating = 0
                        try:
                            r_el = art.locator(".kvMYC").first
                            r_label = r_el.get_attribute("aria-label") or ""
                            r_match = re.search(r'(\d)', r_label)
                            if r_match: rating = int(r_match.group(1))
                        except: rating = 0

                        collected.append({
                            "store_name": target_store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "date_raw": "최근",
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                    except: continue

                print(f"🔄 스크롤 {i+1}회: {len(collected)}건 확보 중...")
                
                # 강제 스크롤
                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || 
                              document.querySelector('.DxyBCb') || 
                              document.querySelector('.m67qrb');
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

            # 텍스트 중복 방지 (동일 매장의 동일 텍스트만 제외)
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
