"""A tap on a post's link, followed to the booking (2026-10-09).

The Reach plan's step 1: results that follow a tap to a booking and its
payment. A desk post's /go/{code} link lands on the business's hosted
/book page with utm_content=<post id>. Before this:

  * /book carried no page-view beacon, so the visit was never counted and
    the campaign tags were never kept for the tab;
  * the booking widget posted cross-origin with no attribution, and the
    browser's Referer is only the origin, so the tags were dropped;
  * only a NEW contact kept attribution; the booking itself never did.

Now the beacon rides /book, the widget sends the tags it kept
(BookAnonBody/BookBody.attribution), and the booking keeps the server's
reading of them in data.attribution, which business_marketing_outcomes
counts (and its payment with it, once paid_at is set).
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import booking_widget_router as bw  # noqa: E402
import public_site  # noqa: E402

POST = "5f0c8a52-4c2e-4c8a-9a51-0c1d2e3f4a5b"
BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"


class Req:
    def __init__(self, referer=None, ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"):
        self.headers = {"user-agent": ua}
        if referer:
            self.headers["referer"] = referer


def test_the_widget_tags_are_kept_when_the_referer_is_only_the_origin():
    got = bw.booking_attribution(Req("https://fade-street.mysolutionist.app/"),
                                 {"utm_content": POST, "utm_source": "social", "utm_medium": "organic_social",
                                  "password": "nope", "email": "x@y.z"})
    assert got["utm_content"] == POST and got["utm_source"] == "social" and got["utm_medium"] == "organic_social"
    assert "password" not in got and "email" not in got            # only lead_attribution's whitelist
    assert got["source_detail"] == "booking"


def test_the_page_address_wins_over_what_the_widget_says():
    got = bw.booking_attribution(Req(f"https://fade-street.mysolutionist.app/book?utm_content={POST}"),
                                 {"utm_content": "something-else"})
    assert got["utm_content"] == POST


def test_nothing_sent_and_no_tags_records_no_campaign():
    got = bw.booking_attribution(Req("https://fade-street.mysolutionist.app/book"), None)
    assert "utm_content" not in got
    got = bw.booking_attribution(Req(), "not an object")
    assert "utm_content" not in got


def test_the_booking_keeps_the_servers_reading_never_the_forms():
    data = {"service": "Fade", "attribution": {"utm_content": "forged"}}
    kept = bw._with_attribution(dict(data), {"utm_content": POST, "source_detail": "booking"})
    assert kept["attribution"] == {"utm_content": POST, "source_detail": "booking"} and kept["service"] == "Fade"
    assert "attribution" not in bw._with_attribution(dict(data), {})


def test_both_booking_doors_record_where_the_booking_came_from():
    src = (pathlib.Path(bw.__file__)).read_text(encoding="utf-8")
    anon = src[src.index("async def book_anon("):src.index('@router.post("/widgets/booking/{business_id}/book")')]
    authed = src[src.index("async def book("):]
    assert "attribution = booking_attribution(request, body.attribution)" in anon
    assert "_with_attribution(dict(body.data), attribution)" in anon
    assert "_with_attribution(dict(body.data), booking_attribution(request, body.attribution))" in authed[:3000]
    assert "attribution" in bw.BookAnonBody.model_fields and "attribution" in bw.BookBody.model_fields


def test_the_hosted_booking_page_carries_the_visit_beacon(monkeypatch):
    business = {"id": BIZ, "name": "Fade Street", "settings": {"booking_page": {"published": True}}}

    async def service(client, path):
        return [business]

    monkeypatch.setattr(public_site, "_sb_service", service)
    monkeypatch.delenv("SITE_TRAFFIC", raising=False)
    page = asyncio.run(public_site._serve_booking_page(None, BIZ, "fade-street"))
    html = page.body.decode("utf-8")
    assert "sol_sid" in html and "sol_c" in html and BIZ in html     # counts the visit, keeps the tags
    assert html.count("var K='sol_sid'") == 1                         # stamped once
    assert html.index("sol_sid") < html.index("</body>")


def test_an_unpublished_booking_page_has_no_beacon(monkeypatch):
    business = {"id": BIZ, "name": "Fade Street", "settings": {"booking_page": {"published": False}}}

    async def service(client, path):
        return [business]

    monkeypatch.setattr(public_site, "_sb_service", service)
    page = asyncio.run(public_site._serve_booking_page(None, BIZ, "fade-street"))
    assert page.status_code == 404 and "sol_sid" not in page.body.decode("utf-8")
