"""Post for Me publish (part 2 of practitioner posting).

  1. Only this business's connected accounts can be targets.
  2. Each network's rules are checked before anything leaves: Instagram needs
     a photo, TikTok / YouTube a video, X fits 280, links are https.
  3. A schedule is in the future and within 90 days; a day holds at most
     POSTS_PER_DAY_CAP posts.
  4. What the person approved is fingerprinted with who approved it, and the
     post reaches Post for Me with OUR row id as external_id.
  5. A refused hand-off is recorded as failed, never as sent.
  6. Reading the list settles in-flight posts per account: posted, partly
     posted, failed — each with the live link or the network's error.
  7. Only a future scheduled post can be cancelled.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import post_for_me as pfm  # noqa: E402
import social_publish_router as spr  # noqa: E402

BIZ, OTHER = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
SESSION = SimpleNamespace(user=SimpleNamespace(id="user-1"))
IMG = "https://cdn.test/fade.jpg"
VID = "https://cdn.test/fade.mp4"


def run(coro):
    return asyncio.run(coro)


class FakeDB:
    def __init__(self):
        self.connections = [
            {"id": "c-ig", "business_id": BIZ, "status": "connected", "platform": "instagram",
             "username": "freshcutz", "provider_account_id": "spc_ig"},
            {"id": "c-x", "business_id": BIZ, "status": "connected", "platform": "x",
             "username": "freshcutz", "provider_account_id": "spc_x"},
            {"id": "c-tt", "business_id": BIZ, "status": "connected", "platform": "tiktok",
             "username": "freshcutz", "provider_account_id": "spc_tt"},
            {"id": "c-other", "business_id": OTHER, "status": "connected", "platform": "instagram",
             "username": "elsewhere", "provider_account_id": "spc_o"},
        ]
        self.pubs = []
        self.n = 0

    @staticmethod
    def _q(path):
        q = path.split("?", 1)[1] if "?" in path else ""
        return dict(p.split("=", 1) for p in q.split("&") if "=" in p)

    def get(self, path):
        q = self._q(path)
        if path.startswith("/social_connections"):
            ids = q.get("id", "in.()")[4:-1].split(",")
            return [c for c in self.connections if c["business_id"] == q["business_id"][3:]
                    and c["status"] == "connected" and c["id"] in ids]
        if path.startswith("/social_publications"):
            rows = [p for p in self.pubs if p["business_id"] == q["business_id"][3:]]
            if "id" in q:
                rows = [p for p in rows if p["id"] == q["id"][3:]]
            if q.get("status") == "neq.failed":
                rows = [p for p in rows if p["status"] != "failed"]
            return [dict(r) for r in rows]
        return []

    def post(self, path, body, prefer=None):
        self.n += 1
        row = {"id": f"pub{self.n}", "created_at": "now", "provider_post_id": None,
               "results": [], **body}
        self.pubs.append(row)
        return [dict(row)]

    def patch(self, path, body):
        rid = self._q(path)["id"][3:]
        for p in self.pubs:
            if p["id"] == rid:
                p.update(body)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("POST_FOR_ME_API_KEY", "pfm_test_key")
    monkeypatch.setenv("POST_FOR_ME_PILOT_BUSINESSES", BIZ)
    d = FakeDB()
    monkeypatch.setattr(spr.sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(spr.sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(spr.sb_clients, "sb_patch_as_service", d.patch)
    return d


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def create_post(**kw):
        calls.append(kw)
        return {"id": f"sp_{len(calls)}", "status": "processing"}
    monkeypatch.setattr(pfm, "create_post", create_post)
    return calls


def _publish(**body):
    return run(spr.publish(BIZ, spr.PublishBody(**body), biz={}, session=SESSION))


def _refused(**body):
    with pytest.raises(HTTPException) as e:
        _publish(**body)
    return e.value


# ─── 1. targets ───────────────────────────────────────────────────────

def test_another_business_account_is_refused(db, sent):
    e = _refused(caption="Fresh fades", connection_ids=["c-ig", "c-other"], media=[{"url": IMG}])
    assert e.status_code == 400 and sent == []


def test_outside_the_pilot_nothing_is_sent(db, sent, monkeypatch):
    monkeypatch.setenv("POST_FOR_ME_PILOT_BUSINESSES", OTHER)
    assert _refused(caption="hi", connection_ids=["c-x"]).status_code == 403
    assert sent == []


# ─── 2. each network's rules ──────────────────────────────────────────

def test_instagram_needs_a_photo(db, sent):
    e = _refused(caption="Fresh fades", connection_ids=["c-ig"])
    assert "Instagram needs a photo" in e.detail and sent == []


def test_tiktok_needs_a_video(db, sent):
    assert "TikTok needs a video" in _refused(caption="hi", connection_ids=["c-tt"], media=[{"url": IMG}]).detail
    _publish(caption="hi", connection_ids=["c-tt"], media=[{"url": VID, "kind": "video"}])
    assert len(sent) == 1


def test_x_caption_fits_280(db, sent):
    e = _refused(caption="x" * 281, connection_ids=["c-x"])
    assert "280" in e.detail


def test_media_must_be_https(db, sent):
    e = _refused(caption="hi", connection_ids=["c-ig"], media=[{"url": "http://cdn.test/a.jpg"}])
    assert "https" in e.detail


def test_empty_post_is_refused(db, sent):
    assert _refused(caption="   ", connection_ids=["c-x"]).status_code == 400


# ─── 3. schedule and daily cap ────────────────────────────────────────

def test_schedule_must_be_future_and_within_90_days(db, sent):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    far = (datetime.now(timezone.utc) + timedelta(days=91)).isoformat()
    naive = (datetime.now() + timedelta(days=1)).replace(tzinfo=None).isoformat()
    for when in (past, far, naive):
        assert _refused(caption="hi", connection_ids=["c-x"], scheduled_at=when).status_code == 400
    assert sent == []


def test_daily_cap(db, sent, monkeypatch):
    monkeypatch.setattr(spr, "POSTS_PER_DAY_CAP", 2)
    _publish(caption="one", connection_ids=["c-x"])
    _publish(caption="two", connection_ids=["c-x"])
    assert _refused(caption="three", connection_ids=["c-x"]).status_code == 429
    assert len(sent) == 2


# ─── 4. approval fingerprint and hand-off ─────────────────────────────

def test_post_carries_our_id_and_the_approval(db, sent):
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    out = _publish(caption="Fresh fades", connection_ids=["c-ig", "c-x"], media=[{"url": IMG}],
                   scheduled_at=when)
    row = db.pubs[0]
    assert sent[0]["external_id"] == row["id"]
    assert sorted(sent[0]["account_ids"]) == ["spc_ig", "spc_x"]
    assert sent[0]["media_urls"] == [IMG] and sent[0]["scheduled_at"]
    assert row["media"] == [{"url": IMG, "kind": "image"}]
    assert row["approved_by"] == "user-1" and len(row["approved_hash"]) == 64
    assert row["status"] == "scheduled" and row["provider_post_id"] == "sp_1"
    assert out["publication"]["targets"] == [{"platform": "instagram", "username": "freshcutz"},
                                             {"platform": "x", "username": "freshcutz"}]


def test_fingerprint_changes_with_any_approved_detail():
    t = [{"provider_account_id": "spc_x"}]
    m = [{"url": IMG, "kind": "image"}]
    base = spr._fingerprint("hi", m, t, None)
    assert base != spr._fingerprint("hi!", m, t, None)
    assert base != spr._fingerprint("hi", [], t, None)
    assert base != spr._fingerprint("hi", m, t + [{"provider_account_id": "spc_ig"}], None)
    assert base != spr._fingerprint("hi", m, t, "2026-12-01T10:00:00+00:00")


# ─── 5. a refused hand-off ────────────────────────────────────────────

def test_refused_hand_off_is_recorded_as_failed(db, monkeypatch):
    async def refuse(**kw):
        raise pfm.PostForMeError("Post for Me answered 422.", 422)
    monkeypatch.setattr(pfm, "create_post", refuse)
    assert _refused(caption="hi", connection_ids=["c-x"]).status_code == 502
    assert db.pubs[0]["status"] == "failed"


# ─── 6. settling results ──────────────────────────────────────────────

def _pub(db, sent, ids=("c-ig", "c-x")):
    _publish(caption="Fresh fades", connection_ids=list(ids), media=[{"url": IMG}])
    return db.pubs[-1]


def _results(monkeypatch, results):
    async def post_results(post_id):
        return results
    monkeypatch.setattr(pfm, "post_results", post_results)


def test_all_accounts_posted(db, sent, monkeypatch):
    _pub(db, sent)
    _results(monkeypatch, [
        {"social_account_id": "spc_ig", "success": True, "error": None, "url": "https://instagram.com/p/1"},
        {"social_account_id": "spc_x", "success": True, "error": None, "url": "https://x.com/s/1"}])
    pub = run(spr.list_publications(BIZ, biz={}))["publications"][0]
    assert pub["status"] == "posted"
    assert {r["username"] for r in pub["results"]} == {"freshcutz"}
    assert db.pubs[0]["status"] == "posted"


def test_one_network_failed_is_partly_posted_with_the_reason(db, sent, monkeypatch):
    _pub(db, sent)
    _results(monkeypatch, [
        {"social_account_id": "spc_ig", "success": False, "error": "Media too small", "url": None},
        {"social_account_id": "spc_x", "success": True, "error": None, "url": "https://x.com/s/1"}])
    pub = run(spr.list_publications(BIZ, biz={}))["publications"][0]
    assert pub["status"] == "partly_posted"
    ig = [r for r in pub["results"] if r["platform"] == "instagram"][0]
    assert ig["error"] == "Media too small"


def test_waiting_on_some_accounts_stays_in_flight(db, sent, monkeypatch):
    _pub(db, sent)
    _results(monkeypatch, [{"social_account_id": "spc_x", "success": True, "error": None, "url": None}])
    assert run(spr.list_publications(BIZ, biz={}))["publications"][0]["status"] == "posting"


def test_a_future_scheduled_post_is_not_asked_about(db, sent, monkeypatch):
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _publish(caption="later", connection_ids=["c-x"], scheduled_at=when)
    asked = []

    async def post_results(post_id):
        asked.append(post_id)
        return []
    monkeypatch.setattr(pfm, "post_results", post_results)
    run(spr.list_publications(BIZ, biz={}))
    assert asked == []


# ─── 7. cancel ────────────────────────────────────────────────────────

def test_only_a_future_scheduled_post_can_be_cancelled(db, sent, monkeypatch):
    cancelled = []

    async def cancel_post(pid):
        cancelled.append(pid)
    monkeypatch.setattr(pfm, "cancel_post", cancel_post)
    _publish(caption="now", connection_ids=["c-x"])
    with pytest.raises(HTTPException) as e:
        run(spr.cancel_publication(BIZ, db.pubs[0]["id"], biz={}))
    assert e.value.status_code == 409 and cancelled == []
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _publish(caption="later", connection_ids=["c-x"], scheduled_at=when)
    run(spr.cancel_publication(BIZ, db.pubs[1]["id"], biz={}))
    assert cancelled == ["sp_2"] and db.pubs[1]["status"] == "cancelled"


def test_cannot_cancel_another_business_post(db, sent):
    db.pubs.append({"id": "pubX", "business_id": OTHER, "status": "scheduled"})
    with pytest.raises(HTTPException) as e:
        run(spr.cancel_publication(BIZ, "pubX", biz={}))
    assert e.value.status_code == 404


# ─── 8. uploads ───────────────────────────────────────────────────────

def test_a_video_link_without_an_extension_still_counts_as_video(db, sent):
    # Post for Me media links need not end in .mp4; the client says the kind.
    _publish(caption="new cut", connection_ids=["c-tt"],
             media=[{"url": "https://media.postforme.dev/abc123", "kind": "video"}])
    assert len(sent) == 1


def test_media_slot_respects_the_pilot_and_hands_out_only_the_slot(db, monkeypatch):
    async def slot():
        return {"upload_url": "https://storage.test/put?sig=1", "media_url": "https://media.test/m1"}
    monkeypatch.setattr(pfm, "upload_slot", slot)
    out = run(spr.media_slot(BIZ, biz={}))
    assert out == {"ok": True, "upload_url": "https://storage.test/put?sig=1", "media_url": "https://media.test/m1"}
    monkeypatch.setenv("POST_FOR_ME_PILOT_BUSINESSES", OTHER)
    with pytest.raises(HTTPException) as e:
        run(spr.media_slot(BIZ, biz={}))
    assert e.value.status_code == 403
