"""Help requests: the pastor says yes, the treasurer pays (church_help.py).

Kevin, 2026-11-18: "requesting help shouldn't be directly tied to treasurer.
shouldn't the pastor handle that and submit approval to treasurer?"

Pins:
  * the care side sends money help to the treasurer only after a yes, and
    only with a payee (pay the provider, not the person); approve-and-send in
    one step never approves when the send is refused
  * the treasurer (a login that works Giving & money) sees a To pay list: the
    need, the amount left of the yes, the payee, the reference, the due day and
    who sent it, never who asked or the story; the alert says the same
  * the treasurer pays up to what's left of the yes, by check, a bank payment
    or a gift card, only what was sent to them; paying more is a new yes; the
    payment goes into the books with no name and no story; a full payment
    closes the request and its Prayer & care ask, and tells whoever sent it
  * who is told: keepers of Giving & money, the treasurer's lane, logins that
    work Giving & money; never the sender; the owner when nobody else
  * a youth's ask is never sent; a send can be taken back until it's paid
  * before the migration the page works, and sending or paying answers 503
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import church_help as ch  # noqa: E402
from test_church_help import (  # noqa: E402,F401
    ASK, BIZ, DANA, ID, STORY, YOUTH_ASK, _add, _by, _decide, _keeper, _page, _req, client, db,
)

PAYEE = "Nashville Electric Service"


@pytest.fixture
def told(db, monkeypatch):
    got = []
    monkeypatch.setattr(ch, "_tell", lambda biz, to, title, body, tag: got.append((sorted(to), title, body)))
    return got


def _send(name, ref, **kw):
    body = {"business_id": BIZ, "payee": PAYEE, "reference": "acct ending 4421", "due": "2026-10-30", **kw}
    return client(name).post(f"/church/help/requests/{ref}/send-to-pay", json=body)


def _pay(name, ref, **kw):
    body = {"business_id": BIZ, "how": "check", "given_on": "2026-10-27", "reference": "Check 1042", **kw}
    return client(name).post(f"/church/help/requests/{ref}/given", json=body)


def _approved_bill(amount="150"):
    bill = _add("carer").json()["request"]
    got = _decide("carer", bill["id"], amount=amount)
    assert got.status_code == 200, got.text
    return got.json()["request"]


# ─── Sending ─────────────────────────────────────────────────────────

def test_send_needs_a_yes_and_a_payee(db, told):
    bill = _add("carer").json()["request"]
    assert _send("carer", bill["id"]).status_code == 409, "a yes comes first"
    assert _decide("carer", bill["id"], amount="150").status_code == 200
    assert _send("carer", bill["id"], payee="  ").status_code == 400, "pay the provider: name them"
    assert _send("viewer", bill["id"]).status_code == 403, "a viewer only reads"
    assert _send("treasurer", bill["id"]).status_code == 403, "the treasurer pays; the care side sends"
    got = _send("carer", bill["id"])
    assert got.status_code == 200, got.text
    sent = got.json()["request"]["to_pay"]
    assert sent["payee"] == PAYEE and sent["reference"] == "acct ending 4421" and sent["due"] == "2026-10-30"
    assert sent["sent_by"] == "carer@lovecity.org" and sent["sent_at"]
    assert got.json()["told"] == 1 and got.json()["told_names"] == ["treasurer@lovecity.org"]
    # Sending again changes the details and rings nobody twice.
    again = _send("carer", bill["id"], payee="NES", reference="")
    assert again.status_code == 200 and again.json()["request"]["to_pay"]["payee"] == "NES"
    assert again.json()["request"]["to_pay"]["reference"] is None
    assert len(told) == 1


def test_approve_and_send_in_one_step_never_half_happens(db, told):
    bill = _add("carer").json()["request"]
    body = {"business_id": BIZ, "status": "approved", "amount": "120", "send_to_pay": {"payee": ""}}
    assert client("carer").post(f"/church/help/requests/{bill['id']}/decide", json=body).status_code == 400
    assert _req(db, bill["id"])["status"] == "new", "a refused send never leaves a yes behind"
    body["send_to_pay"] = {"payee": PAYEE, "due": "2026-10-30"}
    got = client("carer").post(f"/church/help/requests/{bill['id']}/decide", json=body)
    assert got.status_code == 200, got.text
    r = got.json()["request"]
    assert r["status"] == "approved" and r["approved_cents"] == 12000 and r["to_pay"]["payee"] == PAYEE
    assert told and told[0][0] == [ID["treasurer"]]
    # An app ask becomes a row, says yes and goes to the treasurer at once.
    body = {"business_id": BIZ, "status": "approved", "amount": "90", "send_to_pay": {"payee": "Kroger"}}
    got = client("carer").post(f"/church/help/requests/care-{ASK}/decide", json=body)
    assert got.status_code == 200, got.text
    assert got.json()["request"]["to_pay"]["payee"] == "Kroger"


def test_the_treasurer_sees_the_payment_never_who_or_why(db, told):
    bill = _approved_bill()
    assert _send("carer", bill["id"]).status_code == 200
    money = _page("treasurer")
    seen = _by(money, bill["id"])
    assert seen["who"] is None and seen["notes"] is None and seen["contact_id"] is None
    assert seen["to_pay"]["payee"] == PAYEE and seen["to_pay"]["due"] == "2026-10-30"
    assert money["fund"]["to_pay"] == 1 and money["fund"]["to_pay_cents"] == 15000
    assert money["me"]["pay"] is True and money["me"]["send"] is False
    to, title, body = told[0]
    assert title == f"A help payment is ready: $150 to {PAYEE}"
    said = title + body
    assert "Dana" not in said and "light bill" not in said.lower() and "kids" not in said.lower()
    assert "acct ending 4421" in body and "due Fri, Oct 30" in body
    care = _page("carer")
    assert care["me"]["send"] is True and care["me"]["pay"] is False


# ─── Paying ──────────────────────────────────────────────────────────

def test_the_treasurer_pays_only_what_was_sent_and_never_more(db, told):
    bill = _approved_bill()
    assert _pay("treasurer", bill["id"]).status_code == 403, "nothing was sent to the treasurer yet"
    assert _send("carer", bill["id"]).status_code == 200
    assert _pay("treasurer", bill["id"], how="cash").status_code == 400, "the provider, never cash to the person"
    over = _pay("treasurer", bill["id"], amount="151")
    assert over.status_code == 403 and over.json()["detail"]["code"] == "over_approved"
    assert _pay("treasurer", f"care-{ASK}").status_code == 404
    assert db.t["business_expenses"] == []


def test_a_payment_goes_into_the_books_and_closes_the_loop(db, told):
    body = {"business_id": BIZ, "status": "approved", "amount": "120",
            "send_to_pay": {"payee": PAYEE, "reference": "acct ending 4421"}}
    first = client("carer").post(f"/church/help/requests/care-{ASK}/decide", json=body).json()["request"]
    ref = first["id"]
    assert first["care_id"] == ASK and ref != f"care-{ASK}", "the desk finds the ask by its care id"
    told.clear()
    got = _pay("treasurer", ref)
    assert got.status_code == 200, got.text
    r = got.json()["request"]
    assert r["status"] == "helped" and r["given_cents"] == 12000
    g = r["given"][0]
    assert g["how"] == "check" and g["payee"] == PAYEE and g["reference"] == "Check 1042"
    assert g["by"] == "treasurer@lovecity.org" and g["note"] is None
    exp = db.t["business_expenses"][0]
    assert exp["vendor"] == PAYEE and exp["amount"] == 120.0 and exp["subcategory"] == "Benevolence"
    said = " ".join(str(v) for v in exp.values())
    assert "Dana" not in said and "light bill" not in said.lower()
    care = next(c for c in db.t["ministry_care_requests"] if c["id"] == ASK)
    assert care["status"] == "closed", "the Prayer & care ask closes with it"
    assert told == [([ID["carer"]], f"Paid: $120 to {PAYEE}",
                     "treasurer@lovecity.org paid it on Tue, Oct 27. The request is closed, and its Prayer & care ask with it.")]
    # The care side sees who paid.
    assert _by(_page("carer"), ref)["given"][0]["by"] == "treasurer@lovecity.org"
    assert _pay("treasurer", ref).status_code == 409, "paid already"


def test_part_of_a_payment_leaves_the_rest_to_pay(db, told):
    bill = _approved_bill("150")
    assert _send("carer", bill["id"]).status_code == 200
    got = _pay("treasurer", bill["id"], amount="100", how="transfer")
    assert got.status_code == 200, got.text
    assert got.json()["request"]["status"] == "approved"
    assert _page("treasurer")["fund"]["to_pay_cents"] == 5000
    assert _pay("treasurer", bill["id"], amount="60").status_code == 403, "$50 is what's left"
    assert _pay("treasurer", bill["id"]).json()["request"]["status"] == "helped", "no amount pays what's left"


def test_a_send_can_be_taken_back_until_it_is_paid(db, told):
    bill = _approved_bill()
    assert _send("carer", bill["id"]).status_code == 200
    c = client("carer")
    got = c.delete(f"/church/help/requests/{bill['id']}/send-to-pay?business_id={BIZ}")
    assert got.status_code == 200 and got.json()["request"]["to_pay"] is None
    assert _send("carer", bill["id"]).status_code == 200
    assert _pay("treasurer", bill["id"], amount="50").status_code == 200
    assert c.delete(f"/church/help/requests/{bill['id']}/send-to-pay?business_id={BIZ}").status_code == 409


def test_a_youths_ask_is_never_sent(db, told):
    assert _decide("owner", f"care-{YOUTH_ASK}", amount="20").status_code == 200
    ref = next(r["id"] for r in db.t["church_help_requests"] if r["care_request_id"] == YOUTH_ASK)
    assert _send("owner", ref).status_code == 409


# ─── Who is told ─────────────────────────────────────────────────────

def test_who_hears_a_payment_is_ready(db, told, monkeypatch):
    bill = _approved_bill()
    _keeper(db, "admin")
    assert _send("carer", bill["id"]).status_code == 200
    assert told[0][0] == sorted([ID["admin"], ID["treasurer"]]), "the keeper and the Giving login, not the sender"
    # The treasurer's lane counts, whatever their areas.
    db.t["church_keepers"].clear()
    for s in db.t["business_users"]:
        if s["user_id"] == ID["singer"]:
            s["lane"] = "treasurer"
    told.clear()
    second = _approved_bill("90")
    assert _send("carer", second["id"]).status_code == 200
    assert told[0][0] == sorted([ID["singer"], ID["treasurer"]])
    # Nobody keeps Giving & money: the owner hears it, unless the owner sent it.
    monkeypatch.setenv("CHURCH_AREAS", "off")
    monkeypatch.setenv("CHURCH_KEYS", "off")
    for s in db.t["business_users"]:
        s.pop("lane", None)
    told.clear()
    third = _approved_bill("40")
    assert _send("carer", third["id"]).status_code == 200
    assert told[0][0] == [ID["owner"]]
    told.clear()
    fourth = _approved_bill("30")
    got = _send("owner", fourth["id"])
    assert got.status_code == 200 and got.json()["told"] == 0 and told == []


# ─── Before the migration ────────────────────────────────────────────

def test_before_the_migration_the_page_works_and_sending_waits(db, told, monkeypatch):
    real = db.get

    def get(path, **kw):
        if any(k in path for k in ("sent_to_pay_at", "pay_to", ",reference")):
            return None      # PostgREST: the column doesn't exist yet
        return real(path, **kw)
    monkeypatch.setattr(ch.sb_clients, "sb_get_as_service", get)
    bill = _approved_bill()
    page = _page("carer")
    assert page["me"]["send"] is False and _by(page, bill["id"])["to_pay"] is None
    assert _page("treasurer")["me"]["pay"] is False
    assert _send("carer", bill["id"]).status_code == 503
    other = _add("carer").json()["request"]
    body = {"business_id": BIZ, "status": "approved", "amount": "100", "send_to_pay": {"payee": PAYEE}}
    assert client("carer").post(f"/church/help/requests/{other['id']}/decide", json=body).status_code == 503
    assert _req(db, other["id"])["status"] == "new"
    assert _pay("treasurer", bill["id"]).status_code == 503
    # The care side still records help the old way.
    got = client("carer").post(f"/church/help/requests/{bill['id']}/given",
                               json={"business_id": BIZ, "how": "check", "amount": "150", "given_on": "2026-10-27"})
    assert got.status_code == 200, got.text
    assert client("carer").post(f"/church/help/requests/{other['id']}/given",
                                json={"business_id": BIZ, "how": "transfer", "amount": "10"}).status_code == 503
    assert told == []
