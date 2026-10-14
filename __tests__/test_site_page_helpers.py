"""Stored page enumeration is ordered, defensive, and URL-safe."""
import pytest

from site_page_helpers import secondary_pages, valid_page_id


@pytest.mark.parametrize("pid", ["home", "visit-2", "123", "a-b"])
def test_valid_page_ids(pid):
    assert valid_page_id(pid)


@pytest.mark.parametrize("pid", [None, 2, "", "About", "../bad", "a/b", "a_b", "é", "live\n"])
def test_invalid_page_ids(pid):
    assert not valid_page_id(pid)


def test_secondary_pages_follow_explicit_order_then_unlisted_pages():
    cfg = {"site_pages": ["home", "watch", "visit", "watch", [], "missing"],
           "generated_pages": {"visit": "visit", "home": "duplicate", "sermons": "sermons",
                               "watch": "watch", "empty": " ", "invalid/path": "bad", 12: "bad", "none": None}}
    assert list(secondary_pages(cfg)) == ["watch", "visit", "sermons"]
    assert secondary_pages({"generated_pages": None}) == {}
    assert secondary_pages({"site_pages": "visit", "generated_pages": {"visit": "page"}}) == {"visit": "page"}


@pytest.mark.parametrize("cfg", [None, [], "bad", 42])
def test_secondary_pages_accepts_malformed_config(cfg):
    assert secondary_pages(cfg) == {}


def test_reserved_pages_never_appear_in_stored_page_enumeration():
    from site_page_helpers import RESERVED_PAGE_IDS
    pages = {pid: "reserved" for pid in RESERVED_PAGE_IDS}
    pages["sermons"] = "manual sermon index"
    assert secondary_pages({"generated_pages": pages}) == {"sermons": "manual sermon index"}


def test_every_unaware_single_path_get_before_catchall_is_reserved():
    import inspect
    import re
    from kmj_intake_automation import app
    from site_page_helpers import RESERVED_PAGE_IDS
    unservable = set()
    for route in app.routes:
        if route.path == "/{path:path}":
            break
        if "GET" not in getattr(route, "methods", set()) or not re.fullmatch(r"/[a-z0-9-]+", route.path):
            continue
        source = inspect.getsource(route.endpoint)
        host_aware = (route.endpoint.__module__ == "public_site" and
                      ("_platform_page_or_site(" in source or "_site_response_or_none(" in source))
        if not host_aware:
            unservable.add(route.path[1:])
    else:
        pytest.fail("the public catch-all must remain registered last")
    assert len(unservable) >= 17, "the guard must walk the real app routes"
    assert unservable <= RESERVED_PAGE_IDS, unservable - RESERVED_PAGE_IDS
    assert {"my", "data", "texting-terms", "texting-privacy"} <= RESERVED_PAGE_IDS
    assert "sermons" not in RESERVED_PAGE_IDS


MANUAL = {"html_source": "manual", "manual_redirects": {
    "/what-we-believe": "/beliefs", "/media": "/sermons", "/media/*": "/sermons",
    "/media/series/*": "/sermons#series", "/prayer-request": "/connect#prayer", "/i-m-new": "/"}}


@pytest.mark.parametrize("path,to", [
    ("/what-we-believe", "/beliefs"), ("/what-we-believe/", "/beliefs"), ("/What-We-Believe", "/beliefs"),
    ("/media", "/sermons"), ("/media/", "/sermons"), ("/media/page/2/", "/sermons"),
    ("/media/series/q27vmrh/to-the-future", "/sermons#series"), ("/prayer-request", "/connect#prayer"),
    ("/i-m-new", "/"), ("/mediax", None), ("/media-library", None), ("/", None), ("/unknown", None),
])
def test_manual_redirect_matches_exact_paths_then_the_longest_prefix(path, to):
    from site_page_helpers import manual_redirect
    assert manual_redirect(MANUAL, path) == to


@pytest.mark.parametrize("cfg", [
    {**MANUAL, "html_source": "module-composer"}, {"manual_redirects": MANUAL["manual_redirects"]},
    {"html_source": "manual"}, {"html_source": "manual", "manual_redirects": ["/media"]}, None, "manual",
])
def test_only_a_hand_built_site_with_a_redirect_map_redirects(cfg):
    from site_page_helpers import manual_redirect
    assert manual_redirect(cfg, "/media") is None


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\evil.example", "/a/b",
                                    "/connect?next=https://evil.example", "javascript:alert(1)", "", None, 3])
def test_a_stored_target_that_could_leave_the_site_is_ignored(target):
    from site_page_helpers import manual_redirect
    cfg = {"html_source": "manual", "manual_redirects": {"/old": target}}
    assert manual_redirect(cfg, "/old") is None


def test_clean_redirects_keeps_good_entries_in_order_and_names_every_skip():
    from site_page_helpers import clean_redirects
    redirects = {"/b-old": "/visit", "/live": "/watch", "/a-old": "/", "/x/*": "/visit#top",
                 "/visit": "/watch", "/news": "/visit", "/book": "/visit", "/my/*": "/visit",
                 "/old": "/nowhere", "/old2": "/home"}
    kept, skipped = clean_redirects(redirects, ["home", "visit", "watch"])
    assert list(kept) == ["/b-old", "/live", "/a-old", "/x/*"]
    assert [old for old, _ in skipped] == ["/visit", "/news", "/book", "/my/*", "/old", "/old2"]


def test_clean_redirects_caps_the_map():
    from site_page_helpers import MAX_REDIRECTS, clean_redirects
    kept, skipped = clean_redirects({f"/old-{n}": "/" for n in range(MAX_REDIRECTS + 3)}, ["home"])
    assert len(kept) == MAX_REDIRECTS and len(skipped) == 3


def test_only_live_is_redirected_ahead_of_its_api_route():
    from site_page_helpers import API_SHADOWED_REDIRECTS, RESERVED_PAGE_IDS
    assert API_SHADOWED_REDIRECTS == {"/live"}
    assert {p[1:] for p in API_SHADOWED_REDIRECTS} <= RESERVED_PAGE_IDS
