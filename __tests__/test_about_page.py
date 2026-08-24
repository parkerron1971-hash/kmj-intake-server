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


class TestEveryProcessorIsDisclosed:
    """The Privacy Policy went seven weeks naming eight processors while
    the product had quietly connected several more. A disclosure that
    lags the code is the failure mode here, so these pin the list to
    things that are demonstrably in the request path -- not to a
    hand-kept inventory that drifts the same way the last one did.
    """

    def test_the_ai_and_data_processors_are_named(self):
        privacy = legal_content.render_privacy_html()
        for vendor in ("Anthropic", "OpenAI", "Supabase", "Railway",
                       "Twilio", "Stripe", "Plaid"):
            assert _discloses(privacy, vendor), f"{vendor} is not disclosed"
        assert "Meta Platforms" in privacy

    def test_a_mounted_google_integration_is_disclosed(self):
        """gmail.readonly is a restricted scope. If the router is mounted,
        the policy has to say so -- Google's own verification checks it."""
        import kmj_intake_automation as app_module
        mounted = "include_router(google_router)" in _source(app_module)
        if not mounted:
            pytest.skip("Google OAuth router is not mounted")
        privacy = legal_content.render_privacy_html()
        assert _discloses(privacy, "Google"), (
            "Google needs its own entry in the processor list -- mentioning "
            "the word elsewhere in the prose is not a disclosure")
        assert "gmail.readonly" in privacy, (
            "the policy must name the actual scope requested")

    def test_a_mounted_quickbooks_integration_is_disclosed(self):
        import kmj_intake_automation as app_module
        if "include_router(quickbooks_router)" not in _source(app_module):
            pytest.skip("QuickBooks router is not mounted")
        assert _discloses(legal_content.render_privacy_html(), "Intuit")

    def test_the_mail_path_is_disclosed(self):
        """Resend sends and SES receives. Both handle message content."""
        privacy = legal_content.render_privacy_html()
        assert _discloses(privacy, "Resend")
        assert _discloses(privacy, "Amazon Web Services")

    def test_the_public_ledger_anchor_is_disclosed_as_public(self):
        """Anchoring writes to a permanent public network. The policy has
        to say both that only a hash goes out AND that what goes out
        cannot be deleted -- the second half is the part a reader needs
        and the part that is easy to leave off."""
        privacy = legal_content.render_privacy_html()
        assert "Hedera" in privacy
        low = privacy.lower()
        assert "hash" in low
        assert "public" in low
        assert "cannot be deleted" in low or "permanent" in low

    def test_the_policy_was_updated_when_the_processors_were(self):
        """A disclosure edit with a stale date reads as an older policy
        than it is."""
        assert legal_content.LAST_UPDATED_DATE == "August 23, 2026"


def _source(module):
    import inspect
    return inspect.getsource(module)


def _discloses(privacy_html: str, vendor: str) -> bool:
    """True only when the vendor has its OWN entry in the processor list.

    A substring check is not enough and the rehearsal proved it: deleting
    Google from the list left the test green, because the prose further
    down still said "your Google account's security settings". A named
    processor is a <li><strong>Name</strong> row, so that is what this
    looks for.
    """
    return f"<li><strong>{vendor}" in privacy_html


class TestPublicContactAddress:
    """Mail should land in the product, not a personal mailbox — but only
    once an address that actually receives mail exists."""

    def test_falls_back_to_the_real_mailbox_when_inbound_is_not_configured(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.delenv("INBOUND_EMAIL_DOMAIN", raising=False)
        assert marketing_pages._public_contact_email() == marketing_pages.CONTACT_EMAIL

    def test_uses_info_at_the_inbound_domain_once_it_is_live(self, monkeypatch):
        """Kevin, 2026-08-23: the published local is `info`. It was
        `hello` here while the legal pages were still printing a personal
        Gmail -- two addresses for one company. One resolver owns both
        now (platform_addresses), and the drift test below holds them
        together."""
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        assert marketing_pages._public_contact_email() == "info@mysolutionist.app"

    def test_an_explicit_override_wins(self, monkeypatch):
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        monkeypatch.setenv("PUBLIC_CONTACT_EMAIL", "team@mysolutionist.app")
        assert marketing_pages._public_contact_email() == "team@mysolutionist.app"

    def test_the_published_locals_are_ones_the_inbox_actually_claims(self):
        """Both locals have to be in the platform inbox list or the mail
        lands in the contact-reply pipeline instead of Mission Control.
        This coupling is what makes publishing an address safe at all."""
        import email_sender
        import platform_addresses
        claimed = email_sender.PLATFORM_INBOX_DEFAULT_LOCALS.split(",")
        assert platform_addresses.PUBLIC_CONTACT_LOCAL in claimed
        assert platform_addresses.OPERATOR_LOCAL in claimed

    def test_the_legal_pages_and_the_marketing_pages_agree(self, monkeypatch):
        """The bug this class now exists to prevent: marketing_pages
        derived its address while legal_content held its own constant, so
        /about and /privacy printed different ways to reach the same
        company. Two modules, one resolver, one address."""
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        addr = marketing_pages._public_contact_email()
        assert addr in legal_content.render_privacy_html()
        assert addr in legal_content.render_help_html()
        assert addr in marketing_pages.render_about()

    def test_operator_mail_is_not_the_published_address(self, monkeypatch):
        """Lead alerts are internal. They go to the operator local, which
        is deliberately NOT the one on the Privacy Policy, so inbound
        customer mail and "a lead came in" stay separable in the inbox."""
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.delenv("PLATFORM_OPERATOR_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        import platform_addresses
        assert platform_addresses.operator_email() == "admin@mysolutionist.app"
        assert (platform_addresses.operator_email()
                != platform_addresses.public_contact_email())

    def test_the_operator_address_can_be_put_back_on_a_phone(self, monkeypatch):
        """One env var returns lead alerts to a personal mailbox if the
        Mission Control inbox is not being watched."""
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        monkeypatch.setenv("PLATFORM_OPERATOR_EMAIL", "someone@gmail.com")
        import platform_addresses
        assert platform_addresses.operator_email() == "someone@gmail.com"

    def test_the_whole_site_prints_the_resolved_address(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        for f in ("render_about", "render_home", "render_faq"):
            html = getattr(marketing_pages, f)()
            assert "info@mysolutionist.app" in html, f"{f} still prints the old address"

    def test_no_public_page_prints_the_founder_gmail(self, monkeypatch):
        """The guard the sentinel substitution leans on.

        `_fill_contact` returns the html untouched when the token is
        absent -- a deliberately silent no-op, because a renderer that
        raises would turn a cosmetic problem into a 500. That makes a
        hardcoded address exactly the kind of thing that ships quietly,
        which is what had already happened twice (the FAQ body and the
        get-started error toast). So this renders every page on the site
        and fails if the literal survives anywhere, or if a sentinel ever
        reaches a visitor unsubstituted.
        """
        monkeypatch.delenv("PUBLIC_CONTACT_EMAIL", raising=False)
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
        import platform_addresses
        pages = [(marketing_pages, n) for n in dir(marketing_pages)
                 if n.startswith("render_")]
        pages += [(legal_content, n) for n in dir(legal_content)
                  if n.startswith("render_") and n != "render_page"]
        rendered = 0
        for mod, name in pages:
            try:
                html = getattr(mod, name)()
            except TypeError:
                continue          # renderers that take arguments
            if not isinstance(html, str):
                continue
            rendered += 1
            assert platform_addresses.FOUNDER_FALLBACK_EMAIL not in html, (
                f"{mod.__name__}.{name} still prints the founder Gmail")
            assert marketing_pages.CONTACT_TOKEN not in html, (
                f"{mod.__name__}.{name} leaked an unsubstituted sentinel")
            assert "hello@mysolutionist.app" not in html, (
                f"{mod.__name__}.{name} still prints the old hello@ address")
        assert rendered >= 10, (
            f"only {rendered} pages rendered -- the sweep stopped finding them")


def test_cards_are_styled_on_every_page_that_prints_them():
    """/download printed .company-card three times and had never carried
    the rule — it lived in render_about's extra_css, which no other page
    can reach, and this pass deleted it from there."""
    for f in MARKETING:
        html = getattr(marketing_pages, f)()
        if 'class="company-card' in html:
            assert ".company-card{" in html, f"{f} prints unstyled cards"

class TestTheIntakeFlowSpeaksAsATeam:
    """Kevin, 2026-08-20: "Solutionist Team or someone from the team".

    /about stopped being a bio in the same pass, but the moment someone
    actually applies was still a named personal promise: the page said
    "Kevin reaches out", the confirmation email said the same, was signed
    with his full name and title, and arrived from "Kevin at Solutionist".
    """

    def test_the_page_promises_the_team(self):
        html = marketing_pages.render_get_started()
        assert "Someone from the team reaches out" in html
        for named in ("Kevin", "McCloud", "He&rsquo;ll", "He'll"):
            assert named not in html

    def test_the_confirmation_email_does_too(self):
        """The body is built inside the /api/leads handler, so this reads
        the template it is built from rather than sending real mail."""
        src = pathlib.Path(marketing_pages.__file__).read_text(encoding="utf-8")
        block = src.split("lead_subject = ", 1)[1].split("except Exception", 1)[0]
        assert "Someone from the team will reach out" in block
        assert "The Solutionist Team" in block
        assert "Kevin" not in block and "McCloud" not in block
        assert 'from_name="The Solutionist Team"' in block

    def test_a_reply_reaches_the_inbox_the_copy_promises(self, monkeypatch):
        """The mail says "it comes straight to the team", so Reply-To has
        to be the resolved public address, not a hardcoded mailbox."""
        src = pathlib.Path(marketing_pages.__file__).read_text(encoding="utf-8")
        block = src.split("lead_subject = ", 1)[1].split("except Exception", 1)[0]
        assert "reply_to=_public_contact_email()" in block
