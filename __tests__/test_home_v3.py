"""The home page, third edition (marketing_home_v3, 2026-10-14).

Kevin approved the design pass by pass (the "Solutionist Homepage" artifact)
and said "ship to live". These pin what the port has to keep true so a later
re-import of the design cannot quietly undo it:

  1. THE MONEY IS LIVE: the cards, the plan table header, the seven-tools
     card, the calculator and Ask Chief all read the dials; the founding seat
     reads the live count and vanishes when there is no seat to sell.
  2. THE PLAN TABLE IS THE PRODUCT: every row comes from _COMPARE_GROUPS and
     the gate map, Starter reads as a column of what it includes, and the
     "only what changes" switch is off until the visitor turns it on.
  3. THE FILM AND THE PHOTOS ARE ASSETS: /assets/film.mp4, /assets/home/*.jpg,
     every referenced photo exists, and the route cannot leave its folder.
  4. THE LINKS ARE THE SITE'S, and the design-review furniture is gone (the
     Listen tour, the design-preview line, the support-line placeholder).
  5. THE SHELL CARRIES ON: pixel, attribution, structured data from the dials
     and the FAQ, the trial and contact sentinels filled.
  6. NOTHING THE COMPANY PAUSED IS SOLD: no therapy or health care, and a
     health trade typed into the page gets a straight "not yet".
  7. THE ROLLBACK WORKS: HOME_EDITION=v2 serves the second edition.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

import feature_gates
import marketing_home_v3 as v3
import marketing_pages as mp
import pricing_config


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.delenv("HOME_EDITION", raising=False)
    monkeypatch.delenv("CHIEF_MODEL_DEEP", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


def _founder(monkeypatch, taken: int, limit: int = 50):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: ["price_f"])
    monkeypatch.setattr(stripe_billing, "_founder_seat_limit", lambda: limit)
    monkeypatch.setattr(mp, "_founder_seats_taken_sync", lambda: taken)


def _prices(monkeypatch, starter, pro, sol):
    real = dict(pricing_config.tier_price_cents())
    real.update({"starter": starter * 100, "professional": pro * 100, "practice": sol * 100})
    monkeypatch.setattr(pricing_config, "tier_price_cents", lambda: dict(real))


def _between(html: str, start: str, end: str) -> str:
    i = html.index(start)
    return html[i:html.index(end, i)]


# ─── 1. the money is live ────────────────────────────────────────────

def test_the_home_is_the_third_edition():
    html = mp.render_home()
    for anchor in ('id="top"', 'id="who"', 'id="film"', 'id="how"', 'id="night"', 'id="morning"',
                   'id="stack"', 'id="worth"', 'id="trust"', 'id="pricing"', 'id="compare"', 'id="faq"', 'id="start"'):
        assert anchor in html, anchor
    assert "has a <span class=\"glint\">solution.</span>" in html
    assert not re.search(r"\{\{[A-Z_]+\}\}", html), "an unfilled template token"


def test_every_price_on_the_page_reads_the_dials(monkeypatch):
    _prices(monkeypatch, 81, 157, 311)
    html = mp.render_home()
    for dollars in (81, 157, 311):
        assert f'data-to="{dollars}" data-prefix="$">${dollars}</b>' in html
        assert f'data-monthly="{dollars}" data-annual="{dollars * mp.ANNUAL_MONTHS // 12}"' in html
    # the plan table's header, the seven-tools card, the calculator and Ask Chief
    head = _between(html, 'class="cx-grid cx-head"', 'class="cx-g"')
    assert "$81/mo" in head and "$157/mo" in head and "$311/mo" in head
    assert "<b>$81</b><span><strong>a month, all of it</strong>" in html
    assert "const STARTER_PRICE = 81, PRO_PRICE = 157;" in html
    assert "Plans are $81, $157 and $311 a month." in html
    for stale in ("$79", "$149", "$299"):
        assert stale not in html, stale


def test_the_cards_say_what_the_gates_and_dials_say():
    html = mp.render_home()
    d = mp._tier_dials()
    credits = pricing_config.tier_credits()
    cards = re.findall(r'<div class="price-card( is-mid)?">(.*?)</a>\s*</div>', html, re.S)
    assert len(cards) == 3 and [bool(m) for m, _ in cards] == [False, True, False]
    for (plan, name), (_m, body) in zip((("starter", "Starter"), ("professional", "Professional"), ("practice", "Solutionist")), cards):
        assert f'<div class="price-name">{name}</div>' in body
        assert f'aria-label="{credits[plan]:,} AI actions a month"' in body
        assert f'href="/start?plan={plan}"' in body
        if d[plan]["analysis"]:
            assert f"{d[plan]['analysis']} deep analysis" in body
    # a "plus" line only prints while its gate opens on that card's plan
    pro, sol = cards[1][1], cards[2][1]
    assert ("Your own AI can keep records here" in pro) == (feature_gates.FEATURE_MIN_PLAN["agent_connector_write"] == "professional")
    assert ("A texting number of your own" in sol) == (feature_gates.FEATURE_MIN_PLAN["dedicated_sms_number"] == "practice")
    assert "Most people land here" in pro and html.count("Most people land here") == 1


def test_a_gate_that_moves_takes_its_claim_with_it(monkeypatch):
    gates = dict(feature_gates.FEATURE_MIN_PLAN)
    gates["dedicated_sms_number"] = "practice"      # it lives on Professional (Kevin, 2026-10-22)
    monkeypatch.setattr(feature_gates, "FEATURE_MIN_PLAN", gates)
    cards = v3._price_cards_html()
    assert "A texting number of your own" not in cards


def test_the_model_kill_switch_drops_the_depth_line(monkeypatch):
    monkeypatch.setenv("CHIEF_MODEL_DEEP", "some-model")
    html = mp.render_home()
    assert "deep analysis</span>" not in html and 'class="depth"' not in html


def test_the_founding_seat_is_live(monkeypatch):
    _founder(monkeypatch, taken=7)
    html = mp.render_home()
    seat = _between(html, 'id="seat"', "</section>")
    assert "<b>43</b> of 50 seats left" in seat and "Seat 08 is next" in seat and "Claim seat 08" in seat
    assert "Nº 08 / 50" in seat and 'href="/start?plan=founder"' in seat
    assert seat.count('<i class="t"></i>') == 7 and seat.count('<i class="n"></i>') == 1
    strip = _between(html, 'id="founderStrip"', "</a>")
    assert 'data-left="43"' in strip and "<b>43</b> of 50 seats left" in strip and "Claim seat 08" in strip
    price = pricing_config.tier_price_cents()["founder"] // 100
    assert f"locks Professional at ${price} a month" in html, "Ask Chief names the seat while one is open"


def test_no_seat_left_means_no_seat_chapter_and_a_quiet_strip(monkeypatch):
    _founder(monkeypatch, taken=50)
    html = mp.render_home()
    assert 'id="seat"' not in html and "Claim seat" not in html
    assert "founder is-gone" in html and "The 50 founding seats are gone" in html
    assert "locks Professional" not in html


def test_no_founder_price_means_no_seat_anywhere():
    html = mp.render_home()
    for marker in ('id="seat"', 'id="founderStrip"', 'id="founderAd"', "Founding seats ·"):
        assert marker not in html, marker
    assert 'id="seatBiz"' not in html and 'id="fcard"' not in html


# ─── 2. the plan table is the product ────────────────────────────────

def test_the_plan_table_is_the_whole_product():
    html = mp.render_home()
    table = _between(html, 'id="cxTable"', '<p class="cx-foot')
    rows = re.findall(r'<div class="cx-grid cx-r" data-same="([01])"><span class="w"><b>(.*?)</b>.*?</span>((?:<span class="c(?: hi)?">.*?</span>){3})</div>', table, re.S)
    assert len(rows) >= 45, f"only {len(rows)} rows"
    labels = [r[1] for r in rows]
    for label in ("Contacts &amp; CRM", "AI actions a month", "Audit trail", "Team seats", "Your data stays yours"):
        assert label in labels, label
    starter_ticks = sum(1 for _s, _l, cells in rows if cells.startswith('<span class="c"><i class="yes"'))
    assert starter_ticks >= 30, "Starter reads as a column of what it includes"
    # the same/differs flag is what the switch hides by, and it is honest
    for same, _label, cells in rows:
        values = re.findall(r'<span class="c(?: hi)?">(.*?)</span>', cells)
        assert (same == "1") == (len(set(values)) == 1)
    assert 'id="cxDiff" aria-pressed="false"' in html, "the full table is the default"
    assert 'class="cx-g" data-g="0" data-open="true"' in table


def test_every_compare_group_reaches_the_page():
    html = mp.render_home()
    for group, _entries in mp._COMPARE_GROUPS:
        assert f"{group}<small>" in html, group


# ─── 3. the film and the photos are assets ───────────────────────────

def test_the_film_is_the_live_asset():
    html = mp.render_home()
    assert "const FILM = '/assets/film.mp4?v=3'" in html and 'poster="/assets/film-poster.jpg?v=4"' in html
    chapters = re.search(r"CH = \[(.*?)\];", html).group(1)
    assert re.findall(r"\[(\d+), '([^']+)'\]", chapters) == [
        ("5", "Sign in"), ("16", "Say it"), ("26", "Run the day"), ("34", "Be found"),
        ("42", "Bring what you have"), ("50", "The night shift")]
    assert "base64," not in html and len(html) < 400_000


def test_every_photo_the_page_names_is_on_disk():
    html = mp.render_home()
    names = set(re.findall(r"/assets/home/([a-z0-9-]+\.jpg)", html))
    assert len(names) >= 12
    for n in names:
        assert (ROOT / "static" / "home" / n).is_file(), n
    assert "img/" not in re.sub(r"<img\b", "", html)


def test_the_photo_route_stays_in_its_folder():
    try:
        import public_site
    except ImportError as e:   # an optional integration's client missing locally; CI has them all
        pytest.skip(f"public_site needs {e.name}")
    assert public_site._home_asset_path("p-andre.jpg") is not None
    for bad in ("../brand/favicon.png", "..%2fbrand%2ffavicon.png", "P-ANDRE.jpg", "x.png", "nope.jpg", "", ".jpg"):
        assert public_site._home_asset_path(bad) is None, bad


# ─── 4. the links are the site's, the furniture is gone ──────────────

def test_the_links_are_the_sites():
    html = mp.render_home()
    body = html[html.index("<body"):]
    assert 'href="https://mysolutionist.app/' not in body
    assert f'href="{mp.APP_URL}"' in body
    for path in ("/start", "/start?plan=founder", "/compare", "/features", "/about", "/news", "/download",
                 "/terms", "/privacy", "/faq"):
        assert f'href="{path}"' in body, path
    assert "mailto:" in body and 'href="#start">' not in body


def test_every_footer_link_is_a_route():
    try:
        import public_site
    except ImportError as e:
        pytest.skip(f"public_site needs {e.name}")
    html = mp.render_home()
    foot = html[html.index("<footer"):]
    paths = set(re.findall(r'href="(/[^"#?]*)', foot))
    routes = {r.path for r in public_site.router.routes if hasattr(r, "path")}
    for p in paths:
        assert p in routes or p == "/", f"{p} is not a route"


def test_the_design_review_furniture_is_gone():
    html = mp.render_home()
    for marker in ('id="listen"', "speechSynthesis", "design preview", "[SUPPORT LINE]", "sixth pass",
                   "Photos are stand-ins", "claude:viewport", "media/film"):
        assert marker not in html, marker
    assert "sample data" in html, "the page's businesses and numbers are samples and it must say so"


def test_the_phone_menu_is_the_one_the_flyer_waits_for():
    html = mp.render_home()
    assert html.count('id="mobileMenu"') == 1 and 'aria-controls="mobileMenu"' in html
    assert re.search(r'<nav class="sheet" id="mobileMenu"[^>]*\bhidden\b', html)


def test_a_trade_link_lands_on_its_trade_and_keeps_the_campaign_tags():
    html = mp.render_home()
    assert "new URLSearchParams(location.search)" in html and "q.set('trade', TRADE_KEY[id])" in html
    assert "history.replaceState(null, '', location.pathname + '?' + q.toString() + location.hash)" in html
    for key in ("barber", "attorney", "contractor", "coach", "consultant", "ministry", "nonprofit"):
        assert f"'{key}'" in html, key


def test_the_sample_people_are_labeled_not_real():
    """Kevin, 2026-10-15: the photos are stock models, so every made-up name
    and business says so right beside it, and the tag that points at the
    person in the photo names the role, never the made-up name."""
    html = mp.render_home()
    assert "not a real person" in html and '<span class="fx">Fictional</span>' in html
    assert "Stock photo · a model" in html and "Stock photos of models, not customers" in html
    assert "is a fictional business" in html
    # 2026-10-15: the hero has no photo, so it carries no "Fictional business" caption
    assert "Fictional business · " not in html and 'id="coreBiz"' not in html
    assert "a sample customer" not in html
    assert "g.f ? g.t.replace(t.owner, cap(ROLE[t.id])) : g.t" in html


# ─── 5. the shell carries on ─────────────────────────────────────────

def test_the_shell_carries_the_pixel_the_beacon_and_the_flyer_styles(monkeypatch):
    _founder(monkeypatch, taken=7)
    html = mp.render_home()
    assert "/api/track" in html and "_sol_attr" in html
    style = _between(html, "<style>", "</style>")
    assert ".fad-card{" in style, "the flyer's styles ride inside the page's style block, not as text"
    assert 'id="founderAd"' in html and html.count('id="founderAd"') == 1
    for token in ("__TRIAL_FREE__", "__TRIAL_CARD__", "__TRIAL_CARD_NOTE__", "__CONTACT_EMAIL__"):
        assert token not in html, token


def test_the_structured_data_matches_the_dials_and_the_faq(monkeypatch):
    _prices(monkeypatch, 81, 157, 311)
    html = mp.render_home()
    head = html[:html.index("</head>")]
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', head, re.S).group(1)
    graph = {n["@type"]: n for n in json.loads(raw)["@graph"]}
    offers = {o["name"]: o["price"] for o in graph["SoftwareApplication"]["offers"]}
    assert offers == {"Starter": "81", "Professional": "157", "Solutionist": "311"}
    qs = graph["FAQPage"]["mainEntity"]
    page_qs = re.findall(r"<details><summary>(.*?)</summary>", _between(html, 'id="faq"', "</section>"))
    assert [q["name"] for q in qs] == page_qs and len(qs) == 6
    trial = next(q for q in qs if "free trial" in q["name"])
    assert mp._trial_free_phrase() in trial["acceptedAnswer"]["text"]


def test_no_dash_joined_sentences():
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", mp.render_home(), flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    assert " — " not in text and " &mdash; " not in text


def test_no_vendor_model_is_named():
    html = mp.render_home()
    for name in ("Claude", "Sonnet", "Opus", "Fable", "GPT-", "Gemini"):
        assert name not in html, name


# ─── 6. nothing the company paused is sold ───────────────────────────

def test_no_therapy_or_health_care():
    low = mp.render_home().lower()
    for word in ("therapist", "therapy practice", "superbill", "clinical notes", "your ehr", "hipaa"):
        assert word not in low, word
    assert "isn’t taking on therapy or health care practices yet" in mp.render_home()


def _run_form(inputs):
    """Run the page's own trade and health matchers in node and return, per
    input, which branch the reply takes."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    html = mp.render_home()
    kw = re.search(r"  const KW = (\{.*?\});\n", html).group(1)
    health = re.search(r"if \(!hit && (/.*?/i)\.test\(v\)\)", html).group(1)
    src = f"""
const KW = {kw};
const HEALTH = {health};
const ids = ['barber', 'law', 'build', 'coach', 'consult', 'ministry', 'nonprofit'];
const out = {{}};
for (const v of {json.dumps(inputs)}) {{
  const hit = ids.find((id) => KW[id].test(v));
  out[v] = hit || (HEALTH.test(v) ? 'health' : 'other');
}}
console.log(JSON.stringify(out));
"""
    res = subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_a_named_trade_wins_and_health_gets_a_straight_not_yet():
    out = _run_form(["dental clinic", "I'm a therapist", "mental health counselor", "medical malpractice attorney",
                     "church of about two hundred", "hair salon", "roofing company", "food bank", "bakery"])
    assert out["dental clinic"] == "health" and out["I'm a therapist"] == "health"
    assert out["mental health counselor"] == "health"
    assert out["medical malpractice attorney"] == "law", "a named trade wins"
    assert out["church of about two hundred"] == "ministry" and out["hair salon"] == "barber"
    assert out["roofing company"] == "build" and out["food bank"] == "nonprofit" and out["bakery"] == "other"


# ─── 7. the rollback works ───────────────────────────────────────────

def test_home_edition_v2_brings_the_second_edition_back(monkeypatch):
    monkeypatch.setenv("HOME_EDITION", "v2")
    html = mp.render_home()
    assert 'id="room"' in html and 'id="cxTable"' not in html
    monkeypatch.setenv("HOME_EDITION", "")
    assert 'id="cxTable"' in mp.render_home()
