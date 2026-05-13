import os
import json
import time
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")

def scrape():
    with sync_playwright() as p:
        # 자동화 감지 우회 설정 강화
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )

        # 신분증(쿠키) 장착
        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                cookies = json.loads(cookies_raw)
                for c in cookies: c['sameSite'] = "Lax"
                context.add_cookies(cookies)
                print("🍪 신분증 장착 완료")
            except: pass

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            
            # 1. 리뷰 탭 클릭
            page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first.click()
            print("✅ 리뷰 탭 진입")
            page.wait_for_timeout(3000)

            # 2. 최신순 정렬 시도 (3개월 데이터를 확실히 가져오기 위함)
            try:
                page.locator("button[aria-label*='정렬'], button[aria-label*='Sort']").first.click()
                page.wait_for_timeout(1500)
                page.locator("text='최신순', text='Newest'").first.click()
                print("✅ 최신순 정렬 적용")
                page.wait_for_timeout(3000)
            except:
                print("⚠️ 정렬 버튼 스킵 (기본순 수집)")

            all_collected = []
            processed_texts = set()
            
            # 3. 넉넉하게 15회 스크롤 (약 150~200건 수집 - 3개월치 충분)
            print("⏳ 3개월치 통 데이터 수집 시작...")
            
            for i in range(15):
                # 구글 맵 리뷰 텍스트를 담는 모든 가능성 있는 클래스 타겟팅
                items = page.locator(".wiI7pd, .MyE63c, .K7RMe").all()
                
                for item in items:
                    try:
                        text = item.inner_text().strip()
                        if not text or text in processed_texts: continue
                        
                        # 날짜는 필터링용이 아닌 '참고용'으로만 수집
                        parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                        date_el = parent.locator(".rsqaWe").first
                        date_str = date_el.inner_text() if date_el.count() > 0 else "최근"

                        all_collected.append({
                            "store_url": GOOGLE_MAPS_URL,
                            "text": text,
                            "date_raw": date_str,
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                    except: continue

                print(f"🔄 스크롤 {i+1}회: 현재 {len(all_collected)}건 확보")

                # 강제 스크롤 명령
                page.evaluate("""
                    const scrollable = document.querySelector('div[role="main"] div.m67qrb') || 
                                     document.querySelector('.DxyBCb') || 
                                     document.querySelector('.m67qrb');
                    if (scrollable) scrollable.scrollTop = scrollable.scrollHeight;
                """)
                page.wait_for_timeout(3000)

            # 데이터 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(all_collected, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 최종 성공! 총 {len(all_collected)}건의 통 데이터를 저장했습니다.")

        except Exception as e:
            print(f"❌ 에러: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
