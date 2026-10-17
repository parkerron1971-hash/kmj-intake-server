"""The Love City Church site (sites/love-city-church/) builds clean.

Every page renders through build.py, home included; no build-time token is
left in a page; no recipient email address ever reaches the HTML (the old
SnapPages forms printed theirs in the page source); and site_sync installs
the site only into the church's own row.
"""
from __future__ import annotations

import html.parser
import importlib.util
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_sync  # noqa: E402

SITE = os.path.join(ROOT, "sites", "love-city-church")
SERVE_TIME_TOKENS = {"BUSINESS_EMAIL", "PRODUCTS_SECTION", "GALLERY_SECTION", "TESTIMONIALS_SECTION"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
OLD_RECIPIENTS = ("cityofloveoutreach@gmail.com", "lovecitychurchmi@gmail.com",
                  "colmprayer@gmail.com", "kmccloudjrministries@gmail.com")


def _load_build():
    spec = importlib.util.spec_from_file_location("love_city_site_build", os.path.join(SITE, "build.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def build():
    return _load_build()


@pytest.fixture(scope="module")
def pages(build):
    return build.render_pages()


def test_render_pages_returns_every_page_and_home(build, pages):
    assert "home" in pages
    assert set(pages) == set(build.PAGES)
    for page_id in build.PAGES:
        assert os.path.isfile(os.path.join(SITE, f"{page_id}.html")), page_id


def test_no_build_time_tokens_are_left(pages):
    for name, page in pages.items():
        assert page.startswith("<!DOCTYPE html>"), name
        left = set(re.findall(r"\{\{([A-Z_]+)\}\}", page)) - SERVE_TIME_TOKENS
        assert not left, f"{name}: {sorted(left)}"
        # The platform fills these in place; without them it would append
        # sections before </body>.
        for token in ("PRODUCTS_SECTION", "GALLERY_SECTION", "TESTIMONIALS_SECTION"):
            assert "{{" + token + "}}" in page, f"{name}: {token}"


def test_the_inline_build_renders_too(build):
    inline = build.render_pages(inline=True)
    assert set(inline) == set(build.PAGES)
    assert all("/public/site-assets/" not in p for p in inline.values())


def test_no_recipient_email_is_in_any_page(pages):
    for name, page in pages.items():
        assert EMAIL_RE.findall(page) == [], name
        for addr in OLD_RECIPIENTS:
            assert addr not in page, f"{name}: {addr}"
        assert "mailto:{{BUSINESS_EMAIL}}" in page or "mailto:" not in page, name


def test_assets_are_served_from_the_site_asset_route(build, pages):
    for name, page in pages.items():
        for ref in re.findall(r'src="([^"]+\.webp[^"]*)"', page):
            assert ref.startswith(f"{build.API_BASE}/public/site-assets/love-city-church/"), (name, ref)


def test_every_asset_is_a_sensible_webp():
    names = os.listdir(os.path.join(SITE, "assets"))
    assert names
    for n in names:
        assert re.match(r"^[a-z0-9][a-z0-9_-]{0,63}\.webp$", n), n   # the asset route's own pattern
        assert os.path.getsize(os.path.join(SITE, "assets", n)) < 150_000, n


class _Audit(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.imgs_without_alt = []
        self.fields = []           # (tag, id, name, labelled inline or by aria-label)
        self.label_for = set()
        self.iframes_without_title = []
        self.in_label = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img" and "alt" not in a:
            self.imgs_without_alt.append(a.get("src", "")[:60])
        if tag == "iframe" and not a.get("title"):
            self.iframes_without_title.append(a.get("src"))
        if tag == "label":
            self.in_label += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit"):
            self.fields.append((tag, a.get("id"), a.get("name"), bool(a.get("aria-label")) or self.in_label > 0))

    def handle_endtag(self, tag):
        if tag == "label" and self.in_label:
            self.in_label -= 1


def test_images_have_alt_text_frames_have_titles_and_fields_have_labels(pages):
    for name, page in pages.items():
        audit = _Audit()
        audit.feed(page)
        assert audit.imgs_without_alt == [], name
        assert audit.iframes_without_title == [], name
        for tag, fid, fname, labelled in audit.fields:
            if fname == "website":      # the hidden field only bots fill in
                continue
            assert labelled or (fid and fid in audit.label_for), f"{name}: {tag} {fname} has no label"


def test_forms_post_through_the_one_submission_script(build, pages):
    for name, page in pages.items():
        if "data-church-form" in page:
            assert f"{build.API_BASE}/sites/{build.BUSINESS_ID}/contact-submit" in page, name
            assert page.count("/contact-submit") == 1, name


def _forms(page):
    return re.findall(r"<form\b[^>]*>.*?</form>", page, re.S)


def test_without_script_a_form_can_never_put_a_visitors_words_in_a_url(pages):
    """Review finding 4: a form with no method GETs its fields into the URL
    when script is off. Each church form is method="post", its submit
    button is disabled until forms.js enables it, and the disabled button
    points at a visible note saying how else to reach the church."""
    forms = _forms(pages["connect"])
    assert len(forms) == 2
    for form in forms:
        opening = re.match(r"<form\b[^>]*>", form).group(0)
        assert 'method="post"' in opening, opening
        assert "action=" not in opening, opening
        button = re.search(r'<button type="submit"[^>]*>', form).group(0)
        assert " disabled" in button, button
        fallback_id = re.search(r'aria-describedby="([^"]+)"', button).group(1)
        fallback = re.search(rf'<p class="form-fallback" id="{fallback_id}" data-form-fallback>(.*?)</p>', form, re.S)
        assert fallback and "JavaScript" in fallback.group(1), fallback_id


def test_every_field_is_limited_and_a_full_card_fits_the_endpoint(pages):
    """The endpoint rejects messages above 5,000 characters.
    Every field has a maxlength, every free-text box says its limit
    out loud, and the longest possible message (every box full, every
    choice ticked, every question label) stays under 5,000."""
    forms_js = (SITE + "/forms.js")
    assert "var MAX_MESSAGE = 5000;" in open(forms_js, encoding="utf-8").read()
    for form in _forms(pages["connect"]):
        for tag in re.findall(r'<input\b[^>]*type="(?:text|email|tel)"[^>]*>', form):
            if 'name="website"' in tag:
                continue
            assert re.search(r'maxlength="\d+"', tag), tag
        worst = len("Prayer request") + 2      # the form's title line
        for tag in re.findall(r"<textarea\b[^>]*>", form):
            limit = int(re.search(r'maxlength="(\d+)"', tag).group(1))
            hint_id = re.search(r'aria-describedby="([^"]+)"', tag).group(1)
            hint = re.search(rf'id="{hint_id}">([^<]+)<', form).group(1)
            assert f"{limit:,}" in hint, (hint, limit)
            worst += limit
        labels = re.findall(r"<(?:label|legend)\b[^>]*>(.*?)</(?:label|legend)>", form, re.S)
        worst += sum(len(re.sub(r"<[^>]+>", "", l)) + 3 for l in labels)   # every question and every answer label
        assert worst < 5000, worst


def test_service_times_and_address_are_real_text(pages):
    for name, page in pages.items():
        for text in ("Sundays", "11am", "Thursdays", "6pm", "1084 Allen Ave", "Muskegon, MI 49442"):
            assert text in page, f"{name}: {text}"
    assert "We love." in pages["home"] and "Love City Church" in pages["home"]
    # Kevin: the midweek service is Thursday 6pm. The old site's Wednesday
    # time (and its "Refuel" name) must not come back.
    everything = "".join(pages.values())
    assert not re.search(r"Wednesdays?\W{0,3}(at\W)?\d", everything)
    assert "Refuel" not in everything


class _TextBlocks(html.parser.HTMLParser):
    """The visible text of every small block: a sentence, a list item, a
    term or its description, a ticker word. Containers that merely hold
    several of those (a column, a list) are not one claim."""
    BLOCKS = {"p", "li", "dt", "dd", "span", "a", "strong", "address", "figcaption",
              "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "title"}

    def __init__(self):
        super().__init__()
        self.open, self.blocks, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "meta" and dict(attrs).get("name") == "description":
            self.blocks.append(dict(attrs).get("content", ""))
        if tag in self.BLOCKS:
            self.open.append([tag, ""])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == tag:
                self.blocks.append(self.open.pop(i)[1])
                break

    def handle_data(self, data):
        if not self.skip:
            for block in self.open:
                block[1] += data


def test_thursday_is_never_tied_to_the_church_address(pages):
    """Review finding 3, with Kevin's wording kept: Thursday is "Thursdays
    6pm, Mid-week Bible study" and no sentence, item or ticker word puts it
    at 1084 Allen Ave. The address belongs to Sunday (and the pantry)."""
    for name, page in pages.items():
        parser = _TextBlocks()
        parser.feed(page)
        for text in parser.blocks:
            assert not ("Thursday" in text and "Allen" in text), f"{name}: {text.strip()[:160]!r}"
    for name in ("home", "visit", "events"):
        assert "Mid-week Bible study" in pages[name], name
    js = open(SITE + "/site.js", encoding="utf-8").read()
    thursday = next(line for line in js.splitlines() if "day: 4" in line)
    assert "Allen" not in thursday and "where: ''" in thursday, thursday
    assert "' at 1084 Allen Ave'" not in js.split("'Happening now: '")[1].split(";")[0]


def _contrast(a, b):
    def lum(hexcol):
        rgb = [int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_empty_weekday_labels_meet_aa_contrast_on_both_backgrounds():
    """Review finding 6: the labels of days with nothing on are body-size
    text, so 4.5:1, on the paper and on the 'today' tint."""
    css = open(SITE + "/site.css", encoding="utf-8").read()
    var = lambda n: re.search(rf"--{n}: (#[0-9A-Fa-f]{{6}});", css).group(1)
    rule = re.search(r"\.week li:not\(\.has\) \{ color: ([^;]+); \}", css).group(1)
    colour = var(rule[6:-1]) if rule.startswith("var(") else rule
    for bg in ("paper", "paper-2"):
        assert _contrast(colour, var(bg)) >= 4.5, (colour, bg, round(_contrast(colour, var(bg)), 2))


def test_home_marks_its_own_menu_link_as_the_current_page(pages):
    """Review finding 10: every page marks its menu link aria-current,
    Home included."""
    assert '<a href="/" aria-current="page">Home</a>' in pages["home"]
    assert pages["visit"].count('aria-current="page"') >= 1
    assert 'aria-current="page">Home' not in pages["visit"]


def test_every_internal_link_lands_on_a_page_the_site_builds(build, pages):
    for name, page in pages.items():
        for href in re.findall(r'href="(/[^"]*)"', page):
            if href in build.CARDS.values():
                continue  # one of the church's cards (next tests)
            path = href.split("#")[0].split("?")[0].strip("/")
            assert path == "" or path in build.PAGES, f"{name}: {href}"
            if "#" in href and path:
                anchor = href.split("#", 1)[1]
                assert f'id="{anchor}"' in pages[path], f"{name}: {href} has no target"


CARD_RE = re.compile(r"/public/widget/form/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def test_the_ministry_buttons_open_the_churchs_own_cards(build, pages):
    """'I want to be baptized' and 'I want to serve' open the Baptism and
    Serve with us cards made in the app, where the Next steps road counts
    the answers, instead of the connect card with a box ticked."""
    assert build.CARDS and all(CARD_RE.fullmatch(href) for href in build.CARDS.values())
    page = pages["ministries"]
    assert f'href="{build.CARDS["CARD_BAPTISM"]}">I want to be baptized</a>' in page
    assert f'href="{build.CARDS["CARD_SERVE"]}">I want to serve</a>' in page
    assert "interest=baptism" not in page and "interest=serve" not in page


# Both ways a visitor reaches the church: its platform subdomain, and its
# own domain, which arrives through the Cloudflare worker with the API host
# in Host and the visitor's hostname in X-Original-Host.
CHURCH_HOSTS = {
    "subdomain": {"host": "love-city-church.mysolutionist.app"},
    "custom-domain": {"host": "kmj-intake-server-production.up.railway.app", "x-original-host": "lovecityc.com"},
}


@pytest.fixture(scope="module")
def real_app():
    import kmj_intake_automation
    return kmj_intake_automation.app


@pytest.mark.parametrize("hosts", CHURCH_HOSTS.values(), ids=CHURCH_HOSTS.keys())
def test_every_page_path_reaches_the_church_site_through_the_real_routers(build, real_app, hosts, monkeypatch):
    """Review finding 1: the app registers ~100 routers before the public-site
    catch-all, and the authenticated GET /live answered 401 for the church's
    /live page. This sends every page path through the real app, routers in
    their real order, and requires the church-site renderer to answer. Only
    the renderer at the very end is stubbed (it reads the database)."""
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient
    import public_site

    async def site(name, path="/", **kwargs):
        return HTMLResponse(f"church-site {path}")
    monkeypatch.setattr(public_site, "_serve_site_by_slug", site)
    monkeypatch.setattr(public_site, "_serve_site_by_custom_domain", site)
    monkeypatch.setattr(public_site, "_check_rate", lambda *a, **k: True)

    client = TestClient(real_app)
    for page in build.PAGES:
        path = "/" if page == "home" else f"/{page}"
        r = client.get(path, headers=hosts)
        assert (r.status_code, r.text) == (200, f"church-site {path}"), \
            f"{path} on {hosts}: {r.status_code} {r.text[:120]}"


@pytest.mark.parametrize("hosts", CHURCH_HOSTS.values(), ids=CHURCH_HOSTS.keys())
def test_every_card_button_opens_its_card_or_its_closed_page(build, pages, real_app, hosts, monkeypatch):
    """A card button, through the real routers on both church addresses,
    opens that card. Switched off in the app, the same link shows the
    card's closed page with the way back to lovecityc.com, never the JSON
    "Form not found" a visitor saw before. Only the reads are stubbed."""
    from fastapi.testclient import TestClient
    import chief_form_actions
    import intake_endpoint
    import public_site

    live = {"on": True}

    async def db(client, method, path, body=None):
        if path.startswith("/intake_forms"):
            if ("is_active=eq.true" in path) != live["on"]:
                return []
            return [{"id": path.split("id=eq.", 1)[1].split("&", 1)[0], "business_id": build.BUSINESS_ID,
                     "name": "Baptism", "fields": [{"name": "name", "label": "Your name"}], "settings": {}}]
        if path.startswith("/businesses"):
            return [{"id": build.BUSINESS_ID, "name": "Love City Church", "type": "church", "settings": {}}]
        if path.startswith("/business_sites"):
            return [{"business_id": build.BUSINESS_ID, "slug": build.SLUG, "status": "published",
                     "html_content": pages["home"]}]
        return []
    monkeypatch.setattr(intake_endpoint, "supabase_request", db)
    monkeypatch.setattr(chief_form_actions, "public_form_url",
                        lambda b, f: f"https://lovecityc.com/public/widget/form/{f}")
    monkeypatch.setattr(public_site, "_check_rate", lambda *a, **k: True)

    client = TestClient(real_app)
    for href in build.CARDS.values():
        live["on"] = True
        r = client.get(href, headers=hosts)
        assert r.status_code == 200 and 'id="client-form"' in r.text, f"{href} on {hosts}: {r.status_code}"
        live["on"] = False
        r = client.get(href, headers=hosts)
        assert r.status_code == 404 and r.headers["content-type"].startswith("text/html"), href
        assert "isn’t taking answers right now" in r.text and 'id="client-form"' not in r.text
        assert 'href="https://lovecityc.com/"' in r.text and "Back to Love City Church" in r.text


def test_every_old_address_has_a_home_and_installs_cleanly(build, pages):
    from site_page_helpers import clean_redirects
    kept, skipped = clean_redirects(build.REDIRECTS, pages)
    assert skipped == [] and kept == build.REDIRECTS
    # The old paths the domain runbook names (risk R5).
    for old, new in {"/what-we-believe": "/beliefs", "/mission-and-vision": "/about",
                     "/connect-with-us": "/connect", "/prayer-request": "/connect",
                     "/i-m-new": "/visit", "/welcomehome": "/visit",
                     "/services-and-events": "/events", "/media": "/sermons",
                     "/subsplash-media": "/sermons"}.items():
        assert build.REDIRECTS[old].split("?")[0].split("#")[0] == new, old
    # The old sign-up pages open the church's cards, the same ones the
    # Ministries buttons open.
    for old, card in {"/baptism": "CARD_BAPTISM", "/volunteer": "CARD_SERVE",
                      "/ministryworks": "CARD_SERVE", "/city-serve": "CARD_SERVE"}.items():
        assert build.REDIRECTS[old] == build.CARDS[card], old
    # GET /live is an API route ahead of the site. Redirecting it needs the
    # Worker to vouch for the host first (worklog follow-up).
    assert "/live" not in build.REDIRECTS


def test_every_redirect_anchor_and_ticked_interest_exists(build, pages):
    for old, new in build.REDIRECTS.items():
        page = new.split("?")[0].split("#")[0].strip("/") or "home"
        if "#" in new:
            assert f'id="{new.split("#", 1)[1]}"' in pages[page], f"{old} -> {new}"
        if "interest=" in new:
            interest = new.split("interest=", 1)[1].split("#")[0]
            assert f'data-interest="{interest}"' in pages[page], f"{old} -> {new}"


@pytest.mark.parametrize("hosts", CHURCH_HOSTS.values(), ids=CHURCH_HOSTS.keys())
def test_every_old_address_reaches_the_church_site(build, real_app, hosts, monkeypatch):
    """No API route may answer an old address before the church site does,
    so every entry in the map can actually be served."""
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient
    import public_site

    async def site(name, path="/", **kwargs):
        return HTMLResponse(f"church-site {path}")
    monkeypatch.setattr(public_site, "_serve_site_by_slug", site)
    monkeypatch.setattr(public_site, "_serve_site_by_custom_domain", site)
    monkeypatch.setattr(public_site, "_check_rate", lambda *a, **k: True)

    client = TestClient(real_app, follow_redirects=False)
    for old in build.REDIRECTS:
        path = old.replace("/*", "/page/2")
        r = client.get(path, headers=hosts)
        assert (r.status_code, r.text) == (200, f"church-site {path}"), \
            f"{path} on {hosts}: {r.status_code} {r.text[:120]}"


CHURCH_BUSINESS_ID = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"


def _church_mod():
    return next(m for m in site_sync.discover() if m.SLUG == "love-city-church")


def _fake_sites_table(monkeypatch, rows):
    """site_sync against an in-memory business_sites table; returns its writes."""
    import sb_clients
    monkeypatch.setenv("SITE_CHECK", "off")
    monkeypatch.setenv("SITE_ADOPT", "off")
    patches = []

    def patch(path, body):
        patches.append((path, body))
        for row in rows:
            row.update(body)

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: rows)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    return patches


def test_the_site_belongs_to_the_churchs_own_business(build):
    assert (build.SLUG, build.BUSINESS_ID) == ("love-city-church", CHURCH_BUSINESS_ID)
    assert _church_mod().BUSINESS_ID == CHURCH_BUSINESS_ID


def test_without_a_row_nothing_is_installed(monkeypatch):
    patches = _fake_sites_table(monkeypatch, [])
    assert site_sync.sync_site(_church_mod()) == "no-row"
    assert patches == []


def test_a_row_owned_by_another_business_is_never_touched(monkeypatch):
    patches = _fake_sites_table(monkeypatch, [
        {"id": "row-1", "business_id": "3f1c2b9e-0000-4000-8000-000000000001",
         "html_content": "<html>someone else's</html>", "site_config": {}}])
    assert site_sync.sync_site(_church_mod()) == "wrong-business"
    assert patches == []


def test_the_churchs_own_row_installs_once_then_stays_current(pages, monkeypatch):
    patches = _fake_sites_table(monkeypatch, [
        {"id": "row-1", "business_id": CHURCH_BUSINESS_ID,
         "html_content": "<html>the row Giving made</html>",
         "site_config": {"html_source": "module-composer"}}])
    assert site_sync.sync_site(_church_mod()) == "installed"
    assert site_sync.sync_site(_church_mod()) == "current"
    assert len(patches) == 1
    path, body = patches[0]
    assert path == "/business_sites?id=eq.row-1"
    assert body["html_content"] == pages["home"]
    cfg = body["site_config"]
    assert cfg["html_source"] == "manual" and cfg["site_pages"][0] == "home"
    assert set(cfg["site_pages"]) <= set(pages)
    assert cfg["manual_redirects"] == _church_mod().REDIRECTS
    # What was there before is kept, so the install can be undone.
    assert cfg["manual_backup"]["html_content"] == "<html>the row Giving made</html>"


# ---------------------------------------------------------------------------
# In a real browser (CI installs playwright's chromium before pytest). The
# production render is served at a made-up origin; every other request
# (Google Fonts, images, embeds) is refused, which is also how the
# font-failure check gets its failure. forms.js's fetch is replaced by a
# stub per test, so nothing is ever sent anywhere.
# ---------------------------------------------------------------------------
ORIGIN = "https://church.test/"
_NEEDS_EMAIL = re.compile(r"<([a-z][a-z0-9]*)\b[^>]*\bdata-needs-email\b[^>]*>.*?</\1>", re.S | re.I)
FETCH_STUB = """
window.__sent = [];
window.__respond = {status: 200, body: {ok: true}};
window.fetch = function (url, opts) {
  window.__sent.push({url: url, body: JSON.parse(opts.body)});
  var r = window.__respond;
  if (r === 'network') return Promise.reject(new TypeError('Failed to fetch'));
  return Promise.resolve(new Response(JSON.stringify(r.body), {status: r.status, headers: {'Content-Type': 'application/json'}}));
};
"""


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as e:  # no chromium on this machine
        pytest.skip(f"chromium is not available: {e}")
    yield b
    b.close()
    pw.stop()


def _context(browser, pages, **kw):
    # The platform drops data-needs-email blocks when no sender is verified.
    served = {k: _NEEDS_EMAIL.sub("", v) for k, v in pages.items()}
    ctx = browser.new_context(**kw)

    def route(r):
        url = r.request.url
        if not url.startswith(ORIGIN):
            return r.abort()
        path = url[len(ORIGIN):].split("#")[0].split("?")[0].strip("/") or "home"
        if path in served:
            return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=served[path])
        return r.fulfill(status=404, body="")
    ctx.route("**/*", route)
    return ctx


SHARE_TEAM = '[name="share"][value="Our prayer team may pray over this with me"]'
SHARE_PASTORS = '[name="share"][value="Keep this with the pastors only"]'


def _send_prayer(page, response, share=SHARE_TEAM):
    page.evaluate("r => { window.__respond = r; }", response)
    page.fill("#pr-request", "Please pray for my mother's surgery on Friday.")
    page.fill("#pr-first", "Ann")
    page.fill("#pr-email", "ann@example.org")
    page.check(share)                       # "Who prays with you?" is required
    page.click('[data-church-form="prayer-request"] button[type="submit"]')
    note = page.locator('[data-church-form="prayer-request"] [data-form-note]')
    page.wait_for_function("el => el.textContent && el.textContent !== 'Sending…'", arg=note.element_handle())
    return note


def test_a_form_only_says_thank_you_when_the_endpoint_says_ok(browser, pages):
    """Review finding 2: HTTP 200 can carry {ok: false}. Only {ok: true}
    clears the form and thanks the visitor; anything else keeps every word
    they wrote and says it didn't go."""
    ctx = _context(browser, pages)
    ctx.add_init_script(FETCH_STUB)
    page = ctx.new_page()
    page.goto(ORIGIN + "connect")
    for failure in ({"status": 200, "body": {"ok": False, "error": "Email service error."}},
                    {"status": 500, "body": {}}, {"status": 429, "body": {}}, "network"):
        note = _send_prayer(page, failure)
        assert "err" in note.get_attribute("class"), failure
        assert "still here" in note.text_content(), failure
        assert page.input_value("#pr-request").startswith("Please pray"), failure
        assert page.input_value("#pr-email") == "ann@example.org", failure
    note = _send_prayer(page, {"status": 200, "body": {"ok": True}})
    assert "ok" in note.get_attribute("class") and "praying with you" in note.text_content()
    assert page.input_value("#pr-request") == ""
    sent = page.evaluate("window.__sent")
    assert len({item["body"]["submission_id"] for item in sent}) == 1
    assert sent[-1]["body"]["form"] == "prayer_request"
    assert sent[-1]["body"]["fields"]["request"].startswith("Please pray")
    assert sent[-1]["body"]["fields"]["follow_up"] is False
    assert "Please pray for my mother" in sent[-1]["body"]["message"]
    _send_prayer(page, {"status": 200, "body": {"ok": True}})
    assert page.evaluate("window.__sent.at(-1).body.submission_id") != sent[-1]["body"]["submission_id"]
    ctx.close()


def test_with_script_off_nothing_is_sent_or_put_in_the_url(browser, pages):
    """Review finding 4: with JavaScript off the browser would submit the form
    natively. The submit buttons are disabled, so it can't, and the visitor
    is told how else to reach the church."""
    ctx = _context(browser, pages, java_script_enabled=False)
    page = ctx.new_page()
    requests = []
    page.on("request", lambda req: requests.append((req.method, req.url)))
    page.goto(ORIGIN + "connect")
    for form in ("connect-card", "prayer-request"):
        assert page.locator(f'[data-church-form="{form}"] button[type="submit"]').is_disabled()
        assert page.locator(f'[data-church-form="{form}"] [data-form-fallback]').is_visible()
    page.fill("#pr-request", "A private prayer")
    page.fill("#pr-first", "Review")
    page.fill("#pr-email", "review@example.org")
    page.press("#pr-first", "Enter")       # implicit submission
    page.wait_for_timeout(400)
    assert page.url == ORIGIN + "connect"
    # Only the page and its (refused) fonts and images were ever asked for:
    # no POST, and no URL carrying anything the visitor typed.
    assert all(method == "GET" for method, _ in requests), requests
    assert not [u for _, u in requests if re.search(r"prayer|Review|example\.org|first_name|request=", u)], requests
    assert [u for _, u in requests if u.startswith(ORIGIN)] == [ORIGIN + "connect"], requests
    ctx.close()


def test_the_open_menu_holds_keyboard_focus_and_gives_it_back(browser, pages):
    """Review finding 5: the page behind the open menu is inert, Tab cycles
    between the close control and the menu's links, and closing returns
    focus to the toggle."""
    ctx = _context(browser, pages, viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(ORIGIN + "connect")
    page.click("[data-menu-toggle]")
    assert page.evaluate("document.querySelector('main').inert") is True
    inside = "el => !!el.closest('[data-menu], [data-menu-toggle]')"
    for _ in range(14):
        page.keyboard.press("Tab")
        assert page.evaluate(f"({inside})(document.activeElement)"), page.evaluate("document.activeElement.outerHTML")
    page.focus("[data-menu-toggle]")
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.textContent") == "Connect"   # the last menu link
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.hasAttribute('data-menu-toggle')")
    assert page.evaluate("document.querySelector('main').inert") is False
    ctx.close()


def test_when_the_font_fails_nothing_runs_off_a_360px_screen(browser, pages):
    """Review finding 8: Archivo is refused here (every outside request is),
    so headings fall back to a local font. No page may scroll sideways, and
    no poster line may clip its words, at 360px wide."""
    ctx = _context(browser, pages, viewport={"width": 360, "height": 740})
    page = ctx.new_page()
    for name in pages:
        page.goto(ORIGIN + ("" if name == "home" else name))
        page.wait_for_timeout(250)
        # the font really failed: no Archivo face loaded on this page
        assert page.evaluate("[...document.fonts].some(f => f.family.replace(/\"/g, '') === 'Archivo' && f.status === 'loaded')") is False
        sizes = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert sizes[0] <= sizes[1], f"{name}: page is {sizes[0]}px wide on a {sizes[1]}px screen"
        clipped = page.evaluate("""[...document.querySelectorAll('.poster .line')]
            .filter(l => l.scrollWidth > l.clientWidth + 1).map(l => l.textContent.trim())""")
        assert clipped == [], f"{name}: clipped {clipped}"
    ctx.close()


@pytest.mark.parametrize("kind", ["connect-card", "prayer-request"])
def test_structured_forms_succeed_when_saved_without_notification(browser, pages, kind):
    """No recipient is configured: saved answers still thank the visitor.
    Exercise the real form controls and script, then validate the sent payload
    with the backend contract. No live endpoint or email is contacted.
    """
    from website_forms import validate
    ctx = _context(browser, pages)
    ctx.add_init_script(FETCH_STUB)
    page = ctx.new_page()
    page.goto(ORIGIN + "connect?interest=next-step")
    response = {"status": 200, "body": {"ok": True, "notification_sent": False}}
    if kind == "prayer-request":
        page.check("#pr-follow")
        note = _send_prayer(page, response)
        expected = {"request": "Please pray for my mother's surgery on Friday.",
                    "first_name": "Ann", "follow_up": True,
                    "share": "Our prayer team may pray over this with me"}
        empty_field = "#pr-request"
    else:
        page.evaluate("r => { window.__respond = r; }", response)
        page.fill("#cc-first", "Dana")
        page.fill("#cc-last", "Rivers")
        page.fill("#cc-email", "dana@example.org")
        page.fill("#cc-phone", "555-123-4567")
        page.check('[name="visits"][value="A few times"]')
        assert page.is_checked('[data-interest="next-step"]')
        page.check('[data-interest="leaderschool"]')
        page.select_option("#cc-heard", label="A Love City member")
        page.fill("#cc-notes", "Please tell me about the next class.")
        page.click('[data-church-form="connect-card"] button[type="submit"]')
        note = page.locator('[data-church-form="connect-card"] [data-form-note]')
        page.wait_for_function("el => el.textContent && el.textContent !== 'Sending…'", arg=note.element_handle())
        expected = {"first_name": "Dana", "last_name": "Rivers", "visits": "A few times",
                    "heard_from": "A Love City member", "notes": "Please tell me about the next class.",
                    "interests": ["Next Step ministry training", "Leaderschool"]}
        empty_field = "#cc-notes"
    assert "ok" in note.get_attribute("class")
    assert "Thank you" in note.text_content()
    assert page.input_value(empty_field) == ""
    sent = page.evaluate("window.__sent")
    assert len(sent) == 1  # a failed notification must never cause a retry
    payload = sent[0]["body"]
    assert payload["form"] == kind.replace("-", "_")
    assert payload["fields"] == expected
    assert validate(payload)["fields"] == expected
    assert "to" not in payload and "recipient" not in payload
    assert CHURCH_BUSINESS_ID in sent[0]["url"]
    ctx.close()


def test_validation_error_is_shown_as_text_and_keeps_answers(browser, pages):
    ctx = _context(browser, pages)
    ctx.add_init_script(FETCH_STUB)
    page = ctx.new_page()
    page.goto(ORIGIN + "connect")
    note = _send_prayer(page, {"status": 400, "body": {"ok": False, "error": "<b>Check your answer</b>"}})
    assert note.text_content() == "<b>Check your answer</b>"
    assert note.locator("b").count() == 0
    assert page.input_value("#pr-request").startswith("Please pray")
    ctx.close()


@pytest.mark.parametrize("missing", ["randomUUID", "crypto"])
def test_form_submission_without_random_uuid(browser, pages, missing):
    ctx = _context(browser, pages)
    ctx.add_init_script(FETCH_STUB)
    ctx.add_init_script("Object.defineProperty(" +
                        ("window.crypto, 'randomUUID'" if missing == "randomUUID" else "window, 'crypto'") +
                        ", {value: undefined});")
    page = ctx.new_page()
    page.goto(ORIGIN + "connect")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    failed = {"status": 503, "body": {"ok": False}}
    _send_prayer(page, failed)
    _send_prayer(page, failed)
    sent = page.evaluate("window.__sent")
    key = sent[0]["body"]["submission_id"]
    assert key and len(key) <= 80 and sent[1]["body"]["submission_id"] == key
    note = _send_prayer(page, {"status": 200, "body": {"ok": True, "notification_sent": False}})
    assert "Thank you" in note.text_content()
    _send_prayer(page, failed)
    assert page.evaluate("window.__sent.at(-1).body.submission_id") != key
    assert not errors
    ctx.close()
