"""
test_module_check.py — the system looks at a module the way a person does.

The token is tested like a lock. The preview read is tested like a
fence: four tables, one business, one module, sample rows for an empty
module. The run is tested with a fake browser and a fake judge — the
Playwright pass is site_check's, already proven live. The judge's JSON
is parsed like arithmetic.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import module_check as mc


BIZ = "11111111-1111-1111-1111-111111111111"
MOD = "22222222-2222-2222-2222-222222222222"


def _module(**over):
    m = {"id": MOD, "business_id": BIZ, "name": "Credit Profiles", "slug": "credit-profiles",
         "archetype": "progress_tracker",
         "archetype_params": {"subject_field": "client", "value_field": "score", "target": 720},
         "presentation": {"tone": "precise"},
         "schema": {"fields": [
             {"name": "client", "type": "contact_link", "label": "Client"},
             {"name": "score", "type": "number", "label": "Score"},
             {"name": "stage", "type": "select", "label": "Stage", "options": ["new", "working", "done"]},
             {"name": "pulled_on", "type": "date", "label": "Pulled on"},
             {"name": "fee", "type": "currency", "label": "Fee"},
             {"name": "notes", "type": "textarea", "label": "Notes"},
         ], "views": ["list"]}}
    m.update(over)
    return m


# ─── the token ────────────────────────────────────────────────────────

def test_token_round_trips_and_is_scoped(monkeypatch):
    monkeypatch.setenv("PREVIEW_SECRET", "s3cret")
    t = mc.preview_token(BIZ, MOD, sample=True)
    d = mc.read_token(t)
    assert d and d["b"] == BIZ and d["m"] == MOD and d["s"] is True


def test_a_forged_or_expired_token_is_refused(monkeypatch):
    monkeypatch.setenv("PREVIEW_SECRET", "s3cret")
    t = mc.preview_token(BIZ, MOD)
    payload, sig = t.split(".")
    assert mc.read_token(payload + ".AAAA") is None
    assert mc.read_token("garbage") is None
    old = mc.preview_token(BIZ, MOD, ttl_min=-1)
    assert mc.read_token(old) is None
    monkeypatch.setenv("PREVIEW_SECRET", "other")
    assert mc.read_token(t) is None          # a different secret does not open it


# ─── sample rows ──────────────────────────────────────────────────────

def test_sample_rows_are_shaped_from_the_fields_and_deterministic():
    contacts = mc.sample_contacts(BIZ)
    rows = mc.sample_rows(_module(), contacts)
    assert len(rows) == mc.SAMPLE_ROWS
    d = rows[0]["data"]
    assert d["client"] in {c["id"] for c in contacts}
    assert d["stage"] in ("new", "working", "done")
    assert isinstance(d["score"], float) and 500 <= d["score"] <= 720
    assert isinstance(d["fee"], float) and len(d["pulled_on"]) == 10
    assert "Notes" in d["notes"]
    scores = [r["data"]["score"] for r in rows]
    assert scores == sorted(scores)                       # a climb toward the goal
    again = mc.sample_rows(_module(), contacts)
    assert [r["id"] for r in again] == [r["id"] for r in rows]
    assert all(r["preview"] and r["status"] == "active" and r["module_id"] == MOD for r in rows)


def test_sample_titles_follow_the_title_field_or_the_first_text_field():
    # Leads: title_field is lead_name, and a second text field is not the title
    rows = mc.sample_rows(_module(schema={"fields": [
        {"name": "lead_name", "type": "text", "label": "Lead / business name"},
        {"name": "source", "type": "text", "label": "Source"}]},
        name="Leads", archetype_params={"title_field": "lead_name"}), mc.sample_contacts(BIZ))
    assert all(r["data"]["lead_name"].endswith(" lead") for r in rows)
    assert rows[1]["data"]["source"] == "Source 2"
    # no title_field: the first text field is the title
    rows = mc.sample_rows(_module(schema={"fields": [{"name": "job", "type": "text", "label": "Job"}]},
                                  name="Jobs", archetype_params={}), mc.sample_contacts(BIZ))
    assert all(r["data"]["job"].endswith(" job") for r in rows)


def test_sample_titles_read_like_real_ones():
    rows = mc.sample_rows(_module(schema={"fields": [{"name": "title", "type": "text", "label": "Lead / business name"},
                                                    {"name": "notes", "type": "textarea", "label": "Notes"}]},
                                  name="Leads", archetype_params={}), mc.sample_contacts(BIZ))
    titles = [r["data"]["title"] for r in rows]
    assert titles[0].endswith(" lead") and all(len(t.split()) == 2 for t in titles)
    assert not any(t[-1].isdigit() for t in titles)


# ─── the preview read ─────────────────────────────────────────────────

class _DB:
    def __init__(self, entries=None):
        self.entries = entries or []
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path.startswith("/businesses?"):
            return [{"id": BIZ, "name": "Score Up", "settings": {}}]
        if path.startswith("/custom_modules?"):
            return [_module()]
        if path.startswith("/contacts?"):
            return [{"id": "c-real", "name": "Real Person", "business_id": BIZ}]
        if path.startswith("/module_entries?"):
            return list(self.entries)
        raise AssertionError(path)


@pytest.fixture
def db(monkeypatch):
    import sb_clients
    d = _DB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    return d


TOKEN = {"b": BIZ, "m": MOD, "s": True}


def test_only_the_four_tables_answer(db):
    assert mc.answer_rest(TOKEN, "/invoices?select=*")[0] == 403
    assert mc.answer_rest(TOKEN, "/chief_memories?select=*")[0] == 403
    status, rows = mc.answer_rest(TOKEN, "/businesses?is_active=eq.true&order=created_at.asc")
    assert status == 200 and rows[0]["id"] == BIZ
    assert db.paths[-1] == f"/businesses?id=eq.{BIZ}&select=*&limit=1"


def test_reads_are_pinned_to_the_business_and_module(db):
    mc.answer_rest(TOKEN, f"/custom_modules?id=eq.{MOD}&business_id=eq.OTHER&select=*")
    assert f"business_id=eq.{BIZ}" in db.paths[-1] and "OTHER" not in db.paths[-1]
    status, rows = mc.answer_rest(TOKEN, "/module_entries?module_id=eq.SOMEONE-ELSE&select=*")
    assert status == 200 and rows == []
    mc.answer_rest(TOKEN, f"/module_entries?module_id=eq.{MOD}&status=eq.active&select=*&limit=500")
    entries = [p for p in db.paths if p.startswith("/module_entries?")]
    assert entries and f"module_id=eq.{MOD}" in entries[-1] and f"business_id=eq.{BIZ}" in entries[-1]


def test_an_empty_module_answers_with_sample_rows_and_sample_contacts(db):
    status, rows = mc.answer_rest(TOKEN, f"/module_entries?module_id=eq.{MOD}&status=eq.active&select=*")
    assert status == 200 and len(rows) == mc.SAMPLE_ROWS and all(r["preview"] for r in rows)
    status, contacts = mc.answer_rest(TOKEN, f"/contacts?business_id=eq.{BIZ}&select=id,name")
    assert any(c["id"] == "c-real" for c in contacts) and any(c.get("preview") for c in contacts)
    # a single-row read by id finds the sample row
    rid = rows[2]["id"]
    status, one = mc.answer_rest(TOKEN, f"/module_entries?id=eq.{rid}&select=*")
    assert [r["id"] for r in one] == [rid]


def test_a_module_with_rows_is_shown_as_is(db):
    db.entries = [{"id": f"e{i}", "status": "active", "data": {}} for i in range(4)]
    status, rows = mc.answer_rest(TOKEN, f"/module_entries?module_id=eq.{MOD}&select=*")
    assert [r["id"] for r in rows] == ["e0", "e1", "e2", "e3"]
    status, rows = mc.answer_rest({**TOKEN, "s": False}, f"/module_entries?module_id=eq.{MOD}&select=*")
    assert len(rows) == 4


def test_preview_url_carries_a_readable_token(monkeypatch):
    monkeypatch.setenv("PREVIEW_SECRET", "s3cret")
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com/")
    url = mc.preview_url(BIZ, MOD)
    assert url.startswith("https://app.example.com/preview/module/")
    assert mc.read_token(url.rsplit("/", 1)[1])["m"] == MOD


def test_the_pipeline_surface_may_read_its_linked_forms(db, monkeypatch):
    import sb_clients
    seen = []
    real = db.get

    def spy(path):
        seen.append(path)
        if path.startswith("/intake_forms?"):
            return [{"id": "f1", "name": "Project Inquiry"}]
        return real(path)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", spy)
    status, rows = mc.answer_rest(TOKEN, f"/intake_forms?business_id=eq.OTHER&is_active=eq.true&select=id,name&limit=5")
    assert status == 200 and rows[0]["name"] == "Project Inquiry"
    assert f"business_id=eq.{BIZ}" in seen[-1] and "OTHER" not in seen[-1]


def test_the_token_never_lands_in_the_report(db, monkeypatch):
    import site_check
    monkeypatch.setenv("PREVIEW_SECRET", "s3cret")

    def fake_inspect(urls, widths=(), screenshots=True):
        p = _fake_page(urls[0])
        p["failed_requests"] = [f"403 {urls[0]}/rest?path=%2Fsomething"]
        p["console_errors"] = [f"Failed to load resource {urls[0]}"]
        return [p]
    monkeypatch.setattr(site_check, "inspect_pages", fake_inspect)
    monkeypatch.setattr(site_check, "_store_shots", lambda b, r, pages: [])
    monkeypatch.setattr(mc, "judge", lambda page, b, m: {"findings": [], "design_score": 4, "first_impression": "", "next": []})
    rep = mc.run(BIZ, MOD)
    blob = json.dumps(rep)
    assert "eyJ" not in blob and "<preview>" not in rep["url"]
    assert any("Credit Profiles" in (f.get("where") or "") for f in rep["findings"])
    assert all("eyJ" not in c for c in rep["console_errors"])


# ─── the judge's answer ───────────────────────────────────────────────

def test_parse_judge_is_tolerant_and_bounded():
    text = ('Here you go:\n{"findings":[{"severity":"HIGH","width":390,"what":"The score tile clips its number.","where":"hero"},'
            '{"severity":"weird","what":"Labels collide.","where":"chart"},{"what":""}],'
            '"design_score": 9, "first_impression":"A clear climb toward 720.", "next":["a milestone label at 680","", "a warmer tone","x","y"]}')
    v = mc.parse_judge(text)
    assert [f["severity"] for f in v["findings"]] == ["high", "medium"]
    assert v["findings"][0]["width"] == 390 and v["findings"][1]["width"] == 0
    assert v["design_score"] == 5 and v["first_impression"].startswith("A clear")
    assert v["next"] == ["a milestone label at 680", "a warmer tone", "x"]
    assert mc.parse_judge("no json here") == {"findings": [], "design_score": None, "first_impression": "", "next": []}


# ─── the run ──────────────────────────────────────────────────────────

def _fake_page(url, overflow=False):
    return {"url": url, "widths": {"390": {"overflow_x": overflow, "scroll_width": 420, "broken_images": [],
                                           "empty_headings": 0, "leftover_tokens": [], "overlaps": []},
                                   "1100": {"overflow_x": False, "broken_images": [], "empty_headings": 0,
                                            "leftover_tokens": [], "overlaps": []}},
            "shots": {"390": b"jpeg", "1100": b"jpeg"}, "console_errors": [], "failed_requests": []}


def test_run_measures_judges_and_files_a_report(db, monkeypatch):
    import site_check
    monkeypatch.setenv("PREVIEW_SECRET", "s3cret")
    opened = []
    monkeypatch.setattr(site_check, "inspect_pages",
                        lambda urls, widths=(), screenshots=True: (opened.extend(urls), [_fake_page(urls[0], overflow=True)])[1])
    monkeypatch.setattr(site_check, "_store_shots", lambda b, r, pages: ["shots/a.jpg", "shots/b.jpg"])
    monkeypatch.setattr(mc, "judge", lambda page, b, m: {
        "findings": [{"severity": "medium", "width": 1100, "source": "vision",
                      "what": "Everything is the same weight — no hero.", "where": "top"}],
        "design_score": 3, "first_impression": "A table of scores.",
        "next": ["a hero stat for the average score", "a milestone label at 680"]})
    said = []
    rep = mc.run(BIZ, MOD, reason="accepted", progress_cb=lambda p, s: said.append((p, s)))
    assert rep["ok"] and rep["module"] == "Credit Profiles"
    assert opened and "/preview/module/" in opened[0]
    assert rep["url"].endswith("/preview/module/…")          # the token never lands in a report
    assert rep["design_score"] == 3 and rep["next"][0].startswith("a hero")
    whats = [f["what"] for f in rep["findings"]]
    assert whats[0].startswith("Something is wider")         # geometry high first
    assert any("no hero" in w for w in whats)
    assert rep["screenshots"] == ["shots/a.jpg", "shots/b.jpg"]
    assert "2 things to look at, 1 that matters; design 3/5" in rep["summary"]
    assert said[0][0] == 10 and said[-1][0] == 92


def test_run_is_honest_without_a_browser_or_module(db, monkeypatch):
    import site_check
    monkeypatch.setattr(site_check, "inspect_pages", lambda *a, **k: None)
    rep = mc.run(BIZ, MOD)
    assert rep["ok"] is False and rep["error"] == "no_browser"
    monkeypatch.setattr(db, "get", lambda path: [] if path.startswith("/custom_modules") else db.get(path))
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    rep = mc.run(BIZ, MOD)
    assert rep["ok"] is False and rep["error"] == "no_module"


def test_describe_reads_like_a_verdict():
    rep = {"summary": "Credit Profiles: 1 thing to look at; design 3/5.", "first_impression": "A table.",
           "findings": [{"severity": "medium", "what": "No hero.", "where": "top", "width": 1100}],
           "next": ["a hero stat"]}
    s = mc.describe(rep)
    assert "design 3/5" in s and "First impression: A table." in s and "Findings: No hero. (top, 1100px)" in s
    assert s.endswith("Next moves: a hero stat")


def test_latest_report_reads_the_job_row(monkeypatch):
    import sb_clients
    seen = []

    def get(path):
        seen.append(path)
        return [{"result": {"ok": True, "summary": "s", "design_score": 4}, "finished_at": "2026-09-06T20:00:00+00:00"}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    r = mc.latest_report(BIZ, MOD)
    assert r["design_score"] == 4 and r["finished_at"].startswith("2026-09-06")
    assert f"params->>module_id=eq.{MOD}" in seen[0] and "kind=eq.module_check" in seen[0]


# ─── the wiring ───────────────────────────────────────────────────────

def test_the_kind_the_verb_and_the_router_exist():
    import chief_jobs
    import chief_of_staff as cos
    import action_registry as reg
    import chief_prompt
    import kmj_intake_automation
    meta = chief_jobs.KIND_META["module_check"]
    assert meta["dedupe_key"] == "module_id" and meta["working"]
    assert "check_module" in cos.ACTION_HANDLERS
    assert reg.REGISTRY["check_module"]["reversibility"] == "A"
    src = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")
    assert '"type":"check_module"' in src
    paths = {r.path for r in kmj_intake_automation.app.routes}
    assert "/module-preview/{token}/rest" in paths and "/module-check" in paths


def test_dedupe_is_per_module_for_module_check(monkeypatch):
    """Two accepts in a row are two checks: a live job for another module
    must neither dedupe this one away nor get swept as stale."""
    import chief_jobs
    rows = [{"id": "j-other", "status": "running", "kind": "module_check",
             "params": {"module_id": "other"}, "created_at": chief_jobs._now(), "started_at": chief_jobs._now()}]
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return rows
        if method == "POST":
            return [{"id": "j-new", **(body[0] if isinstance(body, list) else body)}]
        return None
    monkeypatch.setattr(chief_jobs, "_sb", fake_sb)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: (coro.close(), None)[1])
    job = asyncio.run(chief_jobs.enqueue(None, user_id="u", business_id=BIZ, kind="module_check",
                                         params={"module_id": MOD}))
    assert job and not job.get("deduped")
    assert not any(m == "PATCH" for m, _, _ in calls)          # the other module's job was left alone
    job2 = asyncio.run(chief_jobs.enqueue(None, user_id="u", business_id=BIZ, kind="module_check",
                                          params={"module_id": "other"}))
    assert job2 and job2.get("deduped") and job2["id"] == "j-other"


def test_accept_enqueues_a_check(monkeypatch):
    import module_check_router as r
    import chief_jobs
    got = []

    async def fake_enqueue(client, **kw):
        got.append(kw); return {"id": "j1"}
    monkeypatch.setattr(chief_jobs, "enqueue", fake_enqueue)
    asyncio.run(r.enqueue_after_accept("u1", BIZ, MOD))
    assert got and got[0]["kind"] == "module_check" and got[0]["params"]["module_id"] == MOD
    assert got[0]["params"]["reason"] == "accepted"
    asyncio.run(r.enqueue_after_accept("u1", BIZ, None))       # nothing to look at → no job
    assert len(got) == 1
