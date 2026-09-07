"""Narration cost logging is separate from Chief planning metering."""
import os,json,subprocess
import httpx

def duration(path):
    return float(json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-of","json",str(path)],timeout=30))["format"]["duration"])

def narration(job,spec,folder,progress):
    voices={}
    if spec.voice=='none':return voices
    from api_usage_logger import log_api_usage_sync
    for i,scene in enumerate(spec.scenes):
        if not scene.narration:continue
        progress(job,'recording_narration')
        response=httpx.post('https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},
            json={'model':'tts-1','voice':spec.voice,'input':scene.narration,'response_format':'wav'},timeout=90)
        response.raise_for_status()
        log_api_usage_sync(endpoint='/ai/tts',model='tts-1',input_tokens=len(scene.narration),output_tokens=0,business_id=job['business_id'],task_type='video_narration',units=0)
        path=folder/'assets'/f'voice-{i}.wav';path.write_bytes(response.content)
        seconds=duration(path)
        if seconds>scene.seconds-.5:raise RuntimeError(f'Narration in scene {i+1} needs {seconds+.5:.1f} seconds. Shorten its narration or extend the scene and render again.')
        voices[scene.id]={'path':'assets/'+path.name,'duration':seconds}
    return voices
