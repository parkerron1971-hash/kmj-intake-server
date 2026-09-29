# __tests__/test_member_portal_sms.py
#
# Signing in with a mobile number (member_portal.py). Pins:
#   1. an email or a number is one identity: normalised to E.164, shown
#      back as (555) 010-2030
#   2. the number matches however the office typed it, and one person per
#      number (a shared number signs nobody in)
#   3. a known number is TEXTED (not emailed); an unknown one gets the same
#      page and nothing; the code works and the session keys on the number
#   4. the text never goes through the stored-history sender, and never
#      to a number that opted out

import pathlib
import sys
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp

BIZ = "11111111-1111-1111-1111-111111111111"
HOST = "first-light.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")


# ─── 1. identity ─────────────────────────────────────────────────────


def test_an_email_or_a_number():
    assert mp.norm_ident("Ana@Example.com ") == "ana@example.com"
    assert mp.norm_ident("(555) 010-2030") == "+15550102030"
    assert mp.norm_ident("555.010.2030") == "+15550102030"
    assert mp.norm_ident("+1 (555) 010 2030") == "+15550102030"
    assert mp.norm_ident("hello") == ""
    assert mp.norm_ident("123") == ""
    assert mp.valid_ident("+15550102030") and not mp.valid_ident("5550102030")
    assert mp.show_ident("+15550102030") == "(555) 010-2030"
    assert mp._last10("(555) 010-2030 x2") == "5550102030"
    assert mp._last10("+1 555-010-2030 ext. 12") == "5550102030"


# ─── fake ────────────────────────────────────────────────────────────


def _q(path, name):
    return urllib.parse.parse_qs(path.split("?", 1)[1]).get(name, [""])[0]


class Fake:
    def __init__(self):
        self.contacts = [{"id": "c1", "business_id": BIZ, "name": "Ana Rivers",
                          "email": "ana@example.com", "phone": "(555) 010-2030 x2"}]
        self.codes = []

    def get(self, path):
        biz = _q(path, "business_id").removeprefix("eq.")
        if path.startswith("/contacts"):
            like = _q(path, "phone")
            if like.startswith("like."):
                digits = like.removeprefix("like.").replace("*", "")
                return [dict(c) for c in self.contacts if c["business_id"] == biz
                        and digits in "".join(ch for ch in c["phone"] if ch.isdigit())]
            em = _q(path, "email").removeprefix("ilike.").replace("\\", "").lower()
            return [dict(c) for c in self.contacts if c["business_id"] == biz and c["email"].lower() == em]
        if path.startswith("/member_login_codes"):
            ident = _q(path, "email").removeprefix("eq.")
            mine = [c for c in self.codes if c["email"] == ident]
            if "consumed_at=is.null" in path:
                live = [c for c in mine if c["consumed_at"] is None]
                return [dict(live[-1])] if live else []
            return [dict(c) for c in mine]
        return []

    def post(self, path, body, prefer=None):
        row = {**body, "id": f"k{len(self.codes)}", "attempts": 0, "consumed_at": None, "succeeded": False}
        self.codes.append(row)
        return [row]

    def patch(self, path, body):
        if not path.split("?", 1)[1].startswith("id=eq."):
            ident = _q(path, "email").removeprefix("eq.")
            hit = [c for c in self.codes if c["email"] == ident and c["consumed_at"] is None]
            for c in hit:
                c.update(body)
            return hit
        row = next(c for c in self.codes if f"id=eq.{c['id']}" in path)
        if "attempts=eq." in path and f"attempts=eq.{row['attempts']}" not in path:
            return []
        if "consumed_at=is.null" in path and row["consumed_at"] is not None:
            return []
        row.update(body)
        return [row]


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(mp.sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(mp.sb_clients, "sb_delete_as_service", lambda p: True)
    biz = {"id": BIZ, "name": "First Light", "type": "church", "settings": {"member_portal": {"enabled": True}}}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": biz, "site": {}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    f.texts, f.mails = [], []

    async def _text(b, phone, code):
        f.texts.append((phone, code))

    async def _mail(b, email, name, code):
        f.mails.append((email, code))
    monkeypatch.setattr(mp, "_send_code_text", _text)
    monkeypatch.setattr(mp, "_send_code_email", _mail)
    monkeypatch.setattr(mp, "gifts_for", lambda b, c, y: [])
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    import member_portal_church as mpc
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [])
    return f


def _client():
    app = FastAPI()
    app.include_router(mp.router)

    @app.get("/my")
    async def _my(request: mp.Request):
        return await mp.serve(request, "/my")
    return TestClient(app, base_url=f"https://{HOST}")


# ─── 2-3. matching, texting, signing in ──────────────────────────────


def test_a_known_number_is_texted_and_signs_in(fake):
    c = _client()
    r = c.post("/my/code", data={"email": "555-010-2030"}, headers=ORIGIN)
    assert r.status_code == 200 and "Check your texts" in r.text and "(555) 010-2030" in r.text
    assert fake.texts and not fake.mails
    phone, code = fake.texts[-1]
    assert phone == "+15550102030" and fake.codes[-1]["email"] == "+15550102030"
    v = c.post("/my/verify", data={"email": "+15550102030", "code": code}, headers=ORIGIN, follow_redirects=False)
    assert v.status_code == 303
    assert "Hi, Ana" in c.get("/my").text


def test_an_unknown_number_gets_the_same_page_and_nothing(fake):
    c = _client()
    known = c.post("/my/code", data={"email": "555-010-2030"}, headers=ORIGIN)
    unknown = c.post("/my/code", data={"email": "555-999-8888"}, headers=ORIGIN)
    strip = lambda r, shown, e164: r.text.replace(shown, "X").replace(e164, "Y")
    assert strip(known, "(555) 010-2030", "+15550102030") == strip(unknown, "(555) 999-8888", "+15559998888")
    assert [t[0] for t in fake.texts] == ["+15550102030"]


def test_one_person_per_number(fake):
    fake.contacts.append({"id": "c2", "business_id": BIZ, "name": "Ben Rivers",
                          "email": "ben@example.com", "phone": "555.010.2030"})
    _client().post("/my/code", data={"email": "(555) 010-2030"}, headers=ORIGIN)
    assert not fake.texts


def test_nonsense_is_refused_before_anything(fake):
    r = _client().post("/my/code", data={"email": "call me"}, headers=ORIGIN)
    assert r.status_code == 400 and "mobile number" in r.text and not fake.texts and not fake.codes


# ─── 4. the text itself ──────────────────────────────────────────────


def test_the_text_skips_history_and_opt_outs(monkeypatch):
    import asyncio
    import sms_service
    import twilio_sms
    sent = []
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)

    async def _sender(client, biz_id):
        return "+15550000000"

    async def _core(*a, **k):
        raise AssertionError("sign-in codes must not go through the stored-history sender")
    monkeypatch.setattr(sms_service, "sender_for", _sender)
    monkeypatch.setattr(sms_service, "send_sms_core", _core)
    monkeypatch.setattr(twilio_sms, "send_sms", lambda to, body, from_number=None: sent.append((to, body, from_number)) or "SM1")
    biz = {"id": BIZ, "name": "First Light"}

    async def _opted(client, phone, biz_id=None):
        return False
    monkeypatch.setattr(sms_service, "is_opted_out", _opted)
    asyncio.run(mp._send_code_text(biz, "+15550102030", "123456"))
    assert sent and sent[0][0] == "+15550102030" and "123456" in sent[0][1] and sent[0][2] == "+15550000000"
    assert sent[0][1].startswith("First Light:")

    async def _stopped(client, phone, biz_id=None):
        return True
    monkeypatch.setattr(sms_service, "is_opted_out", _stopped)
    sent.clear()
    asyncio.run(mp._send_code_text(biz, "+15550102030", "123456"))
    assert not sent
