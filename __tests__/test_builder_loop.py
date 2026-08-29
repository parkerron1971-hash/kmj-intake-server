"""
test_builder_loop.py — the builder with tools (2026-08-29).

A scripted client plays the model: every messages.stream() call pops the
next reply. No network, no playwright (the toolbox gets a fake
screenshotter), no money.
"""
import os
from unittest import mock

import builder_loop as bl
import builder_v2 as v2


ENDPOINT = "https://api.example/contact/biz-1"
REAL = ("BUSINESS: Studio — type: consultant\n"
        "IMAGES (every one appears on the page, exact urls):\n"
        "- https://x/a.jpg (a braid)\n")


def _doc(extra=""):
    return ("<!DOCTYPE html><html><head><title>Studio</title>"
            '<meta name="description" content="A braiding studio by hand">'
            '<meta property="og:title" content="Studio">'
            '<meta property="og:description" content="A braiding studio">'
            '<meta property="og:image" content="https://x/a.jpg">'
            "<style>body{margin:0}</style></head><body>"
            '<nav><a href="#top">Top</a></nav><main id="top"><h1>Braids worn like '
            'their own kind of magnificent.</h1><img src="https://x/a.jpg" alt="a braid">'
            + extra + "</main>"
            f'<form method="POST" action="{ENDPOINT}"><input name="name">'
            '<input name="email"><button>Send</button></form>'
            "<footer>Studio</footer></body></html>")


class _Usage:
    def __init__(self, i=1000, o=500):
        self.input_tokens, self.output_tokens = i, o


class _Text:
    type = "text"
    def __init__(self, text):
        self.text = text


class _Use:
    type = "tool_use"
    def __init__(self, name, inp, id_):
        self.name, self.input, self.id = name, inp, id_


class _Msg:
    def __init__(self, content, stop):
        self.content, self.stop_reason, self.usage = content, stop, _Usage()


class _Client:
    """Scripted replies; records every request's messages + tool_choice."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        outer = self

        class _Messages:
            def stream(_s, **kw):
                outer.seen.append(kw)
                msg = outer.replies.pop(0)

                class _Ctx:
                    text_stream = iter([])
                    def __enter__(self_): return self_
                    def __exit__(self_, *a): return False
                    def get_final_message(self_): return msg
                return _Ctx()
        self.messages = _Messages()


def _box(monkeypatch):
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: REAL)
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: ENDPOINT)
    return bl.ToolBox({}, "biz-1", REAL, ENDPOINT,
                      screenshots=lambda html: [("1440px top", b"jpegbytes")])


def test_render_tool_returns_laws_and_screenshots_and_remembers_the_draft(monkeypatch):
    box = _box(monkeypatch)
    standin = '<div class="slot-frame"><p class="slot-note">Braids from behind.</p></div>'
    out = box.render(_doc(standin), note="first look")
    text = out[0]["text"]
    assert "RENDER 1" in text and "first look" in text
    assert "VISIBLE STAND-IN" in text                 # the law rides the render
    assert any(b.get("type") == "image" for b in out)  # the eyes ride it too
    assert box.last_render and box.renders == 1
    clean = box.render(_doc())
    assert "No law broken" in clean[0]["text"]


def test_look_only_sees_what_the_real_data_names(monkeypatch):
    box = _box(monkeypatch)
    ok = box.look("https://x/a.jpg")
    assert ok[1]["type"] == "image" and ok[1]["source"]["url"] == "https://x/a.jpg"
    no = box.look("https://elsewhere/anything.jpg")
    assert len(no) == 1 and "not in the real data" in no[0]["text"]


def test_vocabulary_reads_a_language_a_move_and_a_framework(monkeypatch):
    box = _box(monkeypatch)
    assert "LANGUAGE" in box.vocabulary("mural")[0]["text"]
    assert "MOVE THE STAGE LIGHT" in box.vocabulary("THE STAGE LIGHT")[0]["text"]
    assert "FRAMEWORK" in box.vocabulary("story_arc")[0]["text"]
    assert "Nothing called" in box.vocabulary("nope")[0]["text"]


def test_loop_renders_corrects_and_finishes(monkeypatch):
    """Turn 1: the model renders a draft with a stand-in and sees the law.
    Turn 2: it hands in a clean page. Two calls, one render, done."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    box = _box(monkeypatch)
    standin = '<div class="slot-frame"><p class="slot-note">Braids from behind.</p></div>'
    client = _Client([
        _Msg([_Text("Let me see it."), _Use("render", {"html": _doc(standin)}, "t1")], "tool_use"),
        _Msg([_Use("finish", {"html": _doc()}, "t2")], "tool_use"),
    ])
    spend = v2.new_spend()
    out = bl.run_loop("SPEC", {}, "biz-1", spend, toolbox=box, client=client,
                      model="claude-opus-5")
    assert out["html"] and "slot-note" not in out["html"]
    r = out["report"]
    assert r["tool_calls"] == 2 and r["renders"] == 1 and r["forced_finish"] is None
    assert r["tools_used"] == ["render", "finish"]
    # the render's findings went back to the model as a tool_result with an image
    second = client.seen[1]["messages"]
    assert second[-1]["role"] == "user"
    tr = second[-1]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "t1"
    assert "VISIBLE STAND-IN" in tr["content"][0]["text"]
    assert any(c.get("type") == "image" for c in tr["content"])
    assert "THE ROOM" in client.seen[0]["system"] and spend["calls"] == 2


def test_loop_keeps_the_last_render_when_the_purse_or_the_cap_runs_out(monkeypatch):
    """Never nothing: with one tool call allowed, the model renders once,
    is then told to finish, does not — the last rendered draft ships."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("BUILDER_LOOP_MAX_TOOLS", "1")
    box = _box(monkeypatch)
    client = _Client([
        _Msg([_Use("render", {"html": _doc()}, "t1")], "tool_use"),
        _Msg([_Text("I would like another look.")], "end_turn"),   # ignores the forced finish
    ])
    spend = v2.new_spend()
    out = bl.run_loop("SPEC", {}, "biz-1", spend, toolbox=box, client=client,
                      model="claude-opus-5")
    assert out["html"] == v2._parse_doc(_doc())
    assert out["report"]["forced_finish"].startswith("last render kept")
    assert client.seen[1]["tool_choice"] == {"type": "tool", "name": "finish"}


def test_loop_is_off_by_default_and_run_builder_v2_falls_back_to_one_pass(monkeypatch):
    monkeypatch.delenv("BUILDER_V2_LOOP", raising=False)
    assert bl.enabled() is False
    monkeypatch.setenv("BUILDER_V2_LOOP", "on")
    assert bl.enabled() is True
    # loop on but producing nothing → the one-pass author still runs
    monkeypatch.setattr(bl, "run_loop", lambda *a, **k: {"html": None, "report": {"tool_calls": 0}})
    calls = []
    monkeypatch.setattr(v2, "_call", lambda s, u, b, spend=None: (calls.append(u), _doc())[1])
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: REAL)
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: ENDPOINT)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["html"] and len(calls) == 1
    assert any(f["stage"] == "loop" for f in out["report"]["fallbacks"])
