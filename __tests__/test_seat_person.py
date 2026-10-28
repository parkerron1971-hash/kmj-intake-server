"""Each office login is its own person (Kevin, 2026-10-28: the people he
invited "went to sign up and it greeted them as Kevin").

A seat used to have no name of its own, so the app greeted every login with
the business's name for its owner. Now a seat is tied to the business's
record of that person (contacts), found by the invite's email or named at
the invite, and the name they give at sign-up covers the rest."""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import business_users_router as bu  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-step-up")
import ledger_unlock as lu  # noqa: E402

FB_ROWS: dict = {}
OWNER = type("U", (), {"id": "owner1", "email": "kevin@x.com"})()


def _stepup(user_id):
    return type("R", (), {"headers": {lu.UNLOCK_HEADER: lu.mint(str(user_id), lu.SCOPE_ACCESS)["token"]}})()


def _user(uid, email):
    return type("U", (), {"id": uid, "email": email})()


@pytest.fixture
def fb(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    for k in ("BILLING_ENFORCE", "CHURCH_AREAS"):
        monkeypatch.delenv(k, raising=False)
    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1", "name": "Love City Church",
                                  "type": "ministry", "settings": {"practitioner_name": "Kevin"}})
    FB_ROWS["seats"] = fb.rows("business_users")
    fb.rows("businesses").append({"id": "b2", "owner_id": "someone", "name": "Elsewhere"})
    fb.rows("contacts").extend([
        {"id": "c-minnie", "business_id": "b1", "name": "Minnie  Tatum", "email": "Minnie.T@yahoo.com"},
        {"id": "c-joann", "business_id": "b1", "name": "JoAnn Price", "email": "joann@x.com"},
        {"id": "c-ann", "business_id": "b1", "name": "Ann Price", "email": "ann@x.com"},
        # A family on one address.
        {"id": "c-rob", "business_id": "b1", "name": "Robert Hill", "email": "hills@x.com"},
        {"id": "c-ruth", "business_id": "b1", "name": "Ruth Hill", "email": "hills@x.com"},
        {"id": "c-other", "business_id": "b2", "name": "Not Ours", "email": "other@x.com"},
    ])
    return fb


def _invite(email, **kw):
    out = asyncio.run(bu.invite("b1", bu.InviteBody(email=email, **kw), _stepup(OWNER.id), OWNER))
    # The database makes the token; the fake doesn't.
    row = next(r for r in FB_ROWS["seats"] if r["id"] == out["member"]["id"])
    row["token"] = "tok-" + row["id"]
    return row["token"]


def _role(uid, email):
    return bu.my_role("b1", _user(uid, email))


def test_the_invited_person_is_greeted_as_themselves_not_the_owner(fb):
    token = _invite("minnie.t@yahoo.com", lane="people_care")
    v = bu.validate_invite(token)
    # The invite page welcomes her by the name the church knows her by, and
    # says what she's joining as.
    assert (v["name"], v["first_name"], v["lane"]) == ("Minnie Tatum", "Minnie", "People & Care")
    assert v["business_name"] == "Love City Church"
    acc = bu.accept(bu.AcceptBody(token=token, name="Minnie"), _user("u-minnie", "minnie.t@yahoo.com"))
    assert acc["me"] == {"name": "Minnie Tatum", "first_name": "Minnie", "contact_id": "c-minnie"}
    seat = fb.rows("business_users")[0]
    assert seat["contact_id"] == "c-minnie" and seat["status"] == "active"
    # Every app load asks who this login is: her, never Kevin.
    assert _role("u-minnie", "minnie.t@yahoo.com")["me"]["first_name"] == "Minnie"
    # The owner's own answer carries no `me`: the business's settings name them.
    assert "me" not in _role("owner1", "kevin@x.com")


def test_an_email_names_only_its_exact_owner(fb):
    """ann@x.com is not joann@x.com: the lookup is an ilike, and only an
    exact address (in any case) names a person."""
    token = _invite("ANN@x.com")
    assert bu.validate_invite(token)["name"] == "Ann Price"


def test_a_shared_family_address_needs_the_name_they_gave(fb):
    token = _invite("hills@x.com")
    # Two people on the address: the invite guesses no one.
    assert bu.validate_invite(token)["name"] is None
    assert "contact_id" not in fb.rows("business_users")[0]
    acc = bu.accept(bu.AcceptBody(token=token, name="ruth "), _user("u-ruth", "hills@x.com"))
    assert acc["me"]["contact_id"] == "c-ruth"
    assert _role("u-ruth", "hills@x.com")["me"]["name"] == "Ruth Hill"


def test_no_record_keeps_the_name_they_signed_up_with(fb):
    token = _invite("new@x.com")
    acc = bu.accept(bu.AcceptBody(token=token, name="  Dana\tBrooks "), _user("u-dana", "new@x.com"))
    assert acc["me"] == {"name": "Dana Brooks", "first_name": "Dana", "contact_id": None}
    assert _role("u-dana", "new@x.com")["me"]["first_name"] == "Dana"
    # Nothing names a login that gave no name and has no record: no `me`,
    # so the app greets no one rather than the owner.
    token2 = _invite("nobody@x.com")
    bu.accept(bu.AcceptBody(token=token2), _user("u-nobody", "nobody@x.com"))
    assert "me" not in _role("u-nobody", "nobody@x.com")


def test_accept_falls_back_to_the_address_they_signed_up_with(fb):
    token = _invite("work@lovecity.org")
    acc = bu.accept(bu.AcceptBody(token=token), _user("u-j", "JoAnn@x.com"))
    assert acc["me"]["contact_id"] == "c-joann"


def test_an_invite_can_name_the_person_but_only_one_of_its_own(fb):
    token = _invite("church@x.com", contact_id="c-rob")
    assert bu.validate_invite(token)["first_name"] == "Robert"
    with pytest.raises(HTTPException) as e:
        _invite("x@x.com", contact_id="c-other")
    assert e.value.status_code == 404


def test_the_team_list_shows_names(fb):
    _invite("minnie.t@yahoo.com")
    _invite("new@x.com")
    members = bu.list_team("b1", OWNER)["members"]
    by_email = {m["invited_email"]: m["person"] for m in members}
    assert by_email["minnie.t@yahoo.com"]["name"] == "Minnie Tatum"
    assert by_email["new@x.com"] is None
