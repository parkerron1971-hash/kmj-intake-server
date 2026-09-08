"""The look-back loop for Video Studio: Chief sees what it made before it ships.

Same pattern as module_check for built modules. After the composition is
compiled (and before the paid full render) we:

1. shoot one proof still per scene from the compiled page with headless
   Chromium, seeking the GSAP timeline to a representative moment;
2. show the stills to a designer judge (vision) with a short rubric and get
   a score out of 5, findings, and presentation-only changes (fit, motion,
   layout image<->split, callout positions, title line breaks);
3. apply the changes, shoot again, judge again, and KEEP the revision only
   if the score rose. One revision pass; the model never touches words,
   media choices, narration or durations, and every change goes back
   through the same schema validation as a plan.

The verdict is posted into the project's Chief conversation so the
practitioner sees what was looked at and what changed. Any failure in this
module degrades to "render the approved plan as-is" — the loop is polish,
never a gate.
"""
import base64
import json
import logging
import re
from pathlib import Path
from PIL import Image
from video_studio_models import Composition, Callout, validate_assets
from video_hyperframes import compile_project

log = logging.getLogger('video-check')
ALLOWED = {'fit', 'motion', 'layout', 'callouts', 'title'}
LAYOUT_SWAPS = {'image': {'split'}, 'split': {'image'}}
KEEP_SCORE = 5  # any proposed change gets one revision pass; the revision ships only if the score rises

RUBRIC = '''You are a senior motion designer reviewing proof frames of a short business video (one frame per scene, in order). Judge the LOOK, not the words. Score 1-5 where 5 = broadcast quality you would ship to a paying client.
Look for, in this order of severity:
1. Text fighting the picture: a title or caption sitting on a busy or important part of a photo/screenshot, low contrast, text over faces or over the logo.
2. Media presentation: a logo inside a visible square tile, a photo letterboxed with obvious bars, a screenshot cropped so its meaning is lost, callouts pointing at nothing or off the feature.
3. Composition: crowded copy, orphan words, a headline wrapped badly, empty frames, two scenes that look identical in a row.
4. Motion choice implied by the layout: a document with a strong push crop, a wide scene without movement.
You may change ONLY presentation: per scene "fit" (contain|cover), "motion" (rise|push|pan|still), "layout" (image<->split only), "callouts" (same labels, new x/y percent inside the picture, 4-96) and "title" line breaks (same words, insert or remove \\n only). Never change words, media, narration or seconds. Do not invent a change when the frame is fine.
Return ONLY JSON: {"score": <1-5>, "findings": [{"scene": "<scene id>", "issue": "<one sentence>"}], "changes": [{"scene": "<scene id>", "fit": "...", "motion": "...", "layout": "...", "title": "...", "callouts": [{"label": "...", "x": 0, "y": 0, "at": 0}]}], "summary": "<one or two plain sentences for the business owner>"}'''


def scene_times(spec):
    at = 0; out = []
    for s in spec.scenes:
        out.append((s.id, at + min(2.4, s.seconds * .55), at)); at += s.seconds
    return out


SEEK_JS = '''(t)=>{const tl=window.__timelines&&window.__timelines.main;if(!tl)return 'no-timeline';tl.pause(t);
for(const el of document.querySelectorAll('.clip')){const s=parseFloat(el.dataset.start||'0'),d=parseFloat(el.dataset.duration||'1e9');const on=t>=s&&t<s+d;el.style.visibility=on?'visible':'hidden';
if(el.tagName==='VIDEO'&&on){try{el.currentTime=parseFloat(el.dataset.mediaStart||'0')+(t-s)}catch(e){}}}
return 'ok'}'''


def proof_stills(folder, spec, out_dir, width=960):
    """One JPEG per scene. Returns [(scene_id, path)] or [] if Chromium is unavailable."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    w, h = {'landscape': (1920, 1080), 'portrait': (1080, 1920), 'square': (1080, 1080)}[spec.format]
    stills = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': w, 'height': h})
            page.goto((Path(folder) / 'index.html').resolve().as_uri())
            page.evaluate('document.fonts.ready.then(()=>true)')
            page.wait_for_timeout(300)
            for sid, t, _ in scene_times(spec):
                page.evaluate(SEEK_JS, t)
                page.wait_for_timeout(120)
                raw = out_dir / f'{sid}.png'
                page.screenshot(path=str(raw))
                with Image.open(raw) as im:
                    im = im.convert('RGB'); im.thumbnail((width, width))
                    target = out_dir / f'{sid}.jpg'; im.save(target, quality=82)
                raw.unlink(missing_ok=True)
                stills.append((sid, target))
            browser.close()
    except Exception:
        log.exception('Proof stills unavailable')
        return []
    return stills


def parse_verdict(text):
    decoder = json.JSONDecoder()
    for m in re.finditer(r'\{', text):
        try:
            value, _ = decoder.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and 'score' in value:
            return value
    raise ValueError('no verdict')


def apply_changes(spec, changes, assets):
    """Presentation-only patches through the same validation as a plan."""
    by_id = {s.id: s for s in spec.scenes}; scenes = list(spec.scenes); touched = []
    for change in changes or []:
        sid = change.get('scene'); scene = by_id.get(sid)
        if not scene: continue
        patch = {}
        if change.get('fit') in ('contain', 'cover') and scene.asset_id: patch['fit'] = change['fit']
        if change.get('motion') in ('rise', 'push', 'pan', 'still'): patch['motion'] = change['motion']
        if change.get('layout') in LAYOUT_SWAPS.get(scene.layout, set()) and scene.asset_id: patch['layout'] = change['layout']
        title = change.get('title')
        if isinstance(title, str) and title.replace('\n', ' ').split() == scene.title.replace('\n', ' ').split() and title.count('\n') <= 1:
            patch['title'] = title
        if isinstance(change.get('callouts'), list) and scene.callouts:
            labels = [c.label for c in scene.callouts]
            try:
                new = [Callout.model_validate(c) for c in change['callouts']][:4]
                if [c.label for c in new] == labels: patch['callouts'] = new
            except Exception:
                pass
        if patch:
            idx = scenes.index(scene); scenes[idx] = scene.model_copy(update=patch); touched.append(sid)
    if not touched: return spec, []
    revised = Composition.model_validate(spec.model_copy(update={'scenes': scenes}).model_dump(mode='json'))
    validate_assets(revised, assets)
    return revised, touched


def judge(stills, spec, business_id):
    import llm_call, chief_models
    content = [{'type': 'text', 'text': RUBRIC + '\nScenes in order: ' + json.dumps([{'id': s.id, 'layout': s.layout, 'fit': s.fit, 'motion': s.motion, 'has_media': bool(s.asset_id), 'callouts': [c.model_dump() for c in s.callouts]} for s in spec.scenes])}]
    for sid, path in stills:
        content.append({'type': 'text', 'text': f'Scene {sid}:'})
        content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(Path(path).read_bytes()).decode()}})
    response = llm_call.post({'model': chief_models.model_for('chat'), 'max_tokens': 1800, 'messages': [{'role': 'user', 'content': content}]}, timeout=120, business_id=business_id, task='video_look')
    response.raise_for_status(); data = response.json()
    text = ''.join(x.get('text', '') for x in data.get('content', []) if x.get('type') == 'text')
    verdict = parse_verdict(text)
    verdict['score'] = max(1, min(5, int(verdict.get('score') or 3)))
    return verdict


def look_pass(job, spec, folder, media, voices, music, analysis, assets, progress):
    """Returns (spec_to_render, message_for_the_owner or None). Never raises."""
    try:
        progress(job, 'checking_the_look')
        folder = Path(folder)
        stills = proof_stills(folder, spec, folder / 'proof-a')
        if not stills: return spec, None
        first = judge(stills, spec, job['business_id'])
        score = first['score']; summary = first.get('summary') or ''
        message = f'I looked at proof frames of every scene before rendering: {score}/5. {summary}'.strip()
        if score >= KEEP_SCORE or not first.get('changes'):
            return spec, message
        revised, touched = apply_changes(spec, first.get('changes'), assets)
        if not touched: return spec, message
        compile_project(revised, folder, media, voices, music, analysis)
        second = judge(proof_stills(folder, revised, folder / 'proof-b'), revised, job['business_id'])
        if second['score'] > score:
            names = ', '.join(touched)
            return revised, f'{message} I adjusted the presentation of scene {names} and the look went from {score}/5 to {second["score"]}/5, so that is the version rendering now.'
        compile_project(spec, folder, media, voices, music, analysis)
        return spec, f'{message} I tried a presentation change on scene {", ".join(touched)} but it did not read better, so the approved plan is rendering as-is.'
    except Exception:
        log.exception('Look pass skipped')
        try: compile_project(spec, folder, media, voices, music, analysis)
        except Exception: pass
        return spec, None
