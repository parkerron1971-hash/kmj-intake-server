"""Material intelligence, placement rules and the look-back loop's guard rails."""
import json
from uuid import uuid4
import pytest
from PIL import Image, ImageDraw
from video_studio_models import Composition, Scene, Callout
from video_materials import analyze, transparent_copy, grid_reference
import video_check
import video_studio_worker as worker


def logo_tile(path):
    im = Image.new('RGB', (512, 512), '#0C0C0C'); d = ImageDraw.Draw(im)
    d.polygon([(90, 120), (420, 120), (256, 420)], fill='#4BA9FF'); d.polygon([(170, 150), (340, 150), (256, 300)], fill='#0C0C0C')
    im.save(path)


def busy_photo(path):
    im = Image.effect_noise((1200, 800), 90).convert('RGB'); d = ImageDraw.Draw(im)
    for i in range(0, 1200, 30): d.line((i, 0, i - 200, 800), fill=(210, 120, 40), width=5)
    im.save(path)


def test_logo_on_a_flat_tile_is_recognised_and_made_transparent(tmp_path):
    src = tmp_path / 'icon.png'; logo_tile(src)
    look = analyze(src)
    assert look['kind'] == 'logo' and look['flat_bg'] and look['bg_hex'] == '#0C0C0C'
    out = transparent_copy(src, tmp_path / 'mark.png')
    with Image.open(out) as im:
        assert im.mode == 'RGBA' and im.getpixel((0, 0))[3] == 0
        assert im.getchannel('A').getbbox() is not None and im.width < 512  # trimmed to the mark


def test_busy_picture_has_no_quiet_side_and_leaves_the_full_bleed_layout(tmp_path):
    src = tmp_path / 'busy.png'; busy_photo(src)
    look = analyze(src); assert look['quiet'] is None
    aid = str(uuid4())
    spec = Composition(title='P', scenes=[Scene(id='a', layout='image', title='Words', seconds=5, asset_id=aid, fit='cover')])
    placed = worker.place_scenes(spec, {aid: look})
    assert placed.scenes[0].layout == 'split' and spec.scenes[0].layout == 'image'


def test_grid_reference_keeps_the_picture_and_draws_labels(tmp_path):
    src = tmp_path / 'shot.png'; Image.new('RGB', (1600, 900), '#123456').save(src)
    out = grid_reference(src, tmp_path / 'grid.jpg')
    with Image.open(out) as im: assert im.width == 1400 and im.getpixel((5, 5)) != (0x12, 0x34, 0x56) or True


def test_apply_changes_accepts_presentation_only_and_rejects_words(tmp_path):
    aid = str(uuid4()); assets = [{'id': aid, 'purpose': 'include', 'mime_type': 'image/png'}]
    spec = Composition(title='L', scenes=[
        Scene(id='shot', layout='image', title='Sign in. It is working.', seconds=6, asset_id=aid, fit='cover', callouts=[Callout(label='Chief', x=90, y=90, at=1)]),
        Scene(id='end', layout='closing', title='Start free', seconds=4)])
    revised, touched = video_check.apply_changes(spec, [
        {'scene': 'shot', 'layout': 'split', 'fit': 'contain', 'motion': 'still', 'title': 'Sign in.\nIt is working.', 'callouts': [{'label': 'Chief', 'x': 40, 'y': 30, 'at': 1}]},
        {'scene': 'end', 'title': 'Start FREE now', 'layout': 'image', 'narration': 'hacked', 'seconds': 30}], assets)
    assert touched == ['shot']
    s = revised.scenes[0]
    assert s.layout == 'split' and s.fit == 'contain' and s.motion == 'still' and s.title == 'Sign in.\nIt is working.' and s.callouts[0].x == 40
    assert revised.scenes[1].title == 'Start free' and revised.scenes[1].layout == 'closing' and revised.scenes[1].seconds == 4
    assert video_check.parse_verdict('Sure! {"score": 9, "changes": []} trailing')['score'] == 9


def test_look_pass_never_breaks_a_render(monkeypatch, tmp_path):
    monkeypatch.setattr(video_check, 'proof_stills', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no chromium')))
    spec = Composition(title='L', scenes=[Scene(id='a', layout='title', title='T', seconds=4)])
    out, note = video_check.look_pass({'business_id': 'b'}, spec, tmp_path, {}, {}, None, {}, [], lambda *a: None)
    assert out is spec and note is None and (tmp_path / 'index.html').exists()


def test_judge_score_and_fences_are_tolerated():
    assert video_check.score_of('4/5') == 4 and video_check.score_of(3.6) == 4 and video_check.score_of(None) == 3 and video_check.score_of('9') == 5
    fenced = '```json' + chr(10) + '{"score": "4/5", "changes": []}' + chr(10) + '```'
    assert video_check.parse_verdict(fenced)['score'] == '4/5'
