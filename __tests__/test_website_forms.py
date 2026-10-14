"""Public website forms: durable receipt, full answers, and private prayer."""
import copy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import brand_engine
import chief_agent
import event_spine
import lead_scoring
import public_site
import sb_clients


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(posts=[], patches=[], mail=[], events=[], scores=[],
                            existing=[], post_result=[{"id": "saved"}],
                            patch_result=[{"id": "saved"}], mail_status=200,
                            mail_error=False, consents=[])
    def get(path):
        if path.startswith("/businesses?"):
            return [{"settings": {"email_domain": {"status": "verified", "domain": "church.org",
                                                       "from_local_part": "pastor"}}}]
        return copy.deepcopy(state.existing) if path.startswith("/contacts?") else []
    def post(path, payload, **kw):
        state.posts.append((path, copy.deepcopy(payload)))
        if path == "/events" and payload["event_type"] == "contact_form_submitted":
            state.events.append(payload)
        return state.post_result
    def patch(path, payload):
        state.patches.append((path, copy.deepcopy(payload)))
        return state.patch_result
    class MailClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kw):
            # Plain legacy forms still notify if the database is unavailable.
            state.mail.append(kw["json"])
            if state.mail_error:
                raise httpx.ConnectError("offline")
            return SimpleNamespace(status_code=state.mail_status)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(chief_agent, "nudge", lambda *a, **kw: None)
    monkeypatch.setattr(event_spine, "emit", lambda *a, **kw: state.events.append((a, kw)))
    monkeypatch.setattr(lead_scoring, "score_in_background", lambda *a, **kw: state.scores.append((a, kw)))
    monkeypatch.setattr(public_site, "_record_website_sms_consent", lambda *a: state.consents.append(a))
    monkeypatch.setattr(public_site, "_check_contact_rate", lambda ip: True)
    monkeypatch.setattr(brand_engine, "get_bundle", lambda b: {"business": {"name": "Church"}, "footer": {"contact_email": "legacy@site.org"}})
    monkeypatch.setattr(brand_engine, "_sb_get", lambda p: [])
    monkeypatch.setattr(public_site.httpx, "AsyncClient", MailClient)
    monkeypatch.setenv("RESEND_API_KEY", "test")
    app = FastAPI()
    app.include_router(public_site.router)
    state.client = TestClient(app)
    return state


def submit(env, **changes):
    body = {"name": "Dana Rivers", "email": "Dana@example.org", "message": "Hello"}
    body.update(changes)
    return env.client.post("/sites/church-1/contact-submit", json=body)


def test_plain_contact_is_backwards_compatible(env):
    response = submit(env)
    assert response.json() == {"ok": True, "notification_sent": True}
    row = env.posts[0][1]
    assert row["status"] == "lead" and row["source"] == "website_contact_form"
    assert row["email"] == "dana@example.org"
    assert env.events and env.scores
    assert env.mail[0]["to"] == ["legacy@site.org"]


def test_connect_card_keeps_every_answer_and_verified_recipient(env):
    fields = {"first_name": "Dana", "last_name": "Rivers", "visits": "A few times",
              "heard_from": "A Love City member", "interests": ["Next Step", "Leaderschool"],
              "notes": "n" * 2500}
    response = submit(env, form="connect_card", phone="(555) 123-4567", fields=fields,
                      message="", to="attacker@example.org", recipient="attacker@example.org")
    assert response.json()["ok"] is True
    path, row = env.posts[0]
    assert path == "/contacts" and row["business_id"] == "church-1"
    assert row["source"] == "website_contact_form"
    assert row["phone"] == "+15551234567"
    assert row["metadata"]["website_form_messages"][0]["fields"] == fields
    assert row["metadata"]["website_connect_card"]["heard_from"] == fields["heard_from"]
    assert env.mail[0]["to"] == ["pastor@church.org"]
    note_path, note = env.posts[1]
    assert note_path == "/events" and note["event_type"] == "contact_note"
    assert note["business_id"] == "church-1" and note["contact_id"] == "saved"
    for answer in (fields["notes"], fields["heard_from"], "Next Step", "Leaderschool"):
        assert answer in note["data"]["note"]
    assert note["data"]["fields"] == fields
    assert not env.events and not env.scores


def test_repeat_card_bounds_history_and_preserves_existing_contact_state(env):
    history = [{"message": str(n)} for n in range(12)]
    env.existing = [{"id": "person", "name": "Dana Rivers", "phone": "+15550000000",
                     "updated_at": "2026-10-13T12:00:00Z",
                     "metadata": {"office_note": "Keep", "website_form_messages": history}}]
    assert submit(env, form="connect-card", fields={"notes": "New"}).json()["ok"] is True
    assert [p[0] for p in env.posts] == ["/events", "/chief_notifications"]
    path, patch = env.patches[0]
    assert "business_id=eq.church-1" in path and "updated_at=eq." in path
    assert patch["metadata"]["website_form_messages"][:-1] == history[-9:]
    assert len(patch["metadata"]["website_form_messages"]) == 10
    assert patch["metadata"]["office_note"] == "Keep"
    assert "status" not in patch and "phone" not in patch


@pytest.mark.parametrize("kind", ["prayer_request", "prayer-request"])
def test_prayer_is_private_even_when_followup_and_sms_requested(env, kind):
    text = "Private prayer " + "p" * 3985
    response = submit(env, form=kind, fields={"request": text, "follow_up": True},
                      message="", sms_consent=True, phone="5551234567")
    assert response.json()["ok"] is True
    assert [p[0] for p in env.posts] == ["/ministry_care_requests", "/chief_notifications"]
    row = env.posts[0][1]
    assert row["business_id"] == "church-1" and row["status"] == "new"
    assert row["submission"]["prayer_request"] == text
    assert row["submission"]["confidential"] == "yes"
    assert row["submission"]["follow_up"] is True
    assert not env.events and not env.scores and not env.consents and not env.patches
    assert len(env.mail) == 1 and env.mail[0]["to"] == ["pastor@church.org"]


def test_legacy_prayer_message_also_stays_private(env):
    assert submit(env, form="prayer-request", message="Pray for my family").json()["ok"] is True
    assert env.posts[0][0] == "/ministry_care_requests"


@pytest.mark.parametrize("kind", ["", "connect_card", "prayer_request"])
@pytest.mark.parametrize("result", [None, []])
def test_no_ok_or_notification_when_insert_fails(env, kind, result):
    env.post_result = result
    response = submit(env, form=kind)
    assert response.status_code == 503 and response.json()["ok"] is False
    assert response.json()["error"] and not env.scores
    assert bool(env.mail) is (not kind)


def test_failed_update_does_not_acknowledge_an_existing_contact(env):
    env.existing = [{"id": "person", "name": "Dana Rivers", "metadata": {}}]
    env.patch_result = None
    response = submit(env)
    assert response.status_code == 503 and response.json()["ok"] is False
    assert len(env.mail) == 1


def test_lookup_failure_does_not_create_duplicate(env, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: None)
    assert submit(env).status_code == 503
    assert not env.posts and len(env.mail) == 1


@pytest.mark.parametrize("kind", ["", "connect_card", "prayer_request"])
@pytest.mark.parametrize("mode", ["http", "network", "configuration"])
def test_saved_submission_succeeds_when_notification_fails(env, monkeypatch, kind, mode):
    if mode == "http": env.mail_status = 503
    if mode == "network": env.mail_error = True
    if mode == "configuration": monkeypatch.delenv("RESEND_API_KEY")
    response = submit(env, form=kind)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "notification_sent": False}


def test_church_without_verified_sender_never_falls_back(env, monkeypatch):
    monkeypatch.setattr(public_site, "_business_public_email", lambda s: "")
    monkeypatch.setenv("DEFAULT_CONTACT_FALLBACK_EMAIL", "platform@example.org")
    assert submit(env, form="prayer_request").json() == {"ok": True, "notification_sent": False}
    assert not env.mail


@pytest.mark.parametrize("changes,field", [
    ({"name": "n" * 201}, "name"), ({"email": "e" * 201}, "email"),
    ({"phone": "1" * 41}, "phone"), ({"message": "m" * 5001}, "message"),
    ({"form": "connect_card", "fields": {"notes": "n" * 2501}}, "notes"),
    ({"form": "connect_card", "fields": {"heard_from": "h" * 201}}, "heard_from"),
    ({"form": "connect_card", "fields": {"interests": ["x"] * 21}}, "interests"),
    ({"form": "connect_card", "fields": {"interests": ["x" * 121]}}, "interest"),
    ({"form": "prayer_request", "fields": {"request": "p" * 4001}}, "request"),
    ({"form": "prayer_request", "fields": {"request": ""}}, "prayer request"),
    ({"fields": []}, "fields"), ({"name": ["Dana"]}, "name"),
    ({"form": "connect_card", "fields": {"secret": "text"}}, "Unknown structured field"),
])
def test_limits_reject_without_saving_or_truncating(env, changes, field):
    response = submit(env, **dict({"form": "connect_card"}, **changes))
    assert response.status_code == 400 and response.json()["ok"] is False
    assert field in response.json()["error"]
    assert not env.posts and not env.patches and not env.mail


def test_full_5000_character_message_is_stored(env):
    text = "m" * 5000
    assert submit(env, message=text).json()["ok"] is True
    assert env.posts[1][1]["data"]["message"] == text
    assert len(env.posts[0][1]["metadata"]["website_form_messages"][0]["message"]) == 1000


def test_rate_limit_has_honest_json_and_no_writes(env, monkeypatch):
    monkeypatch.setattr(public_site, "_check_contact_rate", lambda ip: False)
    response = submit(env)
    assert response.status_code == 429 and response.json()["ok"] is False
    assert not env.posts and not env.mail


def test_optional_scoring_failure_does_not_undo_storage(env, monkeypatch):
    def fail(*a, **kw): raise RuntimeError("unavailable")
    monkeypatch.setattr(lead_scoring, "score_in_background", fail)
    assert submit(env).json()["ok"] is True


def test_concurrent_form_retries_without_losing_either_message(env, monkeypatch):
    env.existing = [{"id": "person", "name": "Dana Rivers", "updated_at": "before",
                     "metadata": {"website_form_messages": [{"message": "Earlier"}]}}]
    def patch(path, payload):
        env.patches.append((path, copy.deepcopy(payload)))
        if len(env.patches) == 1:
            env.existing[0]["updated_at"] = "after"
            env.existing[0]["metadata"]["website_form_messages"].append({"message": "Concurrent"})
            return []
        return [{"id": "person"}]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    assert submit(env, message="Mine").json()["ok"] is True
    assert len(env.patches) == 2
    assert "updated_at=eq.after" in env.patches[1][0]
    assert [m["message"] for m in env.patches[1][1]["metadata"]["website_form_messages"]] == ["Earlier", "Concurrent", "Mine"]


def test_repeated_write_conflicts_still_notify_for_plain_forms(env):
    env.existing = [{"id": "person", "name": "Dana Rivers", "updated_at": "before", "metadata": {}}]
    env.patch_result = []
    assert submit(env).status_code == 503
    assert len(env.patches) == 3 and len(env.mail) == 1


def test_email_and_raw_phone_kept_when_matching_an_existing_person(env):
    env.existing = [{"id": "person", "name": "Dana Rivers", "phone": "+15550000000", "metadata": {}}]
    assert submit(env, phone="555-123-4567 ext 32").json()["ok"] is True
    entry = env.patches[0][1]["metadata"]["website_form_messages"][-1]
    assert entry["name"] == "Dana Rivers"
    assert entry["email"] == "Dana@example.org"
    assert entry["phone"] == "555-123-4567 ext 32"


def test_public_email_override_cannot_redirect_private_prayer(env, monkeypatch):
    monkeypatch.setattr(brand_engine, "_sb_get", lambda p: [{"site_config": {
        "sections": {"contact": {"email": "public@example.org"}}}}])
    assert submit(env, form="prayer_request", to="visitor@example.org").json()["ok"] is True
    assert env.mail[0]["to"] == ["pastor@church.org"]


@pytest.mark.parametrize("kind", ["", "connect_card", "prayer_request"])
def test_no_recipient_still_returns_success_after_storage(env, monkeypatch, kind):
    monkeypatch.setattr(brand_engine, "get_bundle", lambda b: {"business": {"name": "Love City Church"}})
    monkeypatch.setattr(brand_engine, "_sb_get", lambda p: [{"site_config": {}}])
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"settings": {}}] if p.startswith("/businesses?") else [])
    monkeypatch.delenv("DEFAULT_CONTACT_FALLBACK_EMAIL", raising=False)
    fields = {"request": "Please pray for us", "follow_up": True} if kind == "prayer_request" else {"notes": "Please connect with us"}
    args = {"form": kind, "fields": fields} if kind else {}
    response = submit(env, **args)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "notification_sent": False}
    assert len(env.posts) == (3 if kind == "connect_card" else 2) and not env.mail
    path, row = env.posts[0]
    assert row["business_id"] == "church-1"
    if kind == "prayer_request":
        assert path == "/ministry_care_requests"
        assert row["submission"]["prayer_request"] == fields["request"]
    else:
        assert path == "/contacts"
        assert row["metadata"]["website_form_messages"][0]["message"] == "Hello"


def test_saved_prayer_is_readable_only_by_the_church_owner(env, monkeypatch):
    import intake_endpoint
    from fastapi import HTTPException
    monkeypatch.setattr(public_site, "_business_public_email", lambda s: "")
    assert submit(env, form="prayer_request", fields={"request": "A private request"}).json()["ok"] is True
    record = dict(env.posts[0][1], id="request-1")
    def get(path):
        assert "business_id=eq.church-1" in path or "id=eq.church-1" in path
        if path.startswith("/businesses?"):
            return [{"id": "church-1", "owner_id": "church-owner"}]
        assert path.startswith("/ministry_care_requests?")
        return [record]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    result = intake_endpoint.private_care_requests("church-1", SimpleNamespace(id="church-owner"))
    assert result["requests"][0]["submission"]["prayer_request"] == "A private request"
    with pytest.raises(HTTPException) as denied:
        intake_endpoint.private_care_requests("church-1", SimpleNamespace(id="other-owner"))
    assert denied.value.status_code == 403


@pytest.mark.parametrize("result", [None, [], [{}]])
def test_connect_card_requires_a_readable_member_note_before_success(env, monkeypatch, result):
    def post(path, payload, **kw):
        env.posts.append((path, copy.deepcopy(payload)))
        return result if path == "/events" else [{"id": "saved"}]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    response = submit(env, form="connect_card", fields={"notes": "All my answers"})
    assert response.status_code == 503 and response.json()["ok"] is False
    assert [p[0] for p in env.posts] == ["/contacts", "/events"]
    assert not env.mail and not env.scores


@pytest.mark.parametrize("field,value", [
    ("name", "N" * 250), ("email", "e" * 240 + "@example.org"),
    ("phone", "1" * 60), ("message", "A long letter. " * 1500 + "End."),
], ids=["name", "email", "phone", "message"])
def test_plain_over_church_limits_is_saved_whole_and_emailed(env, field, value):
    assert submit(env, **{field: value}).json()["ok"] is True
    event = next(row for path, row in env.posts if path == "/events")
    assert event["data"][field] == value
    assert value in env.mail[0]["html"]
    assert len(env.mail[0]["subject"]) <= 200


def test_plain_hard_cap_is_explicit(env):
    response = submit(env, message="x" * 100001)
    assert response.status_code == 400 and not env.posts and not env.mail


def test_connect_answers_appear_once_in_note_and_email(env):
    answers = "What brings you here?: Meet people\nTell us more: A unique answer"
    assert submit(env, form="connect_card", message=answers,
                  fields={"notes": "A unique answer"}, phone="5551234567").json()["ok"]
    note = next(row for path, row in env.posts if path == "/events")["data"]["note"]
    for text in (note, env.mail[0]["html"]):
        assert text.count("A unique answer") == 1
        assert text.count("5551234567") == 1


@pytest.mark.parametrize("kind", ["connect_card", "prayer_request"])
def test_content_free_alert_even_without_email(env, monkeypatch, kind):
    monkeypatch.delenv("RESEND_API_KEY")
    assert submit(env, form=kind, message="Sensitive secret").json() == {
        "ok": True, "notification_sent": False}
    alert = next(row for path, row in env.posts if path == "/chief_notifications")
    assert alert["business_id"] == "church-1" and alert["status"] == "unread"
    assert alert["action_payload"]["type"] == "navigate"
    assert not any(secret in str(alert) for secret in ("Sensitive secret", "Dana", "example.org"))


def test_prayer_email_does_not_disclose_identity_or_content(env):
    assert submit(env, form="prayer_request", message="Very private text").json()["ok"]
    mail = env.mail[0]
    assert "New prayer request" in mail["subject"]
    assert "https://mysolutionist.app" in mail["html"]
    assert "reply_to" not in mail
    assert not any(secret in str(mail) for secret in ("Very private text", "Dana", "example.org"))


def test_future_prayer_content_option_is_explicit_and_off_by_default(env, monkeypatch):
    import website_forms
    assert website_forms.PRAYER_EMAIL_INCLUDE_CONTENT is False
    monkeypatch.setattr(website_forms, "PRAYER_EMAIL_INCLUDE_CONTENT", True)
    assert submit(env, form="prayer_request", message="Requested full text").json()["ok"]
    assert "Requested full text" in env.mail[0]["html"]


def test_storage_exception_reaches_stdout_with_exception(env, monkeypatch, capsys):
    def broken(path):
        raise RuntimeError("database offline for test")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", broken)
    response = submit(env)
    assert response.status_code == 503 and len(env.mail) == 1
    assert "RuntimeError('database offline for test')" in capsys.readouterr().out


def test_sync_io_does_not_run_on_event_loop(env, monkeypatch):
    import asyncio
    for name in ("sb_get_as_service", "sb_post_as_service", "sb_patch_as_service"):
        original = getattr(sb_clients, name)
        def off_loop(*args, _original=original, **kwargs):
            with pytest.raises(RuntimeError, match="no running event loop"):
                asyncio.get_running_loop()
            return _original(*args, **kwargs)
        monkeypatch.setattr(sb_clients, name, off_loop)
    for kind in ("", "connect_card", "prayer_request"):
        assert submit(env, form=kind).json()["ok"]


@pytest.mark.parametrize("fields", [{"interests": [""]}, {"interests": ["   "]}, {"x" * 10000: "v"}])
def test_invalid_structured_fields_have_bounded_errors(env, fields):
    response = submit(env, form="connect_card", fields=fields)
    assert response.status_code == 400
    assert len(response.json()["error"]) < 100 and not env.posts


@pytest.fixture
def durable_db(env, monkeypatch):
    """Model primary-key ignore-duplicates and scoped reads, including a failed note."""
    from urllib.parse import urlsplit, parse_qs
    tables = {name: {} for name in ("contacts", "events", "ministry_care_requests", "chief_notifications")}
    state = SimpleNamespace(tables=tables, fail_note=False)
    original_get = sb_clients.sb_get_as_service
    def get(path):
        url = urlsplit(path)
        table = url.path.lstrip("/")
        if table not in tables:
            return original_get(path)
        query = parse_qs(url.query)
        rows = list(tables[table].values())
        for key in ("id", "business_id", "email", "phone", "name"):
            if key in query:
                op, value = query[key][0].split(".", 1)
                rows = [r for r in rows if str(r.get(key, "")).lower() == value.lower()]
        return copy.deepcopy(rows)
    def post(path, payload, **kwargs):
        env.posts.append((path, copy.deepcopy(payload)))
        table = path.lstrip("/")
        if table == "events" and state.fail_note:
            state.fail_note = False
            return None
        assert "resolution=ignore-duplicates" in kwargs["prefer"]
        if payload["id"] in tables[table]:
            return []
        tables[table][payload["id"]] = copy.deepcopy(payload)
        return [copy.deepcopy(payload)]
    def patch(path, payload):
        env.patches.append((path, copy.deepcopy(payload)))
        query = parse_qs(urlsplit(path).query)
        row = tables["contacts"][query["id"][0][3:]]
        row.update(copy.deepcopy(payload))
        return [copy.deepcopy(row)]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    return state


def test_failed_note_retry_does_not_duplicate_history(env, durable_db):
    durable_db.fail_note = True
    body = {"form": "connect_card", "fields": {"notes": "Call me"}, "submission_id": "attempt-1"}
    assert submit(env, **body).status_code == 503
    assert submit(env, **body).json()["ok"]
    assert submit(env, **body).json()["ok"]
    assert len(durable_db.tables["contacts"]) == len(durable_db.tables["events"]) == 1
    row = next(iter(durable_db.tables["contacts"].values()))
    assert len(row["metadata"]["website_form_messages"]) == 1
    assert len(durable_db.tables["chief_notifications"]) == 1


@pytest.mark.parametrize("kind", ["connect_card", "prayer_request"])
def test_retries_preserve_reviewed_records_and_alerts(env, durable_db, kind):
    body = {"form": kind, "submission_id": "same-attempt", "message": "Keep me"}
    assert submit(env, **body).json()["ok"]
    table = "ministry_care_requests" if kind == "prayer_request" else "events"
    row = next(iter(durable_db.tables[table].values()))
    if kind == "prayer_request":
        row["status"] = "closed"
    else:
        row["data"]["note"] = "Reviewed by the church"
    alert = next(iter(durable_db.tables["chief_notifications"].values()))
    alert["status"] = "read"
    assert submit(env, **body).json()["ok"]
    assert len(durable_db.tables[table]) == 1 and alert["status"] == "read"
    assert (row["status"] == "closed" if kind == "prayer_request" else row["data"]["note"] == "Reviewed by the church")
    # A deliberate new submission of identical answers gets its own record.
    assert submit(env, **dict(body, submission_id="new-attempt")).json()["ok"]
    assert len(durable_db.tables[table]) == 2


def test_same_client_key_cannot_overwrite_other_answers_or_tenants(env, durable_db):
    body = {"form": "prayer_request", "submission_id": "known-key"}
    assert submit(env, **body).json()["ok"]
    assert submit(env, **body, message="Different text").json()["ok"]
    other = {"name": "Dana Rivers", "email": "Dana@example.org", "message": "Hello", **body}
    assert env.client.post("/sites/other-church/contact-submit", json=other).json()["ok"]
    rows = list(durable_db.tables["ministry_care_requests"].values())
    assert len(rows) == 3 and {r["business_id"] for r in rows} == {"church-1", "other-church"}


def test_plain_full_history_lives_in_events_when_summary_is_evicted(env, durable_db):
    for i in range(12):
        assert submit(env, message=str(i) + "x" * 6000).json()["ok"]
    row = next(iter(durable_db.tables["contacts"].values()))
    assert len(row["metadata"]["website_form_messages"]) == 10
    assert len(durable_db.tables["events"]) == 12
    assert any(r["data"]["message"] == "0" + "x" * 6000 for r in durable_db.tables["events"].values())


def test_alert_failure_does_not_undo_stored_prayer(env, monkeypatch, capsys):
    import website_forms
    def fail(*args):
        raise RuntimeError("alert unavailable")
    monkeypatch.setattr(website_forms, "alert_church", fail)
    assert submit(env, form="prayer_request").json()["ok"]
    assert "alert unavailable" in capsys.readouterr().out


def test_plain_lead_nudge_stays_on_event_loop_after_threaded_storage(env, monkeypatch):
    import asyncio
    calls = []
    def nudge(*args):
        calls.append((args, asyncio.get_running_loop()))
    monkeypatch.setattr(chief_agent, "nudge", nudge)
    assert submit(env).json()["ok"]
    assert len(calls) == 1 and calls[0][0] == ("church-1", "contact_form_submitted")
    assert submit(env, form="connect_card").json()["ok"]
    assert submit(env, form="prayer_request").json()["ok"]
    assert len(calls) == 1
