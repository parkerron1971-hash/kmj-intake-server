"""10 style strands ported verbatim from Studio's TypeScript.

Strand DNA + spatialDNA strings are creative-director-grade descriptions.
Do NOT paraphrase. The Designer Agent prompt relies on these strings as-is.
"""
from __future__ import annotations
from typing import TypedDict, Optional


class StyleStrand(TypedDict):
    id: str
    name: str
    desc: str
    swatches: list[str]
    dna: str
    spatialDNA: str


STYLE_STRANDS: list[StyleStrand] = [
    {
        "id": "editorial",
        "name": "Editorial",
        "desc": "Type-led, magazine grid, stark contrast",
        "swatches": ["#0a0a0a", "#f4f4f4", "#d62828", "#888888"],
        "dna": "Editorial/Magazine: Typographic hierarchy is the primary design tool — large display type sets the rhythm, body text follows in disciplined columns. Asymmetric grid creates editorial tension. Stark color contrast — usually black, white, and one accent color used with restraint. Pull-quotes and rule lines structure the page. The page reads like a well-designed magazine spread. Influence: New York Times Magazine, Apartamento, T Magazine, Wallpaper.",
        "spatialDNA": "Type drives space. Headlines occupy large typographic real estate while body text sits in narrower columns — the asymmetry IS the design. Sections are bordered by thin rule lines. Pull-quotes break grid rhythm intentionally. The eye moves through hierarchy: headline → subhead → body → detail, never flat.",
    },
    {
        "id": "luxury",
        "name": "Luxury",
        "desc": "Refined whitespace, gold, serif elegance",
        "swatches": ["#0d0c0a", "#C9A84C", "#e8dfc8", "#6b5d40"],
        "dna": "Luxury/Refined: Negative space is the primary design element — content arrives after silence, not before it. Gold appears once per section like a watch catching light during a handshake — never decorative, always meaningful. Copy is unhurried and ceremonial — longer sentences that trust the reader. Thin serif display type at light weight creates refinement without aggression. Nothing competes for attention — one focal element per zone. The page communicates that the brand has nothing to prove. Influence: Louis Vuitton, Porsche, Four Seasons, Bottega Veneta.",
        "spatialDNA": "Content arrives after space. Headlines sit in the lower third of hero sections, not centered — silence comes first. Sections are vast and unhurried. A single element per focal zone — never competing anchors. Gold appears once per section, like a detail you notice on second look. Margins are so generous they feel architectural. The page breathes slowly.",
    },
    {
        "id": "bold",
        "name": "Bold / Maximalist",
        "desc": "High energy, layered, loud type",
        "swatches": ["#FF3D00", "#FFEB3B", "#1A1A1A", "#FFFFFF"],
        "dna": "Bold/Maximalist: Type IS the illustration — massive scale, often filling the viewport. High contrast color blocking creates energy zones. Rule-breaking layouts that feel intentional, not chaotic. Multiple strong elements compete and create visual tension. The brand confidence reads as a kind of joyful aggression. Influence: Pentagram, Nike campaigns, Wonka-era branding, Glossier launch posters.",
        "spatialDNA": "Multiple anchors compete for attention deliberately. Type at maximum scale — sometimes spilling off the canvas. Color blocks define zones and CTA energy. Layouts break grids on purpose — but the breaks feel composed. Density is high, but readability is preserved through hierarchy and color contrast.",
    },
    {
        "id": "minimal",
        "name": "Minimal",
        "desc": "Silence as design, precision spacing",
        "swatches": ["#FFFFFF", "#000000", "#F5F5F5", "#888888"],
        "dna": "Minimal: Negative space is the design. Ultra-clean grid. A single focal element per section — restraint in everything. Type is sparing, weights chosen with precision. Color used at minimal saturation. The brand communicates clarity and confidence by removing rather than adding. Influence: Muji, Aesop, Apple product pages, Kinfolk.",
        "spatialDNA": "Almost everything is space. Content arrives in small, deliberate moments — a headline, a single paragraph, a single product image. Sections are vast and quiet. Alignment is precise. Hierarchy comes from position and scale, not from decoration. The page feels like a single careful sentence per breath.",
    },
    {
        "id": "dark",
        "name": "Dark / Cinematic",
        "desc": "Deep bg, glowing accents",
        "swatches": ["#0a0a0a", "#1a1a1a", "#FFD700", "#4A4A4A"],
        "dna": "Dark/Cinematic: Deep backgrounds — often black or near-black — with glowing accent colors that feel like they emit light. Atmospheric depth created through subtle gradients and shadow. Cinematic pacing — sections feel like film scenes. Type often sits in tension with dark space. Influence: Netflix prestige drama, Apple keynote staging, Stüssy, Yeezy launches.",
        "spatialDNA": "Sections feel cinematic — like scenes in a film. Background is deep, foreground glows. Light is directional — accent colors feel emitted, not painted. Pacing is unhurried, with dramatic transitions between sections. Generous letting between elements creates atmospheric depth.",
    },
    {
        "id": "organic",
        "name": "Organic",
        "desc": "Curves, natural tones, texture-rich",
        "swatches": ["#a8d5ba", "#f4a261", "#264653", "#e9c46a"],
        "dna": "Organic/Natural: Flowing curves over hard edges. Earthy palette — sage, terracotta, ochre, deep forest. Tactile textures — paper grain, hand-drawn elements, photographs of natural light. Type often has soft personality. The brand communicates groundedness and authenticity. Influence: Aesop, Loewe, ban.do, hand-letterers in the Brooklyn ceramic scene.",
        "spatialDNA": "Curves replace hard borders. Sections flow into each other rather than terminating. Asymmetry feels intuitive, not engineered. Layouts have hand-made quality — slight imperfection creates warmth. Photography or illustration carries weight that geometry would in other strands.",
    },
    {
        "id": "retrotech",
        "name": "Retro-Tech",
        "desc": "Terminal, grid-based, nostalgic edge",
        "swatches": ["#00FF00", "#000000", "#FFB000", "#FFFFFF"],
        "dna": "Retro-Tech: Monospace type. Terminal aesthetics — green-on-black, amber-on-black, or grayscale with technical accents. Visible grid structure. Nostalgic edge that references early computing, BBS culture, ASCII art. Type and content feel like they exist inside a system. Influence: Are.na, early Apple, Linear, Rhino.",
        "spatialDNA": "Grid is visible — not hidden. Layouts feel constructed inside a system, with deliberate edges and registration marks. Monospace creates rhythm. Margins are tight and technical. Negative space is structured, not vast.",
    },
    {
        "id": "corporate",
        "name": "Corporate Elite",
        "desc": "Authority, power, institutional trust",
        "swatches": ["#0d2742", "#C9A84C", "#FFFFFF", "#5d6975"],
        "dna": "Corporate Elite: Navy authority. Gold accents for status signal. Structured grid — institutional confidence. Serif display for legacy, clean sans for body. The brand projects established power, not new energy. Type is restrained and precise. Influence: Goldman Sachs, McKinsey, Hermès business division, private banks.",
        "spatialDNA": "Structure is visible. Grid is precise and disciplined. Whitespace is generous but intentional — never wasted. Hierarchy is clear: brand mark, primary message, supporting elements, in that order. Sections are bounded by subtle rule lines.",
    },
    {
        "id": "playful",
        "name": "Playful",
        "desc": "Rounded, vibrant, expressive type",
        "swatches": ["#FF69B4", "#00CED1", "#FFD700", "#9370DB"],
        "dna": "Playful/Vibrant: Rounded shapes, bright palette, joyful energy, accessible. Type often bouncing between weights — expressive and human. Colors saturated and warm. The brand invites participation rather than commanding respect. Influence: ban.do, Casper, Glossier, Mailchimp.",
        "spatialDNA": "Shapes have rounded corners. Layouts feel approachable and human — sections invite participation. Color is generous. Type is friendly. Margins are warm but not stiff. Animation is bouncy and welcoming.",
    },
    {
        "id": "brutalist",
        "name": "Brutalist",
        "desc": "Raw, unconventional, visible structure",
        "swatches": ["#000000", "#FFFFFF", "#FF0000", "#888888"],
        "dna": "Brutalist: Raw structure visible. Hard borders. Stark contrast. Confrontational, anti-decoration. Type is functional, often grotesque or system fonts. The brand rejects polish in favor of intent. Pure information design with attitude. Influence: Are.na's earliest design, Rio Olympics, Balenciaga, art world bookmark sites.",
        "spatialDNA": "Structure is visible and aggressive. Borders are hard. Grid is rigid. Whitespace exists but it feels earned, not given. Type is functional. Layouts confront the user with content density. Decoration is rejected.",
    },
]


def get_strand(strand_id: str) -> Optional[StyleStrand]:
    for s in STYLE_STRANDS:
        if s["id"] == strand_id:
            return s
    return None


STRAND_IDS = [s["id"] for s in STYLE_STRANDS]
