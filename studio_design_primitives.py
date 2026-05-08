"""Design primitives library — reference patterns Builder draws from per strand.

These are NOT templates. They are creative-director-grade pattern
descriptions that expand Builder's creative space. Builder reads them,
then makes its own structural decisions.

Each strand has 3-5 distinctive patterns with concrete spatial logic.
SECTION_PACING_PATTERNS holds 7 rhythmic templates the Designer Agent
can pick from.
"""
from __future__ import annotations
from typing import TypedDict


class LayoutPrimitive(TypedDict):
    name: str
    description: str
    spatial_logic: str
    when_to_use: str


HERO_PRIMITIVES_BY_STRAND: dict[str, list[LayoutPrimitive]] = {
    "luxury": [
        {
            "name": "Lower-Third Headline",
            "description": "Headline sits at 65-70% of viewport height. Vast empty space above. Single eyebrow at top-left. CTA appears with extreme spacing below headline.",
            "spatial_logic": "Silence first. Content arrives after the eye has rested. Reader is held in space before being addressed.",
            "when_to_use": "When the brand has nothing to prove. When patience is the message.",
        },
        {
            "name": "Asymmetric Pull-Quote Companion",
            "description": "Headline left at 40-45% width. Pull-quote in italic serif right at 50% width with thin gold rule between. Both sit on lower 60% of viewport. Generous breathing room.",
            "spatial_logic": "Two voices in dialogue — declaration and reflection. Gold rule is the threshold between them.",
            "when_to_use": "When tension statement has weight. When the brand wants to feel like editorial more than advertisement.",
        },
        {
            "name": "Single-Word Display Cascade",
            "description": "Three words stacked — each its own line, each at 7-9rem display weight. Final word in accent color. Reads vertically like a manifesto. CTA tiny and unobtrusive at bottom.",
            "spatial_logic": "Words have weight. The cascade slows the eye. Restraint elsewhere makes the typography breathe.",
            "when_to_use": "When the brand statement is short and definitive. When confidence reads as restraint.",
        },
        {
            "name": "Watermark Backdrop",
            "description": "Massive thin-stroke ornament (gold rule diamond, four-point star) sits at 20% opacity behind the headline. Hero content is centered but the watermark is offset slightly right.",
            "spatial_logic": "Heritage signal. The mark is older than the page. Content sits inside its quiet authority.",
            "when_to_use": "When the brand draws on lineage, ceremony, or institutional weight.",
        },
    ],
    "editorial": [
        {
            "name": "Magazine Front-Of-Book",
            "description": "Top strip with publication name + issue date in small caps. Headline below in large display serif, often italic. Subhead in lighter weight beneath. Drop cap on first paragraph of body. Asymmetric grid splits page into 65/35.",
            "spatial_logic": "The page IS a magazine spread. Reader is positioned as someone reading something edited, not browsing a website.",
            "when_to_use": "Always for editorial-dominant. Default unless specifically pivoting to portfolio or essay.",
        },
        {
            "name": "Letter-From-The-Editor",
            "description": "Numbered first section ('No. 01 — A Letter'). Drop cap. Body in narrower column (max 50ch). Signature at bottom in italic with name + title. Feels personally addressed.",
            "spatial_logic": "Voice is intimate. Reader is addressed directly by a specific person. Hierarchy comes from the letter framing, not from headlines.",
            "when_to_use": "When the practitioner's individual voice is the offering. Coaches, advisors, writers.",
        },
        {
            "name": "Pull-Quote Spread",
            "description": "Massive pull-quote (3-4rem italic serif) takes upper third with thin rule below. Body copy continues underneath in two narrower columns. Quote is the visual anchor.",
            "spatial_logic": "Type IS the illustration. The pull-quote performs the work an image would in another strand.",
            "when_to_use": "When tension statement is the most quotable thing about the brand.",
        },
        {
            "name": "Numbered Department Index",
            "description": "Sections introduced as I, II, III, IV in roman numerals at the start of each section. Section titles in display serif, body in disciplined columns. Page reads like a table of contents made physical.",
            "spatial_logic": "Structure is visible. Each section earns its place by being numbered. Hierarchy is editorial, not promotional.",
            "when_to_use": "When the practice has multiple distinct components and order matters.",
        },
    ],
    "minimal": [
        {
            "name": "Single Sentence Hero",
            "description": "One sentence. Centered. Display weight. Surrounded by extreme negative space — the sentence occupies maybe 30% of viewport. Tiny CTA below. Nothing else above the fold.",
            "spatial_logic": "Negative space IS the design. The reduction is the message.",
            "when_to_use": "When the brand can defend not adding more. When confidence is removal.",
        },
        {
            "name": "Diagram-First",
            "description": "A single primitive geometric diagram (line, circle, three dots) anchors the hero. Headline is small and offset. The diagram IS the brand.",
            "spatial_logic": "Reduction to essential form. The geometry holds attention through restraint.",
            "when_to_use": "When the practice is conceptual — design, strategy, philosophy.",
        },
        {
            "name": "Wordmark + Whitespace",
            "description": "Practitioner or brand name at small-but-precise display weight, centered, at exactly 50% viewport height. Nothing else. Below the fold the page begins gently with single-paragraph sections.",
            "spatial_logic": "The brand name itself is the hero. Everything else is consequence.",
            "when_to_use": "When the practitioner's name carries the practice. Established voices.",
        },
    ],
    "dark": [
        {
            "name": "Cinematic Single-Source Glow",
            "description": "Deep black background. One radial light source (gold or cool-blue) in upper third creates atmospheric pool. Headline lives in the light. Body in cool gray below. Feels like a film still.",
            "spatial_logic": "Light is directional. Reader's eye follows the glow. Atmosphere precedes content.",
            "when_to_use": "Premium experiential brands. Dramatic statements. Performance practices.",
        },
        {
            "name": "Vignette Approach",
            "description": "Frame closes inward at edges. Center of viewport holds content with high contrast. Edges are darker than center. Like looking through glass at something intentional.",
            "spatial_logic": "Compression at edges focuses attention. Reader feels positioned, not addressed.",
            "when_to_use": "When the brand traffics in attention, presence, ceremony.",
        },
        {
            "name": "Dual-Tone Stack",
            "description": "Two horizontal bands. Top band black with gold accent typography. Bottom band slightly lighter (true charcoal, not black) holds body text. The break between is the page's structural bone.",
            "spatial_logic": "Tonal shift IS the section break. No rules needed. The dark itself is structure.",
            "when_to_use": "When the brand is film-like, layered, made of moods.",
        },
    ],
    "bold": [
        {
            "name": "Type-As-Illustration",
            "description": "Headline at 12-15rem, fills viewport horizontally. Letterforms break into multiple colors or are subtly tilted. The type IS the image.",
            "spatial_logic": "Type carries visual weight that imagery would in other strands. Energy comes from scale.",
            "when_to_use": "When the brand is loud and proud. Creative-confident practices.",
        },
        {
            "name": "Color-Block Split",
            "description": "Hero divided into two halves with diagonal or vertical color block. Headline lives on one side, image or pull-quote on other. Bold contrast between halves.",
            "spatial_logic": "Conflict creates energy. The split IS the brand.",
            "when_to_use": "When the practice positions itself in contrast (old vs new, expected vs actual).",
        },
        {
            "name": "Ornamental Maximalism",
            "description": "Headline anchored center but surrounded by smaller orbiting text elements (eyebrows, taglines, decorative marks) at varying angles. Dense without chaos.",
            "spatial_logic": "Multiple anchors compete deliberately. The page rewards looking longer.",
            "when_to_use": "When the brand has multiple stories to tell at once.",
        },
    ],
    "organic": [
        {
            "name": "Earth-Toned Wash",
            "description": "Soft radial gradient in warm sage/terracotta/ochre. Curves replace borders throughout. Headline in display serif sits centered with generous padding. Photos have soft edges or rounded crops.",
            "spatial_logic": "Nothing terminates sharply. The page breathes naturally, like a printed paper.",
            "when_to_use": "Wellness, ceremony, slow-craft brands. Anything where warmth is the proof.",
        },
        {
            "name": "Hand-Crafted Asymmetry",
            "description": "Slight imperfections deliberate — sections offset 3-5%, photos slightly rotated, lines not perfectly straight. Feels made by hand, not designed by software.",
            "spatial_logic": "Imperfection signals authorship. The hand of the maker is visible in the layout.",
            "when_to_use": "When the practice is hand-craft adjacent. Therapy, coaching, artisan practices.",
        },
        {
            "name": "Botanical Frame",
            "description": "Subtle leaf or vine motifs at 8-12% opacity frame the hero. Content lives inside the botanical frame. Color is warm earth — sage, ochre, burgundy.",
            "spatial_logic": "Content is held by nature. The frame is gentle but present.",
            "when_to_use": "Healing practices, nature-adjacent brands, regenerative work.",
        },
    ],
    "corporate": [
        {
            "name": "Authority Stack",
            "description": "Eyebrow with practice category in small caps. Headline below in serif at moderate scale (not maximalist). Body block in disciplined column. Single CTA in navy or gold. Right margin holds a small kicker — credentials, year established, proof point.",
            "spatial_logic": "Hierarchy is precise and unambiguous. Reader knows exactly what to read first, second, third.",
            "when_to_use": "Default for corporate-dominant. Especially advisory practices, financial, legal.",
        },
        {
            "name": "Structured Two-Column",
            "description": "Page divided 60/40. Left column: practice positioning + CTA. Right column: vertical band with practitioner photo OR a credentials list (years, clients, outcomes). Thin gold rule between columns.",
            "spatial_logic": "Two columns make the practice feel institutional. Information is organized like a prospectus.",
            "when_to_use": "When credentials and outcomes matter more than story.",
        },
        {
            "name": "Letterhead Open",
            "description": "Top of page resembles a corporate letterhead: practitioner name + title in small caps, fine rule beneath, date or location stamped right. Hero content begins below the letterhead in a new visual zone.",
            "spatial_logic": "The page is positioned as official correspondence. Reader is addressed formally.",
            "when_to_use": "When the practice deals in formality — legal, advisory, fiduciary.",
        },
    ],
    "playful": [
        {
            "name": "Rounded Optimism",
            "description": "Soft rounded rectangles hold sections. Bright colors (saturated but not garish). Friendly display font with personality. Generous padding everywhere. CTAs as rounded pills.",
            "spatial_logic": "Approachability is the design language. Nothing is sharp. Everything invites participation.",
            "when_to_use": "Creative, lifestyle, accessible practices. Things where friendliness is positioning.",
        },
        {
            "name": "Illustration-First",
            "description": "Custom illustration takes 50%+ of hero. Headline is small and supportive. The illustration carries personality.",
            "spatial_logic": "Visual character does the work. Type plays second fiddle.",
            "when_to_use": "Brands with strong visual identity — illustrators, children's services, creative classes.",
        },
    ],
    "retrotech": [
        {
            "name": "Terminal Frame",
            "description": "Hero looks like a terminal window — fixed-width font, scanline overlay at 4% opacity, cursor blink. Headline in green-on-black or amber-on-black. Content reads like code commentary.",
            "spatial_logic": "Page is a system the reader is operating inside.",
            "when_to_use": "Tech-adjacent practices, dev tooling, technical advisory.",
        },
        {
            "name": "Blueprint Grid",
            "description": "Grid lines are visible at 6% opacity. Coordinates noted at corners. Content sits inside the blueprint. Type is monospace. Page feels engineered, not designed.",
            "spatial_logic": "Construction is visible. Reader sees the structural intent.",
            "when_to_use": "Engineering, technical writing, systems work.",
        },
    ],
    "brutalist": [
        {
            "name": "Raw Borders",
            "description": "Hard 4-6px borders frame everything. Black on white or vice versa. No gradients, no shadows, no rounded corners. Headlines hit hard at full viewport width. Type is functional sans (Helvetica, Arial, system fonts).",
            "spatial_logic": "Decoration rejected. Content is everything. The structure is the design.",
            "when_to_use": "Anti-establishment brands, conceptual practices, design-aware audiences.",
        },
        {
            "name": "Information Density",
            "description": "Hero is dense — multiple text blocks, registration marks, version numbers, timestamps, all visible simultaneously. Reader must work to read.",
            "spatial_logic": "Density rewards attention. Reader is positioned as participant, not consumer.",
            "when_to_use": "When the practice values rigor over polish.",
        },
    ],
}


SECTION_PACING_PATTERNS: dict[str, str] = {
    "compression-release": "Tight, content-dense sections alternate with vast quiet sections. The contrast IS the rhythm. Eye is guided through pulses of activity and rest.",
    "building-momentum": "Each section is slightly more dense than the last. Page builds energy as reader scrolls. Final section is the loudest.",
    "circular": "Page returns to themes from the hero in the closing section. Sense of completion through repetition with variation.",
    "essay-arc": "Setup -> tension -> development -> resolution. Sections follow narrative beats, not feature categories.",
    "cathedral": "Hero is grand. Middle sections are progressively quieter. Final CTA is again grand. Sandwich structure.",
    "list-form": "Page is a sequence of clearly-numbered or named beats. Each section is distinct. No narrative arc - pure inventory.",
    "two-act": "Hero + manifesto opens. Then a structural break (statement bar, divider). Practice/offerings/CTA close. Two distinct movements.",
}


def get_primitives_for_strand(strand_id: str) -> list[LayoutPrimitive]:
    """Return hero primitives for a strand. Empty list if strand unknown."""
    return HERO_PRIMITIVES_BY_STRAND.get(strand_id, [])


def get_pacing_description(pacing_id: str) -> str:
    """Return description of a pacing pattern. Empty string if unknown."""
    return SECTION_PACING_PATTERNS.get(pacing_id, "")


def all_pacing_ids() -> list[str]:
    return list(SECTION_PACING_PATTERNS.keys())
