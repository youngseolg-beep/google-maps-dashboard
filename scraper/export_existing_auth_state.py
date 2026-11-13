"""Export Playwright storage state from the existing dedicated SVReviewMaster profile.

Sensitive output stays on the local machine. Never commit or share it.
"""
import base64
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PlaywrightError

PROFILE = Path(os.environ["LOCALAPPDATA"]) / "SVReviewMaster" / "GoogleMapsSortProfile"
OUTPUT = Path.home() / "google-maps-auth-state.b64"

def main():
    if not (PROFILE / "Default" / "Network" / "Cookies").exists():
        raise SystemExit("PROFILE_NOT_FOUND: dedicated profile cookies file missing")
    print("Close any browser windows using the SVReviewMaster dedicated profile before continuing.")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), headless=False, channel="chrome",
            args=["--profile-directory=Default"],
        )
        try:
            page = context.new_page()
            page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=60000)
            print("Check the opened Google Maps window: is the dedicated account signed in?")
            answer = input("Type YES only if the account is visibly signed in: ").strip()
            if answer.upper() != "YES":
                print("NOT_EXPORTED: login not confirmed")
                return
            if not context.browser or not context.browser.is_connected():
                raise SystemExit("BROWSER_DISCONNECTED: browser exited before state export; keep the opened window running")
            try:
                state = context.storage_state()
            except PlaywrightError as exc:
                raise SystemExit("EXPORT_FAILED: browser connection closed during export. Close other windows using this dedicated profile, then retry once.") from exc
            if not state.get("cookies"):
                raise SystemExit("NOT_EXPORTED: no cookies in browser state")
            encoded = base64.b64encode(json.dumps(state, ensure_ascii=False).encode()).decode()
            OUTPUT.write_text(encoded, encoding="ascii")
            try:
                os.chmod(OUTPUT, 0o600)
            except OSError:
                pass
            print("EXPORTED_LOCALLY: " + str(OUTPUT))
            print("SENSITIVE: do not paste, upload, or commit this file.")
            print("Cloud authentication is NOT yet verified.")
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass

if __name__ == "__main__":
    main()
