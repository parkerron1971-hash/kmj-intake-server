"""The booking page's texts boxes in the business's own name (ISV step 3, 2026-10-11).

Once a business's texting registration is with Twilio, its reviewers read
the booking page's consent boxes, which must name the business word for word
as its campaign quotes them. Pinned here:
  1. Before the registration is sent (or when it can't be read) the payload
     has no `texting` key, so the boxes read exactly as before.
  2. Once sent, the payload carries both boxes in the business's name and its
     own texting pages, from the same functions that write the campaign.
  3. The shipped widget bundle reads them.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import booking_widget_router as bwr  # noqa: E402
import texting_registration as tr  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
ORIGIN = "https://northside.mysolutionist.app"
BUSINESS = {"id": BIZ, "name": "Northside Cuts", "settings": {}}


@pytest.fixture
def reg(monkeypatch):
    state = {"row": None, "origin": ORIGIN}
    monkeypatch.setattr(tr, "registration", lambda bid: state["row"])
    monkeypatch.setattr(tr, "site_origin", lambda bid: state["origin"])
    return state


def test_before_its_sent_the_boxes_read_as_before(reg):
    for row in (None, {"status": "draft"}, {"status": "failed", "twilio": {}}):
        reg["row"] = row
        assert bwr._texting_words(BUSINESS) is None, row


@pytest.mark.parametrize("row", [
    {"status": "submitted"}, {"status": "brand_pending"}, {"status": "campaign_pending"}, {"status": "approved"},
    {"status": "failed", "twilio": {"profile_submitted": True}},          # sent back: still with Twilio
])
def test_once_sent_the_boxes_name_the_business_as_its_campaign_quotes_them(reg, row):
    reg["row"] = row
    words = bwr._texting_words(BUSINESS)
    assert words == {"booking_box": tr.booking_box("Northside Cuts"), "offers_box": tr.offers_box("Northside Cuts"),
                     "terms": f"{ORIGIN}/texting-terms", "privacy": f"{ORIGIN}/texting-privacy"}
    flow = tr.campaign_words("Northside Cuts", ORIGIN)["message_flow"]
    assert f'"{words["booking_box"]}"' in flow and f'"{words["offers_box"]}"' in flow    # word for word
    assert "Solutionist" not in words["booking_box"] + words["offers_box"]


def test_an_unreadable_registration_never_half_switches(reg, monkeypatch):
    def boom(bid):
        raise RuntimeError("read failed")

    monkeypatch.setattr(tr, "registration", boom)
    assert bwr._texting_words(BUSINESS) is None
    reg["origin"] = None
    monkeypatch.setattr(tr, "registration", lambda bid: {"status": "approved"})
    assert bwr._texting_words(BUSINESS) is None                                   # no site: no pages to link


def test_the_payload_carries_them_only_once_sent(reg, monkeypatch):
    monkeypatch.setattr(bwr, "_offerings_for_widget_fields", lambda b, f: [])
    monkeypatch.setattr(bwr, "_slots_per_offering", lambda b, o: {})
    module = {"id": "m1", "name": "Appointments", "schema": {"fields": []}}
    assert "texting" not in bwr._config_payload(BUSINESS, module)
    reg["row"] = {"status": "brand_pending"}
    assert bwr._config_payload(BUSINESS, module)["texting"]["booking_box"].endswith("HELP for help.")


def test_the_shipped_widget_reads_them():
    bundle = pathlib.Path(bwr.__file__).resolve().parent.joinpath("static", "embed.js").read_text(encoding="utf-8")
    assert ".texting.booking_box" in bundle and ".texting.offers_box" in bundle
    assert "from Solutionist System. Not required to book." in bundle                   # the old words, still the default
