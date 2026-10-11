"""
chief_offer_actions.py — Chief makes offers and runs refer-a-friend (2026-10-11).

Kevin, 2026-10-11: "continue to build the next steps that you just shared"
(a way for Chief to make an offer or switch on refer-a-friend). Chief does in
chat what the owner can do in Grow → Offers, through THE SAME functions the
page's API calls (offers.create_offer / change_offer, refer_a_friend.
set_referral), with their checks: card payments connected, codes never
taken twice, every rule on who and when. There is no second write path.

  verb                 class    how Chief calls it   what
  make_offer           write C  tag                  an offer: a code, a link and a counter-card
                                                     QR, checked at booking. Nothing goes out
  change_offer         write C  tag                  pause or turn back on an offer by its code,
                                                     or set its end day or most uses
  set_refer_a_friend   write C  tag                  refer a friend on or off, what each side
                                                     gets, the P.S. on rebook notes, how long a
                                                     thank-you code is good for

WHY CLASS C. An offer changes what a customer pays at checkout, and refer a
friend sends thank-you codes worth money by itself once it's on. Chief does
these when the owner asks in this chat turn (a voice turn is held for a
spoken yes by the class-C gate), never on its own and never unattended.

WHY TAGS, NOT NATIVE WRITE TOOLS. As with the marketing desk
(chief_marketing_actions): each is the owner's alone, checked against the
signed-in person driving THIS turn (chief_of_staff._TURN_USER_ID), which an
outside agent doesn't carry; and class C is never a tool.

WHO. The owner only: the turn's signed-in person against businesses.owner_id,
read as the service role (business_marketing._owner_row, the API's own
check). No turn, no change.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import ValidationError

logger = logging.getLogger("chief_offer_actions")

OFFERS_NAV = {"tab": "grow", "sub": "offers"}
DAY_WORDS = {"mon": 1, "monday": 1, "tue": 2, "tues": 2, "tuesday": 2, "wed": 3, "wednesday": 3,
             "thu": 4, "thur": 4, "thurs": 4, "thursday": 4, "fri": 5, "friday": 5, "sat": 6, "saturday": 6,
             "sun": 7, "sunday": 7}
WHO_WORDS = {"anyone": "for anyone", "first_visit": "for a first visit", "regulars": "for regulars"}


class Refusal(Exception):
    """A plain-words reason nothing changed."""

    def __init__(self, result: str, label: str):
        super().__init__(result)
        self.result, self.label = result, label


def _refused(verb: str, r: Refusal) -> Dict[str, Any]:
    # Both result and label, always: a missing result blanks the app.
    return {"type": verb, "result": r.result, "label": r.label, "nav": OFFERS_NAV, "ok": False, "failed": True}


def _sentence(text: str) -> str:
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _detail(e: Exception) -> str:
    """The server's own words for a refusal: an HTTPException's detail, or a
    validation error's first message without pydantic's prefix."""
    if isinstance(e, HTTPException):
        d = e.detail
        return _sentence(d if isinstance(d, str) else str((d or {}).get("message") or ""))
    if isinstance(e, ValidationError):
        errs = e.errors()
        msg = str(errs[0].get("msg") or "") if errs else ""
        return _sentence(msg.replace("Value error, ", ""))
    return ""


def _flag(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


def _cents(value: Any, what: str, nothing: str) -> int:
    try:
        cents = int(round(float(str(value).replace("$", "").strip()) * 100))
    except (TypeError, ValueError):
        raise Refusal(f"I need {what} as a number of dollars, so {nothing}.", "Amount not understood")
    if cents <= 0:
        raise Refusal(f"{what[:1].upper() + what[1:]} has to be more than $0, so {nothing}.", "Amount not understood")
    return cents


def _days(value: Any, nothing: str) -> List[int]:
    days = []
    for d in (value if isinstance(value, list) else str(value or "").replace(",", " ").split()):
        n = DAY_WORDS.get(str(d).strip().lower()) if not str(d).strip().isdigit() else int(str(d).strip())
        if not n or not 1 <= n <= 7:
            raise Refusal(f"I didn't understand the day {d!r}, so {nothing}.", "Days not understood")
        days.append(n)
    return sorted(set(days))


async def _owner(biz: Dict[str, Any], action: Dict[str, Any], nothing: str) -> str:
    """The owner, asking in this chat turn. Returns the business id."""
    import business_marketing as bm
    import chief_of_staff as cos
    bid = str((biz or {}).get("id") or "")
    if action.get("_unattended"):
        raise Refusal(f"Offers change what customers pay, so I only change them when the owner asks me in chat, "
                      f"never on a scheduled or automatic run. {nothing[:1].upper() + nothing[1:]}.",
                      "Ask me in chat")
    uid = str(cos._TURN_USER_ID.get() or "")
    if not uid:
        raise Refusal(f"I can only change offers when the business owner asks me in chat, so {nothing}.",
                      "Ask me in chat")
    try:
        await asyncio.to_thread(bm._owner_row, bid, uid)
    except HTTPException as e:
        if e.status_code == 403:
            raise Refusal(f"Only the business owner can change its offers, so {nothing}.", "Only the owner can")
        raise Refusal(f"I couldn't confirm this business just now, so {nothing}. Try again in a minute.",
                      "Couldn't confirm the business")
    return bid


# ─── make an offer ────────────────────────────────────────────────────

async def handle_make_offer(client, biz, action) -> Dict[str, Any]:
    """An offer, made through offers.create_offer (the Offers page's POST)."""
    import offers
    verb, nothing = "make_offer", "no offer was made"
    action = action or {}
    try:
        bid = await _owner(biz, action, nothing)
        body: Dict[str, Any] = {"who": action.get("who") or "anyone"}
        if action.get("free_item"):
            body.update(kind="free_item", free_item=str(action["free_item"]))
        elif action.get("percent") is not None:
            try:
                body.update(kind="percent_off", percent=int(round(float(action["percent"]))))
            except (TypeError, ValueError):
                raise Refusal(f"I need the percent off as a number, so {nothing}.", "Percent not understood")
        elif action.get("amount") is not None:
            body.update(kind="amount_off", amount_cents=_cents(action["amount"], "the amount off", nothing))
        else:
            raise Refusal(f"Tell me what it gives (dollars off, a percent off, or something free), so {nothing}.",
                          "What the offer gives is missing")
        if action.get("days"):
            body["hours"] = {"days": _days(action["days"], nothing), "start": str(action.get("start") or ""),
                             "end": str(action.get("end") or "")}
        for k in ("starts_on", "ends_on", "code", "title"):
            if action.get(k):
                body[k] = str(action[k])
        if action.get("max_uses") is not None:
            body["max_uses"] = action["max_uses"]
        body["one_per_person"] = _flag(action.get("one_per_person"), True)
        try:
            made = await offers.create_offer(bid, offers.OfferIn(**body), biz=biz)
        except (HTTPException, ValidationError) as e:
            msg = _detail(e) or "That offer could not be made."
            raise Refusal(msg if "nothing" in msg.lower() else f"{msg} Nothing was made.", "Offer not made")
        listed = made.get("offers") or []
        mine = next((o for o in listed if body.get("code") and o.get("code") == str(body["code"]).upper()), None) \
            or (listed[0] if listed else None)
        if not mine:
            raise Refusal("The offer saved, but I couldn't read it back. Open Grow, Offers to see it.", "Offer made")
        when = mine.get("when") or "Always on"
        who = WHO_WORDS.get(mine.get("who"), "for anyone")
        if mine.get("who") == "first_visit" and "first visit" in str(mine.get("title") or "").lower():
            who = ""                                   # "$10 off your first visit" says it already
        said = [f"Made {mine['code']}: {mine['title']}" + (f", {who}" if who else "")
                + (", any time" if when == "Always on" else f" ({when})")
                + (", once per person" if mine.get("one_per_person") else "")
                + (f", up to {mine['max_uses']} uses" if mine.get("max_uses") else "") + "."]
        if mine.get("link"):
            said.append(f"Its link: {mine['link']}. Nothing goes out until you share it: copy the link, post it, "
                        "or print its counter card in Grow, Offers.")
        else:
            said.append("Nothing can be booked online yet, so it has no link; the code works said at the counter.")
        return {"type": verb, "ok": True, "nav": OFFERS_NAV, "code": mine["code"], "link": mine.get("link"),
                "offer_id": mine.get("id"), "result": " ".join(said), "label": f"Offer {mine['code']} made"}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception("make_offer failed: %s", e)
        return _refused(verb, Refusal(f"I couldn't make that offer just now, so {nothing}. Try again in a minute.",
                                      "Offer not made"))


# ─── change an offer ──────────────────────────────────────────────────

async def handle_change_offer(client, biz, action) -> Dict[str, Any]:
    """Pause, turn back on, or change the end day or most uses of one of
    the owner's offers, by its code (offers.change_offer, the page's PATCH)."""
    import offers
    verb, nothing = "change_offer", "nothing was changed"
    action = action or {}
    try:
        bid = await _owner(biz, action, nothing)
        code = str(action.get("code") or "").strip().upper()
        if not code:
            raise Refusal(f"Tell me which offer by its code, so {nothing}.", "Which offer?")
        try:
            offer = await asyncio.to_thread(offers.find, bid, code)
        except RuntimeError:
            raise Refusal(f"Your offers couldn't be read just now, so {nothing}. Try again in a minute.",
                          "Offers not read")
        if not offer or offer.get("source") != "owner":
            raise Refusal(f"You don't have an offer with the code {code}, so {nothing}.", "No such offer")
        change: Dict[str, Any] = {}
        status = str(action.get("status") or "").strip().lower()
        if status in ("paused", "pause", "off"):
            change["status"] = "paused"
        elif status in ("on", "resume", "active"):
            change["status"] = "on"
        elif status:
            raise Refusal(f"An offer is on or paused, so {nothing}.", "Not changed")
        if action.get("ends_on"):
            change["ends_on"] = str(action["ends_on"])
        if action.get("max_uses") is not None:
            change["max_uses"] = action["max_uses"]
        if not change:
            raise Refusal(f"Tell me what to change: pause it, turn it back on, its end day or its most uses. "
                          f"So {nothing}.", "Not changed")
        try:
            await offers.change_offer(bid, str(offer["id"]), offers.OfferChange(**change), biz=biz)
        except (HTTPException, ValidationError) as e:
            raise Refusal(f"{_detail(e) or 'That change could not be saved.'} {nothing[:1].upper() + nothing[1:]}.",
                          "Not changed")
        said = []
        if change.get("status") == "paused":
            said.append(f"Paused {code}. Its link still opens your booking page, without the offer.")
        elif change.get("status") == "on":
            said.append(f"{code} is on again.")
        if change.get("ends_on"):
            said.append(f"{code} now ends {offers.when_words({'ends_on': change['ends_on']}).replace('through ', '')}.")
        if change.get("max_uses") is not None:
            said.append(f"{code} now works up to {change['max_uses']} times.")
        return {"type": verb, "ok": True, "nav": OFFERS_NAV, "code": code, **change,
                "result": " ".join(said), "label": f"Offer {code} changed"}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception("change_offer failed: %s", e)
        return _refused(verb, Refusal(f"I couldn't change that offer just now, so {nothing}. Try again in a minute.",
                                      "Not changed"))


# ─── refer a friend ───────────────────────────────────────────────────

async def handle_set_refer_a_friend(client, biz, action) -> Dict[str, Any]:
    """Refer a friend on or off, and its settings (refer_a_friend.set_referral,
    the card's PUT)."""
    import offers
    import refer_a_friend as rf
    verb, nothing = "set_refer_a_friend", "nothing was changed"
    action = action or {}
    try:
        bid = await _owner(biz, action, nothing)
        on = _flag(action.get("on"))
        if on is None:
            raise Refusal(f"Tell me whether to turn Refer a friend on or off, so {nothing}.", "On or off?")
        body: Dict[str, Any] = {"on": on}
        if action.get("amount") is not None:
            body["friend_cents"] = body["reward_cents"] = _cents(action["amount"], "the amount each way", nothing)
        if action.get("friend_amount") is not None:
            body["friend_cents"] = _cents(action["friend_amount"], "the friend's amount", nothing)
        if action.get("reward_amount") is not None:
            body["reward_cents"] = _cents(action["reward_amount"], "the client's thank-you", nothing)
        if action.get("in_notes") is not None:
            body["in_notes"] = _flag(action["in_notes"])
        if action.get("good_for_days") is not None:
            try:
                body["thanks_days"] = int(action["good_for_days"])
            except (TypeError, ValueError):
                raise Refusal(f"I need how long a thank-you code is good for as a number of days (or 0 for no end), "
                              f"so {nothing}.", "Days not understood")
        try:
            saved = await rf.set_referral(bid, rf.ReferralIn(**body), biz=biz)
        except (HTTPException, ValidationError) as e:
            raise Refusal(f"{_detail(e) or 'That could not be saved.'} {nothing[:1].upper() + nothing[1:]}.",
                          "Refer a friend not changed")
        r = saved.get("referral") or {}
        give = offers.money(int(r.get("friend_cents") or body.get("friend_cents") or rf.DEFAULT_CENTS))
        get = offers.money(int(r.get("reward_cents") or body.get("reward_cents") or rf.DEFAULT_CENTS))
        if on:
            said = [f"Refer a friend is on: a friend gets {give} off a first visit, and the client gets {get} off "
                    "their next one once the friend's visit is paid."]
            if r.get("in_notes") and r.get("rebook_on"):
                said.append("Each client's own link rides on their “Time for your next visit?” note.")
            elif r.get("in_notes"):
                said.append("Each client's link is set to ride on their “Time for your next visit?” note, but that "
                            "note is off in Outreach, so for now links go out when you send them from Grow, Offers.")
            else:
                said.append("Send any client their own link from Grow, Offers.")
            days = r.get("thanks_days")
            said.append(f"Thank-you codes are good for {days} days." if days else "Thank-you codes have no end.")
        else:
            said = ["Refer a friend is off. Links already shared stop giving money off; thank-yous already earned "
                    "still count."]
        return {"type": verb, "ok": True, "nav": OFFERS_NAV, "on": on, "friend_cents": r.get("friend_cents"),
                "reward_cents": r.get("reward_cents"), "result": " ".join(said),
                "label": "Refer a friend on" if on else "Refer a friend off"}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception("set_refer_a_friend failed: %s", e)
        return _refused(verb, Refusal(f"I couldn't change Refer a friend just now, so {nothing}. Try again in a "
                                      "minute.", "Refer a friend not changed"))
