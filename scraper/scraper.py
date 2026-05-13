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
        # 가속도 및 보안 우회 설정
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
            # 대기 모드를 로딩 완료 시점으로 변경
            page.goto(GOOGLE_MAPS_URL, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(10000)

            # 1. 매장명 수집 (더 강력한 셀렉터)
            target_store_name = ""
            # 구글 맵 제목을 나타내는 다양한 클래스 시도
            name_candidates = [
                "h1.DUwDvf", 
                "h1.fontHeadlineLarge", 
                "xpath=//h1[contains(@class, 'DUwDvf')]",
                "xpath=//div[@role='main']//h1"
            ]
            
            for sel in name_candidates:
                try:
                    el = page.locator(sel).first
                    if el.is_visible():
                        name = el.inner_text().strip()
                        if name and "로그인" not in name and "최대한 활용" not in name and "data=" not in name:
                            target_store_name = name
                            break
                except: continue

            if not target_store_name:
                target_store_name = "테스트 매장_" + str(int(time.time()))[-4:]
            
            print(f"🏢 매장명 최종 확인됨: {target_store_name}")

            # 2. 리뷰 탭 클릭 (안전장치 강화)
            print("🔘 리뷰 탭 진입 시도...")
            # '리뷰'라는 글자가 들어간 버튼을 찾을 때까지 최대 10초 대기
            review_tab = page.get_by_role("tab").filter(has_text=re.compile("리뷰|Reviews")).first
            if review_tab.is_visible():
                review_tab.click(force=True)
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)
            else:
                # 탭 클릭 실패 시 주소 끝에 /reviews 를 붙여서 강제 이동 시도하는 로직은 복잡하니 일단 휠 시도
                print("⚠️ 리뷰 탭을 못 찾았습니다. 화면 중앙에서 수집을 시도합니다.")

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 시작 (스크롤 회차 증가)
            print("⏳ 데이터 수집 시작...")
            for i in range(12):
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
                
                # 스크롤 타겟팅 정밀화
                page.evaluate("""
                    const s = document.querySelector('div[role="main"] div.m67qrb') || 
                              document.querySelector('.DxyBCb') || 
                              document.querySelector('.m67qrb');
                    if (s) s.scrollTop = s.scrollHeight;
                """)
                page.wait_for_timeout(3000)

            # 4. 저장 및 병합 (중복 체크 로직 보강)
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                with open(data_path, "r", encoding="utf-8") as f:
                    try: all_data = json.load(f)
                    except: all_data = []

            # 매장명이 다르면 중복 체크를 하지 않도록 키 수정
            existing_texts = {d.get('text') for d in all_data if d.get('store_name') == target_store_name}
            
            new_added = 0
            for item in collected:
                if item['text'] not in existing_texts:
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
