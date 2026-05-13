import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        # 봇 감지 우회 옵션 유지
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US"
        )
        page = context.new_page()
        # 기본 타임아웃을 60초로 상향
        page.set_default_timeout(60000)
        
        try:
            target_url = GOOGLE_MAPS_URL.split('?')[0].rstrip('/') + "/reviews/"
            print(f"🌐 타겟 진입 시도: {target_url}")
            
            # [수정] networkidle 대신 더 빠른 시점에 진행하도록 변경
            try:
                page.goto(target_url, wait_until="commit", timeout=60000)
            except Exception as e:
                print(f"⚠️ 페이지 로딩 중 타임아웃 발생(무시하고 진행): {e}")

            # 물리적으로 리뷰가 렌더링될 시간을 확보
            print("⏳ 리뷰 데이터 렌더링 대기 중 (10초)...")
            page.wait_for_timeout(10000)

            # 쿠키 동의 버튼 (보이면 무조건 클릭)
            try:
                page.get_by_role("button", name=re.compile("Accept all|Agree|동의", re.I)).first.click()
                print("✅ 쿠키 동의 완료")
            except: pass

            collected = []
            processed_texts = set()

            for i in range(15):
                # 리뷰 기사(article) 단위 수집
                articles = page.locator("div[role='article']").all()
                found_this_turn = 0
                
                for art in articles:
                    try:
                        # 리뷰 본문 클래스 .wiI7pd 타겟팅
                        content_el = art.locator(".wiI7pd").first
                        if content_el.count() == 0: continue
                        content = content_el.inner_text().strip()
                        
                        if not content or content in processed_texts or len(content) < 5: continue
                        if "Drag to change" in content: continue

                        # 작성자/날짜/별점 수집
                        author = "Anonymous"
                        try: author = art.locator(".d4r55").inner_text().strip()
                        except: pass

                        date_str = "Recent"
                        try: date_str = art.locator(".rsqaof").inner_text().strip()
                        except: pass

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

                if found_this_turn > 0:
                    print(f"🔄 {i+1}회차: {found_this_turn}건 추가 (누적 {len(collected)}건)")
                
                # 강제 스크롤
                page.mouse.move(500, 500)
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(3000)

            # 결과 저장
            if collected:
                data_path = "public/data/reviews.json"
                os.makedirs("public/data", exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(collected, f, ensure_ascii=False, indent=4)
                print(f"✨ 성공! 진짜 리뷰 {len(collected)}건 구출 완료.")
            else:
                print("❌ 데이터가 발견되지 않았습니다. 매장 주소를 다시 확인해주세요.")

        except Exception as e:
            print(f"🔥 치명적 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
