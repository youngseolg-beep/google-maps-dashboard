import os
import json
import time
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")

def scrape():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 2000} # 높이를 확 키워서 더 많이 보이게 함
        )

        page = context.new_page()
        
        try:
            print(f"🌐 타겟 진입: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(10000)

            # [수정] 모든 팝업 무시하고 리뷰 탭 강제 클릭 (엔터 키 활용)
            page.keyboard.press("Escape") 
            page.wait_for_timeout(2000)
            
            # 리뷰 페이지로 직접 강제 이동 (가장 확실함)
            rev_url = GOOGLE_MAPS_URL.split('?')[0].rstrip('/') + "/reviews/"
            page.goto(rev_url, wait_until="domcontentloaded")
            print("🚀 리뷰 직접 경로 진입 완료")
            page.wait_for_timeout(10000)

            collected = []
            processed_texts = set()

            for i in range(15):
                # [수정] 클래스고 뭐고 다 버리고 모든 span과 div에서 20자 이상 텍스트 추출
                # 구글 리뷰는 보통 한 문장 이상이므로 20자면 충분히 안전함
                elements = page.query_selector_all("span, div")
                found_this_turn = 0
                
                for el in elements:
                    try:
                        txt = el.inner_text().strip()
                        # 20자 이상이고, 중복 아니면 무조건 수집 (필터 완전 제거)
                        if len(txt) > 20 and txt not in processed_texts:
                            # 시스템 문구 몇 개만 제외
                            if "약관" in txt or "개인정보" in txt or "로그인" in txt: continue
                            
                            collected.append({
                                "store_name": "Paik's Noodle Amsterdam",
                                "store_url": GOOGLE_MAPS_URL,
                                "text": txt,
                                "rating": 5,
                                "date_raw": "Recent",
                                "collected_at": time.strftime("%Y-%m-%d")
                            })
                            processed_texts.add(txt)
                            found_this_turn += 1
                    except: continue
                
                print(f"🔄 {i+1}회차: {found_this_turn}건 확보 (총 {len(collected)}건)")
                
                # 스크롤 타겟팅 정밀화
                page.mouse.move(500, 500)
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(3000)

            # 저장 로직
            if len(collected) > 0:
                data_path = "public/data/reviews.json"
                all_data = []
                if os.path.exists(data_path):
                    with open(data_path, "r", encoding="utf-8") as f:
                        try: all_data = json.load(f)
                        except: all_data = []
                
                # 병합 (중복 체크 완화)
                existing_texts = {d.get('text') for d in all_data}
                new_entries = [c for c in collected if c['text'] not in existing_texts]
                all_data.extend(new_entries)
                
                os.makedirs("public/data", exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    json.dump(all_data, f, ensure_ascii=False, indent=4)
                
                print(f"✨ 최종 성공: 신규 {len(new_entries)}건 추가 (전체 {len(all_data)}건)")
            else:
                print("❌ 여전히 데이터를 찾지 못했습니다.")

        except Exception as e:
            print(f"❌ 오류: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
