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
    assert "/assets/film.mp4?v=2" in html and "/assets/film-poster.jpg?v=3" in html
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


def test_the_plan_matrix_is_the_whole_product():
    """9/12: every row on every plan as a matrix (groups as cards, lit rings,
    dial pills) behind the Compare every plan dropdown UNDER the pricing, so
    Starter shows what it includes and not a column of dashes. The
    seven-tools chapter sits ABOVE the pricing."""
    html = _home()
    assert 'id="cmpMore"' in html and "Compare every plan" in html
    i = html.index('class="matrix"')
    seg = html[i:html.index("</details>", i)]
    rows = re.findall(r'<div class="mx-row">(.*?)</div>(<span class="mx-cell">.*?)</div>', seg, re.S)
    assert len(rows) >= 40, f"only {len(rows)} rows"
    for _what, cells in rows:
        assert cells.count('<span class="mx-cell">') == 3, _what
    assert "Contacts &amp; CRM" in seg and "Audit trail" in seg and "Team seats" in seg
    starter_ticks = sum(1 for _w, c in rows if c.startswith('<span class="mx-cell"><i class="ok">'))
    assert starter_ticks >= 25, "Starter should read as a column of what it includes"
    prices = pricing_config.tier_price_cents()
    assert f'Professional<b>${prices["professional"] // 100}</b>' in seg
    assert html.index('id="compare"') < html.index('id="pricing"') < html.index('id="plans"') < html.index('id="faq"')


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


# ── 2026-09-22: the approved upgrades (concept v19) ──────────────────────
# Kevin approved these from a clickable preview of the live page. Each
# test pins one of them so a later concept re-import cannot drop it, and
# the last one pins what was deliberately NOT shipped.

def _section(html: str, marker: str, end: str = "</section>") -> str:
    i = html.index(marker)
    return html[i:html.index(end, i)]


def test_phone_nav_keeps_log_in_and_opens_a_menu():
    html = _home()
    assert 'id="navBurger"' in html and 'aria-controls="mobileMenu"' in html
    menu = html[html.index('id="mobileMenu"'):html.index('id="thumbBar"')]
    for anchor in ("#what", "#rooms", "#trust", "#compare", "#pricing", "#faq"):
        assert f'href="{anchor}"' in menu, anchor
    assert f'href="{mp.APP_URL}"' in menu and 'href="/start"' in menu
    # the founding popup waits while this menu is open; it looks it up by this id
    assert html.count('id="mobileMenu"') == 1
    # at 520 and under Log in stays and the primary Start hides
    assert "nav.top .right .btn.sm.primary{display:none}" in html
    assert "nav.top .right .btn.sm:not(.primary){display:none}" not in html
    assert "e.key==='Escape'&&!menu.hidden" in html


def test_the_phone_page_never_scrolls_itself():
    html = _home()
    assert "{autoSay=true;typeSay(SAY[trade])}" in html
    assert "const phoneAuto=autoSay&&!tourOn&&matchMedia('(max-width:760px)').matches" in html
    assert "if(!phoneAuto)setTimeout(()=>roomEl.scrollIntoView(" in html


def test_the_thumb_bar():
    html = _home()
    bar = html[html.index('id="thumbBar"'):html.index("</div>", html.index('id="thumbBar"'))]
    assert 'id="thumbAsk"' in bar and f'href="{mp.APP_URL}"' in bar and 'href="/start"' in bar
    assert "Start free trial" in bar
    assert "#askFab{display:none}" in html and "footer{padding-bottom:90px}" in html
    assert "document.body.classList.contains('pre')" in html   # hidden while the intro plays


def test_the_typed_line_and_the_laptop_fit():
    html = _home()
    assert "font:500 clamp(18px,4.9vw,24px) var(--display)" in html
    assert "min-width:260px;flex:1 1 400px;" in html
    # the old calc(length / number) was invalid CSS and cropped the laptop on phones
    assert "/ 1000 * .95" not in html
    assert ".lap{transform:scale(var(--lapS,.34))}" in html
    assert "new ResizeObserver(fitLap)" in html
    assert "overflow-x:clip" not in html, "clipping the page breaks the sticky nav"


def test_the_stuck_nav_is_solid():
    html = _home()
    assert "nav.top.stuck{background:rgba(7,8,11,.965)" in html and "backdrop-filter:blur(14px)}" in html


def test_the_film_has_chapters():
    html = _home()
    ch = html[html.index('id="filmChapters"'):html.index("</div>", html.index('id="filmChapters"'))]
    assert re.findall(r'data-t="(\d+)"', ch) == ["3", "12", "21", "27", "36", "42"]
    for name in ("Sign in", "Say it", "Run the day", "Be found", "Bring what you have", "The night shift"):
        assert f"<b>{name}</b>" in ch, name
    assert html.index('id="filmInline"') < html.index('id="filmChapters"')
    assert "radial-gradient(60% 70% at 50% 50%,rgba(7,8,11,.86)" in html


def _render_with_prices(monkeypatch, starter, pro, sol):
    real = dict(pricing_config.tier_price_cents())
    real.update({"starter": starter * 100, "professional": pro * 100, "practice": sol * 100})
    monkeypatch.setattr(pricing_config, "tier_price_cents", lambda: dict(real))
    return mp.render_home()


def test_the_worth_chapter_reads_the_live_professional_price(monkeypatch):
    html = _render_with_prices(monkeypatch, 81, 157, 311)
    worth = _section(html, 'id="worth"')
    assert 'data-pro="157"' in worth and "what Professional costs, $157 a month" in worth
    assert "$149" not in worth
    assert html.index('id="worth"') < html.index('id="pricing"')
    assert "Assumes Chief fills a third of the missed slots" in worth, "the math says what it assumes"
    for trade in ("barber", "therapist", "contractor", "coach"):
        assert f'data-t="{trade}"' in worth
    assert "attributeFilter:['aria-pressed']" in html   # it follows the hero's trade chips


def test_ask_this_page_uses_the_live_prices(monkeypatch):
    html = _render_with_prices(monkeypatch, 81, 157, 311)
    box = html[html.index('id="pageAsk"'):html.index("</div>", html.index('id="pageAsk"'))]
    assert 'data-starter="81" data-pro="157" data-sol="311"' in box
    assert html.index('id="pageAsk"') < html.index("<details><summary>", html.index('id="faq"'))
    assert "These answers come from this page" in html
    assert "Website Concierge" not in html
    script = html[html.index("var box=$('#pageAsk')"):]
    script = script[:script.index("</script>")]
    assert "founding" not in script.lower() and "$99" not in script, "no founder price the renderer does not fill"
    assert "days free" not in script.replace(mp._trial_free_phrase(), "") and "__TRIAL_FREE__" not in script
    assert "__CONTACT_EMAIL__" not in script


def test_the_structured_data_matches_the_dials(monkeypatch):
    import json
    html = _render_with_prices(monkeypatch, 81, 157, 311)
    head = html[:html.index("</head>")]
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', head, re.S).group(1)
    graph = {n["@type"]: n for n in json.loads(raw)["@graph"]}
    assert graph["Organization"]["url"] == "https://mysolutionist.app/"
    offers = {o["name"]: o["price"] for o in graph["SoftwareApplication"]["offers"]}
    assert offers == {"Starter": "81", "Professional": "157", "Solutionist": "311"}
    qs = graph["FAQPage"]["mainEntity"]
    page_qs = re.findall(r"<details><summary>(.*?)</summary>", _section(html, 'id="faq"'))
    assert [q["name"] for q in qs] == [re.sub(r"<[^>]+>", "", q) for q in page_qs] and len(qs) >= 6
    trial = next(q for q in qs if "free trial" in q["name"])
    assert mp._trial_free_phrase() in trial["acceptedAnswer"]["text"] and "__TRIAL_FREE__" not in raw


def test_what_was_not_approved_did_not_ship():
    html = _home()
    for marker in ("sample quote", "verify one", 'id="proof"', "pv-", "Preview, not live",
                   "Hedera topic 0.0.", "draft signature", "Seat 01 is open", "pvSeats", "Mark changes on the page"):
        assert marker not in html, marker
