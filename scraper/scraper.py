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

    # [수정] 리뷰 페이지로 직접 이동하기 위한 URL 변환
    if "/reviews/" not in GOOGLE_MAPS_URL:
        if "?" in GOOGLE_MAPS_URL:
            direct_url = GOOGLE_MAPS_URL.replace("?", "/reviews/?")
        else:
            direct_url = GOOGLE_MAPS_URL.rstrip("/") + "/reviews/"
    else:
        direct_url = GOOGLE_MAPS_URL

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
            locale="en-US"
        )

        page = context.new_page()
        
        try:
            print(f"🌐 직접 접속 시도: {direct_url}")
            page.goto(direct_url, wait_until="domcontentloaded", timeout=60000)
            
            # 1. 쿠키 및 방해 팝업 제거 (유럽 지역 필수)
            print("🍪 방해 요소(쿠키 동의 등) 확인 중...")
            page.wait_for_timeout(5000)
            popups = [
                "button[aria-label*='Accept all']",
                "button[aria-label*='Agree']",
                "text='Accept all'",
                "text='I agree'"
            ]
            for sel in popups:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        btn.click()
                        print(f"✅ 팝업 제거 성공 ({sel})")
                        page.wait_for_timeout(3000)
                except: continue

            # 2. 매장명 확인
            target_store_name = "Paik's Noodle Amsterdam"
            try:
                page.wait_for_selector("h1", timeout=10000)
                target_store_name = page.locator("h1").first.inner_text().strip()
            except: pass
            print(f"🏢 매장명: {target_store_name}")

            # 3. 데이터 수집 루프
            collected = []
            processed_texts = set()
            
            print("⏳ 리뷰 데이터 긁어모으기 시작...")
            for i in range(15):
                # 리뷰 아티클(칸)들을 모두 찾음
                articles = page.locator("div[role='article']").all()
                current_scroll_count = 0
                
                for art in articles:
                    try:
                        # 아티클 내부의 텍스트 덩어리 추출
                        # .wiI7pd 가 안 잡힐 경우를 대비해 텍스트 전체를 가져옴
                        raw_text = art.inner_text().strip()
                        
                        # 리뷰 본문만 발라내기 위한 정규식 (작성자, 별점 정보 제외 시도)
                        # 구글 맵 리뷰 본문은 보통 특정 클래스에 담김
                        content_el = art.locator(".wiI7pd").first
                        if content_el.count() > 0:
                            txt = content_el.inner_text().strip()
                        else:
                            # 클래스를 못 찾으면 텍스트 중 가장 긴 단락 선택
                            txt = max(raw_text.split('\n'), key=len)

                        if not txt or len(txt) < 5 or txt in processed_texts: continue
                        
                        # 별점 추출
                        rating = 0
                        r_el = art.locator("[aria-label*='star']").first
                        if r_el.count() > 0:
                            r_label = r_el.get_attribute("aria-label") or ""
                            r_match = re.search(r'(\d)', r_label)
                            if r_match: rating = int(r_match.group(1))

                        collected.append({
                            "store_name": target_store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "date_raw": "Recent",
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                        current_scroll_count += 1
                    except: continue

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 (총 {len(collected)}건)")

                # 스크롤: 리뷰 상자 중앙 조준
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

            existing_keys = {f"{d.get('store_name')}_{d.get('text')[:30]}" for d in all_data}
            new_added = 0
            for item in collected:
                if f"{item['store_name']}_{item['text'][:30]}" not in existing_keys:
                    all_data.append(item)
                    new_added += 1

            os.makedirs("public/data", exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=4)
            
            print(f"✨ {target_store_name} 완료! 신규 {new_added}건 추가")

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
