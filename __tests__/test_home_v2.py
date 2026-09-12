"""The home page, second edition (marketing_home_v2, 2026-09-11).

Kevin approved the page as a design concept cut by cut and then said
"let's push the site". These pin what the port has to keep true so a
later concept re-import cannot quietly undo it:

  1. THE FILM IS AN ASSET, NOT A PAYLOAD: the concept embedded 6.8 MB of
     base64 so an artifact sandbox could play it; the site points at
     /assets/film.mp4 and its poster and carries no data: URI.
  2. THE MONEY IS LIVE: the founding strip and the price cards are the
     same functions the first edition used, so the numbers come from the
     dials (test_pricing_section_lit and test_marketing_site_pricing
     keep their contracts on this page); the plan-difference table only
     lists rows the gate map or a dial actually differs on.
  3. THE FLYER IS THE LIVE ONE: marketing_founder_ad's dialog, not the
     concept's copy of it.
  4. THE LINKS ARE THE SITE'S: root-relative, Log in to the app, no
     absolute mysolutionist.app links, and every footer target is a route
     the server has.
  5. THE CONCEPT FURNITURE IS GONE: no note bar, no Listen control, no
     design-notes table, no "cut" label.
  6. THE COPY RULE: no dash-joined sentences (Kevin, 9/11).
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import feature_gates
import marketing_home_v2
import marketing_pages as mp
import pricing_config


@pytest.fixture(autouse=True)
def _no_founder(monkeypatch):
    import stripe_billing
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    monkeypatch.delenv("CHIEF_MODEL_DEEP", raising=False)


HOME = None


def _home() -> str:
    global HOME
    if HOME is None:
        HOME = mp.render_home()
    return HOME


def test_the_home_is_the_second_edition():
    html = _home()
    assert 'id="what"' in html and 'id="room"' in html and 'id="pricing"' in html and 'id="faq"' in html
    assert "Every problem has a solution" in html
    assert html is not None and mp.render_home_v1() != html


def test_the_film_is_an_asset():
    html = _home()
    assert "/assets/film.mp4?v=2" in html and "/assets/film-poster.jpg?v=2" in html
    assert "base64," not in html
    assert len(html) < 400_000, "the page should be well under half a megabyte without the film"


def test_the_money_is_live():
    html = _home()
    prices = pricing_config.tier_price_cents()
    credits = pricing_config.tier_credits()
    for plan in ("starter", "professional", "practice"):
        dollars = prices[plan] // 100
        assert f'data-to="{dollars}" data-prefix="$">${dollars}</b>' in html, plan
        assert f"{credits[plan]:,} AI actions" in html
    assert "is-lit-grid" in html and html.count('class="price-card"') == 2 and "price-card is-mid" in html
    # the seven-tools figure names the starter price from the dial too
    assert f'data-to="{prices["starter"] // 100}">${prices["starter"] // 100}</b>' in html


def test_the_plan_table_is_the_whole_product():
    """9/12: every row on every plan, behind the Compare every plan dropdown,
    so Starter shows what it includes and not a column of dashes."""
    html = _home()
    assert 'id="cmpMore"' in html and "Compare every plan" in html
    i = html.index("Every plan is the whole product")
    seg = html[i:html.index("</table>", i)]
    rows = re.findall(r"<tr><td>(.*?)</td>(.*?)</tr>", seg, re.S)
    assert len(rows) >= 40, f"only {len(rows)} rows"
    for label, cells in rows:
        assert len(re.findall(r"<td>(.*?)</td>", cells)) == 3, label
    assert "Contacts &amp; CRM" in seg and "Audit trail" in seg and "Team seats" in seg
    starter_ticks = sum(1 for _l, c in rows if c.startswith('<td><span class="ok">'))
    assert starter_ticks >= 25, "Starter should read as a column of what it includes"
    # the compare chapter sits under pricing, before the FAQ
    assert html.index('id="pricing"') < html.index('id="compare"') < html.index('id="faq"')


def test_the_flyer_is_the_live_one(monkeypatch):
    import sb_clients
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: ["price_f"])
    monkeypatch.setattr(stripe_billing, "_founder_seat_limit", lambda: 50)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": i} for i in range(7)])
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    html = mp.render_home()
    assert 'id="founderAd"' in html and 'data-left="43"' in html
    assert "sol_founder_ad_concept" not in html, "the concept's own flyer script survived"
    assert html.count('id="founderAd"') == 1


def test_the_links_are_the_sites():
    html = _home()
    body = html[html.index("<body"):]
    assert 'href="https://mysolutionist.app/' not in body
    assert f'href="{mp.APP_URL}"' in body
    for path in ("/start", "/start?plan=founder", "/compare", "/features", "/about", "/news", "/download", "/terms", "/privacy", "/faq"):
        assert f'href="{path}"' in body, path
    assert "mailto:" in body and "__CONTACT_EMAIL__" not in body


def test_the_concept_furniture_is_gone():
    html = _home()
    for marker in ('class="note"', 'id="listenBtn"', 'id="notes"', "Design notes", "cut of the concept", "Concept, not the live site"):
        assert marker not in html, marker
    assert "sample data" in html, "the room's numbers are sample and the page must say so"


def test_the_shell_carries_the_pixel_and_the_beacon():
    html = _home()
    assert "/api/track" in html and "_sol_attr" in html
    assert "__TRIAL_FREE__" not in html and "{{" not in html


def test_no_dash_joined_sentences():
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", _home(), flags=re.S)
    text = re.sub(r'<td><span class="no">—</span></td>|<td>—</td>', "", text)   # a table's "not included" mark is a symbol, not a sentence
    text = re.sub(r"<[^>]+>", " ", text)
    assert " — " not in text and " &mdash; " not in text


def test_every_footer_link_is_a_route():
    try:
        import public_site
    except ImportError as e:   # an optional integration's client missing locally; CI has them all
        pytest.skip(f"public_site needs {e.name}")
    html = _home()
    foot = html[html.index("<footer"):]
    paths = set(re.findall(r'href="(/[^"#?]*)', foot))
    routes = {r.path for r in public_site.router.routes if hasattr(r, "path")}
    for p in paths:
        if p.startswith("/assets/"):
            continue
        assert p in routes or p == "/", f"{p} is not a route"
