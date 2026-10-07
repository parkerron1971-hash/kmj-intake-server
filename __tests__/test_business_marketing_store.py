"""The marketing suite's storage door (business_marketing_store.py).

What an approval binds, the short-link code, the run id, the fail-closed
database layer, and the account export/delete coverage of the five tables.
No network: PostgREST is an httpx.MockTransport. The database half (the RPCs
and policies on a real Postgres) is __tests__/business_marketing_db.mjs.
"""
import asyncio
import copy
import json
import pathlib
import re
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import pytest

import account_lifecycle as al
import business_marketing_store as store
import platform_marketing

SQL = (ROOT / "supabase" / "APPLY-2026-10-07-marketing-suite.sql").read_text(encoding="utf-8")
TABLES = ("marketing_desks", "marketing_runs", "marketing_posts", "marketing_link_clicks", "marketing_post_events")

POST_ID = "6f1c2b3a-0d4e-4f5a-8b6c-7d8e9f0a1b2c"
BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
CONN_FB = "11111111-2222-4333-8444-555555555555"
CONN_IG = "66666666-7777-4888-8999-aaaaaaaaaaaa"
ART_1, ART_2 = "aaaaaaaa-0000-4000-8000-000000000001", "aaaaaaaa-0000-4000-8000-000000000002"
CLIP = "cccccccc-0000-4000-8000-000000000001"
COVER_STORY, COVER_WIDE = "dddddddd-0000-4000-8000-000000000001", "dddddddd-0000-4000-8000-000000000002"
RUN_AT = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def picture_post(**over):
    post = {
        "id": POST_ID, "business_id": BIZ,
        "caption": "Open chairs Thursday 2-5.", "publish_text": "Open chairs Thursday 2-5.\n\nhttps://x.example/go/abcdefgh",
        "landing_url": "https://x.example/book",
        "media": {"artwork_ids": [ART_1, ART_2]},
        "targets": [
            {"connection_id": CONN_FB, "platform": "facebook", "username": "kmj", "provider_account_id": "fb-1"},
            {"connection_id": CONN_IG, "platform": "instagram", "username": "kmj.ig", "provider_account_id": "ig-1"},
        ],
        "run_at": RUN_AT, "expires_at": RUN_AT + timedelta(hours=6),
        # Not content: none of these is bound.
        "status": "draft", "revision": 1, "source": "plan", "play_id": "open_chairs", "design_status": "ready",
        "approved_hash": None, "approved_by": None, "approved_at": None, "approved_via": None,
        "error": None, "link_code": "abcdefgh", "tracked_url": "https://x.example/book?utm_content=x",
        "opening": {"offering": "cut", "starts": "14:00", "ends": "17:00", "open_count": 3},
        "run_id": None, "publication_id": None, "external_urls": [], "claimed_at": None, "checked_at": None,
    }
    post.update(over)
    return post


def clip_post(**over):
    return picture_post(media={"clip_id": CLIP, "clip_fingerprint": "f" * 64,
                               "covers": {"story": COVER_STORY, "wide": COVER_WIDE}}, **over)


# ── the approval binding ─────────────────────────────────────────────

def test_digest_is_a_content_hash_the_database_accepts():
    assert re.fullmatch(r"[a-f0-9]{64}", store.digest(picture_post()))
    assert re.fullmatch(r"[a-f0-9]{64}", store.digest(clip_post()))


def test_digest_of_a_row_read_back_equals_the_digest_it_was_saved_with():
    """PostgREST hands back strings: ISO times in UTC, uuids as text, jsonb as
    dicts. The hash computed before the insert must match the row read back,
    or every approval would look stale."""
    saved = picture_post(id=UUID(POST_ID), business_id=UUID(BIZ))
    read_back = json.loads(json.dumps(picture_post(), default=str))
    read_back["run_at"] = "2026-10-08T15:00:00+00:00"
    read_back["expires_at"] = "2026-10-08T21:00:00Z"
    assert store.digest(saved) == store.digest(read_back)


@pytest.mark.parametrize("change", [
    pytest.param(lambda p: p.update(id=POST_ID.upper()), id="uuid case"),
    pytest.param(lambda p: p.update(run_at=RUN_AT.astimezone(timezone(timedelta(hours=-4)))), id="same instant, other zone"),
    pytest.param(lambda p: p["targets"].reverse(), id="targets in another order"),
    pytest.param(lambda p: p["targets"][0].update(username="renamed"), id="a renamed handle"),
    pytest.param(lambda p: p.update(status="approved", revision=4, approved_hash="a" * 64, approved_by=BIZ,
                                    approved_at="x", approved_via="owner"), id="approval stamps"),
    pytest.param(lambda p: p.update(status="failed", error="boom", claimed_at="x", checked_at="y",
                                    publication_id=str(uuid4()), external_urls=[{"url": "u"}]), id="delivery"),
    pytest.param(lambda p: p.update(source="chief", play_id="other", design_status="designing", run_id=str(uuid4())), id="provenance"),
    pytest.param(lambda p: p.update(opening={"offering": "beard"}), id="the opening it was made for"),
    pytest.param(lambda p: p.update(link_code="zzzzzzzz", tracked_url="https://elsewhere"), id="link bookkeeping"),
])
def test_digest_ignores_what_is_not_content(change):
    before = picture_post()
    after = copy.deepcopy(before)
    change(after)
    assert store.digest(after) == store.digest(before)


@pytest.mark.parametrize("change", [
    pytest.param(lambda p: p.update(id=str(uuid4())), id="id"),
    pytest.param(lambda p: p.update(business_id=str(uuid4())), id="business"),
    pytest.param(lambda p: p.update(caption=p["caption"] + "!"), id="caption"),
    pytest.param(lambda p: p.update(publish_text=p["publish_text"] + " "), id="publish_text"),
    pytest.param(lambda p: p.update(landing_url="https://x.example/other"), id="landing_url"),
    pytest.param(lambda p: p["media"]["artwork_ids"].reverse(), id="picture order"),
    pytest.param(lambda p: p["media"]["artwork_ids"].pop(), id="one picture fewer"),
    pytest.param(lambda p: p.update(media={}), id="no pictures"),
    pytest.param(lambda p: p["targets"].pop(), id="one account fewer"),
    pytest.param(lambda p: p["targets"][0].update(platform="x"), id="account platform"),
    pytest.param(lambda p: p["targets"][0].update(provider_account_id="fb-2"), id="account id"),
    pytest.param(lambda p: p["targets"][0].update(connection_id=str(uuid4())), id="connection"),
    pytest.param(lambda p: p.update(run_at=RUN_AT + timedelta(minutes=1)), id="run_at"),
    pytest.param(lambda p: p.update(run_at=RUN_AT + timedelta(microseconds=1)), id="run_at by a microsecond"),
    pytest.param(lambda p: p.update(expires_at=RUN_AT + timedelta(hours=5)), id="expires_at"),
])
def test_digest_binds_every_part_of_the_content(change):
    before = picture_post()
    after = copy.deepcopy(before)
    change(after)
    assert store.digest(after) != store.digest(before)


@pytest.mark.parametrize("change", [
    pytest.param(lambda m: m.update(clip_id=str(uuid4())), id="another clip"),
    pytest.param(lambda m: m.update(clip_fingerprint="e" * 64), id="the clip re-edited"),
    pytest.param(lambda m: m["covers"].update(story=str(uuid4())), id="another cover"),
    pytest.param(lambda m: m["covers"].pop("wide"), id="one cover fewer"),
])
def test_digest_binds_the_clip_its_fingerprint_and_its_covers(change):
    before = clip_post()
    after = copy.deepcopy(before)
    change(after["media"])
    assert store.digest(after) != store.digest(before)
    assert store.digest(clip_post()) != store.digest(picture_post())


def test_a_cover_left_empty_is_no_cover():
    a = clip_post()
    b = copy.deepcopy(a)
    a["media"]["covers"].pop("wide")
    b["media"]["covers"]["wide"] = None
    assert store.digest(a) == store.digest(b)


@pytest.mark.parametrize("post", [
    pytest.param(picture_post(run_at=datetime(2026, 10, 8, 15, 0)), id="a time without a zone"),
    pytest.param(picture_post(media={"clip_id": CLIP, "clip_fingerprint": "f" * 64, "artwork_ids": [ART_1]}), id="clip and pictures"),
    pytest.param(picture_post(media={"clip_id": CLIP}), id="a clip without its fingerprint"),
    pytest.param(picture_post(media=[ART_1]), id="media as a list"),
    pytest.param(picture_post(targets=[{"platform": "facebook"}]), id="a target with no account"),
    pytest.param(picture_post(targets={"connection_id": CONN_FB}), id="targets as an object"),
    pytest.param(picture_post(id="not-a-uuid"), id="a bad id"),
])
def test_digest_refuses_what_it_cannot_bind_exactly(post):
    with pytest.raises(ValueError):
        store.digest(post)


# ── the short link and the run id ───────────────────────────────────

def test_link_code_is_stable_short_and_per_post():
    a, b = uuid4(), uuid4()
    assert store.link_code(a) == store.link_code(str(a)) == store.link_code(str(a).upper())
    assert store.link_code(a) != store.link_code(b)
    assert store.GO_CODE.match(store.link_code(a))
    assert store.GO_CODE.match(store.link_code(b))


def test_link_code_has_its_own_namespace_apart_from_the_platform_desk():
    post = uuid4()
    assert store.link_code(post) != platform_marketing.link_code(post)


def test_one_run_per_business_per_week():
    week = date(2026, 10, 8)
    assert store.run_id_for(BIZ, week) == store.run_id_for(BIZ.upper(), "2026-10-08")
    assert store.run_id_for(BIZ, week) != store.run_id_for(str(uuid4()), week)
    assert store.run_id_for(BIZ, week) != store.run_id_for(BIZ, week + timedelta(days=7))
    with pytest.raises(ValueError):
        store.run_id_for(BIZ, datetime(2026, 10, 8, 9, 0))


def test_the_app_writes_only_values_the_migration_accepts():
    """A value the app writes and a CHECK refuses is a write that silently
    never happened (MIGRATIONS.md, 2026-08-27). Parse the migration's lists."""
    def check(name):
        m = re.search(rf"CONSTRAINT {name} CHECK \((\w+) IN\s*\((.*?)\)\)", SQL, re.S)
        assert m, name
        return tuple(re.findall(r"'([a-z_]+)'", m.group(2)))
    assert check("marketing_posts_status") == store.POST_STATUSES
    assert check("marketing_posts_source") == store.POST_SOURCES
    assert check("marketing_posts_design_status") == store.DESIGN_STATUSES
    assert check("marketing_posts_approved_via") == store.APPROVED_VIA
    assert check("marketing_runs_kind") == store.RUN_KINDS
    assert check("marketing_runs_trigger") == store.RUN_TRIGGERS
    assert check("marketing_runs_status") == store.RUN_STATUSES


# ── the migration's shape ───────────────────────────────────────────

def _code(sql):
    return re.sub(r"--.*$", "", sql, flags=re.M)


def test_the_migration_is_replayable_and_reloads_the_api():
    code = _code(SQL)
    assert SQL.rstrip().endswith("NOTIFY pgrst, 'reload schema';")
    assert len(re.findall(r"CREATE TABLE IF NOT EXISTS", code)) == 5
    assert "CREATE TABLE public" not in code and "CREATE INDEX marketing" not in code
    assert len(re.findall(r"CREATE POLICY", code)) == len(re.findall(r"DROP POLICY IF EXISTS", code)) == 6
    assert len(re.findall(r"CREATE TRIGGER", code)) == len(re.findall(r"DROP TRIGGER IF EXISTS", code))


def test_every_table_has_rls_and_no_policy_is_open():
    code = _code(SQL)
    for t in TABLES:
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in code, t
    assert not re.search(r"using\s*\(\s*true\s*\)", code, re.I)
    for t in ("marketing_link_clicks", "marketing_post_events"):
        assert not re.search(rf"CREATE POLICY \w+ ON public\.{t}\b", code), f"{t} is service-role only"
    for t in ("marketing_desks", "marketing_runs", "marketing_posts"):
        policies = re.findall(rf"CREATE POLICY \w+ ON public\.{t}\s+FOR (\w+) TO authenticated", code)
        assert policies == ["SELECT", "SELECT"], (t, policies)
    grant = re.search(r"GRANT SELECT ON (.*?) TO authenticated;", code, re.S).group(1)
    assert grant == "public.marketing_desks, public.marketing_runs, public.marketing_posts"


def test_every_rpc_is_service_role_only():
    code = _code(SQL)
    rpcs = ("marketing_claim_run", "marketing_approve", "marketing_claim_due", "marketing_follow")
    revoke = re.search(r"REVOKE ALL ON FUNCTION(.*?)FROM PUBLIC, anon, authenticated;", code, re.S).group(1)
    grant = re.search(r"GRANT EXECUTE ON FUNCTION(.*?)TO service_role;", code, re.S).group(1)
    for name in rpcs:
        assert f"public.{name}(" in revoke and f"public.{name}(" in grant, name
        body = re.search(rf"FUNCTION public\.{name}\(.*?\$\$(.*?)\$\$;", code, re.S)
        assert body, name
        header = code[code.index(f"FUNCTION public.{name}("):code.index("$$", code.index(f"FUNCTION public.{name}("))]
        assert "SET search_path = pg_catalog, public" in header, name
        assert "SECURITY DEFINER" not in header, name


# ── the fail-closed door ────────────────────────────────────────────

@pytest.fixture
def pgrst(monkeypatch):
    """PostgREST as a MockTransport. Set .answer to (status, body) or an exception."""
    monkeypatch.setenv("SUPABASE_URL", "https://db.example")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("SUPABASE_ANON", "anon-key")

    class Fake:
        answer = (200, [])
        calls = []

    def handler(request):
        Fake.calls.append(request)
        if isinstance(Fake.answer, Exception):
            raise Fake.answer
        status, body = Fake.answer
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    monkeypatch.setattr(store, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return Fake


def test_reads_go_out_as_the_service_role_never_anon(pgrst):
    pgrst.answer = (200, [{"business_id": BIZ, "paused": False}])
    assert run(store.get_desk(BIZ)) == {"business_id": BIZ, "paused": False}
    sent = pgrst.calls[-1]
    assert sent.headers["authorization"] == "Bearer service-key"
    assert sent.headers["apikey"] == "service-key"
    assert str(sent.url).startswith("https://db.example/rest/v1/marketing_desks?business_id=eq." + BIZ)


def test_no_desk_is_none_but_an_unreadable_desk_raises(pgrst):
    pgrst.answer = (200, [])
    assert run(store.get_desk(BIZ)) is None
    for failure in [(500, {"message": "boom"}), (404, {"code": "PGRST205"}), (401, {}), (200, {"not": "a list"})]:
        pgrst.answer = failure
        with pytest.raises(store.StoreUnavailable):
            run(store.get_desk(BIZ))
    pgrst.answer = httpx.ConnectError("down")
    with pytest.raises(store.StoreUnavailable):
        run(store.get_post(BIZ, POST_ID))


def test_no_service_key_is_unavailable_not_empty(pgrst, monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    with pytest.raises(store.StoreUnavailable):
        run(store.get_desk(BIZ))
    assert pgrst.calls == [], "never falls back to another key"


def test_get_post_is_scoped_to_the_business(pgrst):
    run(store.get_post(BIZ, POST_ID))
    url = str(pgrst.calls[-1].url)
    assert f"id=eq.{POST_ID}" in url and f"business_id=eq.{BIZ}" in url
    with pytest.raises(ValueError):
        run(store.get_post(BIZ, "x&business_id=neq.0"))


def test_approve_sends_the_exact_versions_and_returns_the_count(pgrst):
    pgrst.answer = (200, 2)
    items = [{"id": POST_ID, "revision": 3, "content_hash": "a" * 64},
             {"id": str(uuid4()), "revision": 1, "content_hash": "b" * 64}]
    assert run(store.approve(BIZ, items, actor=BIZ)) == 2
    sent = pgrst.calls[-1]
    assert str(sent.url) == "https://db.example/rest/v1/rpc/marketing_approve"
    body = json.loads(sent.content)
    assert body == {"p_business_id": BIZ, "p_items": items, "p_actor": BIZ, "p_via": "owner"}


@pytest.mark.parametrize("items,via", [
    ([], "owner"),
    ([{"id": POST_ID, "revision": 1, "content_hash": "a" * 64}] * 51, "owner"),
    ([{"id": POST_ID, "revision": 1, "content_hash": "short"}], "owner"),
    ([{"id": POST_ID, "revision": "1", "content_hash": "a" * 64}], "owner"),
    ([{"id": POST_ID, "content_hash": "a" * 64}], "owner"),
    ([{"id": POST_ID, "revision": 1, "content_hash": "a" * 64}], "chief"),
])
def test_approve_refuses_a_malformed_batch_before_the_database(pgrst, items, via):
    with pytest.raises(ValueError):
        run(store.approve(BIZ, items, actor=BIZ, via=via))
    assert pgrst.calls == []


def test_a_refused_approval_is_a_conflict_with_the_databases_words(pgrst):
    pgrst.answer = (400, {"code": "P0001", "message": "A post changed or its time passed; refresh and review again"})
    with pytest.raises(store.StoreConflict, match="refresh and review again"):
        run(store.approve(BIZ, [{"id": POST_ID, "revision": 1, "content_hash": "a" * 64}], actor=BIZ))
    pgrst.answer = (400, {"code": "22P02", "message": 'invalid input syntax for type uuid: "x"'})
    with pytest.raises(store.StoreConflict) as raised:
        run(store.approve(BIZ, [{"id": POST_ID, "revision": 1, "content_hash": "a" * 64}], actor=BIZ))
    assert "syntax" not in str(raised.value), "Postgres internals stay in the log"
    pgrst.answer = (409, {"code": "23505"})
    with pytest.raises(store.StoreConflict):
        run(store.request("POST", "/marketing_posts", {"id": POST_ID}))


def test_claim_due_and_claim_run_and_follow(pgrst):
    pgrst.answer = (200, [{"id": POST_ID, "status": "dispatching"}])
    assert run(store.claim_due(5)) == [{"id": POST_ID, "status": "dispatching"}]
    assert json.loads(pgrst.calls[-1].content) == {"p_limit": 5}
    for bad in (0, 101, "5"):
        with pytest.raises(ValueError):
            run(store.claim_due(bad))

    pgrst.answer = (200, True)
    assert run(store.claim_run(BIZ, date(2026, 10, 8), kind="week", source="scheduled")) is True
    body = json.loads(pgrst.calls[-1].content)
    assert body == {"p_run_id": str(store.run_id_for(BIZ, date(2026, 10, 8))), "p_business_id": BIZ,
                    "p_week": "2026-10-08", "p_kind": "week", "p_source": "scheduled", "p_replan": False}
    pgrst.answer = (200, None)
    with pytest.raises(store.StoreUnavailable):
        run(store.claim_run(BIZ, "2026-10-08", kind="week", source="manual"))
    with pytest.raises(ValueError):
        run(store.claim_run(BIZ, "2026-10-08", kind="blast", source="manual"))

    calls = len(pgrst.calls)
    assert run(store.follow("NOT-A-CODE", count_click=True)) is None
    assert len(pgrst.calls) == calls, "a malformed code never reaches the database"
    pgrst.answer = (200, [])
    assert run(store.follow("abcdefgh", count_click=True)) is None
    pgrst.answer = (200, [{"business_id": BIZ, "tracked_url": "https://x.example/book?utm_content=1"}])
    assert run(store.follow("abcdefgh", count_click=False)) == {"business_id": BIZ,
                                                                "tracked_url": "https://x.example/book?utm_content=1"}
    assert json.loads(pgrst.calls[-1].content) == {"p_code": "abcdefgh", "p_count_click": False}
    pgrst.answer = (503, {})
    with pytest.raises(store.StoreUnavailable):
        run(store.follow("abcdefgh", count_click=True))


# ── export, delete and import ───────────────────────────────────────

def test_the_five_tables_are_exported_and_deleted_with_the_business():
    order = {t: i for i, t in enumerate(al.BUSINESS_CHILD_TABLES)}
    for t in TABLES:
        assert t in order, t
        assert t not in al.EXPORT_EXCLUDED, t
    assert order["marketing_post_events"] < order["marketing_posts"]
    assert order["marketing_link_clicks"] < order["marketing_posts"]
    assert order["marketing_posts"] < order["marketing_runs"]
    assert order["marketing_posts"] < order["audit_log"]


def test_history_is_never_restored_from_a_file_but_the_desk_settings_are():
    for t in ("marketing_runs", "marketing_posts", "marketing_link_clicks", "marketing_post_events"):
        assert t in al._IMPORT_SKIP, t
    assert "marketing_desks" not in al._IMPORT_SKIP
