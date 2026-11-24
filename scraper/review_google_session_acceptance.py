"""Read-only Google account session acceptance check in the Actions browser.

Uses the existing dedicated Maps auth storage state. Opens the Google account
settings landing page as a GET-only browser navigation. Never clicks, changes
account settings, reads user identity, or writes cookies/reviews to artifacts.
Only boolean page state and URL *categories* are recorded.
"""
import base64
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
import scraper as production

DEST=Path("review-auth-acceptance-result.json")
URL="https://myaccount.google.com/"


def safe_state():
    raw=os.getenv("GOOGLE_MAPS_STORAGE_STATE_B64","").strip()
    if not raw:
        return None,"AUTH_SECRET_NOT_CONFIGURED"
    try:
        state=json.loads(base64.b64decode(raw,validate=True))
        if not isinstance(state,dict) or not isinstance(state.get("cookies"),list):
            return None,"AUTH_STATE_INVALID"
        return state,"AUTH_STATE_PARSED"
    except Exception:
        return None,"AUTH_STATE_INVALID"


def inspect(page):
    return page.evaluate("""() => {
        // Do not return any page text, account names, emails, URLs or tokens.
        const host=location.hostname.toLowerCase();
        const path=location.pathname.toLowerCase();
        const text=(document.body?.innerText || '').slice(0,15000).toLowerCase();
        const nodes=[...document.querySelectorAll('a,button')];
        const showLogin=nodes.some(e=>{
            const r=e.getBoundingClientRect();
            if(!r.width||!r.height) return false;
            const name=(e.getAttribute('aria-label')||'')+' '+(e.innerText||'').slice(0,80);
            return /^(sign in|log in|로그인|เข้าสู่ระบบ)/i.test(name.trim());
        });
        return {
            destination: host === 'myaccount.google.com' ? 'myaccount'
                : host === 'accounts.google.com' ? 'accounts'
                : host.endsWith('.google.com') ? 'other_google' : 'other',
            signin_path: /signin|servicelogin|identifier|challenge/i.test(path),
            login_button_visible: showLogin,
            account_security_challenge_visible:
                /verify it.s you|verify your identity|confirm it.s you|본인 확인|本人確認/i.test(text),
            account_page_visible: host === 'myaccount.google.com'
                && !!document.querySelector('main, [role="main"]'),
        };
    }""")


def run(browser,name,state):
    opts={"locale":"en-US","viewport":{"width":1365,"height":900}}
    ctx=production.new_crawler_context(browser, auth_state=state) if state else browser.new_context(**opts)
    result={"arm":name,"status":"STARTED"}
    try:
        # Direct Maps first; a redirect to Google Account sign-in must not
        # contaminate our separate Maps login-UI diagnostic.
        maps=ctx.new_page()
        nav=maps.goto("https://www.google.com/maps",wait_until="domcontentloaded",timeout=45000)
        result["maps_nav_http_code"]=nav.status if nav else None
        maps.wait_for_timeout(2200)
        result["maps_account_ui_early"]=production.verify_dedicated_google_login(maps)
        maps.wait_for_timeout(5800)
        result["maps_account_ui_late"]=production.verify_dedicated_google_login(maps)
        result["maps_account_ui"]=result["maps_account_ui_late"]
        result["maps_signin_control_visible"]=maps.evaluate("""() => {
            const visible=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0};
            return [...document.querySelectorAll('a,button')].filter(visible).some(el=>
                /^(sign in|log in|로그인)$/i.test(
                    ((el.getAttribute('aria-label')||'')+' '+(el.innerText||'')).trim()
                ));
        }""")
        result["maps_shell_present"]=maps.locator("#pane, #scene, #searchboxinput").count()>0
        result["maps_dom_state"]=maps.evaluate("""() => ({
            maps_path: location.hostname.endsWith('google.com') &&
                location.pathname.startsWith('/maps'),
            google_signin_path: location.hostname === 'accounts.google.com' &&
                /signin|challenge|identifier/i.test(location.pathname),
            document_ready_state: document.readyState,
            body_exists: !!document.body,
            body_text_bucket: !document.body ? 'missing' :
                document.body.innerText.length > 1000 ? 'long' :
                document.body.innerText.length > 100 ? 'medium' : 'short',
            button_count: Math.min(300, document.querySelectorAll('button').length),
            link_count: Math.min(300, document.querySelectorAll('a').length),
            script_count: Math.min(300, document.querySelectorAll('script').length)
        })""")
        result["maps_page_indicators"]=maps.evaluate("""() => {
            const body=(document.body?.innerText || '').toLowerCase();
            const has=words=>words.some(word=>body.includes(word));
            return {
                consent_page_words: has(['before you continue', 'accept all', 'reject all',
                                         'manage options', '쿠키 사용', '모두 수락']),
                explicit_signin_words: has(['sign in to google', 'sign in to maps',
                                           '로그인하여', '로그인이 필요']),
                access_error_words: has(['unusual traffic', 'something went wrong',
                                         'try again later', 'too many requests',
                                         'access denied', '페이지를 표시할 수 없습니다']),
                map_search_ui: !!document.querySelector(
                    'input[aria-label*="Search"], input[aria-label*="검색"], #searchboxinput'),
                place_title_ui: !!document.querySelector('h1.DUwDvf, [role="heading"]'),
                visible_dialogs: Math.min(10,
                    [...document.querySelectorAll('[role="dialog"]')].filter(el=>{
                        const r=el.getBoundingClientRect();
                        return r.width>0&&r.height>0;
                    }).length),
                top_level_iframes: Math.min(20, document.querySelectorAll('iframe').length)
            };
        }""")
        maps.close()
        # A new tab is used for the account-page check.
        account=ctx.new_page()
        account.goto(URL,wait_until="domcontentloaded",timeout=45000)
        account.wait_for_timeout(4200)
        result["signals"]=inspect(account)
        account.close()
        result["status"]="COMPLETE"
    except Exception as exc:
        result["status"]="ERROR"
        result["error_type"]=type(exc).__name__
    finally:
        ctx.close()
    return result

def main():
    if os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("READ_ONLY_PROBE_REFUSES_DB_CREDENTIALS")
    state,status=safe_state()
    # Normalize cross-version Chrome cookie attributes before using Chromium.
    if state is not None:
        try:
            state=production.load_dedicated_google_auth_state()
        except Exception:
            state=None
            status="STORAGE_STATE_NORMALIZATION_FAILED"
    result={"preflight":status,"database_writes":False,
            "account_data_saved":False,"runs":[]}
    if state is not None:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=[
                "--no-sandbox","--disable-dev-shm-usage"
            ])
            try:
                result["runs"].append(run(browser,"anonymous",None))
                result["runs"].append(run(browser,"existing_dedicated_auth",state))
            finally:
                browser.close()
    DEST.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    print("GOOGLE_SESSION_ACCEPTANCE_VERDICT: "+json.dumps(result,sort_keys=True))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Google dedicated account state acceptance (read-only)\n\n")
            f.write("Preflight: "+status+"\n\n")
            f.write("| Browser state | Destination category | Login visible | Security challenge |\n")
            f.write("|---|---|---|---|\n")
            for x in result["runs"]:
                v=x.get("signals",{})
                f.write("| "+x["arm"]+" | "+str(v.get("destination","N/A"))
                    +" | "+str(v.get("login_button_visible","N/A"))
                    +" | "+str(v.get("account_security_challenge_visible","N/A"))+" |\n")
            f.write("\nURL category and UI signals are heuristic, not a formal login proof.\n")


if __name__=="__main__":
    main()
