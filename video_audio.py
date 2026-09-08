"""Music bed for Video Studio renders.

The uploaded soundtrack used to be dropped in at a fixed whisper (12 %) and
cut off dead at the end of the video. This mixes it the way an editor
would: loop it if it is shorter than the piece, trim it to the piece, fade
it in over the first second and out over the last two and a half, and duck
it under every narrated passage with a smooth ramp either side. The result
is a single bed file the renderer plays at unity gain.

Everything runs through ffmpeg with an argument list (no shell). If any
step fails the caller falls back to the raw upload at the old fixed gain —
a render never fails over music polish.
"""
from pathlib import Path
import subprocess

BED_GAIN=.24     # music alone
DUCK_GAIN=.32    # multiplier under narration (≈ -10 dB)
RAMP=.45         # seconds of ramp into and out of a duck
FADE_IN=1.2
FADE_OUT=2.5

def duck_expression(windows):
    """ffmpeg `volume` expression: unity outside every window, DUCK_GAIN inside,
    linear ramps of RAMP seconds either side. Windows are (start, end)."""
    factors=[]
    for a,b in windows:
        mid=(a+b)/2;half=(b-a)/2
        factors.append(f'({DUCK_GAIN}+{1-DUCK_GAIN}*clip((abs(t-{mid:.2f})-{half:.2f})/{RAMP},0,1))')
    return f'{BED_GAIN}*'+'*'.join(factors) if factors else f'{BED_GAIN}'

def narration_windows(spec,voices):
    windows=[];at=0
    for scene in spec.scenes:
        voice=voices.get(scene.id)
        if voice:windows.append((at+.25,at+.25+voice['duration']))
        at+=scene.seconds
    return windows

def prepare_music(spec,folder:Path,media,voices,total):
    """Returns the compiler's music dict, or None to use the raw upload."""
    if not spec.music_asset_id:return None
    item=media.get(str(spec.music_asset_id))
    if not item or not item.get('local'):return None
    target=folder/'assets'/'music-bed.mp3'
    expression=duck_expression(narration_windows(spec,voices))
    filters=f"volume='{expression}':eval=frame,afade=t=in:st=0:d={FADE_IN},afade=t=out:st={max(0,total-FADE_OUT):.2f}:d={FADE_OUT}"
    try:
        subprocess.run(['ffmpeg','-v','error','-y','-protocol_whitelist','file,pipe','-stream_loop','-1','-i',str(item['local']),
            '-t',f'{total:.3f}','-vn','-filter:a',filters,'-ac','2','-ar','44100','-c:a','libmp3lame','-q:a','2',str(target)],
            check=True,timeout=180,capture_output=True)
        if not target.exists() or target.stat().st_size<1000:return None
    except Exception:
        return None
    return {'path':'assets/'+target.name,'duration':total,'volume':1}
