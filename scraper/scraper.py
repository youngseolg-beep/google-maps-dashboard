import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
            locale="ko-KR" # 한국어로 다시 시도 (익숙한 구조 유도)
        )

        page = context.new_page()
        
        try:
            print(f"🌐 타겟 재진입: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(10000)

            # 쿠키 동의 팝업 제거
            try:
                page.click("button[aria-label*='동의'], button[aria-label*='Accept'], button[aria-label*='Agree']", timeout=5000)
            except: pass

            # 리뷰 탭 강제 클릭
            try:
                page.locator('button[role="tab"]').filter(has_text=re.compile(r"리뷰|Reviews")).first.click()
                page.wait_for_timeout(5000)
            except: pass

            collected = []
            processed_texts = set()

            print("⏳ 데이터 정밀 스캔 및 스크롤 시작...")
            for i in range(15):
                # 텍스트 추출 그물을 더 촘촘하게 (클래스 + 구조)
                elements = page.locator(".wiI7pd, div[role='article']").all()
                found_this_turn = 0
                
                for el in elements:
                    try:
                        txt = el.inner_text().strip()
                        # 이름이나 짧은 단어 제외 (10자 이상만 리뷰로 간주)
                        if len(txt) > 10 and txt not in processed_texts:
                            if any(x in txt for x in ["공유", "수정", "삭제", "사진"]): continue
                            
                            collected.append({
                                "store_name": "Paik's Noodle Amsterdam",
                                "store_url": GOOGLE_MAPS_URL,
                                "text": txt,
                                "rating": 5,
                                "date_raw": "최근",
                                "collected_at": time.strftime("%Y-%m-%d")
                            })
                            processed_texts.add(txt)
                            found_this_turn += 1
                    except: continue
                
                print(f"🔄 회차 {i+1}: {found_this_turn}건 추가 발견 (누적 {len(collected)}건)")
                
                # [필살기] 스크롤: 마우스를 리스트 위로 옮기고 휠 + 키보드 End키 조합
                page.mouse.move(400, 600)
                page.mouse.wheel(0, 5000)
                page.keyboard.press("End")
                page.wait_for_timeout(4000)

            # 데이터 저장
            if len(collected) > 0:
                data_path = "public/data/reviews.json"
                # 이번 테스트는 결과 확인을 위해 새 데이터로 덮어쓰거나 확실히 병합
                all_data = []
                if os.path.exists(data_path):
                    with open(data_path, "r", encoding="utf-8") as f:
                        try: all_data = json.load(f)
                        except: all_data = []
                
                # 기존 데이터와 합치기 (중복 제거)
                existing_texts = {d.get('text') for d in all_data}
                new_entries = [c for c in collected if c['text'] not in existing_texts]
                all_data.extend(new_entries)
                
                os.makedirs("public/data", exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(all_data, f, ensure_ascii=False, indent=4)
                
                print(f"✨ 최종 성공! {len(new_entries)}건의 신규 리뷰를 확보했습니다. (총 DB: {len(all_data)}건)")
            else:
                print("❌ 수집된 데이터가 없습니다.")

        except Exception as e:
            print(f"❌ 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
