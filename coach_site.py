"""
coach_site.py — the coaches and consultants section of the public site:
/coaches and its seven product pages.

Kevin, 2026-10-23, after the church section shipped (church_site.py,
#1565/#1566): "now do the same for the coaches and consultants page
upgrade those". The same Stained Glass Light concept: each part of a
practice gets a glass tile and a colour of its own, that colour lights its
whole page, Chief is the character doing that room's real job, and the
devices are drawn in HTML and stand still. Every product claim on the
pages was checked against the modules that back it before it was drawn.

The pages are the coach canvas's own markup, converted once into
coach_site/*.html. The numbers that must match the product (prices,
yearly prices, monthly AI actions, the meter widths, the trial and card
wording, the founding seat) are {{TOKENS}} filled by church_site's
helpers, which read the same dials the main site does.

On unless COACH_SITE=off, which is the rollback: /coaches and
/consultants go back to marketing_home_v3's coaches edition and the
product paths fall through to the catch-all as before.
"""
from __future__ import annotations

import functools
import os
import pathlib
import re
from html import escape
from typing import Dict

DIR = pathlib.Path(__file__).resolve().parent / "coach_site"
ORIGIN = "https://mysolutionist.app"

# slug -> the template and its <head>. "" is the overview at /coaches.
PAGES: Dict[str, Dict[str, str]] = {
    "": {
        "file": "overview.html",
        "title": "Solutionist for Coaches and Consultants · The Solutionist System",
        "description": ("Bookings, clients, proposals, invoices, classes and your marketing in one system, "
                        "with Chief keeping it moving between sessions. Month to month, paid straight to "
                        "your own Stripe."),
    },
    "bookings": {
        "file": "bookings.html",
        "title": "Bookings · Solutionist for Coaches and Consultants",
        "description": ("Your own booking page, the hours you choose to open, standing weekly sessions, "
                        "and confirmations that go out on their own."),
    },
    "clients": {
        "file": "clients.html",
        "title": "Clients · Solutionist for Coaches and Consultants",
        "description": ("One record per client with every session, note, proposal and payment, and a "
                        "brief from Chief before every session."),
    },
    "proposals-and-contracts": {
        "file": "proposals-and-contracts.html",
        "title": "Proposals and Contracts · Solutionist for Coaches and Consultants",
        "description": ("Program outlines and scopes of work drafted in your own voice, sent from the "
                        "client's record, and followed up when they go quiet."),
    },
    "billing-and-time": {
        "file": "billing-and-time.html",
        "title": "Billing and Time · Solutionist for Coaches and Consultants",
        "description": ("Invoices with a pay link on your own Stripe account, the hours you haven't billed "
                        "yet, and reminders Chief drafts when a payment runs late."),
    },
    "courses-and-classes": {
        "file": "courses-and-classes.html",
        "title": "Courses and Classes · Solutionist for Coaches and Consultants",
        "description": ("Courses and live classes for your clients, with recordings for anyone who missed "
                        "one and the work they turn in coming back to you."),
    },
    "marketing-and-website": {
        "file": "marketing-and-website.html",
        "title": "Marketing and Website · Solutionist for Coaches and Consultants",
        "description": ("Your website on your own address, posts Chief drafts in your voice for you to "
                        "approve, and email to the people on your list."),
    },
    "office-and-books": {
        "file": "office-and-books.html",
        "title": "Office and Books · Solutionist for Coaches and Consultants",
        "description": ("Your books on the same system as your invoices, with every payment already in "
                        "them, and the month-end close and 1099s when you want them."),
    },
}
PRODUCTS = tuple(s for s in PAGES if s)

_TOKEN = re.compile(r"\{\{[A-Z_]+\}\}")


def enabled() -> bool:
    return (os.environ.get("COACH_SITE") or "on").strip().lower() not in ("off", "0", "false", "no")


def path_of(slug: str) -> str:
    return "/coaches" + (f"/{slug}" if slug else "")


@functools.lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def render(slug: str) -> str:
    """One page of the coaches section, every token filled."""
    import church_site
    import marketing_home_v2 as v2
    import marketing_pages as mp
    meta = PAGES[slug]
    page = _read(meta["file"])
    tokens = {
        "TITLE": escape(meta["title"]),
        "DESCRIPTION": escape(meta["description"]),
        "URL": ORIGIN + path_of(slug),
        "HOME": ORIGIN,     # the main site by its own address, whatever domain serves this page
        "APP_URL": mp.APP_URL,
        "COACH_CSS": _read("coach.css"),
        **church_site._plan_tokens(),
        **church_site._trial_tokens(),
    }
    if "{{FOUNDER_STRIP}}" in page:
        tokens["FOUNDER_STRIP"] = church_site._founder_strip()
    tokens["PIXEL"] = mp._pixel_script()
    tokens["ANALYTICS"] = v2._analytics_scripts()
    return _TOKEN.sub(lambda m: tokens.get(m.group(0)[2:-2], m.group(0)), page)
