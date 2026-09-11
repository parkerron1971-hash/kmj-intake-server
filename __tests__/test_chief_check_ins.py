"""The reported voice check-ins acknowledge receipt without inventing audio access."""
import asyncio
from unittest.mock import AsyncMock

import pytest
import chief_truth as truth


@pytest.mark.parametrize('message', [
    'Can you hear what I just said?', 'Hello, can you hear me?',
    'Hey Chief, are you there?', 'Chief', 'Hello!', 'Can you read this?',
])
def test_check_ins_survive_unavailable_reviewer(message):
    reviewer = AsyncMock(side_effect=RuntimeError('offline'))
    reply, meta = asyncio.run(truth.finalize_reply(
        None, 'Yes, I heard everything and sent your email.', ctx={}, view_detail={},
        taken=[], message=message, business_id='fixture', reviewer=reviewer))
    assert reply == "I'm here. I received your message. What would you like help with?"
    assert meta['status'] == 'acknowledged'
    reviewer.assert_not_awaited()


@pytest.mark.parametrize('message', [
    'Can you hear me and send Ada an email?',
    'Hello, how many invoices are overdue?', 'Can you hear the recording?',
    'Hello, can you hear me? Did you send the email?', 'What did I just say?',
])
def test_substantive_questions_still_require_review(message):
    assert truth.conversation_check_reply(message) is None
    reviewer = AsyncMock(return_value='')
    reply, meta = asyncio.run(truth.finalize_reply(
        None, 'All your invoices are paid.', ctx={}, view_detail={}, taken=[],
        message=message, business_id='fixture', reviewer=reviewer))
    assert reply == truth.UNVERIFIED_REPLY
    assert meta['status'] == 'withheld'
    reviewer.assert_awaited_once()


def test_check_in_does_not_hide_a_failed_action():
    reply, meta = asyncio.run(truth.finalize_reply(
        None, 'Hello!', ctx={}, view_detail={},
        taken=[{'type': 'send_sms', 'failed': True, 'result': 'Failed: offline', 'label': 'Message failed'}],
        message='Can you hear me?', business_id='fixture', reviewer=AsyncMock()))
    assert meta['status'] == 'receipts'
    assert 'received your message' not in reply
