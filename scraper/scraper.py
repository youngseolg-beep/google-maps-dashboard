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

        page = context.new_page()
        
        try:
            print(f"🌐 접속 시도: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            
            print("⏳ 매장 정보 로드 대기...")
            page.wait_for_timeout(10000) 

            # 1. 매장명 수집
            target_store_name = "Paik's Noodle"
            try:
                name_el = page.locator("h1").first
                if name_el.count() > 0:
                    target_store_name = name_el.inner_text().strip()
            except: pass
            print(f"🏢 매장명 최종 확인: {target_store_name}")

            # 2. 리뷰 탭 클릭
            print("🔘 리뷰 탭 진입 시도...")
            try:
                # 'Reviews'나 '리뷰' 텍스트를 포함한 버튼 혹은 탭 인덱스 1번(리뷰) 클릭
                review_btn = page.locator('button[role="tab"]').filter(has_text=re.compile(r"Reviews|리뷰", re.IGNORECASE)).first
                if review_btn.is_visible():
                    review_btn.click(force=True)
                else:
                    page.click("button[data-tab-index='1']", force=True)
                print("✅ 리뷰 탭 클릭 완료")
            except:
                print("⚠️ 클릭 실패, 직접 좌표 클릭 시도")
                page.mouse.click(400, 300) # 대략적인 리뷰 탭 위치

            page.wait_for_timeout(5000)

            # 3. 데이터 수집 시작 (리뷰 텍스트가 뜰 때까지 반복 확인)
            collected = []
            processed_texts = set()
            
            print("⏳ 리뷰 데이터 탐색 중...")
            for i in range(15):
                # 구글 맵 리뷰 텍스트 요소들 (.wiI7pd 가 가장 흔함)
                items = page.locator(".wiI7pd, .MyE63c, div[role='article']").all()
                
                current_scroll_count = 0
                for item in items:
                    try:
                        # 텍스트 추출 (내부에 글자가 있는 div를 찾음)
                        txt = item.inner_text().strip()
                        if not txt or len(txt) < 5 or txt in processed_texts: continue
                        
                        # 별점 (단순화된 추출)
                        rating = 0
                        parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                        if parent.count() > 0:
                            r_el = parent.locator(".kvMYC").first
                            r_label = r_el.get_attribute("aria-label") or ""
                            r_match = re.search(r'(\d)', r_label)
                            if r_match: rating = int(r_match.group(1))

                        collected.append({
                            "store_name": target_store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "date_raw": "최근",
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                        current_scroll_count += 1
                    except: continue

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 발견 (총 {len(collected)}건)")

                # 스크롤: 리뷰 컨테이너를 찾아서 강제로 내림
                page.evaluate("""
                    const s = document.querySelector('.m67qrb') || document.querySelector('.DxyBCb') || document.querySelector('div[role="main"]');
                    if (s) s.scrollBy(0, 2000);
                    else window.scrollBy(0, 1000);
                """)
                page.wait_for_timeout(3000)
                
                # 만약 3회차까지 하나도 안 잡히면 강제 마우스 휠
                if i == 2 and len(collected) == 0:
                    page.mouse.wheel(0, 3000)

            # 4. 저장 및 병합
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                try:
                    with open(data_path, "r", encoding="utf-8") as f:
                        all_data = json.load(f)
                except: all_data = []

            # 중복 체크 (매장명 + 텍스트 기준)
            existing_keys = {f"{d.get('store_name')}_{d.get('text')}" for d in all_data}
            new_added = 0
            for item in collected:
                if f"{item['store_name']}_{item['text']}" not in existing_keys:
                    all_data.append(item)
                    new_added += 1

            os.makedirs("public/data", exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=4)
            
            print(f"✨ {target_store_name} 완료! 신규 {new_added}건 추가 (전체 DB: {len(all_data)}건)")

        except Exception as e:
            print(f"❌ 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
