"""
member_portal_gifts.py — a giver looks after their own recurring gift.

    GET  /my/gifts            (served by member_portal._serve_page)
    POST /my/gifts            action = amount | pause | resume | stop | card

Subsplash lets a giver change, pause or stop a recurring gift from the
app. Here a recurring gift is a Stripe subscription on the CHURCH'S OWN
connected account (giving_router: mode=subscription, metadata
source_type=gift + business_id). Nothing on our side stores it, so this
asks Stripe: the customers with the member's email on that account, then
their subscriptions, keeping only gifts to THIS church.

Who may touch a gift: the signed-in member (6-digit code), only gifts
whose Stripe customer carries the email on their record here, and only
gifts to this church. Every action re-reads that list and refuses a
subscription that isn't in it. The owner's preview reads and never
writes. A new card goes through Stripe's own page (a Billing Portal
session limited to the payment method and past receipts), so card
numbers never touch this server.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger("member_portal_gifts")

router = APIRouter(tags=["member-portal"])

ACTIONS = ("amount", "pause", "resume", "stop", "card")
SUB_RE = re.compile(r"^sub_[A-Za-z0-9]{6,64}$")
_EVERY = {("week", 1): "weekly", ("week", 2): "every 2 weeks", ("month", 1): "monthly"}

DONE = {"amount": "Your gift amount is changed. The next one uses it.",
        "pause": "Your gift is paused. Nothing more is taken until you resume it.",
        "resume": "Your gift is back on.",
        "stop": "Your recurring gift is stopped. Thank you for every gift you gave."}
ERRORS = {"error": "That didn't go through. Nothing was changed. Please try again.",
          "gone": "We couldn't find that gift. It may already be stopped.",
          "amount": "Please enter an amount between $1 and $25,000.",
          "confirm": "Tick the box to confirm you want to stop this gift.",
          "slow": "That's a lot of changes at once. Please wait a minute.",
          "preview": "This is a preview. Nothing is changed for the member."}


# ─── Stripe, on the church's own account ─────────────────────────────

async def _stripe(method: str, path: str, account: str, *,
                  data: Optional[Dict[str, Any]] = None,
                  params: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    from stripe_checkout_helpers import HTTP_TIMEOUT, STRIPE_API_BASE, _secret_key
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.request(method, f"{STRIPE_API_BASE}{path}", auth=(_secret_key(), ""),
                                    headers={"Stripe-Account": account}, data=data, params=params)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400:
        logger.warning(f"[my-gifts] stripe {method} {path} -> {resp.status_code}: {str(body)[:200]}")
    return resp.status_code, body if isinstance(body, dict) else {}


def _period_end(sub: Dict[str, Any]) -> Optional[int]:
    # Newer Stripe API versions keep the period on the item.
    items = (sub.get("items") or {}).get("data") or []
    return sub.get("current_period_end") or (items[0].get("current_period_end") if items else None)


def _shape(sub: Dict[str, Any]) -> Dict[str, Any]:
    items = (sub.get("items") or {}).get("data") or []
    first = items[0] if items else {}
    price = first.get("price") or {}
    rec = price.get("recurring") or {}
    md = sub.get("metadata") or {}
    fee = items[1] if len(items) > 1 else None
    return {
        "id": sub.get("id"),
        "customer": sub.get("customer"),
        "gift_cents": int(price.get("unit_amount") or 0) * int(first.get("quantity") or 1),
        "fee_cents": int(((fee or {}).get("price") or {}).get("unit_amount") or 0),
        "fund": md.get("fund") or "General",
        "every": _EVERY.get((rec.get("interval"), int(rec.get("interval_count") or 1)), "recurring"),
        "next_at": _period_end(sub),
        "paused": bool(sub.get("pause_collection")),
        "status": sub.get("status"),
        "_items": items,
    }


async def recurring_gifts(biz: Dict[str, Any], email: str) -> Optional[List[Dict[str, Any]]]:
    """This member's live recurring gifts to this church, or None when
    Stripe couldn't be read. [] when there are none (or no email)."""
    account = biz.get("stripe_account_id")
    email = (email or "").strip().lower()
    if not account or not email or "@" not in email:
        return []
    status, found = await _stripe("GET", "/customers", account, params={"email": email, "limit": 10})
    if status >= 400:
        return None
    out: List[Dict[str, Any]] = []
    for cust in found.get("data") or []:
        # Stripe matches email case-sensitively-ish; insist on an exact match.
        if (cust.get("email") or "").strip().lower() != email:
            continue
        status, subs = await _stripe("GET", "/subscriptions", account,
                                     params={"customer": cust.get("id"), "status": "all", "limit": 20})
        if status >= 400:
            return None
        for sub in subs.get("data") or []:
            md = sub.get("metadata") or {}
            if md.get("source_type") != "gift" or str(md.get("business_id")) != str(biz.get("id")):
                continue
            if sub.get("status") not in ("active", "trialing", "past_due", "paused"):
                continue
            out.append(_shape(sub))
    return out


async def _portal_config(biz: Dict[str, Any]) -> Optional[str]:
    """The church's Billing Portal configuration: update the card and see
    past receipts, nothing else (amount, pause and stop happen on our page,
    in the church's words). Made once and kept in settings.giving."""
    import sb_clients
    account = biz["stripe_account_id"]
    settings = dict(biz.get("settings") or {})
    giving = dict(settings.get("giving") or {}) if isinstance(settings.get("giving"), dict) else {}
    saved = giving.get("portal_config")
    if isinstance(saved, dict) and saved.get("account") == account and saved.get("id"):
        return saved["id"]
    status, cfg = await _stripe("POST", "/billing_portal/configurations", account, data={
        "features[payment_method_update][enabled]": "true",
        "features[invoice_history][enabled]": "true",
        "business_profile[headline]": f"{(biz.get('name') or 'Your church')[:60]}: your giving",
    })
    if status >= 400 or not cfg.get("id"):
        return None
    giving["portal_config"] = {"id": cfg["id"], "account": account}
    settings["giving"] = giving
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    return cfg["id"]


async def change(biz: Dict[str, Any], gift: Dict[str, Any], action: str,
                 amount_cents: int = 0, return_url: str = "") -> Tuple[bool, str]:
    """Do one action on a gift already proven to be this member's.
    (ok, code-or-url): for 'card', the url of Stripe's page."""
    from financial_policy import require_stripe_write
    account = biz["stripe_account_id"]
    try:
        require_stripe_write(account)
    except Exception:
        return False, "error"
    sid = gift["id"]
    if action == "pause":
        status, _ = await _stripe("POST", f"/subscriptions/{sid}", account,
                                  data={"pause_collection[behavior]": "void"})
    elif action == "resume":
        status, _ = await _stripe("POST", f"/subscriptions/{sid}", account,
                                  data={"pause_collection": ""})
    elif action == "stop":
        status, _ = await _stripe("DELETE", f"/subscriptions/{sid}", account)
    elif action == "amount":
        from giving_router import MAX_GIFT_CENTS, MIN_GIFT_CENTS, covered_fee_cents
        if not (MIN_GIFT_CENTS <= amount_cents <= MAX_GIFT_CENTS):
            return False, "amount"
        data: Dict[str, Any] = {"proration_behavior": "none"}
        lines = [(0, amount_cents)]
        if gift["fee_cents"] and len(gift["_items"]) > 1:
            lines.append((1, covered_fee_cents(amount_cents)))
        for i, cents in lines:
            item = gift["_items"][i]
            price = item.get("price") or {}
            rec = price.get("recurring") or {}
            data[f"items[{i}][id]"] = item.get("id")
            data[f"items[{i}][price_data][currency]"] = price.get("currency") or "usd"
            data[f"items[{i}][price_data][product]"] = price.get("product")
            data[f"items[{i}][price_data][unit_amount]"] = cents
            data[f"items[{i}][price_data][recurring][interval]"] = rec.get("interval") or "month"
            data[f"items[{i}][price_data][recurring][interval_count]"] = int(rec.get("interval_count") or 1)
        status, _ = await _stripe("POST", f"/subscriptions/{sid}", account, data=data)
    elif action == "card":
        cfg = await _portal_config(biz)
        if not cfg:
            return False, "error"
        status, session = await _stripe("POST", "/billing_portal/sessions", account, data={
            "customer": gift["customer"], "configuration": cfg, "return_url": return_url})
        if status < 400 and session.get("url"):
            return True, session["url"]
        return False, "error"
    else:
        return False, "error"
    return (status < 400), (action if status < 400 else "error")


# ─── the page ────────────────────────────────────────────────────────

def _flash(request: Request) -> str:
    from member_portal import _e
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def _day(ts: Optional[int]) -> str:
    if not ts:
        return ""
    d = datetime.fromtimestamp(int(ts), timezone.utc)
    return f"{d.strftime('%B')} {d.day}"


def render_gifts(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                 gifts: Optional[List[Dict[str, Any]]], give_url: str) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell, money
    from giving_router import fund_label
    if gifts is None:
        body = ('<p class="mp-err" role="alert">Your recurring gifts couldn\'t load just now. Nothing has changed. '
                'Please try again in a moment.</p>')
    elif not gifts:
        email = me.get("email") or ""
        body = ('<section class="mp-card"><p>You don\'t have a recurring gift'
                + (f' under <strong>{_e(email)}</strong>' if email else '') + '.</p>'
                + ('<p class="mp-muted">If you set one up with a different email, ask the church office '
                   'to put that email on your record.</p>')
                + (f'<a class="mp-go" href="{_e(give_url)}">{ui.icon("heart", 16)}Set up a gift</a>' if give_url else '')
                + '</section>')
    else:
        cards = []
        for g in gifts:
            total = g["gift_cents"] + g["fee_cents"]
            fee = (f' (including {money(g["fee_cents"] / 100)} you cover for the processing fee)'
                   if g["fee_cents"] else "")
            state = ("Paused. Nothing is taken until you resume it." if g["paused"]
                     else (f"Next gift {_e(_day(g['next_at']))}." if g["next_at"] else ""))
            if g["status"] == "past_due":
                state = "Your last gift didn't go through. Please update your card."
            sid = _e(g["id"])
            hidden = f'<input type="hidden" name="sub" value="{sid}">'
            toggle = ("resume", "Resume my gift") if g["paused"] else ("pause", "Pause my gift")
            cards.append(f"""
<section class="mp-card mp-form" aria-label="{_e(fund_label(g['fund']))} gift">
  <p class="mp-total">{money(total / 100)} <span class="mp-muted">{_e(g['every'])}</span></p>
  <p>To the {_e(fund_label(g['fund']))}{_e(fee)}.</p>
  <p class="mp-muted">{state}</p>
  <form method="post" action="/my/gifts">{hidden}<input type="hidden" name="action" value="amount">
    <label for="mp-amt-{sid}">Change the amount ($)</label>
    <input class="mp-input" id="mp-amt-{sid}" name="amount" type="number" inputmode="decimal" min="1" max="25000" step="0.01"
           value="{g['gift_cents'] / 100:.2f}" required>
    <button class="mp-go mp-go-2" type="submit">Save the new amount</button>
  </form>
  <form method="post" action="/my/gifts">{hidden}<input type="hidden" name="action" value="{toggle[0]}">
    <button class="mp-go mp-go-2" type="submit">{toggle[1]}</button></form>
  <form method="post" action="/my/gifts">{hidden}<input type="hidden" name="action" value="card">
    <button class="mp-go mp-go-2" type="submit">Update my card or bank</button></form>
  <details class="mb-each"><summary>Stop this gift</summary>
    <form method="post" action="/my/gifts">{hidden}<input type="hidden" name="action" value="stop">
      <label class="mp-check"><input type="checkbox" name="confirm" value="yes" required> Yes, stop my recurring gift</label>
      <button class="mp-go mp-go-2" type="submit">Stop it</button></form>
  </details>
</section>""")
        body = "".join(cards)
    return _shell(biz, site, "My recurring gifts", f"""
<a class="mb-back" href="/my/me">{ui.icon('back', 16)}Me</a>
<h1>My recurring gifts</h1>
<p class="mp-muted">Change, pause or stop a gift you give regularly to {_e(biz.get('name') or 'the church')}.</p>
{_flash(request)}
{body}""", tab="me", who=me)


# ─── POST /my/gifts ──────────────────────────────────────────────────

def _back(**q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse("/my/gifts" + (f"?{qs}" if qs else ""), status_code=303, headers=_SECURE_HEADERS)


@router.post("/my/gifts", include_in_schema=False)
async def gifts_action(request: Request):
    import asyncio
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return _back(err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back()
    form = await request.form()
    action = str(form.get("action") or "")
    sid = str(form.get("sub") or "")
    if action not in ACTIONS or not SUB_RE.match(sid):
        return _back(err="error")
    if action == "stop" and str(form.get("confirm") or "") != "yes":
        return _back(err="confirm")
    amount_cents = 0
    if action == "amount":
        try:
            amount_cents = int(round(float(str(form.get("amount") or "0")) * 100))
        except ValueError:
            return _back(err="amount")
    if not mpc._allowed(church, me):
        return _back(err="slow")
    biz = church["business"]
    full = await asyncio.to_thread(mpc.load_me, biz["id"], me["id"]) or me
    mine = await recurring_gifts(biz, full.get("email") or "")
    if mine is None:
        return _back(err="error")
    gift = next((g for g in mine if g["id"] == sid), None)
    if not gift:
        return _back(err="gone")
    # Behind the proxy the request says http://; Stripe sends the giver
    # back over https to the same host.
    host = request.url.hostname or ""
    local = host in ("localhost", "127.0.0.1")
    origin = (f"http://{host}:{request.url.port}" if local and request.url.port
              else f"{'http' if local else 'https'}://{host}")
    ok, out = await change(biz, gift, action, amount_cents, return_url=f"{origin}/my/gifts")
    if action == "card" and ok:
        from member_portal import _SECURE_HEADERS
        return RedirectResponse(out, status_code=303, headers=_SECURE_HEADERS)
    return _back(**({"done": out} if ok else {"err": out}))
