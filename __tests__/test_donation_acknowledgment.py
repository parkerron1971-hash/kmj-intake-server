"""The receipt, and the branch mechanism that nearly ate it.

A nonprofit issues more donation acknowledgments than every governance
policy put together, and it is the only document in the library with a
statutory text requirement. IRC §170(f)(8): a donor cannot deduct a
single gift of $250 or more without a contemporaneous written
acknowledgment stating the amount (or, for property, a DESCRIPTION),
and whether the organisation gave anything back.

Clause (ii) is the one that goes missing, and a receipt without it does
not substantiate the gift — the donor loses the deduction on audit, over
a letter the organisation believed it had sent correctly. So the tests
below are not about wording. They are about a sentence being present.

They exist in this shape because writing the template found a live trap
in the DSL: assemble() case-folded the value read from the form but not
the value the template declared, so a `requires_value` with any capital
letter matched nothing and its section vanished — no error, no log, just
a clause absent from the finished paper. Every template written before
this one happened to use lowercase keys, so nothing had ever tripped it.
The first draft of this receipt printed a greeting, a "keep this for
your records" note and no amount and no goods-and-services statement.
"""

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import doc_templates as dt  # noqa: E402

TID = "donation_acknowledgment"

_COMMON = {
    "org_name": "Riverbend Community Trust",
    "ein": "84-1234567",
    "donor_name": "Alicia Reyes",
    "gift_date": "August 12, 2026",
    "signer_name": "Dana Whitfield",
    "signer_title": "Executive Director",
}


def _render(**extra) -> str:
    """Through the production seam — build_vars then assemble — because
    a hand-built variables dict skips the defaults and the blank-field
    substitution that decide which sections survive."""
    t = dt.TEMPLATE_INDEX[TID]
    variables = dt.build_vars(
        t, {**_COMMON, **extra},
        business_name="Riverbend Community Trust",
        practitioner_name="Dana Whitfield",
        client_name="Alicia Reyes", date_str="August 15, 2026")
    return dt.assemble(t, variables, drafted_texts={}, include_review_note=False)


# ── The statutory content ────────────────────────────────────────────

def test_a_cash_gift_states_the_amount_and_the_date():
    body = _render(gift_type="cash", amount="$500.00",
                   benefits="nothing in return")
    assert "$500.00" in body
    assert "August 12, 2026" in body


def test_every_branch_states_whether_anything_was_given_back():
    """§170(f)(8)(B). The sentence that is always left out, asserted for
    all three answers — because the field is required and has no blank
    option, one of them always renders."""
    cases = [
        ({"benefits": "nothing in return"},
         "No goods or services were provided"),
        ({"benefits": "goods or services",
          "benefit_description": "Two seats at the annual gala dinner.",
          "benefit_value": "$90.00"},
         "provided you with the following goods or services"),
        ({"benefits": "religious benefits only"},
         "other than intangible religious benefits"),
    ]
    for extra, expected in cases:
        body = _render(gift_type="cash", amount="$500.00", **extra)
        assert expected in body, extra


def test_a_quid_pro_quo_gift_states_the_estimate_and_the_limit():
    body = _render(gift_type="cash", amount="$1,000.00",
                   benefits="goods or services",
                   benefit_description="Two seats at the annual gala dinner.",
                   benefit_value="$90.00")
    assert "$90.00" in body
    assert "Two seats at the annual gala dinner." in body
    # Without this the donor deducts the whole $1,000.
    assert "exceeds that value" in body


def test_a_property_gift_is_described_and_not_valued():
    """Valuing a non-cash gift is the DONOR's job. An organisation that
    writes a number here has performed the donor's appraisal — which is
    why there is no value field beside the description at all."""
    body = _render(gift_type="property",
                   property_description="Twelve boxes of children's books.",
                   benefits="nothing in return")
    assert "Twelve boxes of children's books." in body
    assert "does not state a value" in body
    assert "qualified appraisal" in body

    keys = {f["key"] for f in dt.TEMPLATE_INDEX[TID]["fields"]}
    assert "property_value" not in keys
    assert "fair_market_value" not in keys


def test_the_ein_is_on_the_receipt():
    """The one document where it belongs on the page — a donor's
    accountant looks for it. The PDF letterhead deliberately omits it."""
    assert "84-1234567" in _render(gift_type="cash", amount="$500.00",
                                   benefits="nothing in return")


def test_the_receipt_is_never_drafted():
    """An amount, a date and a statutory sentence. There is no paragraph
    here a model improves, and a fabricated figure on a tax document is a
    different order of problem from one in a bio."""
    assert not any(s["kind"] == "drafted"
                   for s in dt.TEMPLATE_INDEX[TID]["sections"])


def test_the_choices_are_required_so_silence_cannot_happen():
    fields = {f["key"]: f for f in dt.TEMPLATE_INDEX[TID]["fields"]}
    for key in ("gift_type", "benefits"):
        assert fields[key]["required"], key
        assert fields[key].get("default"), f"{key} needs a safe default"


# ── The branch mechanism itself ──────────────────────────────────────

def test_requires_value_is_case_insensitive_on_both_sides():
    """The trap. assemble() lowercased the FORM value and compared it to
    the declared value verbatim, so a template declaring "Cash" matched
    nothing and its section silently disappeared."""
    t = {"numbered": False, "fields": [],
         "sections": [dt.fixed("Kept", "body text",
                               requires_value=("k", "Mixed Case"))]}
    for given in ("Mixed Case", "mixed case", "MIXED CASE", "  Mixed Case  "):
        out = dt.assemble(t, {"k": given}, drafted_texts={},
                          include_review_note=False)
        assert "body text" in out, given
    out = dt.assemble(t, {"k": "something else"}, drafted_texts={},
                      include_review_note=False)
    assert "body text" not in out


@pytest.mark.parametrize("tid", [t["id"] for t in dt.TEMPLATES])
def test_every_requires_value_can_actually_match_an_option(tid):
    """The guard for the whole class.

    A `requires_value` naming a value no option can produce is a section
    that renders for nobody, ever — and it fails the way this one did:
    completely silently, in a finished document, with no error anywhere.
    """
    t = dt.TEMPLATE_INDEX[tid]
    options = {f["key"]: f.get("options")
               for f in t["fields"] if f.get("type") == "select"}
    for s in t["sections"]:
        rv = s.get("requires_value")
        if not rv:
            continue
        opts = options.get(rv["field"])
        assert opts is not None, (
            f"{tid}: requires_value on '{rv['field']}', which is not a "
            f"select field on this template")
        assert any(str(o).strip().lower() == str(rv["value"]).strip().lower()
                   for o in opts), (
            f"{tid}: no option of '{rv['field']}' can ever equal "
            f"{rv['value']!r} — options are {opts}")


@pytest.mark.parametrize("tid", [t["id"] for t in dt.TEMPLATES])
def test_every_select_default_is_one_of_its_options(tid):
    """A default outside the option list is the same failure wearing a
    different hat: the form opens on a value no branch matches."""
    for f in dt.TEMPLATE_INDEX[tid]["fields"]:
        if f.get("type") != "select" or not f.get("default"):
            continue
        assert any(str(o).strip().lower() == str(f["default"]).strip().lower()
                   for o in f["options"]), (
            f"{tid}.{f['key']}: default {f['default']!r} is not in "
            f"{f['options']}")


# ── Where it shows up ────────────────────────────────────────────────

def test_it_is_offered_to_nonprofits_and_ministries():
    t = dt.TEMPLATE_INDEX[TID]
    assert "nonprofit" in t["suggested_for"]
    assert "ministry" in t["suggested_for"]
    assert not dt.is_irrelevant(TID, "nonprofit")
    assert not dt.is_irrelevant(TID, "ministry")


def test_a_coach_is_not_offered_a_deduction_they_cannot_give():
    """Not a refusal — Show all still reaches it, because a consultant
    can legitimately produce one for a client organisation. But a gift to
    a business is not a deductible contribution, and this receipt says
    one is."""
    assert dt.is_irrelevant(TID, "coach")
    why = dt.irrelevance_reason(TID, "coach") or ""
    assert "deduct" in why.lower()
