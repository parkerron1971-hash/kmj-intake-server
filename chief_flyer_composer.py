"""Fixed-canvas flyer composition with owned raster layers and editable SVG text.

No model-authored HTML, script, remote fonts or remote image URLs are accepted.
The normalized layout lives in the existing private artwork record for reproducible exports.
"""
from __future__ import annotations

import asyncio
import base64
import html
import json
from typing import Annotated, Literal, Union
from uuid import UUID, uuid5

import httpx
from fastapi import HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import image_studio as images

PREFIX = 'EDITABLE_FLYER_V1\n'
Color = Annotated[str, Field(pattern=r'^(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}|none)$')]
FONTS = {'sans': 'Arial, Liberation Sans, sans-serif', 'condensed': 'Impact, Arial Narrow, Liberation Sans, sans-serif',
         'serif': 'Georgia, Liberation Serif, serif', 'mono': 'Courier New, Liberation Mono, monospace'}
_slots = asyncio.Semaphore(2)

PROMPT = '''
EDITABLE FLYER FINISHING:
Use compose_flyer when exact typography, logos or screenshot placement matters, or the owner
asks for an editable flyer. It creates a PNG preview plus an SVG master with separate editable
image, shape and text layers. It does not extract layers from an existing flattened design.
For generated key art, first request an image without lettering, leaving the intended text areas
clear; after it is ready, compose the final copy over that owned artwork. Never promise an editable
master for a generate_image-only result. Existing photographs/logos/screenshots can be composed
immediately, without generative redrawing. Do not add a second title over a flattened existing title.
[ACTION:{"type":"compose_flyer","layout":{"width":1080,"height":1350,"background":"#111111",
"title":"Short asset title","layers":[
{"kind":"image","image_id":"owned-artwork-UUID or chat:1","x":0,"y":0,"width":1080,"height":1350,"fit":"cover"},
{"kind":"text","text":"APPROVED HEADLINE\\nSECOND LINE","x":70,"y":120,"width":940,"font_size":100,"font":"sans","weight":800,"fill":"#ffffff","line_height":1.05},
{"kind":"shape","shape":"rect","x":70,"y":1100,"width":450,"height":90,"fill":"#ffffff","radius":12}
]}}]
This is a schema example, not a template to reuse. Invent the composition for the brief. Layer order
is back to front; images may overlap text deliberately. Canvas dimensions are 320-2400 pixels,
maximum 24 layers, four images. Text: x/y are left/top; width is its available line width;
use explicit newlines, font sans/condensed/serif/mono, weight 400/600/700/800/900,
align left/center/right, fill hex color, optional tracking, line_height, opacity and rotation.
Image layers: owned image_id or chat:N; fit cover/contain; optional radius, opacity and rotation.
Shapes: rect/ellipse; x/y/width/height/fill; optional stroke, stroke_width, radius, opacity, rotation.
Use larger body text for phone readability, safe margins and purposeful hierarchy. Exact font
selection is limited to the installed font families; do not promise a specific commercial font.
Refine an editable flyer by issuing its COMPLETE revised layout and preserving unchanged layers.
Do not regenerate its imagery just to change spelling, prices or spacing.
'''


class Layer(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, validate_default=True)
    x: float = Field(ge=-2400, le=2400)
    y: float = Field(ge=-2400, le=2400)
    opacity: float = Field(default=1, ge=0, le=1)
    rotation: float = Field(default=0, ge=-180, le=180)


class TextLayer(Layer):
    kind: Literal['text']
    text: str = Field(min_length=1, max_length=2000)
    width: float = Field(gt=0, le=2400)
    font_size: float = Field(ge=12, le=600)
    font: Literal['sans', 'condensed', 'serif', 'mono'] = 'sans'
    weight: Literal[400, 600, 700, 800, 900] = 700
    fill: Color = '#ffffff'
    align: Literal['left', 'center', 'right'] = 'left'
    line_height: float = Field(default=1.15, ge=.8, le=2)
    tracking: float = Field(default=0, ge=-15, le=40)

    @field_validator('text')
    @classmethod
    def clean_text(cls, text):
        if any(ord(c) < 32 and c not in '\n\t' for c in text) or len(text.splitlines()) > 20:
            raise ValueError('Use at most 20 lines of printable text per layer.')
        return text


class ImageLayer(Layer):
    kind: Literal['image']
    image_id: UUID
    width: float = Field(gt=0, le=4800)
    height: float = Field(gt=0, le=4800)
    fit: Literal['cover', 'contain'] = 'cover'
    radius: float = Field(default=0, ge=0, le=1200)


class ShapeLayer(Layer):
    kind: Literal['shape']
    shape: Literal['rect', 'ellipse'] = 'rect'
    width: float = Field(gt=0, le=4800)
    height: float = Field(gt=0, le=4800)
    fill: Color
    stroke: Color = 'none'
    stroke_width: float = Field(default=0, ge=0, le=100)
    radius: float = Field(default=0, ge=0, le=1200)


class Layout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    width: int = Field(ge=320, le=2400)
    height: int = Field(ge=320, le=2400)
    title: str = Field(default='Flyer', min_length=1, max_length=180)
    background: Color = '#ffffff'
    layers: list[Annotated[Union[TextLayer, ImageLayer, ShapeLayer], Field(discriminator='kind')]] = Field(min_length=1, max_length=24)

    @model_validator(mode='after')
    def bounded(self):
        if sum(isinstance(layer, ImageLayer) for layer in self.layers) > 4:
            raise ValueError('Use at most four image layers.')
        if sum(len(layer.text) for layer in self.layers if isinstance(layer, TextLayer)) > 4000:
            raise ValueError('Keep the flyer copy under 4000 characters.')
        return self


def encode_layout(layout):
    value = PREFIX + layout.model_dump_json()
    if len(value) > 20000:
        raise HTTPException(422, 'Simplify the flyer layout.')
    return value


def decode_layout(row):
    prompt = row.get('prompt', '')
    if not prompt.startswith(PREFIX):
        raise HTTPException(409, 'This artwork has no editable master. Ask Chief to compose an editable flyer.')
    return Layout.model_validate_json(prompt[len(PREFIX):])


async def svg_document(client, business_id, layout):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}">',
             f'<title>{html.escape(layout.title)}</title>',
             f'<rect width="100%" height="100%" fill="{layout.background}"/>']
    loaded = {}
    total = 0
    for i, layer in enumerate(layout.layers):
        width = layer.width
        height = getattr(layer, 'height', layer.font_size if isinstance(layer, TextLayer) else 0)
        parts.append(f'<g id="layer-{i}" opacity="{layer.opacity}" transform="translate({layer.x} {layer.y}) rotate({layer.rotation} {width/2} {height/2})">')
        if isinstance(layer, TextLayer):
            offset = {'left': 0, 'center': width/2, 'right': width}[layer.align]
            anchor = {'left': 'start', 'center': 'middle', 'right': 'end'}[layer.align]
            parts.append(f'<text data-max-width="{width}" font-family="{FONTS[layer.font]}" font-size="{layer.font_size}" font-weight="{layer.weight}" fill="{layer.fill}" text-anchor="{anchor}" letter-spacing="{layer.tracking}">')
            for index, line in enumerate(layer.text.split('\n')):
                parts.append(f'<tspan x="{offset}" y="{layer.font_size + index*layer.font_size*layer.line_height}">{html.escape(line)}</tspan>')
            parts.append('</text>')
        elif isinstance(layer, ShapeLayer):
            attr = f'fill="{layer.fill}" stroke="{layer.stroke}" stroke-width="{layer.stroke_width}"'
            if layer.shape == 'rect':
                parts.append(f'<rect width="{width}" height="{height}" rx="{layer.radius}" {attr}/>')
            else:
                parts.append(f'<ellipse cx="{width/2}" cy="{height/2}" rx="{width/2}" ry="{height/2}" {attr}/>')
        else:
            key = str(layer.image_id)
            if key not in loaded:
                raw = images.normalize_image(await images.original(client, await images.artwork(client, business_id, key)))
                total += len(raw)
                if total > 24 * 1024 * 1024:
                    raise HTTPException(422, 'Use smaller source images for this flyer.')
                loaded[key] = base64.b64encode(raw).decode()
            parts.append(f'<defs><clipPath id="clip-{i}"><rect width="{width}" height="{height}" rx="{layer.radius}"/></clipPath></defs>')
            fit = 'slice' if layer.fit == 'cover' else 'meet'
            parts.append(f'<image width="{width}" height="{height}" preserveAspectRatio="xMidYMid {fit}" clip-path="url(#clip-{i})" href="data:image/png;base64,{loaded[key]}"/>')
        parts.append('</g>')
    parts.append('</svg>')
    return ''.join(parts)


async def render_svg(svg, layout):
    from playwright.async_api import async_playwright
    async with _slots, async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            page = await browser.new_page(viewport={'width': layout.width, 'height': layout.height}, device_scale_factor=1,
                                          java_script_enabled=False, service_workers='block')
            await page.route('**/*', lambda route: route.abort())
            await page.set_content('<!doctype html><meta charset="utf-8"><style>html,body{margin:0}svg{display:block}</style>' + svg)
            await page.evaluate('document.fonts.ready')
            problems = await page.locator('text').evaluate_all('els => els.filter(e => e.getBBox().width > Number(e.dataset.maxWidth) + 2).map(e => e.parentElement.id)')
            if problems:
                raise HTTPException(422, 'Text exceeds its allocated width in ' + ', '.join(problems) + '. Add line breaks or adjust its size/width.')
            clipped = await page.locator('text').evaluate_all('els => els.filter(e => { const r=e.getBoundingClientRect(); return r.left < -1 || r.top < -1 || r.right > innerWidth+1 || r.bottom > innerHeight+1; }).map(e => e.parentElement.id)')
            if clipped:
                raise HTTPException(422, 'Text is clipped outside the canvas in ' + ', '.join(clipped) + '. Move it within the flyer margins.')
            return await page.screenshot(type='png', animations='disabled')
        finally:
            await browser.close()


async def prepare_action(action, body, owner):
    """Resolve current chat sources, never model URLs, into private owned images."""
    from chief_flyer_direction import chat_references, save_chat_reference
    from platform_chief_creative import platform_business
    raw = json.loads(json.dumps(action.get('layout', {})))
    catalog = chat_references(body)
    selections = []
    for index, layer in enumerate(raw.get('layers', [])):
        source = layer.get('image_id')
        if layer.get('kind') == 'image' and isinstance(source, str) and source.startswith('chat:'):
            try:
                number = int(source[5:]) - 1
                if number < 0 or number >= len(catalog):
                    raise ValueError()
            except ValueError:
                raise HTTPException(422, 'Choose an attached image for this layer.') from None
            selections.append((index, catalog[number]))
            layer['image_id'] = '00000000-0000-0000-0000-000000000000'
    Layout.model_validate(raw)  # Complete schema validation before uploads.
    if selections:
        biz = await platform_business(owner)
        async with httpx.AsyncClient(timeout=30) as client:
            biz = await images.business(client, biz['id'])
            for index, image in selections:
                raw['layers'][index]['image_id'] = await save_chat_reference(client, biz, image)
    layout = Layout.model_validate(raw)
    encode_layout(layout)
    return {'type': 'compose_flyer', 'layout': layout.model_dump(mode='json')}


async def compose(client, biz, action, request_id):
    biz = await images.business(client, biz['id'])
    layout = Layout.model_validate(action.get('layout'))
    prompt = encode_layout(layout)
    iid = uuid5(UUID(str(biz['id'])), f'chief-composition:{request_id}')
    existing = await images.db(client, 'GET', f'/image_artworks?id=eq.{iid}&business_id=eq.{biz["id"]}')
    if existing:
        if existing[0]['prompt'] != prompt:
            raise HTTPException(409, 'This request already contains a different layout. Start a new revision.')
        result = await images.present(client, existing[0])
    else:
        svg = await svg_document(client, biz['id'], layout)
        png = await render_svg(svg, layout)
        if len(png) > images.MAX_BYTES:
            raise HTTPException(422, 'The composed flyer is too large. Reduce its dimensions.')
        path = f'{biz["id"]}/{iid}.png'
        await images.store(client, path, png, 'image/png')
        row = {'id': str(iid), 'business_id': str(biz['id']), 'owner_id': str(biz['owner_id']),
               'prompt': prompt, 'status': 'ready', 'storage_path': path, 'cost_usd': 0,
               'size': f'{layout.width}x{layout.height}',
               'reference_ids': list(dict.fromkeys(str(l.image_id) for l in layout.layers if isinstance(l, ImageLayer)))}
        rows = await images.db(client, 'POST', '/image_artworks', row, server_write=True)
        result = await images.present(client, rows[0])
    return {'result': 'Flyer composed with editable text, shape and image layers. Review the PNG and download the SVG master. Nothing was published.',
            'label': 'Your editable flyer', 'image': {**result, 'editable_master': True}}


async def export_master(business_id, image_id):
    async with httpx.AsyncClient(timeout=30) as client:
        await images.business(client, business_id)
        row = await images.artwork(client, business_id, image_id)
        svg = await svg_document(client, business_id, decode_layout(row))
    return Response(svg, media_type='image/svg+xml', headers={
        'Content-Disposition': f'attachment; filename="flyer-{image_id}.svg"',
        'Content-Security-Policy': "default-src 'none'; img-src data:; sandbox",
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store',
    })
