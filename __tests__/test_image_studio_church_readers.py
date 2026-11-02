"""In a church, Image Studio's reads open to whoever does the posts or the clips.

The Media & Communications login holds the posts and clips duties
(church_duties, #1691-#1693), so the server lets her post, post clips and
have covers made, and the covers are made as the owner's images
(clip_finder.church_cover_owner). Image Studio's reads were the owner's alone,
so the media library and the Create desk showed her own covers as unreadable.

Pins, for the gallery (GET /ai/images/gallery/{business_id}) and one image
(GET /ai/images/{business_id}/{image_id}):
  * the owner reads exactly as before: their own token, RLS, their own signing
  * in a church, an Admin, a posts holder and a clips holder read the church's
    pictures, as the service role, pinned to that church, and the preview is
    signed as the service role only in that church's folder
  * a church Manager that holds neither is refused (403)
  * another church's id, and a business that isn't a church, keep the
    owner-only rule
  * a failed duties read is a 503, never a yes
  * no owner_id or storage_path reaches anyone
  * writes stay the owner's (create and upload go through business())

The tables are the duties tests' in-memory PostgREST (test_church_duties.DutyDB),
with owner-scoped RLS modelled on APPLY-2026-09-08-image-studio.sql."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import image_studio as studio  # noqa: E402
import sb_clients  # noqa: E402
from test_church_duties import (ADMIN, C_JESS, C_NAIYA, JESS, LAQ, MEM, NAIYA, SHAP, STRANGER, TIARA,  # noqa: E402
                                DutyDB, _seat)
from test_church_follow_up import BIZ, OTHER_BIZ, OWNER  # noqa: E402

OTHER_OWNER = "b1000000-0000-4000-8000-000000000001"
OTHER_MGR = "b2000000-0000-4000-8000-000000000002"   # a Manager at a business that isn't a church
OTHER_ADM = "b3000000-0000-4000-8000-000000000003"   # an Admin there
GRACE = "c0ffee00-0000-4000-8000-000000000001"       # another church
GRACE_OWNER = "c0ffee00-0000-4000-8000-000000000002"

COVER = "d1000000-0000-4000-8000-000000000001"       # a clip cover, made as the owner's
QUEUED = "d1000000-0000-4000-8000-000000000002"      # still being made
BARBER_IMG = "d2000000-0000-4000-8000-000000000001"
GRACE_IMG = "d3000000-0000-4000-8000-000000000001"

REFUSED = ("The church's pictures are for whoever does “Posts” or “Clips and covers”. "
           "The owner or an admin can give you one in Logins & areas.")


def _art(image_id, biz, owner, status="ready"):
    return {"id": image_id, "business_id": biz, "owner_id": owner, "prompt": "Sunday cover", "status": status,
            "storage_path": f"{biz}/{image_id}.png" if status == "ready" else None,
            "created_at": "2099-01-01T00:00:00Z", "model": None, "director": None}


class Harness:
    """Who is calling, and what the server read and signed for them."""

    def __init__(self, fake):
        self.fake = fake
        self.caller = None
        self.service_reads = []   # image_artworks paths read as the service role
        self.user_reads = []      # paths read with the caller's own token
        self.signed = []          # (storage path, Authorization header)

    def session(self):
        return SimpleNamespace(user=SimpleNamespace(id=self.caller, email=None))

    def run(self, uid, fn, *args):
        self.caller = uid
        return asyncio.run(fn(*args, session=self.session()))

    def status(self, uid, fn, *args):
        with pytest.raises(HTTPException) as e:
            self.run(uid, fn, *args)
        return e.value.status_code, e.value.detail

    def gallery(self, uid, biz=BIZ):
        return self.run(uid, studio.gallery, UUID(biz))

    def one(self, uid, biz=BIZ, image_id=COVER):
        return self.run(uid, studio.get_image, UUID(biz), UUID(image_id))


@pytest.fixture
def h(monkeypatch):
    seats = [
        _seat(ADMIN, "admin", "minnie@lovecity.org", lane="treasurer", name="Minnie Tatum"),
        _seat(NAIYA, "manager", "naiya@lovecity.org", lane="office_leadership", contact_id=C_NAIYA),
        _seat(TIARA, "manager", "tiara@lovecity.org", areas=["kids_youth", "people_care", "groups_classes"],
              name="Tiara Adams"),
        _seat(LAQ, "manager", "laquesha@lovecity.org", lane="sunday_serving", name="Laquesha Bailey-Smith"),
        _seat(JESS, "manager", "jessica@lovecity.org"),
        _seat(SHAP, "manager", "shapretta@lovecity.org", lane="media_comms", name="Shapretta McClain"),
        _seat(MEM, "member", "web@lovecity.org"),
    ]
    other = [{**_seat(OTHER_MGR, "manager", "pat@fade.example"), "business_id": OTHER_BIZ},
             {**_seat(OTHER_ADM, "admin", "sam@fade.example"), "business_id": OTHER_BIZ}]
    fake = DutyDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Kevin"}},
                    {"id": OTHER_BIZ, "name": "Fade Street", "type": "barber", "owner_id": OTHER_OWNER,
                     "settings": {}},
                    {"id": GRACE, "name": "Grace Chapel", "type": "ministry", "owner_id": GRACE_OWNER,
                     "settings": {}}],
        business_users=seats + other,
        contacts=[{"id": C_NAIYA, "business_id": BIZ, "name": "Naiya  Clark", "email": "naiya@lovecity.org"},
                  {"id": C_JESS, "business_id": BIZ, "name": "Jessica McCloud", "email": "Jessica@LoveCity.org"}],
        church_role_defs=[{"business_id": BIZ, "key": "executive_pastor", "catalog_key": "executive_pastor",
                           "title": "Executive Pastor", "job": "pastoral", "status": "active"}],
        church_leader_roles=[{"business_id": BIZ, "contact_id": C_JESS, "role": "executive_pastor",
                              "status": "active"}],
        church_duty_holders=[], church_duty_changes=[],
        image_artworks=[_art(COVER, BIZ, OWNER), _art(QUEUED, BIZ, OWNER, status="queued"),
                        _art(BARBER_IMG, OTHER_BIZ, OTHER_OWNER), _art(GRACE_IMG, GRACE, GRACE_OWNER)],
    )
    harness = Harness(fake)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)

    async def as_service(client, method, path, body=None):
        assert method == "GET", f"a reader never writes: {method} {path}"
        harness.service_reads.append(path)
        return fake.get(path)

    async def as_user(client, method, path, jwt, body=None):
        # Owner-scoped RLS: image_artworks by the business owner; a business row
        # to its owner and its seats.
        uid = jwt.removeprefix("jwt-")
        harness.user_reads.append(path)
        table = path.lstrip("/").split("?")[0]
        owned = {b["id"] for b in fake.t["businesses"] if b["owner_id"] == uid}
        seated = {s["business_id"] for s in fake.t["business_users"]
                  if s["user_id"] == uid and s["status"] == "active"}
        rows = fake.get(path)
        if table == "businesses":
            return [r for r in rows if r["id"] in owned | seated]
        if table == "image_artworks":
            return [r for r in rows if r["business_id"] in owned]
        raise AssertionError(f"unexpected read {path}")

    monkeypatch.setattr(sb_clients, "sb_as_service", as_service)
    monkeypatch.setattr(sb_clients, "sb_as_user", as_user)
    monkeypatch.setattr(sb_clients, "sb_headers_service", lambda *a, **k: {"Authorization": "Bearer service"})
    monkeypatch.setattr(sb_clients, "sb_headers_user", lambda jwt: {"Authorization": f"Bearer {jwt}"})
    monkeypatch.setattr(studio, "token", lambda: f"jwt-{harness.caller}")
    monkeypatch.setattr(studio, "require_user", lambda authorization: SimpleNamespace(
        id=authorization.removeprefix("Bearer jwt-")))
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("CHURCH_AREAS", raising=False)

    def storage(request):
        path = request.url.path.split("/object/sign/image-originals/", 1)[1]
        harness.signed.append((path, request.headers.get("authorization")))
        return httpx.Response(200, json={"signedURL": f"/object/sign/image-originals/{path}?token=temporary"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(studio.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(storage)))
    cd._CACHE.clear()
    cd._FAILED.clear()
    ca._MY_CACHE.clear()
    yield harness
    cd._CACHE.clear()
    cd._FAILED.clear()


def _move(h, duty, *uids):
    for u in uids:
        h.fake.t["church_duty_holders"].append({"business_id": BIZ, "duty": duty, "user_id": u})
    cd._CACHE.clear()


def _ids(rows):
    return sorted(r["id"] for r in rows)


# ─── the owner ────────────────────────────────────────────────────────

def test_the_owner_reads_exactly_as_before(h):
    rows = h.gallery(OWNER)
    assert _ids(rows) == sorted([COVER, QUEUED])
    one = h.one(OWNER)
    assert one["id"] == COVER and one["url"].startswith("https://example.supabase.co/storage/v1/object/sign/")
    # Their own token for every image read, and for every signing: RLS stands.
    assert h.service_reads == []
    assert any(p.startswith("/businesses?") for p in h.user_reads)
    assert h.signed == [(f"{BIZ}/{COVER}.png", f"Bearer jwt-{OWNER}")] * 2


def test_the_owner_of_a_business_that_isnt_a_church_reads_as_before(h):
    assert _ids(h.gallery(OTHER_OWNER, OTHER_BIZ)) == [BARBER_IMG]
    assert h.one(OTHER_OWNER, OTHER_BIZ, BARBER_IMG)["id"] == BARBER_IMG
    assert h.service_reads == [] and all(auth == f"Bearer jwt-{OTHER_OWNER}" for _, auth in h.signed)


# ─── who reads in a church ────────────────────────────────────────────

def test_a_church_admin_reads_the_churchs_pictures(h):
    assert _ids(h.gallery(ADMIN)) == sorted([COVER, QUEUED])
    assert h.one(ADMIN)["id"] == COVER
    # As the service role, pinned to the church that was checked.
    assert h.service_reads and all(f"business_id=eq.{BIZ}" in p for p in h.service_reads)
    assert h.signed == [(f"{BIZ}/{COVER}.png", "Bearer service")] * 2


def test_a_posts_holder_and_a_clips_holder_each_read_them(h):
    # Shapretta, Media & Communications: both by her lane.
    assert _ids(h.gallery(SHAP)) == sorted([COVER, QUEUED]) and h.one(SHAP)["id"] == COVER
    # Posts moved to Laquesha alone, clips to Naiya alone: each reads by the one.
    _move(h, "posts", LAQ)
    _move(h, "clips", NAIYA)
    me = lambda uid: SimpleNamespace(id=uid, email=None)  # noqa: E731
    assert cd.holds(BIZ, me(LAQ), "posts") and not cd.holds(BIZ, me(LAQ), "clips")
    assert cd.holds(BIZ, me(NAIYA), "clips") and not cd.holds(BIZ, me(NAIYA), "posts")
    for uid in (LAQ, NAIYA):
        assert _ids(h.gallery(uid)) == sorted([COVER, QUEUED]), uid
        assert h.one(uid)["id"] == COVER, uid
    # Shapretta has neither now, so she is a Manager whose job it isn't.
    assert h.status(SHAP, studio.gallery, UUID(BIZ)) == (403, REFUSED)


def test_the_executive_pastor_reads_them_by_her_record(h):
    assert h.one(JESS)["id"] == COVER


def test_a_church_manager_without_either_duty_is_refused(h):
    for uid in (NAIYA, LAQ, TIARA):
        assert h.status(uid, studio.gallery, UUID(BIZ)) == (403, REFUSED), uid
        assert h.status(uid, studio.get_image, UUID(BIZ), UUID(COVER)) == (403, REFUSED), uid
    assert h.service_reads == [] and h.signed == []


def test_a_member_and_a_stranger_keep_the_owner_only_rule(h):
    assert h.status(MEM, studio.gallery, UUID(BIZ))[0] == 403
    assert h.status(MEM, studio.get_image, UUID(BIZ), UUID(COVER))[0] == 404
    assert h.status(STRANGER, studio.gallery, UUID(BIZ))[0] == 404
    assert h.status(STRANGER, studio.get_image, UUID(BIZ), UUID(COVER))[0] == 404
    assert h.service_reads == [] and h.signed == []


# ─── what stays shut ──────────────────────────────────────────────────

def test_another_churchs_id_is_refused(h):
    # Shapretta has no login at Grace Chapel: its owner-only rule answers.
    assert h.status(SHAP, studio.gallery, UUID(GRACE))[0] in (403, 404)
    assert h.status(SHAP, studio.get_image, UUID(GRACE), UUID(GRACE_IMG))[0] == 404
    # Grace's picture asked for under Love City's id: the read is pinned to Love City.
    assert h.status(SHAP, studio.get_image, UUID(BIZ), UUID(GRACE_IMG)) == (
        404, "Image not found in this business gallery.")
    assert all(f"business_id=eq.{BIZ}" in p for p in h.service_reads)
    assert not any(GRACE in p for p in h.service_reads)
    assert all(not path.startswith(GRACE) for path, _ in h.signed)


def test_a_manager_at_a_business_that_isnt_a_church_is_refused_as_before(h):
    assert h.status(OTHER_MGR, studio.gallery, UUID(OTHER_BIZ)) == (403, "Business access denied.")
    assert h.status(OTHER_MGR, studio.get_image, UUID(OTHER_BIZ), UUID(BARBER_IMG))[0] == 404
    # An Admin there too: nothing about duties reaches a business that isn't a church.
    assert h.status(OTHER_ADM, studio.gallery, UUID(OTHER_BIZ)) == (403, "Business access denied.")
    assert h.service_reads == [] and h.signed == []


def test_a_failed_duties_read_is_a_503_never_a_yes(h, monkeypatch):
    real = h.fake.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("church_duty_holders")
                        else real(path, **kw))
    cd._CACHE.clear()
    assert h.status(SHAP, studio.gallery, UUID(BIZ))[0] == 503
    assert h.status(SHAP, studio.get_image, UUID(BIZ), UUID(COVER))[0] == 503
    assert h.service_reads == [] and h.signed == []
    # The owner's path reads no duties, so it still answers.
    assert h.one(OWNER)["id"] == COVER


def test_a_failed_business_read_falls_back_to_the_owner_only_rule(h, monkeypatch):
    real = h.fake.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("businesses") else real(path, **kw))
    assert h.status(SHAP, studio.gallery, UUID(BIZ)) == (403, "Business access denied.")
    assert h.status(SHAP, studio.get_image, UUID(BIZ), UUID(COVER))[0] == 404
    assert h.service_reads == []
    assert _ids(h.gallery(OWNER)) == sorted([COVER, QUEUED])


def test_no_owner_id_or_storage_path_reaches_a_reader(h):
    for rows in (h.gallery(SHAP), [h.one(SHAP)], h.gallery(ADMIN), h.gallery(OWNER)):
        for row in rows:
            assert "owner_id" not in row and "storage_path" not in row, row
    ready = h.one(SHAP)
    assert ready["url"] == f"https://example.supabase.co/storage/v1/object/sign/image-originals/{BIZ}/{COVER}.png?token=temporary"
    assert "/public/" not in ready["url"]


def test_a_preview_outside_the_churchs_folder_is_never_signed_as_the_server():
    row = _art(GRACE_IMG, GRACE, GRACE_OWNER)
    with pytest.raises(HTTPException) as e:
        studio.reader_storage_headers(row, BIZ)
    assert e.value.status_code == 403
    sneaky = {**_art(COVER, BIZ, OWNER), "storage_path": f"{GRACE}/{GRACE_IMG}.png"}
    with pytest.raises(HTTPException):
        studio.reader_storage_headers(sneaky, BIZ)


def test_writes_stay_the_owners(h):
    # Generate, upload and publish all start at business(): still the owner's.
    for uid in (SHAP, ADMIN):
        h.caller = uid
        with pytest.raises(HTTPException) as e:
            asyncio.run(studio.business(None, UUID(BIZ)))
        assert e.value.status_code == 403, uid
    req = studio.CreateImage(business_id=UUID(BIZ), request_id=uuid4(), prompt="A Sunday cover")
    h.caller = SHAP
    with pytest.raises(HTTPException) as e:
        asyncio.run(studio.create(req, None))
    assert e.value.status_code == 403
    assert h.service_reads == []
