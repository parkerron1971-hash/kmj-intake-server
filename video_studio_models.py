"""The renderer accepts validated scene data, never model-authored code or URLs."""
import hashlib
import json
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from program_outcomes import StrictModel

Color = str

class Callout(StrictModel):
    """A label that lights up one feature on a screenshot. x/y are percent
    positions inside the picture; `at` is seconds into the scene."""
    label: str = Field(min_length=1, max_length=40)
    x: float = Field(ge=4, le=96, allow_inf_nan=False)
    y: float = Field(ge=4, le=96, allow_inf_nan=False)
    at: float = Field(default=1, ge=0, le=28, allow_inf_nan=False)

class DemoTile(StrictModel):
    label: str = Field(min_length=1, max_length=24)
    value: str = Field(min_length=1, max_length=14)

class Demo(StrictModel):
    """An animated product demonstration built from DATA, never from code.
    chat: the owner types a prompt, the assistant replies, a result card lands.
    dashboard: a greeting, tiles that count up, quick-action chips."""
    kind: Literal['chat', 'dashboard']
    app_name: str = Field(default='', max_length=40)
    assistant: str = Field(default='Chief', max_length=24)
    prompt: str = Field(default='', max_length=90)
    reply: str = Field(default='', max_length=160)
    card_title: str = Field(default='', max_length=40)
    card_value: str = Field(default='', max_length=20)
    card_note: str = Field(default='', max_length=60)
    greeting: str = Field(default='', max_length=60)
    tiles: list[DemoTile] = Field(default_factory=list, max_length=4)
    actions: list[str] = Field(default_factory=list, max_length=6)
    @model_validator(mode='after')
    def limits(self):
        if self.kind=='chat' and not (self.prompt and self.reply): raise ValueError('A chat demo needs a prompt and a reply.')
        if self.kind=='dashboard' and len(self.tiles)<2: raise ValueError('A dashboard demo needs at least two tiles.')
        if any(len(x)>24 for x in self.actions): raise ValueError('Keep each quick action under 24 characters.')
        return self

class Scene(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    layout: Literal['title', 'split', 'image', 'quote', 'features', 'stat', 'closing', 'logo', 'demo'] = 'title'
    title: str = Field(min_length=1, max_length=100)
    subtitle: str = Field(default='', max_length=200)
    eyebrow: str = Field(default='', max_length=45)
    narration: str = Field(default='', max_length=600)
    seconds: float = Field(ge=3, le=30, allow_inf_nan=False)
    asset_id: UUID | None = None
    source_start: float = Field(default=0, ge=0, le=7200, allow_inf_nan=False)
    fit: Literal['contain', 'cover'] = 'contain'
    motion: Literal['rise', 'push', 'pan', 'still'] = 'rise'
    points: list[str] = Field(default_factory=list, max_length=3)
    statistic: int | None = Field(default=None, ge=-1000000, le=1000000)
    suffix: str = Field(default='', max_length=12)
    callouts: list[Callout] = Field(default_factory=list, max_length=4)
    demo: Demo | None = None
    @model_validator(mode='after')
    def limits(self):
        if any(len(x)>80 for x in self.points): raise ValueError('Keep each point under 80 characters.')
        if self.layout=='demo' and not self.demo: raise ValueError('A demo scene needs its demo details.')
        if self.layout=='demo' and self.seconds<6: raise ValueError('A demo scene needs at least six seconds.')
        if self.callouts and not self.asset_id: raise ValueError('Callouts point at a picture; choose media for this scene.')
        if self.layout=='stat' and self.statistic is None: raise ValueError('A stat needs a verified value.')
        if self.layout in ('image','split') and not self.asset_id: raise ValueError('Choose media for this layout.')
        return self

class Composition(StrictModel):
    version: Literal[1] = 1
    title: str = Field(min_length=1,max_length=160)
    format: Literal['landscape','portrait','square'] = 'landscape'
    theme: Literal['midnight','paper','warm'] = 'midnight'
    accent: str = Field(default='#4BA9FF',pattern=r'^#[0-9A-Fa-f]{6}$')
    voice: Literal['none','alloy','nova','onyx'] = 'none'
    captions: bool = True
    music_asset_id: UUID | None = None
    scenes: list[Scene] = Field(min_length=1,max_length=20)
    @model_validator(mode='after')
    def limits(self):
        if len(set(s.id for s in self.scenes))!=len(self.scenes): raise ValueError('Scene IDs must be unique.')
        if sum(s.seconds for s in self.scenes)>180: raise ValueError('Videos can be up to three minutes.')
        if self.voice!='none' and sum(len(s.narration) for s in self.scenes)>5000: raise ValueError('Narration is too long.')
        return self
    def digest(self): return hashlib.sha256(json.dumps(self.model_dump(mode='json'),sort_keys=True).encode()).hexdigest()

class CreateProject(StrictModel):
    title: str = Field(default='Untitled video',min_length=1,max_length=160)
    brief: str = Field(default='',max_length=12000)
    format: Literal['landscape','portrait','square'] = 'landscape'

class Message(StrictModel):
    message: str = Field(min_length=1,max_length=6000)
    expected_revision: int = Field(ge=0,strict=True)
    request_id: UUID

class SaveRevision(StrictModel):
    composition: Composition
    expected_revision: int = Field(ge=0,strict=True)
    label: str = Field(default='Your edits',min_length=1,max_length=100)

class RenderRequest(StrictModel):
    revision_id: UUID
    expected_revision: int = Field(ge=1,strict=True)
    request_id: UUID
    composition_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    approved: Literal[True]

class Purpose(StrictModel):
    purpose: Literal['include','reference']

class ChiefPlan(StrictModel):
    message: str = Field(min_length=1,max_length=3500)
    composition: Composition | None = None

def validate_assets(composition, assets):
    included={str(a['id']):a for a in assets if a['purpose']=='include'}
    for scene in composition.scenes:
        if scene.asset_id:
            asset=included.get(str(scene.asset_id))
            if not asset or not asset['mime_type'].startswith(('image/','video/')):
                raise ValueError('A scene uses unavailable or reference-only media. Choose a file marked Use in video.')
            if asset['mime_type'].startswith('video/') and scene.source_start+scene.seconds>float(asset.get('duration_seconds') or 0)+.05:
                raise ValueError('A scene extends beyond its source video.')
    if composition.music_asset_id:
        asset=included.get(str(composition.music_asset_id))
        if not asset or not asset['mime_type'].startswith('audio/'):
            raise ValueError('Choose an included audio file for the soundtrack.')
