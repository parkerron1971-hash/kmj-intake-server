# __tests__/test_serve_performance.py
#
# Performance pass (2026-08-02) from the site-builder audit.
#
# The public page-serve path did ~8 sequential round trips per view with
# no caching of any kind, and five of them ran inside brand_engine's
# SYNC get_bundle called from an ASYNC handler — so on a single-worker
# uvicorn every anonymous page view stalled the whole event loop.
#
# The rule these tests protect: caching must never make a practitioner
# wait to see their own edit.

from unittest import mock

import brand_engine as be


def _fresh_cache():
    be.invalidate_bundle_cache()


def _fake_business(name="Clean Quick"):
    return {"id": "biz-1", "name": name, "owner_id": "o1",
            "settings": {"brand_kit": {"primary_color": "#2E7DFF"}}}


def test_bundle_is_cached_so_repeat_views_do_no_queries():
    _fresh_cache()
    calls = {"n": 0}

    def counting_get_one(table, col, val):
        calls["n"] += 1
        return _fake_business() if table == "businesses" else {}

    with mock.patch.object(be, "_safe_get_one", side_effect=counting_get_one):
        first = be.get_bundle("biz-1")
        after_first = calls["n"]
        second = be.get_bundle("biz-1")

    assert after_first >= 1, "the first call must actually read"
    assert calls["n"] == after_first, "the second call must hit the cache"
    assert second is first


def test_a_save_invalidates_so_the_practitioner_sees_their_own_edit():
    """The bug this prevents: save_brand_kit ends in get_bundle(), so a
    naive cache would hand the practitioner back the colours they just
    replaced — and keep serving them for the whole TTL."""
    _fresh_cache()
    with mock.patch.object(be, "_safe_get_one",
                           side_effect=lambda t, c, v: _fake_business() if t == "businesses" else {}):
        be.get_bundle("biz-1")
        assert "biz-1" in be._bundle_cache
        be.invalidate_bundle_cache("biz-1")
        assert "biz-1" not in be._bundle_cache


def test_every_brand_write_path_invalidates():
    import inspect
    for fn_name in ("save_brand_kit", "upload_asset", "remove_asset"):
        src = inspect.getsource(getattr(be, fn_name))
        assert "invalidate_bundle_cache" in src, (
            f"{fn_name} writes brand data but never drops the cache — the "
            f"practitioner would keep seeing the old brand for the TTL")


def test_cache_is_per_business():
    _fresh_cache()
    with mock.patch.object(be, "_safe_get_one",
                           side_effect=lambda t, c, v: (
                               {**_fake_business(), "id": v} if t == "businesses" else {})):
        a = be.get_bundle("biz-a")
        b = be.get_bundle("biz-b")
    assert a["business"]["id"] != b["business"]["id"]
    assert be._bundle_cache["biz-a"][1] is not be._bundle_cache["biz-b"][1]


def test_use_cache_false_always_reads_fresh():
    """Read-modify-write callers must be able to bypass."""
    _fresh_cache()
    calls = {"n": 0}

    def counting(table, col, val):
        calls["n"] += 1
        return _fake_business() if table == "businesses" else {}

    with mock.patch.object(be, "_safe_get_one", side_effect=counting):
        be.get_bundle("biz-1")
        n1 = calls["n"]
        be.get_bundle("biz-1", use_cache=False)
    assert calls["n"] > n1


def test_ttl_zero_disables_the_cache_entirely():
    """An escape hatch that actually escapes — BRAND_BUNDLE_TTL=0."""
    _fresh_cache()
    with mock.patch.object(be, "_BUNDLE_TTL", 0):
        with mock.patch.object(be, "_safe_get_one",
                               side_effect=lambda t, c, v: _fake_business() if t == "businesses" else {}):
            be.get_bundle("biz-1")
        assert "biz-1" not in be._bundle_cache


def test_gzip_is_installed_on_the_app():
    import inspect
    import kmj_intake_automation as app_mod
    src = inspect.getsource(app_mod)[:8000]
    assert "GZipMiddleware" in src, (
        "composed pages are 100-250KB of inlined CSS/JS shipped to every "
        "visitor — they must be compressed")
