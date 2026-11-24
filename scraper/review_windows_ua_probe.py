"""Read-only comparison of contemporary Windows Chrome user-agent versions.

Use the same Playwright run_case diagnostic, Linux Actions network and fresh
profile. Vary only advertised Windows Chrome major and browser binary when
explicitly identified. Do not read or write Supabase or capture user data.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright
import review_browser_environment_probe as existing

OUTPUT = Path("review-windows-ua-comparison.json")
UA_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
)

CASES = [
    ("chrome157_matching_windows157", "chrome", 157),
    ("chromium159_windows158", None, 158),
    ("chromium159_matching_windows159", None, 159),
]


def main():
    if os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("Read-only diagnostic refuses Supabase credentials")
    rows = []
    with sync_playwright() as p:
        for name, channel, version in CASES:
            existing.USER_AGENT_OLD = UA_TEMPLATE.format(version=version)
            # Same native options, locale, viewport, timezone and scroll logic.
            row = existing.run_case(
                p, name, channel, existing.NATIVE_ARGS, True, False
            )
            rows.append(row)
    report = {
        "store": "Saemaeul Central Eastville",
        "purpose": "Windows Chrome UA version isolation",
        "database_writes": False,
        "user_local_chrome_not_directly_accessed": True,
        "results": rows,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = [{
        "name": r["name"], "status": r["status"],
        "unique": r["unique_reviews_seen"],
        "initial_cards": r.get("snapshots", [{}])[0].get("visible_cards"),
        "browser_major": r.get("actual_browser_major"),
        "advertised_major": r.get("snapshots", [{}])[0].get("browser_major_version"),
        "scroll_rounds": r["scroll_rounds"],
        "xhr_fetch": r["xhr_fetch_during_scroll"],
        "page_kind": r.get("snapshots", [{}])[0].get("page_kind"),
        "challenge": r.get("snapshots", [{}])[0].get("dialog_signals"),
    } for r in rows]
    print("REVIEW_WINDOWS_UA_VERDICT: " + json.dumps(compact, ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Windows UA version comparison (no DB)\n\n"
                    "| UA setting | Actual browser major | Cards | Unique observed | Outcome |\n"
                    "|---|---:|---:|---:|---|\n")
            for x in compact:
                f.write(
                    f"| {x['name']} | {x['browser_major']} | "
                    f"{x['initial_cards'] or 0} | {x['unique']} | {x['status']} |\n"
                )
            f.write("\nUser's personal Chrome session was not accessed.\n")


if __name__ == "__main__":
    main()
