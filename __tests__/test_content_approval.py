"""The door that satisfies the unattended gate.

post_approval.py refuses to publish anything on a schedule that a human
did not sign off. These cover the other half — that signing off is
possible, that it records the right things, and that the ways it could
be subverted are closed.

The service-role reads and writes are faked. What is under test is the
decision-making, not Supabase.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import content_approval
import post_approval
from auth_supabase import AuthedUser, require_user

BIZ = "biz-1"
OWNER = "user-owner"
PAGE = {"page_id": "PAGE_A", "page_name": "The Solutionist System", "ig_user_id": None}
PAGE_IG = {"page_id": "PAGE_B", "page_name": "With Instagram", "ig_user_id": "IG_1"}


class Store:
    """Stands in for the business row and the schedule table."""

    def __init__(self, posts):
        self.settings = {"content_calendar": {"planned_posts": posts},
                         "website_content": {"news": ["keep me"]}}
        self.scheduled = []
        self.patches = []


@pytest.fixture
def store(monkeypatch):
    s = Store([{"id": "post-1", "title": "A headline",
                "body": "Some words.", "image_url": None}])

    def fake_get(path):
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": OWNER, "settings": s.settings}]
        if path.startswith("/social_accounts"):
            return [PAGE, PAGE_IG]
        return []

    def fake_patch(path, body):
        s.patches.append(body)
        s.settings = body["settings"]
        return {}

    def fake_post(path, row):
        s.scheduled.append(row)
        return {"id": "sched-1"}

    monkeypatch.setattr(content_approval.sb_clients, "sb_get_as_service", fake_get)
    monkeypatch.setattr(content_approval.sb_clients, "sb_patch_as_service", fake_patch)
    monkeypatch.setattr(content_approval.sb_clients, "sb_post_as_service", fake_post)
    return s


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(content_approval.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=OWNER, email="k@example.com", role="authenticated")
    return TestClient(app)


def _soon():
    return (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


# ─── Approving ───────────────────────────────────────────────────────

def test_approving_records_the_words_the_page_and_the_person(client, store):
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_A"})
    assert r.status_code == 200, r.text
    ap = store.settings["content_calendar"]["planned_posts"][0][post_approval.APPROVAL_KEY]
    assert ap["by"] == OWNER
    assert ap["page_id"] == "PAGE_A"
    assert ap["fingerprint"]
    assert ap["to_instagram"] is False


def test_approving_does_not_clobber_its_neighbours(client, store):
    """content_calendar shares the settings blob with website_content —
    the news feed lives there. A write built from a stale copy would
    take the site's posts down as a side effect of approving one."""
    client.post(f"/content/{BIZ}/posts/post-1/approve", json={"page_id": "PAGE_A"})
    assert store.settings["website_content"]["news"] == ["keep me"]


def test_approving_and_scheduling_is_one_call(client, store):
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_A", "run_at": _soon()})
    assert r.status_code == 200
    assert len(store.scheduled) == 1
    action = store.scheduled[0]["action"]
    assert action["type"] == "publish_post"
    assert action["post_id"] == "post-1"
    # The schedule names the Page the handler resolves by, while the
    # approval holds the id the gate compares — so renaming a Page
    # cannot quietly redirect an approved post.
    assert action["page_name"] == PAGE["page_name"]


def test_approving_alone_schedules_nothing(client, store):
    client.post(f"/content/{BIZ}/posts/post-1/approve", json={"page_id": "PAGE_A"})
    assert store.scheduled == []


# ─── The ways it could be subverted ──────────────────────────────────

def test_a_stranger_cannot_approve(client, store, monkeypatch):
    app = FastAPI()
    app.include_router(content_approval.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id="someone-else", email="x@y.z", role="authenticated")
    other = TestClient(app)
    r = other.post(f"/content/{BIZ}/posts/post-1/approve", json={"page_id": "PAGE_A"})
    assert r.status_code == 403


def test_cannot_approve_for_a_page_that_is_not_connected(client):
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_NOT_OURS"})
    assert r.status_code == 400
    assert "not connected" in r.text


def test_cannot_approve_instagram_on_a_page_without_one(client):
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_A", "to_instagram": True})
    assert r.status_code == 400
    assert "no linked Instagram" in r.text


def test_cannot_schedule_into_the_past(client):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_A", "run_at": past})
    assert r.status_code == 400


def test_cannot_schedule_beyond_the_horizon(client):
    far = (datetime.now(timezone.utc) + timedelta(days=200)).isoformat()
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_A", "run_at": far})
    assert r.status_code == 400
    assert "days out" in r.text


def test_a_recurrence_without_a_start_is_refused(client):
    r = client.post(f"/content/{BIZ}/posts/post-1/approve",
                    json={"page_id": "PAGE_A", "recurrence": "weekly"})
    assert r.status_code == 400


# ─── Pending, and withdrawal ─────────────────────────────────────────

def test_pending_lists_what_needs_a_human(client):
    r = client.get(f"/content/{BIZ}/posts/pending")
    assert r.json()["count"] == 1
    assert r.json()["pending"][0]["reason"] == "not approved yet"


def test_an_edited_post_returns_to_pending(client, store):
    """The gate would catch this at publish time anyway — but catching
    it at 9am on a Tuesday tells nobody. It surfaces here instead."""
    client.post(f"/content/{BIZ}/posts/post-1/approve", json={"page_id": "PAGE_A"})
    assert client.get(f"/content/{BIZ}/posts/pending").json()["count"] == 0
    store.settings["content_calendar"]["planned_posts"][0]["body"] = "Rewritten."
    body = client.get(f"/content/{BIZ}/posts/pending").json()
    assert body["count"] == 1
    assert body["pending"][0]["reason"] == "edited since you approved it"


def test_withdrawing_an_approval_disarms_a_queued_run(client, store):
    """The gate reads the POST, not the schedule, so withdrawal takes
    effect immediately — there is no window where a cancelled approval
    still fires."""
    client.post(f"/content/{BIZ}/posts/post-1/approve",
                json={"page_id": "PAGE_A", "run_at": _soon()})
    client.post(f"/content/{BIZ}/posts/post-1/unapprove")
    post = store.settings["content_calendar"]["planned_posts"][0]
    assert post_approval.APPROVAL_KEY not in post
    assert post_approval.refusal(post, page_id="PAGE_A", to_instagram=False)
