"""Independent review regressions for complete scheduling evidence reads."""
import asyncio
from unittest.mock import AsyncMock

import pytest
import chief_availability as availability


def test_short_pages_continue_until_explicit_empty_page(monkeypatch):
    # A server-side cap can be below the requested PAGE_SIZE. len(page) < limit
    # does not prove all bookings were fetched.
    database = AsyncMock(side_effect=[[{'id': 'a'}], [{'id': 'b'}], []])
    monkeypatch.setattr(availability, '_sb', database)
    rows = asyncio.run(availability._pages(None, '/module_entries?business_id=eq.fixture'))
    assert rows == [{'id': 'a'}, {'id': 'b'}]
    assert [call.args[2].split('&offset=')[1] for call in database.call_args_list] == ['0', '1', '2']
    assert all(call.args[1] == 'GET' for call in database.call_args_list)
    assert all('business_id=eq.fixture' in call.args[2] for call in database.call_args_list)


@pytest.mark.parametrize('pages', [
    [[{'id': 'a'}], [{'id': 'a'}]],
    [[{'id': 'a'}], [{'id': 'b'}], [{'id': 'c'}]],
    [[{'id': 'a'}], None],
    [[{'id': 'a'}], [{'id': None}]],
    [[{'id': 'a'}], ['malformed row']],
])
def test_partial_duplicate_overcap_or_malformed_pages_fail_closed(monkeypatch, pages):
    database = AsyncMock(side_effect=pages)
    monkeypatch.setattr(availability, '_sb', database)
    with pytest.raises(availability.Unavailable):
        asyncio.run(availability._pages(None, '/module_entries?business_id=eq.fixture', cap=2))
