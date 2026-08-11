"""
test_module_inspect.py — Chief looks at what it built.

The failure this guards: materialize_spec wrote a custom_modules row and
Chief announced "✅ X is live in Build" on the strength of the insert
returning. A schema that DynamicModule refuses — views:['board'] with no
usable board_column — materializes perfectly and renders as a red "This
module's schema is invalid" panel. Success reported; practitioner clicks
through to an error.

module_inspect is a PORT of the frontend's validateModuleSchema. The
tests below pin the accept/reject set to the frontend's, because a mirror
that silently stops mirroring is worse than no mirror: it would report
"renders fine" about a module the app refuses to draw.
"""

import module_inspect as mi
import module_vocabulary as mv


def _field(name="title", ftype="text", **kw):
    f = {"name": name, "type": ftype, "label": name.replace("_", " ").title()}
    f.update(kw)
    return f


def _schema(**kw):
    s = {"fields": [_field()], "views": ["list"]}
    s.update(kw)
    return s


# ─── The renderer's contract, mirrored ────────────────────────────────

def test_a_plain_valid_module_renders():
    rep = mi.inspect_module_schema(_schema())
    assert rep["renderable"] is True
    assert rep["problems"] == []


def test_schema_must_be_an_object():
    assert not mi.inspect_module_schema(None)["renderable"]
    assert not mi.inspect_module_schema([])["renderable"]


def test_fields_must_be_non_empty():
    assert not mi.inspect_module_schema(_schema(fields=[]))["renderable"]


def test_views_must_be_non_empty():
    assert not mi.inspect_module_schema(_schema(views=[]))["renderable"]


def test_duplicate_field_name_is_a_problem():
    rep = mi.inspect_module_schema(_schema(fields=[_field("a"), _field("a")]))
    assert not rep["renderable"]
    assert any("duplicated" in p for p in rep["problems"])


def test_missing_label_is_a_problem():
    bad = {"name": "x", "type": "text"}
    rep = mi.inspect_module_schema(_schema(fields=[bad]))
    assert not rep["renderable"]
    assert any("label missing" in p for p in rep["problems"])


def test_unknown_field_type_is_a_problem():
    rep = mi.inspect_module_schema(_schema(fields=[_field("x", "rating")]))
    assert not rep["renderable"]
    assert any("type invalid" in p for p in rep["problems"])


def test_every_vocabulary_field_type_is_accepted():
    """The inspector must not be stricter than the vocabulary — a type
    Chief is told it may use has to survive inspection, or Phase 1's whole
    point is undone at the next gate."""
    for ftype in mv.FIELD_TYPES:
        f = _field("f", ftype)
        if ftype == "select":
            f["options"] = ["a"]
        rep = mi.inspect_module_schema({"fields": [f], "views": ["list"]})
        assert rep["renderable"], f"{ftype} rejected: {rep['problems']}"


def test_select_without_options_is_a_problem():
    rep = mi.inspect_module_schema(_schema(fields=[_field("s", "select")]))
    assert not rep["renderable"]
    assert any("no options" in p for p in rep["problems"])


# ─── THE bug: the board view that renders a red panel ─────────────────

def test_board_view_without_board_column_is_caught():
    """This exact schema materialized cleanly and rendered as the error
    panel while Chief said it was live."""
    rep = mi.inspect_module_schema(_schema(views=["list", "board"]))
    assert not rep["renderable"]
    assert any("board_column" in p for p in rep["problems"])


def test_board_column_pointing_at_a_missing_field_is_caught():
    rep = mi.inspect_module_schema(_schema(views=["board"], board_column="nope"))
    assert not rep["renderable"]
    assert any("not found in fields" in p for p in rep["problems"])


def test_board_column_must_be_a_select():
    rep = mi.inspect_module_schema(_schema(
        fields=[_field("status", "text")], views=["board"], board_column="status"))
    assert not rep["renderable"]
    assert any("must be a select" in p for p in rep["problems"])


def test_a_correct_board_module_renders():
    rep = mi.inspect_module_schema(_schema(
        fields=[_field("status", "select", options=["new", "done"])],
        views=["list", "board"], board_column="status"))
    assert rep["renderable"], rep["problems"]


# ─── Warnings: renders, but doesn't behave ────────────────────────────

def test_offering_ref_without_categories_warns_but_still_renders():
    """Deliberately a WARNING, not a problem. The frontend validator does
    not enforce this (tightening a hard render gate can black out a live
    module), so calling it a problem here would have the backend refuse
    what the app happily draws."""
    rep = mi.inspect_module_schema(_schema(fields=[_field("svc", "offering_ref")]))
    assert rep["renderable"] is True
    assert any("offering_categories" in w for w in rep["warnings"])


def test_overdue_trigger_on_a_non_date_field_warns():
    """A trigger like this saves, shows in the UI, and never fires. The
    module looks perfect — which is why this has to be surfaced."""
    rep = mi.inspect_module_schema(
        _schema(fields=[_field("due", "text")]),
        {"triggers": [{"type": "overdue", "field": "due", "action": "draft_reminder"}]})
    assert rep["renderable"] is True
    assert any("not a date field" in w for w in rep["warnings"])


def test_overdue_trigger_on_a_missing_field_warns():
    rep = mi.inspect_module_schema(
        _schema(), {"triggers": [{"type": "overdue", "field": "ghost", "action": "x"}]})
    assert any("not a field" in w for w in rep["warnings"])


def test_unknown_trigger_kind_warns():
    rep = mi.inspect_module_schema(
        _schema(), {"triggers": [{"type": "on_tuesday", "action": "x"}]})
    assert any("never fire" in w for w in rep["warnings"])


def test_closed_statuses_that_match_nothing_warn():
    rep = mi.inspect_module_schema(
        _schema(fields=[_field("status", "select", options=["new", "done"])]),
        {"closed_statuses": ["complete"]})
    assert any("closed_statuses" in w for w in rep["warnings"])


def test_valid_triggers_produce_no_warnings():
    rep = mi.inspect_module_schema(
        _schema(fields=[_field("due", "date"),
                        _field("status", "select", options=["new", "done"])]),
        {"triggers": [{"type": "overdue", "field": "due", "action": "draft_reminder"},
                      {"type": "new_entry", "action": "draft_acknowledgment"}],
         "closed_statuses": ["done"]})
    assert rep["renderable"] and rep["warnings"] == [], rep["warnings"]


# ─── Reading the row back ─────────────────────────────────────────────

def test_a_row_that_never_came_back_is_a_problem():
    """materialize_spec used to return ok:True with module:None. Chief
    then said "✅ module is live in Build" about nothing at all."""
    rep = mi.inspect_module_row(None)
    assert not rep["renderable"]
    assert any("could not be read back" in p for p in rep["problems"])


def test_inactive_module_warns():
    rep = mi.inspect_module_row(
        {"name": "X", "schema": _schema(), "agent_config": {}, "is_active": False})
    assert rep["renderable"]
    assert any("inactive" in w for w in rep["warnings"])


def test_row_with_no_name_or_slug_is_a_problem():
    rep = mi.inspect_module_row({"schema": _schema(), "agent_config": {}})
    assert not rep["renderable"]


# ─── Repair ───────────────────────────────────────────────────────────

def test_repair_drops_an_undrawable_board_and_says_so():
    fixed, notes = mi.repair_schema(_schema(views=["list", "board"]))
    assert fixed["views"] == ["list"]
    assert "board_column" not in fixed
    assert notes and "board" in notes[0]
    assert mi.inspect_module_schema(fixed)["renderable"]


def test_repair_moves_default_view_off_the_dropped_board():
    fixed, _ = mi.repair_schema(
        _schema(views=["list", "board"], default_view="board"))
    assert fixed["default_view"] == "list"


def test_repair_leaves_a_valid_board_alone():
    original = _schema(fields=[_field("status", "select", options=["a", "b"])],
                       views=["list", "board"], board_column="status")
    fixed, notes = mi.repair_schema(original)
    assert notes == []
    assert fixed["views"] == ["list", "board"]


def test_repair_will_not_invent_a_board_column():
    """The narrowness is the design. Promoting some text field to a kanban
    column would build a workflow the practitioner never asked for; a
    module that opens as a list is honest."""
    fixed, _ = mi.repair_schema(_schema(fields=[_field("a"), _field("b")],
                                        views=["list", "board"]))
    assert fixed["views"] == ["list"]
    assert fixed.get("board_column") is None


def test_repair_cannot_rescue_a_board_only_module():
    """views:['board'] alone leaves nothing to fall back to. Repair
    declines rather than fabricating a list view, and the inspector then
    reports it honestly instead of Chief claiming success."""
    fixed, notes = mi.repair_schema(_schema(views=["board"]))
    assert fixed["views"] == ["board"]
    assert notes == []
    assert not mi.inspect_module_schema(fixed)["renderable"]


# ─── End-to-end: what Chief actually SAYS ─────────────────────────────
# The unit tests above prove the inspector is right. These prove the
# inspector's verdict reaches the practitioner — a check nobody reads is
# the same as no check.

import asyncio

import chief_of_staff as cos


def _accept(monkeypatch, verification):
    """Drive handle_accept_module_spec with a stubbed materialize."""
    import module_spec_generator as msg

    monkeypatch.setattr(cos.sb_clients, "sb_get_as_service",
                        lambda *a, **k: [{"draft_json": {"name": "Bookings",
                                                         "slug": "bookings",
                                                         "fields": []}}])
    # vertical_scope is imported INSIDE the handler, so it is not an
    # attribute of chief_of_staff — patch the module itself.
    import vertical_scope
    monkeypatch.setattr(vertical_scope, "check_module_scope",
                        lambda *a, **k: (True, None))
    monkeypatch.setattr(msg, "materialize_spec", lambda spec_id: {
        "ok": True,
        "module": {"id": "m1", "name": "Bookings"},
        "verification": verification,
    })
    return asyncio.run(cos.handle_accept_module_spec(
        None, {"id": "b1", "type": "coach"}, {"spec_id": "s1"}))


def test_chief_does_not_claim_live_for_a_module_that_wont_render(monkeypatch):
    """THE regression. Before this pass Chief said "✅ Bookings is live in
    Build" here, and the practitioner clicked through to a red panel."""
    out = _accept(monkeypatch, {
        "renderable": False,
        "problems": ["board view requires board_column"],
        "warnings": [],
    })
    assert "✅" not in out["label"]
    assert "live in Build" not in out["label"]
    assert "board_column" in out["result"]


def test_chief_still_says_live_when_the_module_is_fine(monkeypatch):
    out = _accept(monkeypatch, {"renderable": True, "problems": [], "warnings": []})
    assert out["label"] == "✅ Bookings is live in Build"


def test_chief_reports_a_repair_it_made(monkeypatch):
    out = _accept(monkeypatch, {
        "renderable": True, "problems": [], "warnings": [],
        "repairs": ["removed the board view: it needs a choice field to group by"],
    })
    assert "✅" in out["label"] and "removed the board view" in out["label"]


def test_chief_surfaces_a_trigger_that_will_never_fire(monkeypatch):
    out = _accept(monkeypatch, {
        "renderable": True, "problems": [],
        "warnings": ['"overdue" trigger points at "due", which is not a date field'],
    })
    assert "✅" in out["label"]
    assert "not a date field" in out["result"]
