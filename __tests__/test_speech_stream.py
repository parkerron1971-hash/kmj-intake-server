import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import speech_stream as speech
import whisper_proxy as tts

class Socket:
    def __init__(self, messages=()):
        self.inputs = asyncio.Queue()
        for m in messages: self.inputs.put_nowait(json.dumps(m))
        self.audio = []
        self.events = []
        self.accept = AsyncMock()
        self.close = AsyncMock()
    async def receive_text(self): return await self.inputs.get()
    async def send_bytes(self, data): self.audio.append(data)
    async def send_json(self, event): self.events.append(event)

class Provider:
    def __init__(self): self.inputs=[]; self.output=asyncio.Queue()
    async def send(self, raw):
        msg=json.loads(raw); self.inputs.append(msg)
        if msg['text'] and msg.get('flush'):
            await self.output.put(json.dumps({'audio':base64.b64encode(b'\x00\x01'*64).decode()}))
        elif not msg['text']: await self.output.put(json.dumps({'isFinal':True}))
    async def close(self): pass
    def __aiter__(self): return self
    async def __anext__(self): return await self.output.get()

@pytest.mark.parametrize('msg', [{}, {'type':'hello','token':'x','business_id':'x','voice':'el:../secret'},
    {'type':'hello','token':'','business_id':'x','voice':'el:voice'}])
def test_invalid_hello_never_selects_a_provider(msg):
    with pytest.raises(ValueError): speech.parse_hello(json.dumps(msg))

def test_audio_flows_before_finish_and_before_usage_logging(monkeypatch):
    async def run():
        logged=[]
        monkeypatch.setattr(tts,'ELEVENLABS_MONTHLY_CHARS_PER_BIZ',10000)
        monkeypatch.setattr(tts,'_EL_CHARS_CACHE',{'biz':(0,tts._month_bounds()[0],0)})
        async def log(**data): logged.append(data)
        monkeypatch.setattr(tts,'log_api_usage',log)
        ws=Socket([{'type':'text','text':"I'll check that for you."}]); up=Provider()
        task=asyncio.create_task(speech.relay(ws,up,'biz','owner'))
        for _ in range(15): await asyncio.sleep(0)
        assert ws.audio and not logged and not task.done()
        await ws.inputs.put(json.dumps({'type':'text','text':'Here is the answer.'}))
        await ws.inputs.put(json.dumps({'type':'finish'}))
        await asyncio.wait_for(task,1)
        assert len(ws.audio)==2 and ws.events[-1]['type']=='done'
        assert len(logged)==1 and logged[0]['input_tokens']==43
        assert all(m.get('flush') is True for m in up.inputs if m['text'])
        assert up.inputs[-1] == {'text': ''}  # finish drains the provider buffer
    asyncio.run(run())

def test_connection_requires_verified_business_owner(monkeypatch):
    async def run():
        monkeypatch.setattr(tts,'_elevenlabs_key',lambda:'test')
        monkeypatch.setattr(speech.rate_limit,'allow',lambda *a:True)
        monkeypatch.setattr(speech.rate_limit,'client_ip',lambda ws:'test')
        monkeypatch.setattr(speech,'_verify_token',lambda token:SimpleNamespace(id='intruder'))
        monkeypatch.setattr(tts,'_owns_business',lambda *a:False)
        connected=[]
        monkeypatch.setattr(speech.websockets,'connect',lambda *a,**k:connected.append(1))
        ws=Socket([{'type':'hello','token':'jwt','business_id':'biz','voice':'el:voice'}])
        await speech.speech_stream(ws)
        assert not connected and ws.events[-1]['type']=='error'
    asyncio.run(run())

def test_quota_cannot_be_crossed_by_a_large_frame(monkeypatch):
    async def run():
        monkeypatch.setattr(tts,'ELEVENLABS_MONTHLY_CHARS_PER_BIZ',10)
        monkeypatch.setattr(tts,'_EL_CHARS_CACHE',{'biz':(0,tts._month_bounds()[0],9)})
        monkeypatch.setattr(tts,'log_api_usage',AsyncMock())
        up=Provider(); ws=Socket([{'type':'text','text':'too much'}])
        with pytest.raises(ValueError): await speech.relay(ws,up,'biz','owner')
        assert not up.inputs and not ws.audio
    asyncio.run(run())

def test_disconnect_cancels_provider_reader_and_still_meters(monkeypatch):
    async def run():
        monkeypatch.setattr(tts,'ELEVENLABS_MONTHLY_CHARS_PER_BIZ',0)
        logged=AsyncMock(); monkeypatch.setattr(tts,'log_api_usage',logged)
        ws=Socket([{'type':'text','text':'Hello there.'}]); up=Provider()
        task=asyncio.create_task(speech.relay(ws,up,'biz','owner'))
        for _ in range(15): await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        logged.assert_awaited_once()
    asyncio.run(run())


def test_http_audio_does_not_wait_for_usage_logging(monkeypatch):
    async def run():
        calls=[]
        class Audio:
            status_code=200
            async def aiter_bytes(self,chunk_size=4096): yield b'pcm-audio'
            async def aclose(self): pass
        class Client:
            def build_request(self,*a,**k): return None
            async def send(self,*a,**k): return Audio()
        monkeypatch.setattr(tts,'_tts_http',lambda provider:Client())
        monkeypatch.setattr(tts,'_phrase_get',lambda key:None)
        async def log(**data): calls.append(data)
        monkeypatch.setattr(tts,'log_api_usage',log)
        response=await tts._elevenlabs_speak('Hello there.','voice','key',fmt='pcm')
        assert calls==[]
        assert await anext(response.body_iterator)==b'pcm-audio'
        assert calls==[]
        with pytest.raises(StopAsyncIteration): await anext(response.body_iterator)
        assert len(calls)==1
    asyncio.run(run())


def test_alignment_times_stay_cumulative_and_bounded():
    raw={'normalizedAlignment': {'chars':['A','b'], 'charStartTimesMs':[1254,1300], 'charDurationsMs':[46,60]}}
    event=speech.alignment_event(raw,1246.7)
    assert event['time_base']=='stream'
    assert event['char_start_times_ms']==[1254,1300]
    assert event['audio_offset_ms']==1246.7
    assert speech.alignment_event({'alignment':{'chars':['x'],'char_start_times_ms':[0],'char_durations_ms':[40]}},0)
    for invalid in [float('nan'), float('inf'), -1, True, 600001]:
        raw['normalizedAlignment']['charStartTimesMs']=[invalid,1300]
        assert speech.alignment_event(raw,0) is None
    assert speech.alignment_event({'alignment':{'chars':['x'],'charStartTimesMs':[],'charDurationsMs':[20]}},0) is None


def test_alignment_precedes_audio_and_malformed_timing_never_blocks_speech(monkeypatch):
    async def run():
        monkeypatch.setattr(tts,'ELEVENLABS_MONTHLY_CHARS_PER_BIZ',0)
        monkeypatch.setattr(tts,'log_api_usage',AsyncMock())
        class AlignedProvider(Provider):
            async def send(self,raw):
                self.inputs.append(json.loads(raw))
                if json.loads(raw)['text']:
                    for start in [0, 25]:
                        await self.output.put(json.dumps({'audio':base64.b64encode(b'\x00\x01'*600).decode(),
                            'normalizedAlignment':{'chars':['x'],'charStartTimesMs':[start],'charDurationsMs':[20]}}))
                    await self.output.put(json.dumps({'audio':base64.b64encode(b'\x00\x01').decode(),'alignment':{'bad':True}}))
                else:
                    await self.output.put(json.dumps({'is_final':True}))
        ws=Socket([{'type':'text','text':'Test.'},{'type':'finish'}]);up=AlignedProvider();order=[]
        async def event(e): order.append(('event',e))
        async def audio(b): order.append(('audio',len(b)))
        ws.send_json=event;ws.send_bytes=audio
        await asyncio.wait_for(speech.relay(ws,up,'biz','owner'),1)
        assert [item[0] for item in order]==['event','audio','event','audio','audio','event']
        assert order[2][1]['audio_offset_ms']==25
        assert order[2][1]['char_start_times_ms']==[25]
        assert order[-1][1]['type']=='done'
    asyncio.run(run())
