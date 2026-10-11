"""business_marketing_sent_links.py — a tracked link on a text or an email.

The Reach plan's step 1 (Kevin, 2026-10-08: "ok all of the plans are great.
let's do it."): links on texts, emails and offers too, not only on posts. A
desk post's link is business_marketing_links'; this is the same link for
what goes out another way. First user: Grow → Outreach (campaigns_router),
where a touch (an email or a text) that says {{link}} sends that touch's own
short link.

  the link     {origin}/go/{code} on the business's own site, exactly like a
               post's: same origin, same redirect (marketing_follow, which
               looks here when the code names no post), same rule that only
               a person's click counts, same refusal to send anyone off the
               business's own hosts.
  where to     the booking page when anything is bookable, else the site's
               home (business_marketing_links.default_landing). Nowhere to
               go (no site, nothing published): no link, and {{link}} is
               left out of the words.
  the tags     utm_source=email|sms, utm_medium=outreach, utm_campaign=
               <campaign id>, utm_content=<link id>: the one join key the
               results use, as a post's id is for a post. So the visit, the
               lead, the booking and what was paid for it (booking_widget_
               router.booking_attribution) are credited to the touch.
  one per      touch: id and code are derived from (kind, campaign, touch),
               so every person who gets that touch gets the same link, and a
               retried send lands on the same row. Made on the touch's first
               send (marketing_links); nothing is made for a draft.

FAIL CLOSED. A read the link depends on that fails raises
links.LinksUnavailable or store.StoreError; the sender defers the send to a
later tick rather than send words with a dead or missing link.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from typing import Any, Dict, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlunsplit
from uuid import UUID, uuid5

import business_marketing_links as links
import business_marketing_store as store

logger = logging.getLogger("business_marketing_sent_links")

TOKEN = "{{link}}"
# Its own namespace: a link's id never equals a post's or a run's.
NAMESPACE = UUID("8f1d6c2a-5b7e-4f3a-9c1d-2e4b6a8c0f13")
KINDS = ("campaign", "journey", "offer")
OFFER_PARTS = ("share", "print")       # an offer's link to share, and its printed QR (counted apart)
CHANNELS = ("email", "sms")
_TOKEN_GAP = re.compile(r"[ \t]*\{\{link\}\}")


def link_id(kind: str, ref_id: Any, part: int) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown link kind {kind!r}")
    return str(uuid5(NAMESPACE, f"{kind}:{UUID(str(ref_id))}:{int(part)}"))


def link_code(lid: Any) -> str:
    """8 characters from the link's id, in the same alphabet as a post's code
    (store.GO_CODE), from its own prefix so it never equals a post's code for
    the same id."""
    raw = hashlib.sha256(f"marketing-link:{UUID(str(lid))}".encode()).digest()[:5]
    return base64.b32encode(raw).decode().lower()


def tracked_url(landing: str, lid: Any, site: Mapping[str, Any], *, channel: Optional[str], campaign_id: Any = None,
                medium: str = "outreach", campaign: Optional[str] = None, source: Optional[str] = None) -> str:
    """The landing page tagged for this link (utm_campaign: the campaign's id,
    a journey's name, or an offer's code; utm_source: the channel, or
    `source` for a link that isn't sent by email or text). Refuses a landing
    that is not on the business's own hosts (links._https_on)."""
    if source is None and channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    parts = links._https_on(landing, links.own_hosts(site))
    if parts is None:
        raise ValueError("A link goes to the business's own site or booking page.")
    tags = dict(parse_qsl(parts.query, keep_blank_values=True))
    tags.update({"utm_source": source or channel, "utm_medium": medium,
                 "utm_campaign": campaign or str(UUID(str(campaign_id))), "utm_content": str(UUID(str(lid)))})
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(tags), parts.fragment))


def wants_link(text: Optional[str]) -> bool:
    return TOKEN in (text or "")


def fill(text: str, link: Optional[str]) -> str:
    """The words with the link in place of {{link}}; with no link, the token
    is left out (and the space before it), never sent as written."""
    text = text or ""
    if TOKEN not in text:
        return text
    return text.replace(TOKEN, link) if link else _TOKEN_GAP.sub("", text)


async def campaign_link(business: Mapping[str, Any], campaign_id: Any, part: int, channel: str) -> Optional[str]:
    """The short link of a campaign's touch `part`, made on first use; None
    when the business has nowhere to send people. Raises
    links.LinksUnavailable / store.StoreError when a read or the write fails."""
    bid = str(UUID(str(business["id"])))
    site = await asyncio.to_thread(links.site_for, bid)
    landing = await asyncio.to_thread(links.default_landing, bid, business, site)
    if not site or not landing:
        return None
    lid = link_id("campaign", campaign_id, part)
    code = link_code(lid)
    row = {"id": lid, "business_id": bid, "code": code, "kind": "campaign", "ref_id": str(UUID(str(campaign_id))),
           "part": int(part), "channel": channel, "landing_url": landing,
           "tracked_url": tracked_url(landing, lid, site, channel=channel, campaign_id=campaign_id)}
    try:
        await store.request("POST", "/marketing_links", row)
    except store.StoreConflict:
        pass                                   # made by an earlier send of this touch: the same link
    return links.short_link(site, code)


def journey_ref(business_id: Any, journey: str) -> str:
    """The id a journey's links hang from (one per business and journey)."""
    return str(uuid5(NAMESPACE, f"journey-ref:{UUID(str(business_id))}:{journey}"))


async def journey_link(business: Mapping[str, Any], journey: str, channel: str) -> Optional[str]:
    """A journey's tracked link to the booking page (outreach_journeys): one
    per business, journey and channel (part 0 email, 1 text), made on first
    use; None when the business has nowhere to send people. Raises like
    campaign_link."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    bid = str(UUID(str(business["id"])))
    site = await asyncio.to_thread(links.site_for, bid)
    landing = await asyncio.to_thread(links.default_landing, bid, business, site)
    if not site or not landing:
        return None
    ref = journey_ref(bid, journey)
    part = CHANNELS.index(channel)
    lid = link_id("journey", ref, part)
    code = link_code(lid)
    row = {"id": lid, "business_id": bid, "code": code, "kind": "journey", "ref_id": ref, "part": part,
           "channel": channel, "landing_url": landing,
           "tracked_url": tracked_url(landing, lid, site, channel=channel, medium="journey", campaign=journey)}
    try:
        await store.request("POST", "/marketing_links", row)
    except store.StoreConflict:
        pass
    return links.short_link(site, code)


async def offer_link(business: Mapping[str, Any], offer: Mapping[str, Any], part: int) -> Optional[str]:
    """An offer's tracked link (offers.py): part 0 to share in posts and
    texts, part 1 for its printed QR, so a scan from the window counts apart
    from a tap. Both land on the booking page with the code already in
    (?offer=CODE). None when nothing can be booked online (the code still
    works at the counter). Made on first use; raises like campaign_link."""
    if part not in (0, 1):
        raise ValueError("an offer's link is part 0 (share) or 1 (print)")
    bid = str(UUID(str(business["id"])))
    site = await asyncio.to_thread(links.site_for, bid)
    if not site or not await asyncio.to_thread(links.bookable, bid, business):
        return None
    code = str(offer["code"])
    landing = f"{links.origin(site)}/book?offer={code}"
    lid = link_id("offer", offer["id"], part)
    short = link_code(lid)
    row = {"id": lid, "business_id": bid, "code": short, "kind": "offer", "ref_id": str(UUID(str(offer["id"]))),
           "part": part, "channel": None, "landing_url": landing,
           "tracked_url": tracked_url(landing, lid, site, channel=None, medium="offer", campaign=code,
                                      source=OFFER_PARTS[part])}
    try:
        await store.request("POST", "/marketing_links", row)
    except store.StoreConflict:
        pass
    return links.short_link(site, short)


def link_ids_for(campaign_id: Any, parts: int) -> Dict[int, str]:
    """{touch index: link id} for a campaign's touches (whether or not each was
    made yet): what its results read."""
    return {i: link_id("campaign", campaign_id, i) for i in range(int(parts))}
