"""
member_join.py — "New here? Join": someone the church doesn't have on file
gets into the member app by themselves.

Kevin, 2026-11-21, the night before the first church's Sunday: "we need to
build this ability because this might be the only way people can get in if
they don't have information". Until now only an email or mobile number the
church already had could sign in.

  THE DOOR     /my/join, from "New to <church>? Join" under the sign-in form.
               One screen: first and last name, email or mobile number, "I'm
               new here" or "I already come here", and "I'm 13 or older".
  THE CODE     the same 6-digit code as signing in (member_portal.issue_code),
               sent to what they typed. Their record is made only AFTER the
               right code comes back: the code proves the address is theirs,
               so nobody can put someone else's email on a church's list, and
               an address that never answers leaves nothing behind.
  THE PASS     what they typed rides from the form to the code page in a
               signed pass (a hidden field; customer_token key purpose
               "member-join"), bound to the church and the address, good for
               PASS_SECONDS. No table, no migration.
  NOTHING SAYS WHO IS ON THE LIST
               an address the church already has gets the ordinary sign-in
               code and signs in as that person (the record is never touched);
               an address on more than one record gets nothing, as at sign-in.
               The page that answers is the same in every case.
  THE RECORD   contacts: their name, the email or the phone, status lead,
               source member_app_join, tag "joined in the app". Then
               member_im_new.save, as if they had told the church "I'm new
               here" in the app: the New here (member app) follow-up to the
               welcome role, reading "First time? Yes" or "Been coming a
               while", the first-time-guest tag for a first timer, and a place
               in the New here room. Nothing is texted or emailed to them.
  LIMITS       per network (member_join_ip, generous: a church's Wi-Fi is one
               address on a Sunday), per address (sign-in's own minute and day),
               per church per day: codes to new addresses (member_join_sent_day)
               and records made (member_join_made_day). Mobile numbers: US and
               Canada only: texts abroad cost money, and sending them on demand
               is how SMS-pumping fraud works. A hidden field a person never
               fills (a bot does) gets the same page and nothing else.
  WHO          churches (church_follow_up.is_church) whose member page is on,
               sign-in open and a code can go out. MEMBER_JOIN = off | owner |
               on, on when unset ("owner": the platform's own church only;
               "off" is the way back). A church closes it for itself with
               settings.member_portal.join = false.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Dict, Mapping, Optional, Tuple

import sb_clients

logger = logging.getLogger("member_join")

SWITCH = "MEMBER_JOIN"
PASS_SECONDS = 30 * 60
PASS_VERSION = 1
NAME_MAX = 60
SOURCE = "member_app_join"
JOINED_TAG = "joined in the app"
VISITS = ("new", "attend")
HONEYPOT = "website"          # the hidden field: a person never fills it


# ─── who it's open to ─────────────────────────────────────────────────


def mode() -> str:
    m = (os.environ.get(SWITCH) or "on").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def join_open(biz: Mapping[str, Any]) -> bool:
    """Whether this church's sign-in page offers "Join". A read that fails
    is a no."""
    import member_portal as mp
    m = mode()
    if m == "off":
        return False
    try:
        if m == "owner":
            import member_asks
            if not member_asks.platform_church(biz.get("id")):
                return False
        import church_follow_up
        b = dict(biz)
        return (mp.portal_active(b) and mp.sign_in_open(b) and church_follow_up.is_church(b)
                and mp.portal_settings(b.get("settings")).get("join") is not False
                and mp.codes_can_go_out())
    except Exception:  # noqa: BLE001
        logger.warning("member join: could not tell whether join is open", exc_info=True)
        return False


# ─── the form ─────────────────────────────────────────────────────────


def _name(v: Any) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()[:NAME_MAX]


def us_phone(ident: str) -> bool:
    return bool(re.fullmatch(r"\+1\d{10}", ident or ""))


def clean(form: Mapping[str, Any]) -> Tuple[Dict[str, str], str]:
    """(values, error). values always carries what can be shown back in the
    form; error is "" when everything is in order."""
    import member_portal as mp
    raw_ident = str(form.get("email") or "").strip()[:120]
    vals = {"first": _name(form.get("first")), "last": _name(form.get("last")),
            "ident": mp.norm_ident(raw_ident), "typed": raw_ident,
            "visit": str(form.get("visit") or "") if str(form.get("visit") or "") in VISITS else "",
            "adult": "yes" if str(form.get("adult") or "") == "yes" else ""}
    for part in ("first", "last"):
        if "://" in vals[part] or "@" in vals[part]:
            vals[part] = ""
    if not vals["first"] or not vals["last"]:
        return vals, "Enter your first and last name."
    if not mp.valid_ident(vals["ident"]):
        return vals, "Enter your email or mobile number."
    if mp.is_phone(vals["ident"]) and not us_phone(vals["ident"]):
        return vals, "Use a US or Canadian mobile number, or your email."
    if not vals["visit"]:
        return vals, "Tell us if you're new here or already come."
    if not vals["adult"]:
        return vals, "You need to be 13 or older to join. A parent can add you from their own page."
    return vals, ""


# ─── the pass: what they typed, signed, from the form to the code ─────


def _sign(business_id: str, payload: str) -> str:
    import member_portal as mp
    return mp._b64(hmac.new(mp._key("member-join", business_id), payload.encode("ascii"),
                            hashlib.sha256).digest())


def mint_pass(business_id: str, vals: Mapping[str, str], now: Optional[int] = None) -> str:
    import member_portal as mp
    now = int(now if now is not None else time.time())
    payload = mp._b64(json.dumps({
        "b": str(business_id), "i": mp.norm_ident(vals["ident"]), "f": vals["first"], "l": vals["last"],
        "v": vals["visit"], "exp": now + PASS_SECONDS, "pv": PASS_VERSION,
    }, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(business_id, payload)}"


def read_pass(value: Any, business_id: str, ident: str, now: Optional[int] = None) -> Optional[Dict[str, str]]:
    """The pass's name and visit for THIS church and THIS address, or None.
    Never raises."""
    import member_portal as mp
    try:
        payload, sig = str(value or "").split(".", 1)
        if not hmac.compare_digest(_sign(business_id, payload), sig):
            return None
        c = json.loads(mp._unb64(payload))
        if c.get("pv") != PASS_VERSION or str(c.get("b")) != str(business_id):
            return None
        if mp.norm_ident(c.get("i")) != mp.norm_ident(ident) or not mp.valid_ident(mp.norm_ident(ident)):
            return None
        if int(c.get("exp") or 0) <= int(now if now is not None else time.time()):
            return None
        first, last, visit = _name(c.get("f")), _name(c.get("l")), str(c.get("v") or "")
        if not first or not last or visit not in VISITS:
            return None
        return {"first": first, "last": last, "visit": visit}
    except Exception:  # noqa: BLE001
        return None


# ─── the record ───────────────────────────────────────────────────────


def make_person(business_id: str, ident: str, who: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """The joiner's record, made now (after their code was right). If the
    address turned up on a record meanwhile, that one person. None when a
    read or the write failed, or the church's day of new records is spent."""
    import member_cache
    import member_portal as mp
    import rate_limit
    biz = str(business_id)
    people = mp.contacts_for_ident(biz, ident)
    if people is None:
        return None
    if people:
        return people[0] if len(people) <= mp.MAX_HOUSEHOLD else None
    if not rate_limit.allow_strict("member_join_made_day", biz):
        logger.warning("member join: the day's new records are spent (business %s)", biz[:8])
        return None
    row: Dict[str, Any] = {"business_id": biz, "name": f"{who['first']} {who['last']}".strip(),
                           "status": "lead", "source": SOURCE, "tags": [JOINED_TAG]}
    if mp.is_phone(ident):
        row["phone"] = ident
    else:
        row["email"] = mp.norm_email(ident)
    made = sb_clients.sb_post_as_service("/contacts", row)
    if not (isinstance(made, list) and made):
        logger.warning("member join: the record was not saved (business %s)", biz[:8])
        return None
    # Read back through sign-in's own lookup, so the row carries what a
    # session reads, and keep it for the page they land on next.
    people = mp.contacts_for_ident(biz, ident)
    if people:
        member_cache.people.put((biz, mp.norm_ident(ident)), people, tag=biz)
        return people[0] if len(people) <= mp.MAX_HOUSEHOLD else None
    return dict(made[0])


def welcome(business: Mapping[str, Any], person: Mapping[str, Any], visit: str) -> None:
    """The church hears about them as it hears about a member who says "I'm
    new here": a follow-up to the welcome role, the first-time tag for a
    first timer. Runs after the reply; never raises."""
    try:
        import member_im_new
        a = member_im_new.clean({"first": "yes" if visit == "new" else "no"})
        ok, said = member_im_new.save(business, person, a)
        if not ok:
            logger.warning("member join: welcome not handed on (%s, business %s)", said,
                           str(business.get("id"))[:8])
    except Exception:  # noqa: BLE001
        logger.warning("member join: welcome not handed on (business %s)", str(business.get("id"))[:8],
                       exc_info=True)
