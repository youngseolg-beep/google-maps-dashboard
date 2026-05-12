import os
import json
import time
import re
import random
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# [1] 환경 변수 설정
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "https://www.google.com/maps/place/9")
START_DATE_STR = os.environ.get("START_DATE", "2026-05-01")

try:
    START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
except:
    START_DATE = datetime.now() - timedelta(days=30)

def parse_relative_date(date_str):
    now = datetime.now()
    if not date_str: return now
    # '방금 전', '1시간 전' 등은 오늘로 처리
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
    with sync_playwright() as p:
        # [우회 전략 1] 봇 감지를 피하기 위해 자동화 표시를 제거하고 실행합니다.
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        
        # 실제 사용자가 가장 많이 쓰는 브라우저 정보를 흉내냅니다.
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="ko-KR"
        )
        page = context.new_page()
        
        print(f"🚀 [접속 시작] {GOOGLE_MAPS_URL}")
        
        try:
            # 주소 접속 (최대 2분 대기)
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(10000) # 페이지 안정화 대기
            
            # [우회 전략 2] "리뷰" 탭을 강제로 찾아 클릭합니다.
            # 텍스트가 담긴 모든 요소를 뒤져서 '리뷰'가 들어간 버튼을 찾습니다.
            print("🔍 리뷰 탭 탐색 중...")
            review_selectors = [
                "button:has-text('리뷰')",
                "div[role='tab']:has-text('리뷰')",
                "span:has-text('리뷰')",
                "[aria-label*='리뷰']"
            ]
            
            clicked = False
            for sel in review_selectors:
                try:
                    targets = page.locator(sel).all()
                    for target in targets:
                        if target.is_visible():
                            target.click()
                            print(f"✅ 리뷰 탭 클릭 성공 ({sel})")
                            clicked = True
                            break
                    if clicked: break
                except: continue
            
            if not clicked:
                print("⚠️ 리뷰 탭을 직접 클릭하지 못했습니다. 현재 화면에서 수집을 시도합니다.")
            
            page.wait_for_timeout(5000)

            # [우회 전략 3] 최신순 정렬 시도
            try:
                page.get_by_label("리뷰 정렬").first.click(timeout=5000)
                page.wait_for_timeout(2000)
                page.get_by_role("menuitemradio", name="최신순").click()
                print("✅ 최신순 정렬 완료")
                page.wait_for_timeout(3000)
            except:
                print("ℹ️ 정렬 건너뜀")

            reviews = []
            processed_ids = set()
            
            # [우회 전략 4] 리뷰 요소 탐지 강화 (구글 맵의 거의 모든 가능성 있는 클래스 포함)
            print("📡 리뷰 데이터 스캔 중...")
            for scroll in range(40): # 최대 40번 스크롤
                # 구글 맵 최신 UI의 리뷰 상자 클래스들
                items = page.locator(".jftiEf, .G5u99, .WNo9u, [role='article']").all()
                
                if not items:
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(3000)
                    continue

                new_on_this_scroll = False
                for item in items:
                    try:
                        # 리뷰 텍스트 가져오기
                        text_el = item.locator(".wiI7pd, .MyE63c, .K7RMe")
                        if text_el.count() == 0: continue
                        
                        review_text = text_el.first.inner_text().strip()
                        if not review_text: continue
                        
                        # 중복 체크를 위해 텍스트 앞부분 활용
                        unique_id = review_text[:50]
                        if unique_id in processed_ids: continue
                        processed_ids.add(unique_id)
                        new_on_this_scroll = True

                        # 날짜 파싱
                        date_str = ""
                        date_el = item.locator(".rsqaWe, .x39p9b")
                        if date_el.count() > 0:
                            date_str = date_el.first.inner_text().strip()
                        
                        actual_date = parse_relative_date(date_str)
                        
                        # 중단 기준 체크
                        if actual_date < START_DATE:
                            print(f"🛑 기준 날짜({START_DATE_STR}) 이전 리뷰 도달. 수집을 마칩니다.")
                            new_on_this_scroll = False
                            break

                        # 별점 파싱
                        rating = 5
                        try:
                            label = item.locator(".kvMYJc").get_attribute("aria-label")
                            rating = int(re.search(r'\d+', label).group())
                        except: pass

                        # 작성자 파싱
                        author = "고객"
                        author_el = item.locator(".d4r55, .XE7Yid")
                        if author_el.count() > 0:
                            author = author_el.first.inner_text().strip()

                        reviews.append({
                            "author": author,
                            "rating": rating,
                            "text": review_text,
                            "date": actual_date.strftime("%Y-%m-%d")
                        })
                    except: continue

                if not new_on_this_scroll and len(reviews) > 0:
                    break # 더 이상 새 리뷰가 없으면 종료
                
                # 스크롤 내리기
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(2500)

            print(f"🏁 [결과] 최종 수집 성공: {len(reviews)}건")

            # 데이터 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
        except Exception as e:
            print(f"❌ 치명적 에러 발생: {e}")
        
        finally:
            browser.close()

if __name__ == "__main__":
    scrape_reviews()
