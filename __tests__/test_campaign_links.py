"""Tracked links on campaign texts and emails (2026-10-09).

The Reach plan's step 1: "links on texts, emails and offers too". A
campaign touch that says {{link}} sends that touch's own short link
({origin}/go/{code}, the same redirect a desk post's link uses), so a tap
and the visit, booking and payment after it count for the touch
(utm_content = the link's id).
"""
from __future__ import annotations

import asyncio
import copy
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import business_marketing_links as links  # noqa: E402
import business_marketing_sent_links as sl  # noqa: E402
import business_marketing_store as store  # noqa: E402
import campaigns_router as cr  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
CAMP = "11111111-2222-4333-8444-555555555555"
SITE = {"business_id": BIZ, "slug": "fade-street", "published": True, "custom_domain": None,
        "custom_domain_status": None}


def run(x):
    return asyncio.run(x)


# ── the link itself ───────────────────────────────────────────────────

def test_one_link_per_touch_derived_never_a_posts():
    a, b = sl.link_id("campaign", CAMP, 0), sl.link_id("campaign", CAMP, 1)
    assert a == sl.link_id("campaign", CAMP, 0) and a != b                  # the same for everyone, per touch
    assert store.GO_CODE.match(sl.link_code(a))
    assert sl.link_code(a) != store.link_code(a)                            # never a post's code for the same id
    with pytest.raises(ValueError):
        sl.link_id("offer", CAMP, 0)                                        # offers come later


def test_the_tracked_url_carries_the_touch_and_stays_on_the_business_site(monkeypatch):
    lid = sl.link_id("campaign", CAMP, 2)
    url = sl.tracked_url("https://fade-street.mysolutionist.app/book?x=1", lid, SITE, channel="sms", campaign_id=CAMP)
    q = parse_qs(urlsplit(url).query)
    assert urlsplit(url).netloc == "fade-street.mysolutionist.app" and q["x"] == ["1"]
    assert q["utm_content"] == [lid] and q["utm_source"] == ["sms"] and q["utm_medium"] == ["outreach"]
    assert q["utm_campaign"] == [CAMP]
    with pytest.raises(ValueError):
        sl.tracked_url("https://evil.example/", lid, SITE, channel="sms", campaign_id=CAMP)
    with pytest.raises(ValueError):
        sl.tracked_url("https://fade-street.mysolutionist.app/", lid, SITE, channel="fax", campaign_id=CAMP)


def test_the_words_carry_the_link_or_leave_the_token_out():
    assert sl.fill("Book here: {{link}}", "https://x/go/abcd2345") == "Book here: https://x/go/abcd2345"
    assert sl.fill("Come back soon {{link}}\nReply STOP to opt out.", None) == "Come back soon\nReply STOP to opt out."
    assert sl.fill("No link here.", "https://x") == "No link here."
    assert sl.wants_link("a {{link}}") and not sl.wants_link(None)


def test_campaign_link_is_made_once_on_the_business_site(monkeypatch):
    writes = []
    monkeypatch.setattr(links, "site_for", lambda bid: SITE)
    monkeypatch.setattr(links, "default_landing", lambda bid, biz, site: "https://fade-street.mysolutionist.app/book")

    async def request(method, path, body=None):
        writes.append((method, path, body))
        if len(writes) > 1:
            raise store.StoreConflict("duplicate")                          # the touch's earlier send made it
        return [body]

    monkeypatch.setattr(store, "request", request)
    first = run(sl.campaign_link({"id": BIZ}, CAMP, 0, "email"))
    again = run(sl.campaign_link({"id": BIZ}, CAMP, 0, "email"))
    lid = sl.link_id("campaign", CAMP, 0)
    assert first == again == f"https://fade-street.mysolutionist.app/go/{sl.link_code(lid)}"
    method, path, row = writes[0]
    assert (method, path) == ("POST", "/marketing_links")
    assert row["id"] == lid and row["business_id"] == BIZ and row["kind"] == "campaign" and row["part"] == 0
    assert row["landing_url"].endswith("/book") and f"utm_content={lid}" in row["tracked_url"]


def test_no_site_means_no_link(monkeypatch):
    monkeypatch.setattr(links, "site_for", lambda bid: SITE)
    monkeypatch.setattr(links, "default_landing", lambda bid, biz, site: None)

    async def request(*a, **k):
        raise AssertionError("nothing is written without a landing")

    monkeypatch.setattr(store, "request", request)
    assert run(sl.campaign_link({"id": BIZ}, CAMP, 0, "email")) is None


def test_the_redirect_falls_back_to_links_in_the_migration():
    sql = (pathlib.Path(__file__).resolve().parent.parent / "supabase" / "APPLY-2026-10-09-marketing-links.sql").read_text()
    follow = sql[sql.index("CREATE OR REPLACE FUNCTION public.marketing_follow"):]
    assert follow.index("FROM public.marketing_posts") < follow.index("FROM public.marketing_links")   # a post wins
    assert "INSERT INTO public.marketing_link_hits" in follow and "IF p_count_click THEN" in follow
    assert "REVOKE ALL ON public.marketing_links, public.marketing_link_hits FROM PUBLIC, anon, authenticated" in sql


# ── the sweep ─────────────────────────────────────────────────────────

class Sweep:
    """campaigns_tick's world: one running campaign, its audience, the sends
    ledger, and the email door."""

    def __init__(self, monkeypatch, touches):
        start = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.camp = {"id": CAMP, "business_id": BIZ, "name": "Come back", "status": "running", "start_at": start,
                     "touches": touches, "audience": {"kind": "silent"}}
        self.biz = {"id": BIZ, "name": "Fade Street", "settings": {}}
        self.contacts = [{"id": f"c{i}", "name": f"Pat {i}", "email": f"p{i}@example.com"} for i in range(3)]
        self.sends, self.emails, self.patches, self.links = [], [], [], []
        import email_sender
        import rules_engine

        def get(path):
            if path.startswith("/campaigns?status=eq.running"):
                return [copy.deepcopy(self.camp)]
            if path.startswith("/campaign_sends"):
                return copy.deepcopy(self.sends)
            if path.startswith("/businesses"):
                return [self.biz]
            return []

        def post(path, body):
            if path == "/campaign_sends":
                self.sends.append(body)
                return [body]
            return [body]

        async def send(**kw):
            self.emails.append(kw)

        async def suppressed(addr):
            return False

        async def link(biz, cid, part, channel):
            self.links.append((cid, part, channel))
            if getattr(self, "link_down", False):
                raise links.LinksUnavailable("site unreadable")
            return "https://fade-street.mysolutionist.app/go/abcd2345"

        monkeypatch.setattr(cr.sb_clients, "sb_get_as_service", get)
        monkeypatch.setattr(cr.sb_clients, "sb_post_as_service", post)
        monkeypatch.setattr(cr.sb_clients, "sb_patch_as_service", lambda path, body: self.patches.append(body) or [body])
        monkeypatch.setattr(cr, "_resolve_audience", lambda bid, aud: copy.deepcopy(self.contacts))
        monkeypatch.setattr(cr, "SEND_PACING_SEC", 0)
        monkeypatch.setattr(email_sender, "send_via_resend", send)
        monkeypatch.setattr(email_sender, "is_suppressed", suppressed)
        monkeypatch.setattr(email_sender, "build_routed_reply_to", lambda b, c: None)
        monkeypatch.setattr(rules_engine, "business_paused", lambda biz: False)
        monkeypatch.setattr(sl, "campaign_link", link)


def test_a_touch_with_link_sends_its_tracked_link_made_once(monkeypatch):
    w = Sweep(monkeypatch, [{"channel": "email", "offset_days": 0, "subject": "Hi",
                             "body": "Hi {{first_name}}, book your next cut: {{link}}"}])
    stats = run(cr.campaigns_tick())
    assert stats["emails"] == 3
    assert w.links == [(CAMP, 0, "email")]                                  # one link for the whole touch
    assert all(e["body"].endswith("book your next cut: https://fade-street.mysolutionist.app/go/abcd2345")
               for e in w.emails)
    assert "{{link}}" not in "".join(e["body"] for e in w.emails)


def test_a_link_that_cannot_be_made_holds_the_touch_and_sends_nothing(monkeypatch):
    w = Sweep(monkeypatch, [{"channel": "email", "offset_days": 0, "subject": "Hi", "body": "Book: {{link}}"}])
    w.link_down = True
    stats = run(cr.campaigns_tick())
    assert stats["emails"] == 0 and w.emails == [] and w.sends == []        # nothing claimed: a later tick sends
    assert not any(p.get("status") == "completed" for p in w.patches)
    w.link_down = False
    assert run(cr.campaigns_tick())["emails"] == 3


def test_a_touch_without_link_makes_none(monkeypatch):
    w = Sweep(monkeypatch, [{"channel": "email", "offset_days": 0, "subject": "Hi", "body": "Just saying hi."}])
    run(cr.campaigns_tick())
    assert w.links == [] and len(w.emails) == 3 and w.emails[0]["body"] == "Just saying hi."


def test_launch_refuses_link_with_nowhere_to_go(monkeypatch):
    monkeypatch.setattr(links, "site_for", lambda bid: None)
    monkeypatch.setattr(links, "default_landing", lambda bid, biz, site: None)
    with pytest.raises(cr.HTTPException) as e:
        cr._require_link_destination({"id": BIZ})
    assert e.value.status_code == 409 and "{{link}}" in e.value.detail

    def down(bid):
        raise links.LinksUnavailable("x")

    monkeypatch.setattr(links, "site_for", down)
    with pytest.raises(cr.HTTPException) as e:
        cr._require_link_destination({"id": BIZ})
    assert e.value.status_code == 503


def test_chief_is_told_how_to_place_the_link():
    src = (pathlib.Path(cr.__file__)).read_text(encoding="utf-8")
    assert re.search(r"write \{\{link\}\} once", src) and "Never write any other web address" in src
