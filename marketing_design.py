"""marketing_design.py — the pictures the Monday plan puts on its posts.

Kevin, 2026-09-28: every planned post should go out with a design, and the
design work that costs money needs a budget of its own — spend inside it,
ask for more when a week needs more.

TWO KINDS OF DESIGN, ONE OF WHICH COSTS MONEY
  The flyer. Built by code from a template in the Solutionist palette and
  rendered by the existing composer (chief_flyer_composer: an SVG with real
  text, rendered in a sandboxed browser). No image model draws the words, so
  the headline is spelled right and the flyer costs nothing to make. Every
  planned post gets one, which is also what lets Instagram — which refuses a
  post without a picture — be part of the week.

  The hero image. One generated photograph a week, behind the flyers of the
  week's lead play. This is the paid part. It is made only when the month's
  design budget still covers it; otherwise the flyers go out flat and the run
  records a request for more budget, which only the owner can grant. The
  prompts are fixed per play (no model writes them) and always ask for no
  lettering, so nothing in the picture can make a claim.

EVERY BUSINESS'S FLYER (marketing suite B8, 2026-10-07)
  flyer_layout also draws a business's free weekly-suggestion flyer: its own
  colours (brand_palette over settings.brand_kit), its own eyebrow, and its
  own name and site in the footer. With none of those passed it is exactly
  the platform flyer, Solutionist's footer and all.

WHERE IT RUNS
  Inside the engine's run, with no signed-in user. It binds image_studio's
  build actor to the platform business and its owner — the same scoped
  capability the durable build runner uses — so every read and write stays
  inside that one business, and the image reservation keeps its ownership
  check and daily limit.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import textwrap
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from fastapi import HTTPException

import platform_marketing as marketing

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1350          # 4:5 — Instagram's portrait feed shape, fine on Facebook and X
HERO_ESTIMATE_USD = 0.10            # a medium-quality portrait image, with headroom over its ~$0.06
HERO_WAIT_SECONDS = 150
DEFAULT_BUDGET_USD = 10.0

NAVY, NAVY_2 = '#0B1330', '#16285C'
BLUE, ICE, VIOLET = '#2E7DFF', '#9DB8FF', '#8975ED'
WHITE, MIST = '#FFFFFF', '#C9D6F5'

EYEBROW = {
    'feature_spotlight': 'NEW IN THE SYSTEM',
    'founder_invitation': 'FOUNDING SEATS',
    'workflow_tip': 'A USEFUL MOVE',
    'behind_the_build': 'WHY WE BUILT IT',
    'question_answered': 'YOU ASKED',
}

# Fixed, lettering-free scenes. A generated picture carries mood, never a claim.
HERO_SCENE = {
    'feature_spotlight': 'a tidy desk in soft morning light with a phone lying face down beside an open notebook',
    'founder_invitation': 'a small-business owner at a calm, organised workspace at dawn, laptop open, confident and unhurried',
    'workflow_tip': 'hands arranging a paper planner, a pen and a phone on a clean wooden desk',
    'behind_the_build': 'a quiet studio workbench at dusk with sketches, a laptop and a cup of coffee',
    'question_answered': 'a person by a bright window with a cup of coffee, thinking, relaxed',
}


def hero_prompt(play):
    return (f'Editorial photograph: {HERO_SCENE[play]}. Cinematic natural light, shallow depth of field, '
            'deep navy and blue tones with a restrained violet accent, no green. Absolutely no text, letters, '
            'numbers, logos, signs, screens with readable content or watermarks. Leave calm, uncluttered space '
            'in the lower third.')


# ── flyer layouts ─────────────────────────────────────────────────────

# Glyph-width estimates for wrapping. The composer measures the real text
# and refuses a line that overflows, so these only need to be close; a
# refusal shrinks the type and tries again.
_CHAR = {'display': 0.40, 'sans': 0.53}


def _wrap(text, size, width, font):
    per_line = max(6, int(width / (size * _CHAR[font])))
    return textwrap.wrap(text, per_line, break_long_words=True) or [text]


def _text(text, x, y, width, size, font='sans', weight=700, fill=WHITE, **extra):
    return {'kind': 'text', 'text': text, 'x': x, 'y': y, 'width': width, 'font_size': size,
            'font': font, 'weight': weight, 'fill': fill, **extra}


# The platform's own flyer: Solutionist's palette and footer. A business's
# flyer (marketing suite B8) passes its own palette (brand_palette) and its
# own name and site as the footer; nothing of Solutionist's is left on it.
PLATFORM_PALETTE = {'bg': NAVY, 'bg2': NAVY_2, 'accent': BLUE, 'accent2': VIOLET, 'ink': WHITE, 'mist': MIST,
                    'ice': ICE, 'on_accent': WHITE}
PLATFORM_FOOTER = {'label': 'THE SOLUTIONIST SYSTEM', 'host': 'mysolutionist.app'}


def flyer_layout(play, copy, *, hero_id=None, scale=1.0, eyebrow=None, footer=None, palette=None):
    """One flyer as a composer Layout. `copy` = {headline, line, cta}, already checked.

    eyebrow, footer ({label, host}) and palette (PLATFORM_PALETTE's keys)
    default to Solutionist's own; with none of them given, the layout is
    exactly the platform flyer it always was."""
    p = {**PLATFORM_PALETTE, **(palette or {})}
    eyebrow = EYEBROW[play] if eyebrow is None else str(eyebrow)
    margin, inner = 80, WIDTH - 160
    layers = [{'kind': 'shape', 'shape': 'rect', 'x': 0, 'y': 0, 'width': WIDTH, 'height': HEIGHT, 'fill': p['bg'],
               'gradient': {'start': p['bg'], 'end': p['bg2'], 'direction': 'vertical'}}]
    if hero_id:
        # The photograph takes the top ~40%; the words need the rest to fit a
        # two-line headline and a two-line sentence at full size.
        layers.append({'kind': 'image', 'image_id': str(hero_id), 'x': 0, 'y': 0, 'width': WIDTH, 'height': 520,
                       'fit': 'cover'})
        layers.append({'kind': 'shape', 'shape': 'rect', 'x': 0, 'y': 420, 'width': WIDTH, 'height': 100,
                       'fill': p['bg'], 'opacity': 0.55})
        area_top, head_size = 560, 88 * scale
    else:
        layers.append({'kind': 'shape', 'shape': 'ellipse', 'x': 560, 'y': -300, 'width': 820, 'height': 820,
                       'fill': p['accent'], 'opacity': 0.16})
        layers.append({'kind': 'shape', 'shape': 'ellipse', 'x': -260, 'y': 980, 'width': 560, 'height': 560,
                       'fill': p['accent2'], 'opacity': 0.12})
        area_top, head_size = 110, 128 * scale
    area_bottom = HEIGHT - 170            # the footer rule sits below this

    eyebrow_size, line_size, cta_size, pill_h = 28, 44 * scale, 34, 96
    head_lines = _wrap(copy['headline'].upper(), head_size, inner, 'display')
    body_lines = _wrap(copy['line'], line_size, inner, 'sans')
    block = (eyebrow_size + 26 + 8 + 40 + head_size * 1.02 * len(head_lines) + 34
             + line_size * 1.3 * len(body_lines) + 64 + pill_h)
    if block > area_bottom - area_top:
        raise HTTPException(422, 'The flyer copy does not fit.')
    # Over a photograph the text sits right under it; on a flat flyer the
    # block is centred, so a short headline doesn't leave a hole above the button.
    y = area_top if hero_id else area_top + (area_bottom - area_top - block) / 2

    layers.append(_text(eyebrow, margin, y, inner, eyebrow_size, weight=800, fill=p['ice'], tracking=6))
    y += eyebrow_size + 26
    layers.append({'kind': 'shape', 'shape': 'rect', 'x': margin, 'y': y, 'width': 120, 'height': 8,
                   'fill': p['accent'], 'radius': 4})
    y += 8 + 40
    layers.append(_text('\n'.join(head_lines), margin, y, inner, head_size, font='display', weight=400,
                        fill=p['ink'], line_height=1.02))
    y += head_size * 1.02 * len(head_lines) + 34
    layers.append(_text('\n'.join(body_lines), margin, y, inner, line_size, weight=600, fill=p['mist'],
                        line_height=1.3))
    y += line_size * 1.3 * len(body_lines) + 64

    cta = copy['cta']
    pill_w = min(inner, len(cta) * cta_size * 0.62 + 110)
    layers.append({'kind': 'shape', 'shape': 'rect', 'x': margin, 'y': y, 'width': pill_w, 'height': pill_h,
                   'fill': p['accent'], 'radius': 48})
    layers.append(_text(cta, margin, y + 22, pill_w, cta_size, weight=800, fill=p['on_accent'], align='center'))

    foot_y = HEIGHT - 110
    layers.append({'kind': 'shape', 'shape': 'rect', 'x': margin, 'y': foot_y - 28, 'width': inner, 'height': 2,
                   'fill': p['ice'], 'opacity': 0.25})
    if footer is None:
        layers.append(_text(PLATFORM_FOOTER['label'], margin, foot_y, 520, 24, weight=800, tracking=4))
        layers.append(_text(PLATFORM_FOOTER['host'], WIDTH - margin - 400, foot_y, 400, 24, weight=600, fill=ICE,
                            align='right'))
    else:
        layers += _footer(footer, p, margin, inner, foot_y)
    return {'width': WIDTH, 'height': HEIGHT, 'title': f'{eyebrow.title()}: {copy["headline"]}'[:180],
            'background': p['bg'], 'layers': layers}


# A business's footer: its own name (left) and its own site (right), each
# sized to its width. The composer measures the real text and refuses a line
# that overflows, so these estimates lean wide: capitals in bold at 0.8 em a
# character, a host in lower case at 0.6 em.
_FOOT_SIZE, _FOOT_MIN = 24, 12
_LABEL_EM, _HOST_EM = 0.8, 0.6
_HOST_MAX_W, _HOST_MIN_W, _FOOT_GAP = 560, 240, 40


def _fit(chars, width, per_em, tracking):
    """The largest size (12 to 24) at which `chars` characters fit `width`."""
    if chars <= 0:
        return _FOOT_SIZE
    size = (width / chars - tracking) / per_em
    return max(_FOOT_MIN, min(_FOOT_SIZE, int(size)))


def _footer(footer, p, margin, inner, foot_y):
    label = ' '.join(str((footer or {}).get('label') or '').split())
    host = str((footer or {}).get('host') or '').strip().lower()
    layers = []
    # The name always fits, at worst at the smallest size; the host gets the rest.
    room = inner - (len(label) * (_FOOT_MIN * _LABEL_EM + 2) + _FOOT_GAP if label else 0)
    host_w = 0
    if host:
        host_w = int(min(_HOST_MAX_W, room, max(_HOST_MIN_W, len(host) * _FOOT_SIZE * _HOST_EM + 8)))
        size = _fit(len(host), host_w, _HOST_EM, 0) if host_w > 0 else 0
        if host_w > 0 and len(host) * size * _HOST_EM <= host_w:
            layers.append(_text(host, WIDTH - margin - host_w, foot_y, host_w, size, weight=600, fill=p['ice'],
                                align='right'))
        else:
            host_w = 0                     # too long to print whole: the name alone, never a cut-off address
    if label:
        width = inner - (host_w + _FOOT_GAP if host_w else 0)
        tracking = 4
        size = _fit(len(label), width, _LABEL_EM, tracking)
        if size < 20:
            tracking = 2
            size = _fit(len(label), width, _LABEL_EM, tracking)
        layers.append(_text(label, margin, foot_y, width, size, weight=800, fill=p['ink'], tracking=tracking))
    return layers


# ── a business's own colours ──────────────────────────────────────────

_HEX = re.compile(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
BLACK = '#000000'
DARK_INK = '#111111'
# A business with no brand colours gets a plain charcoal flyer with a warm
# light accent: nobody else's colours, Solutionist's included.
NEUTRAL_PALETTE = {'bg': '#16181D', 'bg2': '#262A33', 'accent': '#E9E3D5', 'accent2': '#E9E3D5', 'ink': WHITE,
                   'mist': '#D9DCE3', 'ice': '#E9E3D5', 'on_accent': DARK_INK}


def _color(value):
    """'#rrggbb' from a stored brand colour ('#abc', '#aabbcc' or '#aabbccdd'), or None."""
    m = _HEX.match(str(value or '').strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return '#' + h[:6].upper()


def _rgb(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(c))):02X}' for c in rgb)


def _mix(a, b, t):
    """t of the way from colour a to colour b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _luminance(hex_):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """The WCAG contrast ratio of two colours (1 to 21)."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _toward(color, target, against, ratio, steps=20):
    """Move `color` toward `target` until it reaches `ratio` against `against`."""
    for i in range(steps + 1):
        out = _mix(color, target, i / steps)
        if contrast(out, against) >= ratio:
            return out
    return target


def brand_colors(business):
    """The business's own brand colours (settings.brand_kit), checked."""
    settings = (business or {}).get('settings') if isinstance((business or {}).get('settings'), dict) else {}
    kit = settings.get('brand_kit') if isinstance(settings.get('brand_kit'), dict) else {}
    colors = kit.get('colors') if isinstance(kit.get('colors'), dict) else {}
    out = {k: _color(colors.get(k)) for k in ('primary', 'secondary', 'accent')}
    out['primary'] = out['primary'] or _color(kit.get('primary_color'))
    return {k: v for k, v in out.items() if v}


def brand_palette(colors):
    """A readable flyer palette from a business's brand colours: the primary
    darkened behind white words (7:1), the accent kept apart from the
    background, the button's words dark or light by contrast. No colours:
    NEUTRAL_PALETTE."""
    colors = colors or {}
    primary = _color(colors.get('primary'))
    if not primary:
        return dict(NEUTRAL_PALETTE)
    accent = _color(colors.get('accent')) or _color(colors.get('secondary')) or primary
    bg = _toward(primary, BLACK, WHITE, 7.0)
    bg2 = _toward(_mix(bg, primary, 0.5), BLACK, WHITE, 4.5)
    if contrast(accent, bg) < 2.0:
        accent = _toward(accent, WHITE, bg, 2.0)
    accent2 = _color(colors.get('secondary')) or accent
    on_accent = WHITE if contrast(WHITE, accent) >= 3.0 else DARK_INK
    ice = _mix(WHITE, accent, 0.3)
    ice = ice if contrast(ice, bg) >= 4.5 else WHITE
    mist = _mix(WHITE, primary, 0.15)
    mist = mist if contrast(mist, bg) >= 4.5 else WHITE
    return {'bg': bg, 'bg2': bg2, 'accent': accent, 'accent2': accent2, 'ink': WHITE, 'mist': mist, 'ice': ice,
            'on_accent': on_accent}


# ── the platform business, as the build actor ─────────────────────────

async def platform_owner():
    """Solutionist's own business and its owner: the platform_books row owned
    by the platform owner (platform_suite.books_business), never a tenant
    that flagged its own row."""
    import platform_suite
    verdict, books = await asyncio.to_thread(platform_suite.books_business)
    if verdict == platform_suite.UNKNOWN:
        raise HTTPException(503, "Solutionist's own business couldn't be confirmed just now. Try again shortly.")
    if not books:
        raise HTTPException(409, 'Set up The Solutionist System in Mission Control → Money & Website first.')
    return {'business_id': str(books['id']), 'user_id': str(books['owner_id'])}


class acting_for:
    """Bind image_studio's scoped build actor for the platform business."""

    def __init__(self, actor):
        self.actor = actor

    def __enter__(self):
        import image_studio
        self.token = image_studio.build_actor.set(self.actor)
        return self.actor

    def __exit__(self, *exc):
        import image_studio
        image_studio.build_actor.reset(self.token)


async def to_marketing_asset(client, business_id, artwork_id):
    """Copy one owned artwork into the public marketing library (Buffer and Instagram fetch it)."""
    import image_studio as images
    from starlette.datastructures import Headers, UploadFile
    row = await images.artwork(client, business_id, artwork_id)
    raw = images.normalize_image(await images.original(client, row))
    aid = uuid5(NAMESPACE_URL, f'platform-marketing:{business_id}:{artwork_id}')
    return await marketing.save_asset(UploadFile(filename=f'Weekly plan flyer {str(artwork_id)[:8]}.png',
                                                 file=io.BytesIO(raw), headers=Headers({'content-type': 'image/png'})),
                                      asset_id=aid)


async def compose_flyer(client, actor, run_id, slot, copy, hero_id=None):
    """Render one flyer and return its marketing asset. Shrinks the type if a line overflows."""
    import chief_flyer_composer as composer
    biz = {'id': actor['business_id']}
    last = None
    for attempt, scale in enumerate((1.0, 0.88, 0.78, 0.68)):
        try:
            layout = flyer_layout(slot['play_id'], copy, hero_id=hero_id, scale=scale)
            request_id = uuid5(run_id, f"flyer:{slot['slot']}:{hero_id or 'flat'}:{attempt}")
            result = await composer.compose(client, biz, {'layout': layout}, request_id)
            return await to_marketing_asset(client, actor['business_id'], result['image']['id'])
        except HTTPException as exc:
            last = exc
            if exc.status_code != 422:
                raise
    raise last


# ── the budget ────────────────────────────────────────────────────────

def _month_start(now):
    return now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def budget_state(now=None):
    """This month's design budget and what the plan has spent from it.

    Spend is read from the artwork rows the plan itself made (their recorded
    provider cost), never estimated. A hero image with no recorded cost yet
    counts at its estimate, so an unfinished job cannot hide from the total."""
    now = now or marketing.now()
    cfg = await marketing.config()
    budget = float(cfg.get('design_budget_usd') if cfg.get('design_budget_usd') is not None else DEFAULT_BUDGET_USD)
    since = _month_start(now).isoformat().replace('+00:00', 'Z')
    runs = await marketing.db('GET', f'/platform_marketing_runs?created_at=gte.{since}&select=design&limit=10')
    heroes = [r['design']['hero_id'] for r in runs if (r.get('design') or {}).get('hero_id')]
    spent = 0.0
    if heroes:
        ids = ','.join(str(UUID(h)) for h in heroes)
        rows = await marketing.db('GET', f'/image_artworks?id=in.({ids})&select=id,cost_usd,status')
        seen = {r['id']: r for r in rows}
        for h in heroes:
            cost = (seen.get(h) or {}).get('cost_usd')
            spent += float(cost) if cost is not None else HERO_ESTIMATE_USD
    return {'budget_usd': round(budget, 2), 'spent_usd': round(spent, 2),
            'left_usd': round(max(0.0, budget - spent), 2), 'month': _month_start(now).strftime('%Y-%m'),
            'hero_estimate_usd': HERO_ESTIMATE_USD}


async def make_hero(client, actor, run_id, play):
    """Start one generated image and wait for it. Returns its artwork id, or None if it did not finish."""
    import image_studio as images
    request = images.CreateImage(business_id=UUID(actor['business_id']), request_id=uuid5(run_id, f'hero:{play}'),
                                 prompt=hero_prompt(play), quality='medium', size='1024x1536')
    row = await images.create(request, client)
    image_id = row['id']
    for _ in range(HERO_WAIT_SECONDS // 5):
        current = await images.artwork(client, actor['business_id'], image_id)
        if current['status'] == 'ready':
            return image_id
        if current['status'] == 'failed':
            return None
        await asyncio.sleep(5)
    return None


async def design_week(run_id, slots, copies, lead_play):
    """Flyers for every slot that has flyer copy, with one hero image on the
    lead play when the budget covers it. Returns ({slot: asset}, design record)."""
    budget = await budget_state()
    design = {'budget': budget, 'hero_id': None, 'request': None, 'flyers': {}, 'failed': []}
    actor = await platform_owner()
    hero_id = None
    with acting_for(actor):
        async with httpx.AsyncClient(timeout=60) as client:
            if lead_play and budget['left_usd'] >= HERO_ESTIMATE_USD:
                try:
                    hero_id = await make_hero(client, actor, run_id, lead_play)
                    design['hero_id'] = str(hero_id) if hero_id else None
                except HTTPException as exc:
                    design['failed'].append({'what': 'hero image', 'reason': str(exc.detail)[:200]})
            elif lead_play:
                design['request'] = {'needed_usd': HERO_ESTIMATE_USD, 'left_usd': budget['left_usd'],
                                     'budget_usd': budget['budget_usd'],
                                     'reason': 'This week\'s lead post would carry a photograph, and the design budget for '
                                               'the month is used up. The flyers went out without one.'}
            assets = {}
            for slot in slots:
                copy = copies.get(slot['slot'])
                if not copy:
                    continue
                try:
                    use_hero = hero_id if slot['play_id'] == lead_play else None
                    asset = await compose_flyer(client, actor, run_id, slot, copy, use_hero)
                    assets[slot['slot']] = asset
                    design['flyers'][str(slot['slot'])] = asset['id']
                except Exception as exc:
                    log.warning('marketing design: flyer for slot %s failed', slot['slot'], exc_info=True)
                    design['failed'].append({'what': f"flyer {slot['slot']}",
                                             'reason': str(getattr(exc, 'detail', 'render failed'))[:200]})
    return assets, design
