"""site_layouts.py — THE LAYOUT LIBRARY (2026-10-03, the hand-build plan).

Kevin, 2026-10-03: "give it all 12 layouts to choose from." (2026-10-04,
"grow the builder's own layout and object library": two more, bulletin and
booking, the structures I built by hand for the church and the salon.) The new
builder had no layout menu: every business got the Director's one DENSITY
SKELETON (nav, full-viewport hero, band, services grid, strip, portfolio,
steps, about, contact, footer), so the look changed and the skeleton never
did. A site built by hand starts the other way round: look at what the
business has and how people buy from it, decide the page's structure, say
why, then build that structure on purpose.

This module is that decision, in code:
- LAYOUTS: fourteen layouts, each with when it fits, what it needs, its page
  skeleton (the Director's section order), its structure (the builder's
  recipe) and its phone plan.
- signals(ctx): what the business actually has, read from the gathered
  context (photos, offerings, the story the Coach heard, proof, trade).
- rank(sig): a RUBRIC, not a lookup table. Every layout scores itself
  against the signals with plain-language reasons, so a trade nobody
  listed still lands somewhere sensible. Material weighs most: a photo
  layout with no photos is what left the first test site's room section
  empty.

Pure, fail-open, no model calls. The Coach shows the top three as cards,
the Director writes the pick into the blueprint's concept sheet
("LAYOUT: editorial — ..."), and the builder builds to its recipe.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("site_layouts")

Signals = Dict[str, Any]
Points = List[Tuple[int, str]]


# ─── the trades ───────────────────────────────────────────────────────
# Work people judge with their eyes before they buy. Kept as a short
# rubric signal (it nudges, it never decides alone).
_VISUAL_TRADE_RE = re.compile(
    r"hair|barber|salon|braid|loc(s|tician)\b|nail|lash|brow|makeup|beauty|"
    r"tattoo|piercing|photo|film|video|design|art\b|artist|gallery|illustrat|"
    r"bake|bakery|cafe|coffee|restaurant|food|chef|cater|florist|flower|"
    r"wedding|fashion|boutique|apparel|jewel|interior|architect|landscap|"
    r"furniture|ceramic|pottery|craft|detail(ing)?\b|tailor",
    re.IGNORECASE)
# Places people come to: the room itself is the pitch.
_PLACE_TRADE_RE = re.compile(
    r"restaurant|cafe|coffee|bar\b|brewer|winery|venue|event space|hotel|inn\b|"
    r"resort|spa\b|gym|studio|church|ministr|camp|museum|theat|club",
    re.IGNORECASE)
# People come at set times: the weekly times are the first thing they need.
_GATHERING_TRADE_RE = re.compile(
    r"church|ministr|worship|chapel|parish|congregation|temple|mosque|synagogue|"
    r"gym|fitness|yoga|pilates|barre|dance|martial|karate|jiu|boxing|crossfit|"
    r"choir|league|camp\b|recovery|support group|bible study|meetup|swim",
    re.IGNORECASE)
# People book a time before they come: the visit is planned, then booked.
_APPOINTMENT_TRADE_RE = re.compile(
    r"hair|barber|salon|braid|loc(s|tician)\b|nail|lash|brow|makeup|beauty|wax|"
    r"spa\b|massage|esthetic|facial|skin|tattoo|piercing|groom|detail(ing)?\b|"
    r"chiro|physio|acupunct|dental|dentist|clinic|therap|counsel|tutor|lesson|"
    r"personal train|photo session|portrait session",
    re.IGNORECASE)
# A clock time in what the owner said: "9am", "10:30 a.m.", "17:00".
_CLOCK_RE = re.compile(
    r"\b((?:[01]?\d|2[0-3])(?::[0-5]\d)?)\s*(a\.?m\.?|p\.?m\.?)(?![a-z])|\b((?:[01]?\d|2[0-3]):[0-5]\d)\b",
    re.IGNORECASE)
_IDEA_WORDS = {
    "story": re.compile(r"book|chapter|journal|diary|letter|story|stor(y|ies)|"
                        r"journey|road|path|season|margin|notebook|novel", re.I),
    "editorial": re.compile(r"book|letter|essay|column|journal|page|margin|"
                            r"notebook|newspaper|paper", re.I),
    "showcase": re.compile(r"gallery|exhibit|museum|wall|frame|portfolio|"
                           r"lookbook|collection", re.I),
    "fullscreen": re.compile(r"light|room|view|window|arriv|place|horizon|"
                             r"stage|landscape", re.I),
    "grid": re.compile(r"menu|board|catalog|shelf|shelves|counter|price list", re.I),
    "sidebar": re.compile(r"index|directory|menu|catalog|table of contents", re.I),
    "statement": re.compile(r"manifesto|sign|poster|banner|declar|promise", re.I),
    "bulletin": re.compile(r"bulletin|calendar|schedule|timetable|noticeboard|sunday", re.I),
    "booking": re.compile(r"appointment|chair|booking|reservation|planner", re.I),
}


def _leaf(v: Any) -> str:
    if isinstance(v, dict):
        v = v.get("value")
    return str(v or "").strip()


def _has(v: Any) -> bool:
    return bool(_leaf(v)) or (isinstance(v, list) and bool(v))


# ─── the twelve ───────────────────────────────────────────────────────
#
# Each layout's fit() returns (points, reason) pairs. Positive reasons are
# what the card says ("your story carries the site"); negative ones keep a
# layout off the shortlist when the material cannot carry it.

def _fit_split(s: Signals) -> Points:
    p: Points = []
    if s["photos"] >= 1:
        p.append((3, "one strong photo can hold the other half of the screen"))
    else:
        p.append((-4, "there is no photo yet for the picture side"))
    if s["action"] in ("call", "book"):
        p.append((2, "a split page leads straight to one call or booking"))
    if s["calm_trade"]:
        p.append((2, "it reads calm and clear, which your field needs"))
    if s["photos"] >= 6:
        p.append((-1, "with this many photos, the work deserves more room"))
    if s["place_trade"] and s["photos"] >= 3:
        p.append((-1, "the place itself deserves the whole screen"))
    return p


def _fit_editorial(s: Signals) -> Points:
    p: Points = []
    if s["story_beats"] >= 3:
        p.append((3, "your story carries the site"))
    if s["photos"] <= 2:
        p.append((2, "it needs no photos to look finished"))
    if s["action"] in ("call", "book"):
        p.append((2, "it reads like a conversation that ends in one call"))
    if s["calm_trade"]:
        p.append((2, "it is quiet and trustworthy, which your field needs"))
    if _IDEA_WORDS["editorial"].search(s["idea"]):
        p.append((2, "it matches the idea of the site"))
    if s["offerings"] >= 8:
        p.append((-2, "a long menu gets lost inside an essay"))
    if s["visual_trade"] and s["photos"] >= 6:
        p.append((-1, "your work should be seen before it is described"))
    if s["story_beats"] <= 1:
        p.append((-2, "there is not much story yet to read"))
    return p


def _fit_fullscreen(s: Signals) -> Points:
    p: Points = []
    if s["photos"] >= 3 and s["place_trade"]:
        p.append((5, "one great photo of the place can carry the first screen"))
    elif s["photos"] >= 3 and s["visual_trade"]:
        p.append((3, "one great photo of the work can carry the first screen"))
    elif s["photos"] >= 3:
        p.append((1, "there are photos strong enough to open on"))
    if s["photos"] == 0:
        p.append((-6, "it needs one great wide photo, and there are none yet"))
    elif s["photos"] < 3:
        p.append((-2, "it needs a choice of wide photos to open on"))
    if _IDEA_WORDS["fullscreen"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


def _fit_statement(s: Signals) -> Points:
    p: Points = []
    if s["photos"] == 0:
        p.append((4, "the words do the work, so no photos are needed"))
    elif s["photos"] <= 2:
        p.append((1, "type can lead while photos are still coming"))
    if s["idea"]:
        p.append((2, "a sharp idea is strong enough to set at full size"))
    if 1 <= s["offerings"] <= 2:
        p.append((2, "one offer suits one big message"))
    if s["action"]:
        p.append((1, "one message leads to one action"))
    if s["story_beats"] >= 5:
        p.append((-2, "a rich story needs more room than a statement gives"))
    if s["calm_trade"]:
        p.append((-1, "a huge statement can feel loud for your field"))
    if _IDEA_WORDS["statement"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


def _fit_grid(s: Signals) -> Points:
    p: Points = []
    items = max(s["offerings"], s["store_items"])
    if items >= 4:
        what = "products" if s["store_items"] >= s["offerings"] else "offerings"
        p.append((4, f"your {items} {what} each get their own tile"))
    elif items < 3:
        p.append((-3, "there are not enough items yet to fill a grid"))
    if s["retail"]:
        p.append((2, "people browse what you sell"))
    if s["action"] == "buy":
        p.append((1, "a grid gets people to the thing they want to buy"))
    if s["photos"] >= 4:
        p.append((1, "there are photos for the tiles"))
    if _IDEA_WORDS["grid"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


def _fit_magazine(s: Signals) -> Points:
    p: Points = []
    if s["story_beats"] >= 4 and s["photos"] >= 4:
        p.append((3, "several stories and photos can run side by side"))
    if s["offerings"] >= 3 and s["proof"] >= 2:
        p.append((2, "there is enough news, offers and proof to fill the columns"))
    if s["offerings"] >= 4 and s["story_beats"] >= 3:
        p.append((2, "many programs with a story behind them read like departments"))
    if s["photos"] < 3:
        p.append((-5, "a magazine needs at least a few photos to work"))
    if s["calm_trade"]:
        p.append((-2, "it can feel busy for your field"))
    return p


def _fit_bento(s: Signals) -> Points:
    p: Points = []
    facts = s["proof"] + s["offerings"]
    if facts >= 5:
        p.append((3, "you have many facts and features to show at once"))
    elif facts < 4:
        p.append((-3, "there are not enough facts yet to fill the boxes"))
    if s["photos"] >= 2:
        p.append((1, "photos can fill a few of the boxes"))
    return p


def _fit_showcase(s: Signals) -> Points:
    p: Points = []
    if s["photos"] >= 6:
        p.append((5 if s["visual_trade"] else 3, f"your {s['photos']} photos can lead the page"))
    elif s["photos"] < 4:
        p.append((-8, "it needs at least six strong photos"))
    if s["visual_trade"]:
        p.append((3, "people judge your work with their eyes first"))
    if _IDEA_WORDS["showcase"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


def _fit_story(s: Signals) -> Points:
    p: Points = []
    if s["story_beats"] >= 4:
        p.append((4, "your story has enough beats to unfold chapter by chapter"))
    elif s["story_beats"] < 3:
        p.append((-2, "the story needs a few more beats first"))
    if _IDEA_WORDS["story"].search(s["idea"]):
        p.append((2, "it matches the idea of the site"))
    if s["proof"] >= 1:
        p.append((1, "real proof can close the story"))
    return p


def _fit_asymmetric(s: Signals) -> Points:
    p: Points = []
    if s["calm_trade"]:
        p.append((-10, "overlapping pieces do not fit health, legal or money work"))
    if s["visual_trade"] and s["photos"] >= 3:
        p.append((3, "photos with character can overlap and break the grid"))
    if s["photos"] < 3:
        p.append((-4, "it needs at least three photos with character"))
    return p


def _fit_sidebar(s: Signals) -> Points:
    p: Points = []
    if s["offerings"] >= 10:
        p.append((3, "a long menu is easier to move through from the side"))
    if s["retail"] and s["store_items"] >= 10:
        p.append((2, "a big catalog needs steady navigation"))
    if s["offerings"] < 6 and s["store_items"] < 6:
        p.append((-4, "there is too little to navigate"))
    if _IDEA_WORDS["sidebar"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


def _fit_minimal(s: Signals) -> Points:
    p: Points = []
    if s["story_beats"] <= 1 and s["offerings"] <= 2 and s["photos"] <= 1:
        p.append((4, "it looks finished with very little on file"))
    if s["calm_trade"]:
        p.append((2, "calm and clear suits your field"))
    if s["action"]:
        p.append((1, "nothing stands between a visitor and the one action"))
    if s["story_beats"] >= 4:
        p.append((-2, "it would waste a story this rich"))
    return p


def _fit_bulletin(s: Signals) -> Points:
    p: Points = []
    if s["gathering_trade"]:
        p.append((3, "people come at set times, so the times come first"))
        if s["times"] >= 2:
            p.append((3, "your weekly times are on file to lead the page"))
        elif s["times"] == 0:
            p.append((-1, "the weekly times are not on file yet"))
        if s["offerings"] >= 3:
            p.append((1, "your programs read like a weekly bulletin"))
    else:
        p.append((-4, "people do not gather at set times here"))
    if s["events"]:
        p.append((1, "what is coming up has its own place"))
    if _IDEA_WORDS["bulletin"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


def _fit_booking(s: Signals) -> Points:
    p: Points = []
    if s["action"] == "book":
        p.append((3, "people come to book, so booking runs down the page"))
    if s["booking_live"]:
        p.append((2, "your booking page is live, so every service books in one tap"))
    elif s["action"] == "book":
        p.append((-1, "booking is not switched on yet (Chief can set it up)"))
    else:
        p.append((-4, "visitors do not book with you online"))
    if s["timed_offers"] >= 3:
        p.append((2, "each service has its price and length to plan by"))
    elif s["offerings"] < 2:
        p.append((-3, "there are not enough services to plan a visit around"))
    if s["appointment_trade"]:
        p.append((2, "your clients plan their visit before they come"))
    if s["visual_trade"] and s["photos"] >= 6:
        p.append((-2, "with this many photos, the work should lead"))
    if _IDEA_WORDS["booking"].search(s["idea"]):
        p.append((1, "it matches the idea of the site"))
    return p


LAYOUTS: Dict[str, Dict[str, Any]] = {
    "split": {
        "name": "Split", "line": "Words on one side, a picture on the other.",
        "best_for": "Most service businesses with one strong photo",
        "needs": "1 good portrait or work photo",
        "skeleton": "split hero (promise one side, the photo the other) → what you offer → "
                    "an about band that mirrors the hero → proof → how to start → contact → footer. "
                    "6 to 8 sections.",
        "structure": "The hero is a two-column grid (about 55/45) with the headline, one line "
                     "and the action on one side and the photo, cover-fit and full column "
                     "height, on the other. Later bands alternate the photo side or go full "
                     "width; at least one more two-column band repeats the split.",
        "phone": "Every split stacks: headline and action first, then the photo at full width.",
        "fit": _fit_split,
    },
    "editorial": {
        "name": "Editorial", "line": "One column that reads like a good article.",
        "best_for": "Coaches, consultants, writers, therapists",
        "needs": "A real story; photos optional",
        "skeleton": "a headline set large above the column → an opening paragraph → the "
                    "story in subheaded passages → a pull quote that breaks the column → "
                    "what you offer as a typeset list inside the text → how to start → "
                    "contact as a reply at the end → footer. 6 to 9 sections.",
        "structure": "One reading column, 60 to 72ch wide, on a quiet ground. No card grids. "
                     "Pull quotes and figures may break out wider (up to about 900px); "
                     "everything else holds the column. Offerings read as typeset lines "
                     "(name, price, duration), not tiles.",
        "phone": "The same column at full width with 18px body text; pull quotes span the screen.",
        "fit": _fit_editorial,
    },
    "fullscreen": {
        "name": "Full-screen", "line": "One big image or video, the message on top, calm below.",
        "best_for": "Restaurants, venues, events, places",
        "needs": "1 great wide photo",
        "skeleton": "a full-viewport photo hero with the message over it → a calm intro → "
                    "what you offer → the place or the experience → proof → visit or "
                    "contact → footer. 5 to 8 sections.",
        "structure": "The first section is at least 90vh, a real photo cover-fit across the "
                     "whole screen with a scrim so the headline reads. Everything after it is "
                     "quieter: contained bands that let the opening do the talking.",
        "phone": "The hero stays tall (about 85vh) with the headline anchored low over the photo.",
        "fit": _fit_fullscreen,
    },
    "statement": {
        "name": "Statement", "line": "Huge type, no image. The words are the design.",
        "best_for": "One message, one offer, a manifesto",
        "needs": "A sharp one-liner; no photos needed",
        "skeleton": "the statement at monumental size → one line of support and the action "
                    "→ what you offer → proof → contact → footer. 4 to 7 sections.",
        "structure": "The hero headline is display type at 7 to 11vw (clamped), tight "
                     "tracking, filling the first screen with no photo. Later sections keep "
                     "large type and generous space; type and the signature motif carry the "
                     "page.",
        "phone": "The headline scales down but still owns the first screen.",
        "fit": _fit_statement,
    },
    "grid": {
        "name": "Grid", "line": "Tiles of services, products, or work.",
        "best_for": "Menus, shops, salons with many services",
        "needs": "4 or more offerings or items",
        "skeleton": "a compact hero → the grid of offerings (every one a tile with price) → "
                    "featured work or a highlight → proof → contact → footer. 5 to 8 sections.",
        "structure": "The heart of the page is a real grid (3 or 4 columns at desktop) of "
                     "same-shape tiles, each with its name, price and duration, and a photo "
                     "when one exists. The hero stays compact so the grid starts in the "
                     "first scroll.",
        "phone": "Tiles drop to one or two columns and keep price visible without tapping.",
        "fit": _fit_grid,
    },
    "magazine": {
        "name": "Magazine", "line": "A lead story with smaller stories beside it.",
        "best_for": "Churches with many ministries, busy venues",
        "needs": "Several stories and 4 or more photos",
        "skeleton": "a front page (lead story large, two or three smaller stories beside it) → "
                    "sections that read as departments → offerings → proof → contact → "
                    "footer. 6 to 10 sections.",
        "structure": "Multi-column bands of mixed sizes: a lead block spanning about two "
                     "thirds with smaller blocks beside it, headlines of different weights, "
                     "photos at different sizes. Departments get their own running heads.",
        "phone": "One column in a clear story order: the lead story first, then the rest.",
        "fit": _fit_magazine,
    },
    "bento": {
        "name": "Bento", "line": "Boxes of different sizes fitted together.",
        "best_for": "Many features, stats, or facts to show at once",
        "needs": "5 or more distinct facts or features",
        "skeleton": "a hero → a bento board of facts, offers and proof in boxes of "
                    "different sizes → one deeper section → contact → footer. 4 to 7 sections.",
        "structure": "A CSS grid of at least six boxes with deliberately different spans "
                     "(one large, some wide, some small), each box holding one fact, offer, "
                     "stat, quote or photo. Boxes share radius and gap; sizes follow "
                     "importance.",
        "phone": "Boxes stack in order of importance, two small ones may share a row.",
        "fit": _fit_bento,
    },
    "showcase": {
        "name": "Showcase", "line": "Big images lead, words follow.",
        "best_for": "Hair, tattoo, food, photography, design",
        "needs": "6 or more strong photos",
        "skeleton": "the best photo large with a short line → the work in large frames → "
                    "what you offer with prices → the person behind the work → proof → "
                    "contact → footer. 6 to 9 sections.",
        "structure": "Photos take most of the page area: large frames at 45 to 100 percent "
                     "of the width, generous and uncropped where possible, opening larger on "
                     "click. Words are short captions and one or two quiet text bands.",
        "phone": "Full-width images one per row; captions sit under each.",
        "fit": _fit_showcase,
    },
    "story": {
        "name": "Long-scroll story", "line": "Chapters that unfold as you scroll.",
        "best_for": "Founders, coaches, nonprofits with a real story",
        "needs": "A story with at least 4 beats",
        "skeleton": "an opening line → chapter by chapter: the problem, the turn, the work, "
                    "the proof, the invitation → what you offer → contact → footer. "
                    "6 to 10 chapters.",
        "structure": "Each chapter is its own full-height band (at least 80vh at desktop) "
                     "with one idea, one image or motif, and a clear chapter marker. "
                     "Scroll-driven reveals pace the story; a thread or progress mark "
                     "connects the chapters.",
        "phone": "Each chapter fills the screen; markers stay visible as you scroll.",
        "fit": _fit_story,
    },
    "asymmetric": {
        "name": "Asymmetric", "line": "Pieces overlap and break the grid on purpose.",
        "best_for": "Art, fashion, youth, bold creative brands",
        "needs": "3 or more photos with character",
        "skeleton": "a collage hero → the work in overlapping arrangements → who you are → "
                    "what you offer → contact → footer. 5 to 8 sections.",
        "structure": "Photos and type overlap and offset deliberately (marked "
                     "data-overlap-ok): slight rotations, pieces crossing section edges, "
                     "type over image. Every overlap is planned and nothing a visitor reads "
                     "is hidden.",
        "phone": "A planned simpler stack: overlaps relax to clean offsets so nothing collides.",
        "fit": _fit_asymmetric,
    },
    "sidebar": {
        "name": "Sidebar", "line": "Navigation fixed down one side.",
        "best_for": "Long menus, catalogs, many sections",
        "needs": "Enough sections to be worth navigating",
        "skeleton": "a fixed side column (name, section links, the action) beside a "
                    "scrolling main column: intro → the menu or catalog in sections → "
                    "about → contact → footer. 6 to 12 sections.",
        "structure": "At desktop a sticky or fixed side column (about 240 to 300px) holds "
                     "the name, the section links (highlighting the current section) and "
                     "the action; the content scrolls in the remaining width.",
        "phone": "The side column becomes a top bar with a menu button; sections stay anchored.",
        "fit": _fit_sidebar,
    },
    "minimal": {
        "name": "Minimal", "line": "Three or four sections and a lot of space.",
        "best_for": "A new business with little on file, one offer",
        "needs": "Very little",
        "skeleton": "a calm hero with the promise and the action → what you offer → "
                    "contact → footer. 3 or 4 sections.",
        "structure": "Very few sections with wide margins and large type; one accent; no "
                     "decorative bands. Every element earns its place; space is the design.",
        "phone": "Natural fit; keep the space generous rather than shrinking it.",
        "fit": _fit_minimal,
    },
    # The church I built by hand (Rivers) opened on the times: a visitor's
    # first question is "when?", and the strip answered it under the hero.
    "bulletin": {
        "name": "Bulletin", "line": "The weekly times first, then what's on and how to join.",
        "best_for": "Churches, gyms, studios and classes that meet at set times",
        "needs": "Regular weekly times",
        "skeleton": "an opening with the weekly times right under it → what is coming up → "
                    "the programs or ministries, each with when it meets → what to expect on "
                    "a first visit → how to join or plan a visit → contact and directions → "
                    "footer. 6 to 9 sections.",
        "structure": "The weekly times sit inside the first screen or straight under it, in "
                     "one ruled row a visitor reads at a glance (the times-strip object fits; "
                     "it lights the next one). Every program below says when it meets. The "
                     "page runs in the order a newcomer asks: when, what, what is it like, "
                     "how do I come.",
        "phone": "The times strip becomes two columns right under the opening; the next one stays lit.",
        "fit": _fit_bulletin,
    },
    # The salon I built by hand (MaCnificent) ran on booking: pick a style,
    # see its time and price, book it, with the dock keeping Book in reach.
    "booking": {
        "name": "Booking desk", "line": "Every service ready to book, with booking down the middle.",
        "best_for": "Salons, barbers, spas and anything by appointment",
        "needs": "Live booking and services with a price and a length",
        "skeleton": "a compact opening with the book action → the services as a menu, each "
                    "with its price, its length and its own book link → how booking works "
                    "(the hours, any deposit or policy the data states, the book button) → "
                    "the person behind the work → proof → hours and contact → what to expect "
                    "after → footer. 6 to 9 sections.",
        "structure": "Booking is the spine. Every service carries its own book link to the "
                     "booking page; a booking band sits in the middle of the page with the "
                     "hours beside it (the hours-card object fits); on a phone the dock "
                     "object keeps Book one tap away. The opening stays compact so the menu "
                     "starts in the first scroll.",
        "phone": "Services become a one-column menu with price and length showing; the dock "
                 "carries Book once the opening scrolls away.",
        "fit": _fit_booking,
    },
}

KEYS: Tuple[str, ...] = tuple(LAYOUTS)

# The Coach's older hero-shape cards, read as a nudge toward page layouts.
_HERO_SHAPE_TO_LAYOUTS = {
    "split-stage": ("split",), "poster": ("fullscreen", "statement"),
    "editorial": ("editorial",), "exhibition": ("showcase",),
    "monument": ("statement",), "corridor": ("showcase", "fullscreen"),
    "letter": ("editorial", "minimal"),
}

_ALIASES = {
    "full-screen": "fullscreen", "full screen": "fullscreen", "fullscreen hero": "fullscreen",
    "long-scroll story": "story", "long scroll story": "story", "long-scroll": "story",
    "storytelling": "story", "single column": "editorial", "broken grid": "asymmetric",
    "cards": "grid", "modular": "bento", "portfolio": "showcase",
    "booking desk": "booking", "booking-led": "booking", "appointment": "booking",
    "times first": "bulletin", "schedule first": "bulletin", "weekly bulletin": "bulletin",
}


def normalize(key: Any) -> Optional[str]:
    """A layout key from anything a person or a model writes ('Long-scroll
    story — because...', 'EDITORIAL'), or None."""
    raw = str(key or "").strip().lower()
    if not raw:
        return None
    head = re.split(r"\s*(?:[—–:(]|\s-\s|\bbecause\b)", raw, maxsplit=1)[0].strip(" .\"'")
    if head in LAYOUTS:
        return head
    if head in _ALIASES:
        return _ALIASES[head]
    for k in LAYOUTS:
        if re.match(rf"{re.escape(k)}\b", head):
            return k
    for alias, k in _ALIASES.items():
        if head.startswith(alias):
            return k
    return None


# ─── the signals ──────────────────────────────────────────────────────

def _photo_count(ctx: Dict[str, Any]) -> int:
    urls = set()
    for g in (ctx.get("gallery") or []):
        if isinstance(g, dict) and str(g.get("url") or "").strip():
            urls.add(g["url"].strip())
    slots = (((ctx.get("site") or {}).get("site_config") or {}).get("slots") or {})
    if isinstance(slots, dict):
        for rec in slots.values():
            if isinstance(rec, dict) and not rec.get("removed") \
                    and str(rec.get("custom_url") or "").strip():
                urls.add(rec["custom_url"].strip())
    return len(urls)


def _story_beats(dossier: Dict[str, Any]) -> int:
    """How much story the owner has told: filled fields in the sections the
    Coach asks about (each answered question is one beat)."""
    n = 0
    for sec in ("story", "world", "signature"):
        block = dossier.get(sec)
        if isinstance(block, dict):
            n += sum(1 for v in block.values() if _has(v))
    one = ((dossier.get("identity") or {}).get("one_liner")) if isinstance(dossier.get("identity"), dict) else None
    if _has(one):
        n += 1
    return n


def _action(dossier: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    raw = _leaf(((dossier.get("identity") or {}) if isinstance(dossier.get("identity"), dict) else {})
                .get("primary_action")).lower()
    if re.search(r"\bcall\b|discovery|consult|talk|chat|conversation", raw):
        return "call"
    if re.search(r"\bbook|appointment|schedul|reserve", raw):
        return "book"
    if re.search(r"\bbuy|shop|order|purchase", raw):
        return "buy"
    if re.search(r"\bvisit|come in|stop by|join us|attend", raw):
        return "visit"
    if (ctx.get("booking") or {}).get("enabled"):
        return "book"
    return "call" if raw else ""


def signals(ctx: Dict[str, Any], recent: Optional[List[str]] = None) -> Signals:
    """What this business actually has, from the gathered context. Every
    read is defensive: a missing piece counts as nothing, never an error."""
    cfg = ((ctx.get("site") or {}).get("site_config") or {}) if isinstance(ctx.get("site"), dict) else {}
    dossier = cfg.get("discovery_dossier") if isinstance(cfg.get("discovery_dossier"), dict) else {}
    truth = dossier.get("truth") if isinstance(dossier.get("truth"), dict) else {}
    taste = dossier.get("taste") if isinstance(dossier.get("taste"), dict) else {}
    biz = ctx.get("business") or {}
    btype = " ".join(str(x) for x in (biz.get("type"), biz.get("business_type"),
                                       dossier.get("vertical")) if x)
    store = ctx.get("store") if isinstance(ctx.get("store"), dict) else {}
    store_items = len(store.get("items") or []) if isinstance(store.get("items"), list) else 0
    offerings = len(ctx.get("offerings") or [])
    stated = truth.get("offers") if isinstance(truth.get("offers"), list) else []
    offerings = max(offerings, len(stated))
    proof = len(ctx.get("testimonials") or []) + len(truth.get("proven_stats") or [])
    if _has(((dossier.get("story") or {}) if isinstance(dossier.get("story"), dict) else {}).get("proof")):
        proof += 1
    concept = ctx.get("concept") if isinstance(ctx.get("concept"), dict) else {}
    idea = " ".join(x for x in (_leaf(concept.get("idea")), _leaf(taste.get("concept_idea")),
                                _leaf(((dossier.get("signature") or {}) if isinstance(dossier.get("signature"), dict) else {}).get("moment")))
                    if x)
    try:
        import site_concept
        calm = bool(site_concept._PLAIN_TRADE_RE.search(btype))
    except Exception:
        calm = False
    hours = truth.get("hours")
    said = " ".join(_leaf(h) for h in hours) if isinstance(hours, list) else _leaf(hours)
    times = {(m.group(1) or m.group(3) or "") + (m.group(2) or "").lower().replace(".", "")
             for m in _CLOCK_RE.finditer(said)}
    rows = [o for o in (ctx.get("offerings") or []) if isinstance(o, dict)]
    timed = sum(1 for o in rows if any(o.get(k) for k in ("duration_min", "duration_minutes", "duration")))
    timed = max(timed, sum(1 for o in stated if isinstance(o, dict) and _leaf(o.get("duration"))))
    booking = ctx.get("booking") if isinstance(ctx.get("booking"), dict) else {}
    events = ctx.get("events_door") if isinstance(ctx.get("events_door"), dict) else {}
    return {
        "photos": _photo_count(ctx),
        "offerings": offerings,
        "store_items": store_items,
        "retail": bool(store.get("enabled")) and store_items > 0,
        "story_beats": _story_beats(dossier),
        "proof": proof,
        "calm_trade": calm,
        "visual_trade": bool(_VISUAL_TRADE_RE.search(btype)),
        "place_trade": bool(_PLACE_TRADE_RE.search(btype)),
        "action": _action(dossier, ctx),
        "gathering_trade": bool(_GATHERING_TRADE_RE.search(btype)),
        "appointment_trade": bool(_APPOINTMENT_TRADE_RE.search(btype)),
        "times": len(times),
        "timed_offers": timed,
        "booking_live": bool(booking.get("enabled")),
        "events": bool(events.get("enabled")),
        "idea": idea[:400],
        "owner_pick": normalize(_leaf(taste.get("layout"))),
        "hero_shape": _leaf(taste.get("hero_shape")).lower(),
        "recent": [k for k in (recent or []) if k in LAYOUTS],
    }


# ─── the rubric ───────────────────────────────────────────────────────

def score(key: str, sig: Signals) -> Tuple[int, List[str], List[str]]:
    """(score, reasons for, reasons against) for one layout."""
    pts = LAYOUTS[key]["fit"](sig)
    if key in _HERO_SHAPE_TO_LAYOUTS.get(sig.get("hero_shape") or "", ()):
        pts.append((2, "it matches the opening you picked with the Coach"))
    seen = sum(1 for k in (sig.get("recent") or [])[:6] if k == key)
    if seen:
        pts.append((-min(4, 2 * seen), "other sites used it recently"))
    total = sum(n for n, _ in pts)
    pro = [r for n, r in sorted(pts, key=lambda x: -x[0]) if n > 0]
    con = [r for n, r in sorted(pts, key=lambda x: x[0]) if n < 0]
    return total, pro, con


def rank(sig: Signals) -> List[Dict[str, Any]]:
    """Every layout, best fit first: {key, name, score, why, against,
    picked}. The owner's own pick always leads."""
    rows = []
    for key in LAYOUTS:
        total, pro, con = score(key, sig)
        picked = key == sig.get("owner_pick")
        rows.append({"key": key, "name": LAYOUTS[key]["name"], "score": total,
                     "why": pro[:3], "against": con[:2], "picked": picked})
    # stable: the owner's pick, then score, then the catalog's own order
    order = {k: i for i, k in enumerate(LAYOUTS)}
    rows.sort(key=lambda r: (not r["picked"], -r["score"], order[r["key"]]))
    return rows


def shortlist(sig: Signals, n: int = 3) -> List[Dict[str, Any]]:
    return rank(sig)[:n]


def reason_line(row: Dict[str, Any]) -> str:
    """One plain sentence for a card: 'Your story carries the site, and it
    needs no photos to look finished.'"""
    why = [w for w in (row.get("why") or []) if w][:2]
    if row.get("picked"):
        why = ["you picked it"] + why[:1]
    if not why:
        return LAYOUTS[row["key"]]["line"]
    s = why[0] if len(why) == 1 else f"{why[0]}, and {why[1]}"
    return s[0].upper() + s[1:] + "."


# ─── what the Director and the builder read ───────────────────────────

def catalog_block() -> str:
    """Every layout, one line each, for the Director."""
    lines = []
    for k, L in LAYOUTS.items():
        lines.append(f"- {k}: {L['name']}. {L['line']} Best for {L['best_for'].lower()}; "
                     f"needs {L['needs'].lower()}.")
    return "\n".join(lines)


def director_block(sig: Signals) -> str:
    """THE LAYOUT block for the Director's brief: the owner's pick or the
    ranked shortlist with reasons, and the full catalog."""
    rows = rank(sig)
    top = rows[:3]
    head = ["== THE LAYOUT (decide the page's structure before writing a section) =="]
    if rows[0]["picked"]:
        head.append(f"THE OWNER PICKED: {rows[0]['key']} ({rows[0]['name']}). Use it.")
    else:
        head.append("RANKED FOR THIS BUSINESS (from what it actually has; take the "
                    "first unless the idea clearly calls for another layout, "
                    "and say why):")
    for i, r in enumerate(top, 1):
        why = "; ".join(r["why"]) or "fits the material"
        against = f" (against: {'; '.join(r['against'])})" if r["against"] else ""
        head.append(f"{i}. {r['key']} ({r['name']}): {why}{against}")
    head += ["", f"ALL {len(LAYOUTS)} LAYOUTS:", catalog_block()]
    return "\n".join(head)


def builder_block(key: Optional[str]) -> str:
    """The chosen layout's recipe for the builder, or '' when none."""
    k = normalize(key)
    if not k:
        return ""
    L = LAYOUTS[k]
    return "\n".join([
        f"== THE LAYOUT: {k} ({L['name']}) — build this structure ==",
        f"WHAT IT IS: {L['line']}",
        f"SKELETON (the blueprint's sections follow this order): {L['skeleton']}",
        f"STRUCTURE: {L['structure']}",
        f"PHONE: {L['phone']}",
        "The layout is the page's architecture, not a style: the look, the idea and "
        "the objects live inside it. Where the blueprint and this structure disagree, "
        "the blueprint's sections win and keep this structure's shape.",
    ])


def key_from_sheet(sheet: Optional[Dict[str, str]]) -> Optional[str]:
    """The layout the blueprint's concept sheet names ('LAYOUT: editorial
    — your story carries the site'), or None."""
    return normalize((sheet or {}).get("layout"))


def reason_from_sheet(sheet: Optional[Dict[str, str]]) -> str:
    raw = str((sheet or {}).get("layout") or "")
    m = re.split(r"\s*(?:—|–|:|\s-\s)\s*", raw, maxsplit=1)
    return (m[1].strip() if len(m) > 1 else "")[:240]


# ─── the render check (the hand-build "does it look like the sketch?") ─
#
# Measured at 1440px on the page the eyes already open, so it costs no
# extra render. Only CLEAR misses become findings (a sidebar layout with
# no side column, a minimal page with nine sections); a free
# interpretation of a layout is design, not a defect.

RENDER_JS = r"""
(() => {
  const W = innerWidth, H = innerHeight;
  const vis = el => { if (!el) return false; const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.05; };
  const tops = [...document.querySelectorAll('section')].filter(s => !s.parentElement.closest('section') && vis(s));
  const first = tops[0] || null;
  const out = {layout_measured: true, sections: tops.length, hero_cols: 1, hero_img_ratio: 0,
               hero_height_ratio: 0, h1_px: 0, sidebar: false, row_max: 1, tall_sections: 0,
               narrow_text_ratio: 0, overlap_ok: 0, rotated: 0, bento_grids: 0, big_images: 0, mixed_cols: 0,
               times_top: 0, book_links: 0};
  const h1 = document.querySelector('h1');
  if (h1 && vis(h1)) out.h1_px = Math.round(parseFloat(getComputedStyle(h1).fontSize) || 0);
  if (first) {
    const fr = first.getBoundingClientRect(); const area = Math.max(1, fr.width * Math.min(fr.height, H));
    out.hero_height_ratio = +(fr.height / H).toFixed(2);
    let img = 0;
    for (const el of [first, ...first.querySelectorAll('*')]) {
      if (!vis(el)) continue;
      const tag = el.tagName; const bg = getComputedStyle(el).backgroundImage || '';
      if (tag === 'IMG' || tag === 'VIDEO' || tag === 'PICTURE' || bg.includes('url(')) {
        const r = el.getBoundingClientRect();
        const w = Math.max(0, Math.min(r.right, fr.right) - Math.max(r.left, fr.left));
        const h = Math.max(0, Math.min(r.bottom, fr.top + H) - Math.max(r.top, fr.top));
        img = Math.max(img, w * h);
      }
    }
    out.hero_img_ratio = +(img / area).toFixed(2);
    for (const c of [first, ...first.querySelectorAll('div,header,article,figure,aside')]) {
      const kids = [...c.children].filter(vis).map(k => k.getBoundingClientRect()).filter(r => r.width > W * 0.2);
      let cols = 1;
      for (let i = 1; i < kids.length; i++)
        if (kids[i].top < kids[i - 1].bottom - 10 && Math.abs(kids[i].left - kids[i - 1].left) > W * 0.15) cols++;
      if (cols > out.hero_cols) out.hero_cols = cols;
      if (out.hero_cols >= 2) break;
    }
  }
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if ((cs.position === 'fixed' || cs.position === 'sticky') && vis(el)) {
      const r = el.getBoundingClientRect();
      if (r.height > H * 0.7 && r.width < W * 0.35 && el.querySelectorAll('a').length >= 3) out.sidebar = true;
    }
    if (cs.transform && cs.transform !== 'none' && vis(el)) {
      const m = cs.transform.match(/matrix\(([^)]+)\)/);
      if (m) { const v = m[1].split(',').map(Number); if (Math.abs(v[1]) > 0.02 && Math.abs(v[0]) > 0.5) out.rotated++; }
    }
    if (cs.display === 'grid' && vis(el)) {
      const kids = [...el.children].filter(vis).map(k => { const r = k.getBoundingClientRect(); return r.width * r.height; }).filter(a => a > 400);
      if (kids.length >= 5 && Math.max(...kids) / Math.max(1, Math.min(...kids)) > 2.2) out.bento_grids++;
    }
  }
  out.overlap_ok = document.querySelectorAll('[data-overlap-ok]').length;
  for (const parent of document.querySelectorAll('section *')) {
    const kids = [...parent.children].filter(vis).map(k => k.getBoundingClientRect()).filter(r => r.width > 120 && r.height > 80);
    if (kids.length < 2) continue;
    const rows = {};
    for (const r of kids) { const k = Math.round(r.top / 12); (rows[k] = rows[k] || []).push(r); }
    for (const row of Object.values(rows)) {
      if (row.length < 2) continue;
      const ws = row.map(r => r.width); const max = Math.max(...ws), min = Math.min(...ws);
      if (row.length >= 3 && max / min < 1.25) out.row_max = Math.max(out.row_max, row.length);
      if (max / min >= 1.6) out.mixed_cols++;
    }
  }
  out.tall_sections = tops.filter(s => s.getBoundingClientRect().height >= H * 0.8).length;
  const ps = [...document.querySelectorAll('p')].filter(p => vis(p) && (p.textContent || '').trim().length >= 60);
  if (ps.length) out.narrow_text_ratio = +(ps.filter(p => p.getBoundingClientRect().width <= 780).length / ps.length).toFixed(2);
  out.big_images = [...document.querySelectorAll('img')].filter(i => vis(i) && i.getBoundingClientRect().width >= W * 0.45).length;
  const clock = /\b(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s?(?:am|pm|a\.m\.|p\.m\.)|\b(?:[01]?\d|2[0-3]):[0-5]\d\b/gi;
  const seen = new Set(); const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    const el = n.parentElement; if (!el || !vis(el)) continue;
    if (el.getBoundingClientRect().top + scrollY > H * 1.6) continue;
    for (const m of (n.textContent || '').matchAll(clock)) seen.add(m[0].toLowerCase().replace(/[\s.]/g, ''));
  }
  out.times_top = seen.size;
  out.book_links = [...document.querySelectorAll('a[href]')].filter(a => vis(a) && /\/book\b|#book|booking/i.test(a.getAttribute('href') || '')).length;
  return out;
})()
"""


def _desktop(measures: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The widest measured width (1024px or more) that carries layout metrics."""
    best: Dict[str, Any] = {}
    for width, m in sorted((measures or {}).items(), key=lambda kv: int(kv[0])):
        if isinstance(m, dict) and m.get("layout_measured") and int(width) >= 1024:
            best = m
    return best


def render_findings(key: Optional[str], measures: Optional[Dict[str, Any]]) -> List[str]:
    """Clear misses between the rendered page and its chosen layout, in the
    builder's words. [] when there is no layout, no measurement, or the
    page reads as the layout."""
    k = normalize(key)
    m = _desktop(measures)
    if not k or not m:
        return []
    miss: Optional[str] = None
    if k == "split" and m.get("hero_cols", 1) < 2:
        miss = ("the first screen is one column; the split puts the words on one "
                "side and the photo on the other")
    elif k == "editorial" and (m.get("narrow_text_ratio", 1) < 0.6 or m.get("row_max", 1) >= 3):
        miss = ("the text runs wider than a reading column or sits in card rows; hold "
                "running text to a 60 to 72ch column and set offerings as typeset lines")
    elif k == "fullscreen" and (m.get("hero_height_ratio", 0) < 0.85 or m.get("hero_img_ratio", 0) < 0.6):
        miss = ("the opening is not a full-screen photo; make the first section at "
                "least 90vh with the photo across it")
    elif k == "statement" and (m.get("h1_px", 0) < 64 or m.get("hero_img_ratio", 0) > 0.25):
        miss = ("the headline is not the picture; set it at monumental size and keep "
                "photos out of the first screen")
    elif k == "grid" and m.get("row_max", 1) < 3:
        miss = "there is no row of three or more same-size tiles; give the offerings a real grid"
    elif k == "magazine" and m.get("mixed_cols", 0) < 1:
        miss = ("no band sets a large lead block beside smaller ones; build the front "
                "page with a lead story and side stories")
    elif k == "bento" and m.get("bento_grids", 0) < 1:
        miss = ("there is no board of boxes in different sizes; build one grid with "
                "deliberately different spans")
    elif k == "showcase" and m.get("big_images", 0) < 3:
        miss = "the photos are small; let at least three of them run at half the width or more"
    elif k == "story" and m.get("tall_sections", 0) < 4:
        miss = "the chapters are short bands; give each chapter its own full-height section"
    elif k == "asymmetric" and (m.get("overlap_ok", 0) + m.get("rotated", 0)) < 2:
        miss = ("nothing overlaps or breaks the grid; offset and overlap the pieces on "
                "purpose (mark them data-overlap-ok)")
    elif k == "sidebar" and not m.get("sidebar"):
        miss = ("no side column stays put while the page scrolls; build the sticky side "
                "column with the name, the links and the action")
    elif k == "minimal" and m.get("sections", 0) > 5:
        miss = f"the page has {m.get('sections')} sections; a minimal page holds three or four"
    elif k == "bulletin" and m.get("times_top", 0) < 2:
        miss = ("the weekly times are not near the top; set them in one row inside the "
                "first screen or straight under it")
    elif k == "booking" and m.get("book_links", 0) < 3:
        miss = (f"only {m.get('book_links', 0)} links lead to booking; give every service its "
                "own book link and put a booking band in the middle of the page")
    if not miss:
        return []
    return [f"THE LAYOUT is {LAYOUTS[k]['name']}, but at 1440px {miss}. "
            "Rebuild to the layout's STRUCTURE."]
