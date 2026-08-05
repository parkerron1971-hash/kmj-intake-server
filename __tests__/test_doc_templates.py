# __tests__/test_doc_templates.py
#
# The document template library + /doctemplates surface. The integrity
# tests are the point: every placeholder in every template must resolve
# from declared fields or the standard variables — a typo'd placeholder
# in a retainer is a defect the library can never ship with.

import asyncio
import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import doc_templates as dt  # noqa: E402
import doc_templates_router as dtr  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"
    email = "owner1@x.com"


class _Stranger:
    id = "intruder"
    email = "evil@x.com"


BIZ = "b1"

_STANDARD_VARS = {"business_name", "practitioner_name", "client_name", "date"}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


# ─── Library integrity ───────────────────────────────────────────────

def test_every_placeholder_resolves():
    for t in dt.TEMPLATES:
        allowed = _STANDARD_VARS | {f["key"] for f in t["fields"]}
        for s in t["sections"]:
            for text in (s.get("text"), s.get("brief"), s.get("fallback")):
                if not text:
                    continue
                for var in _PLACEHOLDER.findall(text):
                    assert var in allowed, \
                        f"{t['id']}: placeholder {{{var}}} has no source"


def test_library_shape_and_uniqueness():
    ids = [t["id"] for t in dt.TEMPLATES]
    assert len(ids) == len(set(ids)) == 9
    for t in dt.TEMPLATES:
        assert t["title"] and t["description"] and t["category"]
        assert t["suggested_for"], f"{t['id']} suggests nothing"
        assert any(f["required"] for f in t["fields"]), \
            f"{t['id']} has no required field"
        # conditional sections must key on a real field
        keys = {f["key"] for f in t["fields"]}
        for s in t["sections"]:
            if s.get("requires"):
                assert s["requires"] in keys
        # every drafted section can survive the model being down
        for s in t["sections"]:
            if s["kind"] == "drafted":
                assert (s.get("fallback") or "").strip()


def test_assemble_conditionals_fallbacks_and_review_note():
    t = dt.TEMPLATE_INDEX["engagement_letter"]
    v = dt.build_vars(t, {"scope": "The Northside lease", "fee": "$300/hour"},
                      business_name="Reyes Law", practitioner_name="A. Reyes",
                      client_name="Dana Whitfield", date_str="August 4, 2026")
    body = dt.assemble(t, v, {}, include_review_note=True)
    # fallback carried the drafted opener
    assert "Thank you for engaging Reyes Law" in body
    # no deposit given → no deposit clause; no state → no governing law
    assert "DEPOSIT" not in body and "GOVERNING LAW" not in body
    # load-bearing clauses present, variables resolved
    assert "The Northside lease" in body and "$300/hour" in body
    assert "SCOPE OF ENGAGEMENT" in body and "ENDING THE ENGAGEMENT" in body
    assert "Dana Whitfield" in body and "{" not in body.replace("{client_name}", "")
    assert "not legal advice" in body

    # lawyer's own paper carries no review note; deposit clause appears when given
    v2 = dt.build_vars(t, {"scope": "s", "fee": "$1", "deposit": "$1,500",
                           "state": "Georgia"},
                       business_name="Reyes Law", practitioner_name="A. Reyes",
                       client_name="Dana", date_str="August 4, 2026")
    body2 = dt.assemble(t, v2, {0: "Custom drafted opener."},
                        include_review_note=False)
    assert "not legal advice" not in body2
    assert "DEPOSIT" in body2 and "$1,500" in body2
    assert "GOVERNING LAW" in body2 and "Georgia" in body2
    assert "Custom drafted opener." in body2


def test_defaults_apply_and_validation_catches_missing():
    t = dt.TEMPLATE_INDEX["mutual_nda"]
    assert dt.validate_params(t, {}) is not None          # purpose required
    assert dt.validate_params(t, {"purpose": "eval"}) is None
    v = dt.build_vars(t, {"purpose": "eval"}, business_name="B",
                      practitioner_name="P", client_name="C", date_str="D")
    assert v["term_years"] == "2"                          # default applied
    body = dt.assemble(t, v, {}, include_review_note=True)
    assert "2 years" in body


# ─── Router ──────────────────────────────────────────────────────────

@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients

    def get_with_ilike(path):
        # FakeSB treats unknown operators as match-all; _resolve_contact
        # uses name=ilike.*X* — emulate it so a miss is really a miss.
        m = re.search(r"name=ilike\.\*(.+?)\*", path)
        rows = fb.get(re.sub(r"&?name=ilike\.[^&]*", "", path))
        if m:
            needle = m.group(1).lower()
            rows = [r for r in rows if needle in (r.get("name") or "").lower()]
        return rows

    monkeypatch.setattr(sb_clients, "sb_get_as_service", get_with_ilike)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    fb.rows("businesses").append({
        "id": BIZ, "owner_id": "owner1", "name": "Reyes Law",
        "type": "lawyer", "settings": {"practitioner_name": "Alicia Reyes"},
        "voice_profile": {}})
    fb.rows("contacts").append({
        "id": "c9", "business_id": BIZ, "name": "Dana Whitfield",
        "email": "dana@x.com"})
    return fb


@pytest.fixture
def wired(fake, monkeypatch):
    rec = {"units": []}
    monkeypatch.setattr(dtr.billing_limits, "require_units",
                        lambda biz: rec["units"].append(biz))
    monkeypatch.setattr(dtr.llm_call, "api_key", lambda: "")  # fallbacks path
    return rec


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user
    by_path = {}
    for r in dtr.router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
        assert require_user in [d.call for d in r.dependant.dependencies], \
            f"{r.path} is missing require_user"
    assert "GET" in by_path.get("/doctemplates/list", set())
    assert "POST" in by_path.get("/doctemplates/generate", set())


def test_list_ranks_suggested_first(fake):
    out = asyncio.run(dtr.doctemplates_list(BIZ, _User()))
    ts = out["templates"]
    assert len(ts) == 9
    # lawyer templates lead; once a non-suggested appears, no suggested follows
    seen_unsuggested = False
    for t in ts:
        if not t["suggested"]:
            seen_unsuggested = True
        assert not (seen_unsuggested and t["suggested"])
    assert ts[0]["suggested"] and ts[0]["id"] in (
        "engagement_letter", "retainer_agreement", "mutual_nda",
        "demand_letter", "disengagement_letter")


def test_generate_lands_the_queue_draft(fake, wired):
    body = dtr.GenerateBody(
        business_id=BIZ, contact_id="c9", template_id="engagement_letter",
        params={"scope": "The Northside lease negotiation",
                "fee": "$300/hour", "deposit": "$1,500"})
    out = asyncio.run(dtr.doctemplates_generate(body, _User()))
    assert out["ok"] and out["queue_id"]
    assert out["drafted_sections_used"] is False          # model off → fallbacks
    assert "Dana Whitfield" in out["body"]
    assert "$1,500" in out["body"]
    assert "not legal advice" not in out["body"]          # lawyer's own paper

    rows = fake.rows("agent_queue")
    assert len(rows) == 1
    q = rows[0]
    assert q["agent"] == "contract" and q["action_type"] == "document"
    assert q["status"] == "draft" and q["channel"] == "email"
    assert q["contact_id"] == "c9"
    assert q["subject"] == "Engagement Letter — Reyes Law"
    # the generation charged a unit and hit the event spine
    assert wired["units"] == [BIZ]
    events = fake.rows("events")
    assert len(events) == 1 and events[0]["event_type"] == "document_generated"
    assert events[0]["data"]["queue_id"] == q["id"]


def test_generate_guards(fake, wired):
    ok = {"scope": "s", "fee": "$1"}
    with pytest.raises(HTTPException) as e:
        asyncio.run(dtr.doctemplates_generate(dtr.GenerateBody(
            business_id=BIZ, contact_id="c9",
            template_id="engagement_letter", params=ok), _Stranger()))
    assert e.value.status_code == 403

    with pytest.raises(HTTPException) as e:
        asyncio.run(dtr.doctemplates_generate(dtr.GenerateBody(
            business_id=BIZ, contact_id="c9",
            template_id="nope", params=ok), _User()))
    assert e.value.status_code == 404

    with pytest.raises(HTTPException) as e:
        asyncio.run(dtr.doctemplates_generate(dtr.GenerateBody(
            business_id=BIZ, contact_id="c9",
            template_id="engagement_letter", params={"fee": "$1"}), _User()))
    assert e.value.status_code == 400          # scope missing

    with pytest.raises(HTTPException) as e:
        asyncio.run(dtr.doctemplates_generate(dtr.GenerateBody(
            business_id=BIZ, contact_id="ghost",
            template_id="engagement_letter", params=ok), _User()))
    assert e.value.status_code == 404          # contact not found
    assert fake.rows("agent_queue") == []      # nothing queued on any failure


# ─── Chief's generate_document verb ──────────────────────────────────

def test_resolve_template_fuzzy():
    assert dtr.resolve_template("mutual_nda")["id"] == "mutual_nda"
    assert dtr.resolve_template("NDA")["id"] == "mutual_nda"
    assert dtr.resolve_template("demand letter")["id"] == "demand_letter"
    assert dtr.resolve_template("retainer")["id"] == "retainer_agreement"
    assert dtr.resolve_template("closing letter")["id"] == "disengagement_letter"
    assert dtr.resolve_template("sonnet") is None
    # "agreement" is ambiguous → a list comes back, never a guess
    hit = dtr.resolve_template("agreement")
    assert isinstance(hit, list) and len(hit) > 1


def test_verb_registered_and_dispatched():
    import action_registry
    assert "generate_document" in action_registry.REGISTRY
    entry = action_registry.REGISTRY["generate_document"]
    assert entry["reversibility"] == "A" and not entry.get("bulk")
    from chief_contract_actions import handle_generate_document
    assert callable(handle_generate_document)


def test_verb_happy_path_lands_draft(fake, wired):
    from chief_contract_actions import handle_generate_document
    biz = fake.rows("businesses")[0]
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "nda",
        "contact_name": "Dana",
        "params": {"purpose": "evaluating a joint venture"},
    }))
    assert not out.get("failed")
    assert out["type"] == "generate_document"
    assert out["template_id"] == "mutual_nda"
    assert out["queue_id"] and out["nav"] == {"tab": "operate", "sub": "queue"}
    # model off in this fixture → the honest degradation note
    assert "standard wording" in out["result"]
    rows = fake.rows("agent_queue")
    assert len(rows) == 1 and rows[0]["action_type"] == "document"


def test_verb_refuses_instead_of_inventing(fake, wired):
    from chief_contract_actions import handle_generate_document
    biz = fake.rows("businesses")[0]

    # missing required param → asks for it BY LABEL, queues nothing
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "demand letter",
        "contact_name": "Dana", "params": {"amount": "$1,850"},
    }))
    assert out.get("failed") and "What it's owed for" in out["result"]

    # unknown template → lists the library
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "warranty deed",
        "contact_name": "Dana", "params": {},
    }))
    assert out.get("failed") and "Mutual Nondisclosure" in out["result"]

    # unknown contact → refused
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "nda",
        "contact_name": "Zebulon", "params": {"purpose": "x"},
    }))
    assert out.get("failed")
    assert fake.rows("agent_queue") == []


def test_verb_gathers_flat_params(fake, wired):
    # Chief sometimes emits fields flat on the action instead of in params.
    from chief_contract_actions import handle_generate_document
    biz = fake.rows("businesses")[0]
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "demand_letter",
        "contact_name": "Dana",
        "amount": "$2,000", "owed_for": "Invoice #2041",
    }))
    assert not out.get("failed")
    body = fake.rows("agent_queue")[0]["body"]
    assert "$2,000" in body and "Invoice #2041" in body


# ─── Learned defaults — the first contract teaches the system ────────

@pytest.fixture
def patchable(fake, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    return fake


def test_first_contract_teaches_then_second_fills_itself(patchable, wired):
    from chief_contract_actions import handle_generate_document
    fake = patchable
    biz = fake.rows("businesses")[0]

    # FIRST document: fee + state given explicitly → generated AND saved.
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "engagement_letter",
        "contact_name": "Dana",
        "params": {"scope": "The Northside lease", "fee": "$300/hour",
                   "state": "Georgia"},
    }))
    assert not out.get("failed")
    assert "I've saved" in out["result"] and "fee" in out["result"]
    saved = fake.rows("businesses")[0]["settings"]["doc_defaults"]
    assert saved == {"fee": "$300/hour", "state": "Georgia"}
    # engagement facts are never saved
    assert "scope" not in saved

    # SECOND document: no fee/state given — the defaults fill them,
    # the result names what was pulled, and nothing re-asks.
    out2 = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "engagement_letter",
        "contact_name": "Dana",
        "params": {"scope": "Trademark filing"},
    }))
    assert not out2.get("failed")
    assert "Filled from your standard terms" in out2["result"]
    assert "fee = $300/hour" in out2["result"]
    body = fake.rows("agent_queue")[1]["body"]
    assert "$300/hour" in body and "Georgia" in body
    # nothing new was saved the second time (values came from defaults)
    assert "I've saved" not in out2["result"]

    # EXPLICIT beats saved: a different fee this time wins and re-saves.
    out3 = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "engagement_letter",
        "contact_name": "Dana",
        "params": {"scope": "Appeal", "fee": "$5,000 flat"},
    }))
    assert not out3.get("failed")
    assert "$5,000 flat" in fake.rows("agent_queue")[2]["body"]
    assert fake.rows("businesses")[0]["settings"]["doc_defaults"]["fee"] == "$5,000 flat"


def test_first_time_hint_and_list_overlay(patchable, wired):
    from chief_contract_actions import handle_generate_document
    fake = patchable
    biz = fake.rows("businesses")[0]

    # No defaults yet + missing required → the walk-through hint rides along.
    out = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "engagement_letter",
        "contact_name": "Dana", "params": {},
    }))
    assert out.get("failed") and "first one" in out["result"]

    # After terms exist, /list pre-fills sticky fields for the dialog.
    biz["settings"]["doc_defaults"] = {"fee": "$300/hour", "state": "Georgia"}
    listed = asyncio.run(dtr.doctemplates_list(BIZ, _User()))
    eng = next(t for t in listed["templates"] if t["id"] == "engagement_letter")
    by_key = {f["key"]: f for f in eng["fields"]}
    assert by_key["fee"]["default"] == "$300/hour"
    assert by_key["state"]["default"] == "Georgia"
    assert by_key["scope"]["default"] == ""          # engagement facts never pre-fill
    # and the second miss no longer claims first-time
    out2 = asyncio.run(handle_generate_document(None, biz, {
        "type": "generate_document", "template": "engagement_letter",
        "contact_name": "Dana", "params": {},
    }))
    assert out2.get("failed")
    assert "Scope of the engagement" in out2["result"]   # still asks for scope
    assert "Fee" not in out2["result"].replace("Fee, state", "")  # fee satisfied by default
    assert "first one" not in out2["result"]


# ─── Visual pass — the paper rides along with the list ───────────────

def test_list_ships_subtitles_sections_and_page_estimates(fake):
    out = asyncio.run(dtr.doctemplates_list(BIZ, _User()))
    for t in out["templates"]:
        assert t["subtitle"], f"{t['id']} missing subtitle"
        assert t["sections"] and all("text" in s for s in t["sections"])
        assert t["page_estimate"].startswith("≈")
    eng = next(t for t in out["templates"] if t["id"] == "engagement_letter")
    # placeholders intact for live frontend substitution
    joined = "\n".join(s["text"] for s in eng["sections"])
    assert "{scope}" in joined and "{client_name}" in joined
    # conditional sections carry their gate
    assert any(s.get("requires") == "deposit" for s in eng["sections"])
    # drafted sections shipped as their fallback (no briefs leak)
    assert "one-paragraph professional opener" not in joined


# ─── Learn from upload — their paper becomes a template ──────────────

def test_normalize_custom_auto_declares_and_sanitizes():
    raw = {
        "title": "Wedding Photography Contract",
        "subtitle": "Coverage, Payment & Deliverables",
        "fields": [
            {"key": "package_price", "label": "Package price", "required": True,
             "sticky": True, "placeholder": "$2,400"},
            {"key": "client_name", "label": "should be dropped"},   # standard var
        ],
        "sections": [
            {"heading": "1. COVERAGE", "text": "{business_name} will photograph the event on {event_date} for {package_price}."},
            {"heading": None, "text": "Delivery within {delivery_weeks} weeks to {client_name}."},
            {"heading": "", "text": "   "},                          # empty → dropped
        ],
    }
    t = dtr.normalize_custom(raw)
    keys = {f["key"] for f in t["fields"]}
    # declared field kept; standard var dropped; undeclared placeholders auto-declared
    assert keys == {"package_price", "event_date", "delivery_weeks"}
    assert t["category"] == "custom" and len(t["sections"]) == 2
    by_key = {f["key"]: f for f in t["fields"]}
    assert by_key["package_price"]["sticky"] is True
    assert by_key["event_date"]["required"] is False   # auto-declared → optional
    # every placeholder now resolves (the ship-with-a-hole guarantee)
    allowed = dtr._STANDARD_VARS | keys
    for s in t["sections"]:
        for var in dtr._PLACEHOLDER_RE.findall(s["text"]):
            assert var in allowed


def test_normalize_custom_rejects_sectionless():
    with pytest.raises(dtr.GenerationError):
        dtr.normalize_custom({"title": "X", "sections": []})


def test_custom_templates_list_generate_and_resolve(patchable, wired):
    fake = patchable
    fake.rows("business_doc_templates").append({
        "id": "row1", "business_id": BIZ,
        "template": {
            "id": "", "title": "Wedding Photography Contract",
            "subtitle": "Coverage, Payment & Deliverables",
            "description": "Learned from an upload.", "category": "custom",
            "suggested_for": [],
            "fields": [{"key": "package_price", "label": "Package price",
                        "type": "text", "required": True, "placeholder": "",
                        "default": "", "sticky": True}],
            "sections": [{"kind": "fixed", "heading": "1. COVERAGE",
                          "text": "{business_name} will photograph for {client_name} at {package_price}."}],
        },
        "created_at": "2026-08-04T00:00:00Z"})

    # list: custom leads, flagged, still ships sections/pages
    listed = asyncio.run(dtr.doctemplates_list(BIZ, _User()))
    first = listed["templates"][0]
    assert first["custom"] and first["id"] == "custom:row1"
    assert first["suggested"] and first["sections"]

    # generate through the same core via custom id
    out = asyncio.run(dtr.doctemplates_generate(dtr.GenerateBody(
        business_id=BIZ, contact_id="c9", template_id="custom:row1",
        params={"package_price": "$2,400"}), _User()))
    assert out["ok"] and "photograph for Dana Whitfield at $2,400" in out["body"]
    # sticky learned from the custom template too
    assert fake.rows("businesses")[0]["settings"]["doc_defaults"]["package_price"] == "$2,400"

    # Chief's resolver: exact custom title WINS; keyword reaches it too
    hit = dtr.resolve_template("Wedding Photography Contract", business_id=BIZ)
    assert hit["id"] == "custom:row1"
    hit = dtr.resolve_template("wedding", business_id=BIZ)
    assert hit["id"] == "custom:row1"
    # without business context, library behavior unchanged
    assert dtr.resolve_template("wedding") is None


def test_custom_delete_scoped_to_owner(patchable, monkeypatch):
    fake = patchable
    import sb_clients
    deleted = []
    monkeypatch.setattr(sb_clients, "sb_delete_as_service",
                        lambda p: deleted.append(p) or True)
    out = asyncio.run(dtr.doctemplates_delete_custom("row1", BIZ, _User()))
    assert out["ok"] and "business_id=eq.b1" in deleted[0]
    with pytest.raises(HTTPException) as e:
        asyncio.run(dtr.doctemplates_delete_custom("row1", BIZ, _Stranger()))
    assert e.value.status_code == 403
