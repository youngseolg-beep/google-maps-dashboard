"""Offline-only health check of the existing dedicated Google Maps storage state.

No browser/network is launched. No account identifiers, cookies, tokens,
domains or secret values are printed, exported or persisted.
"""
import base64
import json
import os
import time
from pathlib import Path

OUTPUT=Path("review-auth-state-health.json")
# Known authentication cookie *names* are checked only within memory.
# No names or values are included in outputs.
AUTH_NAMES={
    "SID", "HSID", "SSID", "APISID", "SAPISID", "LSID",
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID",
    "__Secure-3PAPISID", "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC",
}


def main():
    encoded=os.getenv("GOOGLE_MAPS_STORAGE_STATE_B64","").strip()
    summary={
        "secret_present": bool(encoded),
        "state_format_valid": False,
        "google_cookie_count": 0,
        "nonexpired_google_cookies": 0,
        "expired_google_cookies": 0,
        "google_session_cookies": 0,
        "auth_named_google_cookies": 0,
        "unexpired_auth_named_google_cookies": 0,
        "auth_state_may_be_usable": False,
        "unexpired_persistent_auth_cookie_count": 0,
        "session_auth_cookie_count": 0,
        "min_persistent_auth_ttl_hours": None,
        "cloud_google_login_verified": False,
        "database_writes": False,
    }
    try:
        if encoded:
            state=json.loads(base64.b64decode(encoded,validate=True))
            cookies=state.get("cookies") if isinstance(state,dict) else None
            if not isinstance(cookies,list):
                raise ValueError("Invalid storage state")
            summary["state_format_valid"]=True
            now=time.time()
            auth_expiry_times=[]
            for c in cookies:
                if not isinstance(c,dict):
                    continue
                domain=str(c.get("domain","")).lower()
                if domain!="google.com" and not domain.endswith(".google.com"):
                    continue
                summary["google_cookie_count"] += 1
                exp=c.get("expires",-1)
                future=not isinstance(exp,(float,int)) or exp < 0 or exp > now
                if future:
                    summary["nonexpired_google_cookies"] += 1
                else:
                    summary["expired_google_cookies"] += 1
                if not isinstance(exp,(float,int)) or exp < 0:
                    summary["google_session_cookies"] += 1
                if c.get("name") in AUTH_NAMES:
                    summary["auth_named_google_cookies"] += 1
                    if future:
                        summary["unexpired_auth_named_google_cookies"] += 1
                        if isinstance(exp,(float,int)) and exp > now:
                            summary["unexpired_persistent_auth_cookie_count"] += 1
                            auth_expiry_times.append(exp)
                        elif isinstance(exp,(float,int)) and exp < 0:
                            summary["session_auth_cookie_count"] += 1
            if auth_expiry_times:
                summary["min_persistent_auth_ttl_hours"] = round((min(auth_expiry_times)-now)/3600,1)
            summary["auth_state_may_be_usable"] = (
                summary["unexpired_auth_named_google_cookies"] > 0
            )
    except Exception:
        summary["state_format_valid"]=False
        # Never print error text. It might contain secret material.

    OUTPUT.write_text(json.dumps(summary,sort_keys=True,indent=2),encoding="utf-8")
    print("AUTH_STORAGE_HEALTH_VERDICT: "+json.dumps(summary,sort_keys=True))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Dedicated account storage-state health (offline only)\n\n")
            f.write("| Check | Result |\n|---|---|\n")
            for key,value in summary.items():
                f.write("| "+key+" | "+str(value)+" |\n")
            f.write("\nAuth-like cookie names are only a heuristic, not proof of login.\n")


if __name__=="__main__":
    main()
