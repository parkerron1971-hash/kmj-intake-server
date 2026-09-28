"""EIN prep and the prefilled SS-4 — the owner's facts in, never an SSN,
never a tax determination, never a submission.

No test here touches the network: the SS-4 blank is a locally built
AcroForm carrying the real form's field names (see test_irs_forms)."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import ein_prep
import irs_forms
from test_irs_forms import _acroform, _no_network  # noqa: F401  (autouse guard)

IDENT = {
    "legal_name": "KMJ Creative Solutions LLC", "legal_name_is_fallback": False,
    "entity_type": "single_member_llc", "formation_state": "MI", "formed_on": "2025-03-14",
    "address_line1": "123 Example St", "address_city": "Detroit", "address_state": "MI",
    "address_zip": "48201", "phone": "(231) 555-0100",
}
PP = {"full_legal_name": "Kevin McCloud Jr.", "preferred_title": "Founder/Owner",
      # Even if a row ever carried one, it must never travel anywhere.
      "ssn": "123-45-6789"}
BP = {"business_subtype": "Faith-driven business coaching (90-day intensives)"}


def _blank_ss4() -> bytes:
    return _acroform([
        (name, "/Btn" if key in ("llc_yes", "llc_no", "llc_in_us") else "/Tx")
        for key, name in irs_forms.SS4_FIELDS.items()
    ])


# ── The SS-4 values ──────────────────────────────────────────────────

def test_a_single_member_llc_answers_8a_8b_8c_with_the_verified_on_states():
    v = irs_forms.ss4_values(IDENT, PP, "KMJ Creative Solutions", BP)
    # /1 is Yes on both pairs — confirmed by rendering the live form.
    assert v["llc_yes"] == irs_forms.SS4_YES == "/1"
    assert v["llc_members"] == "1"
    assert v["llc_in_us"] == "/1"
    assert "llc_no" not in v
    assert v["legal_name"] == "KMJ Creative Solutions LLC"
    assert v["trade_name"] == "KMJ Creative Solutions"
    assert v["mail_city_state_zip"] == "Detroit, MI 48201"
    assert v["responsible_name"] == "Kevin McCloud Jr."
    assert v["signer"] == "Kevin McCloud Jr., Founder/Owner"
    assert v["date_started"] == "03/14/2025"
    assert v["services"].startswith("Faith-driven business coaching")


def test_no_ssn_and_no_tax_determination_is_ever_filled():
    v = irs_forms.ss4_values(IDENT, PP, "KMJ", BP)
    assert "123-45-6789" not in v.values()
    # and the map offers no box for them at all
    for never in ("ssn", "itin", "entity_type", "reason", "closing_month",
                  "employees", "signature", "signed_date"):
        assert not any(never in k for k in irs_forms.SS4_FIELDS), never
    # Line 7b is f1_11 on this revision; nothing may point at it.
    assert not any(v.endswith(".f1_11[0]") for v in irs_forms.SS4_FIELDS.values())


def test_a_display_name_standing_in_for_the_legal_name_is_not_written():
    v = irs_forms.ss4_values({**IDENT, "legal_name_is_fallback": True}, PP, "KMJ", BP)
    assert "legal_name" not in v and "trade_name" not in v


def test_8a_is_left_to_the_owner_when_the_entity_could_be_an_llc():
    # An LLC can elect S-corp status and a nonprofit can be an LLC.
    for et in ("s_corp", "nonprofit", "", None):
        v = irs_forms.ss4_values({**IDENT, "entity_type": et}, PP)
        assert "llc_yes" not in v and "llc_no" not in v, et


def test_8a_is_no_only_for_entities_that_cannot_be_an_llc():
    for et in ("sole_prop", "partnership", "c_corp"):
        v = irs_forms.ss4_values({**IDENT, "entity_type": et}, PP)
        assert v["llc_no"] == irs_forms.SS4_NO and "llc_yes" not in v, et


def test_a_multi_member_llc_does_not_guess_the_member_count():
    v = irs_forms.ss4_values({**IDENT, "entity_type": "multi_member_llc"}, PP)
    assert v["llc_yes"] == "/1" and "llc_members" not in v


def test_a_renamed_ss4_field_refuses_instead_of_returning_a_blank(monkeypatch):
    monkeypatch.setattr(irs_forms, "_fetch", lambda url: _acroform([("x[0]", "/Tx")]))
    with pytest.raises(irs_forms.FormUnavailable) as e:
        irs_forms.fill_ss4(IDENT, PP, "KMJ", BP)
    assert "changed shape" in str(e.value)


def test_the_ss4_text_boxes_fill_and_read_back(monkeypatch):
    # The local fixture's checkboxes carry no appearance streams, so this
    # exercises the text path; the 8a/8c checkbox writes were verified on
    # the live IRS form by rendering it (see the SS4_FIELDS comment).
    monkeypatch.setattr(irs_forms, "_fetch", lambda url: _blank_ss4())
    out = irs_forms.fill_ss4({**IDENT, "entity_type": ""}, PP, "KMJ Creative Solutions", BP)
    from io import BytesIO
    from pypdf import PdfReader
    back = PdfReader(BytesIO(out)).get_fields()
    assert back[irs_forms.SS4_FIELDS["legal_name"]]["/V"] == "KMJ Creative Solutions LLC"
    assert back[irs_forms.SS4_FIELDS["responsible_name"]]["/V"] == "Kevin McCloud Jr."


def test_the_ss4_comes_from_the_stable_irs_path():
    assert irs_forms.SS4_URL == "https://www.irs.gov/pub/irs-pdf/fss4.pdf"


# ── The prep checklist ───────────────────────────────────────────────

def _prep(**over):
    inputs = {"business": {"id": "b1", "name": "KMJ Creative Solutions", "owner_id": "u1"},
              "identity": IDENT, "practitioner": PP, "profile": BP}
    inputs.update(over)
    return ein_prep.prep_for(inputs)


def _item(p, key):
    return next(i for i in p["items"] if i["key"] == key)


def test_known_answers_come_from_records_and_the_rest_are_the_owners():
    p = _prep()
    assert _item(p, "entity")["answer"].startswith("Limited liability company")
    assert _item(p, "entity")["source"] == ein_prep.RECORDS
    assert _item(p, "formation_state")["answer"] == "Michigan"
    assert _item(p, "started")["answer"] == "March 14, 2025"
    assert _item(p, "address")["answer"] == "123 Example St, Detroit, MI 48201"
    for owners in ("reason", "llc_tax", "closing_month", "employees", "county"):
        assert _item(p, owners)["answer"] is None
        assert _item(p, owners)["source"] == ein_prep.YOU
    assert p["from_records"] >= 8
    assert p["apply_url"].startswith("https://www.irs.gov/")


def test_the_ssn_row_never_carries_a_value():
    p = _prep()
    row = _item(p, "responsible_ssn")
    assert row["answer"] is None and row["source"] == ein_prep.YOU
    assert "never" in row["note"].lower()
    assert "123-45-6789" not in repr(p)


def test_the_llc_tax_question_only_appears_for_an_llc():
    assert any(i["key"] == "llc_tax" for i in _prep()["items"])
    sole = _prep(identity={**IDENT, "entity_type": "sole_prop"})
    assert not any(i["key"] == "llc_tax" for i in sole["items"])


def test_an_empty_business_gets_every_question_as_its_own():
    p = _prep(identity={}, practitioner={}, profile={})
    assert p["from_records"] == 0
    assert all(i["source"] == ein_prep.YOU for i in p["items"])


def test_the_endpoints_are_mounted():
    import foundation_router
    paths = {getattr(r, "path", "") for r in foundation_router.router.routes}
    assert "/foundation/ein-prep/{business_id}" in paths
    assert "/foundation/ss4/{business_id}" in paths
