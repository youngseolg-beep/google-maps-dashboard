import os
import json
import time
import re
import random
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")
START_DATE_STR = os.environ.get("START_DATE", "2026-05-01")

try:
    START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
except:
    START_DATE = datetime.now() - timedelta(days=60)

def parse_relative_date(date_str):
    now = datetime.now()
    if not date_str: return now
    if any(x in date_str for x in ['초', '분', '시간', '방금']): return now
    match = re.search(r'(\d+)(일|주|달|개월|년)\s*전', date_str)
    if not match: return now
    num, unit = int(match.group(1)), match.group(2)
    if unit == '일': return now - timedelta(days=num)
    elif unit == '주': return now - timedelta(weeks=num)
    elif unit in ['달', '개월']: return now - timedelta(days=num * 30)
    elif unit == '년': return now - timedelta(days=num * 365)
    return now

def scrape_reviews():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        # [장치 1] 자동화 감지 우회 옵션을 극대화합니다.
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox"
        ])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()
        
        print(f"🚀 [최종 테스트] 접속 중: {GOOGLE_MAPS_URL}")
        
        try:
            # 주소 접속 (여유롭게 대기)
            page.goto(GOOGLE_MAPS_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)

            # [장치 2] 리뷰 탭을 찾기 위해 '리뷰'라는 텍스트를 가진 요소를 클릭
            print("🔍 리뷰 탭 활성화 시도...")
            review_btn = page.get_by_role("button", name=re.compile(r"리뷰", re.I)).first
            if review_btn.is_visible():
                review_btn.click()
                page.wait_for_timeout(3000)
            
            # 최신순 정렬
            try:
                page.get_by_label("리뷰 정렬").click(timeout=3000)
                page.wait_for_timeout(1000)
                page.get_by_role("menuitemradio", name="최신순").click()
                page.wait_for_timeout(2000)
            except:
                pass

            reviews = []
            processed_ids = set()
            
            print("📡 리뷰 스캔 중 (클래스 무시 강제 수집)...")
            
            for scroll in range(20):
                # [장치 3] 특정 클래스가 아니라, 리뷰 작성 날짜(rsqaWe)가 포함된 모든 구역을 뒤집니다.
                # 구글 맵 리뷰의 가장 변하지 않는 특징인 '날짜' 요소를 기준으로 역추적합니다.
                date_elements = page.locator(".rsqaWe").all()
                
                if not date_elements:
                    # 아무것도 안 보이면 조금 더 스크롤
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(2000)
                    continue

                for date_el in date_elements:
                    try:
                        # 날짜 요소의 부모(리뷰 전체 칸)를 찾습니다.
                        container = date_el.locator("xpath=./ancestor::div[contains(@class, 'jftiEf') or contains(@role, 'article')]").first
                        
                        # 텍스트 내용 가져오기
                        text_el = container.locator(".wiI7pd").first
                        if not text_el.is_visible(): continue
                        
                        review_text = text_el.inner_text().strip()
                        if not review_text or review_text in processed_ids: continue
                        
                        processed_ids.add(review_text[:50]) # 중복 방지
                        
                        date_str = date_el.inner_text().strip()
                        actual_date = parse_relative_date(date_str)

                        if actual_date < START_DATE:
                            continue

                        reviews.append({
                            "author": "고객",
                            "rating": 5,
                            "text": review_text,
                            "date": actual_date.strftime("%Y-%m-%d")
                        })
                    except:
                        continue

                print(f"🔄 현재 {len(reviews)}건 수집됨...")
                if len(reviews) >= 20: break
                
                # 천천히 스크롤 (로딩 시간을 줍니다)
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(2500)

            print(f"🏁 최종 수집 완료: {len(reviews)}건")

            # 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
        except Exception as e:
            print(f"❌ 에러: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape_reviews()
