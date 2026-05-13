import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        # headless=True로 하되, 감지 우회 옵션 추가
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US" # 유럽 매장이니 영문으로 고정해서 구조 일원화
        )
        page = context.new_page()
        
        try:
            # 1. 리뷰 직접 경로 접속
            target_url = GOOGLE_MAPS_URL.split('?')[0].rstrip('/') + "/reviews/"
            print(f"🌐 타겟 진입: {target_url}")
            page.goto(target_url, wait_until="networkidle") # 네트워크가 조용해질 때까지 대기
            page.wait_for_timeout(7000)

            # 2. 쿠키 동의 (유럽 필수)
            try:
                page.get_by_role("button", name=re.compile("Accept all|Agree|동의", re.I)).first.click()
                print("✅ 쿠키 동의 완료")
            except: pass

            collected = []
            processed_texts = set()

            for i in range(15):
                # [수정] 클래스명이 바뀌어도 찾을 수 있게 role='article' 내부의 모든 div를 훑음
                articles = page.locator("div[role='article']").all()
                found_this_turn = 0
                
                for art in articles:
                    try:
                        # 본문 텍스트 (구글 리뷰의 가장 핵심적인 긴 문장 div 찾기)
                        content_el = art.locator(".wiI7pd").first
                        if content_el.count() == 0: continue
                        content = content_el.inner_text().strip()
                        
                        if not content or content in processed_texts or len(content) < 5: continue
                        if "Drag to change" in content: continue

                        # 작성자명 (보통 이미지 옆의 첫 번째 굵은 글씨)
                        author = "Anonymous"
                        try:
                            # 작성자 클래스 .d4r55가 없으면 주변 텍스트 시도
                            author = art.locator(".d4r55").inner_text().strip()
                        except: pass

                        # 날짜 (보통 별점 옆의 상대적 시간)
                        date_str = "Recent"
                        try:
                            date_str = art.locator(".rsqaof").inner_text().strip()
                        except: pass

                        # 별점
                        rating = 5
                        try:
                            star_label = art.locator("span[aria-label*='star']").get_attribute("aria-label")
                            rating = int(re.search(r'\d', star_label).group())
                        except: pass

                        collected.append({
                            "store_name": "Paik's Noodle Amsterdam",
                            "author": author,
                            "rating": rating,
                            "text": content,
                            "date": date_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(content)
                        found_this_turn += 1
                    except: continue

                print(f"🔄 {i+1}회차: {found_this_turn}건 추가 (누적 {len(collected)}건)")
                
                # 강제 스크롤: 마우스 휠을 더 세게
                page.mouse.move(500, 500)
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(4000)

            # 3. 저장
            if collected:
                data_path = "public/data/reviews.json"
                os.makedirs("public/data", exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(collected, f, ensure_ascii=False, indent=4)
                print(f"✨ 성공! 진짜 리뷰 {len(collected)}건 구출 완료.")
            else:
                print("❌ 여전히 리뷰를 찾지 못했습니다. 화면 캡처 분석이 필요할 수 있습니다.")

        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
