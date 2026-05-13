# scraper/scraper.py 수정본 (신분증 보정 기능 추가)
import os
import json
import time
from playwright.sync_api import sync_playwright

def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                cookies = json.loads(cookies_raw)
                
                # 🛠️ [핵심 수정] 로봇이 이해할 수 있게 쿠키 형식 보정
                for cookie in cookies:
                    # sameSite 값이 없거나 이상하면 'Lax'로 강제 고정
                    if 'sameSite' in cookie:
                        if cookie['sameSite'] not in ["Strict", "Lax", "None"]:
                            # 첫 글자만 대문자로 바꾸기 (예: 'unspecified' -> 'Lax')
                            cookie['sameSite'] = "Lax"
                    else:
                        cookie['sameSite'] = "Lax"
                
                context.add_cookies(cookies)
                print("🍪 신분증(쿠키) 형식 보정 및 장착 완료!")
            except Exception as e:
                print(f"❌ 쿠키 장착 실패: {e}")

        page = context.new_page()
        
        try:
            # 주소로 이동
            target_url = os.environ.get("GOOGLE_MAPS_URL")
            print(f"🌐 접속 중: {target_url}")
            
            # 구글이 로봇을 의심하지 않게 천천히 접속
            page.goto(target_url, wait_until="commit", timeout=60000)
            page.wait_for_timeout(15000) # 넉넉하게 15초 대기 (리뷰 로딩 시간)

            # 리뷰 텍스트 수집 (선택자를 더 넓게 잡았습니다)
            reviews = []
            review_elements = page.locator(".wiI7pd, .MyE63c, .K7RMe, [class*='review-text']").all()
            
            for el in review_elements:
                text = el.inner_text().strip()
                if text:
                    reviews.append({"text": text, "date": "2026-05-13"})

            # 결과 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 수집 성공! 총 {len(reviews)}건의 리뷰를 저장했습니다.")

        except Exception as e:
            print(f"❌ 에러 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
