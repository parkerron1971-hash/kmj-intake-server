"""
workspace_identity.py — what a vertical LOOKS like, in one place.

WHY THIS EXISTS

There were two answers to "what colour is a law firm". The desk said
gold (`SKINS.lawyer.accent = #c9a227`). The composer preset said blue
(`theme.dark.accent = #3b82f6`). Same business, two brands, decided by
which screen you happened to open. That was true for SEVEN OF SEVEN
verticals — ministry was gold on one surface and teal on the other.

Worse, the presets overrode two deliberate refusals. `personal_services`
and `nonprofit` carry NO accent on the desk, with a written reason: a
salon owner and a charity both arrive with a brand they did not ask us
to overpaint, and the desk showing up in a colour we picked "read as a
product that had not been told". The composer painted them orange and
pink anyway.

So identity lives here now, once, and both surfaces read it.

WHY IT IS MORE THAN A COLOUR

The old preset themes carried a thirteen-key palette each — and NINE of
those keys were byte-identical across all seven verticals. Ground,
surface, raised, hover, ink, muted, faint, border, border_subtle: the
same. Only the accent and its two tints moved. "Unique per vertical"
meant one hue swapped on one template, which is exactly why the seven
layouts looked like each other.

A hue is the weakest possible differentiator. What actually makes a
salon floor feel unlike a law docket is STRUCTURE: how tightly packed
the rows are, how hard the corners are, whether surfaces are separated
by a rule or a fill, how heavy the figures sit. Those are the fields
below, and they are why two verticals sharing an accent still do not
look alike.

Every field is expressible as a CSS custom property, so the ONE engine
still renders all seven and the vertical still lives in data.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# ─── the three display faces ─────────────────────────────────────────
# Capped at three, matching the desk's own rule: "so it stays a system
# and not a font collection." The presets had drifted to five named
# faces, which is a font collection.
# These are the DESK'S OWN families, read out of desk.css rather than
# chosen here — the whole point of this module is that there is one
# answer, so inventing a second set of faces would have rebuilt the
# problem it exists to fix.
#
# One correction to the desk while carrying it across: `geometric` maps
# to `Futura, Century Gothic, Avenir Next` with NO web font behind it.
# Futura is not on Windows and Avenir Next is macOS-only, so a Windows
# practitioner silently gets Century Gothic — a fallback nobody chose.
# `Outfit` is already loaded by the app, so putting it at the front
# costs nothing and closes the gap for both surfaces.
FACES = {
    "serif":     "'Fraunces', Georgia, 'Times New Roman', serif",
    "grotesque": "'Inter Tight', Inter, 'Helvetica Neue', Arial, sans-serif",
    "geometric": "'Outfit', Futura, 'Century Gothic', 'Avenir Next', sans-serif",
}

# ─── structural vocabularies ─────────────────────────────────────────
# Each maps to CSS custom properties. A vertical picks one value from
# each; the combination is what makes it recognisable at a glance with
# the colour removed.

DENSITY = {
    # row height, section gap, base type size
    "tight":   {"row": "34px", "gap": "10px", "pad": "10px 12px", "size": "13px"},
    "regular": {"row": "42px", "gap": "16px", "pad": "13px 16px", "size": "14px"},
    "airy":    {"row": "54px", "gap": "26px", "pad": "18px 22px", "size": "15px"},
}

EDGE = {
    # corner radius and the weight of a separating line
    "soft":  {"radius": "14px", "hair": "1px", "weight": "400"},
    "even":  {"radius": "8px",  "hair": "1px", "weight": "500"},
    "hard":  {"radius": "3px",  "hair": "2px", "weight": "600"},
}

RULE = {
    # how one surface is told apart from the next
    "hairline": "a one-pixel line, and nothing else",
    "filled":   "a raised fill, no line",
    "none":     "space alone",
}

TEXTURE = {
    "none":  None,
    "grid":  "a faint square grid, 22px",
    "hatch": "45-degree hatching, the same fill the trades board already "
             "uses for travel time",
    "paper": "a soft vertical wash, like a printed order of service",
}

COMPOSITIONS = {
    # THE PAGE ITSELF -- not decoration on a shared page.
    #
    # This is the field that was missing, and its absence is why seven
    # verticals looked like one. Architecture used to be DERIVED from
    # whichever primitive led the layout, and seven verticals share only
    # three lead primitives: salon and trades were literally the same
    # page, therapist and ministry were the same page. Padding and radius
    # cannot rescue that. Two businesses can both need a day-timeline and
    # still need completely different rooms around it.
    #
    # So a vertical CHOOSES its page. Each of these is a different
    # skeleton -- different grid, different chrome, different hero,
    # different place for Chief -- and the engine reads it like every
    # other field.
    "floor": {
        "grid": "full-bleed, single working surface, secondaries as a "
                "bottom strip",
        "hero": "none",
        "chief": "below",
        "why": "Read standing up, mid-shift, from three feet away between "
               "clients. Anything competing with the board is noise, "
               "including a headline number.",
    },
    "console": {
        "grid": "two columns -- working surface, and a live queue rail "
                "that never scrolls away",
        "hero": "bar",
        "chief": "below",
        "why": "A dispatcher has the phone in one hand. The board answers "
               "'where is everyone' and the rail answers 'what still has "
               "nobody' -- both have to be true at once or the job is two "
               "screens.",
    },
    "retreat": {
        "grid": "one centred column, one card at a time, wide margins",
        "hero": "quiet",
        "chief": "below",
        "why": "Read alone between sessions by someone who has been "
               "holding other people's difficulty all morning. A grid of "
               "tiles is a demand. One column is a page.",
    },
    "almanac": {
        "grid": "the week full width, then a ruled three-column programme",
        "hero": "stacked",
        "chief": "right",
        "why": "A week that gets planned together and often printed. It "
               "wants the manners of an order of service: columns, rules, "
               "and a rhythm you can follow down the page.",
    },
    "pipeline": {
        "grid": "stages across, scrolling sideways, stage rail pinned left",
        "hero": "wide",
        "chief": "below",
        "why": "Capacity is a shape in TIME. Stacked vertically it reads "
               "as a list of clients; laid across it reads as a full "
               "month beside an empty one, which is the actual problem.",
    },
    "register": {
        "grid": "dense ruled rows on a baseline, marginalia in the left "
                "margin",
        "hero": "stacked",
        "chief": "left",
        "why": "Obligations to funders are a ledger, and a ledger is read "
               "by running a finger down a column. Cards would break the "
               "alignment that makes that possible.",
    },
    "document": {
        "grid": "a single reading measure, centred, generous leading",
        "hero": "stacked",
        "chief": "right",
        "why": "A docket is a document of consequences, so it gets a "
               "document's manners rather than a dashboard's. Full width "
               "would turn a filing calendar into a spreadsheet.",
    },
}


FIGURE = {
    # how the big numbers sit
    "light":   {"weight": "300", "track": "-.03em"},
    "regular": {"weight": "600", "track": "-.02em"},
    "heavy":   {"weight": "800", "track": "-.04em"},
}


def _id(*, mark: str, display: str, line: str, composition: str,
        density: str, edge: str, rule: str, texture: str, figure: str,
        accent: Optional[Dict[str, str]] = None,
        accent2: Optional[Dict[str, str]] = None,
        why: str = "") -> Dict[str, Any]:
    assert display in FACES, display
    assert composition in COMPOSITIONS, composition
    assert density in DENSITY and edge in EDGE, (density, edge)
    assert rule in RULE and texture in TEXTURE and figure in FIGURE
    return {
        "mark": mark, "display": display, "line": line,
        "composition": composition,
        "accent": accent, "accent2": accent2,
        "density": density, "edge": edge, "rule": rule,
        "texture": texture, "figure": figure, "why": why,
    }


IDENTITIES: Dict[str, Dict[str, Any]] = {

    "personal_services": _id(
        # NO ACCENT, and that is the point. Carried over from the desk
        # verbatim: a salon owner has already chosen how their brand
        # looks, and arriving in a colour we picked over the top of that
        # reads as a product that had not been told. The preset used to
        # impose #ff6b35 here.
        accent=None, accent2=None,
        composition="floor",
        mark="Scissors", display="geometric",
        line="Look good. Feel amazing.",
        density="tight", edge="soft", rule="filled", texture="none",
        figure="light",
        why="The day is sold in fifteen-minute slots, so the board is the "
            "densest of the seven — an airy salon screen would show half a "
            "morning. Soft corners and filled surfaces because this is a "
            "styled room, not a worksite, and light figures because the "
            "numbers are not the point: the gaps are.",
    ),

    "contractor": _id(
        accent={"dark": "#f59e0b", "light": "#9a6207"},
        accent2={"dark": "#fcd34d", "light": "#7c4f05"},
        composition="console",
        mark="Wrench", display="grotesque",
        line="Let's build.",
        density="regular", edge="hard", rule="hairline", texture="hatch",
        figure="heavy",
        why="The only hard-edged desk of the seven. Three-pixel radii and "
            "two-pixel rules because a dispatch board is a worksite "
            "instrument, not a document — and heavy figures because the "
            "money numbers are the ones that get shouted across a van. The "
            "hatching is already the language for travel time here, so it "
            "carries to the ground rather than being invented.",
    ),

    "therapist": _id(
        accent={"dark": "#5fbf9b", "light": "#1f7a5c"},
        accent2={"dark": "#8fe0c2", "light": "#155e45"},
        composition="retreat",
        mark="Leaf", display="serif",
        line="You hold space. We handle the rest.",
        density="airy", edge="soft", rule="none", texture="none",
        figure="light",
        why="The airiest of the seven, and deliberately the quietest: this "
            "screen is read between sessions by someone who has been "
            "holding other people's difficulty all morning. Space instead "
            "of rules, soft corners, light figures. Nothing on it should "
            "raise a pulse.",
    ),

    "ministry": _id(
        accent={"dark": "#e0a63c", "light": "#8f6412"},
        accent2={"dark": "#f6d488", "light": "#74510e"},
        composition="almanac",
        mark="Church", display="serif",
        line="People first. Kingdom always.",
        density="airy", edge="soft", rule="hairline", texture="paper",
        figure="regular",
        why="A week runs to a rhythm rather than a clock, so the grid gets "
            "room to breathe. The paper wash is the one texture that reads "
            "as an order of service rather than as decoration, and it is "
            "what separates this from the nonprofit desk at a glance — the "
            "two are otherwise the closest pair.",
    ),

    "consultant": _id(
        accent={"dark": "#22a4e0", "light": "#0f6c9c"},
        accent2={"dark": "#7dd3fc", "light": "#0b5478"},
        composition="pipeline",
        mark="Compass", display="grotesque",
        line="Clarity first, then delivery.",
        density="regular", edge="even", rule="hairline", texture="grid",
        figure="regular",
        why="The grid is the tell. A consultant sells booked capacity, and "
            "the failure is a full month beside an empty one — a ruled "
            "ground makes the shape of the pipeline legible before a word "
            "is read.",
    ),

    "coach": _id(
        accent={"dark": "#a855f7", "light": "#7028c7"},
        accent2={"dark": "#d8b4fe", "light": "#5a1ea3"},
        composition="register",
        mark="TrendingUp", display="grotesque",
        line="Impact is planned.",
        density="regular", edge="even", rule="filled", texture="none",
        figure="regular",
        why="Shares the consultant's capacity bands and its face, so the "
            "separation has to come from structure: filled surfaces and no "
            "grid, because a coach's spine is a ROSTER of people rather "
            "than a schedule, and people read better on cards than on "
            "ruled paper.",
    ),

    "nonprofit": _id(
        # NO ACCENT, same refusal as the salon. A charity arrives with a
        # brand it did not choose us to override. The preset imposed
        # #f472b6.
        accent=None, accent2=None,
        composition="register",
        mark="HeartHandshake", display="grotesque",
        line="Mission first. Every gift accounted for.",
        density="regular", edge="even", rule="hairline", texture="none",
        figure="regular",
        why="Grotesque rather than the ministry's serif, because a serif "
            "next to a church icon reads ecclesiastical and separating "
            "the two verticals is the entire reason this desk exists. No "
            "texture for the same reason: the ministry took the paper.",
    ),

    "lawyer": _id(
        accent={"dark": "#c9a227", "light": "#8a6a15"},
        accent2={"dark": "#e8c96a", "light": "#6d5310"},
        composition="document",
        mark="Scale", display="serif",
        line="Justice is in the details.",
        density="airy", edge="even", rule="filled", texture="none",
        figure="regular",
        why="A docket is a document, so it gets a document's manners: a "
            "serif, generous leading, and rows separated by fill rather "
            "than by lines, because a page of ruled rows reads as a "
            "spreadsheet and this is a calendar of consequences.",
    ),
}

# The composer's archetype names and the desk's businesses.type names are
# two different namespaces for the same seven rooms. This is the only
# place they meet, and it is deliberately explicit rather than derived by
# string munging — `salon` and `personal_services` share no substring.
ARCHETYPE_TO_IDENTITY = {
    "salon": "personal_services",
    "trades": "contractor",
    "therapist": "therapist",
    "ministry": "ministry",
    "consultant": "consultant",
    "nonprofit": "nonprofit",
    "law_firm": "lawyer",
}


def for_archetype(archetype: str) -> Optional[Dict[str, Any]]:
    key = ARCHETYPE_TO_IDENTITY.get(archetype)
    return IDENTITIES.get(key) if key else None


def for_vertical(vertical: Optional[str]) -> Optional[Dict[str, Any]]:
    return IDENTITIES.get((vertical or "").strip().lower())


def tokens(archetype: str, *, dark: bool = True) -> Dict[str, str]:
    """The identity as CSS custom properties.

    This is the whole hybrid in one function: the engine renders every
    vertical the same way and reads these to know what the room is. A
    vertical that defers its accent simply does not emit one, and the
    surface keeps the practitioner's own.
    """
    ident = for_archetype(archetype)
    if not ident:
        return {}

    d = DENSITY[ident["density"]]
    e = EDGE[ident["edge"]]
    f = FIGURE[ident["figure"]]
    out = {
        "--wk-face": FACES[ident["display"]],
        "--wk-row": d["row"], "--wk-gap": d["gap"],
        "--wk-pad": d["pad"], "--wk-size": d["size"],
        "--wk-radius": e["radius"], "--wk-hair": e["hair"],
        "--wk-weight": e["weight"],
        "--wk-fig-weight": f["weight"], "--wk-fig-track": f["track"],
        "--wk-rule": ident["rule"],
        "--wk-texture": ident["texture"],
    }
    accent = ident.get("accent")
    if accent:
        out["--wk-accent"] = accent["dark" if dark else "light"]
        a2 = ident.get("accent2")
        if a2:
            out["--wk-accent2"] = a2["dark" if dark else "light"]
    return out


def describe() -> Dict[str, Dict[str, Any]]:
    return {a: dict(for_archetype(a) or {}, archetype=a)
            for a in ARCHETYPE_TO_IDENTITY}
