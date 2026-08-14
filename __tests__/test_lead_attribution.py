"""
test_lead_attribution.py — THE LEAD ARC PR 6.

WebsiteTraffic.tsx:188 computes a form's top traffic source as

    ev.data?.utm_source || ev.data?.referrer_host || ev.data?.referrer
                                                  || 'direct'

and nothing wrote any of the three, so every form reported 'direct'
forever. Those three key names are a CONTRACT with the frontend, and
half of this file is about not breaking it.

The other half is privacy. This reads a query string off somebody
else's page, which can contain anything at all.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import lead_attribution as la  # noqa: E402


class Req:
    def __init__(self, referer=None, ua=None):
        self.headers = {}
        if referer:
            self.headers["referer"] = referer
        if ua:
            self.headers["user-agent"] = ua


UA_DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
UA_PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
UA_TABLET = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"


# ═══════════════════════════════════════════════════════════════════════
# The header does the work
# ═══════════════════════════════════════════════════════════════════════

def test_campaign_comes_off_the_referring_page_with_no_client_help():
    """The whole design. The contact form is emitted by four renderers
    plus whatever the builder's LLM writes; anything needing the client
    to cooperate would be partially deployed forever."""
    out = la.capture(Req(
        "https://barbershop.example/book?utm_source=google&utm_medium=cpc"
        "&utm_campaign=spring_fades"))
    assert out["utm_source"] == "google"
    assert out["utm_medium"] == "cpc"
    assert out["utm_campaign"] == "spring_fades"


def test_the_landing_page_is_recorded_without_its_query():
    out = la.capture(Req("https://x.example/services/beard?utm_source=ig"))
    assert out["landing_path"] == "/services/beard"
    assert out["landing_host"] == "x.example"
    assert "?" not in out["landing_path"]


def test_device_class_from_the_user_agent():
    assert la.capture(Req(ua=UA_PHONE))["device"] == "mobile"
    assert la.capture(Req(ua=UA_TABLET))["device"] == "tablet"
    assert la.capture(Req(ua=UA_DESKTOP))["device"] == "desktop"


def test_ad_click_ids_are_kept():
    out = la.capture(Req("https://x.example/?gclid=abc123&fbclid=zzz"))
    assert out["gclid"] == "abc123"
    assert out["fbclid"] == "zzz"


# ═══════════════════════════════════════════════════════════════════════
# Privacy — this reads a query string off somebody else's page
# ═══════════════════════════════════════════════════════════════════════

def test_nothing_outside_the_whitelist_is_stored():
    """A query string on a referring page can contain an email address,
    a session token, a password-reset link. None of that belongs in a
    contacts row because a marketing report wanted to know about ads."""
    out = la.capture(Req(
        "https://x.example/reset?token=SECRET&email=someone%40example.com"
        "&ssn=123-45-6789&utm_source=news"))
    assert out["utm_source"] == "news"
    blob = repr(out)
    for leak in ("SECRET", "someone@example.com", "123-45-6789", "token", "ssn"):
        assert leak not in blob, f"{leak} survived into {blob}"


def test_a_referrer_is_reduced_to_a_host():
    """site_analytics already states the reason: full referrer URLs leak
    search terms."""
    out = la.capture(Req(), {"attribution": {
        "referrer": "https://www.google.com/search?q=divorce+lawyer+near+me"}})
    assert out["referrer_host"] == "www.google.com"
    assert "divorce" not in repr(out)


def test_a_client_supplied_landing_path_loses_its_query_too():
    out = la.capture(Req(), {"attribution": {
        "landing_path": "/intake?token=SECRET#frag"}})
    assert out["landing_path"] == "/intake"


def test_everything_is_length_capped():
    out = la.capture(Req(f"https://x.example/{'a' * 900}?utm_source={'b' * 900}"))
    assert len(out["utm_source"]) <= la.MAX_VALUE
    assert len(out["landing_path"]) <= la.MAX_PATH


# ═══════════════════════════════════════════════════════════════════════
# The client may add, never break
# ═══════════════════════════════════════════════════════════════════════

def test_a_client_can_supply_what_the_header_cannot():
    """document.referrer — the site they came FROM — is the one signal
    a header does not carry."""
    out = la.capture(Req("https://mine.example/contact"),
                     {"attribution": {"referrer": "https://reddit.com/r/x"}})
    assert out["referrer_host"] == "reddit.com"
    assert out["landing_host"] == "mine.example"


def test_the_header_wins_over_the_client_for_campaign():
    """The client's copy is a convenience; the header is what the
    browser observed."""
    out = la.capture(Req("https://x.example/?utm_source=google"),
                     {"attribution": {"utm_source": "someone_elses_claim"}})
    assert out["utm_source"] == "google"


def test_our_own_page_is_not_recorded_as_the_referrer():
    """Otherwise every lead is 'referred by' the site they were already
    on, and the funnel says the site refers itself."""
    out = la.capture(Req("https://mine.example/contact"),
                     {"attribution": {"referrer": "https://mine.example/pricing"}})
    assert "referrer_host" not in out


def test_a_garbage_body_cannot_break_a_capture():
    for junk in (None, {}, {"attribution": "not a dict"},
                 {"attribution": {"referrer": 12345}},
                 {"attribution": {"utm_source": None}}):
        assert isinstance(la.capture(Req("https://x.example/"), junk), dict)


def test_a_broken_request_object_cannot_break_a_capture():
    class Exploding:
        @property
        def headers(self):
            raise RuntimeError("boom")
    assert la.capture(Exploding()) == {}
    assert la.capture(None) == {}


def test_nothing_to_record_returns_empty_not_a_shell_of_nulls():
    """So the caller stores NULL rather than an object full of nulls
    that reads like a lookup that ran and failed."""
    assert la.capture(Req()) == {}


# ═══════════════════════════════════════════════════════════════════════
# The contract with WebsiteTraffic.tsx
# ═══════════════════════════════════════════════════════════════════════

def test_event_fields_use_the_exact_names_the_funnel_reads():
    """WebsiteTraffic.tsx:188 looks for utm_source, then referrer_host,
    then referrer. Renaming any of these here silently returns that page
    to reporting 'direct' for every form."""
    attribution = la.capture(
        Req("https://x.example/p?utm_source=google&utm_campaign=c", UA_PHONE),
        {"attribution": {"referrer": "https://news.example/story"}})
    fields = la.event_fields(attribution)
    assert fields["utm_source"] == "google"
    assert fields["referrer_host"] == "news.example"
    assert fields["utm_campaign"] == "c"
    assert fields["device"] == "mobile"


def test_event_fields_omit_what_is_missing():
    """An empty string would beat 'direct' in the frontend's `||` chain
    — no, actually it would not, but a literal 'None' string would, and
    that is the shape of mistake worth guarding."""
    fields = la.event_fields(la.capture(Req(ua=UA_DESKTOP)))
    assert "utm_source" not in fields
    assert fields == {"device": "desktop"}


def test_event_fields_survive_nothing():
    assert la.event_fields(None) == {}
    assert la.event_fields({}) == {}


# ═══════════════════════════════════════════════════════════════════════
# source_detail — the column three frontend files use and none had
# ═══════════════════════════════════════════════════════════════════════

def test_an_explicit_label_wins():
    """The funnel groups per-form conversion by this and shows it to the
    practitioner, so a form's own name beats a URL path."""
    a = la.capture(Req("https://x.example/contact"))
    assert la.detail_for(a, "Discovery Call") == "Discovery Call"


def test_the_landing_page_is_the_fallback():
    """Better than nothing: it says which page of their site the person
    was reading when they decided to get in touch."""
    a = la.capture(Req("https://x.example/services/roofing"))
    assert la.detail_for(a) == "/services/roofing"


def test_no_signal_at_all_is_none_not_an_empty_string():
    assert la.detail_for({}, None) is None
    assert la.detail_for(None) is None


# ═══════════════════════════════════════════════════════════════════════
# Every door writes it
# ═══════════════════════════════════════════════════════════════════════

DOORS = {
    "intake_endpoint.py": "attribution = lead_attribution.capture(",
    "public_site.py": "attribution = lead_attribution.capture(",
    "site_concierge.py": "attribution=lead_attribution.capture(",
    "booking_widget_router.py": "attribution=lead_attribution.capture(",
}


def test_all_four_doors_capture_attribution():
    root = pathlib.Path(__file__).resolve().parent.parent
    for filename, needle in DOORS.items():
        src = (root / filename).read_text(encoding="utf-8")
        assert needle in src, f"{filename} does not capture attribution"


def test_all_four_doors_write_source_detail():
    root = pathlib.Path(__file__).resolve().parent.parent
    for filename in DOORS:
        src = (root / filename).read_text(encoding="utf-8")
        assert "lead_attribution.detail_for(" in src, filename
        assert '"source_detail"' in src, filename
