"""
giving_ways.py: the ways a church's people give (Kevin, 2026-11-01).

The ways
  The church keeps one list of the apps its people give through (Cash App,
  Zelle, Venmo, PayPal, Subsplash, or another app by name), with each
  one's handle. That list is used in two places:
    - the treasurer's "how it was given" menu: Cash, Check, then each way,
      then Other;
    - "Other ways to give" on the give page and in the member app, for each
      way with a handle that the church chose to show.
  Stripe can't take Cash App, Zelle, Venmo or PayPal gifts for a church: a
  religious organization is a category Cash App Pay refuses, PayPal on
  Stripe is Europe-only, and Venmo and Zelle aren't on Stripe. So these
  gifts go straight to the church's own account. The system sees them only
  as a deposit at the bank (giving_deposits recognizes them there), and the
  treasurer records who gave.

The method each way records as
  A way's token is the gift's payment_method, and that word is
  load-bearing:
    - gl_engine books a gift by it (_NON_STRIPE_PAYMENT_HINTS: never the
      Stripe clearing account);
    - giving_deposits.gift_kind matches the deposit by it:
        - Cash App, Zelle, Venmo and PayPal are "transfer";
        - Subsplash is "subsplash bank payout" (a payout less fees);
        - another app by name is "other", with its name in the gift's note.

Card or bank, never pay-later
  A gift checkout used to offer whatever the platform's default payment
  set showed, which included Klarna (pay later or finance a tithe).
  Where this is switched on, a gift checkout filters Stripe's choices with
  allowed_payment_method_types:
    - card: card (Apple Pay and Google Pay ride on card) and Link;
    - bank: us_bank_account.
  A bank payment needs the platform's giving payment set
  (STRIPE_GIVING_PMC, a Connect parent configuration with ACH on), since the
  default set has bank payments off for every business. "Cover the fee" is
  worked out for the way the giver chose.

Switched by GIVING_SERVICES, the same switch as the service counts
(off / owner / on; owner = the platform church).
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("giving_ways")

SWITCH = "GIVING_SERVICES"


def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── The apps ─────────────────────────────────────────────────────────
# key → label, the gift's payment_method token, and what its handle is.
APPS: Dict[str, Dict[str, Any]] = {
    "cashapp": {"label": "Cash App", "token": "cashapp", "handle": "cashtag"},
    "zelle": {"label": "Zelle", "token": "zelle", "handle": "email_or_phone"},
    "venmo": {"label": "Venmo", "token": "venmo", "handle": "venmo"},
    "paypal": {"label": "PayPal", "token": "paypal", "handle": "paypal"},
    "subsplash": {"label": "Subsplash", "token": "subsplash bank payout", "handle": None},
    "other": {"label": "Other app", "token": "other", "handle": "text"},
}
MAX_WAYS = 8
MAX_OTHERS = 3
MAX_LABEL = 40
MAX_TEXT = 120

# What the treasurer can always choose, before and after the church's ways.
BASE_METHODS = [{"id": "cash", "label": "Cash"}, {"id": "check", "label": "Check"}]
TAIL_METHODS = [{"id": "bank_transfer", "label": "Bank transfer"}, {"id": "other", "label": "Other"}]
ALLOWED_TOKENS = {"cash", "check", "bank_transfer", "other"} | {a["token"] for a in APPS.values()}

_CASHTAG = re.compile(r"^\$[A-Za-z][A-Za-z0-9_]{0,19}$")
_VENMO = re.compile(r"^[A-Za-z0-9_-]{5,30}$")
_PAYPAL = re.compile(r"^[A-Za-z0-9]{1,20}$")
_EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
_LINK = re.compile(r"^https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~%!$&'()*+,;=:@/?#-]*)?$")


class WayError(ValueError):
    """A way the church entered that can't be used, in words for the church."""


def _one_line(raw: Any, limit: int) -> str:
    return " ".join(str(raw or "").split())[:limit + 1]


def _clean_handle(app: str, raw: Any) -> str:
    kind = APPS[app]["handle"]
    text = _one_line(raw, 200).strip()
    if not text:
        return ""
    if kind == "cashtag":
        tag = text if text.startswith("$") else "$" + text
        if not _CASHTAG.match(tag):
            raise WayError("A $cashtag is a $ then up to 20 letters or numbers, starting with a letter.")
        return tag
    if kind == "venmo":
        name = text.lstrip("@")
        if not _VENMO.match(name):
            raise WayError("A Venmo username is 5 to 30 letters, numbers, dashes or underscores.")
        return "@" + name
    if kind == "paypal":
        name = re.sub(r"^(https?://)?(www\.)?paypal\.me/", "", text, flags=re.I).strip("/")
        if not _PAYPAL.match(name):
            raise WayError("A PayPal.Me name is up to 20 letters or numbers (paypal.me/yourname).")
        return name
    if kind == "email_or_phone":
        if "@" in text:
            if not _EMAIL.match(text):
                raise WayError("That Zelle email doesn't look right.")
            return text.lower()
        digits = re.sub(r"\D", "", text)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            raise WayError("Enter the Zelle email, or a 10-digit US phone number.")
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if kind == "text":
        if len(text) > MAX_TEXT:
            raise WayError(f"Keep the details to {MAX_TEXT} characters.")
        return text
    return ""


def clean_ways(raw: Any) -> List[Dict[str, Any]]:
    """The church's list, checked. Raises WayError in words for the church."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WayError("The ways to give must be a list.")
    out: List[Dict[str, Any]] = []
    seen: set = set()
    others = 0
    for item in raw:
        if not isinstance(item, dict):
            raise WayError("Each way to give needs an app.")
        app = str(item.get("app") or "").strip().lower()
        if app not in APPS:
            raise WayError("Choose Cash App, Zelle, Venmo, PayPal, Subsplash or another app.")
        way: Dict[str, Any] = {"app": app}
        if app == "other":
            label = _one_line(item.get("label"), MAX_LABEL).strip()
            if not label:
                raise WayError("Name the other app (for example Givelify).")
            if len(label) > MAX_LABEL:
                raise WayError(f"Keep the app's name to {MAX_LABEL} characters.")
            key = "other:" + label.lower()
            others += 1
            if others > MAX_OTHERS:
                raise WayError(f"Add up to {MAX_OTHERS} other apps.")
            way["label"] = label
            link = str(item.get("link") or "").strip()
            if link:
                if len(link) > 200 or not _LINK.match(link):
                    raise WayError("The other app's link must be a full https:// address.")
                way["link"] = link
        else:
            key = app
        if key in seen:
            raise WayError(f"{label_of(way)} is on the list twice.")
        seen.add(key)
        handle = _clean_handle(app, item.get("handle")) if APPS[app]["handle"] else ""
        if handle:
            way["handle"] = handle
        show = item.get("show") is True
        if show and not (handle or way.get("link")):
            raise WayError(f"Add the {label_of(way)} details to show it on the give page.")
        way["show"] = show
        out.append(way)
    if len(out) > MAX_WAYS:
        raise WayError(f"Add up to {MAX_WAYS} ways to give.")
    return out


def stored_ways(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The saved list, re-checked on the way out: a row the checks would
    refuse today is left out rather than shown."""
    raw = (cfg or {}).get("ways")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        try:
            out.extend(clean_ways([item]))
        except WayError:
            continue
    return out[:MAX_WAYS]


def label_of(way: Dict[str, Any]) -> str:
    if way.get("app") == "other":
        return str(way.get("label") or "Other app")
    return APPS.get(str(way.get("app")), {}).get("label", "Other")


# ─── The treasurer's menu ─────────────────────────────────────────────

def method_menu(ways: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Cash, Check, the church's ways, Bank transfer, Other. An app named
    under Other is its own entry (id other:<name>)."""
    out = list(BASE_METHODS)
    for w in ways:
        if w["app"] == "other":
            out.append({"id": f"other:{w['label']}", "label": w["label"]})
        else:
            out.append({"id": APPS[w["app"]]["token"], "label": label_of(w)})
    return out + TAIL_METHODS


def parse_method(raw: Any) -> Tuple[str, Optional[str]]:
    """A menu id → (the gift's payment_method token, the app's name for an
    app named under Other, else None). Raises WayError."""
    text = str(raw or "").strip()
    if text.lower().startswith("other:"):
        name = _one_line(text[6:], MAX_LABEL).strip()
        if not name or len(name) > MAX_LABEL:
            raise WayError("Name the app the gift came through.")
        return "other", name
    if text in ALLOWED_TOKENS:
        return text, None
    raise WayError("Choose how the gift was given.")


def method_label(token: Any) -> str:
    t = str(token or "").strip().lower()
    for m in BASE_METHODS + TAIL_METHODS:
        if m["id"] == t:
            return m["label"]
    for a in APPS.values():
        if a["token"] == t:
            return a["label"]
    if t == "stripe":
        return "Online"
    return t.title() if t else "Other"


# ─── Links for the give page ──────────────────────────────────────────

def link_for(way: Dict[str, Any]) -> Optional[Tuple[str, bool]]:
    """(link, takes an amount) for a way that has one, else None.
    Cash App and PayPal.Me take the amount as a last path part."""
    app, handle = way.get("app"), str(way.get("handle") or "")
    if app == "cashapp" and handle:
        return f"https://cash.app/{handle}", True
    if app == "paypal" and handle:
        return f"https://paypal.me/{handle}", True
    if app == "venmo" and handle:
        return f"https://venmo.com/u/{handle.lstrip('@')}", False
    if app == "other" and way.get("link"):
        return str(way["link"]), False
    return None


def give_page_ways(ways: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The ways the church chose to show, in its order."""
    return [w for w in ways if w.get("show") and (w.get("handle") or w.get("link"))]


def ways_html(ways: List[Dict[str, Any]]) -> str:
    """"Other ways to give" for the give page. Empty when none are shown."""
    from html import escape
    shown = give_page_ways(ways)
    if not shown:
        return ""
    rows: List[str] = []
    for w in shown:
        name = escape(label_of(w))
        handle = escape(str(w.get("handle") or ""))
        link = link_for(w)
        detail = f'<span class="gv-way-handle">{handle}</span>' if handle else ""
        if link:
            href, amt = link
            rows.append(
                f'<a class="gv-way" href="{escape(href)}" data-way-base="{escape(href)}"'
                f'{" data-way-amt" if amt else ""} target="_blank" rel="noopener">'
                f'<span class="gv-way-name">{name}</span>{detail}</a>')
        else:
            rows.append(
                f'<div class="gv-way"><span class="gv-way-name">{name}</span>{detail}'
                f'<button type="button" class="gv-copy" data-copy="{handle}">Copy</button></div>')
    return ('<section class="gv-ways" aria-labelledby="gv-ways-h">'
            '<h2 class="gv-ways-h" id="gv-ways-h">Other ways to give</h2>'
            + "".join(rows) +
            '<p class="gv-note">Gifts sent these ways go straight to the church, '
            'and the church office records them.</p></section>')


WAYS_CSS = """
.gv-ways{margin-top:22px;}
.gv-ways-h{font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin:0 0 8px;
  color:var(--gv-muted,var(--text-muted));}
.gv-way{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 14px;margin-bottom:8px;
  border:1.5px solid var(--gv-line,var(--border));border-radius:var(--gv-radius,12px);min-height:48px;
  color:inherit;text-decoration:none;font-size:15px;}
.gv-way-name{font-weight:700;}
.gv-way-handle{color:var(--gv-muted,var(--text-secondary));overflow-wrap:anywhere;}
.gv-copy{margin-left:auto;padding:8px 12px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;min-height:36px;
  border:1px solid var(--gv-line,var(--border));border-radius:8px;background:transparent;color:inherit;}
.gv-paywith{display:grid;grid-template-columns:1fr 1fr;border:1.5px solid var(--gv-line,var(--border));
  border-radius:var(--gv-radius,12px);overflow:hidden;margin-top:4px;}
.gv-paywith button{padding:12px 6px;font:inherit;font-size:14px;font-weight:600;border:0;background:transparent;
  color:var(--gv-muted,var(--text-secondary));cursor:pointer;min-height:48px;}
.gv-paywith button.on{background:var(--gv-accent,var(--accent));color:var(--gv-on-accent,#fff);}
"""


# ─── Card or bank ─────────────────────────────────────────────────────

PAY_WITH = ("card", "bank")
CARD_ALLOWED = ("card", "link")         # Apple Pay and Google Pay ride on card
BANK_ALLOWED = ("us_bank_account",)
BANK_FEE_PERCENT = 0.008
BANK_FEE_CAP_CENTS = 500
_PMC = re.compile(r"^pmc_[A-Za-z0-9]{8,64}$")


def giving_config_id() -> Optional[str]:
    """The platform's giving payment set (a Connect parent configuration),
    when it's been made and named in STRIPE_GIVING_PMC."""
    raw = (os.environ.get("STRIPE_GIVING_PMC") or "").strip()
    return raw if _PMC.match(raw) else None


def bank_ready(business: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """A giver can choose bank here: switched on, the giving set exists, and
    the church turned bank payments on (checked with Stripe when it did)."""
    return bool(cfg.get("bank_payments") is True and giving_config_id()
                and switched_on(business.get("id")))


def fee_cents(amount_cents: int, pay_with: str = "card") -> int:
    """What to add so the church nets amount_cents after the fee for the way
    the giver pays. Card: 2.9% + 30¢. Bank: 0.8%, at most $5."""
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        return 0
    if pay_with == "bank":
        gross = math.ceil(amount_cents / (1 - BANK_FEE_PERCENT))
        return min(gross - amount_cents, BANK_FEE_CAP_CENTS)
    gross = math.ceil((amount_cents + 30) / (1 - 0.029))
    return gross - amount_cents


def checkout_extras(pay_with: str) -> Dict[str, str]:
    """The form fields that hold a gift checkout to card-or-bank."""
    allowed = BANK_ALLOWED if pay_with == "bank" else CARD_ALLOWED
    out = {f"allowed_payment_method_types[{i}]": t for i, t in enumerate(allowed)}
    pmc = giving_config_id()
    if pmc:
        out["payment_method_configuration"] = pmc
    return out


def bank_available(stripe_account_id: str) -> Optional[bool]:
    """Whether the church's copy of the giving set can take bank payments
    (its ACH capability is active and the set has it on). None when Stripe
    couldn't be asked."""
    pmc = giving_config_id()
    if not pmc or not re.fullmatch(r"acct_[A-Za-z0-9]+", str(stripe_account_id or "")):
        return False
    try:
        import httpx
        from stripe_checkout_helpers import STRIPE_API_BASE, _secret_key
        resp = httpx.get(f"{STRIPE_API_BASE}/payment_method_configurations",
                         params={"limit": 50}, auth=(_secret_key(), ""),
                         headers={"Stripe-Account": stripe_account_id}, timeout=15.0)
        if resp.status_code >= 400:
            logger.warning(f"[giving_ways] config read failed: {resp.status_code} {resp.text[:200]}")
            return None
        for c in (resp.json() or {}).get("data") or []:
            if c.get("parent") == pmc or c.get("id") == pmc:
                return bool(((c.get("us_bank_account") or {}).get("available")))
        return False
    except Exception as e:
        logger.warning(f"[giving_ways] config read failed: {e}")
        return None
