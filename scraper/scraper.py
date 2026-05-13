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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
            locale="ko-KR"
        )

        page = context.new_page()
        
        try:
            print(f"🌐 접속 시도: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(10000) 

            # 1. 매장명 수집
            target_store_name = "Paik's Noodle"
            try:
                name_el = page.locator("h1").first
                if name_el.count() > 0:
                    target_store_name = name_el.inner_text().strip()
            except: pass
            print(f"🏢 매장명 확인: {target_store_name}")

            # 2. 리뷰 탭 클릭
            print("🔘 리뷰 탭 진입 시도...")
            try:
                # 텍스트가 '리뷰' 또는 'Reviews'인 버튼을 찾아 클릭
                review_btn = page.locator('button[role="tab"]').filter(has_text=re.compile(r"리뷰|Reviews")).first
                if review_btn.is_visible():
                    review_btn.click(force=True)
                else:
                    # 탭 인덱스로 직접 클릭 (보통 2번째 탭)
                    page.locator("button[role='tab']").nth(1).click(force=True)
                print("✅ 리뷰 탭 클릭 완료")
            except:
                print("⚠️ 리뷰 탭 클릭 실패, 현재 상태에서 수집 강행")

            print("⏳ 데이터 렌더링 대기 (10초)...")
            page.wait_for_timeout(10000)

            collected = []
            processed_texts = set()
            
            # 3. 데이터 수집 루프
            for i in range(15):
                # [수정] 클래스명에 의존하지 않고 리뷰 아티클 자체를 타겟팅
                articles = page.locator("div[role='article']").all()
                current_scroll_count = 0
                
                for art in articles:
                    try:
                        # 아티클 내부의 모든 span 태그 텍스트를 합쳐서 리뷰 본문 추출
                        # 보통 리뷰 본문은 글자 수가 많으므로 필터링
                        txt = art.inner_text().replace('\n', ' ').strip()
                        
                        # 이미 처리했거나 너무 짧은 텍스트(이름, 날짜 등)는 제외
                        if not txt or len(txt) < 10 or txt in processed_texts: continue
                        
                        # 별점 추출 (aria-label에서 숫자 찾기)
                        rating = 0
                        r_el = art.locator("[aria-label*='별점'], [aria-label*='star']").first
                        if r_el.count() > 0:
                            r_label = r_el.get_attribute("aria-label") or ""
                            r_match = re.search(r'(\d)', r_label)
                            if r_match: rating = int(r_match.group(1))

                        # 우리가 원하는 건 '리뷰 내용'이므로 작성자 이름 등을 걸러내는 최소한의 필터
                        if "리뷰" in txt or "공유" in txt or "사진" in txt:
                            # 구글 맵 특유의 버튼 텍스트가 섞여있다면 정제 시도
                            txt = txt.split("공유")[0].strip()

                        collected.append({
                            "store_name": target_store_name,
                            "store_url": GOOGLE_MAPS_URL,
                            "text": txt,
                            "rating": rating,
                            "date_raw": "최근",
                            "collected_at": time.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(txt)
                        current_scroll_count += 1
                    except: continue

                print(f"🔄 회차 {i+1}: +{current_scroll_count}건 발견 (누적 {len(collected)}건)")

                # [수정] 더 정교한 스크롤: 리뷰 상자 중앙으로 마우스 이동 후 휠 굴리기
                try:
                    scroll_box = page.locator('.m67qrb, .DxyBCb, div[role="main"]').first
                    if scroll_box.is_visible():
                        box = scroll_box.bounding_box()
                        if box:
                            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            page.mouse.wheel(0, 3000)
                    else:
                        page.mouse.wheel(0, 3000)
                except:
                    page.mouse.wheel(0, 2000)
                
                page.wait_for_timeout(3000)

            # 4. 저장 및 병합
            data_path = "public/data/reviews.json"
            all_data = []
            if os.path.exists(data_path):
                try:
                    with open(data_path, "r", encoding="utf-8") as f:
                        all_data = json.load(f)
                except: all_data = []

            existing_keys = {f"{d.get('store_name')}_{d.get('text')[:20]}" for d in all_data}
            new_added = 0
            for item in collected:
                # 텍스트 앞부분 20자로 중복 체크 (정제된 텍스트 대응)
                if f"{item['store_name']}_{item['text'][:20]}" not in existing_keys:
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
