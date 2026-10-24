"""Meet Chief on the church and coach sections (2026-10-24).

Holds:
  1. CHIEF IS INTRODUCED: each overview has the #chief band, role first
     ("A chief of staff for your ..."), its four points and a Chief link in
     the header; every product page has the "How Chief works" strip back to it.
  2. THE BAND'S CLAIMS ARE THE PRODUCT'S: the conversations come from the
     dials over the chat price; chat, voice and drafts run the same model on
     every plan while the deep lane climbs; undo is a day long, covers tasks
     and website text, and never a send or a payment.
  3. THE SAMPLES ADD UP: every weekday next to a date matches the 2026
     calendar, on every page of both sections.
  4. THE PHOTOS ARE THE SITE'S OWN: only pictures served from static/home.
"""
from __future__ import annotations

import datetime
import html as _html
import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402

import church_site  # noqa: E402
import coach_site  # noqa: E402
import marketing_pages as mp  # noqa: E402

SECTIONS = {"churches": church_site, "coaches": coach_site}


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.setenv("CHURCH_SITE", "on")
    monkeypatch.delenv("COACH_SITE", raising=False)
    monkeypatch.delenv("CHURCHSAVVY_URL", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


def _pages(mod):
    return {mod.path_of(s): mod.render(s) for s in mod.PAGES}


# ─── 1. Chief is introduced ─────────────────────────────────────────

@pytest.mark.parametrize("section,who", [("churches", "church"), ("coaches", "practice")])
def test_the_overview_introduces_chief_role_first(section, who):
    html = SECTIONS[section].render("")
    band = re.search(r'<section id="chief".*?</section>', html, flags=re.S)
    assert band, section
    band = band.group(0)
    assert f"A chief of staff for your {who}." in band and "It's called Chief." in band
    assert "Chief is the AI built into Solutionist." in band
    for point in ("Type it or say it", "Ready each morning", "Your yes comes first", "Shows its work"):
        assert point in band, point
    header = html.split("</header>", 1)[0]
    assert '<a href="#chief"' in header, section                     # Chief is in the overview's menu
    assert html.index('id="chief"') < html.index('id="products"')    # met before the products


@pytest.mark.parametrize("section", list(SECTIONS))
def test_every_product_page_points_to_how_chief_works(section):
    mod = SECTIONS[section]
    for slug in mod.PRODUCTS:
        page = mod.render(slug)
        assert f'href="/{section}#chief">How Chief works</a>' in page, slug
        assert page.index("How Chief works") < page.index("The rooms"), slug


# ─── 2. the band's claims are the product's ─────────────────────────

@pytest.mark.parametrize("section", list(SECTIONS))
def test_the_conversations_come_from_the_dials_and_the_chat_price(section, monkeypatch):
    import pricing_config
    real = mp._tier_dials

    def dials():
        d = real()
        d["starter"].update(credits="2,000")
        d["professional"].update(credits="5,000")
        d["practice"].update(credits="20,000")
        return d
    monkeypatch.setattr(mp, "_tier_dials", dials)
    monkeypatch.setattr(pricing_config, "chat_price", lambda: 10)
    html = SECTIONS[section].render("")
    assert "about 200 conversations a month on Starter, 500 on Professional and 2,000 on Solutionist" in html
    assert "About 200 conversations with Chief." in html and "About 500 conversations, room to draft" in html
    assert "About 2,000 conversations, Chief across every" in html
    assert "250 conversations" not in html


def test_everyday_answers_are_the_same_on_every_plan_and_long_sessions_climb(monkeypatch):
    """The band: "The bigger plans also think deeper in long planning
    sessions and the weekly look-back. Everyday answers are the same on
    every plan." True while only the deep lanes ride the tier ladder."""
    import chief_models
    for lane in ("chat", "voice", "draft", "deep", "insight"):
        monkeypatch.delenv(f"CHIEF_MODEL_{lane.upper()}", raising=False)
    plans = ("starter", "professional", "practice")
    for lane in ("chat", "voice", "draft"):
        assert len({chief_models.model_for(lane, p) for p in plans}) == 1, lane
    assert len({chief_models.model_for("deep", p) for p in plans}) == 3


def test_undo_is_a_day_long_and_never_a_send_or_a_payment():
    """The band: "Many changes, like tasks and website text, can be undone
    for a day. Anything sent or paid can't." """
    import action_inverse as ai
    assert ai.UNDO_WINDOW_HOURS == 24
    assert ai.can_undo("create_task") and ai.can_undo("edit_site_text")
    for verb in ("send_email", "send_sms", "send_invoice", "mark_invoice_paid", "generate_payment_link"):
        assert not ai.can_undo(verb), verb


# ─── 3. the samples add up ──────────────────────────────────────────

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                       "sep", "oct", "nov", "dec"), 1)}


def _words(html):
    html = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", html)
    return [w for w in (_html.unescape(x).strip() for x in re.split(r"<[^>]+>", html)) if w]


@pytest.mark.parametrize("section", list(SECTIONS))
def test_every_weekday_matches_its_date_in_2026(section):
    """A calendar tile splits the weekday from the day ("TUE" then "4"), so
    the pairs are read across tags; the samples live in fall 2026."""
    for path, html in _pages(SECTIONS[section]).items():
        words = _words(html)
        for i, w in enumerate(words[:-1]):
            if w.isalpha() and len(w) <= 9 and w[:3].lower() in _DAYS and re.fullmatch(r"\d{1,2}", words[i + 1]):
                day, n = _DAYS[w[:3].lower()], int(words[i + 1])
                fits = [m for m in (9, 10, 11, 12) if n <= 30 and datetime.date(2026, m, n).weekday() == day]
                assert fits, (path, w, n)
        text = " ".join(words)
        for wd, mon, n in re.findall(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{1,2})\b", text):
            assert datetime.date(2026, _MONTHS[mon.lower()], int(n)).weekday() == _DAYS[wd.lower()], (path, wd, mon, n)


# ─── 4. the photos are the site's own ───────────────────────────────

@pytest.mark.parametrize("section", list(SECTIONS))
def test_the_photos_are_the_sites_own(section):
    home = _here.parent / "static" / "home"
    for path, html in _pages(SECTIONS[section]).items():
        for src in re.findall(r'<img[^>]*\ssrc="([^"]+)"', html):
            assert src.startswith("/assets/home/"), (path, src)
            assert (home / src.rsplit("/", 1)[1]).is_file(), (path, src)


def test_a_coach_is_on_camera_and_in_the_room():
    overview = coach_site.render("")
    assert 'src="/assets/home/p-maya.jpg" alt="A coach teaching a live class, on camera"' in overview
    assert 'id="room"' in overview and 'src="/assets/home/w-workshop.jpg"' in overview
    assert re.search(r'<a href="/coaches/courses-and-classes#live"[^>]*>See live classes</a>', overview)
    marketing = coach_site.render("marketing-and-website")                # the recording and its clips
    assert 'src="/assets/home/w-workshop.jpg" alt="The workshop recording"' in marketing
    assert "p-james.jpg" not in marketing                                 # no pastor standing in for a coach
    assert '<span class="lv-cam lv-cam-on"><img src="/assets/home/p-maya.jpg"' in coach_site.render("courses-and-classes")
    assert ">DR</span>" not in coach_site.render("courses-and-classes")
