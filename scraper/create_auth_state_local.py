"""Create a Playwright storage-state secret locally after interactive Google sign-in.

Run on your own PC, never in CI. The output grants access to the signed-in
Google account; do not commit, upload as artifact, or paste into chat.
"""
import base64
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path.home() / "google-maps-auth-state.b64"
MAPS = "https://www.google.com/maps"

def main():
    if OUT.exists():
        raise SystemExit(f"Refusing to overwrite existing secret file: {OUT}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            context = browser.new_context(locale="en-US")
            page = context.new_page()
            page.goto(MAPS, wait_until="domcontentloaded")
            input("Sign in to the dedicated Google account in the browser, verify Maps is signed in, then press Enter here: ")
            state = context.storage_state()
            if not state.get("cookies"):
                raise RuntimeError("No cookies were captured; sign-in cannot be confirmed")
            encoded = base64.b64encode(json.dumps(state).encode("utf-8")).decode("ascii")
            with OUT.open("x", encoding="ascii") as file:
                file.write(encoded)
            if os.name != "nt":
                OUT.chmod(0o600)
            print(f"Saved sensitive auth state to {OUT}. Add file contents to GitHub Actions secret GOOGLE_MAPS_STORAGE_STATE_B64; never commit this file.")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
