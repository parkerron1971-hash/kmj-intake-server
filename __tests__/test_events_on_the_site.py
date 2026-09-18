"""Chief can put an event on the website end to end, and the form link works.

2026-09-18, Kevin: "can you see if the link that chief gave me actually
works" — https://kmj-creative-solutions.mysolutionist.app/public/widget/form/<id>
was a 404 on the site AND on the API host. The path existed only inside
`embed_url` strings. And: "make sure chief has the ability to create an
event page for the website and a button or a place on the site that shows
upcoming events". The /events RSVP page existed, gated on an Events
(event_roster) module + an operator toggle; Chief could create neither.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chief_of_staff as cos
import chief_form_actions as forms
import chief_offering_actions as offerings
import form_page_renderer

_BIZ = {"id": "biz-1", "owner_id": "user-1", "name": "KMJ Creative Solutions",
        "type": "coach", "settings": {"brand_kit": {"accent": "#123456"}}}
_FORM = {"id": "dd62e60e-1cfe-4572-b39c-e6def2bfe0bf", "business_id": "biz-1",
         "name": "Embrace the Shift Workshop Registration", "form_type": "event",
         "fields": [
             {"name": "name", "type": "text", "label": "Full Name", "required": True},
             {"name": "email", "type": "email", "label": "Email", "required": True},
             {"name": "phone", "type": "phone", "label": "Phone"},
             {"name": "how_many_seats", "type": "number", "label": "How many seats?"},
             {"name": "heard", "type": "select", "label": "How did you hear?", "options": ["Friend", "Flyer"]},
             {"name": "agree", "type": "checkbox", "label": "Keep me posted"},
             {"name": "notes", "type": "textarea", "label": "Anything else?"}],
         "settings": {"confirmation_message": "You're registered. See you there!"}}


# ── the form page ─────────────────────────────────────────────────────

def test_the_form_page_renders_every_field_and_posts_to_intake():
    html = form_page_renderer.render_form_page(
        _BIZ, _FORM, submit_url="https://api.example/intake/submit",
        canonical_url="https://kmj.mysolutionist.app/public/widget/form/" + _FORM["id"])
    assert "<!DOCTYPE html>" in html and "Embrace the Shift Workshop Registration" in html
    for name in ("name", "email", "phone", "how_many_seats", "heard", "agree", "notes"):
        assert f'name="{name}"' in html, name
    assert 'type="email"' in html and 'type="tel"' in html and 'type="number"' in html
    assert "<textarea" in html and "<select" in html and 'type="checkbox"' in html
    assert html.count(" required") >= 2
    assert '<option value="Friend">' in html
    assert "You&#x27;re registered. See you there!" in html or "You're registered" in html
    assert "https://api.example/intake/submit" in html
    assert json.dumps({"form_id": _FORM["id"], "business_id": "biz-1"}) in html
    assert f'name="{form_page_renderer.HONEYPOT_NAME}"' in html
    assert "--accent: #123456" in html
    assert "KMJ Creative Solutions" in html


def test_the_form_page_escapes_what_a_practitioner_typed():
    form = {**_FORM, "name": "<script>alert(1)</script> Registration",
            "fields": [{"name": "x", "type": "text", "label": "Say \"hi\" <b>"}]}
    html = form_page_renderer.render_form_page(_BIZ, form, submit_url="https://a/x", canonical_url="https://a/y")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html and "&lt;b&gt;" in html


def test_the_form_link_chief_hands_out_is_absolute_on_the_site_domain(monkeypatch):
    monkeypatch.setattr(forms.sb_clients, "sb_get_as_service",
                        lambda path: [{"slug": "kmj-creative-solutions", "site_config": {}}])
    url = forms.public_form_url("biz-1", _FORM["id"])
    assert url == "https://kmj-creative-solutions.mysolutionist.app/public/widget/form/" + _FORM["id"]
    monkeypatch.setattr(forms.sb_clients, "sb_get_as_service",
                        lambda path: [{"slug": "kmj", "site_config": {"custom_domain": "kmjcreative.com"}}])
    assert forms.public_form_url("biz-1", "f1") == "https://kmjcreative.com/public/widget/form/f1"
    monkeypatch.setattr(forms.sb_clients, "sb_get_as_service", lambda path: [])
    assert forms.public_form_url("biz-1", "f1").startswith("https://") and "/public/widget/form/f1" in forms.public_form_url("biz-1", "f1")


def test_creating_a_form_reports_its_page_link(monkeypatch):
    monkeypatch.setattr(forms.sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None: [{"id": "form-9", **body}])
    monkeypatch.setattr(forms.sb_clients, "sb_get_as_service",
                        lambda path: [{"slug": "kmj-creative-solutions", "site_config": {}}])
    res = asyncio.run(forms.handle_create_client_form(None, _BIZ, {
        "name": "Workshop Registration", "form_type": "event",
        "fields": [{"label": "Your Name", "type": "text", "required": True}]}))
    assert not res.get("failed"), res
    link = "https://kmj-creative-solutions.mysolutionist.app/public/widget/form/form-9"
    assert res["url"] == link and res["embed_url"] == link
    assert link in res["result"] and link in res["label"]


def test_the_form_page_routes_exist_on_both_hosts():
    import intake_endpoint
    import public_site
    paths = {getattr(r, "path", "") for r in intake_endpoint.router.routes}
    assert "/public/widget/form/{form_id}" in paths
    src = (ROOT / "public_site.py").read_text(encoding="utf-8")
    assert src.count("_serve_form_page(client, biz_id, slug") >= 2   # subdomain + custom domain
    assert public_site._FORM_PAGE_PREFIX == "/public/widget/form/"


# ── the events module, created by Chief ───────────────────────────────

def _sb_recorder(routes):
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        for (m, prefix), resp in routes.items():
            if method == m and path.startswith(prefix):
                return resp(body) if callable(resp) else resp
        return []

    return fake_sb, calls


def test_ensure_module_creates_an_events_roster_the_public_page_can_read(monkeypatch):
    fake_sb, calls = _sb_recorder({
        ("GET", "/custom_modules?business_id=eq.biz-1&name=eq."): [],
        ("POST", "/custom_modules"): lambda body: [{"id": "m-ev", **body}],
    })
    monkeypatch.setattr(cos, "_sb", fake_sb)
    res = asyncio.run(cos.handle_ensure_module(None, _BIZ, {
        "module_name": "Events", "archetype": "event_roster", "occasion_noun": "Workshop"}))
    assert not cos._action_failed(res), res
    assert res["result"] == "created" and res["module_id"] == "m-ev"
    posted = [b for m, p, b in calls if m == "POST"][0]
    assert posted["archetype"] == "event_roster"
    from events_rsvp_router import resolve_fields
    f = resolve_fields(posted["archetype_params"])
    names = {x["name"] for x in posted["schema"]["fields"]}
    assert {f["title_field"], f["date_field"], f["location_field"], f["capacity_field"]} <= names
    assert f["occasion_noun"] == "Workshop"
    assert posted["is_active"] is True


def test_ensure_module_refuses_an_archetype_it_cannot_shape(monkeypatch):
    fake_sb, _ = _sb_recorder({})
    monkeypatch.setattr(cos, "_sb", fake_sb)
    res = asyncio.run(cos.handle_ensure_module(None, _BIZ, {"module_name": "Jobs", "archetype": "work_pipeline"}))
    assert cos._action_failed(res) and "event_roster" in res["result"]


def test_a_module_without_an_archetype_is_created_exactly_as_before(monkeypatch):
    fake_sb, calls = _sb_recorder({
        ("POST", "/custom_modules"): lambda body: [{"id": "m-1", **body}],
    })
    monkeypatch.setattr(cos, "_sb", fake_sb)
    res = asyncio.run(cos.handle_ensure_module(None, _BIZ, {"module_name": "Blog"}))
    assert res["result"] == "created"
    posted = [b for m, p, b in calls if m == "POST"][0]
    assert "archetype" not in posted and posted["icon"] == "📝"


# ── the events page, switched on by Chief ─────────────────────────────

def test_set_site_capability_events_needs_an_events_module_first(monkeypatch):
    import events_rsvp_router
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda biz_id: [])
    fake_sb, calls = _sb_recorder({})
    monkeypatch.setattr(offerings, "_sb", fake_sb)
    res = asyncio.run(offerings.handle_set_site_capability(None, dict(_BIZ), {"capability": "events", "on": True}))
    assert res.get("failed") and "Events module" in res["result"]
    assert not any(m == "PATCH" for m, _, _ in calls)


def test_set_site_capability_events_switches_the_page_on_and_names_the_url(monkeypatch):
    import events_rsvp_router
    import discovery
    import offering_profiles
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for",
                        lambda biz_id: [{"id": "m-ev", "name": "Events", "archetype_params": {}}])
    monkeypatch.setattr(discovery, "answer", lambda biz_id, patch: {"ok": True})
    monkeypatch.setattr(offering_profiles, "business_state", lambda biz_id: {
        "booking_enabled": False, "booking_url": "", "store_url": "",
        "events_enabled": True, "events_url": "https://kmj-creative-solutions.mysolutionist.app/events"})
    fake_sb, calls = _sb_recorder({("PATCH", "/businesses?id=eq.biz-1"): lambda body: [body]})
    monkeypatch.setattr(offerings, "_sb", fake_sb)
    biz = dict(_BIZ)
    res = asyncio.run(offerings.handle_set_site_capability(None, biz, {"capability": "events", "on": True}))
    assert not res.get("failed"), res
    patched = [b for m, p, b in calls if m == "PATCH"]
    assert patched and patched[0]["settings"]["events_public"]["enabled"] is True
    assert "https://kmj-creative-solutions.mysolutionist.app/events" in res["label"]
    assert "RSVP" in res["label"]


def test_the_builder_lists_the_events_door_and_the_checker_enforces_it(monkeypatch):
    import builder_v2
    import offering_profiles
    state = {"booking_enabled": True, "booking_url": "https://kmj.example/book",
             "store_url": "", "events_enabled": True,
             "events_url": "https://kmj.example/events"}
    monkeypatch.setattr(offering_profiles, "business_state", lambda biz_id: dict(state))
    block = builder_v2.connected_systems_block("biz-1", {})
    assert "EVENTS: ON" in block and "https://kmj.example/events" in block
    assert "Upcoming Events" in block
    # check_connected parses these exact lines: a page without the door fails.
    missing = builder_v2.check_connected("<html><a href='https://kmj.example/book'>Book</a></html>", block)
    assert any("EVENTS" in m and "https://kmj.example/events" in m for m in missing), missing
    ok = builder_v2.check_connected(
        "<html><a href='https://kmj.example/book'>Book</a><a href='https://kmj.example/events'>Events</a></html>", block)
    assert not any("EVENTS" in m for m in ok)
    monkeypatch.setattr(offering_profiles, "business_state",
                        lambda biz_id: {**state, "events_enabled": False, "events_url": ""})
    assert "EVENTS" not in builder_v2.connected_systems_block("biz-1", {})


def test_business_state_carries_the_events_door(monkeypatch):
    import offering_profiles
    import events_rsvp_router
    import sb_clients
    rows = {"/businesses": [{"settings": {"events_public": {"enabled": True}}, "stripe_account_id": None}],
            "/business_sites": [{"slug": "kmj-creative-solutions", "site_config": {}}]}
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: next((v for k, v in rows.items() if path.startswith(k)), []))
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda biz_id: [{"id": "m"}])
    import booking_widget_router
    monkeypatch.setattr(booking_widget_router, "booking_is_live", lambda biz_id, settings: False)
    state = offering_profiles.business_state("biz-1")
    assert state["events_enabled"] is True
    assert state["events_url"] == "https://kmj-creative-solutions.mysolutionist.app/events"


# ── the flyer question ────────────────────────────────────────────────

def test_the_prompt_shows_images_in_progress_and_the_event_moves():
    src = (ROOT / "chief_prompt.py").read_text(encoding="utf-8")
    assert '"archetype":"event_roster"' in src
    assert '"capability":"events"' in src
    assert "never compose one from a path you remember" in src
    cos_src = (ROOT / "chief_of_staff.py").read_text(encoding="utf-8")
    assert "IMAGES IN PROGRESS" in cos_src and "image_artworks?business_id" in cos_src
