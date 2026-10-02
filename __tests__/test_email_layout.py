"""The shape a business email leaves in.

Covers: brand kit reading (both shapes, bad colours, http logos),
placeholder filling (first name, empty closing line, unknown tokens
untouched), the signature round-trip (plaintext appended by Chief is
recognised and rendered as the designed block), paragraph layout and
escaping, the composed trailers, and the send seam: a business send goes
out as html + text, an explicit-HTML body is untouched, platform mail
with no business stays plain. Plus the preview endpoint's gate.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import email_layout as L  # noqa: E402
import email_sender  # noqa: E402


SIG = {"name": "Sarah Okafor", "title": "Owner", "business": "Studio K",
       "phone": "(415) 555-0142", "email": "hello@studiok.com",
       "link_page_url": "https://studiok.com/book"}
SETTINGS = {
    "brand_kit": {"colors": {"primary": "#0f766e"}, "logo_url": "https://cdn.example/logo.png",
                  "tagline": "Movement for busy people"},
    "email_templates": {"signature": SIG,
                        "global_rules": {"closing_line": "Warmly,", "always_include_signature": True,
                                         "disclaimer": "Not medical advice."}},
}
BIZ = {"id": "b1", "name": "Studio K", "settings": SETTINGS}


# ─── brand + settings ────────────────────────────────────────────────


def test_brand_reads_both_shapes_and_rejects_junk():
    assert L.brand_of(SETTINGS)["primary"] == "#0f766e"
    flat = L.brand_of({"brand_kit": {"primary_color": "#ABC"}})
    assert flat["primary"] == "#ABC"
    bad = L.brand_of({"brand_kit": {"primary_color": "red; background:url(x)"}})
    assert bad["primary"] == L.DEFAULT_ACCENT
    assert L.brand_of({"brand_kit": {"logo_url": "http://insecure/logo.png"}})["logo_url"] == ""
    assert L.brand_of(None)["primary"] == L.DEFAULT_ACCENT


# ─── placeholders ────────────────────────────────────────────────────


def test_placeholders_use_first_name_and_business_values():
    v = L.placeholder_values(BIZ, contact_name="Jordan Lee")
    out = L.fill_placeholders("Hi {contact_name}, welcome to {business_name}. {practitioner_name} here. {closing_line}", v)
    assert out == "Hi Jordan, welcome to Studio K. Sarah Okafor here. Warmly,"


def test_empty_value_does_not_leave_a_dangling_comma_and_unknown_tokens_survive():
    v = L.placeholder_values({"id": "b", "name": "X", "settings": {}}, contact_name=None)
    assert L.fill_placeholders("Hi {contact_name}, see {weird_token}", v) == "Hi there, see {weird_token}"
    v2 = dict(v, closing_line="")
    assert L.fill_placeholders("Thanks {closing_line} !", v2) == "Thanks!"


# ─── signature round-trip ────────────────────────────────────────────


def test_chief_appended_signature_is_recognised_and_rendered_as_a_block():
    composed = L.compose_trailers("Hi Jordan,\n\nThursday at 5:30 works.", SETTINGS)
    assert composed.endswith("--\nNot medical advice.")
    assert L.signature_plaintext(SIG) in composed
    msg, had_sig, disc = L.split_trailers(composed, SIG, "Not medical advice.")
    assert had_sig and disc == "Not medical advice."
    assert msg == "Hi Jordan,\n\nThursday at 5:30 works.\n\nWarmly,"
    html, text = L.render_for_send(composed, BIZ, unsubscribe_url="https://u/x")
    assert "Sarah Okafor" in html and 'style="color:#0f766e;font-size:12px;"' in html  # link in brand colour
    assert 'href="https://studiok.com/book"' in html
    assert "Not medical advice." in html
    assert text.startswith("Hi Jordan,")            # text alternative is the composed body
    assert L.signature_plaintext(SIG) in text


def test_body_without_signature_gets_no_signature_block():
    html, _ = L.render_for_send("Just a note.", BIZ)
    assert "Sarah Okafor" not in html


# ─── layout ──────────────────────────────────────────────────────────


def test_paragraphs_breaks_links_and_escaping():
    h = L.paragraphs_html("Line one\nLine two\n\nSecond para <b>bold</b> https://x.y/z")
    assert h.count("<p ") == 2
    assert "Line one<br />Line two" in h
    assert "&lt;b&gt;bold&lt;/b&gt;" in h                 # user text is never markup
    assert '<a href="https://x.y/z"' in h


def test_render_html_carries_brand_logo_wordmark_and_footer():
    html = L.render_html("Hello.", business_name="Studio K", brand=L.brand_of(SETTINGS),
                         unsubscribe_url="https://u/x")
    assert 'src="https://cdn.example/logo.png"' in html
    assert "background:#0f766e" in html                  # the brand rule at the top
    assert "Movement for busy people" in html
    assert 'href="https://u/x"' in html and "Unsubscribe" in html
    nologo = L.render_html("Hello.", business_name="Studio <K>", brand=L.brand_of({}))
    assert "Studio &lt;K&gt;" in nologo and "<img" not in nologo   # wordmark, escaped


# ─── the send seam ───────────────────────────────────────────────────


class _Resp:
    status_code = 200
    text = '{"id":"msg_1"}'

    def json(self):
        return {"id": "msg_1"}


_LAST = {}


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _LAST["payload"] = json
        return _Resp()


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _FakeClient)

    async def _not_suppressed(email):
        return None
    monkeypatch.setattr(email_sender, "is_suppressed", _not_suppressed)

    async def _row(business_id=None, biz_prefix=None):
        return BIZ if (business_id == "b1" or biz_prefix) else None
    monkeypatch.setattr(email_sender, "_business_identity_row", _row)
    _LAST.clear()


def _send(**kw):
    base = dict(to_email="jordan@example.com", to_name="Jordan", from_email=email_sender.DEFAULT_FROM_EMAIL,
                from_name="Platform", subject="Hi", body="Hi Jordan,\n\nSee you Thursday.", reply_to=None)
    base.update(kw)
    return asyncio.run(email_sender.send_via_resend(**base))


def test_business_send_goes_out_as_html_plus_text(wired):
    _send(business_id="b1")
    p = _LAST["payload"]
    assert "html" in p and "text" in p
    assert "<p " in p["html"] and "See you Thursday." in p["html"]
    assert p["text"].startswith("Hi Jordan,")
    assert "Unsubscribe" in p["html"]


def test_explicit_html_body_is_left_alone(wired):
    _send(business_id="b1", body="<div><p>custom</p></div>")
    p = _LAST["payload"]
    assert p["html"] == "<div><p>custom</p></div>" and "text" not in p


def test_platform_mail_without_a_business_stays_plain(wired, monkeypatch):
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "")
    _send(business_id=None, reply_to=None)
    p = _LAST["payload"]
    assert p.get("text") == "Hi Jordan,\n\nSee you Thursday." and "html" not in p


def test_layout_failure_never_blocks_the_send(wired, monkeypatch):
    import email_layout

    def _boom(*a, **k):
        raise RuntimeError("layout bug")
    monkeypatch.setattr(email_layout, "render_for_send", _boom)
    _send(business_id="b1")
    p = _LAST["payload"]
    assert p.get("text") == "Hi Jordan,\n\nSee you Thursday." and "html" not in p


# ─── preview endpoint ────────────────────────────────────────────────


def test_preview_composes_and_renders(monkeypatch):
    import business_access

    monkeypatch.setattr(business_access, "assert_access", lambda *a, **k: None)

    async def _row(business_id=None, biz_prefix=None):
        return BIZ
    monkeypatch.setattr(email_sender, "_business_identity_row", _row)
    req = email_sender.EmailPreviewRequest(business_id="b1", body="Hi {contact_name},\n\nWelcome to {business_name}.",
                                           subject="Welcome, {contact_name}", contact_name="Maya Patel")
    out = asyncio.run(email_sender.email_preview(req, user=type("U", (), {"id": "u1"})()))
    assert out["subject"] == "Welcome, Maya"
    assert "Welcome to Studio K." in out["html"]
    assert "Sarah Okafor" in out["html"]                  # signature appended the way a send would
    assert "Warmly," in out["text"]
    assert out["from_email"]


# ─── the closing line is its own paragraph ───────────────────────────


def test_inline_closing_line_gets_its_own_paragraph():
    assert L.break_before_closing("Thanks for reading. Best,", "Best,") == "Thanks for reading.\n\nBest,"
    assert L.break_before_closing("Thanks for reading.\n\nBest,", "Best,") == "Thanks for reading.\n\nBest,"   # already its own
    assert L.break_before_closing("Best,", "Best,") == "Best,"
    assert L.break_before_closing("No closing here.", "Best,") == "No closing here."


def test_render_breaks_an_inline_closing_before_the_signature():
    composed = L.compose_trailers("Hi Jordan, welcome aboard. Warmly,", SETTINGS)
    html, _ = L.render_for_send(composed, BIZ)
    assert "welcome aboard.</p>" in html and ">Warmly,</p>" in html
