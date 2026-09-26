"""A web search is a step the owner can look into: the query while it runs,
the pages it found when it lands (chief_search_steps)."""
import json

import chief_search_steps as css


def steps():
    sent = []
    return css.SearchSteps(sent.append), sent


def result_block(use_id, n=10, extra=()):
    content = [{'type': 'web_search_result', 'url': f'https://www.example{i}.test/page', 'title': f'  Page   {i} '}
               for i in range(n)]
    return {'type': 'web_search_tool_result', 'tool_use_id': use_id, 'content': [*extra, *content]}


def test_query_arrives_in_pieces_then_results_land_on_the_same_step():
    s, sent = steps()
    s.block_start(1, {'type': 'server_tool_use', 'id': 'srv_1', 'name': 'web_search', 'input': {}})
    s.delta(1, {'type': 'input_json_delta', 'partial_json': '{"query": "claude api'})
    s.delta(1, {'type': 'input_json_delta', 'partial_json': ' credits"}'})
    s.block_stop(1)
    s.block_start(2, result_block('srv_1', extra=[
        {'type': 'web_search_result', 'url': 'javascript:alert(1)', 'title': 'bad'},
        {'type': 'web_search_result', 'url': 'ftp://files.test/x', 'title': 'bad'}]))
    assert [x['state'] for x in sent] == ['running', 'running', 'done']
    assert len({x['id'] for x in sent}) == 1 and all(x['action'] == 'web_search' for x in sent)
    assert sent[0]['label'] == 'Searching the web'
    assert sent[1]['label'] == 'Searching the web for "claude api credits"'
    done = sent[2]
    assert done['label'] == 'Searched "claude api credits" · 8 pages' and done['ms'] >= 0
    results = done['search']['results']
    assert len(results) == css.MAX_RESULTS
    assert results[0] == {'title': 'Page 0', 'url': 'https://www.example0.test/page', 'host': 'example0.test'}
    assert all(r['url'].startswith('https://') for r in results)


def test_a_query_given_up_front_and_a_failed_search():
    s, sent = steps()
    s.block_start(0, {'type': 'server_tool_use', 'id': 'srv_2', 'name': 'web_search', 'input': {'query': 'plumbers  in\nMuskegon'}})
    s.block_stop(0)
    s.block_start(1, {'type': 'web_search_tool_result', 'tool_use_id': 'srv_2',
                      'content': {'type': 'web_search_tool_result_error', 'error_code': 'unavailable'}})
    assert [x['state'] for x in sent] == ['running', 'failed']
    assert sent[0]['search'] == {'query': 'plumbers in Muskegon'}
    assert sent[1]['label'] == 'The web search did not finish'


def test_an_interrupted_attempt_never_leaves_a_search_running():
    s, sent = steps()
    s.block_start(0, {'type': 'server_tool_use', 'id': 'srv_3', 'name': 'web_search', 'input': {'query': 'x'}})
    s.close()
    s.close()
    assert [x['state'] for x in sent] == ['running', 'failed']


def test_other_blocks_are_ignored_and_a_broken_listener_never_breaks_the_turn():
    sent = []
    s = css.SearchSteps(sent.append)
    s.block_start(0, {'type': 'server_tool_use', 'id': 'srv_4', 'name': 'code_execution', 'input': {}})
    s.block_start(1, {'type': 'text'})
    s.block_start(2, result_block('unknown'))
    s.delta(0, {'type': 'input_json_delta', 'partial_json': '{'})
    s.block_stop(0)
    assert sent == []
    def boom(_):
        raise RuntimeError('listener gone')
    css.SearchSteps(boom).block_start(0, {'type': 'server_tool_use', 'id': 'srv_5', 'name': 'web_search', 'input': {}})


def test_the_chat_stream_carries_the_search_to_the_client():
    import chief_of_staff as cos
    body = {'id': 'ws1', 'action': 'web_search', 'label': 'Searched "x"', 'state': 'done',
            'search': {'query': 'x', 'results': [{'title': 'A', 'url': 'https://a.test', 'host': 'a.test'}]}}
    events = cos._stream_piece_events(cos.STEP_PREFIX + json.dumps(body), cos._ActionTagFilter())
    assert events == [{'type': 'step', **body}]
    sent = []
    token = cos._STREAM_SINK.set(sent.append)
    try:
        cos._emit_stream_step(body)
    finally:
        cos._STREAM_SINK.reset(token)
    assert sent == [cos.STEP_PREFIX + json.dumps(body)]
    cos._emit_stream_step(body)  # Nobody listening: nothing happens.
