"""The Solutionist voice on the public site, and one brand with three front pages.

Kevin, 2026-10-22: "build the voice system to function properly as
suggested. the changes to website one brand three front pages. can we leave
barbers and lawyers on the site?" These pin it:

  1. THE VOICE HOLDS: no page a visitor can open says trade, software, or
     calls Chief an AI agent or assistant (brand_voice.AVOID), counting what a
     screen reader speaks and the prose the page's scripts put on screen.
  2. THE CHECKER READS WHAT VISITORS READ, and never a class name, an id or a
     URL parameter.
  3. ONE BRAND, THREE FRONT PAGES: /churches and /coaches are the home page
     with their own first screen and only their own kinds of business;
     /consultants is the coaches page with consultants first.
  4. NOBODY IS DROPPED: the home still lists all seven kinds of business,
     barbers and law practices among them, with churches and coaches first.
  5. THE PAGES ARE ROUTES, ahead of the catch-all, and in the sitemap.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

import brand_voice
import marketing_home_v3 as v3
import marketing_pages as mp


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.delenv("HOME_EDITION", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


def _pages():
    return {
        "/": mp.render_home(),
        "/churches": v3.render_edition("churches"),
        "/coaches": v3.render_edition("coaches"),
        "/consultants": v3.render_edition("coaches", first="consult"),
        "/features": mp.render_features(),
        "/compare": mp.render_compare(),
        "/faq": mp.render_faq(),
        "/about": mp.render_about(),
        "/get-started": mp.render_get_started(),
    }


def _ed(html: str):
    return json.loads(re.search(r"const ED = (null|\{.*?\});", html).group(1))


# ─── 1. the voice holds ──────────────────────────────────────────────

def test_every_public_page_speaks_in_the_voice():
    bad = [f"{path}: {word!r} (say {say}) in: {ctx}"
           for path, html in _pages().items()
           for word, say, ctx in brand_voice.offenses(html)]
    assert not bad, "\n".join(bad)


def test_the_hero_says_chief_not_an_ai_assistant():
    home = mp.render_home()
    assert "One system for the whole business. Chief keeps it moving" in home
    assert "ai chief of staff" not in home.lower()


# ─── 2. the checker reads what visitors read ─────────────────────────

def test_the_checker_reads_what_visitors_read():
    page = """<html><head><meta name="description" content="Software for every trade">
<style>.trade-list{color:red} /* the trade ticker */</style></head><body>
<div class="trade-list" data-trade="barber" id="trades">Plain words.</div>
<p>Pick your trade</p><button aria-label="Pick a trade">x</button><!-- the trade list -->
<script>
/* the one trade switch: it's the picker */
const KEY = 'trade'; q.set('trade', 1); const R = /[’']s?/i; // don't count this trade
const t = { label: 'Seven trades it already speaks', id: 'trade' };
const h = `<span class="trade">Chief, your AI assistant</span>`;
</script></body></html>"""
    words = sorted(w.lower() for w, _, _ in brand_voice.offenses(page))
    assert words == ["ai assistant", "software", "trade", "trade", "trade", "trades"], words


def test_the_checker_skips_code_it_cannot_read_as_prose():
    js = "const a = 'it''s'; const b = x / 2 / y; const c = 'Seven trades'; const d = /'/; const e = 'last trade';"
    strings = brand_voice._js_strings(js)
    assert "Seven trades" in strings and "last trade" in strings


# ─── 3. one brand, three front pages ─────────────────────────────────

def test_the_home_is_the_whole_brand_and_points_at_both_editions():
    home = mp.render_home()
    assert _ed(home) is None
    assert 'class="h-hero" id="heroH"><span class="l1">Every problem</span>' in home
    assert '<p class="lbl">Seven kinds of business it already speaks</p>' in home
    for path in ("/churches", "/coaches"):
        assert f'<a class="arrow-link" href="{path}">' in home, path   # Who it's for
        assert home[home.index("<footer"):].count(f'href="{path}"') == 1, path
    assert 'class="hero-proof' not in home


@pytest.mark.parametrize("key,first,trades", [
    ("churches", "", ["ministry", "nonprofit"]),
    ("coaches", "", ["coach", "consult"]),
    ("coaches", "consult", ["consult", "coach"]),
])
def test_an_edition_is_the_home_with_its_own_first_screen(key, first, trades):
    ed = v3.EDITIONS[key]
    html = v3.render_edition(key, first=first)
    assert _ed(html) == {"key": ed["path"].strip("/"), "trades": trades}
    assert f'<h1 class="h-hero ed" id="heroH">{ed["h1"]}</h1>' in html
    assert f"<title>{ed['title']} &middot; The Solutionist System</title>" in html
    assert f'<link rel="canonical" href="https://mysolutionist.app{ed["path"]}">' in html
    assert f'<meta name="description" content="{ed["description"]}">' in html
    assert ed["lede"] in html and ed["who"] in html
    for p in ed["proof"]:
        assert f"<li>{p}</li>" in html, p
    assert "Every problem</span>" not in html                        # the home's first screen is gone
    assert '<div class="wrap ticker" hidden role="group"' in html    # the list of every kind is the home's
    assert "const run = !ED && " in html                             # and it stays on its own kind
    assert 'href="/">See every kind of business' in html             # and the way back to it is there
    assert "Every problem has a solution." in html                   # the brand line stays in the footer
    word = re.search(r"\{ id: '" + trades[0] + r"', chip: '[^']*', word: '([^']*)'", html).group(1)
    assert f'<span class="tell-typed" id="typed">{word}</span>' in html


def test_the_church_page_sizes_the_plans_and_drops_the_dollar_calculator():
    html = v3.render_edition("churches")
    assert v3.EDITIONS["churches"]["pricing"] in html
    assert "we never take a cut of your giving" in html
    assert '<div class="wrap worth" hidden>' in html and 'href="#worth"' not in html
    coach = v3.render_edition("coaches")
    assert '<div class="wrap worth">' in coach and 'href="#worth"' in coach


def test_the_calculator_list_is_the_pages_own():
    html = mp.render_home()
    block = re.search(r"const CALC = \{(.*?)\n\};", html, flags=re.S).group(1)
    assert tuple(re.findall(r"^\s*(\w+): \{", block, flags=re.M)) == v3._CALC_TRADES


def test_every_edition_kind_of_business_is_on_the_page():
    ids = set(re.findall(r"^  \{ id: '(\w+)'", mp.render_home(), flags=re.M))
    for ed in v3.EDITIONS.values():
        assert set(ed["trades"]) <= ids, ed["trades"]


# ─── 4. nobody is dropped ────────────────────────────────────────────

def test_barbers_and_law_practices_stay_on_the_home():
    home = mp.render_home()
    order = re.search(r"const ORDER = ED \? ED\.trades : (\[.*?\]);", home).group(1)
    order = json.loads(order.replace("'", '"'))
    assert order[:3] == ["ministry", "coach", "consult"], "churches and coaches lead"
    assert {"barber", "law", "build", "nonprofit"} <= set(order) and len(order) == 7
    assert "'Barbers & salons'" in home and "'Attorneys'" in home


def _page_script(html: str) -> str:
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    return max(scripts, key=len)


@pytest.mark.parametrize("path", ["/", "/churches", "/coaches", "/consultants"])
def test_the_page_script_still_parses(path, tmp_path):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    f = tmp_path / "page.js"
    f.write_text(_page_script(_pages()[path]), encoding="utf-8")
    res = subprocess.run(["node", "--check", str(f)], capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr


def test_the_edition_order_runs_as_written():
    """Run the page's own ordering lines in node against its own list."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    html = v3.render_edition("coaches", first="consult")
    block = re.search(r"(const ED = .*?)\nlet cur = T\[0\];", html, flags=re.S).group(1)
    src = ("const T = ['barber','law','build','coach','consult','ministry','nonprofit'].map((id) => ({ id }));\n"
           "const CALC = { barber: {}, law: {}, build: {}, coach: {} };\n"
           + block + "\nconsole.log(JSON.stringify({ t: T.map((x) => x.id), c: Object.keys(CALC) }));")
    res = subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == {"t": ["consult", "coach"], "c": ["coach"]}


# ─── 5. the pages are routes ─────────────────────────────────────────

def test_the_front_pages_are_routes_ahead_of_the_catch_all_and_in_the_sitemap():
    try:
        import public_site
    except ImportError as e:
        pytest.skip(f"public_site needs {e.name}")
    paths = [getattr(r, "path", "") for r in public_site.router.routes]
    catch_all = paths.index("/{path:path}")
    for p in ("/churches", "/coaches", "/consultants"):
        assert p in paths and paths.index(p) < catch_all, p
    listed = {p for p, _ in public_site._MARKETING_SITEMAP_PATHS}
    assert {"/churches", "/coaches"} <= listed and "/consultants" not in listed   # an alias, canonical /coaches
