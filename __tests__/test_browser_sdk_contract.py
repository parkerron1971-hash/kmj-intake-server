"""The pinned SDK must preserve newer browser-toolset wire fields."""
import json
import httpx
from anthropic import Anthropic
from browser_controller import tool_config


def test_pinned_sdk_preserves_toolset_name_and_browser_state():
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'msg_fixture','type':'message','role':'assistant',
            'model':'fixture-model','stop_reason':'tool_use','stop_sequence':None,
            'content':[{'type':'tool_use','id':'tool_fixture','name':'list_tabs','toolset_name':'browser','input':{}}],
            'usage':{'input_tokens':1,'output_tokens':1}})
    client=Anthropic(api_key='fixture-only',http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    try:
        message=client.messages.create(model='fixture-model',max_tokens=10,tools=[tool_config()],
            messages=[{'role':'user','content':'Start'}])
        block=message.model_dump(exclude_none=True)['content'][0]
        assert block['toolset_name']=='browser'
        result={'type':'tool_result','tool_use_id':'tool_fixture','toolset_name':'browser',
            'content':[{'type':'browser_state','tabs':[{'tab_id':'tab-1','url':'about:blank','title':'','active':True}]}]}
        client.messages.create(model='fixture-model',max_tokens=10,tools=[tool_config()],messages=[
            {'role':'user','content':'Start'},{'role':'assistant','content':[block]},
            {'role':'user','content':[result]}])
        assert requests[0]['tools'][0]==tool_config()
        assert requests[1]['messages'][-1]['content'][0]==result
    finally:
        client.close()
