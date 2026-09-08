"""Narration for Video Studio. Cost logging is separate from Chief planning metering.

Quality pass 2026-09-08:
- The narrator is gpt-4o-mini-tts (the same standard voice the rest of the
  system moved to in the voice latency arc) with a per-theme delivery note,
  instead of the flat tts-1 read.
- A scene whose narration runs long is EXTENDED to fit the voice (up to the
  30-second scene cap and the three-minute video cap) instead of failing the
  render with "shorten its narration". A director would pad the shot, not
  throw the take away. The composition the practitioner approved keeps its
  words, order and media; only the scene's seconds grow.
- Each take is transcribed with word timestamps so captions land on the
  spoken phrase rather than being spread evenly across the scene. If the
  timing call fails the captions fall back to the even split; the render
  never fails over caption polish.
"""
import math
import os,json,re,subprocess
import httpx

TTS_MODEL='gpt-4o-mini-tts'
TIMING_MODEL='whisper-1'
DELIVERY={
    'midnight':'confident, modern and crisp — a premium product film',
    'paper':'warm, measured and editorial — a documentary narrator',
    'warm':'friendly, welcoming and unhurried — a neighbour recommending a place they love',
}
BREATH=.8          # seconds of air after the last word before the scene ends
SCENE_CAP=30
VIDEO_CAP=180
PHRASE_WORDS=7

def duration(path):
    return float(json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-of","json",str(path)],timeout=30))["format"]["duration"])

def instructions(theme):
    return ('You are narrating a short professional business video. Delivery: '+DELIVERY.get(theme,DELIVERY['midnight'])+
        '. Speak clearly at a natural broadcast pace with brief pauses at punctuation. Do not rush, do not overact, no sing-song, no announcer shout.')

def split_phrases(text):
    """Caption phrases: break at punctuation, never longer than PHRASE_WORDS words.
    Returns [(phrase, first_word_index, last_word_index_exclusive)] over the
    whitespace tokens of the narration."""
    tokens=text.split();phrases=[];current=[];begin=0
    for index,token in enumerate(tokens):
        current.append(token)
        closes=bool(re.search(r'[.,;:!?…—]$|[.!?]["”’)]$',token))
        if closes or len(current)>=PHRASE_WORDS:
            phrases.append((' '.join(current),begin,index+1));current=[];begin=index+1
    if current:phrases.append((' '.join(current),begin,len(tokens)))
    # A trailing one- or two-word orphan reads better glued to its neighbour.
    if len(phrases)>1 and phrases[-1][2]-phrases[-1][1]<=2 and phrases[-2][2]-phrases[-2][1]+phrases[-1][2]-phrases[-1][1]<=PHRASE_WORDS+2:
        a,b=phrases[-2],phrases[-1];phrases[-2:]=[(a[0]+' '+b[0],a[1],b[2])]
    return phrases

def time_phrases(text,words,seconds):
    """Map script phrases onto transcribed word timings by proportional index,
    which survives the transcriber hearing a word or two differently."""
    phrases=split_phrases(text);count=len(text.split())
    if not words or not count:return None
    timed=[]
    for phrase,a,b in phrases:
        ia=min(len(words)-1,round(a*len(words)/count));ib=max(ia,min(len(words)-1,round(b*len(words)/count)-1))
        start=float(words[ia]['start']);end=float(words[ib]['end'])
        if timed and start<timed[-1][2]:start=timed[-1][2]
        timed.append((phrase,start,max(start+.4,min(end,seconds))))
    return timed

def fit_scenes(spec,voices):
    """Grow scenes to hold their narration. Raises only when the cap is hit."""
    scenes=list(spec.scenes);grew=False
    for i,scene in enumerate(scenes):
        voice=voices.get(scene.id)
        if not voice:continue
        need=math.ceil((voice['duration']+.25+BREATH)*2)/2
        if need<=scene.seconds:continue
        if need>SCENE_CAP:raise RuntimeError(f'Narration in scene {i+1} runs {voice["duration"]:.0f} seconds; a scene holds {SCENE_CAP}. Shorten its narration and render again.')
        scenes[i]=scene.model_copy(update={'seconds':need});grew=True
    if grew and sum(s.seconds for s in scenes)>VIDEO_CAP:
        raise RuntimeError('Fitting the narration would push the video past three minutes. Shorten the narration and render again.')
    return spec.model_copy(update={'scenes':scenes}) if grew else spec

def word_timings(path,job,seconds):
    try:
        with open(path,'rb') as stream:
            response=httpx.post('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},
                data={'model':TIMING_MODEL,'response_format':'verbose_json','timestamp_granularities[]':'word'},files={'file':('voice.wav',stream,'audio/wav')},timeout=90)
        response.raise_for_status()
        from api_usage_logger import log_api_usage_sync
        log_api_usage_sync(endpoint='/ai/transcribe',model=TIMING_MODEL,input_tokens=0,output_tokens=0,business_id=job['business_id'],task_type='video_caption_timing',
            cost_cents_override=0.6*seconds/60,units=int(seconds))
        return [w for w in response.json().get('words') or [] if 'start' in w and 'end' in w]
    except Exception:
        return []

def narration(job,spec,folder,progress):
    """Returns (voices, spec). The spec comes back with scenes grown to fit."""
    voices={}
    if spec.voice=='none':return voices,spec
    from api_usage_logger import log_api_usage_sync
    for i,scene in enumerate(spec.scenes):
        if not scene.narration:continue
        progress(job,'recording_narration')
        response=httpx.post('https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},
            json={'model':TTS_MODEL,'voice':spec.voice,'input':scene.narration,'instructions':instructions(spec.theme),'response_format':'wav'},timeout=90)
        response.raise_for_status()
        log_api_usage_sync(endpoint='/ai/tts',model=TTS_MODEL,input_tokens=len(scene.narration),output_tokens=0,business_id=job['business_id'],task_type='video_narration',units=0)
        path=folder/'assets'/f'voice-{i}.wav';path.write_bytes(response.content)
        seconds=duration(path)
        voices[scene.id]={'path':'assets/'+path.name,'duration':seconds}
        if spec.captions:
            progress(job,'timing_captions')
            timed=time_phrases(scene.narration,word_timings(path,job,seconds),seconds)
            if timed:voices[scene.id]['phrases']=timed
    return voices,fit_scenes(spec,voices)
