# __tests__/test_worship_timers.py
#
# Timers from the plan, the service clock and the preacher's ask (ChurchSavvy
# round 5, canvas board 24; worship_show.py + worship_show_router.py). Pins:
#   * the ask is checked: its minutes, its item, a time with its zone, the
#     booth's yes or no
#   * the ask belongs to its item: a new item or another service drops it; a
#     press from a booth that hasn't heard of it keeps it; of two asks the
#     newer wins, and the booth's answer to the same ask stands
#   * the server keeps the service's log (the booth never sends it): one line
#     per item as it goes up, none for something on the spot, a new service
#     starts a new log
#   * over HTTP: only a stage screen's link asks; nothing up, nothing to ask
#     for; a second tap asks nothing new; the booth's next press keeps the
#     ask, its answer lands, a new item drops it

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import worship_show as wsh
from test_worship_show_router import BIZ, api, plan  # noqa: E402,F401  (api is the fixture)

SID = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
AT = "2026-11-01T17:24:00+00:00"


def ask(**kw):
    return {"minutes": 5, "item_id": "sermon", "from": "Pastor's phone", "at": AT, "answer": None, **kw}


def test_the_ask_is_checked():
    assert wsh.clean_ask(ask(**{"from": "  Pastor's   phone "}))["from"] == "Pastor's phone"
    yes = wsh.clean_ask(ask(answer="yes", answered_at="2026-11-01T17:25:00Z"))
    assert (yes["answer"], yes["answered_at"]) == ("yes", "2026-11-01T17:25:00Z")
    assert wsh.clean_live({"item_id": "sermon", "ask": ask()})["ask"]["minutes"] == 5
    for bad, words in [(ask(minutes=0), "1 to 15"), (ask(minutes=5.0), "1 to 15"), (ask(minutes=True), "1 to 15"),
                       (ask(item_id="Sermon!"), "isn't an item"), (ask(at="2026-11-01T17:24:00"), "isn't a time"),
                       (ask(at="soon"), "isn't a time"), (ask(answer="maybe"), "yes or no"),
                       (ask(answer="no"), "isn't a time"), ("5 more", "request for more time")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_ask(bad)


def test_the_ask_belongs_to_its_item():
    prev = {"service_id": SID, "item_id": "sermon", "ask": ask()}
    # A booth press that hasn't heard of it keeps it.
    assert wsh.carry_ask(prev, {"service_id": SID, "item_id": "sermon", "slide": 2})["ask"] == ask()
    # The booth's answer to the same ask stands.
    answered = ask(answer="no", answered_at="2026-11-01T17:25:00+00:00")
    assert wsh.carry_ask(prev, {"service_id": SID, "item_id": "sermon", "ask": answered})["ask"]["answer"] == "no"
    # A stale booth can't put back an older, answered ask over a newer one.
    newer = {"service_id": SID, "item_id": "sermon", "ask": ask(at="2026-11-01T17:40:00+00:00")}
    assert wsh.carry_ask(newer, {"service_id": SID, "item_id": "sermon", "ask": answered})["ask"]["answer"] is None
    # A booth that hasn't heard the answer yet presses with the same ask unanswered: the answer stands (PR review).
    said = {"service_id": SID, "item_id": "sermon", "ask": answered}
    assert wsh.carry_ask(said, {"service_id": SID, "item_id": "sermon", "ask": ask()})["ask"]["answer"] == "no"
    # A new item, or another service, drops it.
    assert "ask" not in wsh.carry_ask(prev, {"service_id": SID, "item_id": "well", "ask": ask()})
    assert "ask" not in wsh.carry_ask(prev, {"service_id": OTHER, "item_id": "sermon"})
    assert "ask" not in wsh.carry_ask(None, {"service_id": SID, "item_id": None})


def test_the_server_keeps_the_log():
    at = "2026-11-01T17:00:00+00:00"
    s1 = wsh.carry_log(None, {"service_id": SID, "item_id": "count", "since": "2026-11-01T16:55:00Z"}, at)
    assert s1["log"] == [{"id": "count", "at": "2026-11-01T16:55:00Z"}]
    # The same item again (a new slide) adds nothing; the next item adds a line.
    s2 = wsh.carry_log(s1, {"service_id": SID, "item_id": "count", "slide": 1}, at)
    s3 = wsh.carry_log(s2, {"service_id": SID, "item_id": "well"}, at)
    assert [e["id"] for e in s3["log"]] == ["count", "well"] and s3["log"][1]["at"] == at
    # Something on the spot counts in the item it interrupted.
    s4 = wsh.carry_log(s3, {"service_id": SID, "item_id": "well", "adhoc": {"kind": "verse"}}, at)
    assert [e["id"] for e in s4["log"]] == ["count", "well"]
    # A booth's own log is never taken: clean_live doesn't keep it.
    assert "log" not in wsh.clean_live({"item_id": "well", "log": [{"id": "x", "at": at}]})
    # Another service starts a new log; at most MAX_LOG lines.
    assert wsh.carry_log(s4, {"service_id": OTHER, "item_id": "well"}, at)["log"] == [{"id": "well", "at": at}]
    long = {"service_id": SID, "log": [{"id": f"i{k}", "at": at} for k in range(wsh.MAX_LOG)]}
    assert len(wsh.carry_log(long, {"service_id": SID, "item_id": "last"}, at)["log"]) == wsh.MAX_LOG
    assert "log" not in wsh.carry_log(s4, {"service_id": None, "item_id": None}, at)


def test_the_pastors_phone_asks_the_booth(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    sid = plan(as_).json()["service"]["id"]
    stage = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Pastor's phone", "role": "stage"}).json()["screen"]["token"]
    room = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    # Nothing up yet: nothing to ask more time for.
    assert as_("stranger").post(f"/worship/screen/{stage}/ask").status_code == 409
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 0}})
    assert as_("stranger").post(f"/worship/screen/{room}/ask").status_code == 403
    r = as_("stranger").post(f"/worship/screen/{stage}/ask")
    assert r.status_code == 200, r.text
    first = r.json()["ask"]
    assert (first["minutes"], first["item_id"], first["from"], first["answer"]) == (5, "well", "Pastor's phone", None)
    # A second tap while it waits asks nothing new.
    assert as_("stranger").post(f"/worship/screen/{stage}/ask").json()["ask"]["at"] == first["at"]
    # The booth's next press, from a booth that hadn't heard yet, keeps it; the log has the item.
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 1}})
    live = as_("member").get(f"/worship/live?business_id={BIZ}").json()["state"]
    assert live["ask"]["at"] == first["at"] and [e["id"] for e in live["log"]] == ["well"]
    # The booth gives the 5: the answer lands.
    yes = {**first, "answer": "yes", "answered_at": "2026-11-01T17:25:00Z"}
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 1, "ask": yes,
                                                                          "message": "5 minutes is fine"}})
    live = as_("member").get(f"/worship/live?business_id={BIZ}").json()["state"]
    assert live["ask"]["answer"] == "yes" and live["message"] == "5 minutes is fine"
    # The next item drops it, and the log has both.
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "word", "slide": 0}})
    live = as_("member").get(f"/worship/live?business_id={BIZ}").json()["state"]
    assert "ask" not in live and [e["id"] for e in live["log"]] == ["well", "word"]
    # A failed save still reaches the booth (the hub has it), and says so, like a press (PR review).
    db.fail.add("worship_live")
    r = as_("stranger").post(f"/worship/screen/{stage}/ask")
    assert r.status_code == 200 and r.json()["saved"] is False
    assert as_("member").get(f"/worship/live?business_id={BIZ}").json()["state"]["ask"]["item_id"] == "word"
    db.fail.discard("worship_live")
    # The switch off closes the ask with every screen link.
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert as_("stranger").post(f"/worship/screen/{stage}/ask").status_code == 404


def test_a_press_and_an_ask_never_cross(api, monkeypatch):
    """Each reads the live state, adds to it and writes it back, under the church's lock,
    so an ask can't land between a press's read and its write and undo it (PR review)."""
    import threading
    import time

    import worship_show_router as wsr

    db, as_, client = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    sid = plan(as_).json()["service"]["id"]
    stage = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Pastor's phone", "role": "stage"}).json()["screen"]["token"]
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 0}})
    got = {}
    lock = wsr._church_lock(BIZ)
    with lock:
        t = threading.Thread(target=lambda: got.update(r=client.post(f"/worship/screen/{stage}/ask")))
        t.start()
        time.sleep(0.3)
        assert t.is_alive()                      # the ask waits while a press holds the church
    t.join(5)
    assert got["r"].status_code == 200 and got["r"].json()["ask"]["item_id"] == "well"
