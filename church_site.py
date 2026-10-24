"""
church_site.py — the church section of the public site: /churches and its
seven product pages.

Kevin, 2026-10-23, after the design rounds on the "Church Front Page"
canvas (claude.ai/artifact/AEtgwqRKascF3YW5rNu6Wk): "I like the design,
build this!" The concept is Stained Glass Light. The S mark is already
faceted, so each part of church life gets a glass tile and a colour of its
own, and that colour lights its whole page; Chief is the character on
every page, doing that room's real job; the devices are drawn in HTML and
stand still. Every product claim on the pages was checked against the
modules that back it before it was drawn.

The pages are the canvas's own markup, converted once into
church_site/*.html (the canvas wrappers gone, real links in place). What
must match the product is never typed into them: prices, yearly prices,
monthly AI actions, the meter widths, the trial and card wording and the
founding seat are {{TOKENS}} filled here from the same dials the main
site reads (marketing_pages._tier_dials and its trial helpers,
marketing_home_v3._founder_state), so the church pages cannot drift from
checkout. Logins, banks and the depth ladder are in prose; tests hold the
prose to the dials.

On by default since 2026-10-23 (Kevin: "I should be able to get to
churches page and any other page from mysolutionist.app"). CHURCH_SITE=off
is the rollback: /churches goes back to marketing_home_v3's church edition
and the product paths fall through to the catch-all as before.
"""
from __future__ import annotations

import functools
import os
import pathlib
import re
from html import escape
from typing import Dict

DIR = pathlib.Path(__file__).resolve().parent / "church_site"
ORIGIN = "https://mysolutionist.app"

# slug -> the template and its <head>. "" is the overview at /churches.
PAGES: Dict[str, Dict[str, str]] = {
    "": {
        "file": "overview.html",
        "title": "Solutionist for Churches · The Solutionist System",
        "description": ("Your people and their care, giving, kids check-in, groups and the member app in one "
                        "system, with Chief keeping it moving between Sundays. Month to month, on your own "
                        "Stripe, and we never take a cut of giving."),
    },
    "people-and-care": {
        "file": "people-and-care.html",
        "title": "People and Care · Solutionist for Churches",
        "description": ("Every guest card becomes someone's job, every family has a shepherd who hears early "
                        "when they stop coming, and prayer reaches the person who will pray."),
    },
    "giving": {
        "file": "giving.html",
        "title": "Giving · Solutionist for Churches",
        "description": ("Online giving on your church's own Stripe account, with funds, monthly gifts and "
                        "year-end statements. No platform fee on any gift."),
    },
    "kids-and-youth": {
        "file": "kids-and-youth.html",
        "title": "Kids and Youth · Solutionist for Churches",
        "description": ("Check children in at the desk, on a tablet or at a family kiosk, with printed tags, a "
                        "texted pickup code, and a space of their own for teens."),
    },
    "groups-and-classes": {
        "file": "groups-and-classes.html",
        "title": "Groups and Classes · Solutionist for Churches",
        "description": ("Every small group gets its own chat, prayer wall and meeting schedule, with this "
                        "week's study drafted from Sunday's message for the leader to post."),
    },
    "member-app": {
        "file": "member-app.html",
        "title": "Member App · Solutionist for Churches",
        "description": ("Your church's own app on every member's phone: news and alerts, the Bible, sermons "
                        "and live services, giving, groups, and spaces for youth and kids."),
    },
    "website-and-sermons": {
        "file": "website-and-sermons.html",
        "title": "Website and Sermons · Solutionist for Churches",
        "description": ("Your church's website on its own address, with every sermon by series, events "
                        "people sign up for themselves, and answers for visitors."),
    },
    "office-and-books": {
        "file": "office-and-books.html",
        "title": "Office and Books · Solutionist for Churches",
        "description": ("The church's books on the same system as its giving: funds kept apart, a month-end "
                        "close, statements in January, and giving seen only by the people who should see it."),
    },
}
PRODUCTS = tuple(s for s in PAGES if s)

_TOKEN = re.compile(r"\{\{[A-Z_]+\}\}")
# The ChurchSavvy partner links, removed when there is no partner site to send people to yet.
_CHURCHSAVVY_LINK = re.compile(r'<a href="\{\{CHURCHSAVVY_URL\}\}"[^>]*>.*?</a>\s*', re.S)


def enabled() -> bool:
    return (os.environ.get("CHURCH_SITE") or "on").strip().lower() not in ("off", "0", "false", "no")


def path_of(slug: str) -> str:
    return "/churches" + (f"/{slug}" if slug else "")


@functools.lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def _plan_tokens() -> Dict[str, str]:
    """Prices, yearly prices, AI actions, conversations and meter widths, from
    the dials. A conversation is one Chief turn at the chat price, rounded
    down the way the main site's plan cards round it (_credits_in_words)."""
    import marketing_pages as mp
    import pricing_config
    dials = mp._tier_dials()
    credits = {p: int(str(d["credits"]).replace(",", "")) for p, d in dials.items()}
    top = max(credits.values()) or 1
    per_turn = max(1, pricing_config.chat_price())
    out: Dict[str, str] = {}
    for key, plan in (("STARTER", "starter"), ("PRO", "professional"), ("SOL", "practice")):
        price = int(dials[plan]["price_num"])
        out[f"P_{key}"] = str(price)
        out[f"Y_{key}"] = f"{price * mp.ANNUAL_MONTHS:,}"
        out[f"C_{key}"] = dials[plan]["credits"]
        out[f"CONV_{key}"] = f"{mp._about(credits[plan] // per_turn):,}"
        out[f"W_{key}"] = str(max(4, round(credits[plan] / top * 100)))
    return out


def _trial_tokens() -> Dict[str, str]:
    """The trial and card wording, from what checkout actually grants:
    "no card" only while signup really starts the trial without one."""
    import marketing_pages as mp
    free = mp._trial_free_phrase()
    if mp._no_card_trial_offered():
        return {"CTA_START": "Start free, no card", "TRIAL_LINE": f"{free}, no card needed.",
                "TRIAL_FINE": free + mp._trial_card_note()}
    if mp._trial_days():
        return {"CTA_START": "Start free", "TRIAL_LINE": f"{free}, no card charged until the trial ends.",
                "TRIAL_FINE": free}
    return {"CTA_START": "Get started", "TRIAL_LINE": "Month to month. Cancel any time.",
            "TRIAL_FINE": free}


_ARROW = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0B0C11" stroke-width="2.2" '
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>')


def _founder_strip() -> str:
    """The founding seat under the overview's price cards, in the same words
    as the main site's strip, or nothing when there is no seat to sell."""
    import marketing_home_v3
    f = marketing_home_v3._founder_state()
    if not f:
        return ""
    sq = '<span class="sq" aria-hidden="true"></span>'
    if f["left"] <= 0:
        return (f'<div class="seat">{sq}<b style="font-family: \'Inter Tight\', sans-serif; font-weight: 600; '
                f'font-size: 15px">The {f["limit"]} founding seats are gone.</b>'
                f'<span style="font-size: 14px; color: #5A5E6B">The price on this page is the price.</span></div>')
    return (f'<a href="/start?plan=founder" class="seat">{sq}'
            f'<b style="font-family: \'Inter Tight\', sans-serif; font-weight: 600; font-size: 15px">Founding seat</b>'
            f'<span style="font-size: 14px; color: #5A5E6B">Professional for ${f["price"]} a month, locked while you '
            f'hold it. <b style="color: #0B0C11">{f["left"]}</b> of {f["limit"]} seats left.</span>'
            f'<span style="margin-left: auto; display: inline-flex; align-items: center; gap: 8px; font-weight: 600; '
            f'font-size: 14.5px">Claim seat {f["next"]:02d}{_ARROW}</span></a>')


def render(slug: str) -> str:
    """One page of the church section, every token filled."""
    import marketing_home_v2 as v2
    import marketing_pages as mp
    meta = PAGES[slug]
    page = _read(meta["file"])
    partner = (os.environ.get("CHURCHSAVVY_URL") or "").strip()
    if not partner.startswith("https://"):
        page = _CHURCHSAVVY_LINK.sub("", page)
    tokens = {
        "TITLE": escape(meta["title"]),
        "DESCRIPTION": escape(meta["description"]),
        "URL": ORIGIN + path_of(slug),
        "APP_URL": mp.APP_URL,
        "CHURCHSAVVY_URL": escape(partner),
        "CHURCH_CSS": _read("church.css"),
        **_plan_tokens(),
        **_trial_tokens(),
    }
    if "{{FOUNDER_STRIP}}" in page:
        tokens["FOUNDER_STRIP"] = _founder_strip()
    tokens["PIXEL"] = mp._pixel_script()
    tokens["ANALYTICS"] = v2._analytics_scripts()
    return _TOKEN.sub(lambda m: tokens.get(m.group(0)[2:-2], m.group(0)), page)
