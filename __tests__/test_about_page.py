"""The About page is about why the system exists, not who built it.

Rewritten 2026-08-20. Kevin's ask, in his words: not about him, no
mention of where it was created, no stack on display, and contact should
be an address that lands in the system's own inbox.

The old page opened on a founder card with his name, avatar and
signature, said "a small Michigan LLC" in the lead, gave the founding
state its own line in a company card, and published a Stack card listing
the client framework, the server framework, the host, the database, the
mail provider and the AI vendor — an inventory of the attack surface,
printed for no visitor's benefit.

What these pin is the removal, plus the one distinction that matters:
the location comes off the MARKETING pages and stays in the Terms and
the Privacy Policy, where governing law and the registered entity are
legal statements rather than copy.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import legal_content
import marketing_pages


MARKETING = ("render_home", "render_features", "render_compare", "render_faq",
             "render_about", "render_download", "render_get_started")


def _marketing_html() -> str:
    return "".join(getattr(marketing_pages, f)() for f in MARKETING)


def test_the_about_page_is_not_about_a_person():
    html = marketing_pages.render_about()
    for trace in ("founder-avatar", "founder-sig", "From the founder",
                  "Kevin", "McCloud", "I built", "I'd love to talk"):
        assert trace not in html, f"the founder note left {trace!r} behind"


def test_it_says_why_instead():
    html = marketing_pages.render_about()
    assert "Why this exists" in html
    assert "The work was never" in html
    # the argument itself, not a bio
    assert "integration layer" in html
    assert "Three principles we won" in html


def test_the_marketing_site_no_longer_says_where_it_was_made():
    html = _marketing_html()
    assert "Michigan" not in html
    assert "Michigan, USA" not in html


def test_but_the_legal_pages_still_do():
    """Governing law and the registered entity are not marketing copy.

    Stripping the state from the Terms would change what the document
    says about which law governs it. This guards against a future
    "remove the location" pass reaching too far.
    """
    assert "Michigan" in legal_content.render_terms_html()
    assert "Michigan" in legal_content.render_privacy_html()


def test_the_stack_is_not_on_display():
    html = marketing_pages.render_about()
    for tech in ("FastAPI", "Tauri", "Supabase", "Railway", "Vite", "Anthropic"):
        assert tech not in html, f"/about still advertises {tech}"


def test_the_subprocessor_list_stays_where_it_belongs():
    """Naming infrastructure is a privacy disclosure, not a brag card."""
    privacy = legal_content.render_privacy_html()
    assert "Supabase" in privacy and "Railway" in privacy


class TestPublicContactAddress:
    """Mail should land in the product, not a personal mailbox — but only
    once an address that actually receives mail exists."""

    def test_falls_back_to_the_real_mailbox_when_inbound_is_not_configured(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.delenv("INBOUND_EMAIL_DOMAIN", raising=False)
        assert marketing_pages._public_contact_email() == marketing_pages.CONTACT_EMAIL

    def test_uses_hello_at_the_inbound_domain_once_it_is_live(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        assert marketing_pages._public_contact_email() == "hello@mysolutionist.app"

    def test_an_explicit_override_wins(self, monkeypatch):
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        monkeypatch.setenv("PUBLIC_CONTACT_EMAIL", "team@mysolutionist.app")
        assert marketing_pages._public_contact_email() == "team@mysolutionist.app"

    def test_the_published_local_part_is_one_the_inbox_actually_claims(self):
        """`hello` has to be in the platform inbox list or the mail lands
        in the contact-reply pipeline instead of Mission Control."""
        import email_sender
        assert "hello" in email_sender.PLATFORM_INBOX_DEFAULT_LOCALS.split(",")

    def test_the_whole_site_prints_the_resolved_address(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        for f in ("render_about", "render_home", "render_faq"):
            html = getattr(marketing_pages, f)()
            assert "hello@mysolutionist.app" in html, f"{f} still prints the old address"


def test_cards_are_styled_on_every_page_that_prints_them():
    """/download printed .company-card three times and had never carried
    the rule — it lived in render_about's extra_css, which no other page
    can reach, and this pass deleted it from there."""
    for f in MARKETING:
        html = getattr(marketing_pages, f)()
        if 'class="company-card' in html:
            assert ".company-card{" in html, f"{f} prints unstyled cards"
