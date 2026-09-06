"""
test_business_blueprint.py — the idea-to-business door.

The rubric (business_quality) is deterministic, so it is tested like
arithmetic. The map's shape is a closed pydantic model, tested by
feeding it bad JSON. The whole door is tested with a fake model and a
fake database: one map call, one build call per module, every draft
stored, the map kept as status='blueprint' (never a card), and the
context block that carries the forms and site brief to later turns.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import business_blueprint as bb
import business_quality as bq
import module_spec_generator as msg


# ─── fixtures ─────────────────────────────────────────────────────────

def _map(**over):
    base = {
        "summary": ("A credit repair consultancy: clients come in with a low score, "
                    "I pull their reports monthly and dispute items until they can qualify."),
        "business_type": "consultant",
        "modules": [
            {"name": "Credit Profiles",
             "intake": ("I want to track each client's credit score climbing toward 720, "
                        "pulled monthly, and be told the day someone reaches it."),
             "why": "the whole service is the number going up"},
            {"name": "Invoices",
             "intake": ("Monthly $99 invoices per client, paid or unpaid, and remind me "
                        "when one is 7 days overdue."),
             "why": "how the business gets paid"},
        ],
        "offerings": [
            {"name": "Monthly Credit Repair", "slug": "monthly-credit-repair",
             "category": "service", "current_price": 99, "currency": "usd",
             "description": "Monthly disputes and a report pull.",
             "show_price_to_customer": True, "reasoning": "named in the idea"},
        ],
        "forms": [
            {"name": "New Client Intake", "form_type": "intake",
             "fields": [{"label": "Email", "type": "email", "required": True},
                        {"label": "What is your score today?", "type": "number"}],
             "link_module": "Credit Profiles",
             "confirmation_message": "Got it — I'll pull your report this week."},
        ],
        "site": {"headline": "Your score, repaired.", "tagline": "Monthly, honest, tracked.",
                 "pages": ["Home", "How it works", "Book"], "primary_cta": "Book a free review",
                 "voice": "plain and reassuring"},
        "rails": {
            "get_paid": {"covered_by": "Monthly Credit Repair + Invoices"},
            "get_found": {"covered_by": "the site"},
            "get_booked": {"covered_by": "New Client Intake form"},
            "keep_records": {"covered_by": "Credit Profiles"},
            "follow_up": {"covered_by": "overdue invoice reminder"},
        },
    }
    base.update(over)
    return base


# ─── the rubric ───────────────────────────────────────────────────────

def test_a_complete_map_is_clean():
    rep = bq.assess(_map())
    assert not rep.needs_revision, rep.as_dict()


def test_no_modules_is_no_records():
    rep = bq.assess(_map(modules=[]))
    assert "no_records" in [f.code for f in rep.findings]


def test_nothing_priced_and_no_money_module_is_no_way_to_get_paid():
    m = _map(offerings=[], modules=[_map()["modules"][0]],
             rails={})
    rep = bq.assess(m)
    assert "no_way_to_get_paid" in [f.code for f in rep.findings]


def test_a_priced_offering_alone_is_a_way_to_get_paid():
    m = _map(modules=[_map()["modules"][0]])
    codes = [f.code for f in bq.assess(m).findings]
    assert "no_way_to_get_paid" not in codes


def test_site_without_headline_or_cta():
    assert "no_way_to_be_found" in [f.code for f in bq.assess(_map(site={})).findings]
    s = dict(_map()["site"]); s["primary_cta"] = ""
    assert "site_without_a_cta" in [f.code for f in bq.assess(_map(site=s)).findings]


def test_no_form_and_no_booking_words_is_no_way_in():
    m = _map(forms=[], modules=[
        {"name": "Expenses", "intake": "Log every expense with a category and remind me when the month is over budget."}])
    assert "no_way_in" in [f.code for f in bq.assess(m).findings]


def test_a_feedback_form_is_not_a_way_in_but_a_quote_form_is():
    base_mod = [{"name": "Expenses", "intake": "Log every expense with a category and remind me when the month is over budget."}]
    fb = {"name": "How did we do", "form_type": "feedback", "fields": [{"label": "Rating", "type": "number"}]}
    assert "no_way_in" in [f.code for f in bq.assess(_map(forms=[fb], modules=base_mod)).findings]
    q = dict(fb); q["form_type"] = "quote"
    assert "no_way_in" not in [f.code for f in bq.assess(_map(forms=[q], modules=base_mod)).findings]


def test_no_intake_asks_for_a_nudge_is_no_follow_up():
    m = _map(modules=[{"name": "Clients", "intake": "Every client with their phone, email, score and the date they signed up with me."}])
    assert "no_follow_up" in [f.code for f in bq.assess(m).findings]


def test_duplicates_too_many_and_thin_intakes():
    mods = [dict(_map()["modules"][0]) for _ in range(7)]
    rep = bq.assess(_map(modules=mods))
    codes = [f.code for f in rep.findings]
    assert "duplicate_modules" in codes and "too_many_modules" in codes
    thin = _map(modules=[{"name": "Jobs", "intake": "track jobs and remind me"}])
    assert "thin_intake" in [f.code for f in bq.assess(thin).findings]


def test_notes_do_not_force_a_revision():
    f = dict(_map()["forms"][0]); f.pop("link_module")
    m = _map(forms=[f], rails={"get_found": {"gap": "no budget for ads"}})
    rep = bq.assess(m)
    codes = {x.code: x.severity for x in rep.findings}
    assert codes.get("form_not_linked") == "note"
    assert codes.get("rails_declare_gaps") == "note"
    assert not rep.needs_revision


# ─── the shape ────────────────────────────────────────────────────────

def test_the_map_validates():
    bp = bb.BusinessBlueprint.model_validate(_map())
    assert bp.business_type == "consultant" and len(bp.modules) == 2


def test_a_form_must_link_to_a_module_in_the_map():
    m = _map()
    m["forms"][0]["link_module"] = "Something Else"
    with pytest.raises(Exception):
        bb.BusinessBlueprint.model_validate(m)


def test_form_types_are_the_ones_create_client_form_accepts():
    m = _map()
    m["forms"][0]["form_type"] = "booking"      # not a real form_type
    with pytest.raises(Exception):
        bb.BusinessBlueprint.model_validate(m)


def test_seven_modules_is_refused_by_the_shape():
    with pytest.raises(Exception):
        bb.BusinessBlueprint.model_validate(_map(modules=[_map()["modules"][0]] * 7))


def test_long_prose_is_clipped_not_refused():
    """The first live run: a good map, four sentences over a cap, the whole
    thing thrown away. Prose trims to its budget; structure still rejects."""
    m = _map()
    m["site"]["voice"] = "plain " * 100
    m["rails"]["get_found"]["covered_by"] = "the site, " * 60
    m["modules"][0]["why"] = "because " * 80
    bp = bb.BusinessBlueprint.model_validate(m)
    assert len(bp.site.voice) <= 240 and bp.site.voice.startswith("plain")
    assert len(bp.rails["get_found"].covered_by) <= 240
    assert len(bp.modules[0].why) <= 300
    # structure is still refused: a seventh module, an unknown form type
    with pytest.raises(Exception):
        bb.BusinessBlueprint.model_validate(_map(modules=[_map()["modules"][0]] * 7))


def test_the_prompt_lists_the_real_verticals_and_no_mustache():
    s = bb._system_prompt()
    assert "consultant" in s and "__VERTICALS__" not in s
    assert "{{" not in s and "}}" not in s


# ─── the door, with a fake model and a fake database ─────────────────

class _FakeMsg:
    def __init__(self, text):
        self.content = [SimpleNamespace(type="text", text=text)]


class _FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    @property
    def messages(self):
        outer = self

        class _M:
            def create(self, **kw):
                outer.calls.append(kw)
                return _FakeMsg(outer.answers.pop(0))
        return _M()


class _FakeDB:
    """sb_get/sb_post/sb_patch as the door uses them."""
    def __init__(self):
        self.specs = []
        self.forms = []
        self.jobs = []
        self.n = 0

    def get(self, path):
        if path.startswith("/businesses?"):
            return [{"id": "b1", "name": "Score Up", "type": "custom"}]
        if path.startswith("/module_specs?"):
            if "status=eq.blueprint" in path:
                rows = [r for r in self.specs if r["status"] == "blueprint"]
                return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:1]
            if "status=eq.draft" in path:
                since = path.split("created_at=gte.")[1].split("&")[0]
                return [r for r in self.specs if r["status"] == "draft" and r["created_at"] >= since]
            raise AssertionError(path)
        if path.startswith("/intake_forms?"):
            return self.forms
        if path.startswith("/custom_modules?"):
            return []
        if path.startswith("/chief_jobs?"):
            return self.jobs
        raise AssertionError(path)

    def post(self, path, body):
        assert path == "/module_specs"
        self.n += 1
        row = dict(body); row["id"] = f"spec-{self.n}"
        row["created_at"] = (datetime.now(timezone.utc) + timedelta(seconds=self.n)).isoformat()
        self.specs.append(row)
        return [row]

    def patch(self, path, body):
        sid = path.split("id=eq.")[1]
        for r in self.specs:
            if r["id"] == sid:
                r.update(body)
        return [body]


def _spec(slug, name, archetype="progress_tracker"):
    return {"slug": slug, "name": name, "archetype": archetype,
            "schema": {"fields": [{"name": "client", "type": "contact_link", "label": "Client"}],
                       "views": ["list"]}}


@pytest.fixture
def door(monkeypatch):
    db = _FakeDB()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    for mod in (bb.sb_clients, msg.sb_clients):
        monkeypatch.setattr(mod, "sb_get_as_service", db.get)
        monkeypatch.setattr(mod, "sb_post_as_service", db.post)
        monkeypatch.setattr(mod, "sb_patch_as_service", db.patch)
    built = []

    def fake_generate(business, intake, extra_guidance=None):
        built.append((business.get("type"), intake, extra_guidance))
        if "score" in intake:
            # the builder split this one anyway — only the first survives
            return {"ok": True, "specs": [_spec("credit-profiles", "Credit Profiles"),
                                          _spec("report-pulls", "Report Pulls")],
                    "offerings": [], "quality": {"used": "first"}}
        return {"ok": True, "specs": [_spec("invoices", "Invoices", "composed_dashboard")],
                "offerings": [{"name": "Monthly Credit Repair", "slug": "monthly-credit-repair",
                               "category": "service", "current_price": 99}],
                "quality": {"used": "first"}}
    monkeypatch.setattr(msg, "generate_module_proposal", fake_generate)
    return db, built


IDEA = "I repair credit for clients, $99 a month, and want a site."


def test_the_door_maps_then_builds_one_module_per_piece(door, monkeypatch):
    db, built = door
    client = _FakeClient([json.dumps(_map())])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    said = []

    res = bb.propose_business_from_idea("b1", IDEA, progress_cb=lambda p, m: said.append((p, m)))
    assert res["ok"], res
    # one map call; the builder saw the map's vertical and the ONE-module rule, once per piece
    assert len(client.calls) == 1
    assert sorted(t for t, _, _ in built) == ["consultant", "consultant"]
    assert all("ONE module" in g for _, _, g in built)
    kinds = [(p["kind"], p.get("spec", p.get("offering", {})).get("slug")) for p in res["proposals"]]
    assert ("module", "credit-profiles") in kinds and ("module", "invoices") in kinds
    assert ("module", "report-pulls") not in kinds          # the split was dropped
    assert any(r.get("dropped") == "report-pulls" for r in res["module_reports"])
    # the offering the builder produced is not stored twice from the map's own list
    assert kinds.count(("offering", "monthly-credit-repair")) == 1
    # the map is kept LAST as a blueprint row, never a draft card
    statuses = [r["status"] for r in db.specs]
    assert statuses.count("blueprint") == 1 and statuses.count("draft") == 3
    assert statuses[-1] == "blueprint"
    bp_row = db.specs[-1]
    assert bp_row["draft_json"]["__kind"] == "business" and bp_row["draft_json"]["__shown"] is False
    assert bp_row["draft_json"]["__started_at"] <= db.specs[0]["created_at"]   # owns every draft of the run
    assert res["forms"][0]["name"] == "New Client Intake"
    assert "How it runs:" in res["decomposition_reasoning"]
    assert said[0][1].startswith("drawing the map") and said[-1] == (100, "done — the cards are ready")
    assert [p for p, _ in said] == sorted(p for p, _ in said)          # monotonic


def test_the_job_body_keeps_a_summary_not_the_cards(door, monkeypatch):
    client = _FakeClient([json.dumps(_map())])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    out = bb.run_job("b1", {"idea": IDEA})
    assert out["ok"] and out["modules"] == ["Credit Profiles", "Invoices"]
    assert out["offerings"] == ["Monthly Credit Repair"] and out["forms"] == 1
    assert "proposals" not in out
    bad = bb.run_job("b1", {"idea": "credit"})
    assert bad["ok"] is False and "more" in bad["error"]


def test_replay_returns_the_finished_cards_until_shown_or_stale(door, monkeypatch):
    db, _ = door
    assert bb.replay("b1") is None
    client = _FakeClient([json.dumps(_map())])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    bb.propose_business_from_idea("b1", IDEA)
    rep = bb.replay("b1")
    assert rep and rep["shown"] is False and rep["idea"] == IDEA
    assert len(rep["proposals"]) == 3 and rep["forms"] and rep["site"]["headline"]
    bb.mark_shown(rep["blueprint_row"])
    assert bb.replay("b1")["shown"] is True
    # cards accepted or rejected → nothing to replay
    for r in db.specs:
        if r["status"] == "draft":
            r["status"] = "accepted"
    assert bb.replay("b1") is None


def test_a_map_that_fails_the_rubric_is_revised_once(door, monkeypatch):
    db, built = door
    bad = _map(site={"headline": "Your score, repaired."})      # no CTA → revise
    client = _FakeClient([json.dumps(bad), json.dumps(_map())])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    monkeypatch.setattr(msg, "CRITIQUE_ENABLED", True)

    res = bb.generate_business_blueprint({"id": "b1", "name": "Score Up"}, "I repair credit for clients, $99 a month.")
    assert res["ok"]
    assert len(client.calls) == 2
    assert "REVISE" in client.calls[1]["messages"][0]["content"]
    assert res["quality"]["used"] == "revised"
    assert res["blueprint"]["site"]["primary_cta"] == "Book a free review"


def test_a_worse_revision_is_discarded(door, monkeypatch):
    bad = _map(site={"headline": "Your score, repaired."})
    worse = _map(site={}, forms=[])
    client = _FakeClient([json.dumps(bad), json.dumps(worse)])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    monkeypatch.setattr(msg, "CRITIQUE_ENABLED", True)
    res = bb.generate_business_blueprint({"id": "b1", "name": "Score Up"}, "I repair credit for clients, $99 a month.")
    assert res["quality"]["used"] == "first"
    assert res["blueprint"]["site"]["headline"] == "Your score, repaired."


def test_bad_json_from_the_model_soft_fails(door, monkeypatch):
    client = _FakeClient(["not json at all"])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    res = bb.generate_business_blueprint({"id": "b1"}, "I repair credit for clients, $99 a month.")
    assert not res["ok"] and res["error"].startswith("non_json")


def test_a_one_word_idea_is_asked_to_say_more(door):
    res = bb.generate_business_blueprint({"id": "b1"}, "credit")
    assert not res["ok"] and "more" in res["error"]


def test_the_status_check_knows_the_blueprint_row():
    """The first live run lost its map to module_specs_status_check. The
    migration that widens it must name every status this module writes."""
    sql = (pathlib.Path(__file__).resolve().parent.parent
           / "supabase" / "APPLY-2026-09-06-module-specs-status-blueprint.sql").read_text(encoding="utf-8")
    assert f"'{bb.BLUEPRINT_STATUS}'::text" in sql
    assert "'superseded'::text" in sql and "'draft'::text" in sql


def test_a_refused_map_row_is_a_failed_run(door, monkeypatch):
    db, _ = door
    client = _FakeClient([json.dumps(_map())])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    real_post = db.post

    def refuse_blueprint(path, body):
        if body.get("status") == bb.BLUEPRINT_STATUS:
            return None                     # what PostgREST's 400 looks like to sb_post_as_service
        return real_post(path, body)
    monkeypatch.setattr(bb.sb_clients, "sb_post_as_service", refuse_blueprint)
    monkeypatch.setattr(msg.sb_clients, "sb_post_as_service", refuse_blueprint)
    res = bb.propose_business_from_idea("b1", IDEA)
    assert res["ok"] is False and "keep the map" in res["error"]
    assert bb.replay("b1") is None


# ─── the block that carries the map into later turns ─────────────────

def _lay_out(db, monkeypatch, now=True):
    client = _FakeClient([json.dumps(_map())])
    monkeypatch.setattr(bb.llm_call, "sdk_client", lambda **kw: client)
    bb.propose_business_from_idea("b1", IDEA)


def test_context_block_says_cards_ready_until_they_are_shown(door, monkeypatch):
    db, _ = door
    _lay_out(db, monkeypatch)
    block = bb.context_block("b1")
    assert block.startswith("CARDS READY, NOT YET SHOWN")
    assert '"type":"propose_business_from_idea"' in block and IDEA[:30] in block
    assert "BUSINESS BLUEPRINT ON FILE" in block
    bb.mark_shown(bb.replay("b1")["blueprint_row"])
    block = bb.context_block("b1")
    assert "CARDS READY" not in block and block.startswith("BUSINESS BLUEPRINT ON FILE")


def test_context_block_lists_forms_not_yet_created_and_the_site_brief(door, monkeypatch):
    db, _ = door
    _lay_out(db, monkeypatch)
    bb.mark_shown(bb.replay("b1")["blueprint_row"])
    block = bb.context_block("b1")
    assert "Forms still to create:" in block
    assert "New Client Intake [intake → Credit Profiles]: Email*(email), What is your score today?(number)" in block
    assert 'headline "Your score, repaired."' in block and "Book a free review" in block
    # once the form exists by name, the block says so instead of asking again
    db.forms = [{"name": "new client intake"}]
    assert "Forms: all created." in bb.context_block("b1")


def test_context_block_reports_a_running_job_and_never_asks_for_a_second(door, monkeypatch):
    db, _ = door
    db.jobs = [{"id": "j1", "status": "running", "created_at": "2026-09-06T12:00:00+00:00"}]
    block = bb.context_block("b1")
    assert block.startswith("BUSINESS LAYOUT IN PROGRESS") and "do NOT emit" in block
    _lay_out(db, monkeypatch)
    block = bb.context_block("b1")
    assert block.startswith("BUSINESS LAYOUT IN PROGRESS") and "CARDS READY" not in block


def test_context_block_is_empty_without_a_map_or_after_the_window(door, monkeypatch):
    db, _ = door
    assert bb.context_block("b1") == ""
    db.specs.append({"id": "old", "status": "blueprint", "draft_json": _map(),
                     "created_at": "2025-01-01T00:00:00+00:00"})
    assert bb.context_block("b1") == ""


# ─── the handler, the job kind, the registry and the prompt ──────────

def test_the_verb_is_wired_classified_and_a_job_kind():
    import chief_of_staff as cos
    import chief_prompt
    import action_registry as reg
    import chief_jobs
    assert "propose_business_from_idea" in cos.ACTION_HANDLERS
    assert reg.REGISTRY["propose_business_from_idea"]["reversibility"] == "A"
    meta = chief_jobs.KIND_META[bb.JOB_KIND]
    assert meta["label"] and meta["working"] and meta["done"]
    src = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")
    assert '"type":"propose_business_from_idea"' in src
    assert "0. A WHOLE BUSINESS" in src
    assert "CARDS READY" in src and "BUSINESS BLUEPRINT ON FILE" in src


def _ready(shown=False, idea=IDEA):
    return {"ok": True, "shown": shown, "idea": idea,
            "blueprint_row": {"id": "bp1", "draft_json": {}},
            "decomposition_reasoning": "r",
            "proposals": [
                {"spec_id": "s1", "kind": "module", "spec": _spec("bookings", "Bookings", "booking_calendar")},
                {"spec_id": "s2", "kind": "module", "spec": _spec("credit-profiles", "Credit Profiles")},
                {"spec_id": "s3", "kind": "offering", "offering": {"name": "Monthly Credit Repair", "slug": "m"}},
            ],
            "forms": [{"name": "New Client Intake"}], "site": {"headline": "h"},
            "rails": {}, "business_type": "consultant"}


def test_the_handler_shows_waiting_cards_and_keeps_an_existing_bookings(monkeypatch):
    # asyncio.run, not pytest.mark.asyncio: CI has no pytest-asyncio plugin.
    import chief_module_actions as cma
    shown = []
    monkeypatch.setattr(bb, "replay", lambda bid: _ready())
    monkeypatch.setattr(bb, "mark_shown", lambda row: shown.append(row["id"]))
    monkeypatch.setattr(msg, "_existing_single_instance_modules",
                        lambda bid: [{"archetype": "booking_calendar", "name": "Bookings"}])
    out = asyncio.run(cma.handle_propose_business_from_idea(
        None, {"id": "b1", "name": "Score Up"}, {"type": "propose_business_from_idea", "idea": "anything"}))
    assert out["type"] == "propose_module_from_intake"       # the dock's card stack
    assert out["origin"] == "business_blueprint"
    assert [p["spec_id"] for p in out["proposals"]] == ["s2", "s3"]
    assert "kept your existing Bookings" in out["label"]
    assert "1 module + 1 offering" in out["label"]
    assert "1 form and the site brief follow" in out["label"]
    assert shown == ["bp1"]


def test_the_handler_replays_shown_cards_only_for_the_same_idea(monkeypatch):
    import chief_module_actions as cma
    monkeypatch.setattr(bb, "replay", lambda bid: _ready(shown=True))
    monkeypatch.setattr(bb, "mark_shown", lambda row: None)
    monkeypatch.setattr(bb, "active_job", lambda bid: None)
    monkeypatch.setattr(msg, "_existing_single_instance_modules", lambda bid: [])
    enq = []

    async def fake_enqueue(client, **kw):
        enq.append(kw); return {"id": "job-1"}
    import chief_jobs
    monkeypatch.setattr(chief_jobs, "enqueue", fake_enqueue)
    # same idea again → the cards, no job
    out = asyncio.run(cma.handle_propose_business_from_idea(
        None, {"id": "b1", "name": "Score Up", "owner_id": "u1"}, {"type": "propose_business_from_idea", "idea": IDEA}))
    assert out["type"] == "propose_module_from_intake" and not enq
    # a different idea → a new job
    out = asyncio.run(cma.handle_propose_business_from_idea(
        None, {"id": "b1", "name": "Score Up", "owner_id": "u1"},
        {"type": "propose_business_from_idea", "idea": "I run a bakery with wholesale accounts and a storefront"}))
    assert out["type"] == "propose_business_from_idea" and out["job_id"] == "job-1"
    assert enq[0]["kind"] == bb.JOB_KIND and enq[0]["params"]["idea"].startswith("I run a bakery")
    assert "two to four minutes" in out["label"]


def test_the_handler_never_starts_a_second_job(monkeypatch):
    import chief_module_actions as cma
    monkeypatch.setattr(bb, "replay", lambda bid: None)
    monkeypatch.setattr(bb, "active_job", lambda bid: {"id": "j9", "status": "running"})
    out = asyncio.run(cma.handle_propose_business_from_idea(
        None, {"id": "b1", "name": "Score Up", "owner_id": "u1"}, {"type": "propose_business_from_idea", "idea": IDEA}))
    assert out["result"] == "business layout already in progress" and out["job_id"] == "j9"


def test_the_handler_needs_an_idea():
    import chief_module_actions as cma
    out = asyncio.run(cma.handle_propose_business_from_idea(None, {"id": "b1"}, {"type": "propose_business_from_idea"}))
    assert out.get("result", "").startswith("Failed") or out.get("error") or "idea" in json.dumps(out).lower()
