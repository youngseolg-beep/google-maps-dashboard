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
            # 페이지 이동 후 뼈대가 로드될 때까지 대기
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            
            # [중요] 주소 리다이렉션 및 매장 제목이 뜰 때까지 최대 20초 대기
            print("⏳ 실제 매장 정보로 리다이렉션 대기 중...")
            page.wait_for_timeout(10000) 

            # 1. 매장명 수집 (더 정밀한 필터링)
            target_store_name = "알 수 없는 매장"
            # h1 태그 중 실제 이름일 가능성이 높은 것들 순차 확인
            for _ in range(5): # 2초씩 5번 확인
                name_el = page.locator("h1.DUwDvf, h1.fontHeadlineLarge, h1").first
                if name_el.is_visible():
                    name = name_el.inner_text().strip()
                    if name and "로그인" not in name and "data=" not in name:
                        target_store_name = name
                        break
                page.wait_for_timeout(2000)
            
            print(f"🏢 매장명 최종 확인: {target_store_name}")

            # 2. 리뷰 탭 클릭
            print("🔘 리뷰 탭 진입 시도...")
            # 리뷰 글자가 포함된 버튼을 찾아 클릭
            review_btn = page.locator("button[role='tab']").filter(has_text=re.compile("리뷰|Reviews")).first
            if review_btn.is_visible():
                review_btn.click(force=True)
                page.wait_for_timeout(5000)
            
            # 리뷰 상자(.wiI7pd)가 나타날 때까지 대기
            try:
                page.wait_for_selector(".wiI7pd", timeout=15000)
                print("✅ 리뷰 데이터 로드 확인됨")
            except:
                print("⚠️ 리뷰 텍스트 요소를 찾지 못했습니다. 스크롤을 시도하며 찾습니다.")

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 시작
            for i in range(15):
                # 구글 맵의 리뷰 텍스트를 담는 클래스들
                articles = page.locator("div[role='article']").all()
                
                current_scroll_count = 0
                for art in articles:
                    try:
                        # 텍스트 추출 (여러 가능성 대비)
                        txt = ""
                        text_el = art.locator(".wiI7pd")
                        if text_el.count() > 0:
                            txt = text_el.inner_text().strip()
                        
                        if not txt or txt in processed_texts: continue
                        
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

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 수집 (누적 {len(collected)}건)")

                # 스크롤 명령 (수집 성능 향상을 위해 조금 더 위에서 스크롤)
                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || 
                              document.querySelector('.DxyBCb') || 
                              document.querySelector('.m67qrb');
                    if (s) {
                        s.scrollTop = s.scrollHeight;
                    } else {
                        window.scrollBy(0, 1000);
                    }
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

            # 신규 데이터 추가
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
