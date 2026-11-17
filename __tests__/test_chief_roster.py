"""Chief makes an event's volunteer list in the church's events room (chief_roster.py).

Kevin, 2026-11-17: "Laquesha couldn't make event volunteer list. can we make
sure that she has access and ability to make list and or make volunteers
list." She asked Chief; Chief emitted propose_module_from_intake (a new room,
the owner's and admins') and was refused, when Love City's events room
("Services & Events", an event_roster module) already holds each event's
volunteer roles and who's on them, and every office login adds to it.

Pins:
  * a role's id is the app's newRoleId; a role without an id never reaches
    the room (both readers drop one), so Chief never writes a role by hand
  * a new event's roles are the ones asked for; on an event already there a
    role named again keeps its id and takes its new number, the others stay,
    and nobody falls off a role; people go on their role, once each
  * create_module_entry and update_module_entry write that shape into an
    event_roster room, say where it is, and return both result and label;
    a person Chief links keeps the link only when they're the church's
  * the reply names the church's events page (its real address) only when
    people can sign themselves up there for an open spot
  * a lane's refused new list for an event's volunteers says where it goes
    (the events room, by name) instead of "ask the owner"
  * the manual routes an event's volunteers to the room, in the full brief
    and the short one
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_areas as ca  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_roster as cr  # noqa: E402
import sb_clients  # noqa: E402

BIZ = {"id": "11111111-1111-4111-8111-111111111111", "owner_id": "00000000-0000-4000-8000-000000000001",
       "name": "Love City Church", "type": "ministry", "settings": {}}
DANA = "cccccccc-0000-4000-8000-000000000001"
STRANGER = "dddddddd-0000-4000-8000-000000000009"
ROOM = {"id": "aaaaaaaa-0000-4000-8000-000000000001", "name": "Services & Events", "archetype": "event_roster",
        "archetype_params": {"title_field": "title", "date_field": "date", "signups_field": "signups",
                             "roles": [{"id": "greeters", "label": "Greeters", "needed": 2}]},
        "schema": {"fields": [{"name": "title"}, {"name": "date"}, {"name": "location"}]}, "agent_config": {}}
LAQUESHA = {"areas": ["worship_media"], "role": "manager", "lane": "sunday_serving"}


# ─── The shape ────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,taken,want", [
    ("Greeters", [], "greeters"),
    ("Greeters", ["greeters"], "greeters-2"),
    ("Greeters", ["greeters", "greeters-2"], "greeters-3"),
    ("Café & Kids!", [], "cafe-kids"),
    ("  Parking / Traffic  ", [], "parking-traffic"),
    ("!!!", [], "role"),
    ("Nursery and toddler room helpers", [], "nursery-and-toddler-room"),
], ids=["plain", "taken", "taken-twice", "accents", "spaces", "nothing-left", "long"])
def test_a_roles_id_is_the_apps_own(label, taken, want):
    assert cr.role_id(label, taken) == want


def test_a_new_events_roles_are_the_ones_asked_for_with_ids_the_room_reads():
    data, said = cr.shape(ROOM, {"title": "Fall Festival", "date": "2026-11-07"},
                          roles=[{"label": "Parking", "needed": 3}, "Face painting", {"label": "parking"}])
    assert data["_roles"] == [{"id": "parking", "label": "Parking", "needed": 3},
                              {"id": "face-painting", "label": "Face painting", "needed": 1}]
    assert said["roles"] == data["_roles"] and said["added"] == []
    assert "signups" not in data, "no people named, no list written"
    # Every role reaches the room: an id and a label, as event_roster/types.ts cleanRoles keeps them.
    assert cr.clean_roles(data["_roles"]) == data["_roles"]
    # A count map and a plain list of names read the same way; numbers stay 1-50.
    data, _ = cr.shape(ROOM, {"title": "Picnic"}, roles={"Grill": 2, "Games": 0, "Setup": 99})
    assert [(r["id"], r["needed"]) for r in data["_roles"]] == [("grill", 2), ("games", 1), ("setup", 50)]
    data, _ = cr.shape(ROOM, {"title": "Picnic"}, roles="Grill, Games")
    assert [r["label"] for r in data["_roles"]] == ["Grill", "Games"]


def test_roles_inside_data_are_lifted_unless_the_room_has_a_field_of_that_name():
    data, _ = cr.shape(ROOM, {"title": "Fall Festival", "roles": ["Ushers"], "_roles": [{"label": "Parking"}]})
    assert [r["id"] for r in data["_roles"]] == ["parking", "ushers"] and "roles" not in data
    own = {**ROOM, "schema": {"fields": [{"name": "title"}, {"name": "roles"}]}}
    data, said = cr.shape(own, {"title": "Fall Festival", "roles": "Ushers"})
    assert data["roles"] == "Ushers" and "_roles" not in data, "the room's own field is the room's"


def test_people_go_on_their_role_once_and_a_role_nobody_listed_is_added_for_them():
    data, said = cr.shape(ROOM, {"title": "Fall Festival"}, roles=["Parking"], volunteers=[
        {"name": "Dana Johnson", "role": "parking", "contact_id": DANA},
        {"name": "Tiara", "role": "Face painting"}, {"name": "Marcus", "role": "Face painting"},
        "Laquesha", {"name": "dana johnson", "role": "Parking"}])
    assert data["_roles"] == [{"id": "parking", "label": "Parking", "needed": 1},
                              {"id": "face-painting", "label": "Face painting", "needed": 2}]
    assert data["signups"] == [{"name": "Dana Johnson", "status": "yes", "contact_id": DANA, "role": "parking"},
                               {"name": "Tiara", "status": "yes", "role": "face-painting"},
                               {"name": "Marcus", "status": "yes", "role": "face-painting"},
                               {"name": "Laquesha", "status": "yes"}]
    assert said["added"] == data["signups"]
    # People alone, on a new event: the room's default roles are the ones they fill.
    data, _ = cr.shape(ROOM, {"title": "Sunday"}, volunteers=[{"name": "Ana", "role": "Greeters"}])
    assert "_roles" not in data and data["signups"] == [{"name": "Ana", "status": "yes", "role": "greeters"}]


def test_an_event_already_there_keeps_its_roles_and_its_people():
    before = {"title": "Fall Festival", "date": "2026-11-07",
              "_roles": [{"id": "parking", "label": "Parking", "needed": 2}, {"id": "games", "label": "Games", "needed": 1}],
              "signups": [{"name": "Dana Johnson", "status": "yes", "role": "parking"},
                          {"name": "Visitor", "status": "maybe"}]}
    data, said = cr.shape(ROOM, {}, before=before, roles=[{"label": "PARKING", "needed": 4}, "Cleanup"],
                          volunteers=[{"name": "Dana Johnson", "role": "Parking"}, {"name": "Ana", "role": "Cleanup"}])
    assert data["_roles"] == [{"id": "parking", "label": "Parking", "needed": 4},
                              {"id": "games", "label": "Games", "needed": 1},
                              {"id": "cleanup", "label": "Cleanup", "needed": 1}]
    assert data["signups"] == before["signups"] + [{"name": "Ana", "status": "yes", "role": "cleanup"}]
    assert data["title"] == "Fall Festival" and data["date"] == "2026-11-07"
    assert before["_roles"][0]["needed"] == 2, "what was read is never changed in place"
    # An event on the room's default list starts from it.
    data, _ = cr.shape(ROOM, {}, before={"title": "Sunday"}, roles=["Parking"])
    assert [r["id"] for r in data["_roles"]] == ["greeters", "parking"]
    # Nothing about roles: the data as it was, with the patch.
    data, said = cr.shape(ROOM, {"location": "Hall"}, before=before)
    assert data == {**before, "location": "Hall"} and said["added"] == []


def test_the_label_says_the_room_the_event_and_its_roles():
    assert cr.roles_words([]) == ""
    assert cr.roles_words([{"label": "Parking", "needed": 3}]) == "1 volunteer role: Parking 3"


# ─── The handlers ─────────────────────────────────────────────────────

def _fake(monkeypatch, entry=None, module=ROOM):
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        if method == "GET" and path.startswith("/custom_modules?id=eq."):
            return [module] if module and module["id"] in path else []
        if method == "GET" and path.startswith("/custom_modules?name=ilike."):
            return [module] if module else []
        if method == "GET" and path.startswith("/module_entries?id=eq."):
            return [entry] if entry else []
        if method == "POST" and path.startswith("/module_entries"):
            return [{"id": "e-new", **body}]
        if method == "PATCH" and path.startswith("/module_entries"):
            return [{"id": (entry or {}).get("id"), **body}]
        return []
    monkeypatch.setattr(cos, "_sb", fake_sb)
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: [{"id": DANA}] if path.startswith("/contacts?business_id=eq." + BIZ["id"]) and DANA in path else [])
    return calls


def test_chief_adds_an_event_with_its_volunteer_roles_to_the_events_room(monkeypatch):
    calls = _fake(monkeypatch)
    res = asyncio.run(cos.handle_create_module_entry(None, BIZ, {
        "module_id": "Services & Events", "data": {"title": "Fall Festival", "date": "2026-11-07"},
        "roles": [{"label": "Parking", "needed": 3}, {"label": "Face painting", "needed": 2}],
        "volunteers": [{"name": "Dana Johnson", "role": "Parking", "contact_id": DANA},
                       {"name": "Someone Else", "role": "Parking", "contact_id": STRANGER}]}))
    assert not cos._action_failed(res), res
    assert res["result"] == "entry added" and res["label"] == (
        "Services & Events: Fall Festival (2 volunteer roles: Parking 3, Face painting 2; 2 people added)")
    assert "Services & Events" in res["where"] and res["entry_id"] == "e-new"
    assert res["nav"] == {"tab": "operate", "sub": f"module:{ROOM['id']}"}
    [posted] = [b for m, p, b in calls if m == "POST" and p.startswith("/module_entries")]
    assert posted["data"]["_roles"] == [{"id": "parking", "label": "Parking", "needed": 3},
                                        {"id": "face-painting", "label": "Face painting", "needed": 2}]
    assert posted["data"]["signups"] == [
        {"name": "Dana Johnson", "status": "yes", "contact_id": DANA, "role": "parking"},
        {"name": "Someone Else", "status": "yes", "role": "parking"}], "another church's person keeps only the name"
    for word in ("build", "GitHub", "Claude", "module"):
        assert word not in res["label"] and word not in res["where"], word


def test_the_reply_names_the_events_page_only_when_people_can_sign_up_there(monkeypatch):
    """Love City's events page is on (settings.events_public.enabled), and it shows each event's open
    roles with a sign-up form: Chief says so, with the page's real address, and only then."""
    import business_sites_helpers
    import church_event_signups
    import events_rsvp_router as er
    from datetime import date, timedelta
    site = {"slug": "love-city-church"}
    url = er.events_url_for_site(site)
    monkeypatch.setattr(business_sites_helpers, "get_business_site", lambda biz_id: site if biz_id == BIZ["id"] else None)
    soon = (date.today() + timedelta(days=10)).isoformat()
    on = {**BIZ, "settings": {"events_public": {"enabled": True}}}
    room = {**ROOM, "is_active": True}
    _fake(monkeypatch, module=room)

    def make(biz, **data):
        return asyncio.run(cos.handle_create_module_entry(None, biz, {
            "module_id": room["id"], "data": {"title": "Fall Festival", "date": soon, **data},
            "roles": [{"label": "Parking", "needed": 2}]}))
    res = make(on)
    assert res["events_page"] == url and url.endswith("/events")
    assert f"sign themselves up for the open spots on the church's events page, {url}" in res["where"]
    assert url in res["note_for_chief"] and res["result"] and res["label"]
    # The page off, a private event, an undated one, or one too far out for the page: no page named.
    for biz, data in ((BIZ, {}), (on, {"_visibility": "private"}), (on, {"date": ""}),
                      (on, {"date": (date.today() + timedelta(days=200)).isoformat()})):
        res = make(biz, **data)
        assert "events_page" not in res and "events page" not in res["where"], data
        assert "Don't send people to a public page" in res["note_for_chief"]
    # Every spot taken: nothing open to sign up for.
    res = asyncio.run(cos.handle_create_module_entry(None, on, {
        "module_id": room["id"], "data": {"title": "Fall Festival", "date": soon},
        "roles": [{"label": "Parking", "needed": 1}], "volunteers": [{"name": "Dana", "role": "Parking"}]}))
    assert "events_page" not in res
    # An event already there that takes paid sign-ups: its own form, not the free one.
    entry = {"id": "e1", "module_id": room["id"], "data": {"title": "Retreat", "date": soon}}
    _fake(monkeypatch, entry=entry, module=room)
    paid = {"now": True}
    monkeypatch.setattr(church_event_signups, "blocks_free_rsvp", lambda biz_id, eid: paid["now"])
    upd = lambda: asyncio.run(cos.handle_update_module_entry(None, on, {"entry_id": "e1", "data": {}, "roles": ["Cooks"]}))
    assert "events_page" not in upd()
    paid["now"] = False
    assert upd()["events_page"] == url


def test_the_manual_points_sunday_places_at_who_serves_when():
    import chief_lean_brief as lean
    import chief_turn_eval as te
    full = lean.segments(cos._build_system_prompt(te._fixture_context(BIZ), False))["universal"]
    assert "Sunday's own places (greeters, ushers, a Sunday team) are Who serves when" in full
    assert "never at a text to the whole church (the weekly text is the Office's)" in full
    assert "the events page only when the result names it" in full


def test_any_other_module_is_written_as_before(monkeypatch):
    plain = {"id": "m1", "name": "Flyer Orders", "agent_config": {}}
    calls = _fake(monkeypatch, module=plain)
    res = asyncio.run(cos.handle_create_module_entry(None, BIZ, {
        "module_id": "m1", "data": {"title": "Jessica flyer", "roles": ["x"]}, "roles": ["Parking"]}))
    assert res == {"type": "create_module_entry", "result": "entry added", "label": "Flyer Orders: Jessica flyer",
                   "nav": {"tab": "build"}}
    [posted] = [b for m, p, b in calls if m == "POST"]
    assert posted["data"] == {"title": "Jessica flyer", "roles": ["x"]}


def test_chief_adds_roles_to_an_event_already_there(monkeypatch):
    entry = {"id": "e1", "module_id": ROOM["id"], "data": {
        "title": "Fall Festival", "_roles": [{"id": "parking", "label": "Parking", "needed": 2}],
        "signups": [{"name": "Dana Johnson", "status": "yes", "role": "parking"}]}}
    calls = _fake(monkeypatch, entry=entry)
    res = asyncio.run(cos.handle_update_module_entry(None, BIZ, {
        "entry_id": "e1", "data": {}, "roles": [{"label": "Parking", "needed": 4}, {"label": "Games"}]}))
    assert not cos._action_failed(res), res
    assert res["result"] == "updated" and res["entry_id"] == "e1"
    assert res["label"] == "Services & Events: Fall Festival (2 volunteer roles: Parking 4, Games 1)"
    [patched] = [b for m, p, b in calls if m == "PATCH"]
    assert patched["data"]["_roles"] == [{"id": "parking", "label": "Parking", "needed": 4},
                                         {"id": "games", "label": "Games", "needed": 1}]
    assert patched["data"]["signups"] == entry["data"]["signups"], "Dana stays on Parking"


def test_an_update_with_nothing_to_change_is_refused_as_before(monkeypatch):
    plain = {"id": "m1", "name": "Flyer Orders", "agent_config": {}}
    _fake(monkeypatch, entry={"id": "e1", "module_id": "m1", "data": {"title": "x"}}, module=plain)
    for action in ({"entry_id": "e1", "data": {}}, {"entry_id": "e1", "data": {}, "roles": ["Parking"]}):
        res = asyncio.run(cos.handle_update_module_entry(None, BIZ, action))
        assert cos._action_failed(res) and res["label"], action
    res = asyncio.run(cos.handle_update_module_entry(None, BIZ, {"entry_id": "e1", "data": {"status": "done"}}))
    assert res["label"] == "📦 Solution entry updated" and res["result"] == "updated"


def test_the_write_tools_carry_roles_and_volunteers():
    import mcp_server
    for verb in ("create_module_entry", "update_module_entry"):
        _, schema = mcp_server.WRITE_TOOL_SCHEMAS[verb]
        assert {"roles", "volunteers"} <= set(schema["properties"]), verb
        assert schema["properties"]["roles"]["items"]["required"] == ["label"]


# ─── A lane's new list for an event's volunteers ──────────────────────

def test_the_refusal_says_where_an_events_volunteers_go(monkeypatch):
    import events_rsvp_router
    rooms = {"now": [{"id": ROOM["id"], "name": "Services & Events"}]}
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda biz: rooms["now"])
    ask = {"intake_excerpt": "make an event volunteer list for the Fall Festival"}
    hint = ca.room_hint(BIZ["id"], "propose_module_from_intake", ask, LAQUESHA)
    assert hint.startswith("A new list is for the church's owner or an admin to make, but this one has a place "
                           "already: Services & Events holds each event")
    assert "Chief can add the event there now" in hint
    assert ca.room_hint(BIZ["id"], "ensure_module", {"module_name": "Volunteer Roster"}, LAQUESHA)
    # Not about an event's people, not a new list, no lane, no events room: the refusal stands.
    assert ca.room_hint(BIZ["id"], "propose_module_from_intake", {"intake_excerpt": "track prayer requests"},
                        LAQUESHA) is None
    assert ca.room_hint(BIZ["id"], "remember", ask, LAQUESHA) is None
    assert ca.room_hint(BIZ["id"], "propose_module_from_intake", ask, None) is None
    rooms["now"] = []
    assert ca.room_hint(BIZ["id"], "propose_module_from_intake", ask, LAQUESHA) is None

    def boom(biz):
        raise RuntimeError("down")
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", boom)
    assert ca.room_hint(BIZ["id"], "propose_module_from_intake", ask, LAQUESHA) is None


def test_laquesha_is_told_where_her_list_goes_and_nothing_is_built(monkeypatch):
    import events_rsvp_router
    import policy_engine
    from types import SimpleNamespace
    monkeypatch.setattr(policy_engine, "evaluate", lambda *a, **k: SimpleNamespace(allowed=True, rule="owner"))
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for",
                        lambda biz: [{"id": ROOM["id"], "name": "Services & Events"}])
    ran = []

    async def built(client, biz, action):
        ran.append(action["type"])
        return {"type": action["type"], "result": "proposed", "label": "x"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "propose_module_from_intake", built)
    token = ca.TURN.set(LAQUESHA)
    try:
        out = asyncio.run(cos._execute_actions(None, BIZ, [
            {"type": "propose_module_from_intake", "intake_excerpt": "event volunteer list"},
            {"type": "propose_module_from_intake", "intake_excerpt": "a list of prayer requests"}],
            user_id="00000000-0000-4000-8000-000000000007"))
    finally:
        ca.TURN.reset(token)
    assert ran == []
    assert out[0]["failed"] and out[0]["label"] and "Services & Events holds each event" in out[0]["result"]
    assert out[1]["failed"] and out[1]["result"].startswith("That's for the church's owner or an admin")
    for word in ("GitHub", "Claude Code", "build request"):
        assert word not in out[0]["result"], word


# ─── The manual ───────────────────────────────────────────────────────

def test_the_manual_routes_an_events_volunteers_to_the_room(monkeypatch):
    import chief_lean_brief as lean
    import chief_turn_eval as te
    monkeypatch.delenv("CHIEF_BRIEF", raising=False)
    full = lean.segments(cos._build_system_prompt(te._fixture_context(BIZ), False))["universal"]
    route = "0b. AN EVENT'S VOLUNTEERS OR SIGN-UPS"
    volunteers = "— VOLUNTEERS FOR AN OCCASION (a volunteer list, the roles it needs, who serves)"
    assert route in full and volunteers in full
    assert '"roles":[{"label":"Greeters","needed":4}' in full, "the example renders as JSON"
    short = lean.lean_manual(full)
    assert route in short and volunteers in short, "the short brief keeps both lines"
