"""What the person asked to pay reads: an invoice, or for a church a bill
(bill_words).

Each path that reaches a payer is driven here twice: as a church, where no
line may say invoice, and as a business, where every line is the literal
text it had before. Nothing is sent: Resend, Stripe and the database are
fakes.
"""
import asyncio
import re
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

import bill_words
import chief_invoice_sms
import chief_of_staff as chief
import rules_router
import stripe_checkout_helpers
import stripe_payments_router
from stripe_payments_router import InvoiceCheckoutBody, invoice_checkout

CHURCH = {"id": "11111111-1111-4111-8111-111111111111", "type": "church", "name": "Grace Fellowship",
          "owner_id": "user-1", "stripe_account_id": "acct_123", "settings": {}}
COACH = {**CHURCH, "id": "22222222-2222-4222-8222-222222222222", "type": "coaching", "name": "Example Co"}
BILL = {"id": "inv-1", "business_id": CHURCH["id"], "contact_id": "c-1", "invoice_number": "INV-2026-004",
        "status": "sent", "total": 250.0, "currency": "USD", "due_date": "2026-11-30", "is_gift": False,
        "items": [{"description": "Fellowship hall, Saturday", "quantity": 1, "unit_price": 250.0, "total": 250.0}],
        "stripe_payment_url": "https://buy.stripe.com/test_abc", "notes": ""}
GIFT = {**BILL, "id": "gift-1", "invoice_number": "GIVE-pi_123", "is_gift": True, "status": "paid"}
CONTACT = {"id": "c-1", "name": "Dana Ruiz", "email": "dana@example.org"}

SAYS_INVOICE = re.compile(r"invoice", re.I)


# ─── Who reads bill ───────────────────────────────────────────────────

def test_a_churchs_bill_is_a_bill_and_a_gift_never_is():
    assert bill_words.is_bill(CHURCH, BILL) is True
    assert bill_words.is_bill(CHURCH) is True
    assert bill_words.is_bill(CHURCH, GIFT) is False
    # A gift row is told by its number too, where the mark was not read.
    assert bill_words.is_bill(CHURCH, {"invoice_number": "GIVE-manual-abc"}) is False
    assert bill_words.is_bill(COACH, BILL) is False
    assert bill_words.is_bill(None, BILL) is False
    assert bill_words.is_bill({}, None) is False


def test_a_churchs_words_never_say_invoice():
    said = [
        bill_words.words(CHURCH, BILL)["label"], bill_words.words(CHURCH, BILL)["intro"],
        bill_words.email_subject(CHURCH, BILL, "INV-2026-004", "Grace Fellowship"),
        bill_words.pay_header(CHURCH, BILL, "$250.00"),
        bill_words.stripe_name(CHURCH, BILL, "INV-2026-004").replace("INV-2026-004", ""),
        bill_words.stripe_name(CHURCH, BILL),
        bill_words.text_head(CHURCH, BILL, "INV-2026-004"),
        *bill_words.overdue_nudge(CHURCH, BILL, "Dana", 250.0, "2026-11-30", 9).values(),
    ]
    for line in said:
        assert not SAYS_INVOICE.search(line), line
        assert "—" not in line, line
    assert bill_words.email_subject(CHURCH, BILL, "INV-2026-004", "Grace Fellowship") == "Bill INV-2026-004 from Grace Fellowship"
    assert bill_words.pay_header(CHURCH, BILL, "$250.00") == "Pay this bill: $250.00"
    assert bill_words.stripe_name(CHURCH, BILL, "INV-2026-004") == "Bill INV-2026-004"
    assert bill_words.text_head(CHURCH, BILL, "INV-2026-004") == "Grace Fellowship: bill INV-2026-004"


def test_a_business_reads_the_words_it_always_read():
    assert bill_words.words(COACH, BILL) == {
        "label": "INVOICE", "intro": "Please find your invoice below.",
        "pay_header": "Pay This Invoice — {total}",
        "stripe_named": "Invoice {number}", "stripe_unnamed": "Invoice Payment"}
    assert bill_words.email_subject(COACH, BILL, "INV-2026-004", "Example Co") == "Invoice INV-2026-004 from Example Co"
    assert bill_words.pay_header(COACH, BILL, "$250.00") == "Pay This Invoice — $250.00"
    assert bill_words.stripe_name(COACH, BILL, "INV-2026-004") == "Invoice INV-2026-004"
    assert bill_words.stripe_name(COACH, BILL, "") == "Invoice Payment"
    assert bill_words.text_head(COACH, BILL, "INV-2026-004") == "Example Co — Invoice INV-2026-004"
    assert bill_words.text_head({}, BILL, "INV-1") == "Your business — Invoice INV-1"
    assert bill_words.overdue_nudge(COACH, BILL, "Dana", 250.0, "2026-11-30", 9) == {
        "subject": "Friendly nudge — invoice INV-2026-004",
        "body": ("Hi Dana,\n\nJust a gentle reminder that invoice INV-2026-004 ($250.00) was due on "
                 "2026-11-30. The payment link is on the invoice — and if anything's off, just reply here."
                 "\n\nThank you!"),
        "reasoning": ("Invoice INV-2026-004 is 9 days overdue and Dana hasn't been nudged. Approve to "
                      "send this reminder — nothing sends until you say so."),
    }
    assert "the client" in bill_words.overdue_nudge(COACH, BILL, None, 250.0, "2026-11-30", 9)["reasoning"]


def test_a_gift_row_keeps_the_wording_it_had_even_at_a_church():
    assert bill_words.words(CHURCH, GIFT) == bill_words.words(COACH, BILL)
    assert bill_words.email_subject(CHURCH, GIFT, "GIVE-pi_123", "Grace Fellowship") == "Invoice GIVE-pi_123 from Grace Fellowship"
    assert bill_words.stripe_name(CHURCH, GIFT, "GIVE-pi_123") == "Invoice GIVE-pi_123"


# ─── The email Chief sends ────────────────────────────────────────────

def _send(biz, invoice):
    """Drive _send_invoice_email with Resend faked; return what would go."""
    sent = {}

    async def fake_resend(**kw):
        sent.update(kw)
        return {"id": "re_1"}

    import email_sender
    with mock.patch.object(email_sender, "send_via_resend", fake_resend), \
            mock.patch.object(email_sender, "build_routed_reply_to", lambda b, c: None):
        ok, err, pid = asyncio.run(chief._send_invoice_email(None, biz, deepcopy(invoice), CONTACT))
    assert ok and err is None and pid == "re_1"
    return sent


def test_the_email_a_churchs_payer_gets_says_bill_and_keeps_every_figure():
    sent = _send(CHURCH, BILL)
    assert sent["subject"] == "Bill INV-2026-004 from Grace Fellowship"
    assert sent["to_email"] == "dana@example.org"
    html = sent["body"]
    assert not SAYS_INVOICE.search(html), SAYS_INVOICE.search(html)
    assert ">BILL</div>" in html and "Please find your bill below." in html
    assert "Pay this bill: $250.00" in html
    # Only the word changed: the number, the due day, the line and the total are as they were.
    for kept in ("INV-2026-004", "2026-11-30", "Fellowship hall, Saturday", "$250.00", "https://buy.stripe.com/test_abc", "Hi Dana Ruiz,"):
        assert kept in html, kept


def test_the_email_a_business_sends_is_the_one_it_sent_before():
    sent = _send(COACH, BILL)
    assert sent["subject"] == "Invoice INV-2026-004 from Example Co"
    html = sent["body"]
    assert '<div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#999;">INVOICE</div>' in html
    assert "Please find your invoice below." in html
    assert "Pay This Invoice — $250.00</div>" in html
    assert "bill" not in html.lower()


def test_the_two_emails_differ_only_in_the_word():
    church, coach = _send(CHURCH, BILL)["body"], _send(COACH, BILL)["body"]
    same = (church.replace("Grace Fellowship", "X").replace(">BILL<", ">INVOICE<")
            .replace("Please find your bill below.", "Please find your invoice below.")
            .replace("Pay this bill: $250.00", "Pay This Invoice — $250.00"))
    assert same == coach.replace("Example Co", "X")


def test_with_no_way_to_pay_set_up_the_email_still_never_says_invoice_to_a_churchs_payer():
    html = _send(CHURCH, {**BILL, "stripe_payment_url": None})["body"]
    assert "Please reply to this email for payment arrangements." in html
    assert not SAYS_INVOICE.search(html)


# ─── The text message ─────────────────────────────────────────────────

def test_the_text_a_churchs_payer_gets_says_bill():
    body = chief_invoice_sms.invoice_text(CHURCH, BILL)
    assert body.splitlines()[0] == "Grace Fellowship: bill INV-2026-004"
    assert not SAYS_INVOICE.search(body.replace("INV-2026-004", ""))
    assert "Total: USD 250.00" in body and "Due: 2026-11-30" in body and "Pay: https://buy.stripe.com/test_abc" in body


def test_the_text_a_business_sends_is_the_one_it_sent_before():
    body = chief_invoice_sms.invoice_text(COACH, BILL)
    assert body == ("Example Co — Invoice INV-2026-004\nFellowship hall, Saturday (qty 1)\n"
                    "Total: USD 250.00\nDue: 2026-11-30\nPay: https://buy.stripe.com/test_abc")


# ─── The name on Stripe's pay page ────────────────────────────────────

class _FakeStripe:
    """httpx.AsyncClient, answering the two calls a pay link makes."""
    posted = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FakeStripe.posted.append((url, kw.get("data")))
        body = {"id": "price_1"} if url.endswith("/prices") else {"id": "plink_1", "url": "https://buy.stripe.com/test_x"}
        return SimpleNamespace(status_code=200, json=lambda: body, text="")


def _link(**kw):
    _FakeStripe.posted = []
    with mock.patch.object(stripe_checkout_helpers.httpx, "AsyncClient", _FakeStripe), \
            mock.patch.object(stripe_checkout_helpers, "require_stripe_write", lambda acct: None), \
            mock.patch.object(stripe_checkout_helpers, "_secret_key", lambda: "sk_test_fake"):
        out = asyncio.run(stripe_checkout_helpers.create_invoice_checkout(
            stripe_account_id="acct_123", invoice_id="inv-1", amount_cents=25000, business_id="biz", **kw))
    assert out["url"] == "https://buy.stripe.com/test_x"
    price, link = _FakeStripe.posted
    return price[1], link[1]


def test_the_pay_link_is_named_as_asked_and_as_before_when_not_asked():
    price, link = _link(invoice_number="INV-2026-004", product_name="Bill INV-2026-004")
    assert price["product_data[name]"] == "Bill INV-2026-004"
    assert price["unit_amount"] == 25000
    # What the money is matched by does not change: it is still an invoice to Stripe's metadata.
    assert link["metadata[source_type]"] == "invoice" and link["metadata[source_id]"] == "inv-1"
    assert _link(invoice_number="INV-2026-004")[0]["product_data[name]"] == "Invoice INV-2026-004"
    assert _link()[0]["product_data[name]"] == "Invoice Payment"
    assert _link(invoice_number="INV-2026-004", product_name="  ")[0]["product_data[name]"] == "Invoice INV-2026-004"


def _checkout(biz, invoice):
    seen = {}

    def fake_get(path):
        if path.startswith("/invoices"):
            seen["invoice_select"] = path
            return [deepcopy(invoice)]
        if path.startswith("/businesses"):
            seen["business_select"] = path
            return [deepcopy(biz)]
        return []

    async def fake_create(self, biz_row, **kwargs):
        seen["kwargs"] = kwargs
        return {"id": "plink_1", "url": "https://buy.stripe.com/test_x"}

    import business_users_router
    import financial_policy
    import payments_core
    with mock.patch.object(stripe_payments_router.sb_clients, "sb_get_as_service", fake_get), \
            mock.patch.object(stripe_payments_router.sb_clients, "sb_patch_as_service", lambda p, b: None), \
            mock.patch.object(business_users_router, "require_role", lambda b, u, m: "owner"), \
            mock.patch.object(financial_policy, "require_operational_write", lambda b: None), \
            mock.patch.object(payments_core.StripeAdapter, "create_invoice_checkout", fake_create):
        out = asyncio.run(invoice_checkout(InvoiceCheckoutBody(invoice_id=invoice["id"]),
                                           user=SimpleNamespace(id="user-1", email="o@example.com")))
    assert out["ok"] is True
    return seen


def test_the_apps_send_names_a_churchs_pay_link_bill_and_a_businesss_invoice():
    fresh = {**BILL, "stripe_payment_url": None}
    church = _checkout(CHURCH, fresh)
    assert church["kwargs"]["product_name"] == "Bill INV-2026-004"
    assert church["kwargs"]["invoice_number"] == "INV-2026-004" and church["kwargs"]["amount_cents"] == 25000
    # The endpoint reads what tells a church and a gift apart.
    assert "type" in church["business_select"] and "is_gift" in church["invoice_select"]
    assert _checkout(COACH, fresh)["kwargs"]["product_name"] == "Invoice INV-2026-004"
    # A business row with no type on it (older fixtures, a failed read) is an invoice.
    assert _checkout({k: v for k, v in COACH.items() if k != "type"}, fresh)["kwargs"]["product_name"] == "Invoice INV-2026-004"


# ─── The overdue reminder ─────────────────────────────────────────────

def _analyze(biz):
    posted = []
    overdue = {"id": "inv-1", "invoice_number": "INV-2026-004", "is_gift": False, "total": 250.0,
               "due_date": "2026-01-02", "contact_id": "c-1", "contacts": {"name": "Dana", "email": "dana@example.org"}}

    def fake_get(path):
        if path.startswith("/businesses"):
            return [deepcopy(biz)]
        if path.startswith("/invoices"):
            return [deepcopy(overdue)]
        return []

    def fake_post(path, body):
        posted.append((path, body))
        return [{"id": "p1", **body}]

    with mock.patch.object(rules_router.sb_clients, "sb_get_as_service", fake_get), \
            mock.patch.object(rules_router.sb_clients, "sb_post_as_service", fake_post):
        out = rules_router.analyze_ops(biz["id"], user=SimpleNamespace(id="user-1"))
    assert out["ok"] and len(posted) == 1 and posted[0][0] == "/chief_proposals"
    return posted[0][1]


def test_the_overdue_reminder_a_church_is_offered_says_bill():
    p = _analyze(CHURCH)
    assert p["proposal_type"] == "propose_followup_email" and p["proposed"]["invoice_id"] == "inv-1"
    assert p["proposed"]["subject"] == "A reminder about bill INV-2026-004"
    assert "bill INV-2026-004 ($250.00) was due on 2026-01-02" in p["proposed"]["body"]
    for line in (p["proposed"]["subject"], p["proposed"]["body"], p["reasoning"]):
        assert not SAYS_INVOICE.search(line) and "client" not in line, line
    assert p["proposed"]["contact_email"] == "dana@example.org"


def test_the_overdue_reminder_a_business_is_offered_is_the_one_it_had():
    p = _analyze(COACH)
    assert p["proposed"]["subject"] == "Friendly nudge — invoice INV-2026-004"
    assert p["proposed"]["body"].startswith("Hi Dana,\n\nJust a gentle reminder that invoice INV-2026-004 ($250.00) was due on 2026-01-02.")
    assert p["reasoning"].startswith("Invoice INV-2026-004 is ") and p["reasoning"].endswith(
        "overdue and Dana hasn't been nudged. Approve to send this reminder — nothing sends until you say so.")


# ─── What Chief is told for the emails it writes itself ───────────────

def test_chief_is_told_to_say_bill_to_a_churchs_payer_and_nothing_is_told_to_a_business():
    import church_findway
    menu = church_findway.menu_block(CHURCH)
    assert "call it a bill, never an invoice" in menu
    assert church_findway.menu_block(COACH) == ""

