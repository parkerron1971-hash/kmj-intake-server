# __tests__/test_member_portal_preview.py
#
# "Preview as a member" (member_portal_preview.py): the church owner opens
# the member app as one of their members without any email or text.
# Pins: owner only; a link works once, for two minutes, for one church;
# the preview shows a banner and saves nothing; it works before the page
# is switched on (for a church that could switch it on); End preview
# clears it.

import pathlib
import sys
import time
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp
import member_portal_church as mpc
import member_portal_preview as pv
from auth_supabase import require_user

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
ANA = "33333333-3333-3333-3333-333333333333"
OWNER = "44444444-4444-4444-4444-444444444444"
HOST = "first-light.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}


class _User:
    def __init__(self, uid):
        self.id = uid


def _param(path, name):
    return (urllib.parse.parse_qs(path.split("?", 1)[1]).get(name, [""])[0])


class Fake:
    def __init__(self, enabled=True, kind="church"):
        self.biz = {"id": BIZ, "name": "First Light Church", "type": kind, "owner_id": OWNER,
                    "settings": {"member_portal": {"enabled": enabled}}, "stripe_account_id": None}
        self.contacts = [{"id": ANA, "business_id": BIZ, "name": "Ana Rivers", "email": "", "phone": ""}]
        self.codes = []
        self.care = []

    def get(self, path):
        if path.startswith("/businesses"):
            return [dict(self.biz)] if _param(path, "id") == f"eq.{BIZ}" else []
        if path.startswith("/contacts"):
            cid = _param(path, "id").removeprefix("eq.")
            biz = _param(path, "business_id").removeprefix("eq.")
            return [dict(c) for c in self.contacts if c["id"] == cid and c["business_id"] == biz]
        return []

    def post(self, path, body, prefer=None):
        if path.startswith("/member_login_codes"):
            row = {**body, "consumed_at": None}
            self.codes.append(row)
            return [row]
        if path.startswith("/ministry_care_requests"):
            self.care.append(body)
            return [body]
        return [body]

    def patch(self, path, body):
        if path.startswith("/member_login_codes"):
            h = _param(path, "code_hash").removeprefix("eq.")
            unused_only = "consumed_at=is.null" in path          # honour the query, not a guess
            hit = [c for c in self.codes if c["code_hash"] == h and (c["consumed_at"] is None or not unused_only)
                   and c["business_id"] == _param(path, "business_id").removeprefix("eq.")]
            for c in hit:
                c.update(body)
            return hit
        return []


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    f = Fake()
    for mod in (mp, pv, mpc):
        monkeypatch.setattr(mod.sb_clients, "sb_get_as_service", f.get)
        monkeypatch.setattr(mod.sb_clients, "sb_post_as_service", f.post)
        monkeypatch.setattr(mod.sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(f.biz), "site": {"slug": "first-light"}})
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site", lambda b: ({"slug": "first-light"}, False))
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [])
    monkeypatch.setattr(mpc, "groups_for", lambda b, me: {"mine": [], "open": []})
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [], "series": []})
    return f


def _client(uid=OWNER):
    app = FastAPI()
    app.include_router(mp.router)
    app.include_router(mpc.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)

    @app.get("/my")
    async def _my(request: mp.Request):
        return await mp.serve(request, "/my")

    @app.get("/my/preview")
    async def _pv(request: mp.Request):
        return await mp.serve(request, "/my/preview")
    return TestClient(app, base_url=f"https://{HOST}")


def _link(c):
    r = c.post(f"/member-portal/{BIZ}/preview", json={"contact_id": ANA})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith(f"https://{HOST}/my/preview?t=")
    return "/my/preview?" + url.split("?", 1)[1]


def test_the_owner_opens_the_app_as_a_member_with_a_banner(fake):
    c = _client()
    r = c.get(_link(c), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert pv.PREVIEW_COOKIE.lower() in r.headers["set-cookie"].lower()
    home = c.get("/my").text
    assert "Hi, Ana" in home and "<strong>Preview</strong>" in home and "Ana Rivers" in home
    assert "End preview" in home


def test_only_the_owner_can_make_a_link(fake):
    c = _client(uid="99999999-9999-9999-9999-999999999999")
    assert c.post(f"/member-portal/{BIZ}/preview", json={"contact_id": ANA}).status_code == 403
    assert not fake.codes


def test_a_link_works_once(fake):
    c = _client()
    link = _link(c)
    assert c.get(link, follow_redirects=False).status_code == 303
    fresh = _client()
    assert fresh.get(link, follow_redirects=False).status_code == 410


def test_a_link_is_for_one_church_and_two_minutes(fake):
    tok = pv.issue_link_token(BIZ, ANA, OWNER)
    assert pv._verify("member-preview-link", OTHER, tok) is None
    assert pv._verify("member-preview-link", BIZ, tok, now=int(time.time()) + pv.LINK_TTL_SECONDS + 1) is None
    payload, sig = tok.split(".")
    assert pv.redeem_link_token(BIZ, payload + "." + sig[:-2] + "AA") is None
    # A preview session can't be passed off as a member session, or the reverse.
    session = pv.mint_session(BIZ, ANA, OWNER)
    assert mp.read_session(session, BIZ) is None
    assert pv.read_session(mp.mint_session(BIZ, "ana@example.com", ANA), BIZ) is None


def test_nothing_saves_in_a_preview(fake):
    c = _client()
    c.get(_link(c))
    r = c.post("/my/prayer", data={"request": "Please pray"}, headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/prayer?err=preview"
    assert not fake.care
    assert mpc.ERRORS["preview"] == "This is a preview, so nothing is saved."


def test_it_works_before_the_page_is_switched_on(fake):
    fake.biz["settings"] = {"member_portal": {"enabled": False}}
    c = _client()
    assert c.get("/my").status_code == 404                     # members still see nothing
    c.get(_link(c))
    page = c.get("/my")
    assert page.status_code == 200 and "<strong>Preview</strong>" in page.text


def test_a_church_that_cant_have_the_page_cant_preview_it(fake):
    fake.biz["type"] = "coach"
    c = _client()
    assert c.post(f"/member-portal/{BIZ}/preview", json={"contact_id": ANA}).status_code == 400


def test_someone_outside_the_church_cant_be_previewed(fake):
    c = _client()
    r = c.post(f"/member-portal/{BIZ}/preview", json={"contact_id": "55555555-5555-5555-5555-555555555555"})
    assert r.status_code == 404 and not fake.codes


def test_end_preview_clears_it(fake):
    c = _client()
    c.get(_link(c))
    r = c.post("/my/preview/end", headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and "max-age=0" in r.headers["set-cookie"].lower()
    after = c.get("/my").text
    assert "Send my code" in after and "<strong>Preview</strong>" not in after
