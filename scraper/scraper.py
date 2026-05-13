import os
import json
import time
import random
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# 설정값 가져오기
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")

def parse_date(date_str):
    now = datetime.now()
    if not date_str: return now
    match = re.search(r'(\d+)(일|주|달|개월|년)\s*전', date_str)
    if not match: return now
    num, unit = int(match.group(1)), match.group(2)
    if unit == '일': return now - timedelta(days=num)
    elif unit == '주': return now - timedelta(weeks=num)
    elif unit in ['달', '개월']: return now - timedelta(days=num * 30)
    elif unit == '년': return now - timedelta(days=num * 365)
    return now

def scrape():
    with sync_playwright() as p:
        # 1. 브라우저 실행 (사람처럼 보이기 위해 자동화 감지 우회 옵션 추가)
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        # 🔐 2. 금고(Secrets)에서 신분증(쿠키) 꺼내서 장착하기
        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                # 텍스트로 된 금고 내용을 리스트 형식으로 변환
                cookies = json.loads(cookies_raw)
                context.add_cookies(cookies)
                print("🍪 신분증(쿠키) 장착 완료! 구글이 아는 척을 해줄 겁니다.")
            except Exception as e:
                print(f"❌ 쿠키 장착 실패 (형식 확인 필요): {e}")
        else:
            print("⚠️ 신분증(쿠키)이 금고에 없습니다. 일반 모드로 시도합니다.")

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            # 신분증이 있으므로 페이지가 뜰 때까지 넉넉히 기다립니다.
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000) # 화면이 그려질 시간 10초 대기

            reviews = []
            processed_texts = set()

            # 3. 데이터 수집 (화면에 보이는 리뷰 낚아채기)
            # 구글 맵 리뷰 텍스트의 대표적인 클래스들입니다.
            items = page.locator(".wiI7pd, .MyE63c, .K7RMe").all()
            
            for item in items:
                try:
                    text = item.inner_text().strip()
                    if not text or text in processed_texts: continue
                    
                    # 날짜 찾기
                    parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                    date_str = ""
                    if parent.count() > 0:
                        date_el = parent.first.locator(".rsqaWe")
                        if date_el.count() > 0:
                            date_str = date_el.first.inner_text()
                    
                    actual_date = parse_date(date_str)
                    processed_texts.add(text)

                    reviews.append({
                        "author": "고객",
                        "rating": 5,
                        "text": text,
                        "date": actual_date.strftime("%Y-%m-%d")
                    })
                except: continue

            # 4. 결과 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 수집 성공! 총 {len(reviews)}건의 리뷰를 찾았습니다.")

        except Exception as e:
            print(f"❌ 크롤링 중 에러 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
