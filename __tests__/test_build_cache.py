"""THE CACHE (2026-10-07, the build-cost plan, step 1).

Kevin: "is there a way to ... maintain the quality with decreasing the
cost?" A build re-sent the same system prompt, blueprint, real data and
page on every builder call at full price. Pins: the repeating parts go
first and carry cache breakpoints, the call's own task goes last; the
shared parts are byte-identical across the surgical repair, the section
repair and the owner's rework so one cache write serves them all; every
builder call shares one system prompt; the spend receipt and the usage
row price cached tokens at their real (lower) rate; the eyes and the tool
loop cache what repeats; and no request ever exceeds the API's four
breakpoints.
"""
from types import SimpleNamespace

import builder_loop
import builder_v2 as v2

SPEC = "0. CONCEPT\nINTENSITY: plain\n1. OVERVIEW\nA calm page for a coach."
DATA = "BUSINESS: Vertical Test Coach — type: coach"
DOC = ('<!DOCTYPE html><html><head><title>t</title></head><body>'
       '<section id="top"><h1>Lead</h1></section><section id="prices"><h2>Ways in</h2></section>'
       '</body></html>')


def _breakpoints(system, messages):
    n = sum(1 for b in (system if isinstance(system, list) else []) if b.get("cache_control"))
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            n += sum(1 for b in c if isinstance(b, dict) and b.get("cache_control"))
    return n


# ─── the prompt splits into cached parts and one fresh task ───────────

def test_a_prompt_with_breaks_becomes_cached_blocks_and_a_fresh_task():
    blocks = v2._user_blocks(v2.CACHE_BREAK.join(["A" * 50, "B" * 50, "the task"]))
    assert [b["text"] for b in blocks] == ["A" * 50, "B" * 50, "the task"]
    assert [bool(b.get("cache_control")) for b in blocks] == [True, True, False]
    plain = v2._user_blocks("one plain prompt")
    assert plain == [{"type": "text", "text": "one plain prompt"}]


def test_never_more_than_three_breakpoints_in_the_message():
    blocks = v2._user_blocks(v2.CACHE_BREAK.join(["p1", "p2", "p3", "p4", "p5", "task"]))
    assert sum(1 for b in blocks if b.get("cache_control")) == 3
    assert blocks[-1]["text"] == "task" and "p1" in blocks[0]["text"] and "p3" in blocks[0]["text"]


def test_the_task_comes_last_so_the_shared_parts_can_be_cached():
    repair = v2.build_user_prompt(SPEC, DATA, violations=["number '400' untraced"], prior_doc=DOC)
    section = v2.build_section_prompt(SPEC, DATA, DOC, "prices", ["make it sing"])
    r, s = v2._user_blocks(repair), v2._user_blocks(section)
    # the blueprint and data, then the page: byte-identical in both, so the
    # surgical repair and every section repair of the same draft share them
    assert r[0]["text"] == s[0]["text"] == v2.stable_part(SPEC, DATA)
    assert r[1]["text"] == s[1]["text"] == v2.page_part(DOC)
    assert "SURGICAL REPAIR" in r[-1]["text"] and "number '400' untraced" in r[-1]["text"]
    assert "SECTION REPAIR:" in s[-1]["text"] and v2.SECTION_PREAMBLE in s[-1]["text"]
    assert "SURGICAL REPAIR" not in r[0]["text"] + r[1]["text"]


def test_every_builder_call_shares_one_system_prompt():
    src = open(v2.__file__, encoding="utf-8").read()
    assert "_SECTION_SYSTEM.replace" not in src, "a section call must not change the system prompt"
    assert src.count("_call(_SYSTEM,") >= 4


# ─── the call sends the blocks and prices what was cached ─────────────

class _Usage(SimpleNamespace):
    pass


class _Fake:
    def __init__(self, usage):
        self.seen, outer = [], self

        class _M:
            def stream(_s, **kw):
                outer.seen.append(kw)

                class _C:
                    text_stream = iter(["<html></html>"])

                    def __enter__(self_):
                        return self_

                    def __exit__(self_, *a):
                        return False

                    def get_final_message(self_):
                        return SimpleNamespace(content=[SimpleNamespace(type="text", text="<html></html>")],
                                               stop_reason="end_turn", usage=usage)
                return _C()
        self.messages = _M()


def _wire_call(monkeypatch, usage):
    fake = _Fake(usage)
    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **k: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import model_ladder
    monkeypatch.setattr(model_ladder, "call_with_ladder",
                        lambda fn, model, task, business_id, max_tokens: (fn(model, max_tokens, 60.0), model))
    rows = []
    import api_usage_logger
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", lambda **kw: rows.append(kw))
    return fake, rows


def test_the_call_sends_a_cached_system_and_cached_parts(monkeypatch):
    fake, rows = _wire_call(monkeypatch, _Usage(input_tokens=900, output_tokens=2000,
                                                cache_read_input_tokens=24000,
                                                cache_creation_input_tokens=0))
    spend = v2.new_spend()
    v2._call(v2._SYSTEM, v2.build_section_prompt(SPEC, DATA, DOC, "prices", ["x"]), "biz", spend=spend)
    kw = fake.seen[0]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = kw["messages"][0]["content"]
    assert [bool(b.get("cache_control")) for b in content] == [True, True, False]
    assert _breakpoints(kw["system"], kw["messages"]) <= 4
    # the receipt and the ledger both count the cached read at its rate
    assert spend["cache_read_tokens"] == 24000 and spend["input_tokens"] == 900
    assert rows[0]["cache_read_tokens"] == 24000 and rows[0]["input_tokens"] == 900


def test_a_cached_read_is_priced_at_a_tenth(monkeypatch):
    cold, warm = v2.new_spend(), v2.new_spend()
    v2._record_spend(cold, "claude-opus-5-5", _Usage(input_tokens=25000, output_tokens=2000))
    v2._record_spend(warm, "claude-opus-5-5", _Usage(input_tokens=1000, output_tokens=2000,
                                                     cache_read_input_tokens=24000))
    saved = cold["cost_cents"] - warm["cost_cents"]
    # 24,000 tokens at $4/M is 9.6c fresh and 0.96c cached
    assert 8.5 < saved < 8.8, saved


def test_a_continuation_reuses_the_cached_opening(monkeypatch):
    fake = _Fake(_Usage(input_tokens=1, output_tokens=1))
    script = [("<html><body>half", "max_tokens"), (" rest</body></html>", "end_turn")]

    class _M:
        def stream(_s, **kw):
            fake.seen.append(kw)
            text, stop = script.pop(0)

            class _C:
                text_stream = iter([text])

                def __enter__(self_):
                    return self_

                def __exit__(self_, *a):
                    return False

                def get_final_message(self_):
                    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                                           stop_reason=stop, usage=_Usage(input_tokens=1, output_tokens=1))
            return _C()
    fake.messages = _M()
    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **k: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import model_ladder
    monkeypatch.setattr(model_ladder, "call_with_ladder",
                        lambda fn, model, task, business_id, max_tokens: (fn(model, max_tokens, 60.0), model))
    v2._call(v2._SYSTEM, v2.CACHE_BREAK.join(["shared " * 20, "task"]), "biz", spend=v2.new_spend())
    first, second = fake.seen
    assert second["messages"][0]["content"] == first["messages"][0]["content"]
    assert second["system"] == first["system"]


# ─── the eyes and the tool loop cache what repeats ────────────────────

def test_the_eyes_cache_their_system_and_the_settled_blueprint(monkeypatch):
    seen = {}

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                seen.update(kw)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"verdict":"ship","violations":[]}')],
                                       stop_reason="end_turn", usage=_Usage(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(v2, "_screenshot_walk", lambda doc: [("1440px top", b"jpeg")])
    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **k: _Client())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import model_ladder
    monkeypatch.setattr(model_ladder, "call_with_ladder",
                        lambda fn, model, task, business_id, max_tokens: (fn(model, max_tokens, 60.0), model))
    assert v2.inspect_with_eyes(DOC, SPEC, "biz") is not None
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = seen["messages"][0]["content"]
    cached = [i for i, b in enumerate(content) if b.get("cache_control")]
    assert cached == [0], "the blueprint block (the page has no layout line) closes the cached part"
    assert "SECTIONS ON THE PAGE" in content[1]["text"], "the outline follows the breakpoint"
    assert any(b.get("type") == "image" for b in content[cached[-1] + 1:])


def test_the_loop_caches_its_opening_and_its_newest_turn():
    turns = [{"role": "user", "content": "the whole brief"},
             {"role": "assistant", "content": [SimpleNamespace(type="tool_use", id="t1")]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "seen"}]}]
    sent = builder_loop._cached_turns(turns)
    assert sent[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert sent[2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert turns[2]["content"][-1].get("cache_control") is None, "the stored turns are unchanged"
    system = v2._system_blocks("sys")
    assert _breakpoints(system, sent) == 3
