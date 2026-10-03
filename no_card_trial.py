"""
no_card_trial.py — the trial starts without a card (2026-10-03).

Kevin: "build the no card 500 credit version". Until now a brand-new
business met the paywall the moment onboarding finished: /billing/access
answered locked/no_subscription, and the only way past it was Stripe
Checkout with a card. The card was not what capped the cost — the trial
tank was (pricing_config.trial_credits, a hard ceiling while
BILLING_ENFORCE is on) — so it was friction without protection.

THE SHAPE
  · Business creation starts a trial with no Stripe subscription behind
    it — the row shape Platform Chief's extend_trial already writes:
    subscription_status=trialing, trial_ends_at, the plan's price id. So
    access_state, the trial emails, trial_expiry (which ends it on the
    calendar) and every report already understand it.
  · The tank is smaller: pricing_config.trial_credits_no_card() (500).
  · The first site build stays free (trial_build_free) — it is the pitch,
    and a real build is charged 1,000-1,300 credits, so 500 could never
    pay for one — but it is EARNED (Kevin, 2026-10-03: "this is my own
    money"): a verified phone first, within a platform-wide daily ceiling,
    and without the offer page (a whole extra builder pass). check_build.
  · The site is a preview until a card: its public address shows "coming
    soon" (site_hidden). AI site builders generate free and charge to
    publish; that is the category norm this follows.
  · Adding a card is the existing Checkout. stripe_billing keeps the SAME
    trial end (checkout_trial), so the card unlocks the rest of the full
    tank (trial_credits(), 1,000), puts the site live, and nothing is
    charged before the date the practitioner was already given.
  · Until a card is on file: no texts, no phone numbers, no bulk email
    (billing_limits.require_card) and no second site build — the things
    that cost real money or put the shared sending reputation at risk.

WHO GETS ONE — once per person: never a business that has had any
subscription or trial, never if the owner has had one on another
business, never grandfathered or comped accounts (they never lock
anyway), and only while BILLING_ENFORCE is on (with it off nothing
locks, and a trial clock would only mislead).

Marker: businesses.settings.no_card_trial = {started_at, plan, credits,
source, phone_hash?, phone_verified_at?}.
It stays after a card is added: "no card" means the marker AND no
stripe_subscription_id, so the Stripe webhook ends the no-card state by
itself, with nothing to clean up.

Kill switch: PRICE_NO_CARD_TRIAL=0. New signups then meet the card
paywall exactly as before; trials already running are untouched.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import sb_clients
import pricing_config
import feature_gates

logger = logging.getLogger("no_card_trial")

MARKER = "no_card_trial"

# Stripe Checkout refuses a subscription_data.trial_end less than 48
# hours away. An hour of margin covers the time between minting the
# session and the customer finishing it.
_CHECKOUT_MIN_TRIAL = timedelta(hours=49)


def _trial_days() -> int:
    try:
        return max(0, int(os.environ.get("BILLING_TRIAL_DAYS") or "7"))
    except ValueError:
        return 7


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def marker(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    m = ((row or {}).get("settings") or {}).get(MARKER)
    return m if isinstance(m, dict) else None


def is_no_card(row: Optional[Dict[str, Any]]) -> bool:
    """On a trial that started without a card and still has none.

    Only the marker plus the absence of a Stripe subscription: a card
    added through Checkout writes stripe_subscription_id, and that alone
    ends the no-card state. The status is deliberately NOT tested — a
    no-card trial that ran out (canceled by trial_expiry) is still a
    business that has never given a card, and the copy it sees and the
    checkout it gets both depend on knowing that.

    A row read WITHOUT the stripe_subscription_id column cannot tell a
    no-card trial from one that has since added a card (the marker stays
    on both), so it answers False — the full tank and no held sends, the
    fail-open direction every billing read here takes."""
    if not row or "stripe_subscription_id" not in row:
        return False
    if (row.get("stripe_subscription_id") or "").strip():
        return False
    # A comp (Kevin's override) outranks the trial it was given during.
    if (row.get("comp_tier") or "").strip():
        return False
    return marker(row) is not None


def is_running(row: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """A no-card trial that is still on the calendar."""
    if not is_no_card(row):
        return False
    if (row.get("subscription_status") or "").strip().lower() != "trialing":
        return False
    ends = _parse(row.get("trial_ends_at"))
    return bool(ends and ends > (now or datetime.now(timezone.utc)))


def _plan() -> str:
    plan = (os.environ.get("NO_CARD_TRIAL_PLAN") or "professional").strip().lower()
    return plan if plan in feature_gates.PLANS else "professional"


def _price_id(plan: str) -> str:
    return (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}") or "").strip()


# Throwaway inboxes: a no-card trial is a free tank of AI, and these are
# how one person becomes forty. Not exhaustive — the phone check is the
# real wall before anything costly — just the services that need no
# effort at all. Extend from Railway: DISPOSABLE_EMAIL_DOMAINS=a.com,b.net
_DISPOSABLE = frozenset("""
mailinator.com guerrillamail.com guerrillamail.net guerrillamail.org
guerrillamail.biz guerrillamail.de sharklasers.com grr.la pokemail.net
spam4.me 10minutemail.com 10minutemail.net 20minutemail.com temp-mail.org
temp-mail.io tempmail.com tempmail.net tempmail.dev tempmailo.com
tempail.com tempr.email tempinbox.com tmpmail.org tmpmail.net tmail.ws
yopmail.com yopmail.net yopmail.fr trashmail.com trashmail.net trashmail.de
getnada.com nada.email dispostable.com maildrop.cc throwawaymail.com
fakeinbox.com mintemail.com mohmal.com emailondeck.com discard.email
mytemp.email burnermail.io inboxkitten.com mailnesia.com mailcatch.com
moakt.com emailfake.com 1secmail.com 1secmail.org 1secmail.net
minuteinbox.com mailpoof.com spamgourmet.com getairmail.com mailsac.com
harakirimail.com dropmail.me emltmp.com fexbox.org mail.tm
""".split())


def disposable_email(email: Optional[str]) -> bool:
    domain = (email or "").rsplit("@", 1)[-1].strip().lower()
    if not domain or "@" not in (email or ""):
        return False
    extra = {d.strip().lower() for d in
             (os.environ.get("DISPOSABLE_EMAIL_DOMAINS") or "").split(",") if d.strip()}
    return domain in _DISPOSABLE or domain in extra


def eligible(row: Optional[Dict[str, Any]], email: Optional[str] = None) -> Optional[str]:
    """None when this business may start a no-card trial now, otherwise
    the reason it may not (logged, never shown). `email` is the person
    starting it, when known."""
    if not pricing_config.no_card_trial_enabled():
        return "disabled"
    if disposable_email(email):
        return "disposable_email"
    if not feature_gates.enforcement_on():
        return "enforcement_off"
    if _trial_days() <= 0:
        return "no_trial_days"
    if not row or not row.get("id"):
        return "no_business"
    if (row.get("comp_tier") or "").strip():
        return "comped"
    if (row.get("stripe_subscription_id") or "").strip():
        return "has_subscription"
    if (row.get("trial_ends_at") or "").strip() or marker(row) is not None:
        return "had_trial"
    if (row.get("subscription_status") or "").strip():
        return "has_status"
    if not _price_id(_plan()):
        return "plan_not_configured"
    owner = str(row.get("owner_id") or "")
    if not owner:
        return "no_owner"
    import usage_metering
    if usage_metering.is_grandfathered_user(owner):
        return "grandfathered"
    # Once per PERSON, not per business: a second business must not be a
    # second free tank. Any business of theirs that has had a trial or a
    # subscription counts (the marker always comes with trial_ends_at).
    others = sb_clients.sb_get_as_service(
        f"/businesses?owner_id=eq.{owner}&id=neq.{row['id']}"
        f"&or=(trial_ends_at.not.is.null,stripe_subscription_id.not.is.null)"
        f"&select=id&limit=1")
    if others is None:
        return "owner_history_unreadable"     # fail closed: the card door stays
    if others:
        return "owner_had_trial"
    return None


def start(row: Optional[Dict[str, Any]], source: str = "signup",
          email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Start the no-card trial on this business if it is eligible.

    Returns {trial_ends_at, plan, credits} when it started, else None.
    Never raises: a business that could not get its trial simply meets
    the card paywall, which is exactly how every signup worked before.

    The PATCH is conditional on the row still having no trial and no
    subscription, so two racing callers (signup and the access check)
    start ONE trial, and a Stripe webhook that landed first wins."""
    try:
        why = eligible(row, email)
        if why:
            logger.info(f"[no-card] not starting for {str((row or {}).get('id'))[:8]}: {why}")
            return None
        plan = _plan()
        now = datetime.now(timezone.utc)
        ends = now + timedelta(days=_trial_days())
        credits = pricing_config.trial_credits_no_card()
        settings = dict(row.get("settings") or {})
        settings[MARKER] = {"started_at": now.isoformat(), "plan": plan,
                            "credits": credits, "source": source}
        patch = {
            "subscription_status": "trialing",
            "trial_ends_at": ends.isoformat(),
            "subscription_plan": _price_id(plan),
            "tier": plan,
            "settings": settings,
        }
        where = (f"/businesses?id=eq.{row['id']}&stripe_subscription_id=is.null"
                 f"&trial_ends_at=is.null")
        res = sb_clients.sb_patch_as_service(where, patch)
        if res is None:
            # The tier mirror can trip an old CHECK (the Stripe webhook
            # has the same fallback); the trial is the part that matters.
            patch.pop("tier", None)
            res = sb_clients.sb_patch_as_service(where, patch)
        if not res:
            # Lost the race, or the write failed. Either way there is no
            # trial of OURS on the row to report.
            return None
        logger.info(f"[no-card] trial started for {row['id'][:8]} ({plan}, "
                    f"{credits} credits, ends {ends.date()})")
        try:
            import first_run_arc
            first_run_arc.begin(row["id"], source="subscription",
                                trial_ends_at=ends.isoformat())
        except Exception as e:
            logger.warning(f"[no-card] first-run arc align failed (non-fatal): {e}")
        return {"trial_ends_at": ends.isoformat(), "plan": plan, "credits": credits}
    except Exception as e:
        logger.warning(f"[no-card] start failed (card paywall stays): {e}")
        return None


def checkout_trial(row: Optional[Dict[str, Any]],
                   now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """What Checkout should do about the trial for a no-card business.

    None              not a no-card business; the caller's usual rule applies.
    {"trial_end": ts} the trial is still running: keep its end date, so the
                      card buys the rest of the tank, not a fresh 7 days.
                      Stripe needs 48h; a trial closer to its end than
                      that is given the 48h, which is the customer's way.
    {}                the trial already ended: no second trial."""
    if not is_no_card(row):
        return None
    now = now or datetime.now(timezone.utc)
    if not is_running(row, now):
        return {}
    ends = _parse(row.get("trial_ends_at"))
    end = max(ends, now + _CHECKOUT_MIN_TRIAL)
    return {"trial_end": int(end.timestamp())}


def describe(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The fields the app needs to word a no-card trial honestly."""
    no_card = is_no_card(row)
    out: Dict[str, Any] = {"no_card_trial": no_card}
    if no_card:
        out["trial_credits"] = pricing_config.trial_credits_no_card()
        out["card_trial_credits"] = pricing_config.trial_credits()
        # The free build waits for a verified phone; the site stays a
        # preview until a card (see "What waits for a card").
        out["phone_verified"] = phone_verified(row)
        out["site_live"] = False
    return out


def tank(row: Optional[Dict[str, Any]]) -> int:
    """The trial tank this business draws from."""
    if is_no_card(row):
        return pricing_config.trial_credits_no_card()
    return pricing_config.trial_credits()


# ─── What waits for a card ───────────────────────────────────────────
# Texts (every one goes out on our Twilio account, from the shared
# platform number for anyone without their own line), phone numbers
# (bought on our account), bulk email (sent on our Resend account, whose
# reputation every paying customer's mail rides on), a second site build
# (the first is free; the next is 1,000+ credits, double the whole tank)
# and the site going LIVE (preview-only until a card: the category norm —
# AI site builders generate free and charge to publish — and a no-card
# site cannot be a phishing page on our domain). One-to-one mail — a
# booking confirmation, an invoice, a reply to a client — is how a
# practitioner tries the product, and stays open.

class TrialGate(RuntimeError):
    """Raised where a no-card trial reaches something it must earn first.
    `error` is the 402 code the app reads; str() is the practitioner's
    message."""
    error = "trial_gate"

    def __init__(self, what: str, message: str):
        super().__init__(message)
        self.what = what
        self.message = message

    def detail(self) -> Dict[str, Any]:
        return {"error": self.error, "what": self.what, "message": self.message}


class CardRequired(TrialGate):
    """Waits for a card."""
    error = "card_required"


class PhoneRequired(TrialGate):
    """Waits for a verified phone (the free build's step-up check)."""
    error = "phone_required"


_WHAT = {
    "texts": "Texting turns on once there's a card on file.",
    "number": "A texting number comes once there's a card on file.",
    "bulk_email": "Sending to a group of contacts at once turns on once there's a card on file.",
    "rebuild": "Your free trial includes one site build, and you've used it.",
    "builds_full": "Today's free site builds are all taken.",
}


def card_message(what: str, row: Optional[Dict[str, Any]] = None) -> str:
    """The refusal, in the practitioner's words. While the trial is still
    running it says the true thing about adding a card: nothing is
    charged before the end date, and the tank grows."""
    lead = _WHAT.get(what, "That turns on once there's a card on file.")
    action = {"rebuild": "To build again, add a card",
              "builds_full": "To build now, add a card"}.get(what, "Add a card")
    msg = f"{lead} {action} in Settings → Billing"
    if row is not None and is_running(row):
        ends = _parse(row.get("trial_ends_at"))
        extra = max(0, pricing_config.trial_credits()
                    - pricing_config.trial_credits_no_card())
        msg += " — nothing is charged until your trial ends"
        if ends:
            msg += f" on {ends.strftime('%B')} {ends.day}"
        if extra:
            msg += f", and the card adds {extra:,} more credits"
    if what == "builds_full":
        msg += " — or try again tomorrow"
    return msg + "."


PHONE_MESSAGE = ("Verify your phone and Chief builds your site — it takes a "
                 "moment, and it keeps free builds for real people.")


def _row(business_id: str) -> Optional[Dict[str, Any]]:
    import usage_metering
    return usage_metering._biz_row(business_id)


def blocks(business_id: Optional[str],
           row: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The business row when it is a no-card trial (so the caller can word
    the refusal), else None. Fails OPEN — a lookup error never stops a
    send — like every billing read in this codebase."""
    if not business_id:
        return None
    try:
        r = row if row is not None and "settings" in row else _row(business_id)
        return r if is_no_card(r) else None
    except Exception as e:
        logger.warning(f"[no-card] gate read failed open for {str(business_id)[:8]}: {e}")
        return None


async def blocks_async(client, business_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """blocks() for async paths, on the caller's httpx client."""
    if not business_id:
        return None
    try:
        rows = await sb_clients.sb_as_service(
            client, "GET",
            f"/businesses?id=eq.{business_id}"
            f"&select=id,settings,subscription_status,stripe_subscription_id,"
            f"trial_ends_at,comp_tier&limit=1") or []
        r = rows[0] if rows else None
        return r if is_no_card(r) else None
    except Exception as e:
        logger.warning(f"[no-card] gate read failed open for {str(business_id)[:8]}: {e}")
        return None


def check(business_id: Optional[str], what: str,
          row: Optional[Dict[str, Any]] = None) -> None:
    """Raise CardRequired when a no-card trial reaches `what`."""
    r = blocks(business_id, row)
    if r is not None:
        raise CardRequired(what, card_message(what, r))


async def check_async(client, business_id: Optional[str], what: str) -> None:
    r = await blocks_async(client, business_id)
    if r is not None:
        raise CardRequired(what, card_message(what, r))


# ─── The free build: a verified phone, once, within a daily ceiling ──

def phone_verified(row: Optional[Dict[str, Any]]) -> bool:
    m = marker(row) or {}
    return bool(m.get("phone_hash") and m.get("phone_verified_at"))


def _day_start_iso(now: Optional[datetime] = None) -> str:
    n = now or datetime.now(timezone.utc)
    return (n.replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def free_builds_today() -> Optional[int]:
    """How many free site builds no-card trials have had today (UTC), or
    None when it cannot be read. A free build is a units=0 build marker
    (usage_metering.trial_first_build_is_free); only the ones whose
    business is still a no-card trial count — a card trial's free build
    is someone who gave a card."""
    rows = sb_clients.sb_get_as_service(
        f"/api_usage?task_type=eq.site_build_marker&units=eq.0"
        f"&created_at=gte.{_day_start_iso()}&select=business_id&limit=500")
    if rows is None:
        return None
    ids = sorted({str(r.get("business_id")) for r in rows if r.get("business_id")})
    if not ids:
        return 0
    biz = sb_clients.sb_get_as_service(
        f"/businesses?id=in.({','.join(ids)})"
        f"&select=id,settings,stripe_subscription_id,comp_tier&limit=500")
    if biz is None:
        return None
    return sum(1 for b in biz if is_no_card(b))


def check_phone(business_id: str) -> None:
    """A no-card trial verifies its phone before any 0-credit AI step that
    leads to a build (drafting the blueprint). Fails open on a read error."""
    r = blocks(business_id)
    if r is not None and not phone_verified(r):
        raise PhoneRequired("phone", PHONE_MESSAGE)


def check_build(business_id: str) -> None:
    """Every paid site build asks this first. For a no-card trial:

      1. a SECOND build waits for a card — the first is free, the next is
         charged 1,000+ credits against a 500 tank, and the AI gate only
         asks whether ANY credit is left;
      2. the free build waits for a verified phone — a card is too much to
         ask before the pitch, an email is too little to stop throwaway
         accounts each costing a build (~$2-3); a phone is the step-up
         every trial-abuse guide recommends before the expensive action;
      3. no more than no_card_free_builds_per_day() free builds a day,
         platform-wide — Kevin's money has a ceiling however many people
         sign up.

    Raises CardRequired / PhoneRequired. Read errors fail OPEN except the
    daily ceiling, which fails CLOSED: an unreadable count must not
    become unlimited free builds."""
    r = blocks(business_id)
    if r is None:
        return
    try:
        prior = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}"
            f"&task_type=eq.site_build_marker&select=id&limit=1")
    except Exception as e:
        logger.warning(f"[no-card] rebuild check failed open: {e}")
        prior = None
    if prior:
        raise CardRequired("rebuild", card_message("rebuild", r))
    if not phone_verified(r):
        raise PhoneRequired("phone", PHONE_MESSAGE)
    cap = pricing_config.no_card_free_builds_per_day()
    try:
        used = free_builds_today()
    except Exception as e:
        logger.warning(f"[no-card] free-build count failed closed: {e}")
        used = None
    if cap <= 0 or used is None or used >= cap:
        raise CardRequired("builds_full", card_message("builds_full", r))


# ─── The phone check ─────────────────────────────────────────────────
# Stateless: the code is never stored. send_phone_code returns a token,
# exp.HMAC(business, phone, code, exp); verify recomputes it from what the
# practitioner types. Attempts are rate-limited strictly (shared across
# replicas), so a six-digit code cannot be walked. US/Canada numbers
# only: OTP forms are the classic SMS-pumping target, and premium
# international numbers are how it pays. One phone, one free build,
# across every business on the platform.

PHONE_CODE_TTL_SECONDS = 600


class PhoneError(ValueError):
    """A refusal to show the practitioner as-is."""


def normalize_us(phone: Optional[str]) -> Optional[str]:
    import sms_service
    e164 = sms_service.normalize_phone(phone)
    if e164.startswith("+1") and len(e164) == 12 and e164[2:].isdigit():
        return e164
    return None


def phone_hash(e164: str) -> str:
    import hashlib
    import hmac
    from customer_token import derive_key
    return hmac.new(derive_key("trial-phone", "platform"), e164.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _code_sig(business_id: str, e164: str, code: str, exp: int) -> str:
    import hashlib
    import hmac
    from customer_token import derive_key
    return hmac.new(derive_key("trial-phone-code", str(business_id)),
                    f"{e164}|{code}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()


def _phone_taken(e164: str, business_id: str) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?settings->{MARKER}->>phone_hash=eq.{phone_hash(e164)}"
        f"&id=neq.{business_id}&select=id&limit=1")
    if rows is None:
        raise PhoneError("Couldn't check that number just now — try again in a moment.")
    return bool(rows)


def send_phone_code(business_id: str, phone: str) -> Dict[str, Any]:
    """Text a six-digit code to the practitioner's own phone. Returns
    {ok, token, expires_in} or {ok, verified} when already done.
    Raises PhoneError with the reason to show."""
    import secrets
    import time
    import rate_limit
    import twilio_sms
    row = _row(business_id)
    if not is_no_card(row):
        return {"ok": True, "verified": True, "not_needed": True}
    if phone_verified(row):
        return {"ok": True, "verified": True}
    e164 = normalize_us(phone)
    if not e164:
        raise PhoneError("Enter a US or Canadian mobile number.")
    if _phone_taken(e164, business_id):
        raise PhoneError("That number already unlocked a free build on another "
                         "account. Add a card in Settings → Billing to build instead.")
    if not rate_limit.allow_strict("trial_phone_send", str(business_id)):
        raise PhoneError("That's a lot of codes — try again in an hour.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    exp = int(time.time()) + PHONE_CODE_TTL_SECONDS
    body = (f"Solutionist: {code} is your code to unlock your free site build. "
            f"It works for 10 minutes. Didn't ask for it? Ignore this.")
    try:
        twilio_sms.send_sms(e164, body, from_number=twilio_sms.platform_number() or None)
    except Exception as e:
        logger.warning(f"[no-card] phone code send failed for {business_id[:8]}: "
                       f"{type(e).__name__}")
        raise PhoneError("Couldn't text that number — check it and try again.")
    return {"ok": True, "token": f"{exp}.{_code_sig(business_id, e164, code, exp)}",
            "expires_in": PHONE_CODE_TTL_SECONDS}


def verify_phone_code(business_id: str, phone: str, code: str, token: str) -> Dict[str, Any]:
    """Check the code; on success record the phone (hashed) on the trial."""
    import hmac
    import time
    import rate_limit
    if not rate_limit.allow_strict("trial_phone_check", str(business_id)):
        raise PhoneError("Too many tries — wait a few minutes and try again.")
    e164 = normalize_us(phone)
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    try:
        exp_s, sig = str(token or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        raise PhoneError("That code has expired — send a new one.")
    if not e164 or len(code) != 6:
        raise PhoneError("Enter the six-digit code from the text.")
    if exp < int(time.time()):
        raise PhoneError("That code has expired — send a new one.")
    if not hmac.compare_digest(_code_sig(business_id, e164, code, exp), sig):
        raise PhoneError("That code doesn't match — check the text and try again.")
    if _phone_taken(e164, business_id):
        raise PhoneError("That number already unlocked a free build on another account.")
    row = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
    if not row:
        raise PhoneError("Couldn't save that just now — try again in a moment.")
    settings = dict(row[0].get("settings") or {})
    m = dict(settings.get(MARKER) or {})
    if not m:
        return {"ok": True, "verified": True, "not_needed": True}
    m["phone_hash"] = phone_hash(e164)
    m["phone_verified_at"] = datetime.now(timezone.utc).isoformat()
    settings[MARKER] = m
    if sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                      {"settings": settings}) is None:
        raise PhoneError("Couldn't save that just now — try again in a moment.")
    forget(business_id)
    return {"ok": True, "verified": True}


# ─── Preview-only until a card ───────────────────────────────────────
# public_site asks this on every public page view, so the answer is
# cached briefly per business: a card added through Checkout puts the
# site live within a minute.

_HIDDEN_TTL_SECONDS = 60.0
_hidden_cache: Dict[str, Any] = {}


def forget(business_id: Optional[str]) -> None:
    _hidden_cache.pop(str(business_id or ""), None)


async def site_hidden(client, business_id: Optional[str]) -> bool:
    """True while this business is a no-card trial: its public address
    shows 'coming soon' instead of the site. Fails OPEN (shows the site)."""
    import time
    if not business_id:
        return False
    key = str(business_id)
    hit = _hidden_cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    hidden = (await blocks_async(client, key)) is not None
    _hidden_cache[key] = (now + _HIDDEN_TTL_SECONDS, hidden)
    return hidden
