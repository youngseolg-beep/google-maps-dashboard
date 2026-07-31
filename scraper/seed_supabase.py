import ast
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRAPER_PATH = ROOT / "scraper" / "scraper.py"
REVIEWS_PATH = ROOT / "public" / "data" / "reviews.json"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def normalize_spaces(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def require_config():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 환경변수가 없습니다.")


def supabase_request(method, table, *, query=None, body=None, prefer=None):
    require_config()
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if query:
        url += "?" + urlencode(query, safe=",.*()")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    req = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase 요청 실패 ({exc.code} {exc.reason}): {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase 연결 실패: {exc.reason}") from exc


def write_rows_adaptive(table, rows, *, query=None, prefer=None):
    """
    Write rows while automatically removing columns that do not exist
    in the current Supabase table schema (PGRST204).
    """
    if not rows:
        return

    working_rows = [dict(row) for row in rows]
    removed_columns = []

    while True:
        try:
            supabase_request(
                "POST",
                table,
                query=query,
                body=working_rows,
                prefer=prefer,
            )
            if removed_columns:
                print(
                    f"ℹ️ {table} 미사용 컬럼 자동 제외: "
                    + ", ".join(removed_columns)
                )
            return
        except RuntimeError as exc:
            message = str(exc)
            match = re.search(
                r"Could not find the '([^']+)' column of '[^']+' in the schema cache",
                message,
            )
            if not match:
                raise

            missing_column = match.group(1)
            if missing_column in removed_columns:
                raise

            removed_columns.append(missing_column)
            working_rows = [
                {key: value for key, value in row.items() if key != missing_column}
                for row in working_rows
            ]

            if not working_rows or not any(working_rows):
                raise RuntimeError(
                    f"{table}에 저장 가능한 컬럼이 남아 있지 않습니다."
                ) from exc


def load_stores_from_scraper():
    tree = ast.parse(SCRAPER_PATH.read_text(encoding="utf-8"), filename=str(SCRAPER_PATH))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "STORES":
                    stores = ast.literal_eval(node.value)
                    if not isinstance(stores, list):
                        raise RuntimeError("scraper.py의 STORES가 목록이 아닙니다.")
                    return stores
    raise RuntimeError("scraper.py에서 STORES 목록을 찾지 못했습니다.")


def make_review_key(review):
    store_name = normalize_spaces(review.get("store_name", ""))
    author = normalize_spaces(review.get("author", "Anonymous")) or "Anonymous"
    text = normalize_spaces(review.get("text", ""))
    date = normalize_spaces(review.get("date", "Unknown"))
    rating = normalize_spaces(review.get("rating", ""))
    return "||".join([store_name, author, text, date, rating])



def infer_brand(store_name):
    """Derive a non-null brand value from the existing store name."""
    name = normalize_spaces(store_name).casefold()

    rules = [
        ("paik's noodle", "Paik's Noodle"),
        ("paiks noodle", "Paik's Noodle"),
        ("bornga", "Bornga"),
        ("saemaeul", "Saemaeul"),
        ("paik's coffee", "Paik's Coffee"),
        ("paiks coffee", "Paik's Coffee"),
        ("paik's bibim", "Paik's Bibim"),
        ("paiks bibim", "Paik's Bibim"),
        ("hong kong banjum", "Hong Kong Banjum"),
        ("rolling pasta", "Rolling Pasta"),
        ("baek's beer", "Baek's Beer"),
        ("baeks beer", "Baek's Beer"),
    ]

    for token, brand in rules:
        if token in name:
            return brand

    # The DB requires a value. For an unknown name, use the first two words
    # rather than writing NULL and failing the whole migration.
    words = normalize_spaces(store_name).split()
    return " ".join(words[:2]) if words else "Unknown"


def seed_stores(stores):
    existing = supabase_request(
        "GET", "stores", query={"select": "id,store_name", "limit": "1000"}
    ) or []
    existing_names = {normalize_spaces(row.get("store_name")).casefold() for row in existing}

    rows = []
    for store in stores:
        name = normalize_spaces(store.get("store_name"))
        if not name or name.casefold() in existing_names:
            continue
        rows.append({
            "brand": infer_brand(name),
            "country": normalize_spaces(store.get("country")),
            "sv": normalize_spaces(store.get("sv")),
            "store_name": name,
            "google_maps_url": normalize_spaces(store.get("url")),
            "is_active": True,
        })
        existing_names.add(name.casefold())

    if rows:
        write_rows_adaptive("stores", rows, prefer="return=minimal")
    print(f"🏪 stores 저장 완료: 신규 {len(rows)}건")


def load_store_map():
    rows = supabase_request(
        "GET", "stores", query={"select": "id,store_name", "limit": "1000"}
    ) or []
    result = {
        normalize_spaces(row.get("store_name")).casefold(): row.get("id")
        for row in rows
        if row.get("id") and row.get("store_name")
    }
    if not result:
        raise RuntimeError("stores 테이블에서 매장 ID를 불러오지 못했습니다.")
    print(f"🔗 stores ID 확인 완료: {len(result)}건")
    return result


def prepare_review_row(review, store_map):
    store_name = normalize_spaces(review.get("store_name"))
    store_id = store_map.get(store_name.casefold())
    if not store_id:
        raise RuntimeError(f'매장 ID 매칭 실패: "{store_name}"')

    return {
        "review_key": hashlib.sha256(make_review_key(review).encode("utf-8")).hexdigest(),
        "store_id": store_id,
        "store_name": store_name,
        "sv": normalize_spaces(review.get("sv")),
        "country": normalize_spaces(review.get("country")),
        "city": normalize_spaces(review.get("city")),
        "author": normalize_spaces(review.get("author", "Anonymous")) or "Anonymous",
        "rating": review.get("rating"),
        "text": review.get("text", ""),
        "has_text": bool(review.get("has_text", normalize_spaces(review.get("text", "")))),
        "date": review.get("date", "Unknown"),
        "review_date": review.get("review_date"),
        "review_date_source": review.get("review_date_source", "estimated"),
        "collected_at": review.get("collected_at") or datetime.utcnow().strftime("%Y-%m-%d"),
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "source": "google_maps",
    }


def upload_reviews(rows, batch_size=500):
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        write_rows_adaptive(
            "reviews",
            batch,
            query={"on_conflict": "review_key"},
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print(f"📦 reviews 업로드: {min(start + len(batch), len(rows))}/{len(rows)}")


def main():
    print("🚀 크롤링 없이 Supabase 초기 이관 시작")
    stores = load_stores_from_scraper()
    reviews = json.loads(REVIEWS_PATH.read_text(encoding="utf-8"))
    if not isinstance(reviews, list):
        raise RuntimeError("reviews.json 형식이 목록이 아닙니다.")

    seed_stores(stores)
    store_map = load_store_map()
    rows = [prepare_review_row(review, store_map) for review in reviews if make_review_key(review)]
    upload_reviews(rows)
    print(f"✅ 초기 이관 완료: stores {len(stores)}개 / reviews {len(rows)}건")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"🔥 초기 이관 실패: {exc}")
        raise
