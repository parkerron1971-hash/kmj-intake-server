"""site_sync — a hand-built site installs itself on boot, once per change.

The promises: the first install of a composer-built row keeps a backup;
an unchanged deploy writes nothing; a changed source updates the pages
without touching the backup; a row that belongs to a different business
is refused; a missing row is a no-op; and nothing here can raise into
startup.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_sync  # noqa: E402
from site_page_helpers import RESERVED_PAGE_IDS  # noqa: E402


@pytest.fixture(autouse=True)
def _no_post_deploy_check(monkeypatch):
    """An install schedules a real site check 45s later; tests never
    want a browser or the network."""
    monkeypatch.setenv("SITE_CHECK", "off")
    monkeypatch.setenv("SITE_ADOPT", "off")


def _mod(pages=None, slug="kmj-creative-solutions", biz="biz-1"):
    m = types.SimpleNamespace()
    m.SLUG = slug
    m.BUSINESS_ID = biz
    m.render_pages = lambda: pages if pages is not None else {
        "home": "<html>home</html>", "about": "<html>about</html>",
        "services": "<html>services</html>", "contact": "<html>contact</html>"}
    return m


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.patches = []

    def get(self, path):
        return self.rows

    def patch(self, path, body):
        self.patches.append((path, body))
        return [body]


def _wire(monkeypatch, rows):
    db = _DB(rows)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    return db


def test_first_install_keeps_the_composer_page_set_as_a_backup(monkeypatch):
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1",
                              "html_content": "<html>old composed</html>",
                              "site_config": {"html_source": "module-composer",
                                              "generated_pages": {"about": "<old about>"},
                                              "site_pages": ["home", "about"],
                                              "custom_domain": "kmjcreate.com"}}])
    assert site_sync.sync_site(_mod()) == "installed"
    path, body = db.patches[0]
    assert path == "/business_sites?id=eq.row-1"
    assert body["html_content"] == "<html>home</html>"
    cfg = body["site_config"]
    assert cfg["html_source"] == "manual"
    assert cfg["generated_pages"] == {"about": "<html>about</html>",
                                      "services": "<html>services</html>",
                                      "contact": "<html>contact</html>"}
    assert cfg["site_pages"] == ["home", "about", "services", "contact"]
    assert cfg["custom_domain"] == "kmjcreate.com"          # untouched keys survive
    assert cfg["manual_backup"]["html_content"] == "<html>old composed</html>"
    assert cfg["manual_backup"]["html_source"] == "module-composer"
    assert cfg["manual_backup"]["generated_pages"] == {"about": "<old about>"}
    assert cfg["manual_hash"] == site_sync.content_hash(_mod().render_pages())
    assert body["status"] == "published"


def test_an_unchanged_deploy_writes_nothing(monkeypatch):
    digest = site_sync.content_hash(_mod().render_pages())
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "html_content": "x",
                              "site_config": {"html_source": "manual", "manual_hash": digest,
                                              "site_pages": list(_mod().render_pages()),
                                              "generated_pages": {p: h for p, h in _mod().render_pages().items()
                                                                  if p != "home"}}}])
    assert site_sync.sync_site(_mod()) == "current"
    assert db.patches == []


def test_a_changed_source_updates_without_touching_the_backup(monkeypatch):
    backup = {"html_content": "<html>old composed</html>", "html_source": "module-composer"}
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "html_content": "x",
                              "site_config": {"html_source": "manual", "manual_hash": "stale",
                                              "manual_backup": backup}}])
    changed = _mod(pages={"home": "<html>v2</html>", "about": "<html>about v2</html>"})
    assert site_sync.sync_site(changed) == "updated"
    _, body = db.patches[0]
    assert body["html_content"] == "<html>v2</html>"
    assert body["site_config"]["manual_backup"] == backup
    assert body["site_config"]["generated_pages"] == {"about": "<html>about v2</html>"}
    assert body["site_config"]["site_pages"] == ["home", "about"]


def test_a_row_owned_by_another_business_is_refused(monkeypatch):
    db = _wire(monkeypatch, [{"id": "row-9", "business_id": "someone-else",
                              "html_content": "x", "site_config": {}}])
    assert site_sync.sync_site(_mod()) == "wrong-business"
    assert db.patches == []


def test_no_row_is_a_no_op(monkeypatch):
    db = _wire(monkeypatch, [])
    assert site_sync.sync_site(_mod()) == "no-row"
    assert db.patches == []


def test_sync_all_swallows_a_failing_site(monkeypatch):
    bad = _mod()
    bad.render_pages = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(site_sync, "discover", lambda: [bad])
    _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "html_content": "x",
                         "site_config": {}}])
    assert site_sync.sync_all() == {"kmj-creative-solutions": "error"}


def test_site_sync_off_skips_everything(monkeypatch):
    monkeypatch.setenv("SITE_SYNC", "off")
    called = []
    monkeypatch.setattr(site_sync, "discover", lambda: called.append(1) or [])
    assert site_sync.sync_all() == {}
    assert called == []


def test_the_real_kmj_source_is_discovered_and_renders():
    mods = site_sync.discover()
    slugs = {m.SLUG for m in mods}
    assert "kmj-creative-solutions" in slugs
    kmj = next(m for m in mods if m.SLUG == "kmj-creative-solutions")
    assert kmj.BUSINESS_ID == "12773842-3cc6-41a7-9094-b8606e3f7549"
    pages = kmj.render_pages()
    assert set(pages) == {"home", "about", "services", "contact"}
    assert "{{BUSINESS_EMAIL}}" in pages["contact"]
    assert len(site_sync.content_hash(pages)) == 16


CHURCH_IDS = ["home", "visit", "about", "beliefs", "sermons", "give",
              "ministries", "events", "connect", "watch"]


def test_ten_page_site_installs_every_page_home_first_and_is_idempotent(monkeypatch):
    # Home deliberately arrives last; secondary order is the build's order.
    pages = {pid: f"<html>{pid}</html>" for pid in CHURCH_IDS[1:] + ["home"]}
    row = {"id": "row-1", "business_id": "biz-1", "site_config": {}}
    db = _wire(monkeypatch, [row])
    assert site_sync.sync_site(_mod(pages)) == "installed"
    body = db.patches[0][1]
    cfg = body["site_config"]
    assert body["html_content"] == pages["home"]
    assert cfg["site_pages"] == CHURCH_IDS
    assert list(cfg["generated_pages"]) == CHURCH_IDS[1:]
    assert cfg["generated_pages"] == {p: pages[p] for p in CHURCH_IDS[1:]}
    row.update(body)
    db.patches.clear()
    assert site_sync.sync_site(_mod(pages)) == "current"
    assert db.patches == []


def test_invalid_ids_are_logged_skipped_and_excluded_from_hash(monkeypatch, caplog):
    pages = {"home": "home", "visit-2": "visit", "123": "digits"}
    invalid = ["", "About", "bad_id", "two words", "../escape", "a/b", "x?y", "x#y", "é", "live\n", None, 42]
    pages.update({pid: "bad" for pid in invalid})
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_mod(pages)) == "installed"
    cfg = db.patches[0][1]["site_config"]
    assert cfg["site_pages"] == ["home", "visit-2", "123"]
    assert cfg["generated_pages"] == {"visit-2": "visit", "123": "digits"}
    assert cfg["manual_hash"] == site_sync.content_hash({p: pages[p] for p in cfg["site_pages"]})
    assert sum("invalid page id" in r.message for r in caplog.records) == len(invalid)


def test_cap_includes_home_even_when_home_is_last_and_skips_invalid_first(monkeypatch, caplog):
    pages = {"Invalid": "skip", **{f"page-{n}": f"page {n}" for n in range(25)}, "home": "home"}
    row = {"id": "row-1", "business_id": "biz-1", "site_config": {}}
    db = _wire(monkeypatch, [row])
    assert site_sync.sync_site(_mod(pages)) == "installed"
    body = db.patches[0][1]
    cfg = body["site_config"]
    assert cfg["site_pages"] == ["home"] + [f"page-{n}" for n in range(19)]
    assert len(cfg["generated_pages"]) == 19
    assert cfg["manual_hash"] == site_sync.content_hash({p: pages[p] for p in cfg["site_pages"]})
    assert "page cap 20 reached" in caplog.text
    row.update(body)
    db.patches.clear()
    pages["page-24"] = "changed but not installed"
    assert site_sync.sync_site(_mod(pages)) == "current"
    assert db.patches == []


def test_missing_home_refuses_install(monkeypatch, caplog):
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_mod({"visit": "visit"})) == "error"
    assert db.patches == []
    assert "no home page" in caplog.text


def test_old_install_with_same_hash_but_dropped_custom_pages_is_repaired(monkeypatch):
    pages = {"home": "home", "visit": "visit", "about": "about"}
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1",
                              "site_config": {"html_source": "manual",
                                              "manual_hash": site_sync.content_hash(pages),
                                              "site_pages": ["home", "about"],
                                              "generated_pages": {"about": "about"}}}])
    assert site_sync.sync_site(_mod(pages)) == "updated"
    assert db.patches[0][1]["site_config"]["site_pages"] == list(pages)
    assert db.patches[0][1]["site_config"]["generated_pages"]["visit"] == "visit"


def test_order_change_updates_even_when_content_hash_is_unchanged(monkeypatch):
    pages = {"home": "home", "visit": "visit", "about": "about"}
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1",
                              "site_config": {"html_source": "manual",
                                              "manual_hash": site_sync.content_hash(pages),
                                              "site_pages": ["home", "about", "visit"],
                                              "generated_pages": {"about": "about", "visit": "visit"}}}])
    assert site_sync.sync_site(_mod(pages)) == "updated"
    assert db.patches[0][1]["site_config"]["site_pages"] == list(pages)


def test_real_kmj_install_matches_legacy_bytes_and_stays_current(monkeypatch):
    import hashlib
    import json
    kmj = next(m for m in site_sync.discover() if m.SLUG == "kmj-creative-solutions")
    pages = kmj.render_pages()
    legacy_ids = ["home"] + [p for p in ("about", "services", "contact") if p in pages]
    legacy_generated = {p: pages[p] for p in legacy_ids[1:]}
    # The old installer hashed all rendered pages, sorted by key.
    legacy_blob = json.dumps({k: pages[k] for k in sorted(pages)}, ensure_ascii=False)
    legacy_hash = hashlib.sha256(legacy_blob.encode("utf-8")).hexdigest()[:16]
    row = {"id": "row-1", "business_id": kmj.BUSINESS_ID, "site_config": {}}
    db = _wire(monkeypatch, [row])
    assert site_sync.sync_site(kmj) == "installed"
    body = db.patches[0][1]
    cfg = body["site_config"]
    assert body["html_content"].encode() == pages["home"].encode()
    assert json.dumps(cfg["site_pages"]).encode() == json.dumps(legacy_ids).encode()
    assert json.dumps(cfg["generated_pages"]).encode() == json.dumps(legacy_generated).encode()
    assert cfg["manual_hash"] == legacy_hash
    # JSONB can reorder object keys; that must not trigger a reinstall.
    cfg["generated_pages"] = dict(sorted(cfg["generated_pages"].items()))
    row.update(body)
    db.patches.clear()
    assert site_sync.sync_site(kmj) == "current"
    assert db.patches == []


@pytest.mark.parametrize("page_id", sorted(RESERVED_PAGE_IDS))
def test_reserved_ids_are_skipped_and_visible_on_stdout(monkeypatch, capsys, page_id):
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_mod({"home": "home", page_id: "unreachable", "sermons": "library"})) == "installed"
    cfg = db.patches[0][1]["site_config"]
    assert cfg["site_pages"] == ["home", "sermons"]
    assert cfg["generated_pages"] == {"sermons": "library"}
    output = capsys.readouterr().out
    assert "reserved page id" in output and repr(page_id) in output


@pytest.mark.parametrize("html", ["", " ", None, 42, {}])
def test_empty_or_non_string_pages_do_not_count_toward_cap(monkeypatch, capsys, html):
    pages = {"home": "home", "empty": html, **{f"page-{n}": "page" for n in range(19)}}
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_mod(pages)) == "installed"
    cfg = db.patches[0][1]["site_config"]
    assert len(cfg["site_pages"]) == 20 and "empty" not in cfg["site_pages"]
    assert "page-18" in cfg["generated_pages"]
    assert "empty or non-string page" in capsys.readouterr().out


@pytest.mark.parametrize("html", ["", " ", None, 42, {}])
def test_unservable_home_refuses_the_install(monkeypatch, html):
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_mod({"home": html, "visit": "visit"})) == "error"
    assert db.patches == []


def test_all_skips_are_visible_in_production_stdout(monkeypatch, capsys):
    pages = {"home": "home", "Bad": "bad", **{f"page-{n}": "page" for n in range(20)}}
    _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    site_sync.sync_site(_mod(pages))
    out = capsys.readouterr().out
    assert "invalid page id" in out and "'Bad'" in out
    assert "page cap 20 reached" in out and "'page-19'" in out


def test_every_shipped_build_has_only_servable_pages_within_the_cap():
    from pathlib import Path
    from site_page_helpers import RESERVED_PAGE_IDS, valid_page_id
    builds = site_sync.discover()
    assert {Path(m.__file__) for m in builds} == set(site_sync.SITES_DIR.glob("*/build.py"))
    assert builds, "the contract test must exercise the shipped sites"
    for build in builds:
        pages = build.render_pages()
        assert "home" in pages, build.SLUG
        assert 1 <= len(pages) <= site_sync.MAX_SITE_PAGES, build.SLUG
        for pid, html in pages.items():
            assert valid_page_id(pid) and pid not in RESERVED_PAGE_IDS, (build.SLUG, pid)
            assert isinstance(html, str) and html.strip(), (build.SLUG, pid)


def _church(redirects, pages=None):
    m = _mod(pages or {"home": "home", "visit": "visit", "connect": "connect"}, slug="church")
    if redirects is not None:
        m.REDIRECTS = redirects
    return m


def test_redirects_install_with_the_pages_and_then_stay_current(monkeypatch):
    redirects = {"/i-m-new": "/visit", "/prayer-request": "/connect#prayer",
                 "/volunteer": "/connect?interest=serve#connect-card", "/media/*": "/", "/live": "/visit"}
    row = {"id": "row-1", "business_id": "biz-1", "site_config": {}}
    db = _wire(monkeypatch, [row])
    assert site_sync.sync_site(_church(redirects)) == "installed"
    body = db.patches[0][1]
    assert body["site_config"]["manual_redirects"] == redirects
    row.update(body)
    db.patches.clear()
    assert site_sync.sync_site(_church(redirects)) == "current"
    assert db.patches == []


def test_unusable_redirects_are_skipped_and_printed(monkeypatch, capsys):
    bad = {"/Old": "/visit", "/two words": "/visit", "/visit": "/connect", "/give": "/visit",
           "/sermons/*": "/visit", "/team": "/visit", "/live/*": "/visit", "/off": "https://evil.example/",
           "/off2": "//evil.example", "/off3": "/missing", "/off4": "/home", "/off5": None, 7: "/visit"}
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_church({**bad, "/fine": "/visit"})) == "installed"
    assert db.patches[0][1]["site_config"]["manual_redirects"] == {"/fine": "/visit"}
    out = capsys.readouterr().out
    for old in bad:
        assert repr(old) in out, old


def test_redirects_that_arent_a_dict_install_nothing(monkeypatch, capsys):
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": {}}])
    assert site_sync.sync_site(_church([("/old", "/visit")])) == "installed"
    assert "manual_redirects" not in db.patches[0][1]["site_config"]
    assert "redirects must be a dict" in capsys.readouterr().out


def test_a_change_to_the_redirects_alone_updates_the_row_without_a_browser_check(monkeypatch):
    import threading
    import site_check
    pages = {"home": "home", "visit": "visit", "connect": "connect"}
    stored = {"html_source": "manual", "manual_hash": site_sync.content_hash(pages),
              "site_pages": list(pages), "generated_pages": {"visit": "visit", "connect": "connect"},
              "manual_redirects": {"/old": "/visit"}}
    timers = []

    class _Timer:
        def __init__(self, *args, **kwargs):
            timers.append(args)

        def start(self):
            pass

    monkeypatch.setattr(threading, "Timer", _Timer)
    monkeypatch.setattr(site_check, "enabled", lambda: True)
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": dict(stored)}])
    assert site_sync.sync_site(_church({"/old": "/connect"}, pages)) == "updated"
    assert db.patches[0][1]["site_config"]["manual_redirects"] == {"/old": "/connect"}
    assert timers == []
    # A page change still gets its check.
    assert site_sync.sync_site(_church({"/old": "/visit"}, {**pages, "visit": "new visit"})) == "updated"
    assert len(timers) == 1


def test_dropping_the_redirects_takes_them_out_of_the_row(monkeypatch):
    pages = {"home": "home", "visit": "visit", "connect": "connect"}
    stored = {"html_source": "manual", "manual_hash": site_sync.content_hash(pages),
              "site_pages": list(pages), "generated_pages": {"visit": "visit", "connect": "connect"},
              "manual_redirects": {"/old": "/visit"}}
    db = _wire(monkeypatch, [{"id": "row-1", "business_id": "biz-1", "site_config": stored}])
    assert site_sync.sync_site(_church(None, pages)) == "updated"
    assert "manual_redirects" not in db.patches[0][1]["site_config"]


def test_kmj_declares_no_redirects_and_its_row_never_gets_any(monkeypatch):
    kmj = next(m for m in site_sync.discover() if m.SLUG == "kmj-creative-solutions")
    assert not hasattr(kmj, "REDIRECTS")
    row = {"id": "row-1", "business_id": kmj.BUSINESS_ID, "site_config": {}}
    db = _wire(monkeypatch, [row])
    assert site_sync.sync_site(kmj) == "installed"
    assert "manual_redirects" not in db.patches[0][1]["site_config"]
    row.update(db.patches[0][1])
    db.patches.clear()
    assert site_sync.sync_site(kmj) == "current"
    assert db.patches == []


def test_every_shipped_builds_redirects_install_without_a_skip():
    from site_page_helpers import clean_redirects
    for build in site_sync.discover():
        redirects = getattr(build, "REDIRECTS", None)
        if redirects is not None:
            kept, skipped = clean_redirects(redirects, build.render_pages())
            assert skipped == [] and kept == redirects, (build.SLUG, skipped)
