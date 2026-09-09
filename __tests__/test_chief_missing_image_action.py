import asyncio
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import chief_of_staff as chief


def test_edit_retry_retains_existing_flyer_id_and_format():
    image_id = str(uuid4())
    history = [
        {'role': 'user', 'content': 'Make a landscape promotion.'},
        {'role': 'assistant', 'content': f'Your flyer. Image ID: {image_id}; size: 1536x1024'},
        {'role': 'user', 'content': 'Add 90-Day Intensive beneath 50% OFF.'},
    ]
    async def model(client, system, messages, **kwargs):
        assert image_id in json.dumps(messages)
        assert '1536x1024' in json.dumps(messages)
        assert '90-Day Intensive' in messages[-1]['content']
        return 'Creating the edit. [ACTION:' + json.dumps({'type': 'generate_image',
            'prompt': 'Add 90-Day Intensive beneath 50% OFF; preserve the rest.',
            'size': '1536x1024', 'reference_ids': [image_id]}) + ']'
    with patch.object(chief, '_call_claude', side_effect=model) as call:
        actions, clean, raw = asyncio.run(chief._retry_missing_actions(
            None, 'system', history, history[-1]['content'], 2000, 'test-model'))
    assert len(actions) == 1
    assert actions[0]['reference_ids'] == [image_id]
    assert actions[0]['size'] == '1536x1024'
    assert call.call_count == 1


@pytest.mark.parametrize('reply', [None, '', "I've queued the edit. It's rendering now."])
def test_failed_retry_never_claims_queued_or_invents_an_approval(reply):
    with patch.object(chief, '_call_claude', new_callable=AsyncMock, return_value=reply) as call:
        actions, clean, raw = asyncio.run(chief._retry_missing_actions(
            None, 'system', [{'role': 'user', 'content': 'Edit the flyer'}], 'Edit the flyer', 2000, 'test-model'))
    assert actions == []
    assert "couldn't start" in clean
    assert 'Nothing was queued' in clean
    assert 'Approvals' not in clean and 'rendering now' not in clean
    call.assert_awaited_once()
