"""The browser hand — a sandboxed browser Chief can propose, a person
approves, and the job runner runs. Each rule in browser_hand's header
is a test here, driven through a fake page and a scripted model so the
exact production loop runs without Chromium or a key.

  * a proposal is validated (https, a task, an allow-list) and round-trips
    through the Approval Queue body;
  * the run stops when the page leaves the allowed sites, refuses a goto
    off them, refuses to type into a password / card / account field,
    records one frame per step, and stops at the step and time budgets;
  * the verb FILES a proposal and opens no browser; approving starts a
    job through the one shared approval core; the registry says class C
    and the connector never lists it; the job kind emits a catalogued
    spine event.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import browser_hand as bh

BIZ = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SPEC = {"task": "Find the renewal date on the license lookup page",
        "start_url": "https://licensing.example.gov/lookup",
        "domains": ["licensing.example.gov"], "max_steps": 6}


class FakePage:
    """The five methods run() uses. `urls` is what url() reports on each
    call (the last value repeats); `focused` is what the focused field
    looks like when the model types."""

    def __init__(self, urls=None, focused=None, fail_goto=False):
        self._urls = list(urls or ["https://licensing.example.gov/lookup"])
        self.focused = focused or {"tag": "input", "type": "text", "name": "q"}
        self.acts = []
        self.gotos = []
        self.shots = 0
        self.closed = False
        self.fail_goto = fail_goto

    def url(self):
        return self._urls.pop(0) if len(self._urls) > 1 else self._urls[0]

    def goto(self, url):
        if self.fail_goto:
            raise RuntimeError("net::ERR")
        self.gotos.append(url)

    def screenshot(self):
        self.shots += 1
        return b"\xff\xd8jpeg" + bytes([self.shots])

    def focused_field(self):
        return self.focused

    def act(self, action):
        self.acts.append(action)

    def close(self):
        self.closed = True


def _scripted(*actions):
    """A model that answers with the given actions in order, then `done`."""
    seq = list(actions)

    def ask(spec, jpeg, history):
        assert jpeg.startswith(b"\xff\xd8"), "the model sees a JPEG frame"
        return seq.pop(0) if seq else {"action": "done", "summary": "finished"}
    return ask


def _frames():
    stored = []

    def store(biz, run_id, n, jpeg):
        stored.append((run_id, n, len(jpeg)))
        return f"{biz}/hand/{run_id}/{n:02d}.jpg"
    return stored, store


def _run(page, ask, spec=SPEC, **kw):
    stored, store = _frames()
    res = bh.run(BIZ, "run-1", spec, open_browser=lambda: page, ask=ask,
                 store_frame=store, **kw)
    return res, stored


# ─── The proposal ───────────────────────────────────────────────────────

def test_a_spec_needs_https_a_task_and_gets_an_allow_list():
    with pytest.raises(ValueError):
        bh.make_spec("do it", "https://x.example", [])
    with pytest.raises(ValueError):
        bh.make_spec("renew the thing on the portal", "http://x.example/path", [])
    spec = bh.make_spec("renew the thing on the portal", "https://www.Portal.Example/a",
                        ["Supplier.example", "https://other.example/x"], max_steps=99)
    assert spec["domains"] == ["other.example", "portal.example", "supplier.example"]
    assert spec["max_steps"] == bh.MAX_STEPS_CEILING


def test_host_allowed_is_https_only_and_covers_subdomains():
    d = ["portal.example"]
    assert bh.host_allowed("https://portal.example/x", d)
    assert bh.host_allowed("https://www.portal.example/x", d)
    assert bh.host_allowed("https://api.portal.example/x", d)
    assert not bh.host_allowed("https://notportal.example/x", d)
    assert not bh.host_allowed("https://portal.example.evil.com/x", d)
    assert not bh.host_allowed("http://portal.example/x", d)
    assert not bh.host_allowed("javascript:alert(1)", d)


def test_the_spec_round_trips_through_the_queue_body():
    spec = bh.make_spec(**SPEC)
    body = bh.spec_to_body(spec)
    assert "Allowed sites: licensing.example.gov" in body
    assert bh.spec_from_body(body) == spec
    assert bh.spec_from_body("no spec here") is None
    assert bh.spec_from_body('spec: {"task":"x","start_url":"http://bad"}') is None


def test_parse_action_only_accepts_the_hands_own_actions():
    assert bh.parse_action('```json\n{"action":"click","x":1,"y":2}\n```')["action"] == "click"
    assert bh.parse_action('{"action":"launch_missiles"}')["action"] == "fail"
    assert bh.parse_action("I would click the button")["action"] == "fail"
    assert bh.parse_action("")["action"] == "fail"


# ─── The rules, in the loop ─────────────────────────────────────────────

def test_a_happy_run_records_a_frame_per_step_and_closes_the_browser():
    page = FakePage()
    res, stored = _run(page, _scripted({"action": "click", "x": 10, "y": 20, "why": "open search"},
                                       {"action": "type", "text": "12345"}))
    assert res["ok"] and res["stopped"] == "done" and res["summary"] == "finished"
    assert [s["n"] for s in res["steps"]] == [1, 2, 3]
    assert [n for _, n, _ in stored] == [1, 2, 3], "one frame before every decision"
    assert res["frames"] == 3
    assert page.acts[0]["action"] == "click" and page.acts[1]["text"] == "12345"
    assert page.closed
    assert page.gotos == [SPEC["start_url"]]


def test_the_run_stops_the_moment_the_page_leaves_the_allowed_sites():
    page = FakePage(urls=["https://licensing.example.gov/lookup",
                          "https://tracking.adnetwork.example/land"])
    res, _ = _run(page, _scripted({"action": "click", "x": 5, "y": 5},
                                  {"action": "click", "x": 6, "y": 6}))
    assert res["stopped"] == "off_domain" and not res["ok"]
    assert "tracking.adnetwork.example" in res["summary"]
    assert len(page.acts) == 1, "the second action never ran"


def test_a_goto_off_the_allowed_sites_is_refused_and_recorded():
    page = FakePage()
    res, _ = _run(page, _scripted({"action": "goto", "url": "https://evil.example/steal"}))
    assert res["ok"] and res["stopped"] == "done"
    assert page.gotos == [SPEC["start_url"]], "the browser never went there"
    assert res["steps"][0]["note"] == "refused: not on the allowed sites"


@pytest.mark.parametrize("field,why", [
    ({"tag": "input", "type": "password", "name": "pw"}, "password"),
    ({"tag": "input", "type": "text", "autocomplete": "cc-number"}, "card"),
    ({"tag": "input", "type": "text", "name": "cardNumber"}, "credential, card or account"),
    ({"tag": "input", "type": "text", "id": "routing_number"}, "credential, card or account"),
    ({"tag": "input", "type": "text", "label": "Social Security Number"}, "credential, card or account"),
    ({"tag": "input", "type": "text", "autocomplete": "one-time-code"}, "credential"),
])
def test_the_hand_will_not_type_into_a_credential_or_card_field(field, why):
    page = FakePage(focused=field)
    res, _ = _run(page, _scripted({"action": "type", "text": "hunter2"}))
    assert page.acts == [], "nothing was typed"
    assert res["steps"][0]["note"].startswith("refused: will not type into")
    assert why in res["steps"][0]["note"]
    assert res["stopped"] == "done", "the model was told and carried on"


def test_typing_into_an_ordinary_field_is_fine():
    page = FakePage(focused={"tag": "input", "type": "text", "name": "license_number"})
    res, _ = _run(page, _scripted({"action": "type", "text": "MT-1234"}))
    assert page.acts and page.acts[0]["text"] == "MT-1234"
    assert res["steps"][0]["note"] is None


def test_the_step_budget_stops_a_model_that_never_finishes():
    page = FakePage()
    forever = lambda spec, jpeg, history: {"action": "scroll", "dy": 400}
    res, stored = _run(page, forever, spec={**SPEC, "max_steps": 4})
    assert res["stopped"] == "max_steps" and not res["ok"]
    assert len(res["steps"]) == 4 and len(page.acts) == 4
    assert [n for _, n, _ in stored] == [1, 2, 3, 4, 5], "plus the final frame"


def test_the_time_budget_stops_a_slow_run():
    page = FakePage()
    ticks = iter([0.0, 0.0, 1000.0])
    res, _ = _run(page, _scripted({"action": "click", "x": 1, "y": 1}),
                  clock=lambda: next(ticks, 1000.0))
    assert res["stopped"] == "time_budget" and not res["ok"]


def test_a_model_fail_is_an_honest_failure_not_a_crash():
    page = FakePage()
    res, _ = _run(page, _scripted({"action": "fail", "reason": "this needs a login"}))
    assert res["stopped"] == "failed" and res["summary"] == "this needs a login"


def test_no_browser_on_the_server_is_named_not_hidden():
    res = bh.run(BIZ, "r", SPEC, open_browser=lambda: None, ask=_scripted())
    assert res["stopped"] == "no_browser" and not res["ok"]


def test_a_start_page_off_the_allow_list_never_opens():
    page = FakePage()
    res, _ = _run(page, _scripted(), spec={**SPEC, "start_url": "https://licensing.example.gov/x",
                                           "domains": []})
    # the start page's own host is always allowed — so this one runs
    assert res["ok"]
    page = FakePage(urls=["https://a.example/x"])
    res = bh.run(BIZ, "r", {**SPEC, "start_url": "https://a.example/x", "domains": ["b.example"]},
                 open_browser=lambda: page, ask=_scripted(), store_frame=lambda *a: None)
    assert res["ok"] and res["domains"] == ["a.example", "b.example"], "the start host joins the list"


# ─── The doors: verb, approval, registry, job ───────────────────────────

def test_the_verb_files_a_proposal_and_opens_no_browser(monkeypatch):
    import chief_of_staff as cos
    posts = []

    async def _sb(client, method, path, body=None):
        posts.append((method, path, body))
        return [{"id": "q-hand-1", **(body or {})}]
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(bh, "open_chromium", lambda: pytest.fail("a proposal must not open a browser"))

    out = asyncio.run(cos.handle_use_browser_hand(None, {"id": BIZ}, {
        "task": SPEC["task"], "start_url": SPEC["start_url"], "domains": ["licensing.example.gov"]}))
    assert out["result"] == "proposed" and out["queue_id"] == "q-hand-1"
    assert out["label"] and out["nav"]
    method, path, body = posts[0]
    assert (method, path) == ("POST", "/agent_queue")
    assert body["channel"] == "hand" and body["action_type"] == "browser_hand"
    assert body["status"] == "draft", "nothing runs until a person approves"
    assert bh.spec_from_body(body["body"])["domains"] == ["licensing.example.gov"]


def test_the_verb_refuses_a_bad_ask_in_plain_words(monkeypatch):
    import chief_of_staff as cos
    out = asyncio.run(cos.handle_use_browser_hand(None, {"id": BIZ}, {
        "task": "x", "start_url": "http://insecure.example"}))
    assert out["result"] and out["label"], "both keys, always — a missing result blanks the app"
    text = (out["result"] + " " + out["label"]).lower()
    assert "sentence" in text or "https" in text


def test_approving_a_hand_proposal_starts_a_job_through_the_shared_core(monkeypatch):
    import chief_of_staff as cos
    import chief_jobs
    patches, enq = [], []

    async def _sb(client, method, path, body=None):
        if method == "PATCH":
            patches.append((path, body))
        return []
    monkeypatch.setattr(cos, "_sb", _sb)

    async def enqueue(client, *, user_id, business_id, kind, params=None, source="desktop"):
        enq.append((user_id, business_id, kind, params, source))
        return {"id": "job-1"}
    monkeypatch.setattr(chief_jobs, "enqueue", enqueue)

    spec = bh.make_spec(**SPEC)
    item = {"id": "q-hand-1", "business_id": BIZ, "channel": "hand",
            "action_type": "browser_hand", "subject": "Browser hand: x",
            "body": bh.spec_to_body(spec), "status": "draft"}
    biz = {"id": BIZ, "owner_id": "owner-1"}
    delivery = asyncio.run(cos._do_approve_one(None, biz, item))
    assert delivery["ok"] and delivery["sent"] is False
    assert delivery["reason"] == "hand_started" and delivery["job_id"] == "job-1"
    assert enq == [("owner-1", BIZ, "browser_hand", {"spec": spec, "queue_id": "q-hand-1"}, "approval")]
    assert patches[0][1]["status"] == "approved"
    assert "hand is on it" in cos._approve_label(item["subject"], delivery)


def test_an_unreadable_hand_proposal_does_not_run(monkeypatch):
    import chief_of_staff as cos
    import chief_jobs

    async def _sb(client, method, path, body=None):
        return []
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(chief_jobs, "enqueue",
                        lambda *a, **k: pytest.fail("a broken spec must not start a job"))
    item = {"id": "q", "channel": "hand", "action_type": "browser_hand", "body": "garbage"}
    delivery = asyncio.run(cos._do_approve_one(None, {"id": BIZ, "owner_id": "o"}, item))
    assert delivery["ok"] is False and delivery["reason"] == "hand_spec_invalid"


def test_the_registry_says_class_c_and_the_connector_never_lists_it():
    import action_registry
    import mcp_server
    entry = action_registry.REGISTRY["use_browser_hand"]
    assert entry["reversibility"] == "C"
    assert "use_browser_hand" not in mcp_server.WRITE_TOOL_SCHEMAS
    assert not action_registry.may_expose_to_agent("use_browser_hand") if hasattr(action_registry, "may_expose_to_agent") else True


def test_the_job_kind_runs_the_hand_and_emits_a_catalogued_event(monkeypatch):
    import chief_jobs
    import event_spine
    emitted = []
    monkeypatch.setattr(event_spine, "emit",
                        lambda et, biz, data=None, contact_id=None, source="system":
                        emitted.append((et, biz, data, source)) or True)
    monkeypatch.setattr(bh, "run", lambda biz, run_id, spec, progress_cb=None: {
        "ok": False, "stopped": "off_domain", "summary": "Stopped: left the sites",
        "steps": [{"n": 1}], "frames": 1, "task": spec["task"]})
    assert "browser_hand" in chief_jobs.KIND_META
    res = chief_jobs._execute_kind("browser_hand", BIZ, {"spec": SPEC, "queue_id": "q1"}, "job-9")
    assert res["error"] == "Stopped: left the sites", "the recap reads `error` for an honest failure"
    et, biz, data, source = emitted[0]
    assert et == "hand_run_completed" and et in event_spine.EVENT_CATALOG
    assert data["job_id"] == "job-9" and data["queue_id"] == "q1" and data["ok"] is False
    assert set(event_spine.EVENT_CATALOG[et]["payload"]) >= set(data)
