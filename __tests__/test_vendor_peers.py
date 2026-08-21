"""THE SOURCING DESK stage 4 — the anonymous peer signal.

This is the one stage that is a privacy decision wearing an engineering
costume, so the tests are about what must NEVER happen:

  - a business that is not contributing must not read the signal
  - a count below the k threshold must not reach the wire, and must not
    quietly become a zero on the way (a "0" and a "not enough to say" are
    different facts and must not look alike)
  - a business must not be able to ask about a domain it does not already
    hold, or this is a directory you can walk one domain at a time

The k threshold and the reciprocity rule are ALSO enforced inside the
database function, on purpose — these tests cover the router's half, and
the SQL half was proven against production in a rolled-back DO block.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import sourcing_router as sr


class _U:
    id = "owner"


BIZ = "biz1"


# ─── The domain mirror must agree with the generated column ──────────
#
# These six expectations are not invented: they are what
# suppliers.domain actually returned for these inputs on production,
# recorded when the column was verified. If the Python drifts from the
# SQL, a legitimate lookup gets dropped — so the pinning matters.

@pytest.mark.parametrize("raw,expected", [
    ("https://www.Northwind.com/wholesale?x=1", "northwind.com"),
    ("Orders@Northwind.com", "northwind.com"),
    ("northwind.com/", "northwind.com"),
    ("  HTTP://NorthWind.com  ", "northwind.com"),
    ("", None),
    (None, None),
])
def test_the_python_domain_matches_the_sql_column(raw, expected):
    assert sr._domain_of(raw) == expected


# ─── Reciprocity: not contributing means no answer ───────────────────

def _install(monkeypatch, *, sharing_rows, suppliers=None, searches=None,
             rpc=None, posts=None, patches=None):
    def _get(path):
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": "owner"}]
        if path.startswith("/vendor_sharing_consent"):
            return sharing_rows
        if path.startswith("/suppliers"):
            return suppliers if suppliers is not None else []
        if path.startswith("/sourcing_searches"):
            return searches if searches is not None else []
        return []

    def _post(path, body, **kw):
        if posts is not None:
            posts.append((path, body))
        if path.startswith("/rpc/") and rpc is not None:
            return rpc(body)
        return [body]

    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", _post)
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service",
                        lambda p, b: (patches.append((p, b))
                                      if patches is not None else None))


def test_a_business_that_shares_nothing_reads_nothing(monkeypatch):
    posts = []
    _install(monkeypatch, sharing_rows=[], posts=posts)
    out = sr.peer_counts(BIZ, sr.PeersBody(domains=["northwind.com"]), user=_U())
    assert out["sharing"] is False
    assert out["peers"] == {}
    assert not [p for p, _ in posts if p.startswith("/rpc/")], \
        "asked the database about peers without contributing"


# ─── No enumeration ──────────────────────────────────────────────────

def test_a_domain_the_business_does_not_hold_is_never_asked_about(monkeypatch):
    """Otherwise this is a directory you can walk one domain at a time —
    the exact thing the arc refused to build."""
    asked = []

    def _rpc(body):
        asked.append(body["p_domain"])
        return [{"peers_any": 5, "peers_trade": None, "shared": True,
                 "trade": "agency"}]

    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[{"domain": "northwind.com"}],
             rpc=_rpc)
    out = sr.peer_counts(BIZ, sr.PeersBody(
        domains=["northwind.com", "a-competitor.example"]), user=_U())
    assert asked == ["northwind.com"]
    assert "a-competitor.example" not in out["peers"]


def test_a_domain_from_their_own_search_results_is_askable(monkeypatch):
    """A candidate their own paid search turned up is theirs to ask
    about, even before they save it."""
    asked = []

    def _rpc(body):
        asked.append(body["p_domain"])
        return [{"peers_any": 3, "peers_trade": None, "shared": True,
                 "trade": "agency"}]

    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[],
             searches=[{"candidates": [
                 {"name": "Acme", "website": "https://www.acme.com/trade",
                  "source_url": "https://acme.com/trade"}]}],
             rpc=_rpc)
    out = sr.peer_counts(BIZ, sr.PeersBody(domains=["acme.com"]), user=_U())
    assert asked == ["acme.com"]
    assert out["peers"]["acme.com"]["any"] == 3


def test_the_request_is_capped(monkeypatch):
    asked = []

    def _rpc(body):
        asked.append(body["p_domain"])
        return [{"peers_any": None, "shared": True}]

    many = [f"v{i}.com" for i in range(200)]
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[{"domain": d} for d in many], rpc=_rpc)
    sr.peer_counts(BIZ, sr.PeersBody(domains=many), user=_U())
    assert len(asked) <= sr._PEER_DOMAIN_CAP


# ─── Below the threshold reaches nobody, and never becomes a zero ────

def test_a_count_below_the_threshold_is_absent_not_zero(monkeypatch):
    """'Not enough to say' and 'nobody uses them' are different facts.
    A zero here would be an empty state that lies."""
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[{"domain": "northwind.com"}],
             rpc=lambda b: [{"peers_any": None, "peers_trade": None,
                             "shared": True, "trade": "agency"}])
    out = sr.peer_counts(BIZ, sr.PeersBody(domains=["northwind.com"]), user=_U())
    assert "northwind.com" not in out["peers"]
    assert out["peers"] == {}


def test_a_cleared_count_comes_through_with_its_trade_slice(monkeypatch):
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[{"domain": "northwind.com"}],
             rpc=lambda b: [{"peers_any": 7, "peers_trade": 4,
                             "shared": True, "trade": "agency"}])
    out = sr.peer_counts(BIZ, sr.PeersBody(domains=["northwind.com"]), user=_U())
    assert out["peers"]["northwind.com"] == {"any": 7, "trade": 4,
                                             "trade_name": "agency"}


def test_a_trade_slice_below_the_threshold_stays_absent(monkeypatch):
    """The two slices are gated independently — the platform-wide number
    appearing must not drag an identifying trade number along with it."""
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[{"domain": "northwind.com"}],
             rpc=lambda b: [{"peers_any": 5, "peers_trade": None,
                             "shared": True, "trade": "agency"}])
    out = sr.peer_counts(BIZ, sr.PeersBody(domains=["northwind.com"]), user=_U())
    assert out["peers"]["northwind.com"]["any"] == 5
    assert out["peers"]["northwind.com"]["trade"] is None


def test_one_domain_failing_does_not_lose_the_others(monkeypatch):
    def _rpc(body):
        if body["p_domain"] == "broken.com":
            raise RuntimeError("supabase is having a day")
        return [{"peers_any": 4, "peers_trade": None, "shared": True,
                 "trade": "agency"}]

    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             suppliers=[{"domain": "broken.com"}, {"domain": "fine.com"}],
             rpc=_rpc)
    out = sr.peer_counts(BIZ, sr.PeersBody(
        domains=["broken.com", "fine.com"]), user=_U())
    assert "fine.com" in out["peers"]
    assert "broken.com" not in out["peers"]


# ─── Consent ─────────────────────────────────────────────────────────

def test_turning_it_off_stamps_a_date_rather_than_deleting(monkeypatch):
    """'They turned it off in September' is a fact worth being able to
    answer."""
    patches = []
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": None}],
             patches=patches)
    out = sr.set_sharing(BIZ, sr.SharingBody(sharing=False), user=_U())
    assert out["sharing"] is False
    assert patches and patches[0][1]["opted_out_at"] is not None


def test_turning_it_back_on_clears_the_stamp(monkeypatch):
    patches = []
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_out_at": "2026-08-01"}],
             patches=patches)
    sr.set_sharing(BIZ, sr.SharingBody(sharing=True), user=_U())
    assert patches[0][1]["opted_out_at"] is None
    assert patches[0][1]["opted_in_at"]


def test_opting_out_when_there_was_never_consent_writes_nothing(monkeypatch):
    """A row here records a consent that was given. Opting out of
    something never agreed to must not create one."""
    posts, patches = [], []
    _install(monkeypatch, sharing_rows=[], posts=posts, patches=patches)
    out = sr.set_sharing(BIZ, sr.SharingBody(sharing=False), user=_U())
    assert out["sharing"] is False
    assert [p for p, _ in posts if "consent" in p] == []
    assert patches == []


def test_sharing_state_reads_opted_out_as_off(monkeypatch):
    _install(monkeypatch,
             sharing_rows=[{"business_id": BIZ, "opted_in_at": "2026-08-01",
                            "opted_out_at": "2026-08-15"}])
    out = sr.sharing_state(BIZ, user=_U())
    assert out["sharing"] is False
    assert out["since"] is None
    assert out["min_peers"] == sr.PEER_MIN


def test_only_the_owner_can_change_what_gets_shared(monkeypatch):
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service",
                        lambda path: [{"id": BIZ, "owner_id": "somebody-else"}])

    class _Other:
        id = "intruder"

    with pytest.raises(HTTPException) as e:
        sr.set_sharing(BIZ, sr.SharingBody(sharing=True), user=_Other())
    assert e.value.status_code == 403
