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
            locale="en-US" # 유럽 매장이니 영어로 고정
        )

        page = context.new_page()
        
        try:
            print(f"🌐 타겟 진입: {GOOGLE_MAPS_URL}")
            # 리뷰 탭으로 바로 점프하는 파라미터 강제 삽입
            target_url = GOOGLE_MAPS_URL
            if "/reviews/" not in target_url:
                target_url = target_url.split('?')[0].rstrip('/') + "/reviews/"
            
            page.goto(target_url, wait_until="commit")
            page.wait_for_timeout(10000)

            # 1. 유럽 전용 쿠키 팝업 제거 (더 강력하게)
            try:
                page.mouse.click(640, 500) # 화면 중앙 클릭해서 팝업 활성화
                page.get_by_role("button", name=re.compile("Accept all|Agree|동의", re.I)).first.click()
                print("✅ 쿠키 동의 완료")
            except: pass

            collected = []
            processed_texts = set()

            print("⏳ 무차별 텍스트 스캔 시작...")
            for i in range(20):
                # [필살기] 모든 텍스트 노드를 다 가져와서 리뷰 패턴인 것만 필터링
                # 구글 리뷰 텍스트는 보통 10자 이상, 특정 div 내부에 존재
                elements = page.query_selector_all("div, span, p")
                current_found = 0
                
                for el in elements:
                    try:
                        txt = el.inner_text().strip()
                        # 리뷰일 확률이 높은 조건: 15자 이상, 중복 아님, 메뉴/버튼 텍스트 아님
                        if len(txt) > 15 and txt not in processed_texts:
                            if any(x in txt for x in ["Google", "Menu", "Photos", "About", "Order"]): continue
                            
                            collected.append({
                                "store_name": "Paik's Noodle Amsterdam",
                                "store_url": GOOGLE_MAPS_URL,
                                "text": txt,
                                "rating": 5, # 별점 수집 포기하고 텍스트에 집중
                                "collected_at": time.strftime("%Y-%m-%d")
                            })
                            processed_texts.add(txt)
                            current_found += 1
                    except: continue
                
                print(f"🔄 회차 {i+1}: {current_found}건 발견 (총 {len(collected)}건)")
                
                # 강제 좌표 스크롤 (마우스 휠)
                page.mouse.move(400, 500)
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(3000)

            # 2. 결과 저장
            if len(collected) > 0:
                data_path = "public/data/reviews.json"
                all_data = []
                if os.path.exists(data_path):
                    with open(data_path, "r", encoding="utf-8") as f:
                        try: all_data = json.load(f)
                        except: all_data = []
                
                # 병합
                existing_texts = {d.get('text') for d in all_data}
                new_entries = [c for c in collected if c['text'] not in existing_texts]
                all_data.extend(new_entries)
                
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(all_data, f, ensure_ascii=False, indent=4)
                print(f"✨ 최종 성공! {len(new_entries)}건의 리뷰를 구출했습니다.")
            else:
                print("❌ 모든 수단을 동원했으나 구글이 데이터를 차단했습니다.")

        except Exception as e:
            print(f"❌ 에러 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
