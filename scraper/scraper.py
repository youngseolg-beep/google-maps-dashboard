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
            # 리뷰 페이지로 직접 진입
            target_url = GOOGLE_MAPS_URL.split('?')[0].rstrip('/') + "/reviews/"
            print(f"🌐 타겟 진입: {target_url}")
            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            # 유럽 쿠키 동의 팝업 처리
            try:
                page.get_by_role("button", name=re.compile("Accept all|Agree|동의", re.I)).first.click()
            except: pass

            collected = []
            processed_texts = set()

            for i in range(15):
                # 1. 리뷰 상자(Article) 단위로 탐색 (이미지의 한 리뷰 단위를 의미)
                review_articles = page.locator("div[role='article']").all()
                
                for art in review_articles:
                    try:
                        # 2. [내용] 추출 및 '자세히 보기' 처리
                        more_btn = art.locator("button:has-text('자세히'), button:has-text('More')").first
                        if more_btn.is_visible(): more_btn.click()
                        
                        txt_el = art.locator(".wiI7pd").first
                        if txt_el.count() == 0: continue
                        content = txt_el.inner_text().strip()
                        
                        if not content or content in processed_texts: continue

                        # 3. [작성자 이름] 추출 (이미지의 'win' 부분)
                        author = "익명"
                        author_el = art.locator(".d4r55").first # 작성자명 클래스
                        if author_el.count() > 0:
                            author = author_el.inner_text().strip()

                        # 4. [별점] 추출 (이미지의 노란 별 부분)
                        rating = 5
                        try:
                            star_el = art.locator("span[aria-label*='star'], span[aria-label*='별점']").first
                            label = star_el.get_attribute("aria-label")
                            rating = int(re.search(r'\d', label).group())
                        except: pass

                        # 5. [날짜] 추출 (이미지의 '3개월 전' 부분)
                        date_str = "최근"
                        date_el = art.locator(".rsqaof").first # 날짜 클래스
                        if date_el.count() > 0:
                            date_str = date_el.inner_text().strip()

                        collected.append({
                            "store_name": "Paik's Noodle Amsterdam",
                            "author": author,
                            "rating": rating,
                            "text": content,
                            "date": date_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(content)
                    except: continue

                print(f"🔄 {i+1}회차: {len(collected)}건 확보 중...")
                
                # 스크롤해서 다음 리뷰 로딩
                page.mouse.move(400, 600)
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(3000)

            # 저장
            if collected:
                data_path = "public/data/reviews.json"
                os.makedirs("public/data", exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(collected, f, ensure_ascii=False, indent=4)
                print(f"✨ 성공! 정밀 수집된 리뷰 {len(collected)}건 저장 완료.")

        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
