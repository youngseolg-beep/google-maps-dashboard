import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL:
        print("❌ URL이 설정되지 않았습니다.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        # locale을 ko-KR로 설정하여 구글이 한국어 구조를 주도록 유도
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
            locale="ko-KR" 
        )

        page = context.new_page()
        
        try:
            print(f"🌐 접속 시도: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(10000) 

            # 1. 매장명 수집
            target_store_name = "Paik's Noodle"
            try:
                # h1 태그 내부의 텍스트를 가져옴
                target_store_name = page.locator("h1").first.inner_text().strip()
            except: pass
            print(f"🏢 매장명 확인: {target_store_name}")

            # 2. 리뷰 탭 클릭
            print("🔘 리뷰 탭 진입 시도...")
            # 텍스트 매칭 범위를 넓힘 (리뷰, Reviews, 评价 등)
            review_btn = page.get_by_role("tab").filter(has_text=re.compile(r"리뷰|Reviews|Review", re.I)).first
            
            if review_btn.is_visible():
                review_btn.click(force=True)
            else:
                # 탭 인덱스로 직접 클릭 (보통 2번째가 리뷰)
                page.locator("button[role='tab']").nth(1).click(force=True)
            
            print("⏳ 리뷰 리스트 로딩 대기 (15초)...")
            page.wait_for_timeout(15000)

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 루프 (스크롤 20회로 증폭)
            for i in range(20):
                # [핵심] 특정 클래스 대신 '리뷰 상자' 자체를 타겟팅
                articles = page.locator("div[role='article']").all()
                current_scroll_count = 0
                
                for art in articles:
                    try:
                        # 아티클 내부에서 가장 긴 텍스트 블록을 찾음 (이게 리뷰 내용일 확률 99%)
                        # 구글 맵의 리뷰 본문은 보통 특정 클래스나 span 안에 있음
                        content_locators = [".wiI7pd", ".MyE63c", "span"]
                        txt = ""
                        for loc in content_locators:
                            potential_text = art.locator(loc).first
                            if potential_text.count() > 0:
                                temp_txt = potential_text.inner_text().strip()
                                if len(temp_txt) > len(txt): # 가장 긴 텍스트 채택
                                    txt = temp_txt
                        
                        if not txt or len(txt) < 3 or txt in processed_texts: continue
                        
                        # 별점 추출
                        rating = 0
                        r_el = art.locator("[aria-label*='별점'], [aria-label*='star']").first
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

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 발견 (누적 {len(collected)}건)")

                # 스크롤: 리뷰 컨테이너를 찾아서 강제로 내림
                page.evaluate("""
                    const s = document.querySelector('.m67qrb') || 
                              document.querySelector('.DxyBCb') || 
                              document.querySelector('div[role="main"] div[tabindex="0"]');
                    if (s) s.scrollBy(0, 2000);
                    else window.scrollBy(0, 1500);
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
            
            print(f"✨ {target_store_name} 수집 완료! 신규 {new_added}건 추가")

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
