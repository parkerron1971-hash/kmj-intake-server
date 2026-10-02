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
                              "site_config": {"html_source": "manual", "manual_hash": digest}}])
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
