"""Therapy, counseling and health care practices are paused (2026-10-12).

No new one may be opened: the platform has no BAA with the vendors that would
hold their clients' data, and for a practice that bills insurance even the
schedule and invoices are protected health information. Lawyers, massage,
fitness and wellness stay open.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest
from fastapi import HTTPException

import launch_access as la
import vertical_scope as vs
from test_i2_gl_sync import FakeSB


@pytest.fixture(autouse=True)
def _default_pause(monkeypatch):
    monkeypatch.delenv("PAUSED_VERTICALS", raising=False)


@pytest.mark.parametrize("btype", [
    "therapist", "Therapist / Counselor", "counselor", "LMFT practice", "lcsw",
    "Psychologist", "mental_health", "Northside Behavioral Health",
    "physical therapy", "speech-therapy clinic",
    "Dental office", "chiropractor", "Family medical practice", "home health",
    "Lawrence family dental",
])
def test_these_are_paused(btype):
    assert vs.is_paused(btype) is True


@pytest.mark.parametrize("btype", [
    "barber", "lawyer", "Law firm", "Attorney and Counselor at Law", "legal counsel",
    "massage therapy", "fitness_wellness", "wellness studio", "life coach", "coach",
    "consultant", "ministry", "custom", "", None,
])
def test_these_stay_open(btype):
    assert vs.is_paused(btype) is False


def test_the_switch_reopens_one_family_or_all(monkeypatch):
    monkeypatch.setenv("PAUSED_VERTICALS", "therapist")
    assert vs.is_paused("therapist") and not vs.is_paused("Dental office")
    monkeypatch.setenv("PAUSED_VERTICALS", "none")
    assert not vs.is_paused("therapist") and not vs.is_paused("Dental office")


def _u(uid):
    return type("U", (), {"id": uid})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    for k in ("BILLING_ENFORCE", "LAUNCH_INVITE_ONLY", "STRIPE_PRICE_ID_STARTER"):
        monkeypatch.delenv(k, raising=False)
    return fb


def test_a_therapy_practice_is_not_opened(fake):
    with pytest.raises(HTTPException) as e:
        la.create_business(la.CreateBusinessBody(name="Vale Counseling", type="therapist"), _u("u1"))
    assert e.value.status_code == 422
    assert e.value.detail["error"] == "vertical_paused"
    assert "therapy, counseling or health care" in e.value.detail["message"]
    assert fake.rows("businesses") == [], "nothing was written"


def test_a_law_firm_still_opens(fake):
    out = la.create_business(la.CreateBusinessBody(name="Reyes Family Law", type="lawyer"), _u("u2"))
    assert out["ok"] and out["business"]["name"] == "Reyes Family Law"
