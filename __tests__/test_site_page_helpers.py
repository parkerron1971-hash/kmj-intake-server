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
    cfg = {"site_pages": ["home", "watch-live", "visit", "watch-live", [], "missing"],
           "generated_pages": {"visit": "visit", "home": "duplicate", "sermons": "sermons",
                               "watch-live": "watch-live", "empty": " ", "invalid/path": "bad", 12: "bad", "none": None}}
    assert list(secondary_pages(cfg)) == ["watch-live", "visit", "sermons"]
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
