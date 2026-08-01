# __tests__/test_chief_text_blocks.py
#
# The 8/01 "Ignore that last bit" bug.
#
# Chief answered a "walk me through my active work" question by trying to
# WEB SEARCH the practitioner's own projects, and the practitioner saw
# every one of the model's between-search course-corrections glued
# together without so much as a space:
#
#   "...so I'm not guessing.Ignore that last bit — let me get you the
#    real picture instead of generic web results."
#
# Root cause: "".join() over every text block in the response. With
# server tools the content array is [text][tool_use][tool_result][text],
# and each text block is a separate thought — not continuous prose.

import chief_of_staff as cos


def _text(t):
    return {"type": "text", "text": t}


def test_single_block_passes_through():
    assert cos._text_from_content([_text("  Here's where things stand.  ")]) \
        == "Here's where things stand."


def test_multi_block_keeps_only_the_final_answer():
    """The exact shape of the reported bug."""
    content = [
        _text("Projects — 2 in the tracker. Let me pull the actual titles "
              "so I'm not guessing."),
        {"type": "server_tool_use", "name": "web_search"},
        {"type": "web_search_tool_result", "content": []},
        _text("Ignore that last bit — let me get you the real picture "
              "instead of generic web results."),
        {"type": "server_tool_use", "name": "web_search"},
        _text("Here's the full picture: 2 projects, both active."),
    ]
    out = cos._text_from_content(content)
    assert out == "Here's the full picture: 2 projects, both active."
    assert "Ignore that last bit" not in out
    # The run-together signature must be impossible now.
    assert "guessing.Ignore" not in out


def test_empty_and_whitespace_blocks_are_ignored():
    assert cos._text_from_content([]) == ""
    assert cos._text_from_content([_text("   "), _text("")]) == ""
    assert cos._text_from_content([_text("  "), _text("real answer")]) == "real answer"


def test_non_text_blocks_never_leak():
    content = [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "x"}},
        {"type": "web_search_tool_result", "content": [{"title": "SEO spam"}]},
        _text("The answer."),
    ]
    out = cos._text_from_content(content)
    assert out == "The answer."
    assert "SEO spam" not in out and "web_search" not in out


def test_malformed_content_does_not_raise():
    assert cos._text_from_content(None) == ""
    assert cos._text_from_content(["not a dict", 42, None]) == ""
    assert cos._text_from_content([{"type": "text"}]) == ""   # missing 'text' key


def test_prompt_forbids_searching_own_business_data_and_promising_sequels():
    block = cos._build_web_search_block()
    # The search that started it all.
    assert "projects" in block.lower()
    assert "cannot see their data" in block
    # The promise it can never keep.
    assert "ONE REPLY, NO SEQUELS" in block
    for phrase in ("details incoming", "while that loads", "let me pull that"):
        assert phrase in block.lower()
    assert "ignore that last bit" in block.lower()
