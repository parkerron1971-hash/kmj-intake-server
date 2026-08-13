"""Site-builder audit follow-up (2026-08-13) — secondary pages must not
go stale.

compose_site rendered About / Services / Contact as an inline tail step,
and every INCREMENTAL path went through refresh_if_composed, which
rebuilt the home page alone. Offerings CRUD, override saves and Chief
edits all call it. So a practitioner who added a service saw it on Home
and not on Services until the next full compose — and a full compose
costs money, so in practice the secondary pages just drifted.

The render is deterministic (module renderers, no LLM), so keeping them
current is free. One shared helper now serves both callers.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import site_composer  # noqa: E402


MULTI = {
    "site": {"id": "s1", "slug": "acme",
             "site_config": {"site_type": "multi-page",
                             "html_source": "module-composer",
                             "page_spec": {"sections": []}}},
    "business": {"id": "b1", "name": "Acme"},
    "dna": {"vibe": "calm"},
}
SINGLE = {
    "site": {"id": "s1", "slug": "acme",
             "site_config": {"site_type": "landing-page",
                             "html_source": "module-composer",
                             "page_spec": {"sections": []}}},
    "business": {"id": "b1", "name": "Acme"},
    "dna": {"vibe": "calm"},
}


# ─── _multi_page_slug ────────────────────────────────────────────────


def test_slug_returned_for_multi_page_site():
    assert site_composer._multi_page_slug(MULTI) == "acme"


def test_no_slug_for_single_page_site():
    assert site_composer._multi_page_slug(SINGLE) == ""


def test_no_slug_when_the_site_row_has_none():
    ctx = {"site": {"site_config": {"site_type": "multi-page"}}}
    assert site_composer._multi_page_slug(ctx) == ""


def test_malformed_context_does_not_raise():
    assert site_composer._multi_page_slug({}) == ""
    assert site_composer._multi_page_slug({"site": None}) == ""


# ─── refresh_if_composed keeps the other pages current ───────────────


@pytest.fixture
def wired(monkeypatch):
    """Replace everything refresh_if_composed touches, and record which
    of the two renders ran."""
    calls = {"home": 0, "secondary": [], "nav": []}

    def _ctx_for(ctx):
        monkeypatch.setattr(site_composer, "gather_context", lambda bid: ctx)

    monkeypatch.setattr(site_composer, "sanitize_spec", lambda spec, ctx: spec)
    monkeypatch.setattr(
        site_composer, "render_and_persist",
        lambda bid, spec, ctx, **kw: calls.__setitem__("home", calls["home"] + 1))
    monkeypatch.setattr(
        site_composer, "rebuild_secondary_pages",
        lambda bid, ctx, slug: calls["secondary"].append(slug) or 3)
    return calls, _ctx_for


def test_refresh_rebuilds_secondary_pages_on_a_multi_page_site(wired):
    """The regression. This used to render home and stop."""
    calls, ctx_for = wired
    ctx_for(dict(MULTI))
    assert site_composer.refresh_if_composed("b1") is True
    assert calls["home"] == 1
    assert calls["secondary"] == ["acme"]


def test_refresh_leaves_single_page_sites_alone(wired):
    calls, ctx_for = wired
    ctx_for(dict(SINGLE))
    assert site_composer.refresh_if_composed("b1") is True
    assert calls["home"] == 1
    assert calls["secondary"] == []


def test_canvas_sites_refresh_their_secondary_pages_too(wired):
    """A canvas-authored home page still has module-rendered secondary
    pages, and they go just as stale."""
    calls, ctx_for = wired
    ctx = {
        "site": {"id": "s1", "slug": "acme",
                 "site_config": {"site_type": "multi-page",
                                 "html_source": "canvas",
                                 "canvas": {"html": "<html>real</html>"}}},
        "business": {"id": "b1", "name": "Acme"},
        "dna": {},
    }
    ctx_for(ctx)
    assert site_composer.refresh_if_composed("b1") is True
    assert calls["home"] == 1
    assert calls["secondary"] == ["acme"]


def test_nav_is_set_before_the_home_render(monkeypatch):
    """page_nav has to be on ctx BEFORE render_and_persist, or the home
    header ships without its cross-page links — the same ordering
    compose_site uses."""
    seen = {}
    monkeypatch.setattr(site_composer, "gather_context", lambda bid: dict(MULTI))
    monkeypatch.setattr(site_composer, "sanitize_spec", lambda spec, ctx: spec)
    monkeypatch.setattr(
        site_composer, "render_and_persist",
        lambda bid, spec, ctx, **kw: seen.update(nav=ctx.get("page_nav")))
    monkeypatch.setattr(site_composer, "rebuild_secondary_pages",
                        lambda bid, ctx, slug: 3)
    site_composer.refresh_if_composed("b1")
    assert seen.get("nav"), "home rendered without page_nav"
    assert [p["id"] for p in seen["nav"]["pages"]] == [
        "home", "about", "services", "contact"]


def test_the_helper_swallows_its_own_failures(monkeypatch):
    """Best-effort means best-effort. rebuild_secondary_pages is the
    thing that must never raise — a broken secondary render cannot be
    allowed to unwind a home page that already rendered fine."""
    import site_multipage

    def _boom(ctx, slug, title):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(site_multipage, "build_secondary_pages", _boom)
    assert site_composer.rebuild_secondary_pages("b1", dict(MULTI), "acme") == 0


def test_the_helper_writes_nothing_when_no_pages_rendered(monkeypatch):
    """An empty render must not blank generated_pages on the site row."""
    import site_multipage
    wrote = []
    monkeypatch.setattr(site_multipage, "build_secondary_pages",
                        lambda ctx, slug, title: {})
    monkeypatch.setattr(site_composer.sb_clients, "sb_patch_as_service",
                        lambda path, body: wrote.append(path))
    assert site_composer.rebuild_secondary_pages("b1", dict(MULTI), "acme") == 0
    assert wrote == []
