import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()
        
        try:
            # 1. 리뷰 직접 경로 접속
            target_url = GOOGLE_MAPS_URL.split('?')[0].rstrip('/') + "/reviews/"
            print(f"🌐 타겟 진입: {target_url}")
            page.goto(target_url, wait_until="domcontentloaded")
            
            # 2. 쿠키 및 팝업 제거
            page.wait_for_timeout(5000)
            try:
                page.get_by_role("button", name=re.compile("Accept all|Agree|동의", re.I)).first.click()
            except: pass

            # 3. 정렬 버튼 클릭 (최신순으로 변경하여 데이터 갱신 유도)
            print("↕️ 최신순 정렬 시도...")
            try:
                page.get_by_role("button", name=re.compile("Sort|정렬", re.I)).click()
                page.wait_for_timeout(2000)
                page.get_by_role("menuitem", name=re.compile("Newest|최신순", re.I)).click()
                page.wait_for_timeout(3000)
            except: pass

            collected = []
            processed_texts = set()

            # 4. 수집 루프
            for i in range(15):
                # [핵심] 구글 리뷰 텍스트의 '진짜' 클래스만 타겟팅
                # .wiI7pd: 리뷰 본문 / [aria-label*='star']: 별점
                review_elements = page.locator("div[role='article']").all()
                
                for art in review_elements:
                    try:
                        # 본문 추출 (숨겨진 '자세히 보기'가 있다면 클릭)
                        more_btn = art.locator("button:has-text('자세히'), button:has-text('More')").first
                        if more_btn.is_visible(): more_btn.click()
                        
                        txt_el = art.locator(".wiI7pd").first
                        if txt_el.count() == 0: continue
                        
                        txt = txt_el.inner_text().strip()
                        if not txt or txt in processed_texts or len(txt) < 5: continue
                        
                        # 시스템 문구 필터링 (완전 차단)
                        if any(x in txt for x in ["Collapse", "Nearby", "Hotels", "Drag to change"]): continue

                        # 별점 추출
                        rating = 5
                        try:
                            star_el = art.locator("span[aria-label*='star'], span[aria-label*='별점']").first
                            label = star_el.get_attribute("aria-label")
                            rating = int(re.search(r'\d', label).group())
                        except: pass

                        collected.append({
                            "store_name": "Paik's Noodle Amsterdam",
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                    except: continue

                print(f"🔄 {i+1}회차: 누적 {len(collected)}건 확보")
                
                # 스크롤: 리뷰 상자를 정확히 타겟팅
                page.mouse.move(400, 500)
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(3000)

            # 5. 저장 (기존 쓰레기 데이터 덮어쓰기 위해 새로 작성)
            if collected:
                data_path = "public/data/reviews.json"
                os.makedirs("public/data", exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(collected, f, ensure_ascii=False, indent=4)
                print(f"✨ 성공! 진짜 리뷰 {len(collected)}건 저장 완료.")

        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
