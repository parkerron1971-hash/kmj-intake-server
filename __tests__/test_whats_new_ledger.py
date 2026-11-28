"""The old whatsNew.ts flowing into platform_updates (whats_new_ledger.py):
the parser reads the file's real shapes and refuses anything else, an entry
becomes a published 'ledger' row with a one-line version, a sync only ever adds,
and old news never counts as new (platform_updates.is_new)."""
from types import SimpleNamespace

import pytest

import platform_updates as PU
import sb_clients
import whats_new_ledger as L

FILE = r"""
// src/core/updates/whatsNew.ts
// a header comment with 'quotes' and { braces } [ and ] that mean nothing
export interface WhatsNewEntry { id: string; }

export const WHATS_NEW: WhatsNewEntry[] = [
  { id: '2026-11-27-member-warning', date: '2026-11-27', area: 'Operate', kinds: ['ministry'], page: 'operate:contacts',
    title: 'Warn your members that the pastor will never ask for gift cards',
    body: 'Scammers text members using the pastor’s name. You read exactly what goes, then it goes. Nothing goes out until you press Send.' },
  /* a block comment between entries */
  { id: '2026-11-26-laptop-fit', date: '2026-11-26', area: 'Everywhere',
    title: "Everything fits a laptop's screen",
    body: "It\'s \"roomier\" now: Members, Texts and Approvals fit.\nA second line." },
  { id: '2026-11-24-good-news', date: '2026-11-24', area: 'Operate', kinds: ['ministry',], areas: ['giving_money', 'office'],
    title: `Approve good news from your phone`,
    body: `A template body with an emoji 🎉 and \u{1F64F}, and a backslash \\ kept.` , },
  // a trailing comment
];
"""


def test_the_parser_reads_every_shape_the_file_uses():
    got = L.parse_ledger(FILE)
    assert [e["id"] for e in got] == ["2026-11-27-member-warning", "2026-11-26-laptop-fit", "2026-11-24-good-news"]
    assert got[0]["kinds"] == ["ministry"] and got[0]["page"] == "operate:contacts"
    assert "pastor’s name" in got[0]["body"]
    assert got[1]["title"] == "Everything fits a laptop's screen"
    assert got[1]["body"] == 'It\'s "roomier" now: Members, Texts and Approvals fit.\nA second line.'
    assert got[2]["areas"] == ["giving_money", "office"] and got[2]["kinds"] == ["ministry"]
    assert "\U0001F389" in got[2]["body"] and "\U0001F64F" in got[2]["body"] and "backslash \\ kept" in got[2]["body"]


@pytest.mark.parametrize("bad, why", [
    ("export const WHATS_NEW = [ { id: 'x', title: `${oops}` } ];", "template"),
    ("export const WHATS_NEW = [ { id: 'x', title: 'never ends } ];", "line break|never ends"),
    ("export const WHATS_NEW = [ { id: 'x', n: 3 } ];", "unexpected value"),
    ("export const OTHER = [];", "no WHATS_NEW"),
    ("export const WHATS_NEW = [ { id: 'x' }", "never ends|expected"),
])
def test_anything_else_stops_the_parse_with_where(bad, why):
    with pytest.raises(L.LedgerParseError, match=why):
        L.parse_ledger(bad)


def test_an_entry_becomes_a_published_ledger_row_with_one_line():
    e = L.parse_ledger(FILE)[0]
    row, why = L.to_row(e, "2026-11-27T12:00:00Z")
    assert why is None
    assert row["status"] == "published" and row["source"] == "ledger" and row["roles"] == []
    assert row["line"] == "Scammers text members using the pastor’s name."
    long = L.first_line("word " * 80)
    assert len(long) <= L.LINE_MAX and long.endswith("…")
    assert L.to_row({"id": "Bad Id", "date": "2026-11-27", "title": "x"}, "now")[0] is None
    assert L.to_row({"id": "2026-11-27-x", "date": "tomorrow", "title": "x"}, "now")[0] is None
    # A page or key that isn't one is dropped, not the whole entry.
    row, _ = L.to_row({"id": "2026-11-27-y", "date": "2026-11-27", "title": "y", "page": "Not A Page",
                       "kinds": ["ministry", "Has Space"]}, "now")
    assert row["page"] is None and row["kinds"] == ["ministry"]


def test_a_sync_only_adds_and_says_what_it_did(monkeypatch):
    posts = []
    table = {"2026-11-26-laptop-fit"}           # already there (maybe edited in Mission Control)

    def post(path, body, prefer=None, **kw):
        posts.append((path, prefer, [r["id"] for r in body]))
        new = [r for r in body if r["id"] not in table]
        table.update(r["id"] for r in new)
        return new
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    got = L.sync(FILE)
    assert got == {"ok": True, "read": 3, "added": 2, "skipped": []}
    assert posts[0][0] == "/platform_updates?on_conflict=id"
    assert "ignore-duplicates" in posts[0][1]              # never overwrite a row
    assert L.sync(FILE)["added"] == 0                       # running it again is safe


def test_a_sync_that_cannot_parse_or_write_writes_nothing(monkeypatch):
    posts = []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: posts.append(a) or None)
    assert L.sync("export const WHATS_NEW = [ { id: 'x', title: `${x}` } ];")["ok"] is False
    assert posts == []
    got = L.sync(FILE)
    assert got["ok"] is False and "APPLY-2026-11-27-whats-new.sql" in got["error"]
    monkeypatch.setattr(L, "fetch_text", lambda: None)
    assert L.sync() == {"ok": False, "error": "whatsNew.ts couldn't be read"}


def test_a_duplicate_id_in_the_file_is_skipped_not_doubled(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, **k: body)
    twice = FILE.replace("// a trailing comment",
                         "{ id: '2026-11-26-laptop-fit', date: '2026-11-26', title: 'again', body: 'x' },")
    got = L.sync(twice)
    assert got["added"] == 3 and got["skipped"] == ["2026-11-26-laptop-fit: listed twice"]


def test_the_scheduler_run_is_off_with_the_switch(monkeypatch):
    import asyncio
    called = []
    monkeypatch.setattr(L, "sync", lambda: called.append(1) or {"ok": True, "added": 0, "read": 0})
    monkeypatch.setenv("WHATS_NEW_LEDGER_SYNC", "off")
    asyncio.run(L.sync_tick())
    assert called == []
    monkeypatch.delenv("WHATS_NEW_LEDGER_SYNC")
    asyncio.run(L.sync_tick())
    assert called == [1]


# ─── Old news stays old (platform_updates.is_new, the cross-review's M2) ───

def _v(seen=()):
    return PU.Viewer(kind="ministry", church=True, role="owner", areas=None, joined="2026-08-01", seen=seen)


def test_imported_old_news_never_counts_as_new_but_later_entries_do(monkeypatch):
    monkeypatch.delenv("WHATS_NEW_LEDGER_NEW_AFTER", raising=False)
    old = {"id": "2026-11-20-old", "date": "2026-11-20", "source": "ledger", "status": "published"}
    cut = {"id": "2026-11-27-cut", "date": "2026-11-27", "source": "ledger", "status": "published"}
    later = {"id": "2026-12-01-later", "date": "2026-12-01", "source": "ledger", "status": "published"}
    editor = {"id": "2026-11-20-editor", "date": "2026-11-20", "source": "editor", "status": "published"}
    today = "2026-12-02"
    assert not PU.is_new(old, _v(), today) and not PU.is_new(cut, _v(), today)
    assert PU.is_new(later, _v(), today) and PU.is_new(editor, _v(), today)
    assert [e["id"] for e in PU.card([old, cut, later, editor], _v(), today)] == ["2026-12-01-later", "2026-11-20-editor"]
    # Old news is still in the list, shown as not new.
    assert PU.shape(old, _v(), today)["new"] is False
    # The day can be moved, e.g. to the day the import really runs.
    monkeypatch.setenv("WHATS_NEW_LEDGER_NEW_AFTER", "2026-12-01")
    assert not PU.is_new(later, _v(), today)
    monkeypatch.setenv("WHATS_NEW_LEDGER_NEW_AFTER", "not a day")
    assert PU.ledger_new_after() == PU.LEDGER_NEW_AFTER_DEFAULT


def test_the_owner_runs_the_import_now(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import auth_supabase
    import lead_admin
    who = SimpleNamespace(id="u1", email="someone@example.com")
    app = FastAPI()
    app.include_router(PU.router)
    app.dependency_overrides[auth_supabase.require_user] = lambda: who
    monkeypatch.setattr(L, "sync", lambda: {"ok": True, "read": 699, "added": 699, "skipped": []})
    c = TestClient(app)
    assert c.post("/platform/updates/sync-ledger").status_code == 403
    who.email = lead_admin.PLATFORM_OWNER_EMAIL
    assert c.post("/platform/updates/sync-ledger").json()["added"] == 699
    monkeypatch.setattr(L, "sync", lambda: {"ok": False, "error": "the table refused the rows"})
    r = c.post("/platform/updates/sync-ledger")
    assert r.status_code == 503 and "refused" in r.json()["detail"]
