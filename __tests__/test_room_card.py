"""The room card: what it is for, what is in it now, the one next thing,
and where it sits. Built without a model call; must open for an empty
day-one business and for a full one, and must never raise.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import business_track_router as btr  # noqa: E402
import room_card as rc  # noqa: E402
import room_orientation as ro  # noqa: E402
import sb_clients  # noqa: E402

BIZ = {"id": "b1", "name": "Fade Society", "type": "personal_services", "settings": {}}


def _wire(monkeypatch, table_rows=None, fail=False):
    """table_rows: {table: rows}. Unknown tables read as [] (a fresh business)."""
    table_rows = table_rows or {}
    def _get(path):
        if fail:
            raise RuntimeError("down")
        table = path.lstrip("/").split("?")[0]
        rows = table_rows.get(table, [])
        # crude status filter support for the invoices tiles
        if "status=eq.paid" in path:
            rows = [r for r in rows if r.get("status") == "paid"]
        elif "status=in.(" in path:
            rows = [r for r in rows if r.get("status") in ("sent", "overdue", "open", "unpaid")]
        elif "status=eq.lead" in path:
            rows = [r for r in rows if r.get("status") == "lead"]
        return rows
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)


def _plugins(monkeypatch, items):
    monkeypatch.setattr(btr, "resolve_plugins", lambda biz: items)


PLUGINS = [
    {"key": "import_contacts", "title": "Bring your client list over", "why": "first domino",
     "nav": {"tab": "operate", "sub": "contacts"}, "done": False, "blocked_by": []},
    {"key": "offerings", "title": "Load what you sell", "why": "prices drive everything",
     "nav": {"tab": "operate", "sub": "offerings-manager"}, "done": False, "blocked_by": []},
    {"key": "availability", "title": "Set the hours you actually work", "why": "booking",
     "nav": {"tab": "build", "page": "booking"}, "done": False, "blocked_by": ["offerings"]},
    {"key": "payments", "title": "Connect how you get paid", "why": "money",
     "nav": {"tab": "build", "page": "integrations"}, "done": False, "blocked_by": []},
]


class TestShape:
    def test_a_day_one_contacts_card(self, monkeypatch):
        _wire(monkeypatch)
        _plugins(monkeypatch, PLUGINS)
        card = rc.build_room_card(BIZ, "operate", sub="contacts")
        assert card["ok"] and card["key"] == "operate/contacts" and card["known"]
        assert card["label"] == "Contacts" and card["tab_label"] == "Operate"
        assert card["purpose"].endswith(".") and card["next_rule"]
        labels = [t["label"] for t in card["now"]]
        assert labels == ["people", "leads"]
        assert [t["value"] for t in card["now"]] == ["0", "0"]
        assert [r["tab"] for r in card["rooms"]] == ["home", "operate", "grow", "build"]
        assert {d["leaf"] for d in card["doors"]} >= {"contacts", "invoices", "calendar", "queue"}
        assert all(d["key"].startswith("operate/") for d in card["doors"])

    def test_live_numbers_are_the_practitioners_own(self, monkeypatch):
        _wire(monkeypatch, {
            "contacts": [{"id": i, "status": "lead" if i < 3 else "active"} for i in range(12)],
            "invoices": [{"id": 1, "status": "paid"}, {"id": 2, "status": "sent"}, {"id": 3, "status": "overdue"}],
        })
        _plugins(monkeypatch, PLUGINS)
        c = rc.build_room_card(BIZ, "operate", sub="contacts")
        assert {t["label"]: t["value"] for t in c["now"]} == {"people": "12", "leads": "3"}
        inv = rc.build_room_card(BIZ, "operate", sub="invoices")
        assert {t["label"]: t["value"] for t in inv["now"]} == {"open invoices": "2", "paid": "1"}

    def test_counts_cap_at_a_glance(self, monkeypatch):
        _wire(monkeypatch, {"contacts": [{"id": i} for i in range(rc.COUNT_CAP + 40)]})
        _plugins(monkeypatch, [])
        c = rc.build_room_card(BIZ, "operate", sub="contacts")
        assert c["now"][0]["value"] == f"{rc.COUNT_CAP}+"


class TestNextMove:
    def test_prefers_the_move_that_lives_in_this_room(self, monkeypatch):
        _wire(monkeypatch)
        _plugins(monkeypatch, PLUGINS)
        c = rc.build_room_card(BIZ, "operate", sub="offerings-manager")
        assert c["next_move"]["key"] == "offerings" and c["next_move"]["in_this_room"] is True
        assert c["next_move"]["chief_can_do_it_here"] is True

    def test_a_tab_card_takes_any_move_in_the_tab(self, monkeypatch):
        _wire(monkeypatch)
        _plugins(monkeypatch, PLUGINS)
        c = rc.build_room_card(BIZ, "build")
        # availability is blocked; payments is the first unblocked build move
        assert c["next_move"]["key"] == "payments" and c["next_move"]["in_this_room"] is True
        assert c["next_move"]["chief_can_do_it_here"] is False

    def test_falls_back_to_the_first_undone_anywhere(self, monkeypatch):
        _wire(monkeypatch)
        _plugins(monkeypatch, PLUGINS)
        c = rc.build_room_card(BIZ, "grow", sub="reviews")
        assert c["next_move"]["key"] == "import_contacts" and c["next_move"]["in_this_room"] is False

    def test_all_done_means_no_next_move(self, monkeypatch):
        _wire(monkeypatch)
        _plugins(monkeypatch, [dict(p, done=True) for p in PLUGINS])
        assert rc.build_room_card(BIZ, "operate", sub="contacts")["next_move"] is None


class TestNeverRaises:
    def test_reads_down_still_opens_the_card(self, monkeypatch):
        _wire(monkeypatch, fail=True)
        def boom(biz):
            raise RuntimeError("probes down")
        monkeypatch.setattr(btr, "resolve_plugins", boom)
        c = rc.build_room_card(BIZ, "operate", sub="contacts")
        assert c["ok"] and c["now"] == [] and c["next_move"] is None
        assert c["purpose"] and c["doors"]

    def test_unknown_room_falls_back_to_the_tab(self, monkeypatch):
        _wire(monkeypatch)
        _plugins(monkeypatch, [])
        c = rc.build_room_card(BIZ, "grow", sub="something-new")
        assert c["known"] is False and c["label"] == "Grow" and c["doors"]
        c2 = rc.build_room_card(BIZ, None)
        assert c2["ok"] and c2["label"] == "this page"


class TestRoute:
    def test_router_is_registered_and_gated(self):
        import inspect
        import room_card_router as rcr
        assert "/rooms/{business_id}/card" in {r.path for r in rcr.router.routes}
        assert "require_role" in inspect.getsource(rcr._gate)
        # Registered with the app (the source is the cheapest honest check;
        # importing the whole app in a unit test drags in every router).
        src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
        assert "from room_card_router import router as room_card_router" in src
        assert "app.include_router(room_card_router)" in src
