"""Check requests: money going out (church_checks.py, member_portal_checks.py).
Kevin 2026-10-27, on the Church Office Prototypes ("Check requests" tab):
"lets go with your list". A volunteer spent $340 on Bible school supplies;
under Serve she taps Get paid back, adds the receipt, the amount and the
ministry; the treasurer approves it, a keeper above the limit, and the
office pays it into the books.

Pins:
  * the switch: off hides it all, owner shows it to the platform owner alone
    (and the member side only in their preview), and missing tables are a
    quiet no and 503s, never 500
  * who: the owner, admins, the accountant and Giving & money logins; anyone
    else is refused, and a viewer only reads
  * a member sees only their own requests and receipts, and the reason a
    declined one gives them
  * receipts: kept in the private bucket under the church's own folder,
    re-saved without the phone's tags, read only through the server by the
    office or the asker; never a public link
  * the limit: up to it the treasurer approves; above it a keeper says yes
    (here, or by an ask and a tap or code), the owner bound too; with no
    keeper the limit alone governs; raising it needs the same yes
  * paid writes ONE expense in the ministry's line (with the receipt), a
    closed period refuses it, taking it back removes the expense; spent vs
    budget per ministry adds up from the books
  * another church's requests, people and receipts are unreachable
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas  # noqa: E402
import church_checks as cc  # noqa: E402
import church_keys as ck  # noqa: E402
import member_portal_checks as mpck  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SALON = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "treasurer", "viewer", "singer", "accountant", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
T0 = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
DANA = "cccccccc-0000-4000-8000-000000000001"
MARCUS = "cccccccc-0000-4000-8000-000000000002"
THEIR_PERSON = "cccccccc-0000-4000-8000-000000000003"
DANA_ME = {"id": DANA, "name": "Dana Moore", "email": "dana@example.com"}
MARCUS_ME = {"id": MARCUS, "name": "Marcus Reed", "email": "marcus@example.com"}
THEIRS_ME = {"id": THEIR_PERSON, "name": "Grace Member", "email": "grace@example.com"}


def photo(size=(400, 600), tag=b"") -> bytes:
    """A phone photo: a JPEG with its own tags (the make, here)."""
    from PIL import Image
    im = Image.new("RGB", size, (240, 236, 228))
    ex = Image.Exif()
    ex[0x010F] = "PhoneMaker"
    out = io.BytesIO()
    im.save(out, "JPEG", exif=ex.tobytes())
    return out.getvalue() + tag


class ChecksDB(FakeDB):
    """The two tables' defaults and the settings' upsert, on the shared fake."""

    REQ_DEFAULTS = {"contact_id": None, "asker_name": None, "payee": None, "receipt_path": None, "receipt_type": None,
                    "status": "new", "source": "office", "decline_reason": None, "decided_by": None,
                    "decided_at": None, "paid_how": None, "check_number": None, "paid_on": None, "expense_id": None,
                    "paid_by": None, "paid_at": None, "created_by": None}

    def _gone(self, path):
        return self.missing and path.lstrip("/").split("?")[0].startswith("church_check_")

    def get(self, path, **kw):
        return None if self._gone(path) else super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        if self._gone(path):
            return None
        table = path.lstrip("/").split("?")[0]
        rows = body if isinstance(body, list) else [body]
        if table == "church_check_requests":
            rows = [{**self.REQ_DEFAULTS, **r} for r in rows]
        if table == "church_check_settings":
            have = self.t.setdefault(table, [])
            old = next((r for r in have if r["business_id"] == rows[0]["business_id"]), None)
            if old:
                old.update(rows[0])
                return [dict(old)]
        if table == "church_area_keys":
            rows = [{"status": "asked", "asked_at": ck._iso(ck._now()), "code_tries": 0, "reason": "",
                     "answered_by": None, "opens_until": None, "how": None, **r} for r in rows]
        return super().post(path, rows, prefer=prefer, **kw)

    def patch(self, path, body, **kw):
        return None if self._gone(path) else super().patch(path, body, **kw)


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin"), ("treasurer", "member"), ("viewer", "viewer"), ("singer", "member"))
    fake = ChecksDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"], "settings": {}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}},
                    {"id": SALON, "name": "Shear Joy", "type": "salon", "owner_id": ID["owner"], "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        business_collaborators=[{"id": "col1", "business_id": BIZ, "user_id": ID["accountant"], "status": "active",
                                 "role": "accountant"}],
        contacts=[{"id": DANA, "business_id": BIZ, "name": "Dana Moore", "email": "dana@example.com"},
                  {"id": MARCUS, "business_id": BIZ, "name": "Marcus Reed", "email": "marcus@example.com"},
                  {"id": THEIR_PERSON, "business_id": OTHER, "name": "Grace Member", "email": "grace@example.com"}],
        groups=[{"id": "g1", "business_id": BIZ, "name": "Kids ministry", "kind": "ministry", "active": True},
                {"id": "g2", "business_id": BIZ, "name": "Hospitality", "kind": "ministry", "active": True},
                {"id": "g3", "business_id": BIZ, "name": "Tuesday small group", "kind": "small_group", "active": True},
                {"id": "g4", "business_id": OTHER, "name": "Their kids", "kind": "ministry", "active": True}],
        # Dana leads Kids; Marcus serves nowhere and has no login.
        group_members=[{"business_id": BIZ, "group_id": "g1", "contact_id": DANA, "role": "leader"}],
        church_leader_roles=[], space_leaders=[],
        church_check_settings=[], church_check_requests=[], business_expenses=[],
        church_keepers=[], church_area_keys=[], accounting_periods=[],
    )
    fake.missing = False
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_CHECKS", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("CHURCH_KEYS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(cc, "_now", lambda: T0)
    monkeypatch.setattr(ck, "_now", lambda: T0)
    monkeypatch.setattr(cc, "_tz", lambda biz: ZoneInfo("America/New_York"))
    fake.told = []
    monkeypatch.setattr(ck, "_tell", lambda biz, to, title, body, seats, tag: fake.told.append((sorted(to), title, body)))
    # Who sees what: the treasurer works Giving & money, the viewer too
    # (read only), the singer worship only.
    areas = {ID["treasurer"]: ["giving_money"], ID["viewer"]: ["giving_money"], ID["singer"]: ["worship_media"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": areas.get(uid), "by": "picked"})
    # Storage: the private bucket, in memory.
    fake.files = {}
    fake.dropped = []
    monkeypatch.setattr(cc, "_storage_put", lambda path, data, media: (fake.files.__setitem__(path, (data, media)) or (True, 200, "")))
    monkeypatch.setattr(cc, "_storage_get", lambda path: (fake.files.get(path) or (None,))[0])
    monkeypatch.setattr(cc, "_storage_drop", lambda path: (fake.dropped.append(path), fake.files.pop(path, None)))
    monkeypatch.setattr(cc, "_church_owner_email", lambda owner_id: "owner@lovecity.org" if owner_id == ID["owner"] else "")
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(cc.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def _page(name, biz=BIZ):
    got = client(name).get(f"/church/checks?business_id={biz}")
    assert got.status_code == 200, got.text
    return got.json()


def _add(who, biz=BIZ, **kw):
    body = {"business_id": biz, "amount": "500", "about": "Youth retreat deposit", "ministry": "Kids ministry",
            "payee": "Camp Swift Creek", **kw}
    return client(who).post("/church/checks/requests", json=body)


def _ask(person=DANA_ME, amount="340", about="Bible school supplies", ministry="Kids ministry", raw=None):
    return cc.member_ask({"id": BIZ, "owner_id": ID["owner"]}, person, amount, about, ministry,
                         photo() if raw is None else raw)


def _decide(name, rid, status="approved", reason=None, biz=BIZ):
    body = {"business_id": biz, "status": status, **({"reason": reason} if reason is not None else {})}
    return client(name).post(f"/church/checks/requests/{rid}/decide", json=body)


def _pay(name, rid, biz=BIZ, **kw):
    body = {"business_id": biz, "how": "check", "check_number": "1043", "paid_on": "2026-10-27", **kw}
    return client(name).post(f"/church/checks/requests/{rid}/paid", json=body)


def _keeper(db, name, area="giving_money"):
    db.t["church_keepers"].append({"business_id": BIZ, "area": area, "user_id": ID[name], "added_by": ID["admin"],
                                   "added_at": "2026-10-01T00:00:00+00:00",
                                   "starts_at": "2026-10-01T00:00:00+00:00", "ends_at": None})


def _req(db, rid):
    return next(r for r in db.t["church_check_requests"] if r["id"] == rid)


def _by(page, rid):
    return next(r for r in page["requests"] if r["id"] == rid)


# ─── The switch, the tables ──────────────────────────────────────────

def test_the_switch_and_tables_not_made_yet(db, monkeypatch):
    def status(name):
        return client(name).get(f"/church/checks/status?business_id={BIZ}").json()["enabled"]
    monkeypatch.setenv("CHURCH_CHECKS", "off")
    assert status("owner") is False and status("admin") is False
    assert client("owner").get(f"/church/checks?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_CHECKS", "owner")    # the platform owner alone until a Thursday
    assert status("owner") is True and status("admin") is False
    assert _add("admin").status_code == 404
    assert _add("owner").status_code == 200
    monkeypatch.setenv("CHURCH_CHECKS", "on")
    assert status("admin") is True
    db.missing = True
    assert client("owner").get(f"/church/checks/status?business_id={BIZ}").json() == {
        "enabled": False, "approve": False, "settings": False}
    c = client("owner")
    for got in (c.get(f"/church/checks?business_id={BIZ}"), _add("owner"),
                c.put("/church/checks/settings", json={"business_id": BIZ, "limit": "100"})):
        assert got.status_code == 503, got.text
    with pytest.raises(HTTPException) as e:
        _ask()
    assert e.value.status_code == 503
    assert db.t["business_expenses"] == [] and db.files == {}, "nothing kept before the tables exist"


def test_the_member_side_follows_the_switch(db, monkeypatch):
    import member_portal
    req = object()
    monkeypatch.setenv("CHURCH_CHECKS", "on")
    assert mpck.shown_here(req, {"id": BIZ}) is True
    monkeypatch.setenv("CHURCH_CHECKS", "off")
    assert mpck.shown_here(req, {"id": BIZ}) is False
    assert mpck.door(req, {"id": BIZ}) == ""
    monkeypatch.setenv("CHURCH_CHECKS", "owner")
    monkeypatch.setattr(member_portal, "_previewing", lambda request, biz: None)
    assert mpck.shown_here(req, {"id": BIZ}) is False, "owner mode: a member never sees it"
    monkeypatch.setattr(member_portal, "_previewing", lambda request, biz: {"cid": DANA, "own": "someone"})
    monkeypatch.setattr(cc, "is_platform_owner", lambda own: own == ID["owner"])
    assert mpck.shown_here(req, {"id": BIZ}) is False, "another owner's preview"
    monkeypatch.setattr(member_portal, "_previewing", lambda request, biz: {"cid": DANA, "own": ID["owner"]})
    assert mpck.shown_here(req, {"id": BIZ}) is True, "the platform owner's own preview"
    assert 'href="/my/paid-back"' in mpck.door(req, {"id": BIZ})


def test_status_says_what_each_login_may_do(db):
    def status(name, biz=BIZ):
        return client(name).get(f"/church/checks/status?business_id={biz}").json()
    assert status("owner") == {"enabled": True, "approve": True, "settings": True}
    assert status("admin") == {"enabled": True, "approve": True, "settings": True}
    assert status("accountant") == {"enabled": True, "approve": True, "settings": False}
    assert status("treasurer") == {"enabled": True, "approve": True, "settings": False}
    assert status("viewer") == {"enabled": True, "approve": False, "settings": False}
    assert status("singer")["enabled"] is False, "their areas leave out Giving & money"
    assert status("owner", SALON)["enabled"] is False, "churches only"
    assert client("stranger").get(f"/church/checks/status?business_id={BIZ}").status_code == 404
    assert client("singer").get(f"/church/checks?business_id={BIZ}").status_code == 403
    assert _add("viewer").status_code == 403, "a viewer only reads"


def test_with_who_sees_what_off_money_stays_with_the_owner_admins_and_accountant(db, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert client("treasurer").get(f"/church/checks/status?business_id={BIZ}").json()["enabled"] is False
    assert client("accountant").get(f"/church/checks/status?business_id={BIZ}").json()["enabled"] is True


# ─── The member: their own, and only their own ───────────────────────

def test_a_member_sees_only_their_own_requests_and_the_reason_for_a_no(db):
    church = {"id": BIZ, "owner_id": ID["owner"]}
    assert cc.serves(church, DANA_ME) is True, "Dana leads Kids"
    assert cc.serves(church, MARCUS_ME) is False, "Marcus serves nowhere"
    assert cc.serves(church, {"id": MARCUS, "email": "treasurer@lovecity.org"}) is True, "a church login serves"
    assert cc.serves(church, {"id": MARCUS, "email": "owner@lovecity.org"}) is True, "so does the owner"

    lines = cc.member_lines(church)
    assert lines == ["Hospitality", "Kids ministry"], "never saved: the church's ministry groups"
    supplies = _ask()
    coffee = _ask(amount="62.18", about="Coffee for Sunday", ministry="hospitality")
    theirs = _ask(person=MARCUS_ME, amount="20", about="Batteries", ministry="Kids ministry")
    assert supplies["status"] == "new" and supplies["source"] == "app" and supplies["payee"] == "Dana Moore"
    assert coffee["ministry"] == "Hospitality", "the line's own spelling"
    assert supplies["amount_cents"] == 34000 and coffee["amount_cents"] == 6218

    # The office says no to the coffee, with a reason she reads.
    got = _decide("treasurer", coffee["id"], "declined", reason="Hospitality's coffee comes from the Costco order.")
    assert got.status_code == 200
    assert _decide("treasurer", supplies["id"], "declined").status_code == 400, "a no says why"

    mine = cc.member_requests(church, DANA_ME)
    assert {r["id"] for r in mine} == {supplies["id"], coffee["id"]}, "never Marcus's"
    no = next(r for r in mine if r["id"] == coffee["id"])
    assert no["status"] == "declined" and no["decline_reason"] == "Hospitality's coffee comes from the Costco order."
    assert all("contact_id" not in r and "who" not in r for r in mine)
    assert [r["id"] for r in cc.member_requests(church, MARCUS_ME)] == [theirs["id"]]

    # The page she sees says it in words.
    from starlette.requests import Request
    request = Request({"type": "http", "method": "GET", "path": "/my/paid-back", "query_string": b"", "headers": [],
                       "server": ("x", 443), "scheme": "https"})
    html = mpck.render_page({"id": BIZ, "name": "Love City Church", "type": "church", "settings": {}}, {}, request,
                            DANA_ME, lines, mine, lead=True)
    assert "Not approved" in html and "the Costco order" in html and "Waiting" in html
    assert "Batteries" not in html
    assert 'accept="image/*,application/pdf"' in html and 'enctype="multipart/form-data"' in html


def test_receipts_are_private_and_read_only_through_the_server(db):
    church = {"id": BIZ, "owner_id": ID["owner"]}
    row = _ask(raw=photo())
    path = row["receipt_path"]
    assert re.fullmatch(rf"{BIZ}/check-requests/[0-9a-f]{{32}}\.jpg", path), path
    assert cc.RECEIPT_BUCKET == "business-documents", "the private bucket (closed 2026-08-10)"
    kept, media = db.files[path]
    assert media == "image/jpeg" and b"PhoneMaker" not in kept, "re-saved: the phone's tags don't travel"
    # Nothing ever names a public link.
    import inspect
    for mod in (cc, mpck):
        assert "/object/public/" not in inspect.getsource(mod)

    # The asker reads their own; nobody else's.
    assert cc.member_receipt(church, DANA_ME, row["id"]).body == kept
    with pytest.raises(HTTPException) as e:
        cc.member_receipt(church, MARCUS_ME, row["id"])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        cc.member_receipt({"id": OTHER}, THEIRS_ME, row["id"])
    assert e.value.status_code == 404

    # The office: the treasurer's role reads it; nobody else does.
    got = client("treasurer").get(f"/church/checks/requests/{row['id']}/receipt?business_id={BIZ}")
    assert got.status_code == 200 and got.content == kept
    assert got.headers["cache-control"] == "private, no-store" and got.headers["content-type"] == "image/jpeg"
    assert client("singer").get(f"/church/checks/requests/{row['id']}/receipt?business_id={BIZ}").status_code == 403
    assert client("other_owner").get(f"/church/checks/requests/{row['id']}/receipt?business_id={BIZ}").status_code == 404
    assert client("other_owner").get(f"/church/checks/requests/{row['id']}/receipt?business_id={OTHER}").status_code == 404
    # A path that isn't one of this church's receipts is never read.
    _req(db, row["id"])["receipt_path"] = f"{OTHER}/check-requests/{'a' * 32}.jpg"
    assert client("owner").get(f"/church/checks/requests/{row['id']}/receipt?business_id={BIZ}").status_code == 404

    # A PDF stays a PDF; anything else isn't a receipt.
    pdf = _ask(raw=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF")
    assert pdf["receipt_type"] == "pdf" and pdf["receipt_path"].endswith(".pdf")
    for bad in (b"", b"not a picture", b"GIF89a"):
        with pytest.raises(HTTPException) as e:
            _ask(raw=bad)
        assert e.value.status_code == 400
    assert len(db.t["church_check_requests"]) == 2

    # The office attaches one to its own request, and a new one replaces it.
    rid = _add("treasurer").json()["request"]["id"]
    c = client("treasurer")
    up = c.post(f"/church/checks/requests/{rid}/receipt", data={"business_id": BIZ},
                files={"file": ("invoice.jpg", photo((300, 300)), "image/jpeg")})
    assert up.status_code == 200 and up.json()["request"]["receipt"] == "image"
    first = _req(db, rid)["receipt_path"]
    c.post(f"/church/checks/requests/{rid}/receipt", data={"business_id": BIZ},
           files={"file": ("invoice.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert first in db.dropped and _req(db, rid)["receipt_path"].endswith(".pdf")


def test_the_member_post_saves_and_a_preview_saves_nothing(db, monkeypatch):
    import member_portal
    import member_portal_church
    import rate_limit
    church = {"business": {"id": BIZ, "name": "Love City Church", "type": "church", "owner_id": ID["owner"], "settings": {}}}
    state = {"me": DANA_ME, "unavailable": False}

    async def signed_in(request):
        return church, state["me"], state["unavailable"]
    monkeypatch.setattr(member_portal_church, "_signed_in", signed_in)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    app = FastAPI()
    app.include_router(mpck.router)
    c = TestClient(app)

    def send(**form):
        data = {"amount": "340", "about": "Bible school supplies", "ministry": "Kids ministry", **form}
        return c.post("/my/paid-back", data=data, files={"receipt": ("receipt.jpg", photo(), "image/jpeg")},
                      follow_redirects=False)
    got = send()
    assert got.status_code == 303 and got.headers["location"] == "/my/paid-back?done=sent"
    assert len(db.t["church_check_requests"]) == 1 and db.t["church_check_requests"][0]["contact_id"] == DANA
    got = send(amount="abc")
    assert got.status_code == 303 and "err=said" in got.headers["location"] and len(db.t["church_check_requests"]) == 1
    state["unavailable"] = "preview"
    assert send().headers["location"] == "/my/paid-back?err=preview"
    state.update(me=MARCUS_ME, unavailable=False)
    assert send().headers["location"] == "/my", "Marcus doesn't serve"
    monkeypatch.setenv("CHURCH_CHECKS", "owner")
    monkeypatch.setattr(member_portal, "_previewing", lambda request, biz: None)
    state["me"] = DANA_ME
    assert send().headers["location"] == "/my", "owner mode: members can't send yet"
    assert len(db.t["church_check_requests"]) == 1


# ─── The limit and the keepers ───────────────────────────────────────

def test_with_no_keeper_the_limit_alone_governs(db):
    small = _ask(amount="62.18", ministry="Hospitality")["id"]
    big = _ask()["id"]                                             # $340, over $250
    page = _page("treasurer")
    assert page["keeper"]["on"] is False and page["settings"]["limit_cents"] == 25000
    assert _by(page, big)["over_limit"] is True and _by(page, small)["over_limit"] is False
    assert _decide("treasurer", small).json()["request"]["status"] == "approved"
    for name in ("treasurer", "owner", "admin"):
        got = _decide(name, big)
        assert got.status_code == 403 and got.json()["detail"]["code"] == "over_limit", name
        assert "no keeper for Giving & money" in got.json()["detail"]["message"]
    asked = client("treasurer").post(f"/church/checks/requests/{big}/keeper", json={"business_id": BIZ})
    assert asked.status_code == 409 and asked.json()["detail"]["code"] == "over_limit"
    assert _req(db, big)["status"] == "new"
    # The owner can raise the limit while there's no keeper.
    assert client("owner").put("/church/checks/settings", json={"business_id": BIZ, "limit": "400"}).status_code == 200
    assert _decide("treasurer", big).status_code == 200


def test_above_the_limit_a_keeper_says_yes_the_owner_bound_too(db):
    _keeper(db, "admin")
    big = _ask()["id"]
    assert _page("treasurer")["keeper"] == {"on": True, "mine": False, "open_until": None, "asked": None, "keepers": 1}
    for name in ("treasurer", "owner", "accountant"):
        got = _decide(name, big)
        assert got.status_code == 403 and got.json()["detail"]["code"] == "needs_keeper", name
    # The church keys' own ask: the keeper hears the ministry and the amount.
    asked = client("treasurer").post(f"/church/checks/requests/{big}/keeper", json={"business_id": BIZ})
    assert asked.status_code == 200 and asked.json()["told"] == 1
    keepers, title, body = db.told[-1]
    assert keepers == [ID["admin"]] and "Giving & money" in title
    assert "Kids ministry" in body and "$340" in body and "$250 limit" in body
    assert _page("treasurer")["keeper"]["asked"]["id"] == asked.json()["key"]["id"]
    assert _decide("treasurer", big).status_code == 403, "an ask opens nothing until a keeper says yes"
    # The keeper's yes opens Giving & money to the asker for an hour.
    ck.answer(BIZ, PEOPLE["admin"], asked.json()["key"]["id"], True)
    assert _page("treasurer")["keeper"]["open_until"]
    got = _decide("treasurer", big)
    assert got.status_code == 200 and got.json()["request"]["status"] == "approved"
    assert got.json()["request"]["decided_by"] == "treasurer@lovecity.org"


def test_a_keeper_approves_here_and_a_code_opens_it_too(db):
    _keeper(db, "admin")
    _keeper(db, "owner")
    big = _ask()["id"]
    assert _page("admin")["keeper"]["mine"] is True
    assert _decide("admin", big).status_code == 200, "a keeper says yes here"
    other = _ask(amount="900", about="Sound board repair", ministry="Hospitality")["id"]
    asked = client("treasurer").post(f"/church/checks/requests/{other}/keeper", json={"business_id": BIZ}).json()
    code = re.search(r"code: (\d{6})", db.told[-1][2]).group(1)
    wrong = client("treasurer").post("/church/checks/key-code", json={
        "business_id": BIZ, "key_id": asked["key"]["id"], "code": "000000" if code != "000000" else "111111"})
    assert wrong.status_code == 400
    assert client("treasurer").post("/church/checks/key-code", json={
        "business_id": BIZ, "key_id": asked["key"]["id"], "code": code}).status_code == 200
    assert _decide("treasurer", other).status_code == 200
    # Raising the limit needs the same yes; lowering it doesn't.
    raised = client("accountant").put("/church/checks/settings", json={"business_id": BIZ, "limit": "500"})
    assert raised.status_code == 403, "the owner and admins change the limit"
    db.t["church_keepers"] = [k for k in db.t["church_keepers"] if k["user_id"] != ID["owner"]]
    raised = client("owner").put("/church/checks/settings", json={"business_id": BIZ, "limit": "500"})
    assert raised.status_code == 403 and raised.json()["detail"]["code"] == "needs_keeper"
    assert client("owner").put("/church/checks/settings", json={"business_id": BIZ, "limit": "100"}).json()[
        "settings"]["limit_cents"] == 10000
    assert client("admin").put("/church/checks/settings", json={"business_id": BIZ, "limit": "500"}).json()[
        "settings"]["limit_cents"] == 50000


# ─── Paid: the books, the budgets ────────────────────────────────────

def test_paid_writes_one_expense_and_taking_it_back_removes_it(db):
    admin = client("admin")
    saved = admin.put("/church/checks/settings", json={"business_id": BIZ, "limit": "1000", "lines": [
        {"name": "Kids ministry", "budget": "2000"}, {"name": "Hospitality", "budget": "600"}, {"name": "Youth", "budget": ""}]})
    assert saved.status_code == 200
    assert saved.json()["settings"]["lines"] == [{"name": "Kids ministry", "budget_cents": 200000},
                                                 {"name": "Hospitality", "budget_cents": 60000},
                                                 {"name": "Youth", "budget_cents": 0}]
    row = _ask()
    assert _pay("treasurer", row["id"]).status_code == 409, "approve it first"
    assert _decide("treasurer", row["id"]).status_code == 200
    assert _pay("treasurer", row["id"], check_number="").status_code == 400, "a check has its number"
    got = _pay("treasurer", row["id"])
    assert got.status_code == 200 and got.json()["in_books"] is True
    paid = got.json()["request"]["paid"]
    assert paid == {"how": "check", "check_number": "1043", "paid_on": "2026-10-27", "in_books": True,
                    "by": "treasurer@lovecity.org"}
    assert len(db.t["business_expenses"]) == 1
    exp = db.t["business_expenses"][0]
    assert exp["amount"] == 340.0 and exp["category"] == "operating" and exp["subcategory"] == "Kids ministry"
    assert exp["vendor"] == "Dana Moore" and exp["date"] == "2026-10-27" and exp["payment_method"] == "check"
    assert exp["receipt_path"] == row["receipt_path"], "the receipt goes into the books with it"
    assert exp["description"] == "Check request: Bible school supplies (paid by check #1043)"
    assert _req(db, row["id"])["expense_id"] == exp["id"]
    # Paying twice is once.
    assert _pay("treasurer", row["id"]).status_code == 409 and len(db.t["business_expenses"]) == 1

    # The office pays the camp directly, by transfer.
    camp = _add("treasurer").json()["request"]
    assert camp["payee"] == "Camp Swift Creek" and camp["added_by"] == "treasurer@lovecity.org"
    _decide("treasurer", camp["id"])
    assert _pay("treasurer", camp["id"], how="transfer", check_number="").status_code == 200
    exp2 = db.t["business_expenses"][1]
    assert exp2["vendor"] == "Camp Swift Creek" and exp2["payment_method"] is None
    assert exp2["description"] == "Check request: Youth retreat deposit (paid by bank transfer)"

    # Spent vs budget by ministry this year: the books' own expenses in the
    # line (one entered elsewhere counts too), approved-not-paid beside it.
    db.t["business_expenses"].append({"id": "e-old", "business_id": BIZ, "amount": 370.0, "subcategory": "kids ministry",
                                      "date": "2026-03-02", "category": "operating"})
    db.t["business_expenses"].append({"id": "e-last", "business_id": BIZ, "amount": 99.0, "subcategory": "Kids ministry",
                                      "date": "2025-12-30", "category": "operating"})
    coffee = _ask(amount="62.18", about="Coffee", ministry="Hospitality")
    _decide("treasurer", coffee["id"])
    b = _page("treasurer")["budgets"]
    kids = next(x for x in b["lines"] if x["name"] == "Kids ministry")
    hosp = next(x for x in b["lines"] if x["name"] == "Hospitality")
    assert b["year"] == 2026
    assert kids == {"name": "Kids ministry", "budget_cents": 200000, "spent_cents": 34000 + 50000 + 37000, "committed_cents": 0}
    assert hosp == {"name": "Hospitality", "budget_cents": 60000, "spent_cents": 0, "committed_cents": 6218}
    assert b["paid_year_cents"] == 84000

    # Taking it back: the owner and admins; the request goes back to approved.
    assert client("treasurer").delete(f"/church/checks/requests/{row['id']}/paid?business_id={BIZ}").status_code == 403
    back = admin.delete(f"/church/checks/requests/{row['id']}/paid?business_id={BIZ}")
    assert back.status_code == 200 and back.json()["books"] is True
    assert back.json()["request"]["status"] == "approved" and back.json()["request"]["paid"] is None
    assert all(e["id"] != exp["id"] for e in db.t["business_expenses"])
    assert _req(db, row["id"])["expense_id"] is None and _req(db, row["id"])["check_number"] is None
    # Paid again later is one new expense.
    assert _pay("treasurer", row["id"], check_number="1050").status_code == 200
    assert sum(1 for e in db.t["business_expenses"] if e.get("description", "").startswith("Check request: Bible")) == 1


def test_a_closed_period_refuses_paying_and_taking_back(db):
    db.t["accounting_periods"].append({"id": "p1", "business_id": BIZ, "status": "closed", "period_type": "month",
                                       "period_start": "2026-09-01", "period_end": "2026-09-30"})
    row = _ask(amount="62.18", ministry="Hospitality")
    _decide("treasurer", row["id"])
    late = _pay("treasurer", row["id"], paid_on="2026-09-15")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "books_closed"
    assert db.t["business_expenses"] == [] and _req(db, row["id"])["status"] == "approved"
    assert _pay("treasurer", row["id"], paid_on="2026-12-25").status_code == 400, "not before it's paid"
    # Paid in October, then September and October close: the payment stays.
    assert _pay("treasurer", row["id"], paid_on="2026-10-02").status_code == 200
    db.t["accounting_periods"].append({"id": "p2", "business_id": BIZ, "status": "closed", "period_type": "month",
                                       "period_start": "2026-10-01", "period_end": "2026-10-31"})
    back = client("owner").delete(f"/church/checks/requests/{row['id']}/paid?business_id={BIZ}")
    assert back.status_code == 409 and back.json()["detail"]["code"] == "books_closed"
    assert len(db.t["business_expenses"]) == 1 and _req(db, row["id"])["status"] == "paid"


def test_two_presses_of_mark_paid_put_it_in_the_books_once(db, monkeypatch):
    row = _ask(amount="20", ministry="Hospitality")
    _decide("treasurer", row["id"])
    stale = dict(_req(db, row["id"]))          # read as approved by both
    assert _pay("treasurer", row["id"]).status_code == 200
    monkeypatch.setattr(cc, "resolve", lambda me, rid: dict(stale))
    second = _pay("admin", row["id"], check_number="1044")
    assert second.status_code == 409
    assert len(db.t["business_expenses"]) == 1, "the second press's expense went back out"
    assert _req(db, row["id"])["check_number"] == "1043"


def test_a_take_back_whose_expense_wont_delete_says_so(db, monkeypatch):
    row = _ask(amount="20", ministry="Hospitality")
    _decide("treasurer", row["id"])
    _pay("treasurer", row["id"])
    real = db.delete
    monkeypatch.setattr(sb_clients, "sb_delete_as_service",
                        lambda path, **kw: False if path.startswith("/business_expenses") else real(path, **kw))
    got = client("admin").delete(f"/church/checks/requests/{row['id']}/paid?business_id={BIZ}").json()
    assert got["books"] is False and "still in the books" in got["message"]


def test_declines_edits_and_their_rules(db):
    row = _ask(amount="40", ministry="Hospitality")
    c = client("treasurer")
    assert c.patch(f"/church/checks/requests/{row['id']}", json={"business_id": BIZ, "amount": "45.50"}).json()[
        "request"]["amount_cents"] == 4550
    assert c.patch(f"/church/checks/requests/{row['id']}", json={"business_id": BIZ, "ministry": "Choir"}).status_code == 400
    assert _decide("viewer", row["id"], "declined", reason="No").status_code == 403
    assert _decide("treasurer", row["id"], "declined", reason="Please send the itemized receipt.").status_code == 200
    assert _pay("treasurer", row["id"]).status_code == 409
    assert _decide("treasurer", row["id"]).status_code == 409
    assert c.patch(f"/church/checks/requests/{row['id']}", json={"business_id": BIZ, "amount": "1"}).status_code == 409
    paid = _ask(amount="10", ministry="Hospitality")
    _decide("treasurer", paid["id"])
    _pay("treasurer", paid["id"])
    assert _decide("treasurer", paid["id"], "declined", reason="x").status_code == 409, "take the payment back first"
    # Adding: an amount, what for, one of the lines.
    assert _add("treasurer", amount="0").status_code == 400
    assert _add("treasurer", about="").status_code == 400
    assert _add("treasurer", ministry="Choir").status_code == 400
    assert client("admin").put("/church/checks/settings", json={"business_id": BIZ, "lines": []}).status_code == 400
    assert client("admin").put("/church/checks/settings", json={"business_id": BIZ, "lines": [
        {"name": "Kids"}, {"name": "kids"}]}).status_code == 400


# ─── Another church ──────────────────────────────────────────────────

def test_another_church_is_unreachable(db):
    theirs_biz = {"id": OTHER, "owner_id": ID["other_owner"]}
    theirs = cc.member_ask(theirs_biz, THEIRS_ME, "40", "Snacks", "Their kids", photo())
    assert theirs["receipt_path"].startswith(f"{OTHER}/check-requests/")
    rid = theirs["id"]
    assert _decide("owner", rid).status_code == 404
    assert _pay("owner", rid).status_code == 404
    assert client("owner").patch(f"/church/checks/requests/{rid}", json={"business_id": BIZ, "amount": "1"}).status_code == 404
    assert client("owner").get(f"/church/checks/requests/{rid}/receipt?business_id={BIZ}").status_code == 404
    assert client("owner").post(f"/church/checks/requests/{rid}/keeper", json={"business_id": BIZ}).status_code == 404
    assert _add("owner", contact_id=THEIR_PERSON).status_code == 400, "their person isn't ours"
    assert client("other_owner").get(f"/church/checks?business_id={BIZ}").status_code == 404
    assert all(r["id"] != rid for r in _page("owner")["requests"])
    assert cc.member_requests({"id": BIZ}, THEIRS_ME) == []
    assert _req(db, rid)["status"] == "new"
    # Our member's ask can't name their ministry, and their lines aren't ours.
    with pytest.raises(HTTPException):
        _ask(ministry="Their kids")
    assert "Their kids" not in cc.member_lines({"id": BIZ})
