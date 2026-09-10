"""Execution results, not the optimistic first draft, determine the reply."""
import asyncio
from unittest.mock import AsyncMock

import chief_of_staff as chief


def test_failed_email_correction_replaces_optimistic_draft(monkeypatch):
    correction = 'The email could not be sent. Nothing was sent.'
    monkeypatch.setattr(chief, '_call_claude', AsyncMock(return_value=correction))
    result = asyncio.run(chief._compose_post_action_reply(
        None, 'Send Ada the email', "I've sent the email to Ada.",
        [{'type': 'draft_and_send', 'result': 'Failed: provider unavailable',
          'failed': True, 'label': 'Email failed'}], 'fixture'))
    assert result == correction


def test_action_only_correction_cannot_restore_false_success(monkeypatch):
    monkeypatch.setattr(chief, '_call_claude', AsyncMock(
        return_value='[ACTION:{"type":"send_sms"}]'))
    result = asyncio.run(chief._compose_post_action_reply(
        None, 'Send the message', 'Your message has been sent.',
        [{'type': 'send_sms', 'failed': True, 'result': 'Failed: offline',
          'label': 'Message failed'}], 'fixture'))
    assert result != 'Your message has been sent.'
    assert '[ACTION:' not in result
