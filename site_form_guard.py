"""site_form_guard.py: the bot checks on a website's forms (M-5, 2026-11-27).

Mission M-5 step 1 (the inbound-safety fixes Kevin said yes to): the public
form door, `POST /sites/{id}/contact-submit`, carries every church's connect
card and prayer request. Until now it had a per-replica 5-a-minute dict and
nothing else on the server: the hidden "website" field on Love City's forms
was checked only in the visitor's browser, so a script posting straight to
the door was never stopped.

Three checks, all before anything is read, stored, alerted or mailed:

  the limiter   `rate_limit.allow_strict("site_contact", ip)`: shared across
                replicas (public_site._check_contact_rate).
  the honeypot  a hidden field only a bot fills in (`website`, `_hp`,
                `sol-hp`). No form sends these as real answers.
  the token     `_t`, signed when the page was served: the script `inject()`
                adds to every public site page puts it on each contact-submit
                POST, including pages whose form scripts were frozen when
                they were built. A token that isn't ours, or that came back
                less than MIN_SECONDS after the page was made, is a bot.

A bot is told what a person is told ({"ok": true}) and nothing is kept: a
script learns nothing, and a person is never shown an error by mistake.

What never stops a person:
  - no token (a page cached before this shipped, an embed, a preview, a tab
    left open longer than MAX_AGE): allowed, and counted in the log line, so
    "missing" can become a Needs-a-look signal once the log shows every real
    card carries one;
  - no secret configured, or SITE_FORM_GUARD=off: no token is minted and
    none is checked.

The words a person wrote are never logged here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

MIN_SECONDS = 3                     # faster than a person can fill a form
MAX_AGE = 7 * 24 * 3600             # older than this: treated as no token
FUTURE_SLACK = 120                  # replicas' clocks may differ a little
HONEYPOTS = ("website", "_hp", "sol-hp")
TOKEN_KEY = "_t"
VERSION = "v1"
SCRIPT_MARK = "__solFormGuard"


def on() -> bool:
    return (os.environ.get("SITE_FORM_GUARD") or "on").strip().lower() != "off"


def _secret() -> bytes:
    raw = (os.environ.get("SITE_FORM_SECRET") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not raw:
        return b""
    # Derived, so the service key itself never signs anything a visitor sees.
    return hashlib.sha256(b"site-form-token|" + raw.encode()).digest()


def _sig(key: bytes, business_id: str, ts: int) -> str:
    return hmac.new(key, f"{VERSION}|{business_id}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]


def token(business_id: Any, now: Optional[float] = None) -> str:
    """A token for this business's page, made now. "" when off or unsigned."""
    key = _secret()
    biz = str(business_id or "").strip()
    if not on() or not key or not biz:
        return ""
    ts = int(now if now is not None else time.time())
    return f"{VERSION}.{ts}.{_sig(key, biz, ts)}"


def token_says(business_id: Any, tok: Any, now: Optional[float] = None) -> str:
    """'' (a good token), 'missing' (none, stale, or nothing to check it
    with), 'bad' (not ours, or another business's) or 'too_fast'."""
    key = _secret()
    if not on() or not key:
        return "missing"
    if tok is None or tok == "":
        return "missing"
    if not isinstance(tok, str) or len(tok) > 80:
        return "bad"
    parts = tok.split(".")
    if len(parts) != 3 or parts[0] != VERSION or not parts[1].isdigit():
        return "bad"
    ts = int(parts[1])
    if not hmac.compare_digest(parts[2], _sig(key, str(business_id or "").strip(), ts)):
        return "bad"
    age = (now if now is not None else time.time()) - ts
    if age < -FUTURE_SLACK:
        return "bad"
    if age > MAX_AGE:
        return "missing"
    if age < MIN_SECONDS:
        return "too_fast"
    return ""


def honeypot_filled(body: Dict[str, Any]) -> bool:
    for k in HONEYPOTS:
        v = body.get(k)
        if v is not None and v is not False and str(v).strip():
            return True
    return False


def verdict(business_id: Any, body: Any, now: Optional[float] = None) -> str:
    """'' for a person (or someone we can't tell), else why it's a bot:
    'honeypot', 'bad_token' or 'too_fast'. Never raises."""
    try:
        if not on() or not isinstance(body, dict):
            return ""
        if honeypot_filled(body):
            return "honeypot"
        says = token_says(business_id, body.get(TOKEN_KEY), now)
        return {"bad": "bad_token", "too_fast": "too_fast"}.get(says, "")
    except Exception:  # noqa: BLE001: a check that breaks never stops a person
        return ""


def script(business_id: Any) -> str:
    """The page's script: adds the token to each JSON POST it sends to
    /contact-submit. It touches nothing else and never sends anything
    itself: any error and the page's own fetch runs exactly as written."""
    tok = token(business_id)
    if not tok:
        return ""
    return ("<script>(function(){try{if(window." + SCRIPT_MARK + "||!window.fetch)return;window."
            + SCRIPT_MARK + "=1;var T=" + json.dumps(tok) + ",F=window.fetch;"
            "window.fetch=function(u,o){try{var s=typeof u==='string'?u:(u&&u.url)||'';"
            "if(s.indexOf('/contact-submit')>-1&&o&&typeof o.body==='string'){var b=JSON.parse(o.body);"
            "if(b&&typeof b==='object'&&!Array.isArray(b)&&!b._t){b._t=T;"
            "return F.call(this,u,Object.assign({},o,{body:JSON.stringify(b)}));}}}catch(e){}"
            "return F.apply(this,arguments);};}catch(e){}})();</script>")


def inject(html: str, business_id: Any) -> str:
    """The script before </body>, once. Never raises, never blocks a page."""
    if not html or not business_id or SCRIPT_MARK in html:
        return html
    try:
        tag = script(business_id)
    except Exception:  # noqa: BLE001
        return html
    if not tag:
        return html
    for close in ("</body>", "</BODY>"):
        if close in html:
            return html.replace(close, tag + "\n" + close, 1)
    return html + tag
