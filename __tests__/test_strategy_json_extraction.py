"""_extract_json — the parser that decides whether 30 seconds of research
reaches the card or comes back "unreadable".

Found on a live board 8/04: "Look into this" searched, then failed. The
old parser was find('{') + rfind('}'), which only works when the object is
the LAST thing in the text — and neither shape a web-searching model
actually produces satisfies that.
"""

from strategy_router import _extract_json


GOOD = (
    '{"summary": "s", "findings": ["a"], "watch_outs": [], '
    '"verdict": "worth trying", '
    '"sources": [{"title": "T", "url": "https://x.test/a"}]}'
)


RESEARCH = ("summary", "findings", "verdict")


def test_plain_object():
    assert _extract_json(GOOD)["verdict"] == "worth trying"


def test_fenced_block():
    assert _extract_json("```json\n" + GOOD + "\n```")["summary"] == "s"


def test_prose_before_the_object():
    assert _extract_json("Here is what I found.\n\n" + GOOD)["findings"] == ["a"]


def test_trailing_line_with_a_brace_does_not_defeat_it():
    """rfind('}') walked past the object whenever the model signed off with
    anything brace-ish after it."""
    out = _extract_json(GOOD + '\n\nSources checked: {see above}')
    assert out is not None and out["verdict"] == "worth trying"


def test_truncated_object_fails_cleanly():
    """Cut mid-object at max_tokens: the last '}' in the string closes a
    SOURCE, so the old parser handed json.loads a fragment. It must not
    return half a set of findings dressed up as research."""
    cut = (
        '{"summary": "s", "findings": ["a", "b"], "watch_outs": [], '
        '"sources": [{"title": "T", "url": "https://x.test/a"}, '
        '{"title": "U", "url": "https://x.test/'
    )
    assert _extract_json(cut, require=RESEARCH) is None


def test_braces_inside_strings_are_not_structure():
    out = _extract_json('{"summary": "costs {approx} $40", "findings": []}')
    assert out["summary"] == "costs {approx} $40"


def test_escaped_quote_inside_a_string():
    out = _extract_json('{"summary": "they call it \\"the wall\\"", "findings": []}')
    assert out["summary"] == 'they call it "the wall"'


def test_an_unbalanced_false_start_is_skipped():
    """A stray brace ahead of the object must not poison the parse."""
    out = _extract_json('{ not json at all\n\n' + GOOD)
    assert out is not None and out["verdict"] == "worth trying"


def test_a_balanced_object_that_is_not_the_payload_is_skipped():
    """The scan must not stop at the first thing that happens to parse —
    it stops at the first thing that looks like the answer."""
    out = _extract_json('{"note": "not the payload"}\n\n' + GOOD, require=RESEARCH)
    assert out is not None and out["verdict"] == "worth trying"


def test_empty_and_junk():
    assert _extract_json("") is None
    assert _extract_json("no object here") is None
    assert _extract_json("[1, 2, 3]") is None


def test_nested_object_is_never_mistaken_for_the_payload():
    """The failure mode `require` exists for: a source object parses
    perfectly and would otherwise be returned as the research."""
    assert _extract_json(
        '{"sources": [{"title": "T", "url": "https://x.test/a"}',
        require=RESEARCH) is None


def test_other_endpoints_name_their_own_payload():
    assert _extract_json('{"suggestions": []}', require=("suggestions",)) == {"suggestions": []}
    assert _extract_json('{"nope": 1}', require=("suggestions",)) is None
