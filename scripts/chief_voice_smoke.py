"""Synthetic speech benchmark; never reads business records or changes settings.
Uses the same selected voice for HTTP Turbo and WebSocket Flash. Writes WAVs.
"""
import asyncio, base64, json, os, pathlib, sys, time, wave
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
import httpx, websockets
from urllib.parse import urlencode
VOICE=sys.argv[1]  # selected ElevenLabs voice id; never an API key
TEXT="I'll look through that with you. Let's start with the part that matters most."
OUT=pathlib.Path(__file__).resolve().parents[2]/'voice-bench'

def save(name,audio):
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT/(name+'.wav')),'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(audio)

async def main():
    key=os.environ['ELEVENLABS_API_KEY']
    for model in ['eleven_turbo_v2_5','eleven_flash_v2_5']:
        async with httpx.AsyncClient(timeout=25) as client:
            start=time.perf_counter(); first=None; audio=bytearray()
            async with client.stream('POST',f'https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/stream?output_format=pcm_24000',
                headers={'xi-api-key':key},json={'text':TEXT,'model_id':model}) as res:
                res.raise_for_status()
                async for chunk in res.aiter_bytes():
                    if first is None: first=time.perf_counter()
                    audio.extend(chunk)
            save(model,audio)
            print(json.dumps({'transport':'http','model':model,'first_audio_ms':round((first-start)*1000),'audio_seconds':round(len(audio)/48000,2)}))
    url=f'wss://api.elevenlabs.io/v1/text-to-speech/{VOICE}/stream-input?'+urlencode({'model_id':'eleven_flash_v2_5','output_format':'pcm_24000','auto_mode':'true'})
    async with websockets.connect(url,additional_headers={'xi-api-key':key},open_timeout=10) as ws:
        await ws.send(json.dumps({'text':' '}))
        start=time.perf_counter(); first=None; audio=bytearray(); ended=False
        await ws.send(json.dumps({'text':"I'll look through that with you. ",'flush':True}))
        async for raw in ws:
            msg=json.loads(raw)
            if msg.get('error'): raise RuntimeError('Provider rejected the fixture')
            if msg.get('audio'):
                if first is None:
                    first=time.perf_counter()
                    # Receiving audio before the rest of the text is the contract.
                    await ws.send(json.dumps({'text':"Let's start with the part that matters most. ",'flush':True}))
                    await ws.send(json.dumps({'text':''})); ended=True
                audio.extend(base64.b64decode(msg['audio']))
            if msg.get('isFinal'): break
        assert ended and len(audio)>4800
        save('websocket_flash',audio)
        print(json.dumps({'transport':'websocket','model':'eleven_flash_v2_5','first_audio_ms':round((first-start)*1000),'audio_before_remaining_text':True,'audio_seconds':round(len(audio)/48000,2)}))
asyncio.run(main())
