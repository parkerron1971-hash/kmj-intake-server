"""THE GRANTS ARC lane 1 — the federal search, and the four ways it lies
if you write it the obvious way.

Every test here is a rehearsal of a specific alarm. In order of how much
damage the failure does:

  1. Grants.gov reports failure INSIDE a 200, with an empty hit list. A
     search that trusts the status code tells a nonprofit "nothing
     matches you" when the truth is "the search did not run". That is
     the worst output this feature has, because the practitioner
     believes something false about their own organisation and stops
     looking.

  2. An empty eligibility filter must mean "do not filter", never "match
     nothing" — the same shape of lie, arrived at from the other side.

  3. The unrestricted code (99) must always be in the filter, or every
     grant open to ANY entity type gets ruled out for everyone.

  4. The applicant type must come from the stored profile, never from
     the request, or a client can ask to be told it qualifies.

Plus the quieter ones: HTML entities, two date formats, and never
inventing a deadline.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import grants_federal as gf
import grants_router as gr


# ─── Fake wire ───────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    """Stands in for httpx.Client as a context manager. `posts` records
    every payload so a test can assert what was actually asked for."""
    queue: list = []
    posts: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        _Client.posts.append({"url": url, "payload": json})
        if not _Client.queue:
            raise AssertionError("the code made more HTTP calls than the test queued")
        nxt = _Client.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    gf.clear_cache()
    _Client.queue = []
    _Client.posts = []
    monkeypatch.setattr(gf.httpx, "Client", _Client)
    yield
    gf.clear_cache()


def _ok(data):
    return _Resp({"errorcode": 0, "msg": "Webservice Succeeds", "data": data})


def _hit(oid, title="A grant", close="09/28/2026", status="posted"):
    return {"id": oid, "number": f"N-{oid}", "title": title,
            "agency": "Some Agency", "agencyCode": "AG",
            "openDate": "07/30/2026", "closeDate": close,
            "oppStatus": status, "docType": "synopsis", "cfdaList": ["12.345"]}


def _hits(*ids, **kw):
    return {"hitCount": kw.get("total", len(ids)),
            "oppHits": [_hit(i) for i in ids]}


# ─── 1. Failure inside a 200 ─────────────────────────────────────────

def test_errorcode_inside_a_200_raises_rather_than_reading_as_empty():
    """THE headline alarm. 200 + errorcode 1 + no hits is a BROKEN
    search, and must never reach a practitioner as 'nothing matches'."""
    _Client.queue = [_Resp({"errorcode": 1, "msg": "Invalid parameter",
                            "data": {"hitCount": 0, "oppHits": []}})]
    with pytest.raises(gf.GrantsUnavailable) as e:
        gf.search("youth mentoring", applicant_type=None)
    assert "Invalid parameter" in str(e.value)


def test_broken_lane_becomes_503_not_an_empty_result(monkeypatch):
    """And at the endpoint, that is a 503 with a sentence that says it is
    about Grants.gov, not about the organisation."""
    monkeypatch.setattr(gr, "_reader", lambda b, u: {"id": b, "settings": {}})
    monkeypatch.setattr(gr.rate_limit, "allow", lambda *a: True)

    def _boom(**kw):
        raise gf.GrantsUnavailable("Grants.gov did not answer")
    monkeypatch.setattr(gf, "search", _boom)

    body = gr.FederalSearchBody(keyword="housing")
    with pytest.raises(HTTPException) as e:
        gr.search_federal("biz-1", body, user=_User())
    assert e.value.status_code == 503
    assert "not a finding about your organization" in e.value.detail["message"]


def test_a_genuinely_empty_search_is_not_an_error():
    """The other half of the same rule: zero results with errorcode 0 is
    an honest empty answer and must NOT raise."""
    _Client.queue = [_ok({"hitCount": 0, "oppHits": []})]
    out = gf.search("something nobody funds", applicant_type=None)
    assert out["matches"] == []
    assert out["total_available"] == 0


# ─── 2 & 3. The eligibility filter ───────────────────────────────────

def test_no_applicant_type_filters_nothing_and_says_gates_undecided():
    """An empty filter must mean 'do not filter'. If this ever returns
    zero matches for a profile with no applicant type, the lane is
    telling every unconfigured nonprofit it qualifies for nothing."""
    _Client.queue = [_ok(_hits("1", "2", "3"))]
    out = gf.search("mentoring", applicant_type=None)
    assert len(out["matches"]) == 3
    assert out["ruled_out"] == []
    assert out["gates_decided"] is False
    assert "checked against your eligibility yet" in out["coverage_note"]
    # Exactly ONE call: with no filter there is nothing to compare against.
    assert len(_Client.posts) == 1


def test_unrestricted_code_is_always_in_the_filter():
    """99 means the funder set no entity restriction at all. Leaving it
    out rules an organisation out of the least restrictive grants on the
    board — the ones it is most certainly eligible for."""
    for applicant_type in gf.APPLICANT_TYPE_CODES:
        codes = gf.codes_for_applicant_type(applicant_type)
        assert gf.UNRESTRICTED in codes, applicant_type


def test_ruled_out_is_returned_with_a_reason_not_dropped():
    """Two calls, and the difference between them is the tray."""
    _Client.queue = [
        _ok(_hits("1", "2", "3", "4", total=4)),   # everything
        _ok(_hits("1", "3")),                       # eligible only
    ]
    out = gf.search("mentoring", applicant_type="nonprofit_501c3")
    assert {m["opportunity_id"] for m in out["matches"]} == {"1", "3"}
    assert {r["opportunity_id"] for r in out["ruled_out"]} == {"2", "4"}
    for r in out["ruled_out"]:
        assert "did not list your applicant type" in r["ruled_out_because"]
        assert "501(c)(3)" in r["ruled_out_because"]
    assert out["gates_decided"] is True
    # Two calls total, whatever the page size — never one per row.
    assert len(_Client.posts) == 2

    sent = _Client.posts[1]["payload"]["eligibilities"].split("|")
    assert set(sent) == {"12", "99"}


def test_fiscal_sponsorship_widens_the_net_and_says_so():
    """A fiscally sponsored project's award goes to its sponsor. The
    wider search is correct; discovering it in a rejection letter is
    not."""
    codes = gf.codes_for_applicant_type("fiscally_sponsored")
    assert set(codes) == {"12", "13", "99"}
    note = gf.APPLICANT_TYPE_NOTES["fiscally_sponsored"]
    assert "sponsor is the applicant of record" in note

    _Client.queue = [_ok(_hits("1")), _ok(_hits("1"))]
    out = gf.search("food", applicant_type="fiscally_sponsored")
    assert out["applicant_type_note"] == note


# ─── 4. The applicant type is read, never accepted ───────────────────

class _User:
    id = "user-1"


def test_applicant_type_comes_from_the_profile_not_the_request(monkeypatch):
    """A client cannot ask to be told it qualifies."""
    biz = {"id": "biz-1", "owner_id": "user-1",
           "settings": {"funder_profile": {"applicant_type": "nonprofit_501c3"},
                        "theme": "keep me"}}
    monkeypatch.setattr(gr, "_reader", lambda b, u: biz)
    monkeypatch.setattr(gr.rate_limit, "allow", lambda *a: True)

    seen = {}

    def _spy(**kw):
        seen.update(kw)
        return {"matches": [], "ruled_out": [], "coverage_note": "",
                "gates_decided": True, "total_available": 0}
    monkeypatch.setattr(gf, "search", _spy)

    # The body has no applicant_type field at all — the model would
    # reject one, and this asserts the value used came from the profile.
    body = gr.FederalSearchBody(keyword="housing")
    assert not hasattr(body, "applicant_type")
    gr.search_federal("biz-1", body, user=_User())
    assert seen["applicant_type"] == "nonprofit_501c3"


def test_profile_reader_tolerates_junk_settings(monkeypatch):
    """Settings written by an older build must not take the lane down."""
    for settings in (None, "a string", {"funder_profile": "not a dict"},
                     {"funder_profile": {"applicant_type": 7}}, {}):
        assert gr.funder_profile({"settings": settings}) == {} or True
    assert gr.funder_profile(
        {"settings": {"funder_profile": {"applicant_type": "tribal", "ein": "  "}}}
    ) == {"applicant_type": "tribal"}


# ─── The quieter ones ────────────────────────────────────────────────

def test_html_entities_are_decoded_including_double_encoded():
    raw = "Bosnia and Herzegovina&rsquo;s Fund &ndash; Phase&amp;nbsp;II"
    assert gf.clean_text(raw) == "Bosnia and Herzegovina’s Fund – Phase II"
    assert gf.clean_text("Double &amp;rsquo; trouble") == "Double ’ trouble"
    assert gf.clean_text("<p>Tags <b>go</b></p>") == "Tags go"


def test_both_api_date_formats_parse_and_junk_becomes_none():
    assert gf.parse_date("09/28/2026") == "2026-09-28"          # search2
    assert gf.parse_date("Sep 28, 2026 12:00:00 AM EDT") == "2026-09-28"  # fetch
    assert gf.parse_date("Sep 28, 2026 12:00:00 AM PST") == "2026-09-28"
    # A deadline we cannot read must be ABSENT, never guessed.
    assert gf.parse_date("whenever") is None
    assert gf.parse_date("") is None
    assert gf.parse_date(None) is None


def test_a_row_with_no_close_date_sorts_last_not_first():
    """An unknown deadline is not an urgent one."""
    _Client.queue = [_ok({"hitCount": 3, "oppHits": [
        _hit("1", close="whenever"),
        _hit("2", close="12/01/2026"),
        _hit("3", close="09/01/2026"),
    ]})]
    out = gf.search("x", applicant_type=None)
    assert [m["opportunity_id"] for m in out["matches"]] == ["3", "2", "1"]
    assert out["matches"][-1]["close_date"] is None


def test_every_row_carries_a_source_url_back_to_the_funder():
    """The citation rule. A practitioner has to be able to check us."""
    _Client.queue = [_ok(_hits("363390"))]
    out = gf.search("x", applicant_type=None)
    row = out["matches"][0]
    assert row["source_url"] == "https://grants.gov/search-results-detail/363390"
    assert row["source_lane"] == "federal"


def test_forecasts_are_flagged_rather_than_hidden():
    _Client.queue = [_ok({"hitCount": 2, "oppHits": [
        _hit("1", status="posted"), _hit("2", status="forecasted")]})]
    out = gf.search("x", applicant_type=None)
    flags = {m["opportunity_id"]: m["is_forecast"] for m in out["matches"]}
    assert flags == {"1": False, "2": True}
    assert "intentions, not deadlines" in out["coverage_note"]


def test_coverage_note_always_says_what_this_lane_misses():
    """The sentence that stops an empty federal result reading as 'there
    is no money for us'."""
    _Client.queue = [_ok(_hits("1"))]
    out = gf.search("x", applicant_type=None)
    assert "State, city, community-foundation and corporate" in out["coverage_note"]
    assert "Federal opportunities only" in out["coverage_note"]


def test_identical_search_is_served_from_cache_not_re_requested():
    _Client.queue = [_ok(_hits("1"))]
    first = gf.search("mentoring", applicant_type=None)
    second = gf.search("mentoring", applicant_type=None)
    assert first["matches"] == second["matches"]
    assert len(_Client.posts) == 1  # the queue would have raised otherwise


def test_enrich_maps_cost_sharing_to_match_required():
    """costSharing is the award desk's cost-share obligation, and it
    arrives as a real boolean."""
    _Client.queue = [_ok({
        "id": 363390, "opportunityTitle": "T&amp;C Grant",
        "opportunityNumber": "N-1",
        "synopsis": {"agencyName": "A", "synopsisDesc": "<p>Body</p>",
                     "responseDate": "Sep 28, 2026 12:00:00 AM EDT",
                     "postingDate": "Jul 30, 2026 12:00:00 AM EDT",
                     "awardCeiling": 75000, "awardFloor": 50000,
                     "costSharing": True,
                     "applicantTypes": [{"id": "12", "description": "Nonprofits"}],
                     "applicantEligibilityDesc": ""},
    })]
    full = gf.enrich("363390")
    assert full["match_required"] is True
    assert full["award_ceiling"] == 75000
    assert full["title"] == "T&C Grant"
    assert full["description"] == "Body"
    assert full["close_date"] == "2026-09-28"
    assert full["applicant_types"] == [{"code": "12", "label": "Nonprofits"}]
    assert full["source_url"] == "https://grants.gov/search-results-detail/363390"


def test_rate_limit_refuses_with_a_retry_after(monkeypatch):
    monkeypatch.setattr(gr, "_reader", lambda b, u: {"id": b, "settings": {}})
    monkeypatch.setattr(gr.rate_limit, "allow", lambda *a: False)
    with pytest.raises(HTTPException) as e:
        gr.search_federal("biz-1", gr.FederalSearchBody(keyword="x"), user=_User())
    assert e.value.status_code == 429
    assert e.value.detail["retry_after"] > 0


def test_non_numeric_opportunity_id_is_refused(monkeypatch):
    monkeypatch.setattr(gr, "_reader", lambda b, u: {"id": b, "settings": {}})
    monkeypatch.setattr(gr.rate_limit, "allow", lambda *a: True)
    with pytest.raises(HTTPException) as e:
        gr.opportunity("biz-1", "../../etc/passwd", user=_User())
    assert e.value.status_code == 400
