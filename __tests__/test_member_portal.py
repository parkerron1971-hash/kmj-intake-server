# __tests__/test_member_portal.py
#
# A church member's own page at <church site>/my (member_portal.py). Pins:
#   1. the session: signed per church, expires, cannot be tampered with or
#      carried to another church, and ends at the church's epoch
#   2. the gate: nonprofit family + switched on + a client surface allowed
#   3. nothing says who is on the list — not the code page, not the verify
#      message — and only a known address is mailed
#   4. a code: single use, 10 minutes, 5 tries, a newer code retires older
#      ones, and a daily cap on wrong codes per address
#   5. signing in sets a __Host- httponly/secure/Lax cookie; a household
#      email leads to "who's signing in?"; an over-shared one does not sign in
#   6. every request re-checks the person's record (revocation); a failed
#      read says "try again" and never burns a code or shows $0; a
#      cross-site POST is refused; the limiter's per-address cooldown
#   7. the owner switch: a real boolean, turning on moves the epoch

import pathlib
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
HOST = "first-light.mysolutionist.app"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")


def _biz(**over):
    b = {"id": BIZ, "name": "First Light Church", "type": "church",
         "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
    b.update(over)
    return b


# ─── 1. session ──────────────────────────────────────────────────────


def test_session_round_trip_and_scope():
    v = mp.mint_session(BIZ, "Ana@Example.com ", "c1")
    c = mp.read_session(v, BIZ)
    assert c["em"] == "ana@example.com" and c["cid"] == "c1"
    assert mp.read_session(v, OTHER) is None                # another church's key
    payload, sig = v.split(".")
    # A fixed suffix can equal the real signature. Change a significant byte.
    tampered_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert mp.read_session(payload + "." + tampered_sig, BIZ) is None
    assert mp.read_session("garbage", BIZ) is None
    old = mp.mint_session(BIZ, "ana@example.com", "c1", now=int(time.time()) - mp.SESSION_TTL_SECONDS - 5)
    assert mp.read_session(old, BIZ) is None                 # expired


def test_session_ends_at_the_church_epoch():
    v = mp.mint_session(BIZ, "ana@example.com", "c1", now=1_000_000_000)
    assert mp.read_session(v, BIZ, now=1_000_000_100, epoch=999_999_999)
    assert mp.read_session(v, BIZ, now=1_000_000_100, epoch=1_000_000_050) is None


def test_code_hash_is_per_church_and_address():
    a = mp.code_hash(BIZ, "ana@example.com", "123456")
    assert a == mp.code_hash(BIZ, "ANA@example.com ", "123456")
    assert a != mp.code_hash(OTHER, "ana@example.com", "123456")
    assert a != mp.code_hash(BIZ, "ben@example.com", "123456")
    assert len(mp.new_code()) == 6 and mp.new_code().isdigit()


# ─── 2. gate ─────────────────────────────────────────────────────────


def test_gate():
    assert mp.portal_active(_biz())
    assert not mp.portal_active(_biz(settings={}))
    assert not mp.portal_active(_biz(type="coach"))
    assert not mp.portal_active(_biz(settings={"member_portal": "yes"}))


# ─── fake data layer: honours the business + email filters ────────────


def _param(path, name):
    q = urllib.parse.parse_qs(path.split("?", 1)[1], keep_blank_values=True)
    v = q.get(name, [None])[0]
    return v


class Fake:
    def __init__(self):
        self.contacts = [{"id": "c1", "business_id": BIZ, "name": "Ana Rivers", "email": "ana@example.com"}]
        self.codes = []
        self.mailed = []
        self.gifts_fail = False
        self.contacts_fail = False
        self.gifts = [{"date": "2026-03-01", "fund": "General", "amount": 50.0,
                       "refunded": False, "method": "cash"}]

    def get(self, path):
        biz = (_param(path, "business_id") or "").removeprefix("eq.")
        if path.startswith("/contacts"):
            if self.contacts_fail:
                return None
            raw = (_param(path, "email") or "").removeprefix("ilike.")
            want = raw.replace("\\", "").lower()
            limit = int(_param(path, "limit") or 100)
            return [dict(c) for c in self.contacts
                    if c["business_id"] == biz and c["email"].lower() == want][:limit]
        if path.startswith("/member_login_codes"):
            em = (_param(path, "email") or "").removeprefix("eq.")
            mine = [c for c in self.codes if c["business_id"] == biz and c["email"] == em]
            if "consumed_at=is.null" in path:
                live = [c for c in mine if c["consumed_at"] is None]
                return [dict(live[-1])] if live else []
            return [dict(c) for c in mine]
        return []

    def post(self, path, body, prefer=None):
        row = {**body, "id": f"code{len(self.codes)}", "attempts": 0,
               "consumed_at": None, "succeeded": False}
        self.codes.append(row)
        return [row]

    def patch(self, path, body):
        if not path.split("?", 1)[1].startswith("id=eq."):   # retire every unused code for an address
            biz = (_param(path, "business_id") or "").removeprefix("eq.")
            em = (_param(path, "email") or "").removeprefix("eq.")
            hit = [c for c in self.codes if c["business_id"] == biz and c["email"] == em
                   and c["consumed_at"] is None]
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
    monkeypatch.setattr(mp, "_church_for_request",
                        lambda req: {"business": _biz(), "site": {"slug": "first-light"}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)

    async def _mail(biz, email, name, code):
        f.mailed.append((email, code))
    monkeypatch.setattr(mp, "_send_code_email", _mail)

    def _gifts(b, c, y):
        if f.gifts_fail:
            raise RuntimeError("read failed")
        return f.gifts
    monkeypatch.setattr(mp, "gifts_for", _gifts)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    import events_rsvp_router
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda b: [])
    return f


def _client():
    app = FastAPI()
    app.include_router(mp.router)

    @app.get("/my")
    async def _my(request: mp.Request):
        return await mp.serve(request, "/my")

    @app.get("/my/statement")
    async def _st(request: mp.Request):
        return await mp.serve(request, "/my/statement")

    @app.get("/my/me")
    async def _me(request: mp.Request):
        return await mp.serve(request, "/my/me")
    return TestClient(app, base_url=f"https://{HOST}")


ORIGIN = {"origin": f"https://{HOST}"}


def _ask(c, fake, email="ana@example.com"):
    c.post("/my/code", data={"email": email}, headers=ORIGIN)
    return fake.mailed[-1][1] if fake.mailed else None


def _verify(c, code, email="ana@example.com"):
    return c.post("/my/verify", data={"email": email, "code": code},
                  headers=ORIGIN, follow_redirects=False)


def _wrong(code):
    return "000000" if code != "000000" else "111111"


# ─── 3. nothing says who is on the list ──────────────────────────────


def test_unknown_address_gets_the_same_page_and_no_mail(fake):
    c = _client()
    known = c.post("/my/code", data={"email": "ana@example.com"}, headers=ORIGIN)
    unknown = c.post("/my/code", data={"email": "nobody@example.com"}, headers=ORIGIN)
    assert known.status_code == unknown.status_code == 200
    strip = lambda r, e: r.text.replace(e, "EMAIL")
    assert strip(known, "ana@example.com") == strip(unknown, "nobody@example.com")
    assert [m[0] for m in fake.mailed] == ["ana@example.com"]
    assert len(fake.codes) == 1 and fake.codes[0]["email"] == "ana@example.com"
    assert fake.mailed[0][1] not in str(fake.codes[0])      # only the hash is stored


def test_verify_answers_known_and_unknown_addresses_alike(fake):
    c = _client()
    code = _ask(c, fake)
    _ask(c, fake, "nobody@example.com")
    known = _verify(c, _wrong(code))
    unknown = _verify(c, "123456", "nobody@example.com")
    assert known.status_code == unknown.status_code == 400
    assert mp._e(mp.GENERIC_CODE_ERROR) in known.text
    strip = lambda r, e: r.text.replace(e, "EMAIL")
    assert strip(known, "ana@example.com") == strip(unknown, "nobody@example.com")


def test_cross_site_post_is_refused(fake):
    r = _client().post("/my/code", data={"email": "ana@example.com"},
                       headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and not fake.mailed


# ─── 4. the code ─────────────────────────────────────────────────────


def test_wrong_code_counts_and_locks_after_five(fake):
    c = _client()
    code = _ask(c, fake)
    for _ in range(mp.MAX_CODE_ATTEMPTS):
        assert _verify(c, _wrong(code)).status_code == 400
    # Even the right code is refused once the tries are spent.
    r = _verify(c, code)
    assert r.status_code == 400 and mp.SESSION_COOKIE not in r.cookies


def test_expired_code_is_refused(fake):
    c = _client()
    code = _ask(c, fake)
    fake.codes[-1]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert _verify(c, code).status_code == 400


def test_a_new_code_retires_the_old_one(fake):
    c = _client()
    first = _ask(c, fake)
    second = _ask(c, fake)
    assert first != second or len(fake.codes) == 2
    assert _verify(c, first).status_code == 400 if first != second else True
    assert _verify(c, second).status_code == 303
    # After signing in, nothing earlier comes back to life.
    assert all(row["consumed_at"] for row in fake.codes)


def test_daily_cap_on_wrong_codes_across_codes(fake):
    c = _client()
    for _ in range(mp.MAX_FAILED_PER_DAY // mp.MAX_CODE_ATTEMPTS):
        code = _ask(c, fake)
        for _ in range(mp.MAX_CODE_ATTEMPTS):
            _verify(c, _wrong(code))
    mailed = len(fake.mailed)
    code = _ask(c, fake)
    assert len(fake.mailed) == mailed          # no new code once the day's budget is spent
    assert _verify(c, code or "123456").status_code == 400


# ─── 5. signing in ───────────────────────────────────────────────────


def test_right_code_signs_in_once_with_a_host_cookie(fake):
    c = _client()
    code = _ask(c, fake)
    r = _verify(c, code)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("__host-sol_member=")
    for part in ("httponly", "secure", "samesite=lax", "path=/;", "max-age="):
        assert part in cookie + ";"
    assert "domain=" not in cookie
    assert _verify(c, code).status_code == 400           # single use
    home = c.get("/my")
    assert "Hi, Ana" in home.text
    # Giving lives on Me (member app, 2026-09-30).
    assert "$50.00" in c.get("/my/me").text


def test_one_person_per_email(fake):
    # Kevin, 2026-09-29: one person per email. A signed-in session ends the
    # moment a second record shares the address, and no code is sent to it.
    c = _client()
    _verify(c, _ask(c, fake))
    assert "Hi, Ana" in c.get("/my").text
    fake.contacts.append({"id": "c2", "business_id": BIZ, "name": "Ben Rivers", "email": "ANA@example.com"})
    page = c.get("/my")
    assert "Send my code" in page.text and "Ben Rivers" not in page.text
    mailed = len(fake.mailed)
    c.post("/my/code", data={"email": "ana@example.com"}, headers=ORIGIN)
    assert len(fake.mailed) == mailed
    assert mp.MAX_HOUSEHOLD == 1


def test_over_shared_address_is_never_mailed(fake):
    for i in range(mp.MAX_HOUSEHOLD):
        fake.contacts.append({"id": f"x{i}", "business_id": BIZ, "name": f"P{i}", "email": "ana@example.com"})
    r = _client().post("/my/code", data={"email": "ana@example.com"}, headers=ORIGIN)
    assert r.status_code == 200 and not fake.mailed


def test_another_churchs_member_is_not_on_this_list(fake):
    fake.contacts = [{"id": "c9", "business_id": OTHER, "name": "Zed", "email": "zed@example.com"}]
    _client().post("/my/code", data={"email": "zed@example.com"}, headers=ORIGIN)
    assert not fake.mailed


# ─── 6. re-checks, failures, limits ──────────────────────────────────


def test_session_ends_when_the_record_changes(fake):
    c = _client()
    _verify(c, _ask(c, fake))
    assert "Hi, Ana" in c.get("/my").text
    fake.contacts[0]["email"] = "new@example.com"
    assert "Send my code" in c.get("/my").text


def test_failed_people_read_says_try_again_and_keeps_the_code(fake):
    c = _client()
    code = _ask(c, fake)
    fake.contacts_fail = True
    r = _verify(c, code)
    assert r.status_code == 503 and "try again" in r.text.lower()
    assert fake.codes[-1]["consumed_at"] is None and fake.codes[-1]["attempts"] == 0
    fake.contacts_fail = False
    assert _verify(c, code).status_code == 303
    fake.contacts_fail = True
    page = c.get("/my")
    assert page.status_code == 503 and "Send my code" not in page.text


def test_failed_giving_read_is_said_not_zero(fake):
    c = _client()
    _verify(c, _ask(c, fake))
    fake.gifts_fail = True
    page = c.get("/my/me").text
    assert "couldn't load" in page and "$0" not in page


def test_per_address_cooldown(fake, monkeypatch):
    import rate_limit
    seen = {}

    def allow(bucket, key):
        n, _ = rate_limit._LIMITS[bucket]
        seen[(bucket, key)] = seen.get((bucket, key), 0) + 1
        return seen[(bucket, key)] <= n
    monkeypatch.setattr(rate_limit, "allow_strict", allow)
    c = _client()
    assert c.post("/my/code", data={"email": "ana@example.com"}, headers=ORIGIN).status_code == 200
    again = c.post("/my/code", data={"email": "ana@example.com"}, headers=ORIGIN)
    assert again.status_code == 429 and len(fake.mailed) == 1
    # Another address is unaffected by this one's cooldown.
    assert c.post("/my/code", data={"email": "ben@example.com"}, headers=ORIGIN).status_code == 200


def test_sign_out_clears_the_cookie(fake):
    c = _client()
    _verify(c, _ask(c, fake))
    r = c.post("/my/signout", headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and "max-age=0" in r.headers["set-cookie"].lower()


def test_closed_portal_is_a_plain_404(fake, monkeypatch):
    monkeypatch.setattr(mp, "_church_for_request",
                        lambda req: {"business": _biz(settings={}), "site": {}})
    c = _client()
    assert c.get("/my").status_code == 404
    r = c.post("/my/code", data={"email": "ana@example.com"}, headers=ORIGIN)
    assert r.status_code == 404 and not fake.mailed


# ─── 7. owner switch ─────────────────────────────────────────────────


def test_owner_switch_needs_a_real_boolean_and_moves_the_epoch(monkeypatch):
    from types import SimpleNamespace
    stored = {"settings": {"giving": {"enabled": True}}}
    patched = []
    monkeypatch.setattr(mp, "_require_owner", lambda b, u: {**_biz(settings={}), "settings": {}})
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site",
                        lambda biz: ({"slug": "first-light", "site_config": {}}, False))
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", lambda p: [{"settings": dict(stored["settings"])}])

    def _patch(path, body):
        patched.append(body)
        stored["settings"] = body["settings"]
        return [{"id": BIZ}]
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", _patch)
    user = SimpleNamespace(id="owner")
    with pytest.raises(mp.HTTPException) as e:
        mp.patch_member_portal_config(BIZ, {"enabled": "false"}, user)
    assert e.value.status_code == 400 and not patched
    out = mp.patch_member_portal_config(BIZ, {"enabled": True}, user)
    assert out["enabled"] and stored["settings"]["member_portal"]["epoch"] > 0
    # Settings changed elsewhere since the owner row was read are kept.
    assert stored["settings"]["giving"] == {"enabled": True}
    first = stored["settings"]["member_portal"]["epoch"]
    time.sleep(1.01)
    mp.patch_member_portal_config(BIZ, {"sign_out_all": True}, user)
    assert stored["settings"]["member_portal"]["epoch"] > first
