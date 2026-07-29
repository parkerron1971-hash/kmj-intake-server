"""
test_giving_statements.py — the document a church is obliged to produce.

The compliance tests carry the weight. A giving statement missing the
goods-and-services declaration is not cosmetically incomplete — the IRS can
disallow the donor's deduction on it (Publication 1771). So the declaration
is asserted as ALWAYS PRESENT, and the incomplete case is asserted to say so
out loud rather than printing something that looks finished.

The sensitivity tests are the other half: giving history is a read, and it
must still never reach an outside agent.
"""
from __future__ import annotations

import pytest

import action_registry
import giving_statements as gs


BIZ, CONTACT = "biz-1", "contact-1"


class FakeSB:
    def __init__(self, invoices):
        self.invoices = invoices

    def sb_get_as_service(self, path):
        if not path.startswith("/invoices"):
            return []
        rows = self.invoices
        for part in path.split("&"):
            if part.startswith("contact_id=eq."):
                cid = part.split("=eq.")[1]
                rows = [r for r in rows if r.get("contact_id") == cid]
        return rows


def _inv(amount, when="2025-03-04", contact_id=CONTACT, name="Marcus Webb",
         category="", refund_cents=None):
    return {"id": f"inv-{amount}-{when}", "total": amount,
            "paid_at": f"{when}T12:00:00Z", "category": category,
            "refund_amount_cents": refund_cents, "contact_id": contact_id,
            "contacts": {"name": name, "email": "m@example.com"}}


@pytest.fixture
def sb(monkeypatch):
    def _install(invoices):
        import sys, types
        mod = types.ModuleType("sb_clients")
        mod.sb_get_as_service = FakeSB(invoices).sb_get_as_service
        monkeypatch.setitem(sys.modules, "sb_clients", mod)
    return _install


# ─── the compliance core ─────────────────────────────────────────────

def test_declaration_is_always_present(sb):
    """IRS Pub 1771 requirement #3, and the one most often omitted. Its
    absence is what invalidates an otherwise-correct statement."""
    sb([_inv(100)])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025)
    assert s["declaration"]
    assert gs.NO_GOODS_LANGUAGE in gs.render_text(s)


def test_religious_benefit_language_when_asked_for(sb):
    sb([_inv(100)])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025,
                                 goods_and_services="religious")
    assert s["declaration"] == gs.RELIGIOUS_BENEFIT_LANGUAGE
    assert s["statement_complete"] is True


def test_goods_provided_without_a_value_is_not_sendable(sb):
    """A description with no good-faith estimate is NOT compliant. It must
    refuse to look finished."""
    sb([_inv(500)])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025,
                                 goods_and_services="Gala dinner and concert")
    assert s["statement_complete"] is False
    assert "REQUIRED" in s["declaration"]
    assert "NOT READY TO SEND" in gs.render_text(s)


def test_gifts_at_or_over_250_are_flagged(sb):
    """The $250 threshold is per GIFT, not per year — which is why the
    individual gifts are itemised at all."""
    sb([_inv(100), _inv(250, "2025-05-01"), _inv(600, "2025-07-01")])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025)
    flagged = [g["amount"] for g in s["gifts_requiring_acknowledgment"]]
    assert flagged == [250, 600]


def test_many_small_gifts_totalling_over_250_are_not_flagged(sb):
    """Ten $50 gifts is $500 for the year but no single gift crosses the
    threshold. Flagging them would misstate the rule."""
    sb([_inv(50, f"2025-0{m}-01") for m in range(1, 10)])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025)
    assert s["total"] == 450
    assert s["gifts_requiring_acknowledgment"] == []


def test_disclaimer_is_in_the_document(sb):
    """The system prints what the org tells it; it does not assert 501(c)(3)
    status or give tax advice."""
    sb([_inv(100)])
    assert "not tax advice" in gs.render_text(
        gs.statement_for_contact(BIZ, CONTACT, 2025)).lower()


# ─── money correctness ───────────────────────────────────────────────

def test_refunds_reduce_the_stated_total(sb):
    """A refunded gift was not a gift. Printing it overstates a donor's
    deduction — which is the donor's problem, caused by us."""
    sb([_inv(500, refund_cents=20000)])       # $500 less $200 refunded
    s = gs.statement_for_contact(BIZ, CONTACT, 2025)
    assert s["total"] == 300


def test_fully_refunded_gift_disappears(sb):
    sb([_inv(100, refund_cents=10000)])
    assert gs.statement_for_contact(BIZ, CONTACT, 2025)["empty"] is True


def test_totals_sum_the_gifts(sb):
    sb([_inv(100), _inv(250, "2025-06-01"), _inv(75.50, "2025-09-01")])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025)
    assert s["total"] == pytest.approx(425.50)
    assert s["gift_count"] == 3


def test_no_gifts_is_an_empty_statement_not_a_zero_one(sb):
    """A $0.00 statement implies 'you gave nothing'. No statement is the
    honest output."""
    sb([])
    s = gs.statement_for_contact(BIZ, CONTACT, 2025)
    assert s["empty"] is True
    assert "$" not in gs.render_text(s)


# ─── the year run ────────────────────────────────────────────────────

def test_year_run_groups_by_donor(sb):
    sb([_inv(100, contact_id="a", name="Ann"),
        _inv(300, "2025-04-01", contact_id="a", name="Ann"),
        _inv(50,  "2025-04-01", contact_id="b", name="Ben")])
    run = gs.statements_for_year(BIZ, 2025)
    assert run["donor_count"] == 2
    ann = next(d for d in run["donors"] if d["name"] == "Ann")
    assert ann["total"] == 400
    assert ann["needs_acknowledgment"] is True
    ben = next(d for d in run["donors"] if d["name"] == "Ben")
    assert ben["needs_acknowledgment"] is False


def test_donors_sorted_by_total(sb):
    sb([_inv(50, contact_id="a", name="Ann"),
        _inv(900, "2025-04-01", contact_id="b", name="Ben")])
    assert gs.statements_for_year(BIZ, 2025)["donors"][0]["name"] == "Ben"


def test_unattributed_gifts_counted_but_never_invented_into_a_statement(sb):
    """Loose cash with no giver attached cannot be acknowledged to anyone.
    It must still reconcile in the totals."""
    sb([_inv(100, contact_id="a", name="Ann"),
        _inv(40, "2025-04-01", contact_id=None, name=None)])
    run = gs.statements_for_year(BIZ, 2025)
    assert run["donor_count"] == 1
    assert run["unattributed_total"] == 40
    assert run["total_recorded"] == 140


# ─── sensitivity: reads that must not leave the building ─────────────

@pytest.mark.parametrize("verb", ["giving_statement", "giving_statements_run"])
def test_giving_verbs_are_reads(verb):
    assert action_registry.effect(verb) == action_registry.READ


@pytest.mark.parametrize("verb", ["giving_statement", "giving_statements_run"])
def test_giving_never_reaches_an_agent_surface(verb):
    """The distinction this whole flag exists for: read-ness answers 'can
    it break anything', sensitivity answers 'may a third party see it'.
    A congregation's giving history is the case where they diverge."""
    assert action_registry.is_sensitive(verb) is True
    assert action_registry.may_expose_to_agent(verb) is False
    assert action_registry.may_expose_to_agent(verb, allow_writes=True) is False


def test_ordinary_reads_are_still_exposed():
    """The flag must not have quietly closed the whole agent surface."""
    assert action_registry.may_expose_to_agent("catch_up") is True
    assert action_registry.is_sensitive("catch_up") is False


def test_unknown_verbs_are_treated_as_sensitive():
    """Same default-deny posture as every other accessor in the registry."""
    assert action_registry.is_sensitive("verb_that_does_not_exist") is True
