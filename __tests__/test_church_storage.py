"""A church plan's storage allowance (church_storage.py, church_storage_router.py;
Kevin, 2026-11-17: "build").

Pinned here:
  1. The allowance: 100 / 250 / 500 / 1024 GB, env dials, on the plan limits,
     and on the plan cards only once CHURCH_STORAGE is on for everyone.
  2. The meter: recordings not removed + class recordings + the church's
     files; every read paged past 1,000 rows; a missing files function is
     files_counted false, never a failure; no church plan, no limit.
  3. The switch: off answers {"enabled": false} and a delete is a 404; owner
     is the platform owner's churches only.
  4. The page's contract (the app is built against it), and who may see it.
  5. Deleting: only the church's own, ended, unpublished recording; only its
     own folder in the bucket; never marked removed unless every file went;
     an unpublished draft loses the dead link; a second delete is harmless.
  6. The write key's signing: botocore's answers for a signed DELETE and
     LIST, and the player's GET link unchanged (AWS's published example).
  7. A recording made while full: kept 14 days, three warnings, removed only
     when still full and not published; released (silently) when there's
     room again or it gets published; nothing twice; recording never stops.
  8. The 80% heads-up: once per crossing, again only after dropping below 75%.
  9. Practitioner words never name the bucket, its provider or the database.
"""
from __future__ import annotations

import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from xml.sax.saxutils import escape

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_site  # noqa: E402
import church_storage as cs  # noqa: E402
import church_storage_router as csr  # noqa: E402
import church_texts  # noqa: E402
import feature_gates as fg  # noqa: E402
import member_asks  # noqa: E402
import pricing_config  # noqa: E402
import sample_church  # noqa: E402
import sb_clients  # noqa: E402
import stream_relay_router as sr  # noqa: E402
from auth_supabase import require_user  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER = "44444444-4444-4444-4444-444444444444"
MANAGER = "55555555-5555-4555-8555-555555555555"
MEMBER = "66666666-6666-4666-8666-666666666666"
STRANGER = "77777777-7777-4777-8777-777777777777"
GIB = 1024 ** 3


def pct(n):
    """n% of the 1 GiB test allowance, rounded up, so it reads n%."""
    return -(-GIB * n // 100)

T0 = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)      # a Sunday, as the service ends
WRITE_KEY = "AKWRITE"
FORBIDDEN = ("r2", "cloudflare", "bucket", "postgrest", "supabase", "github", "claude")


def _sid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


class _User:
    def __init__(self, uid):
        self.id = uid
        self.email = f"{uid}@test"


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    """Just enough PostgREST: eq/neq/gt/like/in/is.null/not.is.null filters,
    order, limit (so sb_get_all_as_service pages for real), the files
    function, and ignore-duplicates on church_storage_notes."""

    def __init__(self):
        self.t = {k: [] for k in ("stream_sessions", "academy_courses", "academy_live_sessions", "sermons",
                                  "chief_notifications", "church_storage_notes", "business_users")}
        self.t["businesses"] = [
            {"id": BIZ, "owner_id": OWNER, "comp_tier": "church_small", "subscription_plan": None,
             "subscription_status": "active"},
            {"id": OTHER, "owner_id": STRANGER, "comp_tier": "church_small", "subscription_plan": None,
             "subscription_status": "active"}]
        self.t["business_users"] = [
            {"business_id": BIZ, "user_id": MANAGER, "status": "active", "role": "manager"},
            {"business_id": BIZ, "user_id": MEMBER, "status": "active", "role": "member"}]
        self.files = {BIZ: 0, OTHER: 0}
        self.files_missing = False
        self.fail = set()               # tables (or "rpc") whose reads fail
        self.gets = []

    def _match(self, row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            v = vals[0]
            cell = row.get(k)
            if v == "is.null":
                if cell is not None:
                    return False
            elif v == "not.is.null":
                if cell is None:
                    return False
            elif v.startswith("eq."):
                if str(cell).lower() != v[3:].lower():
                    return False
            elif v.startswith("neq."):
                if str(cell).lower() == v[4:].lower():
                    return False
            elif v.startswith("gt."):
                if cell is None or not str(cell) > v[3:]:
                    return False
            elif v.startswith("like."):
                if not fnmatch(str(cell or ""), v[5:]):
                    return False
            elif v.startswith("in.("):
                if str(cell).lower() not in v[4:-1].lower().split(","):
                    return False
            else:
                raise AssertionError(f"filter not faked: {k}={v}")
        return True

    def get(self, path, redact=False):
        self.gets.append(path)
        table, q = _params(path)
        if table in self.fail:
            return None
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, q)]
        if "order" in q:
            col, _, way = q["order"][0].partition(".")
            rows.sort(key=lambda r: str(r.get(col)), reverse=(way == "desc"))
        return rows[: int(q.get("limit", ["100000"])[0])]

    def post(self, path, body, prefer="return=representation", redact=False):
        if path.startswith("/rpc/"):
            assert path == f"/rpc/{cs.FILES_RPC}"
            if self.files_missing or "rpc" in self.fail:
                return None
            return self.files.get(body["p_business"], 0)
        table, _ = _params(path)
        if table in self.fail:
            return None
        rows = self.t.setdefault(table, [])
        if table == "church_storage_notes" and any(r["business_id"] == body["business_id"] for r in rows):
            assert "ignore-duplicates" in (prefer or "")
            return []
        rows.append(dict(body))
        return [dict(body)]

    def patch(self, path, body):
        table, q = _params(path)
        if table in self.fail:
            return None
        hit = [r for r in self.t.get(table, []) if self._match(r, q)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]

    # ── helpers ──

    def session(self, n, *, biz=BIZ, size=GIB // 4, status="ended", started=None, duration=2 * 3600, **kw):
        sid = _sid(n)
        row = {"id": sid, "business_id": biz, "status": status, "bytes": size, "duration_s": duration,
               "started_at": (started or (T0 - timedelta(days=7 * (50 - n)))).isoformat(),
               "ended_at": None, "sermon_id": None, "playlist_path": sr.playlist_path(biz, sid),
               "removed_at": None, "keep_until": None, "warnings_sent": 0, "last_warned_at": None, **kw}
        self.t["stream_sessions"].append(row)
        return row

    def one(self, sid):
        return next(r for r in self.t["stream_sessions"] if r["id"] == sid)

    def notices(self, kind=None):
        return [n for n in self.t["chief_notifications"]
                if n["type"] == cs.NOTICE_TYPE and (kind is None or n["data"]["kind"] == kind)]


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class R2:
    """The media bucket, as the write key sees it: LIST pages of `page`
    keys with a continuation token, DELETE of one object."""

    def __init__(self, page=2):
        self.objects = {}
        self.page = page
        self.fail_delete = set()
        self.fail_list = False
        self.calls = []

    def add(self, biz, sid, n=3, size=100):
        for i in range(n):
            self.objects[f"live/{biz}/{sid}/seg_{i:06d}.ts"] = size
        self.objects[f"live/{biz}/{sid}/index.m3u8"] = 10

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url):
        p = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(p.query)
        assert q["X-Amz-Credential"][0].startswith(WRITE_KEY + "/"), "signed with the write key"
        assert "X-Amz-Signature" in q
        self.calls.append((method, p.path))
        if method == "GET":
            assert p.path == "/media" and q["list-type"] == ["2"]
            if self.fail_list:
                return _Resp(500)
            prefix = q["prefix"][0]
            after = q.get("continuation-token", [""])[0]
            keys = sorted(k for k in self.objects if k.startswith(prefix) and k > after)
            page, more = keys[: self.page], len(keys) > self.page
            body = "".join(f"<Contents><Key>{escape(k)}</Key><Size>{self.objects[k]}</Size></Contents>"
                           for k in page)
            token = f"<NextContinuationToken>{escape(page[-1])}</NextContinuationToken>" if more else ""
            return _Resp(200, '<?xml version="1.0" encoding="UTF-8"?>'
                              '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                              f"<Name>media</Name><Prefix>{escape(prefix)}</Prefix>"
                              f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{body}{token}"
                              "</ListBucketResult>")
        assert method == "DELETE"
        key = urllib.parse.unquote(p.path[len("/media/"):])
        if key in self.fail_delete:
            return _Resp(500)
        self.objects.pop(key, None)
        return _Resp(204)


@pytest.fixture
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sr, "_church_tz", lambda biz: timezone.utc)
    monkeypatch.setattr(sample_church, "drop_samples", lambda rows, key="business_id": list(rows))
    monkeypatch.setattr(church_texts, "_church_rows", lambda: [dict(b) for b in d.t["businesses"]])
    monkeypatch.setenv("LIMIT_CHURCH_SMALL_STORAGE_GB", "1")       # 1 GiB: small numbers
    sr._cache.clear()
    return d


@pytest.fixture
def r2(monkeypatch):
    bucket = R2()
    monkeypatch.setenv("STREAM_R2_ENDPOINT", "https://acct123.r2.cloudflarestorage.com")
    monkeypatch.setenv("STREAM_R2_BUCKET", "media")
    monkeypatch.setenv("STREAM_R2_ACCESS_KEY_ID", "AKREAD")
    monkeypatch.setenv("STREAM_R2_SECRET_ACCESS_KEY", "read-secret")
    monkeypatch.setenv("STREAM_R2_WRITE_ACCESS_KEY_ID", WRITE_KEY)
    monkeypatch.setenv("STREAM_R2_WRITE_SECRET_ACCESS_KEY", "write-secret")
    monkeypatch.setattr(cs, "_client", lambda: bucket)
    return bucket


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("CHURCH_STORAGE", "on")


def _app(uid=OWNER):
    app = FastAPI()
    app.include_router(csr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


# ─── 1. The allowance ────────────────────────────────────────────────

def test_the_allowance_is_kevins(monkeypatch):
    assert pricing_config.church_storage_gb() == {"church_small": 100, "church_growing": 250,
                                                  "church_established": 500, "church_large": 1024}
    assert pricing_config.extra_storage_offer() == {"gb": 100, "cents": 500}
    lim = fg.plan_limits()
    assert [lim[p]["storage_gb"] for p in fg.CHURCH_PLANS] == [100, 250, 500, 1024]
    assert lim["professional"].get("storage_gb") is None
    monkeypatch.setenv("LIMIT_CHURCH_GROWING_STORAGE_GB", "300")
    monkeypatch.setenv("PRICE_EXTRA_STORAGE_CENTS", "700")
    assert pricing_config.church_storage_gb()["church_growing"] == 300
    assert pricing_config.extra_storage_offer()["cents"] == 700


def test_the_plan_list_says_storage_only_once_it_is_everyones(monkeypatch):
    import stripe_billing as sb
    limits = fg.plan_limits()
    for m in ("off", "owner"):
        monkeypatch.setenv("CHURCH_STORAGE", m)
        assert sb._plan_detail(fg, limits, "church_growing")["storage_gb"] is None
    monkeypatch.setenv("CHURCH_STORAGE", "on")
    assert sb._plan_detail(fg, limits, "church_growing")["storage_gb"] == 250
    assert sb._plan_detail(fg, limits, "professional")["storage_gb"] is None


def test_the_church_plan_cards_say_storage_only_when_on(monkeypatch):
    for m in ("off", "owner"):
        monkeypatch.setenv("CHURCH_STORAGE", m)
        assert not any("storage" in x for x in church_site._includes("church_small"))
        assert "storage" not in church_site._plan_strip()
        assert not any("storage" in x for p in church_site._picker_data()["plans"] for x in p["items"])
    monkeypatch.setenv("CHURCH_STORAGE", "on")
    assert "100 GB of storage" in church_site._includes("church_small")
    assert "1 TB of storage" in church_site._includes("church_large")
    strip = church_site._plan_strip()
    for words in ("100 GB of storage", "250 GB of storage", "500 GB of storage", "1 TB of storage"):
        assert words in strip
    picker = church_site._picker_data()["plans"]
    assert [p["items"][-1] for p in picker] == ["100 GB of storage", "250 GB of storage",
                                               "500 GB of storage", "1 TB of storage"]


# ─── 2. The meter ────────────────────────────────────────────────────

def test_the_meter_counts_recordings_classes_and_files(db, on):
    db.session(1, size=300)
    db.session(2, size=200, removed_at=T0.isoformat())             # deleted: not counted
    db.session(3, size=50, status="live")                           # being recorded: counted
    db.session(4, biz=OTHER, size=10 ** 9)                          # another church
    db.t["academy_courses"] += [{"id": "c1", "business_id": BIZ}, {"id": "c2", "business_id": OTHER}]
    db.t["academy_live_sessions"] += [{"id": "l1", "course_id": "c1", "recording_bytes": 70},
                                      {"id": "l2", "course_id": "c1", "recording_bytes": None},
                                      {"id": "l3", "course_id": "c2", "recording_bytes": 999}]
    db.files[BIZ] = 1000
    m = cs.used(BIZ)
    assert m["parts"] == {"recordings": 350, "classes": 70, "files": 1000}
    assert m["used_bytes"] == 1420 and m["files_counted"] is True
    assert m["allowance_bytes"] == GIB and m["extra_bytes"] == 0
    assert m["state"] == "ok" and m["percent"] == 0


def test_files_not_counted_until_the_migration_and_classes_skip_quietly(db, on):
    db.session(1, size=300)
    assert cs.used(BIZ)["complete"] is True
    db.files_missing = True
    db.fail.add("academy_courses")
    m = cs.used(BIZ)
    assert m["files_counted"] is False and m["parts"] == {"recordings": 300, "classes": 0, "files": 0}
    assert m["complete"] is False                      # the page shows 0s; the rules decide nothing
    db.files_missing = False
    assert cs.used(BIZ)["complete"] is False           # classes still unread
    assert cs.class_bytes(BIZ) is None
    db.fail.clear()
    assert cs.class_bytes(BIZ) == 0 and cs.used(BIZ)["complete"] is True


def test_every_page_is_read(db, on):
    for n in range(1, 1102):
        db.session(n, size=1, started=T0 - timedelta(hours=n))
    assert cs.used(BIZ)["parts"]["recordings"] == 1101
    assert sum("stream_sessions" in g for g in db.gets) >= 2


def test_a_failed_read_is_none_never_zero(db, on):
    db.fail.add("stream_sessions")
    assert cs.used(BIZ) is None


def test_no_church_plan_no_limit(db, on):
    db.t["businesses"][0]["comp_tier"] = None
    m = cs.used(BIZ)
    assert m["allowance_bytes"] is None and m["percent"] is None and m["sundays_left"] is None


def test_states_and_sundays(db, on):
    assert cs.state_of(79, 100) == "ok" and cs.state_of(80, 100) == "near"
    assert cs.state_of(99, 100) == "near" and cs.state_of(100, 100) == "full"
    assert cs.percent_of(996, 1000) == 99
    db.session(1, size=pct(85))
    m = cs.used(BIZ)
    assert m["state"] == "near" and m["percent"] == 85
    # One service on record: what it took is a Sunday.
    assert m["bytes_per_sunday"] == pct(85) and m["sundays_left"] == 0


def test_a_sunday_is_the_churchs_own_average_else_6_gb(db):
    assert cs.sunday_bytes([]) == 6 * GIB
    rows = [{"status": "ended", "duration_s": 3600, "bytes": b, "started_at": f"2026-11-{d:02d}"}
            for d, b in [(1, 1000), (2, 2000), (3, 3000), (4, 4000), (5, 5000), (6, 6000), (7, 7000),
                         (8, 8000), (9, 9000)]]
    rows += [{"status": "ended", "duration_s": 600, "bytes": 1, "started_at": "2026-11-30"},     # a sound check
             {"status": "live", "duration_s": 7200, "bytes": 1, "started_at": "2026-11-30"}]
    assert cs.sunday_bytes(rows) == sum(range(2000, 10000, 1000)) // 8          # the last eight services


# ─── 3 and 4. The switch and the page ────────────────────────────────

def test_switched_off_the_page_is_off_and_delete_is_404(db, r2, monkeypatch):
    monkeypatch.delenv("CHURCH_STORAGE", raising=False)
    s = db.session(1)
    r2.add(BIZ, s["id"])
    c = _app()
    assert c.get(f"/church/storage?business_id={BIZ}").json() == {"enabled": False}
    assert c.delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}").status_code == 404
    assert r2.calls == [] and db.one(s["id"])["removed_at"] is None


def test_owner_is_the_platform_owners_churches_only(db, r2, monkeypatch):
    monkeypatch.setenv("CHURCH_STORAGE", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    assert cs.switched_on(BIZ) and not cs.switched_on(OTHER)
    assert _app().get(f"/church/storage?business_id={BIZ}").json()["enabled"] is True
    assert _app(STRANGER).get(f"/church/storage?business_id={OTHER}").json() == {"enabled": False}
    assert not cs.cards_on()


def test_only_a_manager_or_the_owner(db, on):
    assert _app(MANAGER).get(f"/church/storage?business_id={BIZ}").status_code == 200
    assert _app(MEMBER).get(f"/church/storage?business_id={BIZ}").status_code == 403
    assert _app(STRANGER).get(f"/church/storage?business_id={BIZ}").status_code == 403
    assert _app(STRANGER).delete(f"/church/storage/recordings/{_sid(1)}?business_id={BIZ}").status_code == 403
    assert _app().get("/church/storage?business_id=nope").status_code == 400


def test_the_page_contract(db, r2, on):
    db.session(1, size=100, sermon_id="s-1", started=T0 - timedelta(days=14))
    db.session(2, size=200, started=T0 - timedelta(days=7), keep_until=(T0 + timedelta(days=7)).isoformat(),
               warnings_sent=1)
    db.session(3, size=300, started=T0, status="live")
    db.session(4, size=400, started=T0 - timedelta(days=21), removed_at=T0.isoformat())
    db.t["sermons"] += [{"id": "s-1", "business_id": BIZ, "published": True, "video_url": sr.watch_url(_sid(1))},
                        {"id": "s-2", "business_id": BIZ, "published": False, "video_url": sr.watch_url(_sid(2))}]
    db.files[BIZ] = 50
    got = _app().get(f"/church/storage?business_id={BIZ}").json()
    assert list(got) == ["enabled", "allowance_bytes", "extra_bytes", "used_bytes", "parts", "files_counted",
                         "percent", "state", "bytes_per_sunday", "sundays_left", "can_delete", "can_download",
                         "recordings"]
    assert got["enabled"] is True and got["allowance_bytes"] == GIB and got["used_bytes"] == 650
    assert got["parts"] == {"recordings": 600, "classes": 0, "files": 50}
    assert got["can_delete"] is True and got["can_download"] is False
    assert [r["session_id"] for r in got["recordings"]] == [_sid(2), _sid(1)]     # ended, not removed, newest first
    assert list(got["recordings"][0]) == ["session_id", "started_at", "duration_s", "bytes", "published",
                                          "sermon_id", "keep_until"]
    assert got["recordings"][0]["published"] is False and got["recordings"][0]["keep_until"]
    assert got["recordings"][1]["published"] is True and got["recordings"][1]["sermon_id"] == "s-1"
    # One read of the sermons for the whole list.
    assert sum(g.startswith("/sermons?") for g in db.gets) == 1


def test_the_page_shows_fifty_and_says_when_it_cant_delete(db, on, monkeypatch):
    for n in range(1, 61):
        db.session(n, size=1)
    got = _app().get(f"/church/storage?business_id={BIZ}").json()
    assert len(got["recordings"]) == 50 and got["recordings"][0]["session_id"] == _sid(60)
    assert got["can_delete"] is False


def test_the_page_is_off_for_a_business_not_on_a_church_plan(db, on):
    db.t["businesses"][0]["comp_tier"] = None
    assert _app().get(f"/church/storage?business_id={BIZ}").json() == {"enabled": False}


def test_a_failed_read_is_a_503_never_an_empty_page(db, on):
    db.session(1)
    db.fail.add("sermons")
    assert _app().get(f"/church/storage?business_id={BIZ}").status_code == 503


# ─── 5. Deleting ─────────────────────────────────────────────────────

def test_deleting_takes_only_that_recordings_folder(db, r2, on):
    a, b = db.session(1, size=500, sermon_id="d-1"), db.session(2, size=600)
    r2.add(BIZ, a["id"], n=5)
    r2.add(BIZ, b["id"], n=2)
    r2.objects[f"live/{BIZ}/{a['id']}x/seg_000001.ts"] = 1          # a neighbour sharing the name's start
    db.t["sermons"] += [{"id": "d-1", "business_id": BIZ, "published": False, "video_url": sr.watch_url(a["id"])},
                        {"id": "d-9", "business_id": OTHER, "published": False, "video_url": sr.watch_url(a["id"])}]
    r = _app(MANAGER).delete(f"/church/storage/recordings/{a['id']}?business_id={BIZ}")
    assert r.status_code == 200, r.text
    assert r.json() == {"removed": True, "freed_bytes": 500}
    assert not any(k.startswith(f"live/{BIZ}/{a['id']}/") for k in r2.objects)
    assert sum(k.startswith(f"live/{BIZ}/{b['id']}/") for k in r2.objects) == 3
    assert f"live/{BIZ}/{a['id']}x/seg_000001.ts" in r2.objects
    row = db.one(a["id"])
    assert row["removed_at"] and row["keep_until"] is None
    # The draft keeps its words and loses the dead player; another church's row is untouched.
    assert db.t["sermons"][0]["video_url"] == "" and db.t["sermons"][1]["video_url"]
    # A second delete changes nothing.
    again = _app(MANAGER).delete(f"/church/storage/recordings/{a['id']}?business_id={BIZ}")
    assert again.json() == {"removed": True, "freed_bytes": 0}
    assert cs.used(BIZ)["parts"]["recordings"] == 600


def test_delete_refusals(db, r2, on, monkeypatch):
    live, pub, mine = db.session(1, status="live"), db.session(2), db.session(3)
    theirs = db.session(4, biz=OTHER)
    db.t["sermons"].append({"id": "p", "business_id": BIZ, "published": True, "video_url": sr.watch_url(pub["id"])})
    c = _app()
    assert c.delete(f"/church/storage/recordings/{theirs['id']}?business_id={BIZ}").status_code == 404
    assert c.delete(f"/church/storage/recordings/{_sid(99)}?business_id={BIZ}").status_code == 404
    assert c.delete(f"/church/storage/recordings/{live['id']}?business_id={BIZ}").status_code == 409
    r = c.delete(f"/church/storage/recordings/{pub['id']}?business_id={BIZ}")
    assert r.status_code == 409
    assert r.json()["detail"] == "This recording is a published sermon. Unpublish it first, then delete it."
    monkeypatch.delenv("STREAM_R2_WRITE_ACCESS_KEY_ID")
    r = c.delete(f"/church/storage/recordings/{mine['id']}?business_id={BIZ}")
    assert r.status_code == 503 and r.json()["detail"] == "Deleting recordings isn't switched on yet."
    assert r2.calls == [] and all(s["removed_at"] is None for s in db.t["stream_sessions"])


def test_a_half_finished_delete_is_never_marked_and_a_retry_finishes(db, r2, on):
    s = db.session(1, size=500)
    r2.add(BIZ, s["id"], n=4)
    r2.fail_delete.add(f"live/{BIZ}/{s['id']}/seg_000002.ts")
    c = _app()
    r = c.delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}")
    assert r.status_code == 503 and db.one(s["id"])["removed_at"] is None
    r2.fail_delete.clear()
    assert c.delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}").json() == {
        "removed": True, "freed_bytes": 500}
    assert not any(k.startswith(f"live/{BIZ}/{s['id']}/") for k in r2.objects)


def test_a_listing_that_fails_deletes_nothing(db, r2, on):
    s = db.session(1)
    r2.add(BIZ, s["id"])
    r2.fail_list = True
    assert _app().delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}").status_code == 503
    assert len(r2.objects) == 4 and db.one(s["id"])["removed_at"] is None


def test_a_recording_stored_anywhere_unexpected_is_never_deleted(db, r2, on):
    s = db.session(1, playlist_path=f"live/{BIZ}/index.m3u8")
    r2.add(BIZ, s["id"])
    assert _app().delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}").status_code == 503
    assert r2.calls == [] and len(r2.objects) == 4
    assert cs.recording_prefix(BIZ, {"id": s["id"], "playlist_path": ""}) == f"live/{BIZ}/{s['id']}/"
    assert cs.recording_prefix(BIZ, {"id": "../x"}) is None


def test_the_overview_leaves_out_deleted_recordings_where_storage_is_on(monkeypatch):
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: seen.append(p) or [])
    sr._sessions(BIZ, live=False, limit=10)
    sr._sessions(BIZ, live=False, limit=10, hide_removed=True)
    assert "removed_at" not in seen[0] and "&removed_at=is.null" in seen[1]


def test_the_stream_panel_hides_deleted_recordings_and_still_loads_before_the_migration(db, on, monkeypatch):
    db.session(1)
    db.session(2, removed_at=T0.isoformat())
    monkeypatch.setattr(sr, "is_ready", lambda: True)
    monkeypatch.setattr(sr, "stream_row", lambda biz: {})
    monkeypatch.setattr(sr, "sweep_stale", lambda biz=None: 0)
    monkeypatch.setattr(sr, "staff_watch_url", lambda sid: f"https://x.test/{sid}")
    app = FastAPI()
    app.include_router(sr.router)
    app.dependency_overrides[require_user] = lambda: _User(OWNER)
    c = TestClient(app)
    assert [r["id"] for r in c.get(f"/stream-relay?business_id={BIZ}").json()["recent"]] == [_sid(1)]
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, redact=False: None if "removed_at" in path else real(path))
    assert len(c.get(f"/stream-relay?business_id={BIZ}").json()["recent"]) == 2


# ─── 6. Signing with the write key ───────────────────────────────────

KID, SEC = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
WHEN = datetime(2013, 5, 24, tzinfo=timezone.utc)
R2_HOST = "acct123.r2.cloudflarestorage.com"
SEG = "/media/live/11111111-1111-1111-1111-111111111111/22222222-2222-4222-8222-222222222222/seg_000001.ts"
PREFIX = "live/11111111-1111-1111-1111-111111111111/22222222-2222-4222-8222-222222222222/"


def _sig(url):
    return url.rsplit("X-Amz-Signature=", 1)[1]


def test_the_players_get_link_is_unchanged():
    """AWS's published example for a presigned GET, byte for byte."""
    url = sr.sigv4_presign("https", "examplebucket.s3.amazonaws.com", "/test.txt", key_id=KID, secret=SEC,
                           expires=86400, when=WHEN, region="us-east-1")
    assert url == ("https://examplebucket.s3.amazonaws.com/test.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256"
                   "&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request"
                   "&X-Amz-Date=20130524T000000Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host"
                   "&X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404")


# Each expected signature below is what botocore 1.44.5's S3SigV4QueryAuth
# signs for the same request, key and moment (worked out once, outside the
# repo: there is no boto on this server).
@pytest.mark.parametrize("method,host,path,query,region,expires,want", [
    ("DELETE", "examplebucket.s3.amazonaws.com", "/test.txt", None, "us-east-1", 300,
     "1d101a20982ed26de656b49384a6346ec323d0e26924b2bf56f2a636c5ea20d7"),
    ("DELETE", R2_HOST, SEG, None, "auto", 300,
     "d03a37efbc156aff31576a6616f726850e144f959eba9d664dfbde4f1f37bbcd"),
    ("GET", R2_HOST, "/media", {"list-type": "2", "prefix": PREFIX}, "auto", 300,
     "a90bf8cc6c2a7058fabdd3944f5423711fe59cc7a17400a369f17b59fb43b3be"),
    ("GET", R2_HOST, "/media", {"list-type": "2", "prefix": "live/a b/",
                                "continuation-token": "1ueGcxLPRx1Tr/XYExHnhbYLgveDs2J/wm36Hy4vbOwM="},
     "auto", 300, "b9ce9ce886af08c75d39963c7229fd49cb45f26cab50a106501860fbd3ec6232"),
])
def test_delete_and_list_are_signed_as_botocore_signs_them(method, host, path, query, region, expires, want):
    url = sr.sigv4_presign("https", host, path, key_id=KID, secret=SEC, expires=expires, when=WHEN,
                           region=region, method=method, query=query)
    assert _sig(url) == want


def test_the_list_query_rides_in_the_link_as_signed():
    url = sr.sigv4_presign("https", R2_HOST, "/media", key_id=KID, secret=SEC, expires=300, when=WHEN,
                           query={"list-type": "2", "prefix": PREFIX})
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["list-type"] == ["2"] and q["prefix"] == [PREFIX]
    with pytest.raises(ValueError):
        sr.sigv4_presign("https", R2_HOST, "/media", key_id=KID, secret=SEC, expires=300, when=WHEN,
                         query={"X-Amz-Expires": "999999"})


def test_the_write_key_is_its_own_and_optional(monkeypatch):
    monkeypatch.setenv("STREAM_R2_ENDPOINT", "https://" + R2_HOST)
    monkeypatch.setenv("STREAM_R2_BUCKET", "media")
    monkeypatch.setenv("STREAM_R2_ACCESS_KEY_ID", "AKREAD")
    monkeypatch.setenv("STREAM_R2_SECRET_ACCESS_KEY", "read-secret")
    monkeypatch.delenv("STREAM_R2_WRITE_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("STREAM_R2_WRITE_SECRET_ACCESS_KEY", raising=False)
    assert sr.r2_write_config() is None and sr.r2_write_link("DELETE", "live/x") is None
    assert not cs.can_delete()
    monkeypatch.setenv("STREAM_R2_WRITE_ACCESS_KEY_ID", WRITE_KEY)
    monkeypatch.setenv("STREAM_R2_WRITE_SECRET_ACCESS_KEY", "write-secret")
    url = sr.r2_write_link("DELETE", "live/a/b/seg_000001.ts", when=WHEN)
    assert url.startswith(f"https://{R2_HOST}/media/live/a/b/seg_000001.ts?")
    assert f"X-Amz-Credential={WRITE_KEY}%2F" in url
    assert "AKREAD" not in sr.r2_write_link("GET", None, {"list-type": "2", "prefix": "live/"})
    assert "AKREAD" in sr.r2_link("live/a/b/seg_000001.ts")          # the player keeps the read key
    assert cs.can_delete()


def test_a_listing_page_is_read(db):
    page = cs.parse_listing('<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                            "<IsTruncated>true</IsTruncated><Contents><Key>a/1.ts</Key><Size>7</Size></Contents>"
                            "<NextContinuationToken>tok</NextContinuationToken></ListBucketResult>")
    assert page == ([("a/1.ts", 7)], "tok", True)
    assert cs.parse_listing("<Error><Code>AccessDenied</Code></Error>") is None
    assert cs.parse_listing("not xml") is None


# ─── 7. A recording made while full ──────────────────────────────────

def _fill(db, size=pct(90)):
    return db.session(1, size=size, started=T0 - timedelta(days=30))


def _end(db, n=2, size=pct(20)):
    """Sunday's service, just ended."""
    return db.session(n, size=size, started=T0 - timedelta(hours=2), sermon_id=f"draft-{n}")


def test_switched_off_a_recording_end_does_nothing(db, r2, monkeypatch):
    monkeypatch.delenv("CHURCH_STORAGE", raising=False)
    _fill(db)
    s = _end(db)
    assert cs.recording_ended(BIZ, s["id"], now=T0) is None
    assert db.one(s["id"])["keep_until"] is None and db.notices() == []
    assert db.gets == []                               # not even a read


def test_without_the_write_key_nothing_is_promised(db, r2, on, monkeypatch):
    monkeypatch.delenv("STREAM_R2_WRITE_SECRET_ACCESS_KEY")
    _fill(db)
    s = _end(db)
    assert cs.recording_ended(BIZ, s["id"], now=T0) is None
    assert db.one(s["id"])["keep_until"] is None and db.notices() == []
    assert cs.storage_tick(now=T0)["churches"] == 0


def test_a_recording_made_while_full_is_kept_14_days_and_the_office_hears(db, r2, on):
    _fill(db)
    s = _end(db)
    assert cs.recording_ended(BIZ, s["id"], now=T0) == "held"
    row = db.one(s["id"])
    assert row["keep_until"] == (T0 + timedelta(days=14)).isoformat()
    assert row["warnings_sent"] == 1 and row["last_warned_at"] == T0.isoformat()
    [n] = db.notices("held")
    assert n["title"] == "Your storage is full"
    assert n["body"].startswith("Sunday's recording is kept until Sunday, December 6. Make room to keep it.")
    assert n["priority"] == "high" and n["data"]["session_id"] == s["id"]
    # Once: a retried end, or a second replica, says nothing more.
    assert cs.recording_ended(BIZ, s["id"], now=T0 + timedelta(minutes=1)) is None
    assert len(db.notices()) == 1
    # The heads-up isn't sent on top of the warning.
    assert cs.storage_tick(now=T0 + timedelta(hours=16))["notices"] == 0


def test_under_the_allowance_nothing_is_held(db, r2, on):
    s = _end(db)
    assert cs.recording_ended(BIZ, s["id"], now=T0) is None
    assert db.one(s["id"])["keep_until"] is None and db.notices() == []


def test_a_storage_failure_never_stops_the_end_of_a_service(db, monkeypatch):
    calls = []

    def boom(biz, sid):
        calls.append(sid)
        raise RuntimeError("storage down")
    monkeypatch.setattr(cs, "recording_ended", boom)
    answers = {"stream_relay_close": {"outcome": "ending", "session": {"id": _sid(5), "duration_s": 60}},
               "stream_relay_finish": {"outcome": "ended", "session": {"id": _sid(5), "sermon_id": None}}}
    monkeypatch.setattr(sr, "_rpc", lambda name, args: answers[name])
    assert sr.finalize({"id": _sid(5), "business_id": BIZ}, 60, 1000) is None
    assert calls == [_sid(5)]


def _day(n, hour=9, minute=40):
    return (T0 + timedelta(days=n)).replace(hour=hour, minute=minute)


def test_the_three_warnings_then_the_removal(db, r2, on):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"], n=3)
    db.t["sermons"].append({"id": s["sermon_id"], "business_id": BIZ, "published": False,
                            "video_url": sr.watch_url(s["id"])})
    cs.recording_ended(BIZ, s["id"], now=T0)
    for day in range(1, 8):
        cs.storage_tick(now=_day(day))
    assert db.one(s["id"])["warnings_sent"] == 1                   # day 7 at 9:40 is before 7 x 24 hours
    cs.storage_tick(now=_day(8))
    assert db.one(s["id"])["warnings_sent"] == 2
    [two] = db.notices("second")
    assert two["title"] == "Sunday's recording: one week left"
    assert "kept until Sunday, December 6" in two["body"]
    cs.storage_tick(now=_day(8, hour=12))                         # the same day again: nothing new
    assert len(db.notices("second")) == 1
    for day in range(9, 14):
        cs.storage_tick(now=_day(day))
    assert db.one(s["id"])["warnings_sent"] == 2
    cs.storage_tick(now=_day(14))
    assert db.one(s["id"])["warnings_sent"] == 3
    [last] = db.notices("last")
    assert last["title"] == "Last day to keep Sunday's recording"
    assert "will be deleted after Sunday, December 6" in last["body"]
    assert db.one(s["id"])["removed_at"] is None and len(r2.objects) == 4
    out = cs.storage_tick(now=_day(15))
    assert out["removed"] == 1
    assert db.one(s["id"])["removed_at"] and not r2.objects
    [gone] = db.notices("removed")
    assert gone["title"] == "Sunday's recording was deleted"
    assert "sermon draft is still there, without the video" in gone["body"]
    assert db.t["sermons"][0]["video_url"] == ""
    cs.storage_tick(now=_day(16))
    assert len(db.notices("removed")) == 1                         # told once


def test_never_removed_within_12_hours_of_the_last_warning(db, r2, on):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    keep = T0 + timedelta(days=14)
    s.update(keep_until=keep.isoformat(), warnings_sent=3, last_warned_at=(keep - timedelta(hours=2)).isoformat())
    assert cs.storage_tick(now=keep + timedelta(hours=1))["removed"] == 0
    assert cs.storage_tick(now=keep + timedelta(hours=11))["removed"] == 1


def test_room_again_releases_it_silently(db, r2, on):
    first = _fill(db)
    s = _end(db)
    cs.recording_ended(BIZ, s["id"], now=T0)
    first["removed_at"] = _day(2).isoformat()                       # the church deleted an old one
    out = cs.storage_tick(now=_day(3))
    assert out["cleared"] == 1 and db.one(s["id"])["keep_until"] is None
    assert len(db.notices()) == 1                                   # only the first warning, ever
    for day in range(4, 20):
        cs.storage_tick(now=_day(day))
    assert db.one(s["id"])["removed_at"] is None and len(db.notices()) == 1


def test_published_meanwhile_is_kept_for_good(db, r2, on):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    cs.recording_ended(BIZ, s["id"], now=T0)
    db.t["sermons"].append({"id": "p", "business_id": BIZ, "published": True, "video_url": sr.watch_url(s["id"])})
    assert cs.storage_tick(now=_day(3))["cleared"] == 1
    for day in range(4, 20):
        cs.storage_tick(now=_day(day))
    assert db.one(s["id"])["removed_at"] is None and len(r2.objects) == 4


def test_published_at_the_last_moment_is_not_removed(db, r2, on, monkeypatch):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    keep = T0 + timedelta(days=14)
    s.update(keep_until=keep.isoformat(), warnings_sent=3, last_warned_at=(keep - timedelta(days=1)).isoformat())
    monkeypatch.setattr(cs, "published_sessions", lambda biz: set())          # the morning's read said no
    monkeypatch.setattr(sr, "_published", lambda biz, sid: True)              # and then it was published
    assert cs.storage_tick(now=keep + timedelta(days=1))["removed"] == 0
    assert len(r2.objects) == 4 and db.one(s["id"])["keep_until"] is None


def test_a_failed_read_never_removes(db, r2, on):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    keep = T0 + timedelta(days=14)
    s.update(keep_until=keep.isoformat(), warnings_sent=3, last_warned_at=(keep - timedelta(days=1)).isoformat())
    db.fail.add("sermons")
    assert cs.storage_tick(now=keep + timedelta(days=1))["removed"] == 0
    db.fail = {"stream_sessions"}
    assert cs.storage_tick(now=keep + timedelta(days=1))["removed"] == 0
    assert len(r2.objects) == 4


def test_a_church_that_left_its_plan_is_let_go(db, r2, on):
    _fill(db)
    s = _end(db)
    cs.recording_ended(BIZ, s["id"], now=T0)
    db.t["businesses"][0]["comp_tier"] = None
    assert cs.storage_tick(now=_day(2))["cleared"] == 1
    assert db.one(s["id"])["keep_until"] is None


def test_owner_mode_ticks_only_the_owners_churches(db, r2, monkeypatch):
    monkeypatch.setenv("CHURCH_STORAGE", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    db.session(7, biz=OTHER, size=pct(95))
    out = cs.storage_tick(now=T0)
    assert out["churches"] == 1 and out["notices"] == 0
    assert not db.notices()
    monkeypatch.setenv("CHURCH_STORAGE", "off")
    assert cs.storage_tick(now=T0) == {"churches": 0, "cleared": 0, "warned": 0, "removed": 0, "notices": 0,
                                       "errors": 0}


# ─── 7b. A warning counts only once it reached the office ────────────

def test_a_first_warning_that_didnt_save_is_not_counted_and_is_sent_next_run(db, r2, on):
    _fill(db)
    s = _end(db)
    db.fail.add("chief_notifications")
    assert cs.recording_ended(BIZ, s["id"], now=T0) == "held"
    row = db.one(s["id"])
    assert row["keep_until"] and row["warnings_sent"] == 0 and row["last_warned_at"] is None
    assert db.notices() == []
    db.fail.clear()
    assert cs.storage_tick(now=_day(1))["warned"] == 1
    row = db.one(s["id"])
    assert row["warnings_sent"] == 1 and row["last_warned_at"] == _day(1).isoformat()
    # The 14 days start when the church is told.
    assert row["keep_until"] == (_day(1) + timedelta(days=14)).isoformat()
    [n] = db.notices("held")
    assert "kept until Monday, December 7" in n["body"]
    cs.storage_tick(now=_day(2))
    assert len(db.notices("held")) == 1


def test_a_last_warning_that_didnt_save_is_not_counted_and_nothing_is_removed(db, r2, on):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    cs.recording_ended(BIZ, s["id"], now=T0)
    for day in range(1, 14):
        cs.storage_tick(now=_day(day))
    assert db.one(s["id"])["warnings_sent"] == 2
    db.fail.add("chief_notifications")
    assert cs.storage_tick(now=_day(14))["warned"] == 0
    row = db.one(s["id"])
    assert row["warnings_sent"] == 2 and row["last_warned_at"] == _day(8).isoformat()   # rolled back
    assert db.notices("last") == []
    db.fail.clear()
    out = cs.storage_tick(now=_day(15))            # past the date: the last warning, not a removal
    assert out == {**out, "removed": 0, "warned": 1}
    assert db.one(s["id"])["warnings_sent"] == 3 and len(r2.objects) == 4
    assert len(db.notices("last")) == 1
    assert cs.storage_tick(now=_day(16))["removed"] == 1
    assert not r2.objects


def test_a_claimed_warning_that_couldnt_be_undone_never_counts_and_is_sent_again(db, r2, on, monkeypatch):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    cs.recording_ended(BIZ, s["id"], now=T0)
    for day in range(1, 14):
        cs.storage_tick(now=_day(day))
    real = db.patch

    def no_undo(path, body):                       # the roll-back write fails too
        if "last_warned_at=is.null" in path and body.get("warnings_sent") == 2:
            return None
        return real(path, body)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", no_undo)
    db.fail.add("chief_notifications")
    cs.storage_tick(now=_day(14))
    row = db.one(s["id"])
    assert row["warnings_sent"] == 3 and row["last_warned_at"] is None           # claimed, not delivered
    db.fail.clear()
    out = cs.storage_tick(now=_day(15))            # sent again, still not removed
    assert out["removed"] == 0 and out["warned"] == 1 and len(r2.objects) == 4
    assert db.one(s["id"])["last_warned_at"] == _day(15).isoformat()
    assert len(db.notices("last")) == 1
    assert cs.storage_tick(now=_day(16))["removed"] == 1


def test_a_heads_up_that_didnt_save_is_tried_again(db, r2, on):
    db.session(1, size=pct(85), started=T0 - timedelta(days=7))
    db.fail.add("chief_notifications")
    assert cs.storage_tick(now=_day(0))["notices"] == 0
    db.fail.clear()
    assert cs.storage_tick(now=_day(1))["notices"] == 1
    assert len(db.notices("near")) == 1


# ─── 7c. A failed read never releases, removes or holds ──────────────

@pytest.mark.parametrize("unread", ["files", "classes"])
def test_an_unread_part_never_releases_a_hold(db, r2, on, unread):
    first = _fill(db)
    s = _end(db)
    cs.recording_ended(BIZ, s["id"], now=T0)
    first["removed_at"] = _day(2).isoformat()      # room again, on what can be read
    if unread == "files":
        db.files_missing = True
    else:
        db.fail.add("academy_courses")
    out = cs.storage_tick(now=_day(3))
    assert out["cleared"] == 0 and out["errors"] == 2          # both churches: nothing decided
    assert db.one(s["id"])["keep_until"]
    db.files_missing = False
    db.fail.clear()
    assert cs.storage_tick(now=_day(4))["cleared"] == 1


@pytest.mark.parametrize("unread", ["files", "classes"])
def test_an_unread_part_never_removes(db, r2, on, unread):
    _fill(db)
    s = _end(db)
    r2.add(BIZ, s["id"])
    keep = T0 + timedelta(days=14)
    s.update(keep_until=keep.isoformat(), warnings_sent=3, last_warned_at=(keep - timedelta(days=1)).isoformat())
    if unread == "files":
        db.files_missing = True
    else:
        db.fail.add("academy_courses")
    assert cs.storage_tick(now=keep + timedelta(days=1))["removed"] == 0
    assert len(r2.objects) == 4 and db.one(s["id"])["removed_at"] is None and db.notices() == []


@pytest.mark.parametrize("unread", ["files", "classes"])
def test_a_recording_end_with_an_unread_part_decides_nothing(db, r2, on, unread):
    _fill(db)
    s = _end(db)
    if unread == "files":
        db.files_missing = True
    else:
        db.fail.add("academy_courses")
    assert cs.recording_ended(BIZ, s["id"], now=T0) is None
    assert db.one(s["id"])["keep_until"] is None and db.notices() == []
    near = db.session(3, size=1, started=T0 - timedelta(hours=1))
    _fill_rows = [r for r in db.t["stream_sessions"] if r["id"] in (_sid(1), _sid(2))]
    for r in _fill_rows:
        r["bytes"] = pct(42)                         # 84%: a heads-up, if it could tell
    assert cs.recording_ended(BIZ, near["id"], now=T0) is None
    assert db.notices() == [] and db.t["church_storage_notes"] == []


def test_failures_are_printed_for_the_logs(db, r2, on, capsys):
    s = db.session(1)
    r2.add(BIZ, s["id"])
    r2.fail_delete.add(f"live/{BIZ}/{s['id']}/seg_000001.ts")
    assert _app().delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}").status_code == 503
    r2.fail_list = True
    assert _app().delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}").status_code == 503
    out = capsys.readouterr().out
    assert "[church_storage] delete of" in out and "answered 500" in out
    assert "[church_storage] listing answered 500" in out
    assert "logger" not in pathlib.Path(cs.__file__).read_text(encoding="utf-8")


# ─── 8. The 80% heads-up ─────────────────────────────────────────────

def test_the_heads_up_once_per_crossing(db, r2, on):
    first = db.session(1, size=pct(50), started=T0 - timedelta(days=60))
    db.session(2, size=pct(32), started=T0 - timedelta(days=7))
    assert cs.storage_tick(now=_day(0))["notices"] == 1
    [n] = db.notices("near")
    assert n["title"] == "Your storage is 82% full"
    # 0.18 GiB free, a Sunday ~0.41 GiB: less than one.
    assert n["body"].startswith("There's room for less than one more Sunday's recording.")
    assert "oldest recordings you haven't published" in n["body"]
    for day in range(1, 5):
        cs.storage_tick(now=_day(day))
    assert len(db.notices("near")) == 1                              # not daily
    first["bytes"] = pct(45)                                  # 77%: under 80, not under 75
    cs.storage_tick(now=_day(5))
    first["bytes"] = pct(50)
    cs.storage_tick(now=_day(6))
    assert len(db.notices("near")) == 1                              # sitting at the line: once
    first["removed_at"] = _day(7).isoformat()                        # well under: re-armed
    cs.storage_tick(now=_day(7))
    first["removed_at"] = None
    cs.storage_tick(now=_day(8))
    assert len(db.notices("near")) == 2


def test_the_heads_up_counts_sundays(db, r2, on):
    db.session(1, size=GIB // 16, started=T0 - timedelta(days=7))      # a Sunday: 1/16 GiB
    db.files[BIZ] = GIB * 3 // 4
    assert cs.recording_ended(BIZ, _sid(1), now=T0) == "near"
    [n] = db.notices("near")
    assert n["title"] == "Your storage is 81% full"
    assert n["body"].startswith("There's room for about 3 more Sundays of recordings.")
    assert cs.recording_ended(BIZ, _sid(1), now=T0) is None             # once


# ─── 9. Words ────────────────────────────────────────────────────────

def test_practitioner_words_never_name_the_machinery():
    texts = []
    for kind in ("held", "second", "last", "removed"):
        texts += cs.notice(kind, day="Sunday", started="November 22", keep="Sunday, December 6", has_draft=True)
    for pct, sundays in ((80, 3), (85, 1), (99, 0), (100, 0)):
        texts += cs.notice("near", percent=pct, sundays=sundays)
    src = pathlib.Path(csr.__file__).read_text(encoding="utf-8")
    import re
    texts += re.findall(r'HTTPException\(\d+, "([^"]+)"\)', src)
    texts += re.findall(r'HTTPException\(\d+, "([^"]+)"', pathlib.Path(cs.__file__).read_text(encoding="utf-8"))
    assert len(texts) > 20
    for t in texts:
        low = t.lower()
        assert not any(re.search(rf"\b{w}\b", low) for w in FORBIDDEN), t
