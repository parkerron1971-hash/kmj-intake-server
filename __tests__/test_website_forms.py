"""Public website forms: durable receipt, full answers, and private prayer."""
import copy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import brand_engine
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
        return copy.deepcopy(state.existing)
    def post(path, payload, **kw):
        state.posts.append((path, copy.deepcopy(payload)))
        return state.post_result
    def patch(path, payload):
        state.patches.append((path, copy.deepcopy(payload)))
        return state.patch_result
    class MailClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kw):
            assert state.posts or state.patches, "Notification before durable storage"
            state.mail.append(kw["json"])
            if state.mail_error:
                raise httpx.ConnectError("offline")
            return SimpleNamespace(status_code=state.mail_status)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
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
    assert row["source"] == "website connect card"
    assert row["phone"] == "+15551234567"
    assert row["metadata"]["website_form_messages"][0]["fields"] == fields
    assert row["metadata"]["website_connect_card"]["heard_from"] == fields["heard_from"]
    assert env.mail[0]["to"] == ["pastor@church.org"]
    assert not env.events and not env.scores


def test_repeat_card_preserves_history_and_existing_contact_state(env):
    history = [{"message": str(n)} for n in range(12)]
    env.existing = [{"id": "person", "name": "Dana Rivers", "phone": "+15550000000",
                     "updated_at": "2026-10-13T12:00:00Z",
                     "metadata": {"office_note": "Keep", "website_form_messages": history}}]
    assert submit(env, form="connect-card", fields={"notes": "New"}).json()["ok"] is True
    assert not env.posts
    path, patch = env.patches[0]
    assert "business_id=eq.church-1" in path and "updated_at=eq." in path
    assert patch["metadata"]["website_form_messages"][:-1] == history
    assert patch["metadata"]["office_note"] == "Keep"
    assert "status" not in patch and "phone" not in patch


@pytest.mark.parametrize("kind", ["prayer_request", "prayer-request"])
def test_prayer_is_private_even_when_followup_and_sms_requested(env, kind):
    text = "Private prayer " + "p" * 3985
    response = submit(env, form=kind, fields={"request": text, "follow_up": True},
                      message="", sms_consent=True, phone="5551234567")
    assert response.json()["ok"] is True
    assert len(env.posts) == 1 and env.posts[0][0] == "/ministry_care_requests"
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
    assert response.json()["error"] and not env.mail and not env.scores


def test_failed_update_does_not_acknowledge_an_existing_contact(env):
    env.existing = [{"id": "person", "name": "Dana Rivers", "metadata": {}}]
    env.patch_result = None
    response = submit(env)
    assert response.status_code == 503 and response.json()["ok"] is False
    assert not env.mail


def test_lookup_failure_does_not_create_duplicate(env, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: None)
    assert submit(env).status_code == 503
    assert not env.posts and not env.mail


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
    ({"form": "connect_card", "fields": {"secret": "text"}}, "Unknown field"),
])
def test_limits_reject_without_saving_or_truncating(env, changes, field):
    response = submit(env, **changes)
    assert response.status_code == 400 and response.json()["ok"] is False
    assert field in response.json()["error"]
    assert not env.posts and not env.patches and not env.mail


def test_full_5000_character_message_is_stored(env):
    text = "m" * 5000
    assert submit(env, message=text).json()["ok"] is True
    assert env.posts[0][1]["metadata"]["website_form_messages"][0]["message"] == text


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


def test_repeated_write_conflicts_fail_without_email(env):
    env.existing = [{"id": "person", "name": "Dana Rivers", "updated_at": "before", "metadata": {}}]
    env.patch_result = []
    assert submit(env).status_code == 503
    assert len(env.patches) == 3 and not env.mail
