import ast
from pathlib import Path

import pytest

import chief_headline as headline
from chief_turn_direction import direction_for


# Synthetic reproduction of a plan-to-vision self-correction; no business data.
PIVOT = ("I need to know exactly what is the plan. Well, actually, let's go back to "
         "that vision we were talking about earlier and making the vision and getting "
         "things done with that. Let's try to figure that out.")


def test_latest_direction_is_vision_not_the_abandoned_plan_audit():
    d = direction_for(PIVOT)
    assert d.redirected and d.resume and d.brief_opener
    assert d.focus.startswith("let's go back to that vision")
    assert "what is the plan" not in d.focus
    assert "earlier constraints" not in d.focus  # no fabricated owner words
    assert "recall_conversation" in d.prompt()
    assert "not unrelated constraints" in d.prompt()


@pytest.mark.parametrize('message,focus', [
    ("Review the goals. Actually, let's discuss the vision.", "let's discuss the vision."),
    ("Review goals, actually, I want to discuss pricing.", "I want to discuss pricing."),
    ("Review goals. Scratch that. Let us discuss pricing.", "Let us discuss pricing."),
    ("Review goals. Instead, focus on pricing.", "focus on pricing."),
    ("Send it. Actually, don't send it.", "don't send it."),
    ("Review goals. Actually, let's discuss pricing. Actually, let's return to the vision.",
     "let's return to the vision."),
])
def test_explicit_redirects_highlight_the_last_direction(message, focus):
    assert direction_for(message).focus == focus


@pytest.mark.parametrize('message', [
    'Review this quotation: "Actually, let\'s go back to the vision."',
    "Review this quotation: 'Actually, let us discuss pricing.'",
    'Review this quotation: “Actually, let us discuss pricing.”',
    'Review this code: `Actually, let us discuss pricing.`',
    'Review this note:\n> Actually, let us discuss pricing.',
    'The actual revenue was lower. What happened?',
    'Actually, revenue increased. Explain why.',
    'What invoices were due earlier this year?',
])
def test_quoted_or_descriptive_text_is_not_a_conversation_redirect(message):
    d = direction_for(message)
    assert not d.brief_opener and d.prompt() == ''
    assert d.focus == message


def test_constraints_remain_in_the_original_message():
    message = "Do not send anything. Draft a note. Actually, let's draft an email instead."
    d = direction_for(message)
    assert d.focus == "let's draft an email instead."
    assert "permission requirements in the full request" in d.prompt()
    assert message.startswith('Do not send anything.')


def test_resumed_record_question_does_not_start_a_second_answer():
    assert not headline.eligible("Can we go back to which invoices Maria owes?",
                                 lane='voice', is_greeting=False, is_coach_mode=False)
    assert not headline.eligible(PIVOT, lane='voice', is_greeting=False, is_coach_mode=False)


def test_main_turn_gets_direction_from_original_message_before_generation():
    # Inspect syntax, not an exact prompt snapshot: all normal and retry model
    # calls must share guidance built from the unmodified request.
    source = Path(__file__).resolve().parents[1].joinpath('chief_of_staff.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    turn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'chief_chat')
    guidance = [n for n in ast.walk(turn) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == 'direction_for']
    calls = [n for n in ast.walk(turn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == '_call_claude']
    assert len(guidance) == 1
    assert 'req.message' in ast.unparse(guidance[0])
    assert all(guidance[0].lineno < call.lineno for call in calls)
