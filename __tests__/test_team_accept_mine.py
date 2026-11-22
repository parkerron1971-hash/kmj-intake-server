"""An office login gets in by its own confirmed address (business_users_router.accept_mine).

Kevin, 2026-11-21: "when the login access is going out to those the churches
give ... the system have them create account but it makes them sign up like
they are a church." The invite link's token lives only in the browser that
opened it. A confirmation link opened on another browser, or an emailed
sign-in link, comes back without it, and a person with no business met the
new-church setup. The app now asks /team/accept-mine first.

Pins:
  * an invitation waiting for the account's confirmed address is taken,
    exactly as the token link takes it (status, user, name, their record)
  * nothing is taken for an address that isn't confirmed, or can't be read
  * only that address's invitations: never another's, a revoked one, or
    one already taken; the address is matched whole, never as a pattern
  * an unread list is a 503, never "nothing waits"

People and churches here are made up."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest
from fastapi import HTTPException

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import business_users_router as bu  # noqa: E402
from test_seat_person import FB_ROWS, _invite, _user, fb  # noqa: E402,F401


@pytest.fixture
def confirmed(monkeypatch):
    """Who Supabase says has confirmed which address."""
    known = {}
    monkeypatch.setattr(bu, "_confirmed_email", lambda uid: known.get(uid))
    return known


def _seat(email):
    return next(r for r in FB_ROWS["seats"] if r["invited_email"] == email)


def test_a_waiting_invitation_is_taken_by_the_confirmed_address(fb, confirmed):
    _invite("minnie.t@yahoo.com")
    confirmed["u-minnie"] = "minnie.t@yahoo.com"
    got = bu.accept_mine(bu.AcceptMineBody(name="Minnie"), _user("u-minnie", "minnie.t@yahoo.com"))
    assert got == {"ok": True, "accepted": ["b1"], "confirmed": True}
    seat = _seat("minnie.t@yahoo.com")
    assert seat["status"] == "active" and seat["user_id"] == "u-minnie" and seat["contact_id"] == "c-minnie"
    assert bu.my_role("b1", _user("u-minnie", "minnie.t@yahoo.com"))["me"]["first_name"] == "Minnie"
    # Asked again, nothing more waits.
    assert bu.accept_mine(None, _user("u-minnie", "minnie.t@yahoo.com"))["accepted"] == []


def test_an_address_not_confirmed_takes_nothing(fb, confirmed):
    _invite("joann@x.com")
    got = bu.accept_mine(None, _user("u-j", "joann@x.com"))     # Supabase hasn't confirmed it (or can't say)
    assert got == {"ok": True, "accepted": [], "confirmed": False}
    assert _seat("joann@x.com")["status"] == "invited"


def test_only_that_addresss_own_invitations(fb, confirmed):
    _invite("joann@x.com")
    _invite("ann@x.com")
    _invite("hills@x.com")
    _seat("hills@x.com")["status"] = "revoked"
    confirmed["u-ann"] = "ann@x.com"
    assert bu.accept_mine(None, _user("u-ann", "ann@x.com"))["accepted"] == ["b1"]
    assert _seat("joann@x.com")["status"] == "invited" and _seat("ann@x.com")["status"] == "active"
    # A revoked one stays revoked.
    confirmed["u-hill"] = "hills@x.com"
    assert bu.accept_mine(None, _user("u-hill", "hills@x.com"))["accepted"] == []
    assert _seat("hills@x.com")["status"] == "revoked"


def test_the_address_is_matched_whole(fb, confirmed, monkeypatch):
    _invite("joann@x.com")
    seen = []
    real = bu.sb_clients.sb_get_as_service

    def spy(path, *a, **kw):
        seen.append(path)
        return real(path, *a, **kw)
    monkeypatch.setattr(bu.sb_clients, "sb_get_as_service", spy)
    confirmed["u-star"] = "*@x.com"
    assert bu.accept_mine(None, _user("u-star", "*@x.com"))["accepted"] == []
    assert _seat("joann@x.com")["status"] == "invited"
    assert any("invited_email=eq." in p for p in seen) and not any("ilike" in p for p in seen if "business_users" in p)


def test_an_unread_list_is_a_503(fb, confirmed, monkeypatch):
    confirmed["u-j"] = "joann@x.com"
    monkeypatch.setattr(bu.sb_clients, "sb_get_as_service", lambda path, *a, **kw: None)
    with pytest.raises(HTTPException) as e:
        bu.accept_mine(None, _user("u-j", "joann@x.com"))
    assert e.value.status_code == 503


def test_confirmed_email_reads_supabase_and_needs_the_confirmation(monkeypatch):
    import httpx

    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b
    answers = {}
    monkeypatch.setattr(bu.sb_clients, "sb_url", lambda: "https://example.supabase.co")
    monkeypatch.setattr(bu.sb_clients, "sb_headers_service", lambda *a, **k: {})
    monkeypatch.setattr(httpx, "get", lambda url, **kw: answers[url.rsplit("/", 1)[1]])
    a, b, c = ("a0000000-0000-4000-8000-00000000000a", "b0000000-0000-4000-8000-00000000000b",
               "c0000000-0000-4000-8000-00000000000c")
    answers[a] = R(200, {"email": "Sam@X.com", "email_confirmed_at": "2026-11-21T10:00:00Z"})
    answers[b] = R(200, {"email": "lee@x.com", "email_confirmed_at": None})
    answers[c] = R(404, {})
    assert bu._confirmed_email(a) == "sam@x.com"
    assert bu._confirmed_email(b) is None and bu._confirmed_email(c) is None
    assert bu._confirmed_email("not-an-id; drop") is None
