"""Pages that match, wired (2026-10-01, the concept-layer plan, step 6).

- A builder home page gives up its own sections to About / Services /
  Contact on every refresh (no module templates with fixed copy).
- The World concept's offer page is its own builder run, saved beside the
  secondary pages, kept through refreshes, cleared when the concept moves
  off it, and served at its own path."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import builder_v2 as v2  # noqa: E402
import public_site  # noqa: E402
import sb_clients  # noqa: E402
import site_composer  # noqa: E402
from test_site_pages import HOME  # noqa: E402


def _db(monkeypatch, row):
    patched = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [row])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **k: patched.append(body) or [body])
    return patched


# ─── the cut pages ───────────────────────────────────────────────────

def test_a_builder_home_gives_its_sections_to_the_secondary_pages(monkeypatch):
    patched = _db(monkeypatch, {"site_config": {"generated_pages": {"offer": "<html>OFFER</html>"}},
                                "html_content": HOME})
    import site_multipage
    monkeypatch.setattr(site_multipage, "build_secondary_pages",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("module pages")))
    n = site_composer.rebuild_secondary_pages("b1", {"business": {"name": "Marrow & Steel"}}, "acme")
    pages = patched[-1]["site_config"]["generated_pages"]
    assert n == 4 and set(pages) == {"about", "services", "contact", "offer"}
    assert "Two Chairs, Two Barbers" in pages["about"]
    assert pages["offer"] == "<html>OFFER</html>", "the offer page is its own build"


def test_a_module_home_keeps_module_pages(monkeypatch):
    patched = _db(monkeypatch, {"site_config": {}, "html_content": "<html><body><section>x</section></body></html>"})
    import site_multipage
    monkeypatch.setattr(site_multipage, "build_secondary_pages",
                        lambda ctx, slug, title: {"about": "<html>module</html>"})
    assert site_composer.rebuild_secondary_pages("b1", {"business": {"name": "A"}}, "acme") == 1
    assert patched[-1]["site_config"]["generated_pages"] == {"about": "<html>module</html>"}


# ─── the offer page ──────────────────────────────────────────────────

def test_the_offer_page_is_built_with_the_house_style_and_saved(monkeypatch):
    patched = _db(monkeypatch, {"site_config": {"generated_pages": {"about": "<html>A</html>"}}})
    seen = {}

    def _run(spec, ctx, bid, progress_cb=None, page="home", house=""):
        seen.update(page=page, house=house)
        return {"html": "<!DOCTYPE html><html>OFFER</html>", "report": {}}

    monkeypatch.setattr(v2, "run_builder_v2", _run)
    ctx = {"design_spec_text": "0. THE CONCEPT\nINTENSITY: world",
           "offer_page": {"path": "/saturday-shave-club", "name": "Saturday Shave Club"}}
    assert site_composer.build_offer_page("b1", ctx, HOME) is True
    assert seen["page"] == "offer" and ".js .reveal" in seen["house"]
    cfg = patched[-1]["site_config"]
    assert cfg["generated_pages"]["offer"].endswith("OFFER</html>")
    assert cfg["generated_pages"]["about"] == "<html>A</html>"
    assert cfg["offer_page"]["path"] == "/saturday-shave-club"


def test_moving_off_world_clears_the_old_offer_page(monkeypatch):
    patched = _db(monkeypatch, {"site_config": {"generated_pages": {"offer": "<html>OLD</html>"},
                                                "offer_page": {"path": "/club"}}})
    monkeypatch.setattr(v2, "run_builder_v2",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no build")))
    assert site_composer.build_offer_page("b1", {}, HOME) is False
    cfg = patched[-1]["site_config"]
    assert "offer" not in cfg["generated_pages"] and "offer_page" not in cfg


def test_the_offer_page_is_served_at_its_path():
    cfg = {"offer_page": {"path": "/saturday-shave-club"}}
    assert public_site._site_page_id(cfg, "/saturday-shave-club") == "offer"
    assert public_site._site_page_id(cfg, "/about") == "about"
    assert public_site._site_page_id(cfg, "/nope") is None
    assert public_site._site_page_id({}, "/saturday-shave-club") is None


def test_the_preview_keeps_cut_pages_and_the_offer_inside_it():
    html = ('<a href="/services#prices">P</a><a href="/#hero">H</a>'
            '<a href="/saturday-shave-club">Club</a>')
    out = public_site._rewrite_nav_for_preview(html, "acme", {"offer_page": {"path": "/saturday-shave-club"}})
    assert 'href="/public/site/acme/services#prices"' in out
    assert 'href="/public/site/acme#hero"' in out
    assert 'href="/public/site/acme/saturday-shave-club"' in out


# ─── the builder's offer-page mode ───────────────────────────────────

def _offer_doc(endpoint, extra=""):
    return ("<!DOCTYPE html><html><head><title>Club</title>"
            '<meta name="description" content="The club">'
            '<meta property="og:image" content="https://x/a.jpg"></head><body>'
            '<nav><a href="/">Home</a></nav><main><h1>The Saturday Shave Club</h1>'
            + extra + "</main><footer>Club</footer></body></html>")


def test_the_offer_page_is_one_page_not_the_whole_inventory(monkeypatch):
    endpoint = "https://api.example/contact/biz-1"
    calls = []
    monkeypatch.setattr(v2, "_call", lambda s, u, b, spend=None: calls.append(u) or _offer_doc(endpoint))
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: (
        "BUSINESS: x\nIMAGES (every one appears on the page, exact urls):\n- https://x/a.jpg\n"
        "- https://x/b.jpg\nCONTACT FORM ENDPOINT (the form's action): " + endpoint))
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: endpoint)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    ctx = {"offer_page": {"path": "/saturday-shave-club", "name": "Saturday Shave Club"}}
    out = v2.run_builder_v2("0. THE CONCEPT\nINTENSITY: world\nSCOPE: offer (Saturday Shave Club)\n"
                            "1. OVERVIEW\nx", ctx, "biz-1", page="offer", house="STYLES: .x{}")
    assert out["html"], "no every-image or form law on the offer page"
    assert out["report"]["page"] == "offer"
    assert "THIS CALL BUILDS THE OFFER PAGE" in calls[0] and "/saturday-shave-club" in calls[0]
    assert "STYLES: .x{}" in calls[0]


def test_the_home_must_link_its_offer_page(monkeypatch):
    endpoint = "https://api.example/contact/biz-1"
    calls = []
    from test_builder_v2 import _law_passing_doc
    monkeypatch.setattr(v2, "_call", lambda s, u, b, spend=None: calls.append(u) or _law_passing_doc(endpoint))
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: endpoint)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    ctx = {"offer_page": {"path": "/saturday-shave-club", "name": "Saturday Shave Club"}}
    out = v2.run_builder_v2("0. THE CONCEPT\nINTENSITY: world\nSCOPE: offer\n1. OVERVIEW\nx", ctx, "biz-1")
    assert out["html"]
    assert len(calls) == 2 and "OFFER LINK MISSING" in calls[1]


def test_the_live_check_looks_at_the_offer_page_too(monkeypatch):
    import site_check
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "slug": "acme", "html_content": "<html></html>",
        "site_config": {"generated_pages": {"about": "<html>a</html>", "offer": "<html>o</html>"},
                        "offer_page": {"path": "/saturday-shave-club"}}}])
    _, urls = site_check.site_pages("b1")
    assert "https://acme.mysolutionist.app/saturday-shave-club" in urls
    assert "https://acme.mysolutionist.app/about" in urls


# ─── the offer page's own edits (2026-10-01) ─────────────────────────
# Builder pages number editable elements by position, so the offer page's
# v2/f4 and the home page's v2/f4 were different words under one key: an
# Edit Mode change on one would have rewritten the other on refresh.

def _store(monkeypatch, text):
    from agents.override_system import override_storage
    monkeypatch.setattr(override_storage, "overrides_as_lookup",
                        lambda bid, kind: {p: {"override_value": v, "status": "active"}
                                           for p, v in text.items()} if kind == "text" else {})
    monkeypatch.setattr(site_composer, "_inject_color_overrides", lambda html, bid: html)


def test_the_offer_page_answers_to_its_own_edit_keys(monkeypatch):
    from agents.override_system.override_resolver import resolve_html_overrides
    home = '<h2 data-override-target="v2/f4">The Board</h2>'
    offer = site_composer.namespace_offer_page('<h2 data-override-target="v2/f4">Week one</h2>')
    assert 'data-override-target="v2o/f4"' in offer
    _store(monkeypatch, {"v2/f4": "Home edit", "v2o/f4": "Offer edit"})
    assert ">Home edit<" in resolve_html_overrides(home, "b1")
    applied = site_composer._apply_page_overrides(offer, "b1")
    assert ">Offer edit<" in applied and "Home edit" not in applied


def test_a_rebuilt_offer_page_keeps_its_base_and_retires_old_edits(monkeypatch):
    patched = _db(monkeypatch, {"site_config": {"generated_pages": {}}})
    from agents.override_system import override_storage
    staled = []
    monkeypatch.setattr(override_storage, "list_overrides", lambda bid, kind: [
        {"id": "o1", "target_path": "v2o/f2", "status": "active"},
        {"id": "h1", "target_path": "v2/f2", "status": "active"}] if kind == "text" else [])
    monkeypatch.setattr(override_storage, "mark_overrides_status",
                        lambda ids, status: staled.extend(ids))
    _store(monkeypatch, {})
    monkeypatch.setattr(v2, "run_builder_v2", lambda *a, **k: {
        "html": '<!DOCTYPE html><html><body><h1 data-override-target="v2/f1">Week one</h1></body></html>'})
    ctx = {"design_spec_text": "x", "offer_page": {"path": "/course", "name": "Course"}}
    assert site_composer.build_offer_page("b1", ctx, HOME) is True
    cfg = patched[-1]["site_config"]
    assert 'data-override-target="v2o/f1"' in cfg["generated_pages"]["offer"]
    assert 'data-override-target="v2o/f1"' in cfg["offer_page"]["html_base"]
    assert staled == ["o1"], "only the offer page's old edits retire; the home's stay"


def test_an_edit_reaches_the_offer_page_without_a_rebuild(monkeypatch):
    base = '<!DOCTYPE html><html><body><h1 data-override-target="v2o/f1">Week one</h1></body></html>'
    patched = _db(monkeypatch, {"site_config": {"generated_pages": {"offer": base},
                                                "offer_page": {"path": "/course", "html_base": base}}})
    _store(monkeypatch, {"v2o/f1": "Week one: finding center"})
    assert site_composer.refresh_offer_page("b1") is True
    assert ">Week one: finding center<" in patched[-1]["site_config"]["generated_pages"]["offer"]
    assert patched[-1]["site_config"]["offer_page"]["html_base"] == base, "the base stays clean for reverts"


def test_the_studio_previews_the_offer_page_by_id_or_path():
    cfg = {"offer_page": {"path": "/six-week-wheel-course"}}
    assert public_site._preview_page_id(cfg, "offer") == "offer"
    assert public_site._preview_page_id(cfg, "six-week-wheel-course") == "offer"
    assert public_site._preview_page_id(cfg, "about") == "about"
