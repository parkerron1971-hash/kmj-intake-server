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

Church plans by size (2026-11-03). While pricing_config.church_plans_offered()
is on (PLAN_CHURCH_OFFERED=1), every part of a page that describes the public
ladder (Starter / Professional / Solutionist) gives way to the four church
plans: Small, Growing, Established and Large. In the templates those parts
are sections, {{#NAME}}the public ladder's words{{/NAME}}. Switched off, the
markers drop and the page is what it was; switched on, each section becomes
_by_size()[NAME], drawn here from pricing_config, feature_gates and
chief_models, the dials checkout and the plan limits read.

On by default since 2026-10-23 (Kevin: "I should be able to get to
churches page and any other page from mysolutionist.app"). CHURCH_SITE=off
is the rollback: /churches goes back to marketing_home_v3's church edition
and the product paths fall through to the catch-all as before.

The church page is the front door (2026-11-04). Kevin narrowed Solutionist
to churches first, then approved the church-first mock
(claude.ai/artifact/CgBg3zVjHSQ2EFgaZyHdUy): "this design will work for
now. build it and merge it." mysolutionist.app/ now serves the overview
(is_home), with the Sunday Light hero ("Many pieces. One light."), Why
Solutionist exists (grow, belong, serve; the mission and the vision), a week
at a sample church, the move, and the size picker. Its new parts' style and
behaviour sit beside the template in overview.css and overview.js.
HOME_EDITION=v3 (or v2) is the rollback, a Railway value rather than a
deploy: / goes back to the business home, and the church page stays at
/churches. The picker's plans, the move's offer and the hero's "priced by
the size of your Sunday" come from the same dials as the cards.

The product pages become lit rooms (2026-11-05), Giving first. Kevin, on the
Giving mock (claude.ai/artifact/NHKdhA7FbSsaaR788at2Zn): "the design is good!
love it. let's build it". A lit room carries {{LIT_CSS}} / {{LIT_JS}} (the
shared kit in lit.css and lit.js: devices at a size people can read, the
room's own stained glass and light, a sticky story in steps, the ring a
finger leaves) and {{ROOM_CSS}} / {{ROOM_JS}} (its own parts, beside its
template: giving.css, giving.js). Every sample on a lit room is labeled or
plainly a sample church; every claim is one the page already made.
"""
from __future__ import annotations

import functools
import os
import pathlib
import re
from html import escape
from typing import Dict, List

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
        "description": ("Every guest card becomes someone's job, every member family can have a shepherd who hears "
                        "early when they stop coming, and prayer reaches the person who will pray."),
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
        "description": ("The church's books on the same system as its giving: gifts counted by fund, a month-end "
                        "close, statements in January, and giving seen only by the people who should see it."),
    },
}
PRODUCTS = tuple(s for s in PAGES if s)

_TOKEN = re.compile(r"\{\{[A-Z_]+\}\}")
# A part of a page that says the public ladder; see the module docstring.
_SECTION = re.compile(r"\{\{#([A-Z0-9_]+)\}\}(.*?)\{\{/\1\}\}", re.S)
# The ChurchSavvy partner links, removed when there is no partner site to send people to yet.
_CHURCHSAVVY_LINK = re.compile(r'<a href="\{\{CHURCHSAVVY_URL\}\}"[^>]*>.*?</a>\s*', re.S)


def enabled() -> bool:
    return (os.environ.get("CHURCH_SITE") or "on").strip().lower() not in ("off", "0", "false", "no")


def home_edit() -> bool:
    """Whether the overview carries the 2026-11-10 edit (overview_edit.css and .js): the product leads
    the hero, one window and one accent, fewer boxes. On unless HOME_EDIT=off, which gives back the page
    as it was with no deploy. Kevin: "hero product is it! i like that one."""
    return (os.environ.get("HOME_EDIT") or "on").strip().lower() not in ("off", "0", "false", "no")


def is_home() -> bool:
    """Whether mysolutionist.app/ is the church overview: unless HOME_EDITION
    names one of the business homes (v3, v2), and while the section is on."""
    edition = (os.environ.get("HOME_EDITION") or "").strip().lower()
    return enabled() and edition in ("", "churches")


# The business home's own address while the church page is the home (Kevin, 2026-11-04: "give the
# business home its own page at /business for now"). With a business home back at / (HOME_EDITION=v3
# or v2), / is its address again and /business serves the same page with "/" as its canonical.
BUSINESS_PATH = "/business"

# Where a church page's Start buttons go: public_site's /start carries for=church to the
# app, whose signup and setup then speak church (Kevin's run-through, 2026-11-05).
START_PATH = "/start?for=church"


def business_path() -> str:
    """Where the business home lives right now: /business while the church page is the home, / otherwise."""
    return BUSINESS_PATH if is_home() else "/"


# The product pages' strip link to the business home: with the church page at /, it goes to /business.
_ALL_OF_SOLUTIONIST = re.compile(r'<a href="\{\{HOME\}\}/"([^>]*>All of Solutionist</a>)')


def path_of(slug: str) -> str:
    return "/churches" + (f"/{slug}" if slug else "")


@functools.lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def _plan_tokens() -> Dict[str, str]:
    """Prices, yearly prices, AI actions, messages to Chief and meter widths,
    from the dials. Messages are credits over what a message charges on
    average (pricing_config.credits_per_message), rounded down the way the
    main site's plan cards round it (_credits_in_words)."""
    import marketing_pages as mp
    import pricing_config
    dials = mp._tier_dials()
    # The three cards this page draws, measured against each other: the
    # dials also carry every audience plan (a Large Church's 30,000 credits
    # would shrink every bar here).
    credits = {p: int(str(dials[p]["credits"]).replace(",", "")) for p in ("starter", "professional", "practice")}
    top = max(credits.values()) or 1
    per_turn = pricing_config.credits_per_message()
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
    return (f'<a href="{ORIGIN}/start?plan=founder" class="seat">{sq}'
            f'<b style="font-family: \'Inter Tight\', sans-serif; font-weight: 600; font-size: 15px">Founding seat</b>'
            f'<span style="font-size: 14px; color: #5A5E6B">Professional for ${f["price"]} a month, locked while you '
            f'hold it. <b style="color: #0B0C11">{f["left"]}</b> of {f["limit"]} seats left.</span>'
            f'<span style="margin-left: auto; display: inline-flex; align-items: center; gap: 8px; font-weight: 600; '
            f'font-size: 14.5px">Claim seat {f["next"]:02d}{_ARROW}</span></a>')


# ─── Church plans by size ────────────────────────────────────────────

_TICK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg>'
_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
# The line under each overview card's meter, smallest church to largest.
_METER_LINES = (" to Chief.", ", room to draft for every shepherd and leader.",
                ", Chief across every ministry.", ", Chief beside a large staff.")
_DEPTH_DOTS = {"Standard": 1, "Advanced": 2, "Maximum": 3}


def plans_by_size() -> bool:
    """Whether the church section shows the church plans by size: the
    switch that puts them on sale (PLAN_CHURCH_OFFERED=1)."""
    import pricing_config
    return pricing_config.church_plans_offered()


def _words(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else f"{n:,}"


def _dollars(cents: int) -> str:
    return f"{cents // 100:,}" if cents % 100 == 0 else f"{cents / 100:,.2f}"


def _count(n: int, thing: str) -> str:
    return f"{n:,} {thing}" + ("" if n == 1 else "s")


def _and(words) -> str:
    words = list(words)
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _name(plan: str) -> str:
    """The plan's name at checkout: 'Growing Church'."""
    import billing_limits
    return billing_limits.PLAN_DISPLAY.get(plan, plan)


def _short(plan: str) -> str:
    """The plan's name in a sentence: 'Growing'."""
    name = _name(plan)
    return name[:-len(" Church")] if name.endswith(" Church") else name


def _on(feature: str) -> str:
    """Which church plans carry a feature, from feature_gates: 'every plan',
    or their names ('Established and Large')."""
    import feature_gates as fg
    plans = [p for p in fg.CHURCH_PLANS if feature in fg.plan_features(p)]
    if len(plans) == len(fg.CHURCH_PLANS):
        return "every plan"
    return _and(_short(p) for p in plans)


def _people(plan: str) -> str:
    """The size a plan is for: 'Up to 100 people on a Sunday'."""
    import pricing_config
    low, high = pricing_config.church_size_bands()[plan]
    if high is None:
        return f"{low:,} or more people on a Sunday"
    if not low:
        return f"Up to {high:,} people on a Sunday"
    return f"{low:,}–{high:,} people on a Sunday"


def _clips(hours: int) -> str:
    return f"Clips from {_count(hours, 'hour')} of sermons a month"


def _includes(plan: str) -> List[str]:
    """An overview card's Includes list, from the plan's limits and features."""
    import feature_gates as fg
    lim = fg.plan_limits()[plan]
    have = fg.plan_features(plan)
    out = [_count(lim["max_seats"], "office login"), _count(lim["texts_monthly"], "text") + " a month",
           _clips(lim["clip_hours_monthly"])]
    if "dedicated_sms_number" in have:
        out.append("Your own texting number and text-to-give")
    if {"reports_full", "period_close", "vertical_reports"} <= have:
        out.append("Full books, budgets and the donors report")
    if {"audit_trail", "accountant_collaborator"} <= have:
        out.append("An audit trail, and a seat for your accountant")
    if (lim.get("max_businesses") or 1) > 1:
        out.append(f"Up to {lim['max_businesses']} organizations, like a church and its school")
    return out


def _plan_cards() -> str:
    """The overview's four cards, in the markup of the three they replace.
    Growing is the lit card, where Professional sits on the public ladder;
    the meters are measured against the four church plans."""
    import chief_models
    import feature_gates as fg
    import marketing_pages as mp
    import pricing_config
    plans = fg.CHURCH_PLANS
    prices = pricing_config.church_price_cents()
    credits = pricing_config.church_credits()
    top = max(credits.values()) or 1
    per_turn = pricing_config.credits_per_message()
    cards = []
    for i, plan in enumerate(plans):
        lit = i == 1
        label = chief_models.deep_analysis_label(plan)
        on = _DEPTH_DOTS.get(label, 1)
        dots = "".join('<i class="on"></i>' if n < on else "<i></i>" for n in range(3))
        month, year = _dollars(prices[plan]), _dollars(prices[plan] * mp.ANNUAL_MONTHS)
        conv = f"{mp._about(credits[plan] // per_turn):,}"
        width = max(4, round(credits[plan] / top * 100))
        line = _METER_LINES[min(i, len(_METER_LINES) - 1)]
        items = "\n".join(f"<li>{_TICK}<span>{escape(x, quote=False)}</span></li>" for x in _includes(plan))
        button = "background: #F5F6F8; color: #0B0C11" if lit else "border: 1px solid rgba(11,12,17,0.2); color: #0B0C11"
        cards.append(
            f'<div class="pc{" mid" if lit else ""}">\n'
            '<div style="display: flex; justify-content: space-between; align-items: center; min-height: 24px">'
            f'<span class="pname">{escape(_name(plan))}</span></div>\n'
            f'<div class="pz"><b>$<span class="pnum" data-m="{month}" data-y="{year}">{month}</span></b>'
            '<span class="pper">a month</span></div>\n'
            '<div class="pbl">Billed monthly · cancel anytime</div>\n'
            f'<div class="pds">{_people(plan)}.</div>\n'
            f'<div class="mtr"><div class="mrow"><b>{credits[plan]:,}</b><span>AI actions a month</span></div>'
            f'<div class="mbar"><i style="width: {width}%"></i></div><small>About {conv} messages{line}</small></div>\n'
            f'<div class="dep"><span>Chief thinks <b>{escape(label)}</b></span><span class="dd">{dots}</span></div>\n'
            '<div class="pinc">Includes</div>\n'
            f'<ul>\n{items}\n</ul>\n'
            f'<a href="{{{{HOME}}}}/start" class="pbtn" style="{button}">Start free</a>\n'
            '</div>')
    return '<div class="plans four">\n' + "\n\n".join(cards) + "\n</div>"


def _offer_line() -> str:
    """What sits around the four plans, from pricing_config.church_offer():
    Multi-site, extra texts and what a text is, one more login, and the
    move. It takes the founding seat's place under the cards: for churches
    the founding offer is the free move.

    What a text is: texts are counted by 160-character part, the way they
    are billed (church_texts.py). It's said here, under the cards, and once
    in the FAQ, not on every line that says "texts"."""
    import church_texts
    import pricing_config
    o = pricing_config.church_offer()
    top = max(h for (_low, h) in pricing_config.church_size_bands().values() if h is not None)
    months, moves = o["move_months"], o["founding_moves"]
    move = f"Moving from another system costs {_words(months)} month{'' if months == 1 else 's'} of your plan"
    # The price the first churches keep is its own line now (_founding_line):
    # ten churches keep their price, the first five who ask move free.
    if moves == 1:
        move += ", and the first church moves free."
    elif moves:
        move += f", and the first {_words(moves)} churches move free."
    else:
        move += "."
    text = (f"Over {top:,} people or more than one campus? Multi-site starts at "
            f"${_dollars(o['multi_site_from_cents'])} a month. "
            f"Extra texts are ${_dollars(o['extra_texts_cents_per_thousand'])} per 1,000. {church_texts.UNIT_LINE} "
            f"One more office login is ${_dollars(o['extra_login_cents'])} a month. {move}")
    return ('<div style="display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 20px; padding: 18px 22px; '
            'border-radius: 18px; background: #FFFFFF; border: 1px solid rgba(11,12,17,0.12)">'
            '<b style="font-family: \'Inter Tight\', sans-serif; font-weight: 600; font-size: 15px">Good to know</b>'
            f'<span style="flex: 1 1 420px; min-width: 0; font-size: 14px; line-height: 1.55; color: #5A5E6B">{text}</span>'
            '</div>')


def _founding_line() -> str:
    """The founding churches' price under the cards (Kevin, 2026-11-13: "yes
    founding prices"): the first ten churches that pay keep the price they
    start at, for as long as they stay, and how many places are left. Nothing
    while the offer is off, the count can't be read, or the places are gone
    (church_founding.public_state; the count may lag five minutes)."""
    import church_founding
    state = church_founding.public_state()
    if not state or state["left"] <= 0:
        return ""
    total = state["spots"]
    who = "The first church keeps the price it starts at, for as long as it stays." if total == 1 else \
        f"The first {_words(total)} churches keep the price they start at, for as long as they stay."
    return ('<div style="display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 20px; padding: 18px 22px; '
            'border-radius: 18px; background: #FFFFFF; border: 1px solid rgba(11,12,17,0.12)">'
            '<b style="font-family: \'Inter Tight\', sans-serif; font-weight: 600; font-size: 15px">Founding price</b>'
            '<span style="flex: 1 1 420px; min-width: 0; font-size: 14px; line-height: 1.55; color: #5A5E6B">'
            f'{who} <b style="color: #0B0C11">{state["left"]:,}</b> of {total:,} left.</span>'
            '</div>')


def _plan_strip() -> str:
    """The product pages' plan strip: the four plans, compact."""
    import feature_gates as fg
    import pricing_config
    plans = fg.CHURCH_PLANS
    prices = pricing_config.church_price_cents()
    credits = pricing_config.church_credits()
    lim = fg.plan_limits()
    out = []
    for i, plan in enumerate(plans):
        lp = lim[plan]
        items = (_people(plan), _count(lp["max_seats"], "office login"), _count(lp["texts_monthly"], "text") + " a month",
                 f"{credits[plan]:,} AI actions a month", _clips(lp["clip_hours_monthly"]))
        lis = "\n".join(f"<li>{_TICK}{x}</li>" for x in items)
        out.append(f'<div class="plan{" mid" if i == 1 else ""}"><span class="pn">{escape(_name(plan))}</span>'
                   f'<span class="pp">${_dollars(prices[plan])} <small>a month</small></span><ul>\n{lis}\n</ul></div>')
    return '<div class="planrow four">\n' + "\n".join(out) + "\n</div>"


# The picker's slider, 0 to 1,000: one even stretch per plan, the last one stopping short so the
# top of the track is the church past the largest plan. Its colours are the four cards' rooms.
_PICK_COLOURS = ("#14B8A6", "#22C55E", "#3B82F6", "#EC4899")
_PICK_START = 160          # the size the picker opens on: a Growing church


def _picker_data() -> Dict[str, object]:
    """What the size picker draws, from the dials the cards read: each plan's
    people band, its price a month and a year, and what it holds (the same
    lines as the cards: logins, texts, messages to Chief, sermon clips). Past
    the largest band is Multi-site, priced from church_offer()."""
    import feature_gates as fg
    import marketing_pages as mp
    import pricing_config
    plans = fg.CHURCH_PLANS
    prices = pricing_config.church_price_cents()
    credits = pricing_config.church_credits()
    bands = pricing_config.church_size_bands()
    lim = fg.plan_limits()
    per_turn = pricing_config.credits_per_message()
    top = max(h for (_low, h) in bands.values() if h is not None)
    n = len(plans)
    stops = [round(i * 1000 / n) for i in range(n)] + [980]
    out, seg, marks = [], [], []
    for i, plan in enumerate(plans):
        low, high = bands[plan]
        high = high if high is not None else top
        lp = lim[plan]
        conv = f"{mp._about(credits[plan] // per_turn):,}"
        out.append({
            "name": _name(plan), "short": _short(plan), "max": high,
            "m": f"${_dollars(prices[plan])}", "y": f"${_dollars(prices[plan] * mp.ANNUAL_MONTHS)}",
            "col": _PICK_COLOURS[min(i, len(_PICK_COLOURS) - 1)],
            "items": [_count(lp["max_seats"], "office login"), _count(lp["texts_monthly"], "text") + " a month",
                      f"About {conv} messages to Chief", _clips(lp["clip_hours_monthly"])],
        })
        seg.append([stops[i], stops[i + 1], max(20, low) if i == 0 else low, high])
        marks.append(f"Up to {high:,}" if not low else f"{low:,} to {high:,}")
    o = pricing_config.church_offer()
    multi = {"name": "Multi-site", "price": f"From ${_dollars(o['multi_site_from_cents'])}", "per": "a month",
             "items": [f"Over {top:,} people, or more than one campus", "Talk to us: info@mysolutionist.app"]}
    return {"plans": out, "seg": seg, "top": top, "multi": multi, "marks": marks}


def _picker() -> str:
    """How many on a Sunday: drag the number, the sanctuary fills seat by
    seat, and the matching card below lights up. The page opens on a Growing
    church; the script takes it from there with the same numbers."""
    import json
    d = _picker_data()
    start = next((p for p in d["plans"] if _PICK_START <= p["max"]), d["plans"][-1])
    marks = "".join(f"<span>{escape(m)}</span>" for m in d["marks"])
    items = "".join(f"<li>{escape(x)}</li>" for x in start["items"])
    data = json.dumps({k: d[k] for k in ("plans", "seg", "top", "multi")}).replace("</", "<\\/")
    return (
        '<div style="position: relative; display: flex; flex-direction: column; gap: 14px">\n'
        '<div class="pk" id="picker">\n<div class="pk-l">\n'
        '<label for="pk-range">How many on a Sunday?</label>\n'
        f'<div class="pk-num"><output id="pk-out" for="pk-range">{_PICK_START}</output><span id="pk-unit">people</span></div>\n'
        '<input type="range" id="pk-range" min="0" max="1000" step="1" value="380" aria-describedby="pk-plan">\n'
        f'<div class="pk-marks" aria-hidden="true">{marks}</div>\n'
        '<div class="pk-plan" id="pk-plan" aria-live="polite">\n'
        f'<div class="top"><span class="nm" id="pk-name">{escape(start["name"])}</span>'
        f'<span class="pr"><b id="pk-price">{escape(start["m"])}</b><span id="pk-per">a month</span></span></div>\n'
        f'<ul id="pk-list">{items}</ul>\n'
        f'<a id="pk-go" href="{{{{HOME}}}}/start">Start free</a>\n'
        '</div>\n</div>\n<div class="pk-room">\n'
        '<canvas id="pk-canvas" aria-label="A sanctuary drawn as seats. Lit seats are your people on a Sunday; '
        'the room is the size of your plan."></canvas>\n'
        f'<div class="pk-cap"><span id="pk-cap"><b>{escape(start["name"])}</b> · room for {start["max"]:,}</span>'
        '<span>One dot is one person</span></div>\n'
        '</div>\n</div>\n'
        f'<script type="application/json" id="pk-data">{data}</script>\n'
        '</div>')


def _move_tokens() -> Dict[str, str]:
    """The move's offer, in the moving-over section's words, from
    pricing_config.church_offer(): how many churches move free (one glass
    pane each, up to five) and what the move costs after them. The price the
    first churches keep is said under the cards (_founding_line), since
    2026-11-13 for the first ten that pay, not the five that move free."""
    import pricing_config
    o = pricing_config.church_offer()
    months, moves = o["move_months"], o["founding_moves"]
    cost = f"{_words(months)} month{'' if months == 1 else 's'} of your plan, paid once"
    if moves and months:
        free = "The first church moves free." if moves == 1 else f"The first {_words(moves)} churches move free."
        after = f"After that, the move is {cost}. Either way, people do it with you."
    elif months:
        free, after = f"The move is {cost}.", "People do it with you, by hand."
    else:
        free, after = "Moving over is free.", "People do it with you, by hand."
    return {"MOVE_FREE": free, "MOVE_AFTER": after, "MOVE_PANES": "<i></i>" * min(moves, 5)}


def _by_size() -> Dict[str, str]:
    """Every section's words once the church plans are on sale. The prose
    that says 'every plan' is held to feature_gates by the tests."""
    import feature_gates as fg
    import marketing_pages as mp
    import pricing_config
    plans = fg.CHURCH_PLANS
    lim = fg.plan_limits()
    credits = pricing_config.church_credits()
    per_turn = pricing_config.credits_per_message()
    conv = [f"{mp._about(credits[p] // per_turn):,} on {_short(p)}" for p in plans]
    conv[0] = conv[0].replace(" on ", " messages a month on ", 1)
    logins = [f"{lim[p]['max_seats']:,} on {_short(p)}" for p in plans]
    logins[0] = logins[0].replace(" on ", " office logins on ", 1)
    funds = _on("vertical_ledgers")
    accountant = _on("accountant_collaborator")
    return {
        # overview: the hero and the size picker say "by size" only while the plans by size are on sale
        "HERO_KICK": "For churches, priced by the size of your Sunday",
        "PROOF_SIZE": "Priced by your size",
        "PICKER": _picker(),
        "PRICING_H2": 'Priced by <b style="font-weight: 600">your church\'s size.</b>',
        "PRICING_LEDE": ("People, Giving, Kids, Groups, your app and your site come with every plan. Your plan is set "
                         "by how many people come on a Sunday, and it sets the room: office logins, texts, Chief's "
                         "work and sermon clips, and from Established up, an audit trail, a seat for your accountant "
                         "and hands-off marketing. "
                         "Leaders, volunteers and members use the member app free, on every plan."),
        "PLAN_CARDS": _plan_cards(),
        "FOUNDER": _offer_line() + _founding_line(),
        "CONV_LINE": _and(conv),
        # the product pages
        "PLAN_STRIP": _plan_strip(),
        "FUNDS_LEDE": ("Givers pick the fund, and each gift stays counted in it, on every plan. Restricted gifts "
                       "post to Restricted Contributions, apart from General." if funds == "every plan" else
                       f"Givers pick the fund on every plan, and each gift stays counted in it. On {funds}, "
                       "restricted gifts post to Restricted Contributions, apart from General."),
        "FUNDS_CLOSE": f"Month-end and year-end close on {_on('period_close')}",
        "PREP_990": f"990 prep on {_on('vertical_reports')}",
        "BUDGET_PLAN": f"Budget against actual on {_on('reports_full')}",
        "CLOSE_PLAN": f"On {_on('period_close')}",
        "SORTING_PLAN": f"On {_on('chief_bookkeeping')}",
        "VISITORS_PLAN": f"On {_on('site_concierge')}",
        "LOGINS_LINE": _and(logins),
        "ACCOUNTANT_PLAN": f"A seat for your accountant on {accountant}",
        "BOOKS_PLANS_LEDE": ("Every church sees its own full ledger, closes its months and has Chief sort the bank "
                             f"rows, on every plan. {accountant} add an audit trail and a seat for your accountant."),
        "SITE_PLANS_LEDE": ("The site, sermons and events, Chief's help with visitors and posts, and sermon clips are "
                            "on every plan. A bigger church gets more hours of clips and more of Chief's work."),
        "APP_PLANS_LEDE": ("Every tab, every space and every alert is on every plan, for every member you have, and "
                           "sign-in codes are texted from your church's own number. The plans change how many people "
                           "sign in at the office and how many texts go out each month."),
    }


def _sections(page: str) -> str:
    """The public ladder's words, or the church plans by size in their place."""
    by_size = _by_size() if plans_by_size() else None
    if by_size is None:
        return _SECTION.sub(lambda m: m.group(2), page)
    return _SECTION.sub(lambda m: by_size.get(m.group(1), m.group(2)), page)


def render(slug: str) -> str:
    """One page of the church section, every token filled."""
    import marketing_home_v2 as v2
    import marketing_pages as mp
    meta = PAGES[slug]
    page = _sections(_read(meta["file"]))
    partner = (os.environ.get("CHURCHSAVVY_URL") or "").strip()
    if not partner.startswith("https://"):
        page = _CHURCHSAVVY_LINK.sub("", page)
    home = is_home()
    if home and slug:
        page = _ALL_OF_SOLUTIONIST.sub(lambda m: '<a href="{{HOME}}' + BUSINESS_PATH + '"' + m.group(1), page)
    tokens = {
        "TITLE": escape(meta["title"]),
        "DESCRIPTION": escape(meta["description"]),
        # the overview is the home page while is_home(): one address for search, wherever it's served
        "URL": ORIGIN + ("/" if home and not slug else path_of(slug)),
        # the main site, always by its own address: these pages may one day
        # be served from a church's own domain, where "/" is not Solutionist
        "HOME": ORIGIN,
        "APP_URL": mp.APP_URL,
        "CHURCHSAVVY_URL": escape(partner),
        "CHURCH_CSS": _read("church.css"),
        **_plan_tokens(),
        **_trial_tokens(),
    }
    if "{{FOUNDER_STRIP}}" in page:
        tokens["FOUNDER_STRIP"] = _founder_strip()
    if "{{OVERVIEW_CSS}}" in page:
        tokens["OVERVIEW_CSS"] = _read("overview.css")
        tokens["OVERVIEW_JS"] = _read("overview.js")
        # the edit is one layer on top, and only its two root classes switch it on: HOME_EDIT=off sends neither
        edit = home_edit()
        tokens["EDIT_ATTR"] = ' class="ep ep-prod"' if edit else ""
        tokens["EDIT_STYLE"] = "<style>\n" + _read("overview_edit.css") + "\n</style>" if edit else ""
        tokens["EDIT_SCRIPT"] = "<script>\n" + _read("overview_edit.js") + "\n</script>" if edit else ""
    if "{{LIT_CSS}}" in page:
        # a lit room: the shared kit, then the room's own parts beside its template (giving.css, giving.js)
        room = meta["file"].rsplit(".", 1)[0]
        tokens.update(LIT_CSS=_read("lit.css"), LIT_JS=_read("lit.js"),
                      ROOM_CSS=_read(room + ".css"), ROOM_JS=_read(room + ".js"))
    if "{{MOVE_FREE}}" in page:
        tokens.update(_move_tokens())
    tokens["PIXEL"] = mp._pixel_script()
    tokens["ANALYTICS"] = v2._analytics_scripts()
    page = _TOKEN.sub(lambda m: tokens.get(m.group(0)[2:-2], m.group(0)), page)
    # Every Start button here says it is a church (/start?for=church), so the
    # app's signup, Chief's welcome and the setup speak church and Ministry /
    # Church starts picked (the app's lib/signupKind). Before 2026-11-05 a
    # pastor who pressed Start was asked to set up a business.
    return page.replace(f'href="{ORIGIN}/start"', f'href="{ORIGIN}{START_PATH}"')
