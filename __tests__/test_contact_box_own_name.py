"""The website contact form's texts box in the business's own name (2026-10-12).

Kevin asked whether the texting forms name the provider or just the business.
The booking page's boxes switch to the business's own name once its texting
registration is sent (#1377); the composed site's contact form kept saying
"from {business} via The Solutionist System". Pinned here:
  1. the box the site module really renders is found and switched: the
     platform's name out, the business's own texting pages linked, the rest
     of the disclosure (STOP, HELP, rates, not a condition) untouched;
  2. it switches only once the registration is sent (the booking page's rule,
     now shared), remembered for a few minutes, and a failed read leaves the
     box as built;
  3. every served page passes it (public_site._augment_html), and a page
     without the box doesn't ask.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import texting_registration as tr  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
ORIGIN = "https://andres.mysolutionist.app"
TERMS, PRIVACY = f"{ORIGIN}/texting-terms", f"{ORIGIN}/texting-privacy"


def box(name="Andre's Cuts & Co"):
    from site_modules import contact_footer
    return contact_footer._sms_consent_block({"contact": {"sms_capable": True}, "business": {"name": name}})


# ── 1. the box, switched ──────────────────────────────────────────────

def test_the_real_box_is_found_and_names_only_the_business():
    built = box()
    assert tr.CONTACT_MARK in built                     # the words the site module bakes in
    own = tr.contact_box_in_own_name(built, TERMS, PRIVACY)
    assert "Solutionist" not in own
    assert "from Andre&#x27;s Cuts &amp; Co (replies, confirmations, and reminders)." in " ".join(own.split())
    assert f'href="{TERMS}"' in own and f'href="{PRIVACY}"' in own
    for kept in ("Consent is", "not a condition of any purchase", "Message and data", "<strong>STOP</strong>",
                 "<strong>HELP</strong> for help.", 'name="sms_consent"'):
        assert kept in own, kept
    assert tr.contact_box_in_own_name(own, TERMS, PRIVACY) == own          # once only
    page = "<html><p>no texts box here</p></html>"
    assert tr.contact_box_in_own_name(page, TERMS, PRIVACY) == page


# ── 2. only once sent ─────────────────────────────────────────────────

def test_it_switches_only_once_the_registration_is_sent(monkeypatch):
    rows = {"row": None}
    reads = []
    monkeypatch.setattr(tr, "_PAGES_SEEN", {})
    monkeypatch.setattr(tr, "registration", lambda bid: reads.append(bid) or rows["row"])
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    assert tr.own_texting_pages(BIZ) is None                                  # nothing yet
    for status, sent in (("draft", False), ("failed", False), ("submitted", True), ("brand_pending", True),
                         ("campaign_pending", True), ("approved", True)):
        assert tr.is_sent({"status": status}) is sent, status
    assert tr.is_sent({"status": "failed", "twilio": {"profile_submitted": True}})   # sent, then sent back
    monkeypatch.setattr(tr, "_PAGES_SEEN", {})
    rows["row"] = {"status": "brand_pending"}
    assert tr.own_texting_pages(BIZ) == {"terms": TERMS, "privacy": PRIVACY}
    reads.clear()
    tr.own_texting_pages(BIZ)
    assert reads == []                                                        # remembered
    monkeypatch.setattr(tr, "_PAGES_SEEN", {})

    def broken(bid):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(tr, "registration", broken)
    assert tr.own_texting_pages(BIZ) is None and BIZ not in tr._PAGES_SEEN     # as built, asked again next time


def test_the_booking_page_uses_the_same_rule():
    src = pathlib.Path(tr.__file__).resolve().parent.joinpath("booking_widget_router.py").read_text(encoding="utf-8")
    assert "tr.is_sent(tr.registration(bid))" in src and "_TEXTING_SENT" not in src


# ── 3. every served page ──────────────────────────────────────────────

def test_a_visitor_sees_the_switched_box(monkeypatch):
    import public_site as ps

    async def _no_rows(client, path):
        return []
    asked = []
    monkeypatch.setattr(ps, "_sb", _no_rows)
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz_id: html)
    monkeypatch.setattr(ps, "_optimize_images", lambda html: html, raising=False)
    monkeypatch.setattr(tr, "own_texting_pages", lambda bid: asked.append(bid) or {"terms": TERMS, "privacy": PRIVACY})
    page = f"<html><body><form>{box('Grace Salon')}</form></body></html>"
    served = asyncio.run(ps._augment_html(None, BIZ, "grace", page))
    assert "via The Solutionist System" not in served and f'href="{TERMS}"' in served and asked == [BIZ]
    asked.clear()
    plain = asyncio.run(ps._augment_html(None, BIZ, "grace", "<html><body><p>Hi</p></body></html>"))
    assert asked == [] and "Texting terms" not in plain                       # no box, no question
    monkeypatch.setattr(tr, "own_texting_pages", lambda bid: None)            # not sent: as built
    assert "via The Solutionist System" in asyncio.run(ps._augment_html(None, BIZ, "grace", page))
