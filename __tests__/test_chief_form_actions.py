"""Client Forms — the verbs that let Chief build the public intake door.

The contract these tests defend:
  • a Chief-written form ALWAYS carries a required field literally named
    `name` — intake_endpoint.submit_intake raises 400 on a submission
    without it, before it ever loads the form config, so a form missing
    it rejects every submission at the client's browser,
  • no field name can collide with intake_endpoint.HONEYPOT_FIELDS — a
    honeypot drops the submission and answers 200, which is invisible
    from outside by design,
  • the label → name transform matches IntakeFormBuilder's exactly, or
    the fields arrive under keys the form doesn't know,
  • a module link that matches nothing, or matches several, ASKS rather
    than filing real client answers under the wrong solution,
  • every return path carries result + label, and failures carry the
    machine-readable "failed": True flag (#345 seam),
  • the verbs are registered, classified, and named in Chief's own prompt
    — a verb the prompt never mentions is a verb the model never emits.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chief_form_actions as cfa
import sb_clients
from intake_endpoint import HONEYPOT_FIELDS

BIZ = {"id": "biz1", "name": "Test Co", "owner_id": "u1"}


def _run(coro):
    return asyncio.run(coro)


def _patch_writes(monkeypatch, *, gets=None, insert_id="form1"):
    """Capture what would be written; serve reads from `gets`."""
    captured = {"posts": [], "patches": []}

    def _get(path):
        for prefix, rows in (gets or {}).items():
            if path.startswith(prefix):
                return rows
        return []

    def _post(path, body, prefer="return=representation"):
        captured["posts"].append((path, body))
        if path.startswith("/intake_forms"):
            return [dict(body, id=insert_id)]
        return [dict(body)]

    def _patch(path, body):
        captured["patches"].append((path, body))
        return [body]

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)
    return captured


def _form_row(captured):
    return next(b for p, b in captured["posts"] if p.startswith("/intake_forms"))


# ─── the label → name transform ───────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("Your Name", "your_name"),
    ("What brought you in?", "what_brought_you_in"),
    ("E-mail  Address", "e_mail_address"),
    ("  Budget ($)  ", "budget"),
    ("Phone #", "phone"),
])
def test_field_name_mirrors_the_builder_transform(label, expected):
    assert cfa._field_name_from_label(label) == expected


def test_derived_names_can_never_be_a_honeypot():
    """Collision-proof by CONSTRUCTION, not by luck: a hyphen cannot
    survive the transform and a leading underscore is stripped. This is
    the same argument intake_endpoint makes from the other side, pinned
    here because THIS module is what writes the names."""
    for hp in HONEYPOT_FIELDS:
        assert cfa._field_name_from_label(hp) != hp


# ─── invariant 1: the name field ──────────────────────────────────────

def test_a_form_without_a_name_question_gets_one(monkeypatch):
    captured = _patch_writes(monkeypatch)
    res = _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Quote Request",
        "fields": [{"label": "What do you need?", "type": "textarea"}],
    }))
    assert not res.get("failed")
    fields = _form_row(captured)["fields"]
    name_field = next(f for f in fields if f["name"] == "name")
    assert name_field["required"] is True
    assert fields[0]["name"] == "name", "it goes first, where a form asks it"


def test_a_name_question_marked_optional_is_forced_required(monkeypatch):
    captured = _patch_writes(monkeypatch)
    _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Connect Card",
        "fields": [{"label": "Name", "type": "text", "required": False},
                   {"label": "Email", "type": "email", "required": True}],
    }))
    fields = _form_row(captured)["fields"]
    assert next(f for f in fields if f["name"] == "name")["required"] is True


def test_the_name_question_cannot_be_removed(monkeypatch):
    _patch_writes(monkeypatch, gets={"/intake_forms": [{
        "id": "form1", "business_id": "biz1", "name": "Intake",
        "fields": list(cfa._DEFAULT_FIELDS), "settings": {}, "is_active": True}]})
    res = _run(cfa.handle_update_client_form(None, BIZ, {
        "form_id": "form1", "remove_fields": ["Your Name"]}))
    assert res["failed"] is True
    assert "name question" in res["result"]


# ─── invariant 2: honeypots ───────────────────────────────────────────

def test_an_explicit_honeypot_name_is_refused(monkeypatch):
    captured = _patch_writes(monkeypatch)
    res = _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Trap", "fields": [
            {"label": "Name", "type": "text"},
            {"label": "Anti spam", "name": "_hp", "type": "text"}]}))
    assert res["failed"] is True
    assert "spam-trap" in res["result"]
    assert not captured["posts"], "nothing is written when a form is refused"


# ─── field normalization ──────────────────────────────────────────────

def test_type_synonyms_are_mapped_not_rejected(monkeypatch):
    captured = _patch_writes(monkeypatch)
    _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Intake", "fields": [
            {"label": "Name", "type": "text"},
            {"label": "Phone number", "type": "telephone"},
            {"label": "Notes", "type": "long_text"},
            {"label": "Source", "type": "dropdown", "options": ["Referral", "Google"]},
        ]}))
    by_name = {f["name"]: f for f in _form_row(captured)["fields"]}
    assert by_name["phone"]["type"] == "phone", (
        "'Phone number' lands on the key the submit door reads")
    assert by_name["notes"]["type"] == "textarea"
    assert by_name["source"]["type"] == "select"
    assert by_name["source"]["options"] == ["Referral", "Google"]


def test_a_select_with_no_options_is_demoted_not_shipped_dead(monkeypatch):
    captured = _patch_writes(monkeypatch)
    _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Intake", "fields": [{"label": "Name"},
                                     {"label": "Interest", "type": "select"}]}))
    by_name = {f["name"]: f for f in _form_row(captured)["fields"]}
    assert by_name["interest"]["type"] == "text", (
        "an empty dropdown is a control the client cannot answer")


def test_plain_strings_are_accepted_as_fields(monkeypatch):
    captured = _patch_writes(monkeypatch)
    _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Intake", "fields": ["Your Name", "Email", "What's going on?"]}))
    names = [f["name"] for f in _form_row(captured)["fields"]]
    assert names == ["name", "email", "what_s_going_on"], (
        "'Your Name' canonicalizes to `name` rather than becoming a SECOND "
        "name question next to the auto-added one, and the apostrophe "
        "becomes an underscore exactly as the builder transform does")
    types = {f["name"]: f["type"] for f in _form_row(captured)["fields"]}
    assert types["email"] == "email", "inferred from the name when no type is given"


def test_duplicate_fields_collapse(monkeypatch):
    captured = _patch_writes(monkeypatch)
    _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Intake", "fields": ["Name", "Email", "E-mail", "Email"]}))
    names = [f["name"] for f in _form_row(captured)["fields"]]
    assert names.count("email") == 1


def test_no_fields_gives_the_same_default_a_seeded_form_gets(monkeypatch):
    captured = _patch_writes(monkeypatch)
    _run(cfa.handle_create_client_form(None, BIZ, {"name": "Contact Form"}))
    names = [f["name"] for f in _form_row(captured)["fields"]]
    assert names == ["name", "email", "phone", "message"]


def test_an_enormous_field_list_is_capped_with_a_question(monkeypatch):
    captured = _patch_writes(monkeypatch)
    res = _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Intake",
        "fields": [f"Question {i}" for i in range(cfa.MAX_FIELDS + 1)]}))
    assert res["failed"] is True
    assert not captured["posts"]


def test_a_form_needs_a_name(monkeypatch):
    captured = _patch_writes(monkeypatch)
    res = _run(cfa.handle_create_client_form(None, BIZ, {"fields": ["Name"]}))
    assert res["failed"] is True
    assert not captured["posts"]


# ─── module linking ───────────────────────────────────────────────────

MODULE_ROWS = [{"id": "mod1", "name": "Equipment Rentals", "slug": "equipment-rentals",
                "schema": {"fields": [{"name": "name", "type": "text"},
                                      {"name": "message", "type": "textarea"},
                                      {"name": "returned", "type": "checkbox"}]}}]


def test_linking_a_module_wires_the_field_map(monkeypatch):
    captured = _patch_writes(monkeypatch, gets={"/custom_modules": MODULE_ROWS})
    res = _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Rental Request", "link_module": "Equipment Rentals"}))
    settings = _form_row(captured)["settings"]
    assert settings["linked_module_id"] == "mod1"
    assert settings["field_map"] == {"name": "name", "message": "message"}, (
        "only the pairs that agree; 'returned' has no form field")
    assert "Equipment Rentals" in res["result"]


def test_an_unknown_module_asks_instead_of_guessing(monkeypatch):
    captured = _patch_writes(monkeypatch, gets={"/custom_modules": []})
    res = _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Rental Request", "link_module": "Rentals"}))
    assert res["failed"] is True
    assert not captured["posts"], "no half-wired form is left behind"


def test_an_ambiguous_module_asks_which_one(monkeypatch):
    rows = MODULE_ROWS + [{"id": "mod2", "name": "Equipment Repairs",
                           "slug": "equipment-repairs", "schema": {"fields": []}}]
    captured = _patch_writes(monkeypatch, gets={"/custom_modules": rows})
    res = _run(cfa.handle_create_client_form(None, BIZ, {
        "name": "Request", "link_module": "Equipment"}))
    assert res["failed"] is True
    assert "Equipment Rentals" in res["result"] and "Equipment Repairs" in res["result"]
    assert not captured["posts"]


# ─── update ───────────────────────────────────────────────────────────

EXISTING = {"id": "form1", "business_id": "biz1", "name": "Intake",
            "form_type": "general", "fields": list(cfa._DEFAULT_FIELDS),
            "settings": {"confirmation_message": "Thanks."}, "is_active": True}


def test_update_adds_a_question_and_keeps_the_rest(monkeypatch):
    captured = _patch_writes(monkeypatch, gets={"/intake_forms": [dict(EXISTING)]})
    res = _run(cfa.handle_update_client_form(None, BIZ, {
        "form_id": "form1",
        "add_fields": [{"label": "Budget", "type": "select",
                        "options": ["Under $1k", "$1-5k"]}]}))
    assert not res.get("failed")
    path, body = captured["patches"][0]
    assert "business_id=eq.biz1" in path, "tenant filter on the write, always"
    names = [f["name"] for f in body["fields"]]
    assert names == ["name", "email", "phone", "message", "budget"]
    assert "Budget" in res["result"]


def test_update_can_switch_a_form_off(monkeypatch):
    captured = _patch_writes(monkeypatch, gets={"/intake_forms": [dict(EXISTING)]})
    res = _run(cfa.handle_update_client_form(None, BIZ, {
        "form_id": "form1", "is_active": False}))
    assert captured["patches"][0][1]["is_active"] is False
    assert "switched off" in res["result"]


def test_update_with_nothing_to_change_says_so(monkeypatch):
    captured = _patch_writes(monkeypatch, gets={"/intake_forms": [dict(EXISTING)]})
    res = _run(cfa.handle_update_client_form(None, BIZ, {"form_id": "form1"}))
    assert res["failed"] is True
    assert not captured["patches"]


def test_update_of_an_unknown_form_fails_cleanly(monkeypatch):
    captured = _patch_writes(monkeypatch, gets={"/intake_forms": []})
    res = _run(cfa.handle_update_client_form(None, BIZ, {"form_name": "Nope"}))
    assert res["failed"] is True
    assert not captured["patches"]


# ─── list ─────────────────────────────────────────────────────────────

def test_list_reports_submission_counts(monkeypatch):
    _patch_writes(monkeypatch, gets={
        "/intake_forms": [dict(EXISTING), dict(EXISTING, id="form2", name="Waitlist")],
        "/events": [{"data": {"form_id": "form1"}}, {"data": {"form_id": "form1"}},
                    {"data": {"form_id": "form2"}}],
    })
    res = _run(cfa.handle_list_client_forms(None, BIZ, {}))
    counts = {f["name"]: f["submissions"] for f in res["forms"]}
    assert counts == {"Intake": 2, "Waitlist": 1}
    assert "2 submissions" in res["result"]


def test_list_with_no_forms_offers_to_build_one(monkeypatch):
    _patch_writes(monkeypatch, gets={})
    res = _run(cfa.handle_list_client_forms(None, BIZ, {}))
    assert res["forms"] == []
    assert not res.get("failed"), "no forms is not a failure"


# ─── the shape every action card depends on ───────────────────────────

def test_every_return_path_carries_result_and_label(monkeypatch):
    """A missing `result` blanks the app — the frontend calls
    .toLowerCase() on it. Non-negotiable on success AND failure."""
    _patch_writes(monkeypatch, gets={"/intake_forms": [dict(EXISTING)]})
    calls = [
        cfa.handle_create_client_form(None, BIZ, {"name": "A"}),
        cfa.handle_create_client_form(None, BIZ, {}),                  # fails
        cfa.handle_update_client_form(None, BIZ, {"form_id": "form1",
                                                 "new_name": "B"}),
        cfa.handle_update_client_form(None, BIZ, {}),                  # fails
        cfa.handle_list_client_forms(None, BIZ, {}),
    ]
    for coro in calls:
        res = _run(coro)
        assert isinstance(res.get("result"), str) and res["result"]
        assert isinstance(res.get("label"), str) and res["label"]
        assert "type" in res


# ─── registration: a handler is not a capability ──────────────────────

VERBS = ("create_client_form", "update_client_form", "list_client_forms")


@pytest.mark.parametrize("verb", VERBS)
def test_verb_is_registered_and_classified(verb):
    import action_registry as reg
    import chief_of_staff as cos
    assert verb in cos.ACTION_HANDLERS
    assert verb in reg.known_verbs()


@pytest.mark.parametrize("verb", VERBS)
def test_chief_is_told_the_form_verbs_exist(verb):
    """The lesson inspect_module taught (#515, see test_add_module_field):
    registering a handler is not shipping a capability. A verb the prompt
    never names is a verb the model never emits — which is exactly how
    this whole surface stayed unreachable while its table, its submit
    door and its screen all worked."""
    import chief_of_staff as cos

    class _EmptyCtx(dict):
        def __missing__(self, key):
            return []

    prompt = cos._build_system_prompt(
        _EmptyCtx(business={"id": "b1", "name": "T", "type": "coach",
                            "settings": {}, "voice_profile": {}}), False)
    assert verb in prompt
