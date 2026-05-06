"""30 sub-strands ported verbatim from Studio's TypeScript.

Source: solutionist-studio/src/lib/design/subStrands.ts
3 sub-strands per parent strand × 10 parent strands = 30 total.

Sub-strand fields drive the Brief Expander (Pass 3.8b) and refine the
parent strand's flavor (warm/cool/neutral temperature, signatureDetail
that becomes a CSS treatment).
"""
from __future__ import annotations
from typing import TypedDict, Literal, Optional


class SubStrand(TypedDict):
    id: str
    parentStrandId: str
    name: str
    description: str
    temperature: Literal["warm", "cool", "neutral"]
    colorDirection: str
    typographyDirection: str
    spatialDirection: str
    heroLayout: str
    signatureDetail: str
    exampleBrands: str


SUB_STRANDS: list[SubStrand] = [
    # ── LUXURY ───────────────────────────────────────────────────────────
    {
        "id": "luxury-warm",
        "parentStrandId": "luxury",
        "name": "Warm Luxury",
        "temperature": "warm",
        "description": "Spa, boutique hotel aesthetic — gold, cream, and blush tones with generous whitespace and centered layouts",
        "colorDirection": "Gold, ivory, soft blush, warm undertones",
        "typographyDirection": "Serif display (light weight), rounded sans body",
        "spatialDirection": "Generous padding, floating elements, centered alignment",
        "heroLayout": "centered-single-column",
        "signatureDetail": "Gold accent lines that bookend headings — ::before and ::after horizontal rules flanking the text, width: 48px, height: 1px, accent color",
        "exampleBrands": "Four Seasons, Aesop, Le Labo",
    },
    {
        "id": "luxury-cold",
        "parentStrandId": "luxury",
        "name": "Cold Luxury",
        "temperature": "cool",
        "description": "Jeweler, gallery aesthetic — silver, white, and slate with sharp geometry and left-aligned layouts",
        "colorDirection": "Silver, cool white, slate gray, no warm tones",
        "typographyDirection": "Thin sans-serif display (200-300 weight), geometric body",
        "spatialDirection": "Sharp geometry, left-aligned content, precise spacing",
        "heroLayout": "left-aligned",
        "signatureDetail": "Thin 1px border frames around images and sections — every visual element sits inside a precise rectangular frame",
        "exampleBrands": "Cartier, White Cube Gallery, COS",
    },
    {
        "id": "luxury-noir",
        "parentStrandId": "luxury",
        "name": "Noir Luxury",
        "temperature": "cool",
        "description": "Nightlife, high fashion — pure black with one vivid accent color used with extreme restraint",
        "colorDirection": "Pure black background, one vivid accent (electric blue, hot pink, or neon), no warm tones",
        "typographyDirection": "Condensed display font, tight leading, uppercase transforms",
        "spatialDirection": "Full-bleed images, tight spacing, accent used only once per viewport",
        "heroLayout": "full-bleed",
        "signatureDetail": "Accent color used on ONLY one element per viewport — extreme restraint makes each accent moment command attention",
        "exampleBrands": "Saint Laurent, Berghain, Tom Ford",
    },

    # ── BRUTALIST ────────────────────────────────────────────────────────
    {
        "id": "brutalist-raw",
        "parentStrandId": "brutalist",
        "name": "Raw Brutalist",
        "temperature": "neutral",
        "description": "Construction, industrial — exposed structure, monospace everything, visible grid, system colors",
        "colorDirection": "Black, white, system red. No gradients, no softness",
        "typographyDirection": "Monospace for everything — display, body, labels",
        "spatialDirection": "Visible grid lines, elements touch containers, nothing floats free",
        "heroLayout": "left-aligned",
        "signatureDetail": "Border on every element — nothing floats free. Every div, card, and image has a visible 2px border. Structure is the aesthetic",
        "exampleBrands": "Bloomberg Terminal, Craigslist redesigned",
    },
    {
        "id": "brutalist-neo",
        "parentStrandId": "brutalist",
        "name": "Neo Brutalist",
        "temperature": "neutral",
        "description": "Art school, gallery — intentional ugly-beautiful with mixed typefaces and controlled chaos",
        "colorDirection": "High contrast with one unexpected color. Black + white + bright yellow or red",
        "typographyDirection": "Mixed typefaces — serif and sans-serif in the same headline. Rule-breaking by design",
        "spatialDirection": "Overlapping elements, intentional misalignment, asymmetric grid",
        "heroLayout": "left-aligned",
        "signatureDetail": "One element intentionally misaligned or rotated 2-4 degrees — a card, image, or text block that breaks the grid on purpose",
        "exampleBrands": "Balenciaga web, Virgil Abloh exhibits",
    },
    {
        "id": "brutalist-type",
        "parentStrandId": "brutalist",
        "name": "Type Brutalist",
        "temperature": "neutral",
        "description": "Typography-obsessed — giant text IS the layout, no images, words fill the viewport",
        "colorDirection": "Two colors only — background and text. No accent. Monochrome extremity",
        "typographyDirection": "Display at 15vw+. Type fills the container edge to edge. Body text is tiny by contrast",
        "spatialDirection": "Type IS the spatial element. Whitespace between letters, not between sections",
        "heroLayout": "statement",
        "signatureDetail": "H1 at 15vw+ — the headline IS the hero. No image, no subtext needed. The typography fills the viewport",
        "exampleBrands": "Studio Dumbar, Experimental Jetset",
    },

    # ── EDITORIAL ────────────────────────────────────────────────────────
    {
        "id": "editorial-magazine",
        "parentStrandId": "editorial",
        "name": "Magazine Editorial",
        "temperature": "warm",
        "description": "Classic magazine spread — columns, drop caps, pull quotes, serif-heavy, structured but elegant",
        "colorDirection": "Warm paper tones, dark text, muted accent, aged paper feel",
        "typographyDirection": "Serif display (Playfair, Cormorant), serif body (Lora, Libre Baskerville), monospace accent",
        "spatialDirection": "Multi-column layout, pull-quotes breaking columns, generous line-height",
        "heroLayout": "centered",
        "signatureDetail": "Drop cap on the first paragraph — ::first-letter styled at 4x size with accent color, float:left, line-height:0.8",
        "exampleBrands": "Monocle, Kinfolk, Cereal Magazine",
    },
    {
        "id": "editorial-newspaper",
        "parentStrandId": "editorial",
        "name": "Newspaper Editorial",
        "temperature": "cool",
        "description": "News layout — multi-column grid, dense but organized, small type, lots of content visible at once",
        "colorDirection": "White background, black text, one accent for links/highlights. High contrast, no decoration",
        "typographyDirection": "Compact sans-serif body (14px or less), bold serif headlines, monospace for data",
        "spatialDirection": "Dense multi-column grid, visible column rules, information-first layout",
        "heroLayout": "left-aligned",
        "signatureDetail": "Visible column rules — 1px vertical dividers between grid columns creating a newspaper feel",
        "exampleBrands": "NYT, Financial Times, The Outline",
    },
    {
        "id": "editorial-portfolio",
        "parentStrandId": "editorial",
        "name": "Portfolio Editorial",
        "temperature": "neutral",
        "description": "Showcase-first — large images with captions, minimal text, the work speaks, clean navigation",
        "colorDirection": "Neutral backgrounds (off-white or very dark), images provide all color",
        "typographyDirection": "Clean sans display, monospace captions against serif body — type contrast signals different content roles",
        "spatialDirection": "Full-width images, narrow caption columns, generous vertical spacing between projects",
        "heroLayout": "full-bleed",
        "signatureDetail": "Image captions in a different typeface than body — monospace captions (font-family: var(--font-accent)) against serif body text",
        "exampleBrands": "Pentagram, Studio Feixen",
    },

    # ── DARK ─────────────────────────────────────────────────────────────
    {
        "id": "dark-atmospheric",
        "parentStrandId": "dark",
        "name": "Atmospheric Dark",
        "temperature": "warm",
        "description": "Fog, depth, mystery — gradients that bleed, multiple layers of translucency, cinematic depth",
        "colorDirection": "Deep near-black (#080b12), muted accent (teal, violet), multiple surface layers at 2-4% opacity",
        "typographyDirection": "Sans-serif display with text-shadow glow, light-weight body text",
        "spatialDirection": "Layered z-axis depth, overlapping semi-transparent sections, no hard edges",
        "heroLayout": "centered",
        "signatureDetail": "Multiple overlapping radial-gradients creating a deep atmospheric field — at least 3 gradient layers at different positions and sizes behind content",
        "exampleBrands": "A24 Films, Spotify Wrapped",
    },
    {
        "id": "dark-neon",
        "parentStrandId": "dark",
        "name": "Neon Dark",
        "temperature": "cool",
        "description": "Cyberpunk, tech — one bright neon accent on pure black, clean sans-serif, high contrast, glowing elements",
        "colorDirection": "Pure black (#000), one neon accent (electric green, hot pink, cyan), no mid-tones",
        "typographyDirection": "Clean geometric sans-serif display, monospace accents, no serifs anywhere",
        "spatialDirection": "Clean geometry, generous spacing, accent glow creates visual hierarchy",
        "heroLayout": "centered",
        "signatureDetail": "Neon text-shadow glow on one headline — text-shadow: 0 0 20px accent, 0 0 60px accent, 0 0 120px accent at decreasing opacity",
        "exampleBrands": "MKBHD, Razer, Cyberpunk 2077",
    },
    {
        "id": "dark-film",
        "parentStrandId": "dark",
        "name": "Film Dark",
        "temperature": "warm",
        "description": "Cinematic widescreen — letterbox proportions, warm amber tones, film grain texture, auteur feel",
        "colorDirection": "Near-black with warm undertone (#1a1410), amber/sepia accent, desaturated warm palette",
        "typographyDirection": "Elegant serif display (light weight), classic proportions, generous leading",
        "spatialDirection": "Widescreen proportions, content centered in a narrow horizontal band, cinematic framing",
        "heroLayout": "full-bleed",
        "signatureDetail": "Aspect-ratio: 21/9 on hero images — cinematic widescreen crop that immediately signals film-grade quality",
        "exampleBrands": "Christopher Nolan sites, Roger Deakins",
    },

    # ── MINIMAL ──────────────────────────────────────────────────────────
    {
        "id": "minimal-warm",
        "parentStrandId": "minimal",
        "name": "Warm Minimal",
        "temperature": "warm",
        "description": "Japanese-inspired — warm neutrals, off-whites, natural materials feel, soft, inviting restraint",
        "colorDirection": "Warm off-white (#f5f0e8), warm gray text, one warm accent (terracotta, sage)",
        "typographyDirection": "Clean sans-serif display (light weight), generous letter-spacing, warm body text",
        "spatialDirection": "Generous padding, centered alignment, rounded corners (8-12px) on everything",
        "heroLayout": "centered",
        "signatureDetail": "Rounded corners on everything — border-radius: 8-12px on all containers, cards, images, and buttons. Softness is structural",
        "exampleBrands": "Muji, Kinfolk, Snow Peak",
    },
    {
        "id": "minimal-cold",
        "parentStrandId": "minimal",
        "name": "Cold Minimal",
        "temperature": "cool",
        "description": "Swiss design — pure geometry, no warmth, grid-based, Helvetica energy, high information density",
        "colorDirection": "Pure white (#fff), pure black text, one primary color accent (blue or red), zero warmth",
        "typographyDirection": "Helvetica/Inter/Suisse (geometric sans-serif), strict weight hierarchy, no serifs",
        "spatialDirection": "Visible grid structure, precise spacing, mathematical proportions",
        "heroLayout": "left-aligned",
        "signatureDetail": "Visible grid lines at extremely low opacity (2%) creating an underlying mathematical structure that is felt but barely seen",
        "exampleBrands": "Swiss Style reboot, Dieter Rams",
    },
    {
        "id": "minimal-void",
        "parentStrandId": "minimal",
        "name": "Void Minimal",
        "temperature": "neutral",
        "description": "Almost nothing — one color, one typeface, maximum whitespace, the page is mostly empty",
        "colorDirection": "One background color, one text color. No accent. No variation. Two colors total",
        "typographyDirection": "One typeface, two weights only. Display and body are the same family",
        "spatialDirection": "Content occupies less than 30% of viewport height on any scroll position. Vast emptiness",
        "heroLayout": "minimal-text",
        "signatureDetail": "Content occupies less than 30% of viewport — vast emptiness is the design. Most of the screen is intentionally blank",
        "exampleBrands": "Apple product pages, Nothing Phone",
    },

    # ── BOLD ─────────────────────────────────────────────────────────────
    {
        "id": "bold-pop",
        "parentStrandId": "bold",
        "name": "Pop Bold",
        "temperature": "warm",
        "description": "Bright, saturated, energetic — multiple accent colors, rounded shapes, billboard that is fun",
        "colorDirection": "Multiple bright colors (3-4 accent colors), saturated, warm undertones",
        "typographyDirection": "Rounded sans-serif display (bold/black weight), friendly body text",
        "spatialDirection": "Rounded containers, pill shapes everywhere, generous but not vast padding",
        "heroLayout": "centered",
        "signatureDetail": "border-radius: 999px on buttons AND section containers — everything is a pill or blob, no sharp corners anywhere",
        "exampleBrands": "Mailchimp, Slack, Headspace",
    },
    {
        "id": "bold-brutalist-pop",
        "parentStrandId": "bold",
        "name": "Brutalist Pop",
        "temperature": "neutral",
        "description": "Bold meets brutalist — thick borders plus bright colors plus large type, structured energy",
        "colorDirection": "Bright primary colors (yellow, red, blue) with black borders. Poster aesthetic",
        "typographyDirection": "Heavy sans-serif display (900 weight), clean geometric body, uppercase headers",
        "spatialDirection": "Thick 4px+ borders on cards and sections, structured grid, visible frames",
        "heroLayout": "left-aligned",
        "signatureDetail": "4px+ borders on cards and sections — thick, visible, structural frames in bright colors. The border IS the design",
        "exampleBrands": "Gumroad, Notion early, Figma marketing",
    },
    {
        "id": "bold-statement",
        "parentStrandId": "bold",
        "name": "Statement Bold",
        "temperature": "neutral",
        "description": "One massive message per section — not many sections, each is one sentence at billboard scale",
        "colorDirection": "High contrast, minimal palette. Background and text are the design",
        "typographyDirection": "Display at 8-15vw. Each section is one sentence. The type IS the content",
        "spatialDirection": "Sections are viewport-height with one centered statement per section. Scroll = new statement",
        "heroLayout": "statement",
        "signatureDetail": "Viewport-height sections with ONE centered statement each — scroll reveals new statements, like Apple keynote slides as a website",
        "exampleBrands": "Apple keynote slides as a website",
    },

    # ── PLAYFUL ──────────────────────────────────────────────────────────
    {
        "id": "playful-warm",
        "parentStrandId": "playful",
        "name": "Warm Playful",
        "temperature": "warm",
        "description": "Friendly, approachable, rounded — soft pastels plus one vibrant accent, hand-drawn feel",
        "colorDirection": "Soft pastels (light pink, mint, lavender) + one vibrant accent. Warm and inviting",
        "typographyDirection": "Rounded sans-serif display, friendly body text with generous line-height",
        "spatialDirection": "Generous padding, off-center elements, nothing perfectly aligned",
        "heroLayout": "centered",
        "signatureDetail": "Subtle rotation on hover — transform: rotate(1-3deg) on cards and images. Nothing is perfectly straight. Adds personality",
        "exampleBrands": "Duolingo, Notion, Figma community",
    },
    {
        "id": "playful-retro",
        "parentStrandId": "playful",
        "name": "Retro Playful",
        "temperature": "warm",
        "description": "70s/80s revival — rounded serif fonts, warm earth tones, groovy curves, nostalgic but modern",
        "colorDirection": "Warm earth tones (terracotta, mustard, olive, burnt orange), retro palette",
        "typographyDirection": "Rounded serif display (Cooper, Recoleta style), clean sans body",
        "spatialDirection": "Wavy borders, rounded sections, organic flow between content zones",
        "heroLayout": "centered",
        "signatureDetail": "Wavy SVG borders on sections — section dividers are organic wave shapes, not straight lines",
        "exampleBrands": "Mailchimp rebrand, Figma Config",
    },
    {
        "id": "playful-illustrated",
        "parentStrandId": "playful",
        "name": "Illustrated Playful",
        "temperature": "warm",
        "description": "Illustration-forward — design accommodates artwork, large SVG zones, storybook feel",
        "colorDirection": "Bright but not neon. Colors that work WITH illustrations, not competing",
        "typographyDirection": "Friendly display font, clean body text, decorative accents possible",
        "spatialDirection": "Large illustration zones between sections, generous whitespace around art",
        "heroLayout": "split",
        "signatureDetail": "Decorative SVG elements scattered between sections — small stars, squiggles, arrows, dots as visual punctuation between content zones",
        "exampleBrands": "Dropbox rebrand, Intercom",
    },

    # ── ORGANIC ──────────────────────────────────────────────────────────
    {
        "id": "organic-earth",
        "parentStrandId": "organic",
        "name": "Earth Organic",
        "temperature": "warm",
        "description": "Natural materials, earth tones, grounded — textured backgrounds, serif warmth, tactile feel",
        "colorDirection": "Earth tones (warm browns, deep greens, sand, clay). Desaturated but warm",
        "typographyDirection": "Warm serif display (italic for emphasis), natural body text with generous line-height",
        "spatialDirection": "Organic spacing (not mathematical), flowing sections, gentle curves",
        "heroLayout": "centered",
        "signatureDetail": "Subtle CSS noise texture overlay on backgrounds — a very faint grain using SVG filter or tiny repeating gradient for tactile quality",
        "exampleBrands": "Patagonia, Allbirds",
    },
    {
        "id": "organic-botanical",
        "parentStrandId": "organic",
        "name": "Botanical Organic",
        "temperature": "warm",
        "description": "Green-forward — growth imagery, lighter and more air, botanical illustration energy",
        "colorDirection": "Green accent always (sage, forest, emerald), light warm background, botanical palette",
        "typographyDirection": "Light serif display, airy body text, accent font for labels",
        "spatialDirection": "Airy layout, lots of whitespace, content breathes",
        "heroLayout": "centered",
        "signatureDetail": "Accent color is always a natural green regardless of other choices — green is the botanical signature that grounds every design",
        "exampleBrands": "Aesop, The Body Shop",
    },
    {
        "id": "organic-handmade",
        "parentStrandId": "organic",
        "name": "Handmade Organic",
        "temperature": "warm",
        "description": "Craft, artisan, imperfect beauty — mixed fonts suggesting hand-lettering, warm, intimate",
        "colorDirection": "Warm cream background, dark brown text, hand-made feel in color choices",
        "typographyDirection": "Mixed fonts suggesting hand-lettering, slightly decorative display, warm body",
        "spatialDirection": "Slightly uneven spacing, organic rhythm, not perfectly aligned",
        "heroLayout": "centered",
        "signatureDetail": "Slightly uneven letter-spacing on headings — alternating 0.02em and 0.05em creating a hand-set type feel, as if placed by a letterpress",
        "exampleBrands": "Etsy seller pages, local bakeries",
    },

    # ── RETROTECH ────────────────────────────────────────────────────────
    {
        "id": "retrotech-terminal",
        "parentStrandId": "retrotech",
        "name": "Terminal Retrotech",
        "temperature": "cool",
        "description": "Pure terminal — green or amber on black, monospace only, blinking cursor, command-line aesthetic",
        "colorDirection": "Green (#39ff14) or amber (#ff8c00) on pure black. Terminal palette only",
        "typographyDirection": "Monospace everything. No serif, no sans-serif. Terminal only",
        "spatialDirection": "Fixed-width content columns, terminal-style padding (48px), text-only layouts",
        "heroLayout": "left-aligned",
        "signatureDetail": "Blinking cursor after the hero headline — animation: blink 1s step-end infinite, border-right: 2px solid accent",
        "exampleBrands": "Cool Retro Term, Hackerman memes made real",
    },
    {
        "id": "retrotech-vaporwave",
        "parentStrandId": "retrotech",
        "name": "Vaporwave Retrotech",
        "temperature": "warm",
        "description": "80s/90s nostalgia — purple, pink, cyan gradient backgrounds, grid overlays, retro-futurism",
        "colorDirection": "Purple to pink to cyan gradient spectrum. Sunset colors. Neon undertones",
        "typographyDirection": "Retro display fonts (blocky, geometric), clean sans body, neon glow effects",
        "spatialDirection": "Grid background overlays, centered content, gradient backgrounds as primary design element",
        "heroLayout": "centered",
        "signatureDetail": "Linear-gradient background going through 3+ colors (sunset spectrum) — the multi-color gradient IS the primary design element",
        "exampleBrands": "Vaporwave aesthetics, Synthwave album covers",
    },
    {
        "id": "retrotech-blueprint",
        "parentStrandId": "retrotech",
        "name": "Blueprint Retrotech",
        "temperature": "cool",
        "description": "Technical drawing aesthetic — blue/white, grid lines, precise measurements, engineering feel",
        "colorDirection": "Blueprint blue (#1a3a5c) background, white lines and text. Technical palette",
        "typographyDirection": "Monospace for labels, clean sans for content, annotation-style captions",
        "spatialDirection": "Grid background, annotation labels pointing to elements, precise measurement markers",
        "heroLayout": "left-aligned",
        "signatureDetail": "Dashed borders and annotation-style labels — small monospace text with dashed connector lines pointing to elements, like technical blueprints",
        "exampleBrands": "Engineering documentation, NASA identity",
    },

    # ── CORPORATE ────────────────────────────────────────────────────────
    {
        "id": "corporate-authority",
        "parentStrandId": "corporate",
        "name": "Authority Corporate",
        "temperature": "cool",
        "description": "Law firm, finance — dark navy plus gold, serif headlines, conservative layout, institutional trust",
        "colorDirection": "Dark navy (#001f4e), gold accent (#c8a94a), light surface (#f0f4fa). Conservative",
        "typographyDirection": "Serif headlines (weight 600), sans-serif body, structured hierarchy",
        "spatialDirection": "12-column grid, structured sections, justified alignment options, conservative spacing",
        "heroLayout": "split",
        "signatureDetail": "Very subtle pinstripe background — 1px repeating-linear-gradient at 1% opacity with 20px spacing, creating a fabric-like texture",
        "exampleBrands": "Goldman Sachs, White & Case",
    },
    {
        "id": "corporate-modern",
        "parentStrandId": "corporate",
        "name": "Modern Corporate",
        "temperature": "neutral",
        "description": "Tech company, SaaS — light background, blue accent, sans-serif everything, clean and approachable",
        "colorDirection": "Light/white background, blue accent (#4A90D9), subtle gray surfaces. Clean and modern",
        "typographyDirection": "Geometric sans-serif for everything (Inter, Plus Jakarta Sans), medium weights",
        "spatialDirection": "Clean grid, generous whitespace, rounded corners (8px), card-based layouts",
        "heroLayout": "split",
        "signatureDetail": "Gradient accent on CTAs — linear-gradient from slightly darker to slightly lighter in the accent color, creating a polished button feel",
        "exampleBrands": "Stripe, Linear, Vercel",
    },
    {
        "id": "corporate-institutional",
        "parentStrandId": "corporate",
        "name": "Institutional Corporate",
        "temperature": "cool",
        "description": "University, hospital, government — structured, hierarchical, information-dense, accessible",
        "colorDirection": "Accessible blue or dark red accent, white/light gray background, high contrast required",
        "typographyDirection": "Readable sans-serif (system fonts or highly legible web fonts), strict hierarchy",
        "spatialDirection": "Information-dense, structured navigation, clear section hierarchy, breadcrumbs",
        "heroLayout": "left-aligned",
        "signatureDetail": "Visible breadcrumb/section navigation showing exactly where you are in the page structure — always visible, always orienting",
        "exampleBrands": "MIT, Mayo Clinic, gov.uk",
    },
]


def get_substrand(substrand_id: str) -> Optional[SubStrand]:
    for s in SUB_STRANDS:
        if s["id"] == substrand_id:
            return s
    return None


def get_substrands_for_parent(parent_id: str) -> list[SubStrand]:
    return [s for s in SUB_STRANDS if s["parentStrandId"] == parent_id]


SUBSTRAND_IDS = [s["id"] for s in SUB_STRANDS]
