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
            viewport={"width": 1280, "height": 1000},
            locale="en-US" # 해외 매장 대응을 위해 로케일 고정
        )

        page = context.new_page()
        
        try:
            print(f"🌐 접속 시도: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            
            print("⏳ 매장 정보 로딩 및 리다이렉션 대기...")
            page.wait_for_timeout(10000) 

            # 1. 매장명 수집
            target_store_name = "Paik's Noodle" # 기본값
            try:
                # 여러 셀렉터 중 가장 먼저 잡히는 것 사용
                name_el = page.locator("h1").first
                if name_el.is_visible():
                    target_store_name = name_el.inner_text().strip()
            except: pass
            print(f"🏢 매장명 최종 확인: {target_store_name}")

            # 2. 리뷰 탭 클릭 (강력한 3단계 시도)
            print("🔘 리뷰 탭 진입 시도...")
            # 방법 A: 버튼 역할과 텍스트로 찾기
            review_btn = page.locator('button[role="tab"]', has_text=re.compile(r"Reviews|리뷰", re.IGNORECASE)).first
            
            if review_btn.is_visible():
                review_btn.hover()
                review_btn.click(force=True)
                print("✅ 리뷰 탭 클릭 명령 전송")
            else:
                # 방법 B: 클래스 기반 클릭 (구글 맵 고유 클래스)
                page.click("button[data-tab-index='1']", force=True)
                print("✅ 인덱스 기반 클릭 시도")
            
            page.wait_for_timeout(5000)

            # 3. 데이터 수집 전 '진짜' 스크롤 영역 확인
            # 구글 맵 리뷰 리스트의 본체 클래스: m67qrb 또는 DxyBCb
            print("⏳ 리뷰 리스트 본체 로딩 확인 중...")
            page.wait_for_selector(".wiI7pd", timeout=10000) # 리뷰 텍스트가 뜰 때까지 대기

            collected = []
            processed_texts = set()
            
            # 4. 데이터 수집 시작
            for i in range(15):
                articles = page.locator("div[role='article']").all()
                current_scroll_count = 0
                
                for art in articles:
                    try:
                        # 리뷰 텍스트 수집
                        txt_el = art.locator(".wiI7pd")
                        if txt_el.count() == 0: continue
                        txt = txt_el.inner_text().strip()
                        
                        if not txt or txt in processed_texts: continue
                        
                        # 별점 수집
                        rating = 0
                        try:
                            r_el = art.locator(".kvMYC")
                            if r_el.count() > 0:
                                r_label = r_el.first.get_attribute("aria-label") or ""
                                r_match = re.search(r'(\d)', r_label)
                                if r_match: rating = int(r_match.group(1))
                        except: pass

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

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 수집 (누적 {len(collected)}건)")

                # 스크롤: 마우스를 리뷰 영역 위로 옮긴 후 휠 굴리기
                try:
                    scroll_area = page.locator(".m67qrb, .DxyBCb, [role='main']").first
                    box = scroll_area.bounding_box()
                    if box:
                        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        page.mouse.wheel(0, 5000)
                except:
                    page.mouse.wheel(0, 3000)
                
                page.wait_for_timeout(3000)

            # 5. 저장 및 병합
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                with open(data_path, "r", encoding="utf-8") as f:
                    try: all_data = json.load(f)
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
            
            print(f"✨ {target_store_name} 완료! 신규 {new_added}건 추가 (전체 DB: {len(all_data)}건)")

        except Exception as e:
            print(f"❌ 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
