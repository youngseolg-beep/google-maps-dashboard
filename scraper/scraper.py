import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL:
        print("❌ URL이 없습니다.")
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
            page.wait_for_timeout(10000) 

            # 1. 매장명 수집
            target_store_name = "Paik's Noodle"
            try:
                name_el = page.locator("h1").first
                if name_el.count() > 0:
                    target_store_name = name_el.inner_text().strip()
            except: pass
            print(f"🏢 매장명: {target_store_name}")

            # 2. 리뷰 탭 클릭
            print("🔘 리뷰 탭 진입 시도...")
            review_btn = page.locator('button[role="tab"]').filter(has_text=re.compile(r"Reviews|리뷰", re.IGNORECASE)).first
            if review_btn.is_visible():
                review_btn.click(force=True)
            else:
                page.click("button[data-tab-index='1']", force=True)
            
            # [중요] 클릭 후 화면 전환을 위해 충분히 대기
            page.wait_for_timeout(7000)

            # 3. 데이터 로딩 확인 (요소가 뜰 때까지 최대 15초 대기)
            print("⏳ 데이터 렌더링 확인 중...")
            try:
                page.wait_for_selector(".wiI7pd", timeout=15000, state="visible")
                print("✅ 리뷰 텍스트 발견!")
            except:
                print("⚠️ 요소를 못 찾았습니다. 강제 휠로 로딩 유도...")
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(3000)

            collected = []
            processed_texts = set()
            
            # 4. 데이터 수집 루프
            for i in range(15):
                # 리뷰 아티클 전체 탐색
                articles = page.locator("div[role='article']").all()
                current_scroll_count = 0
                
                for art in articles:
                    try:
                        # 텍스트 추출
                        txt_el = art.locator(".wiI7pd")
                        if txt_el.count() == 0: continue
                        txt = txt_el.inner_text().strip()
                        
                        if not txt or len(txt) < 5 or txt in processed_texts: continue
                        
                        # 별점 추출
                        rating = 0
                        r_el = art.locator(".kvMYC").first
                        if r_el.count() > 0:
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

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 (총 {len(collected)}건)")

                # [핵심] 스크롤 타겟팅: 리뷰 리스트 박스 위에서 정확히 휠 굴리기
                try:
                    scroll_box = page.locator(".m67qrb, .DxyBCb, div[role='main']").first
                    box = scroll_box.bounding_box()
                    if box:
                        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        page.mouse.wheel(0, 4000)
                except:
                    page.mouse.wheel(0, 3000)
                
                page.wait_for_timeout(3500)

            # 5. 저장
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
            
            print(f"✨ {target_store_name} 완료! 신규 {new_added}건 추가")

        except Exception as e:
            print(f"❌ 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
