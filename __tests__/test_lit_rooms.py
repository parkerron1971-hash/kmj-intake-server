"""The church product pages as lit rooms (church_site, 2026-11-05), Giving first.

Kevin, on the Giving mock (claude.ai/artifact/NHKdhA7FbSsaaR788at2Zn): "the design is good! love it. let's
build it and do upgrades to others as well".

Holds:
  1. THE KIT IS SHARED AND TAKES THE ROOM'S COLOUR: lit.css never names a room's colour; a lit room gets the
     kit and its own parts inlined, with no template marker left, and both scripts parse.
  2. THE ROOM STILL ANSWERS ITS OWN MENU: every "In this room" link lands on a section of the page.
  3. COMPLETE AT REST: the hero and the statements open on their finished state, so the page reads right before
     (or without) any script; the story shows every step's scene inline on phones.
  4. THE PLAN-BY-SIZE WORDS STILL SWITCH: the funds lede, the close and 990 prep follow PLAN_CHURCH_OFFERED.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402

import church_site as cs  # noqa: E402
import marketing_pages as mp  # noqa: E402

LIT = ["giving", "member-app", "kids-and-youth", "people-and-care", "groups-and-classes",
       "website-and-sermons", "office-and-books"]


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.setenv("CHURCH_SITE", "on")
    monkeypatch.delenv("HOME_EDITION", raising=False)
    monkeypatch.delenv("PLAN_CHURCH_OFFERED", raising=False)
    monkeypatch.delenv("CHURCH_OFFERED", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


# ─── 1. the kit ─────────────────────────────────────────────────────

def test_the_kit_never_names_a_rooms_colour():
    css = cs._read("lit.css")
    for hexcode in ("#22C55E", "#86EFAC", "#15803D", "#EC4899", "#F97316", "#14B8A6", "#3B82F6", "#EAB308"):
        assert hexcode.lower() not in css.lower(), hexcode
    assert "var(--p)" in css and "var(--pl)" in css


@pytest.mark.parametrize("slug", LIT)
def test_a_lit_room_carries_the_kit_and_its_own_parts(slug):
    page = cs.render(slug)
    assert "{{" not in page
    assert ".lit-phone{" in page and ".lit-stage{" in page                  # the kit
    assert cs._read(slug + ".css")[:200] in page                             # the room's own parts
    assert "window.Lit" in page and cs._read(slug + ".js")[:120] in page


@pytest.mark.parametrize("name", ["lit.js"] + [s + ".js" for s in LIT])
def test_the_scripts_parse(name):
    js = cs._read(name)
    assert "{{" not in js
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    res = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr


# ─── 2. the room's own menu ─────────────────────────────────────────

@pytest.mark.parametrize("slug", LIT)
def test_every_in_this_room_link_lands(slug):
    page = cs.render(slug)
    nav = re.search(r'<nav aria-label="In this room">(.*?)</nav>', page, flags=re.S).group(1)
    for anchor in re.findall(r'href="#([a-z-]+)"', nav):
        assert f'id="{anchor}"' in page, anchor


# ─── 3. complete at rest ────────────────────────────────────────────

def test_giving_opens_on_its_finished_scenes():
    page = cs.render("giving")
    assert 'class="gu-hero landed"' in page                                  # the gift has landed
    assert re.search(r'data-to="18340" data-money>\$18,340<', page)          # and the count says so
    assert 'gu-state sent' in page                                           # statements: sent
    steps = re.findall(r'<div class="lit-step" data-step="(\d)">', page)
    assert steps == ["1", "2", "3", "4"]
    assert page.count('<div class="inline"><div class="lit-scene') == 4     # each step's scene, for phones


def test_giving_keeps_its_sample_labels_and_names_no_one():
    page = cs.render("giving")
    assert "Grace Fellowship" in page and "SAMPLE" in page and "Giving · sample" in page
    for gone in ("Love City", "Kevin"):
        assert gone not in page


@pytest.mark.parametrize("slug", LIT)
def test_every_room_names_no_one_and_says_its_samples_are_samples(slug):
    page = cs.render(slug)
    for gone in ("Love City", "Kevin", "office work"):
        assert gone not in page, (slug, gone)
    assert "Grace Fellowship" in page or "sample" in page.lower(), slug


@pytest.mark.parametrize("slug", LIT)
def test_every_room_reads_without_its_script(slug):
    """Complete at rest: no room hides its words until a script runs."""
    page = cs.render(slug)
    body = re.sub(r"(?s)<(script|style)\b.*?</\1>", "", page)
    assert len(re.sub(r"<[^>]+>", " ", body).split()) > 250, slug
    assert re.search(r"<h1\b", body), slug


@pytest.mark.parametrize("slug", LIT)
def test_every_rooms_start_button_says_church(slug):
    page = cs.render(slug)
    assert 'href="https://mysolutionist.app/start"' not in page
    assert "/start?for=church" in page


# Each of these read well in a mock and isn't what the product does (the claims
# review, 2026-11-06). A Stripe payout is matched to a payout, never to a Sunday:
# that match is GIVING_DEPOSITS, and it isn't on for every church.
NOT_WHAT_IT_DOES = {
    "office-and-books": ["Sunday Oct 25 giving", "Sunday's giving", "Sunday's gifts", "(PDF)", "Here 3 of the last 4",
                         "with who made it", "moved from General to Building fund", "Given this year"],
    "kids-and-youth": ["from their own phones", "not in yet", "which leader", "by Denise R.", "leaders Denise",
                       "second leader", "one tap"],
    "people-and-care": ["or in the app", "Talk with a pastor", "Monday 8:00", "Came for the first time",
                        "checked in at Kids", "Chief reads what they wrote", "Deacon · 12 families"],
    "groups-and-classes": ["7 people are praying", "go first, when"],
    "website-and-sermons": ["gracefellowship.org/visit", "what your site already says", "will look for you at 11",
                            "Cars leave the church", "42 going", "pick another job", "38 min", "/sermons/rooted-in-love"],
    "member-app": ["from the member app</small>", "at the welcome desk"],
    # A covered fee is 2.9% + 30c on the gift, and the gift is recorded at the full amount.
    "giving": ["$3.20", "$103.20", "never pays the light bill", "Pause this gift?", "January 1 to December 31",
               "Your statement is attached", "Preview one", "Chief puts them together", "file with their taxes",
               "Sarah Kim · posted to the books", "first gift this month", "before it sends anything"],
    "": ["have a note ready", "142 opened", "watching live", "every gift accounted for", "the only color on",
         "Search people, groups, gifts", "Start free on", "drafts for shepherds", "Monthly givers come too",
         "Start free, then ask for the move", "The app and the website"],
}


@pytest.mark.parametrize("slug,lines", sorted(NOT_WHAT_IT_DOES.items()))
def test_a_room_says_only_what_the_product_does(slug, lines):
    page = cs.render(slug)
    for line in lines:
        assert line not in page, (slug, line)


@pytest.mark.parametrize("slug", LIT)
def test_a_pastor_is_never_called_a_small_business(slug):
    page = cs.render(slug)
    assert "small business" not in page.lower(), slug
    assert "before it sends anything or touches money" not in page, slug


def test_the_covered_fee_is_the_one_the_giving_code_charges():
    import giving_router
    fee = giving_router.covered_fee_cents(10000)
    assert fee == 330
    page = cs.render("giving")
    assert f"Add about ${fee / 100:.2f} to cover the card fee" in page
    assert f"${(10000 + fee) / 100:.2f}" in page


# ─── 4. the plan-by-size words ──────────────────────────────────────

def test_the_funds_words_follow_the_plans(monkeypatch):
    off = cs.render("giving")
    assert "On Professional and up, restricted gifts post to Restricted Contributions" in off
    assert "Month-end and year-end close on Professional" in off and "990 prep on the Solutionist plan" in off
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    on = cs.render("giving")
    assert "each gift stays counted in it, on every plan" in on
    assert "990 prep on every plan" in on
