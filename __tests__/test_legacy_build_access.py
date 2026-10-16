"""
test_legacy_build_access.py — a build for a business needs access to that
business, whichever engine runs it.

THE DEFECT (Codex re-check of #1464, 2026-10-16): POST
/director/build-with-loop checked access only in its default branch. With
LEGACY_SITE_ENGINES=1 it handed the caller's `business_id` straight to
run_build_loop, which persists the build and fills its picture slots
through generate_dalle_image -> download_and_rehost ->
_upload_site_image_debug. #1464 made that last writer the service role,
so storage no longer checks the business either. Any signed-in stranger
with a business's id could build onto it and write pictures into its
folder. The flag is off by default, so this was conditional, not live.

POST /sites/{business_id}/generate-html had the same shape: a 410 when
the flag is off, and with it on a service-role rebuild of anyone's site,
no owner check at all.

The fix checks the canonical business id before either branch can build.
These run each route under both flag settings with the real access
checks over a two-business fake; only the expensive build is replaced
by a recorder.
"""
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import billing_limits
import business_users_router
import public_site
import sb_clients
import site_composer
from auth_supabase import require_user
from agents.director_agent import router as director_router

A = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"   # the business being built
B = "12773842-3cc6-41a7-9094-b8606e3f7549"   # someone else's
OWNER_A, ADMIN_A, MEMBER_A, VIEWER_A = "u-owner-a", "u-admin-a", "u-member-a", "u-viewer-a"
OWNER_B, STRANGER = "u-owner-b", "u-stranger"
SEATS_A = {ADMIN_A: "admin", MEMBER_A: "member", VIEWER_A: "viewer"}

FLAGS = pytest.mark.parametrize("legacy", ["1", ""], ids=["legacy-on", "legacy-off"])


def _businesses(path, *a, **kw):
    # Like Postgres: a uuid compares case-blind and comes back lowercase.
    if path.startswith("/businesses?id=eq."):
        biz = path.split("id=eq.", 1)[1].split("&", 1)[0].lower()
        owner = {A: OWNER_A, B: OWNER_B}.get(biz)
        return [{"id": biz, "owner_id": owner}] if owner else []
    return []


def _role_of(biz, uid):
    biz, uid = biz.lower(), str(uid)
    if biz == A:
        return "owner" if uid == OWNER_A else SEATS_A.get(uid)
    if biz == B and uid == OWNER_B:
        return "owner"
    return None


def _access(monkeypatch, legacy):
    monkeypatch.setenv("LEGACY_SITE_ENGINES", legacy)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _businesses)
    monkeypatch.setattr(business_users_router, "role_of", _role_of)


# ── POST /director/build-with-loop ───────────────────────────────────

@pytest.fixture
def director(monkeypatch):
    def run(legacy):
        _access(monkeypatch, legacy)
        builds = []
        monkeypatch.setattr(director_router, "run_build_loop",
                            lambda **kw: builds.append(("legacy", kw.get("business_id")))
                            or {"status": "completed"})
        monkeypatch.setattr(site_composer, "compose_site",
                            lambda biz, **kw: builds.append(("composer", biz)) or {"ok": True})
        monkeypatch.setattr(billing_limits, "require_units", lambda biz: None)
        bare, app = FastAPI(), FastAPI()
        bare.include_router(director_router.router)
        app.include_router(director_router.router)
        who = {"id": OWNER_A}
        app.dependency_overrides[sb_clients.authed_request] = (
            lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"]), token="t"))
        signed_in, signed_out = TestClient(app), TestClient(bare)

        def post(user, business_id=A):
            who["id"] = user
            body = {"business_name": "Love City Church", "module_id": "cinematic_authority"}
            if business_id is not None:
                body["business_id"] = business_id
            client = signed_out if user is None else signed_in
            return client.post("/director/build-with-loop", json=body)
        post.builds = builds
        return post
    return run


@FLAGS
def test_director_signed_out_builds_nothing(director, legacy):
    post = director(legacy)
    assert post(None).status_code == 401
    assert post.builds == []


@FLAGS
@pytest.mark.parametrize("user", [STRANGER, VIEWER_A, OWNER_B])
def test_director_refuses_a_build_onto_a_business_the_caller_cannot_change(director, legacy, user):
    post = director(legacy)
    r = post(user)
    assert r.status_code in (403, 404), r.text
    assert post.builds == []


@FLAGS
@pytest.mark.parametrize("business_id", [f"{A}/../{B}", f"{A}&id=eq.{B}", "not-a-uuid"])
def test_director_refuses_an_id_that_is_not_a_plain_uuid(director, legacy, business_id):
    post = director(legacy)
    r = post(OWNER_A, business_id=business_id)
    assert r.status_code == 404, r.text
    assert post.builds == []


@FLAGS
@pytest.mark.parametrize("user", [OWNER_A, ADMIN_A, MEMBER_A])
def test_director_builds_for_someone_allowed_to_change_the_business(director, legacy, user):
    post = director(legacy)
    r = post(user, business_id=A.upper())
    assert r.status_code == 200, r.text
    engine = "legacy" if legacy else "composer"
    assert post.builds == [(engine, A)]          # the canonical id, not the request string


def test_director_legacy_run_without_a_business_writes_to_no_business(director):
    # An ephemeral verification run: nothing to persist into, so nothing to check.
    post = director("1")
    r = post(STRANGER, business_id=None)
    assert r.status_code == 200, r.text
    assert post.builds == [("legacy", None)]


def test_director_default_run_without_a_business_is_retired(director):
    post = director("")
    assert post(OWNER_A, business_id=None).status_code == 410
    assert post.builds == []


# ── POST /sites/{business_id}/generate-html ──────────────────────────

@pytest.fixture
def generate_html(monkeypatch):
    def run(legacy):
        _access(monkeypatch, legacy)
        builds, started = [], threading.Event()

        def job(business_id, site_id):
            builds.append(business_id)
            started.set()
        monkeypatch.setattr(public_site, "_run_builder_job", job)
        monkeypatch.setattr(public_site, "_html_build_cooldown", {})
        import brand_engine
        monkeypatch.setattr(brand_engine, "_sb_get", lambda path, *a, **kw: [
            {"id": "site-a", "site_config": {"design_brief": {"x": 1}}}])
        bare, app = FastAPI(), FastAPI()
        bare.include_router(public_site.router)
        app.include_router(public_site.router)
        who = {"id": OWNER_A}
        app.dependency_overrides[require_user] = (
            lambda: SimpleNamespace(id=who["id"], email=None, role="authenticated"))
        signed_in, signed_out = TestClient(app), TestClient(bare)

        def post(user, business_id=A):
            who["id"] = user
            client = signed_out if user is None else signed_in
            return client.post(f"/sites/{business_id}/generate-html")
        post.builds, post.started = builds, started
        return post
    return run


@FLAGS
def test_generate_html_signed_out_builds_nothing(generate_html, legacy):
    post = generate_html(legacy)
    assert post(None).status_code == 401
    assert post.builds == []


@FLAGS
@pytest.mark.parametrize("user", [STRANGER, OWNER_B])
def test_generate_html_refuses_anyone_but_the_owner(generate_html, legacy, user):
    post = generate_html(legacy)
    r = post(user)
    assert r.status_code in (403, 404), r.text
    assert not post.started.wait(0.2)
    assert post.builds == []


def test_generate_html_legacy_builds_for_the_owner(generate_html):
    post = generate_html("1")
    r = post(OWNER_A)
    assert r.status_code == 202, r.text
    assert post.started.wait(5)
    assert post.builds == [A]


def test_generate_html_stays_retired_for_the_owner_by_default(generate_html):
    post = generate_html("")
    assert post(OWNER_A).status_code == 410
    assert post.builds == []
