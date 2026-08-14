"""
test_site_traffic_per_business.py — the top of the funnel.

Every number on WebsiteTraffic.tsx is a CONVERSION — form submissions,
bookings, link clicks, downloads. The denominator did not exist, so
"twelve leads" could not be told apart from twelve-out-of-thirty or
twelve-out-of-a-thousand.

site_events held traffic for mysolutionist.app only: no business_id,
and the read gated to PLATFORM_OWNER_EMAIL. This gives the table a
second tenant without disturbing the first, which is what most of these
tests are about.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import lead_attribution as la  # noqa: E402
import public_site as ps  # noqa: E402
import site_analytics as sa  # noqa: E402

BIZ = "11111111-2222-4333-8444-555555555555"


class Req:
    def __init__(self, origin=None):
        self.headers = {"origin": origin} if origin else {}


# ═══════════════════════════════════════════════════════════════════════
# The beacon
# ═══════════════════════════════════════════════════════════════════════

def test_a_served_page_gets_the_beacon():
    html = ps._inject_traffic_beacon("<html><body><h1>Hi</h1></body></html>", BIZ)
    assert "sol_sid" in html
    assert BIZ in html
    assert html.index("sol_sid") < html.index("</body>")


def test_the_beacon_is_stamped_once():
    once = ps._inject_traffic_beacon("<body></body>", BIZ)
    assert ps._inject_traffic_beacon(once, BIZ) == once


def test_no_business_means_no_beacon():
    assert ps._inject_traffic_beacon("<body></body>", None) == "<body></body>"


def test_there_is_a_kill_switch():
    import os
    with mock.patch.dict(os.environ, {"SITE_TRAFFIC": "off"}):
        assert ps._inject_traffic_beacon("<body></body>", BIZ) == "<body></body>"


def test_a_page_with_no_body_tag_still_renders():
    """Defensive: a site that cannot be measured is a small problem, a
    site that will not render is a large one."""
    out = ps._inject_traffic_beacon("<h1>bare</h1>", BIZ)
    assert out.startswith("<h1>bare</h1>")
    assert "sol_sid" in out


def test_the_beacon_honours_do_not_track_in_the_browser():
    """Server-side DNT already exists. Client-side too, so a visitor who
    asked not to be tracked costs nothing — not even a request."""
    js = ps._traffic_beacon(BIZ)
    assert "doNotTrack" in js
    assert js.index("doNotTrack") < js.index("fetch(")


def test_the_beacon_does_not_use_sendBeacon():
    """sendBeacon is the right tool and it does not work here: a JSON
    body is not a CORS simple request, beacons cannot preflight, and
    cross-origin the browser drops it SILENTLY. Customer sites on their
    own verified domain are always cross-origin to the API."""
    js = ps._traffic_beacon(BIZ)
    assert "sendBeacon" not in js
    assert "keepalive:true" in js


def test_the_beacon_posts_somewhere_absolute():
    """A relative /api/track resolves against the CUSTOMER's domain,
    where nothing is listening."""
    js = ps._traffic_beacon(BIZ)
    assert "https://" in js and "/api/track" in js


def test_the_beacon_rides_the_same_seam_as_the_rest_of_the_page_hooks():
    """All ten call sites of _inject_brand_meta are visitor-facing
    pages; previews render through other handlers. Riding it is how the
    beacon reaches the site, its pages, thank-you, the link page, the
    resource library, booking and academy without ten edits."""
    import inspect
    src = inspect.getsource(ps._inject_brand_meta)
    assert "_inject_traffic_beacon" in src


# ═══════════════════════════════════════════════════════════════════════
# Ingest — the second tenant must not disturb the first
# ═══════════════════════════════════════════════════════════════════════

def _track(payload, origin=None, ua=None, dnt=None, business_exists=True):
    posted = {}

    class FakeResp:
        status_code = 200
        text = ""
        def json(self): return [{"id": BIZ}] if business_exists else []

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw): return FakeResp()
        async def post(self, url, **kw):
            posted.update(kw.get("json") or {})
            return FakeResp()

    ev = sa.TrackEvent(**payload)
    with mock.patch.object(sa.httpx, "AsyncClient", lambda **kw: FakeClient()), \
         mock.patch.object(sa, "SUPABASE_URL", "https://x"), \
         mock.patch.object(sa, "_service_headers", lambda extra=None: {}):
        sa._biz_cache.clear()
        asyncio.run(sa.track(ev, Req(origin), user_agent=ua, dnt=dnt))
    return posted


def test_a_customer_site_view_is_stored_against_that_business():
    out = _track({"s": "sess1", "p": "/services", "b": BIZ, "d": "mobile"})
    assert out["business_id"] == BIZ
    assert out["path"] == "/services"


def test_the_marketing_site_still_stores_a_null_business():
    """Every row written before today looks like this, and /admin/traffic
    reads exactly these."""
    out = _track({"s": "sess1", "p": "/features"})
    assert out["business_id"] is None


def test_an_unknown_business_id_is_stored_as_null_not_rejected():
    """The id is baked into a page anyone can view-source. A junk value
    must not create rows under a business that does not exist — and must
    not 500 a tracking beacon on somebody's website either."""
    out = _track({"s": "s", "p": "/", "b": BIZ}, business_exists=False)
    assert out["business_id"] is None
    assert out["path"] == "/"          # the view is still counted


def test_a_malformed_business_id_never_reaches_the_database():
    out = _track({"s": "s", "p": "/", "b": "'; drop table--"})
    assert out["business_id"] is None


def test_an_internal_click_is_not_a_referral():
    """Page-to-page inside the same site. Counting it makes every site
    its own top traffic source — and the old rule only knew how to
    exclude mysolutionist.app."""
    out = _track({"s": "s", "p": "/pricing", "b": BIZ,
                  "r": "https://barber.example/services"},
                 origin="https://barber.example")
    assert out["referrer_host"] is None


def test_a_real_referral_survives():
    out = _track({"s": "s", "p": "/", "b": BIZ,
                  "r": "https://www.google.com/search?q=barber+near+me"},
                 origin="https://barber.example")
    assert out["referrer_host"] == "www.google.com"


def test_the_referrer_is_only_ever_a_host():
    """Full referrer URLs routinely carry search terms."""
    out = _track({"s": "s", "p": "/", "b": BIZ,
                  "r": "https://www.google.com/search?q=bankruptcy+lawyer"})
    assert out["referrer_host"] == "www.google.com"
    assert "bankruptcy" not in repr(out)


def test_do_not_track_writes_nothing_at_all():
    assert _track({"s": "s", "p": "/", "b": BIZ}, dnt="1") == {}


def test_a_bot_writes_nothing_at_all():
    assert _track({"s": "s", "p": "/", "b": BIZ}, ua="Googlebot/2.1") == {}


def test_the_query_string_is_dropped_before_storage():
    out = _track({"s": "s", "p": "/thanks?email=someone%40example.com", "b": BIZ})
    assert out["path"] == "/thanks"
    assert "example.com" not in repr(out)


def test_the_admin_read_is_still_only_the_marketing_site():
    """Without the business_id filter this endpoint would silently start
    reporting every customer's traffic as Kevin's own."""
    import inspect
    src = inspect.getsource(sa.traffic_summary)
    assert '"business_id": "is.null"' in src


# ═══════════════════════════════════════════════════════════════════════
# The per-business read
# ═══════════════════════════════════════════════════════════════════════

def _summary(events, leads):
    class FakeResp:
        def __init__(self, payload): self.status_code = 200; self._p = payload; self.text = ""
        def json(self): return self._p

    calls = []

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw):
            calls.append((url, kw.get("params") or {}))
            return FakeResp(leads if "contacts" in url else events)

    user = type("U", (), {"id": "owner-1"})()
    with mock.patch.object(sa.httpx, "AsyncClient", lambda **kw: FakeClient()), \
         mock.patch.object(sa, "SUPABASE_URL", "https://x"), \
         mock.patch.object(sa, "_service_headers", lambda extra=None: {}), \
         mock.patch.object(sa, "_require_business_access", lambda b, u: {"id": b}):
        out = asyncio.run(sa.business_traffic(BIZ, days=30, user=user))
    return out, calls


def view(sid, path="/", ref=None, dev="desktop"):
    return {"ts": "2026-08-14T10:00:00Z", "session_id": sid, "path": path,
            "referrer_host": ref, "device": dev, "event": "view"}


def test_conversion_is_leads_over_SESSIONS_not_views():
    """One person reading four pages is one chance to convert, not four.
    A per-view rate would FALL every time the site got more engaging."""
    events = [view("a", "/"), view("a", "/about"), view("a", "/pricing"),
              view("a", "/contact"), view("b", "/")]
    out, _ = _summary(events, [{"id": "c1", "created_at": "x", "source": "website_contact_form"}])
    assert out["views"] == 5
    assert out["sessions"] == 2
    assert out["conversion_pct"] == 50.0


def test_no_visitors_reports_none_not_zero_percent():
    """0% would read as 'this site converts nothing'. No visitors is the
    absence of a rate, not a rate of zero."""
    out, _ = _summary([], [])
    assert out["conversion_pct"] is None
    assert out["sessions"] == 0


def test_the_read_is_scoped_to_one_business():
    out, calls = _summary([view("a")], [])
    ev_params = [p for u, p in calls if "site_events" in u][0]
    assert ev_params["business_id"] == f"eq.{BIZ}"


def test_leads_are_counted_from_every_door():
    """The whole finding of the lead arc was surfaces that counted one
    door out of five."""
    out, calls = _summary(
        [view("a"), view("b")],
        [{"id": "1", "created_at": "x", "source": "website_contact_form"},
         {"id": "2", "created_at": "x", "source": "site_concierge"},
         {"id": "3", "created_at": "x", "source": "booking_widget"}])
    lead_params = [p for u, p in calls if "contacts" in u][0]
    assert "source" not in lead_params            # not filtered to one door
    assert out["leads"] == 3
    assert {d["source"] for d in out["lead_sources"]} == {
        "website_contact_form", "site_concierge", "booking_widget"}


def test_top_paths_and_referrers_come_back():
    events = [view("a", "/", "google.com"), view("b", "/", "google.com"),
              view("c", "/pricing", "reddit.com")]
    out, _ = _summary(events, [])
    assert out["top_paths"][0] == {"path": "/", "views": 2}
    assert out["referrers"][0] == {"host": "google.com", "views": 2}


def test_a_truncated_window_says_so():
    out, _ = _summary([view(str(i)) for i in range(sa.MAX_ROWS)], [])
    assert out["truncated"] is True


def test_the_endpoint_is_not_gated_to_the_platform_owner():
    """This is the practitioner's own site; Kevin is not the audience.
    /admin/traffic keeps its PLATFORM_OWNER_EMAIL gate."""
    import inspect
    src = inspect.getsource(sa.business_traffic)
    assert "require_owner" not in src
    assert "_require_business_access" in src


# ═══════════════════════════════════════════════════════════════════════
# how_heard — shipped on the templates since the beginning, read by
# nothing
# ═══════════════════════════════════════════════════════════════════════

def test_what_they_said_sent_them_is_finally_recorded():
    a = la.capture(Req(), submission={"name": "Jo", "how_heard": "Friend"})
    assert a["self_reported"] == "Friend"


def test_every_spelling_a_practitioner_might_use():
    for key in ("how_heard", "how_did_you_hear_about_us", "referral_source",
                "heard_about_us", "how_found_us"):
        assert la.self_reported_source({key: "Drive-by"}) == "Drive-by"


def test_a_non_answer_is_not_an_answer():
    """'Other' and an unselected placeholder say nothing, and recording
    them as a source would put 'Other' at the top of a report."""
    for junk in ("Other", "other", "n/a", "none", "Select...", "-", ""):
        assert la.self_reported_source({"how_heard": junk}) is None


def test_it_reaches_the_funnel():
    a = la.capture(Req(), submission={"how_heard": "Google"})
    assert la.event_fields(a)["self_reported"] == "Google"


def test_it_sits_beside_the_measured_signals_not_instead_of_them():
    """'Friend' and utm_source=google are both true when somebody
    googles a name a friend gave them."""
    class R2:
        headers = {"referer": "https://x.example/?utm_source=google"}
    a = la.capture(R2(), submission={"how_heard": "Friend"})
    assert a["utm_source"] == "google"
    assert a["self_reported"] == "Friend"


def test_the_intake_door_passes_its_submission():
    import inspect

    import intake_endpoint
    src = inspect.getsource(intake_endpoint.submit_intake)
    assert "submission=submission_data" in src
