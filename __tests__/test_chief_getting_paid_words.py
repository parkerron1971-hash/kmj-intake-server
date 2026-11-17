"""Chief sends people to the one place card payments are connected.

Card payments are connected on OPERATE → Payments (Stripe Connect), and
every invoice of a connected business gets its own pay link
(chief_of_staff.handle_create_invoice). Chief's instructions still
described the older way: paste a Stripe, Square or PayPal link on
BUILD → Integrations, with Connect "coming soon" and a per-invoice link
only for the platform owner. The app no longer offers the pasted links
card to anyone who has not already saved one (solutionist-studio#1606),
so those instructions sent people to a card that is not there.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMPT = (ROOT / "chief_prompt.py").read_text(encoding="utf-8")
PROXY = (ROOT / "stripe_proxy.py").read_text(encoding="utf-8")


def _block() -> str:
    start = PROMPT.index("GETTING PAID:\n")
    return PROMPT[start:start + 2600]


def test_the_block_names_payments_as_the_place_to_connect():
    block = _block()
    assert "OPERATE → Payments" in block
    assert '"tab":"operate","sub":"payments"' in block


def test_nobody_is_told_to_paste_a_new_link():
    block = _block()
    assert "Never tell anyone to paste a new link" in block
    assert "find Payment Providers, paste their link" not in PROMPT
    assert "Integrations → Payment Providers" not in PROMPT
    assert "Payment Providers" not in PROXY
    assert "paste your" not in PROXY


def test_connect_is_not_called_coming_soon():
    assert "will replace the manual paste flow" not in PROMPT
    assert "Don't promise auto-generation unless the practitioner is the platform owner" not in PROMPT
    assert 'never call it "coming soon"' in _block()


def test_a_link_saved_earlier_is_still_described_truthfully():
    block = _block()
    # It keeps working and is still shown on Integrations, where it can be
    # changed or switched off.
    assert "keeps working" in block
    assert "BUILD → Integrations" in block
    assert "settings.payment_providers" in block
