"""Solutionist Studio's deterministic design data, ported from TypeScript.

Source files in solutionist-studio/src/lib/design/ and src/lib/.
Each section below corresponds to one TS source file. When in doubt,
the TypeScript IS the spec.

This module contains ONLY data. Pure functions live in:
  - studio_composite.py
  - studio_design_system.py
  - studio_vocab_detect.py
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


# ─── TYPES ────────────────────────────────────────────────────────────────

VocabularySection = Literal[
    "cultural-identity",
    "community-movement",
    "life-stage",
    "aesthetic-movement",
]


class ColorPalette(TypedDict):
    primary: str
    secondary: str
    accent: str
    background: str
    text: str


class CulturalVocabulary(TypedDict):
    id: str
    name: str
    section: VocabularySection
    signal_words: List[str]
    color_philosophy: str
    color_palette: ColorPalette
    typography_direction: str
    imagery_style: str
    energy: str
    layout_affinity: List[str]
    real_world_references: List[str]
    detection_signals: List[str]


class LayoutStyle(TypedDict):
    id: str
    name: str
    description: str
    vocabulary_affinity: List[str]
    generation_prompt: str
    structure_notes: str
    section_order: List[str]


class FontPairing(TypedDict):
    """Mirrors src/lib/design/fontLibrary.ts:FontPairing."""

    id: str
    name: str
    heading_font: str
    body_font: str
    heading_weight: str
    body_weight: str
    google_fonts_url: str
    feel: str
    vocabulary_match: List[str]
    layout_match: List[str]
    css_variables: Dict[str, str]
    sample_heading_style: str
    sample_body_style: str


class StyleStrand(TypedDict):
    """Mirrors src/lib/strandConstants.ts:STYLE_STRANDS entries."""

    id: str
    name: str
    desc: str
    swatches: List[str]
    dna: str
    spatial_dna: str


# ─── VOCABULARIES — port from culturalVocabularies.ts ──────────────────

VOCABULARIES: Dict[str, CulturalVocabulary] = {
    # ─── SECTION 1: CULTURAL IDENTITY ───────────────────────────────
    "expressive-vibrancy": {
        "id": "expressive-vibrancy",
        "name": "Expressive Vibrancy",
        "section": "cultural-identity",
        "signal_words": [
            "bold", "colorful", "unapologetic", "celebratory", "authentic",
            "sisterhood", "natural", "queen", "glow", "melanin",
        ],
        "color_philosophy": "Bold unapologetic color. Rich jewel tones mixed with warm earth tones. Color as celebration not decoration. Never washed out.",
        "color_palette": {
            "primary": "#8B1A4A",
            "secondary": "#2D1B69",
            "accent": "#F4A261",
            "background": "#FFF8F0",
            "text": "#1A1A1A",
        },
        "typography_direction": "Strong confident headings with personality. Warm rounded sans-serif for body. Type should feel alive not corporate.",
        "imagery_style": "Authentic representation. Natural light. Joy and community present. Skin tones celebrated. Real not staged.",
        "energy": "Warm, welcoming, powerful, affirming, celebratory",
        "layout_affinity": ["magazine", "celebration", "gallery"],
        "real_world_references": [
            "Essence Magazine", "Fenty Beauty", "natural hair brands", "Black women wellness",
        ],
        "detection_signals": [
            "beauty", "wellness", "natural hair", "sisterhood", "melanin",
            "glow", "queen", "empowerment", "women of color", "Black women",
        ],
    },
    "sovereign-authority": {
        "id": "sovereign-authority",
        "name": "Sovereign Authority",
        "section": "cultural-identity",
        "signal_words": [
            "royal", "powerful", "composed", "premium", "legacy",
            "excellence", "kingdom", "empire", "built", "earned",
        ],
        "color_philosophy": "Deep rich backgrounds. Navy, forest green, burgundy, or black. Gold or bronze as the accent — wealth signal. Never cheap or flashy.",
        "color_palette": {
            "primary": "#1A1A2E",
            "secondary": "#16213E",
            "accent": "#C9A84C",
            "background": "#0F0F1A",
            "text": "#F5F5F0",
        },
        "typography_direction": "Bold commanding headings. Either strong serif for legacy feel or sharp modern sans for power. Nothing weak or decorative.",
        "imagery_style": "Sharp high contrast. Aspirational but grounded. Power without trying too hard. Excellence in frame.",
        "energy": "Composed, authoritative, premium, earned, legacy",
        "layout_affinity": ["throne", "authority", "clean-launch"],
        "real_world_references": [
            "luxury menswear", "Black Wall Street aesthetic", "private equity", "executive presence",
        ],
        "detection_signals": [
            "consulting", "executive", "leadership", "empire", "legacy",
            "luxury", "premium", "authority", "professional services",
            "Black men", "men of color",
        ],
    },
    "warm-community": {
        "id": "warm-community",
        "name": "Warm Community",
        "section": "cultural-identity",
        "signal_words": [
            "familia", "warmth", "trust", "celebration", "heritage",
            "handcrafted", "together", "roots", "generational", "heart",
        ],
        "color_philosophy": "Warm and vibrant. Terracotta, warm reds, gold, deep greens. Colors that feel like a home-cooked meal. Inviting always.",
        "color_palette": {
            "primary": "#C0392B",
            "secondary": "#E67E22",
            "accent": "#F1C40F",
            "background": "#FDF6EC",
            "text": "#2C1810",
        },
        "typography_direction": "Expressive but readable. Mix of warm display font for headings and clean sans for body. Feels handmade not corporate.",
        "imagery_style": "Family and community present. Food, celebration, people together. Warm light. Authentic moments.",
        "energy": "Warm, trustworthy, celebratory, community-rooted, generational",
        "layout_affinity": ["community-hub", "story-arc", "celebration"],
        "real_world_references": [
            "family restaurants", "Latino-owned businesses", "heritage brands", "community markets",
        ],
        "detection_signals": [
            "familia", "family", "community", "heritage", "homemade",
            "traditional", "generations", "Latino", "Hispanic", "culture",
        ],
    },
    "cultural-fusion": {
        "id": "cultural-fusion",
        "name": "Cultural Fusion",
        "section": "cultural-identity",
        "signal_words": [
            "between worlds", "layered", "rich", "complex", "both-and",
            "global", "hybrid", "bridging", "multidimensional",
        ],
        "color_philosophy": "Unexpected color combinations that honor multiple traditions. Rich layering. Nothing should feel like one thing.",
        "color_palette": {
            "primary": "#2E4057",
            "secondary": "#8B4513",
            "accent": "#DAA520",
            "background": "#F8F4EE",
            "text": "#1A1A1A",
        },
        "typography_direction": "Mix of cultural type influences. Heading that feels rooted, body that feels global. The combination tells the story.",
        "imagery_style": "Multiple worlds present. Cultural markers honored. Layered and rich visually.",
        "energy": "Complex, layered, global, rooted, multidimensional",
        "layout_affinity": ["magazine", "experience", "gallery"],
        "real_world_references": [
            "Afropolitan brands", "multicultural media", "diaspora businesses",
        ],
        "detection_signals": [
            "multicultural", "mixed", "diaspora", "global", "between cultures",
            "international", "fusion", "hybrid identity",
        ],
    },
    "diaspora-modern": {
        "id": "diaspora-modern",
        "name": "Diaspora Modern",
        "section": "cultural-identity",
        "signal_words": [
            "Afropolitan", "global", "sophisticated", "rooted", "worldly",
            "refined", "continental", "pan-African", "elevated", "cosmopolitan",
        ],
        "color_philosophy": "Rich earth tones meeting modern sophistication. Kente-inspired accent colors used with restraint. Never costumey — always elevated.",
        "color_palette": {
            "primary": "#2C1810",
            "secondary": "#8B6914",
            "accent": "#E8A020",
            "background": "#FAF7F2",
            "text": "#1A1208",
        },
        "typography_direction": "Modern and sophisticated. Clean geometric sans with strong weight contrast. Global feel with cultural roots.",
        "imagery_style": "Elevated African and Caribbean aesthetics. Fashion-forward. Architecture and landscape of the diaspora. Aspirational and authentic.",
        "energy": "Sophisticated, rooted, worldly, elevated, proud",
        "layout_affinity": ["magazine", "throne", "authority"],
        "real_world_references": [
            "OkayAfrica", "Afropunk", "African luxury brands", "diaspora media",
        ],
        "detection_signals": [
            "African", "Caribbean", "Nigerian", "Ghanaian", "Jamaican",
            "pan-African", "continental", "diaspora",
        ],
    },
    "asian-excellence": {
        "id": "asian-excellence",
        "name": "Asian Excellence",
        "section": "cultural-identity",
        "signal_words": [
            "precision", "harmony", "balance", "mastery", "honor",
            "craft", "discipline", "refined", "intentional", "generational",
        ],
        "color_philosophy": "Balance and harmony in color. Either clean minimal with one bold accent, or rich traditional tones used with precision. Nothing accidental.",
        "color_palette": {
            "primary": "#1A1A2E",
            "secondary": "#C41E3A",
            "accent": "#FFD700",
            "background": "#FAFAFA",
            "text": "#1A1A1A",
        },
        "typography_direction": "Precise and intentional. Clean geometric for modern feel or elegant serif for traditional feel. Perfect spacing.",
        "imagery_style": "Precision and craft visible. Clean compositions. Mastery shown not told. Harmony in every frame.",
        "energy": "Precise, harmonious, masterful, intentional, honorable",
        "layout_affinity": ["clean-launch", "authority", "magazine"],
        "real_world_references": [
            "Japanese brand design", "Korean beauty brands", "South Asian luxury", "tech excellence",
        ],
        "detection_signals": [
            "Asian", "Japanese", "Korean", "Chinese", "South Asian",
            "Indian", "precision", "harmony", "mastery", "craft",
        ],
    },
    "indigenous-earth": {
        "id": "indigenous-earth",
        "name": "Indigenous Earth-Rooted",
        "section": "cultural-identity",
        "signal_words": [
            "land", "ancestors", "cycles", "natural", "ceremonial",
            "sacred", "healing", "medicine", "community", "stewardship",
        ],
        "color_philosophy": "Earth pulled directly from the land. Terracotta, sage, clay, stone, sky. Nothing synthetic. Every color has meaning.",
        "color_palette": {
            "primary": "#8B4513",
            "secondary": "#556B2F",
            "accent": "#DAA520",
            "background": "#F5F0E8",
            "text": "#2C1810",
        },
        "typography_direction": "Organic and warm. Hand-drawn feel where appropriate. Readable and grounded. Never cold or corporate.",
        "imagery_style": "Land and nature present. Ceremonial elements honored. Community and ceremony. Earth textures and natural materials.",
        "energy": "Sacred, grounded, cyclical, communal, healing",
        "layout_affinity": ["community-hub", "story-arc", "organic"],
        "real_world_references": [
            "Indigenous artisan brands", "earth medicine practices", "land stewardship orgs",
        ],
        "detection_signals": [
            "Indigenous", "Native", "tribal", "land", "ancestors",
            "ceremonial", "medicine", "earth", "sacred", "healing land",
        ],
    },
    "universal-premium": {
        "id": "universal-premium",
        "name": "Universal Premium",
        "section": "cultural-identity",
        "signal_words": [
            "refined", "minimal", "exclusive", "timeless", "investment",
            "luxury", "curated", "intentional", "elevated", "discerning",
        ],
        "color_philosophy": "Restraint is the luxury signal. Cream, ivory, charcoal, black. One accent used sparingly. Less communicates more.",
        "color_palette": {
            "primary": "#1A1A1A",
            "secondary": "#3D3D3D",
            "accent": "#C9A84C",
            "background": "#FAFAF8",
            "text": "#1A1A1A",
        },
        "typography_direction": "Elegant and precise. High-end serif for headings. Clean light sans for body. Generous letter-spacing.",
        "imagery_style": "Editorial quality only. Clean compositions. Premium materials and environments. Nothing amateur.",
        "energy": "Exclusive, timeless, refined, curated, investment-worthy",
        "layout_affinity": ["magazine", "throne", "clean-launch"],
        "real_world_references": [
            "luxury fashion", "high-end real estate", "premium consulting", "fine dining brands",
        ],
        "detection_signals": [
            "luxury", "premium", "exclusive", "high-end", "bespoke",
            "curated", "discerning", "investment", "elite", "refined",
        ],
    },

    # ─── SECTION 2: COMMUNITY / MOVEMENT ────────────────────────────
    "faith-ministry": {
        "id": "faith-ministry",
        "name": "Faith and Ministry",
        "section": "community-movement",
        "signal_words": [
            "kingdom", "purpose", "transformation", "community", "anointed",
            "gospel", "worship", "discipleship", "covenant", "calling",
        ],
        "color_philosophy": "Royal purples and deep blues with gold for traditional feel. Or clean light palette — white space as peace and breath. Both honor the sacred.",
        "color_palette": {
            "primary": "#4A235A",
            "secondary": "#1A3A5C",
            "accent": "#C9A84C",
            "background": "#FAFAF8",
            "text": "#1A1A1A",
        },
        "typography_direction": "Dignified and warm. Strong serif for headlines that carry weight. Clean readable sans for body. Nothing frivolous.",
        "imagery_style": "Community gathered. Worship and celebration. Light and hope present. Real people real moments.",
        "energy": "Trustworthy, inspiring, communal, purposeful, grounded",
        "layout_affinity": ["community-hub", "movement", "story-arc"],
        "real_world_references": [
            "megachurch brands", "ministry organizations", "faith-based nonprofits",
        ],
        "detection_signals": [
            "church", "pastor", "ministry", "gospel", "worship",
            "faith", "kingdom", "discipleship", "congregation", "spiritual",
        ],
    },
    "wellness-healing": {
        "id": "wellness-healing",
        "name": "Wellness and Healing",
        "section": "community-movement",
        "signal_words": [
            "safe", "calm", "restoration", "breath", "wholeness",
            "gentle", "somatic", "holistic", "regulated", "nourished",
        ],
        "color_philosophy": "Soft and intentional. Sage, blush, warm white, muted earth. Colors that lower the nervous system. Nothing jarring or loud.",
        "color_palette": {
            "primary": "#5B7B6F",
            "secondary": "#8B6E5A",
            "accent": "#D4A89A",
            "background": "#FAF8F5",
            "text": "#2C2C2C",
        },
        "typography_direction": "Gentle and readable. Soft serif or rounded sans. Nothing sharp or aggressive. Words should feel like a warm hand.",
        "imagery_style": "Natural calm. Soft light. Rest and restoration visible. Bodies at ease. Nature present.",
        "energy": "Safe, calm, restorative, gentle, whole",
        "layout_affinity": ["story-arc", "community-hub", "clean-launch"],
        "real_world_references": [
            "therapy practices", "holistic health brands", "meditation apps", "wellness retreats",
        ],
        "detection_signals": [
            "therapy", "healing", "wellness", "holistic", "somatic",
            "mental health", "coach", "restoration", "breathwork", "trauma",
        ],
    },
    "creative-artist": {
        "id": "creative-artist",
        "name": "Creative and Artist",
        "section": "community-movement",
        "signal_words": [
            "original", "expressive", "process", "vision", "craft",
            "perspective", "raw", "made", "built", "invented",
        ],
        "color_philosophy": "Unexpected combinations that feel intentional not accidental. Rules exist to be broken with purpose. Color as creative statement.",
        "color_palette": {
            "primary": "#1A1A1A",
            "secondary": "#FF4444",
            "accent": "#FFE566",
            "background": "#F8F8F8",
            "text": "#1A1A1A",
        },
        "typography_direction": "Type AS design element. Display fonts that make a statement. Body that steps back. Hierarchy is everything.",
        "imagery_style": "Work front and center. Process visible. Artist present. Nothing stock nothing generic.",
        "energy": "Provocative, distinctive, original, process-driven, memorable",
        "layout_affinity": ["gallery", "magazine", "experience"],
        "real_world_references": [
            "artist portfolios", "design studios", "creative agencies", "art galleries",
        ],
        "detection_signals": [
            "artist", "designer", "photographer", "creative", "portfolio",
            "studio", "gallery", "maker", "craft", "visual",
        ],
    },
    "activist-advocate": {
        "id": "activist-advocate",
        "name": "Activist and Advocate",
        "section": "community-movement",
        "signal_words": [
            "movement", "justice", "together", "change", "bold",
            "unapologetic", "resist", "build", "community", "power",
        ],
        "color_philosophy": "Bold and unapologetic. High contrast. Colors that demand attention and signal urgency. Nothing passive.",
        "color_palette": {
            "primary": "#1A1A1A",
            "secondary": "#CC0000",
            "accent": "#FFD700",
            "background": "#FFFFFF",
            "text": "#1A1A1A",
        },
        "typography_direction": "Strong and direct. Bold weight. Nothing subtle about the message. Type that commands attention.",
        "imagery_style": "People in action. Community gathered. Real moments of change. Faces of the movement.",
        "energy": "Urgent, powerful, communal, bold, unapologetic",
        "layout_affinity": ["movement", "story-arc", "authority"],
        "real_world_references": [
            "social justice organizations", "community nonprofits", "advocacy campaigns",
        ],
        "detection_signals": [
            "nonprofit", "advocacy", "justice", "movement", "community organizing",
            "activist", "social change", "equity", "rights",
        ],
    },
    "scholar-educator": {
        "id": "scholar-educator",
        "name": "Scholar and Educator",
        "section": "community-movement",
        "signal_words": [
            "knowledge", "credibility", "depth", "transformation", "legacy",
            "curriculum", "research", "expertise", "proven", "studied",
        ],
        "color_philosophy": "Trust signals in color. Deep navy, forest green, burgundy. Academic gravitas without stuffiness. Credibility visible.",
        "color_palette": {
            "primary": "#1B3A6B",
            "secondary": "#2D5016",
            "accent": "#C9A84C",
            "background": "#F8F9FA",
            "text": "#1A1A1A",
        },
        "typography_direction": "Authoritative and clear. Strong serif for credibility. Readable body. Hierarchy that guides the reader.",
        "imagery_style": "Expertise in context. Teaching and speaking moments. Books and knowledge environments. Professional and warm.",
        "energy": "Credible, deep, transformative, authoritative, warm",
        "layout_affinity": ["authority", "story-arc", "community-hub"],
        "real_world_references": [
            "online course creators", "academic brands", "thought leadership platforms", "professional coaches",
        ],
        "detection_signals": [
            "professor", "educator", "curriculum", "course", "training",
            "academic", "research", "expertise", "certifications", "speaking", "author",
        ],
    },
    "street-culture": {
        "id": "street-culture",
        "name": "Street and Culture",
        "section": "community-movement",
        "signal_words": [
            "raw", "authentic", "culture", "limited", "exclusive",
            "real", "drops", "movement", "underground", "built different",
        ],
        "color_philosophy": "Either all black with one bold pop of color or maximum color maximalism. Nothing in between. Authenticity over polish.",
        "color_palette": {
            "primary": "#0A0A0A",
            "secondary": "#1A1A1A",
            "accent": "#FF6B00",
            "background": "#0F0F0F",
            "text": "#FFFFFF",
        },
        "typography_direction": "Bold and raw. Either strong grotesque or custom-feeling display. Type that has attitude.",
        "imagery_style": "Culture in context. Real environments. People who rep the brand. Authentic not produced. Feels like it was earned not bought.",
        "energy": "Raw, authentic, culture-driven, earned, real",
        "layout_affinity": ["experience", "gallery", "celebration"],
        "real_world_references": [
            "streetwear brands", "music artist sites", "sneaker culture", "urban brands",
        ],
        "detection_signals": [
            "streetwear", "urban", "music", "brand drops", "culture",
            "hip hop", "merch", "limited edition", "hype", "raw",
        ],
    },

    # ─── SECTION 3: LIFE STAGE ──────────────────────────────────────
    "rising-entrepreneur": {
        "id": "rising-entrepreneur",
        "name": "Rising Entrepreneur",
        "section": "life-stage",
        "signal_words": [
            "new", "building", "starting", "first", "launch",
            "hustle", "dream", "beginning", "chapter", "opportunity",
        ],
        "color_philosophy": "Fresh and energetic. Accessible but not cheap. Colors that signal ambition and optimism. Avoid feeling amateur.",
        "color_palette": {
            "primary": "#2D3561",
            "secondary": "#A23B72",
            "accent": "#F18F01",
            "background": "#FAFAFA",
            "text": "#1A1A1A",
        },
        "typography_direction": "Modern and clean. Approachable sans-serif. Nothing too bold or too delicate. Strikes the balance between fresh and credible.",
        "imagery_style": "Aspirational but relatable. Hustle visible. The journey matters. Real moments of building.",
        "energy": "Hungry, hopeful, establishing, proving",
        "layout_affinity": ["story-arc", "clean-launch", "community-hub"],
        "real_world_references": [
            "startup brands", "side hustle sites", "new coach launches", "first-time business owners",
        ],
        "detection_signals": [
            "new business", "just launched", "starting", "building",
            "first brand", "side hustle", "new chapter",
        ],
    },
    "established-authority": {
        "id": "established-authority",
        "name": "Established Authority",
        "section": "life-stage",
        "signal_words": [
            "proven", "experienced", "trusted", "recognized", "scaled",
            "team", "track record", "results", "known", "reputation",
        ],
        "color_philosophy": "Confidence in restraint. Rich deep tones that communicate experience. Nothing trendy — timeless authority.",
        "color_palette": {
            "primary": "#1A1A2E",
            "secondary": "#2D4A22",
            "accent": "#C9A84C",
            "background": "#FAFAF8",
            "text": "#1A1A1A",
        },
        "typography_direction": "Refined and weighty. Strong serif or premium sans. Typography that communicates tenure and trust.",
        "imagery_style": "Professional excellence. Results visible. Team and scale present. Polished without being sterile.",
        "energy": "Confident, refined, scaling, legacy-minded",
        "layout_affinity": ["authority", "throne", "magazine"],
        "real_world_references": [
            "established consulting firms", "recognized coaches", "scaled service businesses",
        ],
        "detection_signals": [
            "years of experience", "established", "proven", "scaling",
            "team", "multiple clients", "known for",
        ],
    },
    "reinvention": {
        "id": "reinvention",
        "name": "Reinvention",
        "section": "life-stage",
        "signal_words": [
            "pivot", "new direction", "transformation", "fresh start",
            "evolved", "different", "changed", "next chapter", "rebrand", "becoming",
        ],
        "color_philosophy": "Bold fresh palette that signals change. Not tied to old identity. Colors that feel like a new beginning.",
        "color_palette": {
            "primary": "#2C3E50",
            "secondary": "#8E44AD",
            "accent": "#E74C3C",
            "background": "#FAFAFA",
            "text": "#1A1A1A",
        },
        "typography_direction": "Forward-looking and distinctive. Type that signals this is something new. Clean break from whatever came before.",
        "imagery_style": "Forward momentum visible. Before/after energy. Clean slate environments. Bold personal presence.",
        "energy": "Bold, fresh start, leaving old behind, new chapter",
        "layout_affinity": ["story-arc", "experience", "clean-launch"],
        "real_world_references": [
            "career pivot brands", "rebrands", "life transitions", "new ventures from established people",
        ],
        "detection_signals": [
            "pivot", "rebrand", "new direction", "leaving corporate",
            "transition", "starting over", "new chapter", "different now",
        ],
    },
    "legacy-builder": {
        "id": "legacy-builder",
        "name": "Legacy Builder",
        "section": "life-stage",
        "signal_words": [
            "generational", "institution", "foundation", "permanent",
            "timeless", "family", "decades", "enduring", "heritage", "built to last",
        ],
        "color_philosophy": "Institutional gravitas. Colors that communicate permanence and weight. Nothing trendy — everything timeless.",
        "color_palette": {
            "primary": "#1A1A1A",
            "secondary": "#2C1810",
            "accent": "#8B7355",
            "background": "#F5F3EE",
            "text": "#1A1A1A",
        },
        "typography_direction": "Classic and enduring. Strong serif that communicates decades of expertise. Weight and permanence in every letter.",
        "imagery_style": "Heritage and permanence visible. Generational imagery. Buildings, archives, history. Gravitas without stuffiness.",
        "energy": "Timeless, institutional, generational, serious",
        "layout_affinity": ["throne", "authority", "magazine"],
        "real_world_references": [
            "family businesses", "institutions", "foundations", "generational brands",
        ],
        "detection_signals": [
            "generational", "legacy", "institution", "family business",
            "decades", "what I leave behind", "foundation",
        ],
    },

    # ─── SECTION 4: AESTHETIC MOVEMENT ──────────────────────────────
    "maximalist": {
        "id": "maximalist",
        "name": "Maximalist",
        "section": "aesthetic-movement",
        "signal_words": [
            "more", "bold", "layered", "abundant", "vibrant",
            "expressive", "everything", "rich", "ornate", "overflowing",
        ],
        "color_philosophy": "More is more. Pattern, color, texture, layering. Abundance celebrated visually.",
        "color_palette": {
            "primary": "#8B1A4A",
            "secondary": "#1A3A8B",
            "accent": "#F4A261",
            "background": "#FFF8F0",
            "text": "#1A1A1A",
        },
        "typography_direction": "Expressive and layered. Multiple type styles working together. Display fonts with personality. Nothing restrained.",
        "imagery_style": "Rich and layered. Multiple textures. Abundance visible. Color photography with saturation.",
        "energy": "Abundant, bold, layered, expressive, overwhelming in the best way",
        "layout_affinity": ["celebration", "experience", "gallery"],
        "real_world_references": [
            "maximalist interiors", "fashion editorials", "festival brands", "art-forward brands",
        ],
        "detection_signals": [
            "colorful", "bold", "vibrant", "more", "maximalist",
            "expressive", "everything", "layered",
        ],
    },
    "minimalist": {
        "id": "minimalist",
        "name": "Minimalist",
        "section": "aesthetic-movement",
        "signal_words": [
            "clean", "simple", "focused", "intentional", "space",
            "less", "restrained", "essential", "clarity", "precise",
        ],
        "color_philosophy": "Intentional restraint. White space as design. Less communicates more. Every element earns its place.",
        "color_palette": {
            "primary": "#1A1A1A",
            "secondary": "#3D3D3D",
            "accent": "#0066CC",
            "background": "#FFFFFF",
            "text": "#1A1A1A",
        },
        "typography_direction": "Clean and precise. Geometric sans-serif. Perfect spacing. Nothing extra. Restraint is the statement.",
        "imagery_style": "Clean compositions. Negative space honored. Quality over quantity. Every image is essential.",
        "energy": "Focused, intentional, clear, essential, restrained",
        "layout_affinity": ["clean-launch", "magazine", "authority"],
        "real_world_references": [
            "Apple", "Muji", "minimal tech brands", "Scandinavian design",
        ],
        "detection_signals": [
            "clean", "simple", "minimal", "less", "focused",
            "clear", "white space", "restrained",
        ],
    },
    "editorial": {
        "id": "editorial",
        "name": "Editorial",
        "section": "aesthetic-movement",
        "signal_words": [
            "magazine", "publication", "content", "editorial", "written",
            "story", "narrative", "feature", "spread", "column",
        ],
        "color_philosophy": "Typography is the design. Color supports the words. Magazine-quality composition throughout.",
        "color_palette": {
            "primary": "#1A1A1A",
            "secondary": "#8B0000",
            "accent": "#1A1A1A",
            "background": "#FAFAFA",
            "text": "#1A1A1A",
        },
        "typography_direction": "Editorial excellence. Strong serif headlines. Clean body. Perfect measure and leading. Type IS the design.",
        "imagery_style": "Editorial photography. Strong composition. Magazine-quality. Supports the narrative.",
        "energy": "Intellectual, curated, narrative-driven, sophisticated, literary",
        "layout_affinity": ["magazine", "gallery", "authority"],
        "real_world_references": [
            "The New Yorker", "Monocle", "editorial platforms", "content-first brands",
        ],
        "detection_signals": [
            "editorial", "magazine", "publication", "content", "writing",
            "thought leadership", "words matter",
        ],
    },
    "organic-natural": {
        "id": "organic-natural",
        "name": "Organic and Natural",
        "section": "aesthetic-movement",
        "signal_words": [
            "handmade", "organic", "natural", "earthy", "artisan",
            "slow", "intentional", "textured", "warm", "imperfect",
        ],
        "color_philosophy": "Earth tones and textures. Handcrafted warmth. Human over perfect. Warmth over polish.",
        "color_palette": {
            "primary": "#5C4033",
            "secondary": "#3E5C40",
            "accent": "#C4A35A",
            "background": "#F7F3EE",
            "text": "#2C2010",
        },
        "typography_direction": "Warm and organic. Slightly imperfect where appropriate. Hand-drawn accents welcome. Human feeling.",
        "imagery_style": "Natural materials. Handcrafted objects. Earth textures. Warm light. Human touch visible.",
        "energy": "Warm, grounded, handcrafted, intentional, human",
        "layout_affinity": ["story-arc", "community-hub", "celebration"],
        "real_world_references": [
            "artisan brands", "organic food brands", "craft businesses", "slow living",
        ],
        "detection_signals": [
            "handmade", "organic", "natural", "earthy", "artisan",
            "small batch", "slow", "intentional", "textured",
        ],
    },
    "futurist-tech": {
        "id": "futurist-tech",
        "name": "Futurist and Tech",
        "section": "aesthetic-movement",
        "signal_words": [
            "future", "innovation", "digital", "platform", "automated",
            "smart", "next", "forward", "advanced", "disruptive",
        ],
        "color_philosophy": "Dark backgrounds with electric accent colors. Gradients as depth. Forward-looking always.",
        "color_palette": {
            "primary": "#0A0A0F",
            "secondary": "#0D1B2A",
            "accent": "#00F5FF",
            "background": "#050508",
            "text": "#E8E8FF",
        },
        "typography_direction": "Sharp and modern. Geometric sans-serif. Monospace accents for technical feel. Forward-looking typography.",
        "imagery_style": "Abstract and futuristic. Dark environments. Gradients and glow effects. Technology as visual language.",
        "energy": "Forward-looking, innovative, electric, precise, cutting-edge",
        "layout_affinity": ["experience", "clean-launch", "authority"],
        "real_world_references": [
            "tech startups", "AI companies", "SaaS brands", "blockchain/web3",
        ],
        "detection_signals": [
            "tech", "AI", "software", "app", "digital",
            "automation", "innovation", "future", "platform", "SaaS",
        ],
    },
}


# ─── LAYOUTS — port from layoutLibrary.ts ──────────────────────────────

LAYOUTS: Dict[str, LayoutStyle] = {
    "magazine": {
        "id": "magazine",
        "name": "The Magazine",
        "description": "Full bleed editorial. Large typography. Generous whitespace. Content as art.",
        "vocabulary_affinity": ["editorial", "expressive-vibrancy", "diaspora-modern", "universal-premium", "creative-artist"],
        "generation_prompt": "Build an editorial magazine-style homepage. Full bleed hero with large bold typography overlay. Minimal navigation bar — transparent or minimal. Content in generous full-width sections with lots of breathing room. Asymmetric grid where appropriate. Typography is the primary design element. Feels like a luxury magazine or high-end brand site. Every section should feel like a spread.",
        "structure_notes": "Typography-driven. Full bleed sections. Asymmetric layouts. Generous whitespace between sections.",
        "section_order": ["nav", "hero-full-bleed", "statement-section", "services-editorial", "image-feature", "testimonial-pull-quote", "cta-full-width", "footer"],
    },
    "throne": {
        "id": "throne",
        "name": "The Throne",
        "description": "Dark, powerful, commanding. Gold accents. Everything deliberate.",
        "vocabulary_affinity": ["sovereign-authority", "universal-premium", "legacy-builder", "diaspora-modern", "established-authority"],
        "generation_prompt": "Build a commanding dark-themed homepage. Dark hero background with powerful centered or left-aligned headline. Gold or premium accent color for dividers and highlights. Structured sections below with clear hierarchy. Generous whitespace that feels intentional not empty. Every element earns its place. Feels like entering a space of authority. Use dark backgrounds throughout — this is not a light site.",
        "structure_notes": "Dark backgrounds throughout. Gold/premium accents. Strong hierarchy. Authority-driven structure.",
        "section_order": ["nav-dark", "hero-dark", "authority-statement", "services-premium", "credentials-section", "testimonial-dark", "cta-dark", "footer-dark"],
    },
    "community-hub": {
        "id": "community-hub",
        "name": "The Community Hub",
        "description": "Warm, welcoming, people-forward. Feels like walking into a beloved space.",
        "vocabulary_affinity": ["warm-community", "faith-ministry", "wellness-healing", "scholar-educator", "rising-entrepreneur"],
        "generation_prompt": "Build a warm community-focused homepage. Hero with face or people imagery prominent. Warm welcoming headline. Services in approachable friendly cards below. Testimonials woven throughout — not just at the bottom. Clear next step always visible. Feels like walking into a space that knows you. People are the design element.",
        "structure_notes": "People-forward imagery. Warm color palette. Approachable card-based services. Testimonials woven throughout.",
        "section_order": ["nav-warm", "hero-warm", "welcome-section", "services-cards", "community-proof", "about-personal", "testimonials-warm", "cta-warm", "footer-warm"],
    },
    "gallery": {
        "id": "gallery",
        "name": "The Gallery",
        "description": "Image-first. Work speaks loudest. Minimal words maximum impact.",
        "vocabulary_affinity": ["creative-artist", "street-culture", "expressive-vibrancy", "maximalist"],
        "generation_prompt": "Build an image-first gallery homepage. Work is the hero — portfolio grid or masonry layout above the fold or immediately after a brief identity statement. Minimal text — the work speaks. Services brief and secondary. Booking or contact at the end. This is a gallery with a business attached not a business with a gallery attached.",
        "structure_notes": "Image-dominant. Masonry or grid portfolio. Minimal text. Work-first hierarchy.",
        "section_order": ["nav-minimal", "identity-brief", "gallery-hero", "gallery-grid", "services-brief", "contact-simple", "footer-minimal"],
    },
    "authority": {
        "id": "authority",
        "name": "The Authority Page",
        "description": "Trust signals high. Credentials visible early. Expertise undeniable.",
        "vocabulary_affinity": ["scholar-educator", "established-authority", "sovereign-authority", "activist-advocate", "universal-premium"],
        "generation_prompt": "Build an authority and credibility-focused homepage. Clear compelling value proposition in the hero. Credentials, certifications, media mentions, or years of experience visible high on the page — not hidden. Services in a structured organized grid. FAQ or objection-handling section. Strong CTA that appears multiple times. Trust is the conversion mechanism on this page.",
        "structure_notes": "Credentials early. Trust signals prominent. Structured grid. Repeated CTAs. FAQ section.",
        "section_order": ["nav", "hero-authority", "credentials-bar", "value-proposition", "services-grid", "social-proof", "faq-section", "cta-repeated", "footer"],
    },
    "story-arc": {
        "id": "story-arc",
        "name": "The Story Arc",
        "description": "Narrative flow. Problem to solution to invitation. Personal and momentum-building.",
        "vocabulary_affinity": ["reinvention", "rising-entrepreneur", "wellness-healing", "faith-ministry", "organic-natural"],
        "generation_prompt": "Build a story-driven narrative homepage. The page tells a journey from top to bottom. Start with the problem or pain the audience feels. Move through the journey or transformation. Arrive at the solution and who provides it. Social proof and testimonials woven naturally into the narrative. End with a clear personal invitation. Alternating section layouts create visual rhythm. Feels like a conversation not a brochure.",
        "structure_notes": "Narrative flow. Problem→journey→solution→invitation. Alternating layouts. Conversational tone.",
        "section_order": ["nav", "hero-problem-aware", "problem-section", "journey-section", "solution-reveal", "proof-woven", "about-personal", "invitation-cta", "footer"],
    },
    "movement": {
        "id": "movement",
        "name": "The Movement Page",
        "description": "Mission front and center. Bold statement. Action-oriented. Community over individual.",
        "vocabulary_affinity": ["activist-advocate", "faith-ministry", "street-culture", "warm-community"],
        "generation_prompt": "Build a mission-driven movement homepage. Bold statement hero — no hesitation, no softening. Mission and cause visible immediately. Not about one person but about what is being built together. Community imagery prominent. Email capture or join CTA high on the page. Action language throughout. Feels like something is happening and the visitor is being invited in.",
        "structure_notes": "Mission-first. Bold statements. Community imagery. Action CTAs high on page.",
        "section_order": ["nav-bold", "hero-statement", "mission-section", "community-section", "impact-numbers", "join-cta", "stories-section", "movement-footer"],
    },
    "experience": {
        "id": "experience",
        "name": "The Experience",
        "description": "Immersive. Cinematic sections. The site IS the brand statement.",
        "vocabulary_affinity": ["futurist-tech", "cultural-fusion", "maximalist", "street-culture", "creative-artist"],
        "generation_prompt": "Build an immersive experience homepage. Full screen sections — one dominant idea per section. Cinematic feel throughout. Bold color transitions between sections. Typography used dramatically. The experience of scrolling this page is itself a brand statement. This is not a brochure — it is an experience. CSS transitions and visual drama encouraged.",
        "structure_notes": "Full-screen sections. Cinematic transitions. One idea per screen. Visual drama.",
        "section_order": ["nav-overlay", "hero-fullscreen", "brand-statement-screen", "services-cinematic", "visual-feature-screen", "proof-screen", "cta-screen", "footer-dramatic"],
    },
    "clean-launch": {
        "id": "clean-launch",
        "name": "The Clean Launch",
        "description": "One focused message. Nothing extra. Clarity converts.",
        "vocabulary_affinity": ["minimalist", "universal-premium", "rising-entrepreneur", "futurist-tech", "asian-excellence"],
        "generation_prompt": "Build a clean focused single-message homepage. Hero with one clear headline and one CTA — nothing competing with it. Services or offerings below in a clean simple layout. Brief social proof. Simple contact or booking. Nothing extra. Every element that does not convert or communicate has been removed. Clarity is the design principle. White space is your friend.",
        "structure_notes": "Single-message focused. Minimal elements. Clarity-first. Maximum white space.",
        "section_order": ["nav-minimal", "hero-focused", "brief-services", "simple-proof", "single-cta", "footer-minimal"],
    },
    "celebration": {
        "id": "celebration",
        "name": "The Celebration",
        "description": "Colorful, joyful, layered. Energy jumps off the page.",
        "vocabulary_affinity": ["expressive-vibrancy", "warm-community", "organic-natural", "maximalist", "cultural-fusion"],
        "generation_prompt": "Build a celebration-energy homepage. Colorful and layered — sections feel like rooms in a beautiful space. Joy is a design element. Pattern or texture present where appropriate. Typography with personality. Images of people, celebration, and abundance. This site should make visitors feel something positive immediately. Energy is the first impression.",
        "structure_notes": "Colorful sections. Layered textures. Joy as design element. Personality in typography.",
        "section_order": ["nav-colorful", "hero-joyful", "celebration-intro", "services-warm-cards", "gallery-life", "testimonials-joyful", "cta-warm", "footer-celebration"],
    },
    "studio-portfolio": {
        "id": "studio-portfolio",
        "name": "The Studio Portfolio",
        "description": "Split hero, work-forward center, services as portrait cards. Creative brand that leads with proof.",
        "vocabulary_affinity": ["creative-artist", "expressive-vibrancy", "rising-entrepreneur", "editorial"],
        "generation_prompt": "Build a creative studio portfolio homepage. Split hero section — strong headline and two CTAs on the left, large dominant portrait or work image on the right. Below the hero add a scrolling ticker marquee showing service categories or brand keywords looping across the full width. Center section is a portfolio grid — masonry or uniform cards showing work samples in rows, 3 columns, generous gap between cards. After the portfolio add a services section with cards arranged in a row — each card has a tall portrait-oriented image, service name, one-line description, and a link. End with an embedded social feed section showing recent Instagram-style posts in a grid. Personality and voice should be present in every headline — this is not a corporate site, it is a personal creative brand.",
        "structure_notes": "Split hero. Ticker marquee. Masonry portfolio grid. Portrait service cards. Social feed grid.",
        "section_order": ["nav", "hero-split", "marquee-ticker", "portfolio-grid", "services-portrait-cards", "about-brief", "testimonials", "social-feed", "footer"],
    },
    "empire-platform": {
        "id": "empire-platform",
        "name": "The Empire Platform",
        "description": "Full bleed hero with identity words. Founder intro. Multiple full-width sections for each revenue stream. One page, multiple worlds.",
        "vocabulary_affinity": ["faith-ministry", "legacy-builder", "sovereign-authority", "established-authority", "activist-advocate"],
        "generation_prompt": "Build a multi-vertical empire homepage. Full bleed hero with a background image and overlay — place 4-5 identity descriptor words across the top of the hero in caps separated by dividers (example: MOTIVATED | DETERMINED | DESTINED) then a strong headline below. Immediately after the hero add a founder/leader intro section — split layout with personal bio text on one side and a tall vertical portrait on the other. Then alternate between full-width image break sections and split-content sections — each full-width break promotes one specific offering (a program, an event, merchandise, or booking) with its own background image, headline, and CTA button. Each offering is a completely separate visual section. End with a newsletter or community opt-in form section before the footer. This page should feel like multiple worlds under one roof — one identity, many dimensions.",
        "structure_notes": "Identity words hero. Founder split intro. Alternating full-width breaks per offering. Community opt-in.",
        "section_order": ["nav", "hero-identity-words", "founder-intro-split", "full-width-break-1", "program-split-section", "full-width-break-2", "event-promotion-section", "full-width-break-3", "merchandise-or-booking-section", "community-optin", "footer"],
    },
}


# ─── VOCAB→LAYOUT MAP — port from vocabularyLayoutMap.ts ───────────────

VOCAB_LAYOUT_MAP: Dict[str, List[str]] = {
    "expressive-vibrancy": ["magazine", "studio-portfolio", "celebration", "gallery"],
    "sovereign-authority": ["throne", "empire-platform", "authority", "clean-launch"],
    "warm-community": ["community-hub", "story-arc", "celebration"],
    "cultural-fusion": ["magazine", "experience", "gallery"],
    "diaspora-modern": ["magazine", "throne", "authority"],
    "asian-excellence": ["clean-launch", "authority", "magazine"],
    "indigenous-earth": ["community-hub", "story-arc", "celebration"],
    "universal-premium": ["magazine", "throne", "clean-launch"],
    "faith-ministry": ["empire-platform", "community-hub", "movement", "story-arc"],
    "wellness-healing": ["story-arc", "community-hub", "clean-launch"],
    "creative-artist": ["studio-portfolio", "gallery", "magazine", "experience"],
    "activist-advocate": ["movement", "empire-platform", "story-arc", "authority"],
    "scholar-educator": ["authority", "story-arc", "community-hub"],
    "street-culture": ["experience", "gallery", "celebration"],
    "rising-entrepreneur": ["story-arc", "clean-launch", "studio-portfolio", "community-hub"],
    "established-authority": ["authority", "empire-platform", "throne", "magazine"],
    "reinvention": ["story-arc", "experience", "clean-launch"],
    "legacy-builder": ["empire-platform", "throne", "authority", "magazine"],
    "maximalist": ["celebration", "experience", "gallery"],
    "minimalist": ["clean-launch", "magazine", "authority"],
    "editorial": ["magazine", "studio-portfolio", "gallery", "authority"],
    "organic-natural": ["story-arc", "community-hub", "celebration"],
    "futurist-tech": ["experience", "clean-launch", "authority"],
}


# ─── FONT PAIRINGS — port from fontLibrary.ts ─────────────────────────

FONT_PAIRINGS: Dict[str, FontPairing] = {
    "playfair-lato": {
        "id": "playfair-lato",
        "name": "Classic Luxury",
        "heading_font": "Playfair Display",
        "body_font": "Lato",
        "heading_weight": "700",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Lato:wght@300;400;700&display=swap",
        "feel": "Classic luxury, editorial, high-end beauty and lifestyle",
        "vocabulary_match": ["universal-premium", "expressive-vibrancy", "diaspora-modern"],
        "layout_match": ["magazine", "celebration", "gallery"],
        "css_variables": {"heading": "'Playfair Display', Georgia, serif", "body": "'Lato', 'Helvetica Neue', sans-serif"},
        "sample_heading_style": "font-family: 'Playfair Display', Georgia, serif; font-weight: 700;",
        "sample_body_style": "font-family: 'Lato', 'Helvetica Neue', sans-serif; font-weight: 400;",
    },
    "cormorant-jost": {
        "id": "cormorant-jost",
        "name": "Refined Editorial",
        "heading_font": "Cormorant Garamond",
        "body_font": "Jost",
        "heading_weight": "600",
        "body_weight": "300",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600&family=Jost:wght@300;400;500&display=swap",
        "feel": "Refined, editorial, fashion-forward, whisper luxury",
        "vocabulary_match": ["universal-premium", "editorial", "cultural-fusion"],
        "layout_match": ["magazine", "clean-launch", "throne"],
        "css_variables": {"heading": "'Cormorant Garamond', Georgia, serif", "body": "'Jost', sans-serif"},
        "sample_heading_style": "font-family: 'Cormorant Garamond', Georgia, serif; font-weight: 600;",
        "sample_body_style": "font-family: 'Jost', sans-serif; font-weight: 300;",
    },
    "dm-serif-dm-sans": {
        "id": "dm-serif-dm-sans",
        "name": "Modern Authority",
        "heading_font": "DM Serif Display",
        "body_font": "DM Sans",
        "heading_weight": "400",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500&display=swap",
        "feel": "Modern luxury, clean authority, premium but approachable",
        "vocabulary_match": ["established-authority", "universal-premium", "minimalist"],
        "layout_match": ["clean-launch", "authority", "magazine"],
        "css_variables": {"heading": "'DM Serif Display', Georgia, serif", "body": "'DM Sans', sans-serif"},
        "sample_heading_style": "font-family: 'DM Serif Display', Georgia, serif; font-weight: 400;",
        "sample_body_style": "font-family: 'DM Sans', sans-serif; font-weight: 400;",
    },
    "bebas-montserrat": {
        "id": "bebas-montserrat",
        "name": "Bold Command",
        "heading_font": "Bebas Neue",
        "body_font": "Montserrat",
        "heading_weight": "400",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Montserrat:wght@300;400;600&display=swap",
        "feel": "Bold, commanding, strong, no hesitation",
        "vocabulary_match": ["sovereign-authority", "street-culture", "activist-advocate"],
        "layout_match": ["throne", "movement", "experience"],
        "css_variables": {"heading": "'Bebas Neue', sans-serif", "body": "'Montserrat', sans-serif"},
        "sample_heading_style": "font-family: 'Bebas Neue', sans-serif; font-weight: 400;",
        "sample_body_style": "font-family: 'Montserrat', sans-serif; font-weight: 400;",
    },
    "oswald-open-sans": {
        "id": "oswald-open-sans",
        "name": "Direct Power",
        "heading_font": "Oswald",
        "body_font": "Open Sans",
        "heading_weight": "600",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Oswald:wght@400;600&family=Open+Sans:wght@300;400;600&display=swap",
        "feel": "Direct, strong, no-nonsense, earned authority",
        "vocabulary_match": ["sovereign-authority", "legacy-builder", "activist-advocate"],
        "layout_match": ["authority", "throne", "movement"],
        "css_variables": {"heading": "'Oswald', sans-serif", "body": "'Open Sans', sans-serif"},
        "sample_heading_style": "font-family: 'Oswald', sans-serif; font-weight: 600;",
        "sample_body_style": "font-family: 'Open Sans', sans-serif; font-weight: 400;",
    },
    "raleway-raleway": {
        "id": "raleway-raleway",
        "name": "Elegant Strong",
        "heading_font": "Raleway",
        "body_font": "Raleway",
        "heading_weight": "700",
        "body_weight": "300",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;700&display=swap",
        "feel": "Elegant and strong, modern premium, single-family harmony",
        "vocabulary_match": ["sovereign-authority", "diaspora-modern", "universal-premium"],
        "layout_match": ["throne", "clean-launch", "magazine"],
        "css_variables": {"heading": "'Raleway', sans-serif", "body": "'Raleway', sans-serif"},
        "sample_heading_style": "font-family: 'Raleway', sans-serif; font-weight: 700;",
        "sample_body_style": "font-family: 'Raleway', sans-serif; font-weight: 300;",
    },
    "lora-source-sans": {
        "id": "lora-source-sans",
        "name": "Warm Trustworthy",
        "heading_font": "Lora",
        "body_font": "Source Sans 3",
        "heading_weight": "600",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Lora:wght@400;600&family=Source+Sans+3:wght@300;400;600&display=swap",
        "feel": "Warm, trustworthy, approachable, grounded and real",
        "vocabulary_match": ["warm-community", "faith-ministry", "wellness-healing"],
        "layout_match": ["community-hub", "story-arc", "empire-platform"],
        "css_variables": {"heading": "'Lora', Georgia, serif", "body": "'Source Sans 3', sans-serif"},
        "sample_heading_style": "font-family: 'Lora', Georgia, serif; font-weight: 600;",
        "sample_body_style": "font-family: 'Source Sans 3', sans-serif; font-weight: 400;",
    },
    "merriweather-inter": {
        "id": "merriweather-inter",
        "name": "Grounded Reader",
        "heading_font": "Merriweather",
        "body_font": "Inter",
        "heading_weight": "700",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Inter:wght@300;400;500&display=swap",
        "feel": "Readable, grounded, honest, scholarly and accessible",
        "vocabulary_match": ["scholar-educator", "activist-advocate", "organic-natural"],
        "layout_match": ["authority", "story-arc", "community-hub"],
        "css_variables": {"heading": "'Merriweather', Georgia, serif", "body": "'Inter', sans-serif"},
        "sample_heading_style": "font-family: 'Merriweather', Georgia, serif; font-weight: 700;",
        "sample_body_style": "font-family: 'Inter', sans-serif; font-weight: 400;",
    },
    "nunito-nunito-sans": {
        "id": "nunito-nunito-sans",
        "name": "Friendly Warmth",
        "heading_font": "Nunito",
        "body_font": "Nunito Sans",
        "heading_weight": "700",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Nunito:wght@400;700&family=Nunito+Sans:wght@300;400;600&display=swap",
        "feel": "Friendly, soft, welcoming, community and care focused",
        "vocabulary_match": ["rising-entrepreneur", "wellness-healing", "warm-community"],
        "layout_match": ["community-hub", "story-arc", "celebration"],
        "css_variables": {"heading": "'Nunito', sans-serif", "body": "'Nunito Sans', sans-serif"},
        "sample_heading_style": "font-family: 'Nunito', sans-serif; font-weight: 700;",
        "sample_body_style": "font-family: 'Nunito Sans', sans-serif; font-weight: 400;",
    },
    "abril-poppins": {
        "id": "abril-poppins",
        "name": "Bold Personality",
        "heading_font": "Abril Fatface",
        "body_font": "Poppins",
        "heading_weight": "400",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Abril+Fatface&family=Poppins:wght@300;400;600&display=swap",
        "feel": "Bold personality, expressive, celebration energy, unapologetic",
        "vocabulary_match": ["expressive-vibrancy", "maximalist", "cultural-fusion"],
        "layout_match": ["celebration", "gallery", "studio-portfolio"],
        "css_variables": {"heading": "'Abril Fatface', Georgia, serif", "body": "'Poppins', sans-serif"},
        "sample_heading_style": "font-family: 'Abril Fatface', Georgia, serif; font-weight: 400;",
        "sample_body_style": "font-family: 'Poppins', sans-serif; font-weight: 400;",
    },
    "space-grotesk": {
        "id": "space-grotesk",
        "name": "Future Forward",
        "heading_font": "Space Grotesk",
        "body_font": "Space Grotesk",
        "heading_weight": "700",
        "body_weight": "300",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;700&display=swap",
        "feel": "Modern, techy, distinctive, forward-looking and precise",
        "vocabulary_match": ["futurist-tech", "asian-excellence", "minimalist"],
        "layout_match": ["experience", "clean-launch", "authority"],
        "css_variables": {"heading": "'Space Grotesk', sans-serif", "body": "'Space Grotesk', sans-serif"},
        "sample_heading_style": "font-family: 'Space Grotesk', sans-serif; font-weight: 700;",
        "sample_body_style": "font-family: 'Space Grotesk', sans-serif; font-weight: 300;",
    },
    "cinzel-libre-baskerville": {
        "id": "cinzel-libre-baskerville",
        "name": "Sacred Dignity",
        "heading_font": "Cinzel",
        "body_font": "Libre Baskerville",
        "heading_weight": "700",
        "body_weight": "400",
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700&family=Libre+Baskerville:wght@400;700&display=swap",
        "feel": "Sacred, dignified, timeless, kingdom and legacy weight",
        "vocabulary_match": ["faith-ministry", "legacy-builder", "scholar-educator"],
        "layout_match": ["empire-platform", "throne", "authority"],
        "css_variables": {"heading": "'Cinzel', Georgia, serif", "body": "'Libre Baskerville', Georgia, serif"},
        "sample_heading_style": "font-family: 'Cinzel', Georgia, serif; font-weight: 700;",
        "sample_body_style": "font-family: 'Libre Baskerville', Georgia, serif; font-weight: 400;",
    },
}


# ─── STYLE STRANDS — port from strandConstants.ts ──────────────────────

STYLE_STRANDS: Dict[str, StyleStrand] = {
    "editorial": {
        "id": "editorial",
        "name": "Editorial",
        "desc": "Type-led, magazine grid, stark contrast",
        "swatches": ["#111", "#fff", "#e8e0d5", "#222"],
        "dna": "Editorial/Magazine: Typography IS the layout — headlines scale to fill their containers, pull-quotes become structural elements, section numbers are massive and ghosted behind content. Copy is precise and declarative — short sentences that land like headlines. Black and white base with one controlled accent that appears surgically. Asymmetric grid where nothing is centered by accident. The design has a strong point of view — it makes arguments not suggestions. Influence: NYT Magazine, Bloomberg Businessweek, Kinfolk, i-D Magazine.",
        "spatial_dna": "Asymmetry is structural. One element bleeds off the edge of every major section — a large numeral, a cropped word, an oversized headline. Text columns are never equal width. Content anchors to the left or right, never floats centered. The grid is felt not seen. Negative space is not empty — it is weight on the opposite side of the content.",
    },
    "luxury": {
        "id": "luxury",
        "name": "Luxury",
        "desc": "Refined whitespace, gold, serif elegance",
        "swatches": ["#0d0c0a", "#C9A84C", "#e8dfc8", "#6b5d40"],
        "dna": "Luxury/Refined: Negative space is the primary design element — content arrives after silence, not before it. Gold appears once per section like a watch catching light during a handshake — never decorative, always meaningful. Copy is unhurried and ceremonial — longer sentences that trust the reader. Thin serif display type at light weight creates refinement without aggression. Nothing competes for attention — one focal element per zone. The page communicates that the brand has nothing to prove. Influence: Louis Vuitton, Porsche, Four Seasons, Bottega Veneta.",
        "spatial_dna": "Content arrives after space. Headlines sit in the lower third of hero sections, not centered — silence comes first. Sections are vast and unhurried. A single element per focal zone — never competing anchors. Gold appears once per section, like a detail you notice on second look. Margins are so generous they feel architectural. The page breathes slowly.",
    },
    "bold": {
        "id": "bold",
        "name": "Bold / Maximalist",
        "desc": "High energy, layered, loud type",
        "swatches": ["#ff3a1e", "#ffd500", "#0a0a0a", "#f5f0e8"],
        "dna": "Bold/Maximalist: Type IS the image — headlines fill containers edge to edge, words overlap photography, scale creates hierarchy before color does. Copy is punchy and confrontational — one sentence paragraphs, active voice, verbs that move. High contrast color blocking creates sections without borders. The grid exists to be broken visibly. Energy and confidence are the message before the words are read. Influence: David Carson, Virgil Abloh, Off-White, early Kanye West creative direction.",
        "spatial_dna": "Type IS the layout. Headlines scale to fill their containers edge to edge. Words overlap imagery. Sections collide rather than separate — no breathing room between them. Color blocks are full-bleed with hard cuts, no fades. Elements intentionally break their containing boxes. The diagonal exists — rotated text, angled dividers. Density is the point.",
    },
    "minimal": {
        "id": "minimal",
        "name": "Minimal",
        "desc": "Silence as design, precision spacing",
        "swatches": ["#fafafa", "#111", "#e0e0e0", "#888"],
        "dna": "Minimal: Radical restraint — every element that could be removed has been. One focal point per screen, never two. Negative space is not empty — it is the loudest element on the page. Copy is sparse and weighted — every word earns its place, sentences end before they overstay. Monochromatic or near-mono palette where a single accent color appears once and is unforgettable. The design communicates confidence through what it refuses to add. Influence: Apple, Muji, Dieter Rams, early Google, Jony Ive.",
        "spatial_dna": "One thing per screen. Radical negative space is not empty — it is the loudest element on the page. Content is surgically centered or anchored to a single point. Nothing shares visual attention. Scroll reveals content one piece at a time rather than showing everything at once. Lines are single pixel. If an element could be removed and the page still functions, remove it.",
    },
    "dark": {
        "id": "dark",
        "name": "Dark / Cinematic",
        "desc": "Deep bg, glowing accents",
        "swatches": ["#080b12", "#00e5c8", "#c47aff", "#1a2230"],
        "dna": "Dark/Cinematic: The page has atmosphere — visitors feel like they entered something, not opened something. Deep near-black backgrounds create depth that flat black never achieves. Accent colors glow rather than sit — the difference between a screen and a printed page. Copy is dramatic and present-tense — this is happening now, you are here. Layered z-axis gives the sense that content exists at different depths. Gold or electric accents appear like light sources inside the darkness. Influence: A24 films, Christopher Nolan titles, high-end gaming, Dior Beauty.",
        "spatial_dna": "Depth through layering, not flatness. Elements exist at different z-levels — background imagery, mid-layer content, foreground text. Sections bleed into each other with no hard dividers. The page has atmosphere — you feel like you are inside it, not reading it. Light comes from within content, not from the background. Accent colors glow rather than sit flat.",
    },
    "organic": {
        "id": "organic",
        "name": "Organic",
        "desc": "Curves, natural tones, texture-rich",
        "swatches": ["#e8e0d0", "#4a7c59", "#c4a882", "#2d2a24"],
        "dna": "Organic/Natural: Edges breathe — containers have curves, sections overlap like layers of sediment, nothing is perfectly rectangular. Earthy desaturated palette with warm undertones that feel like materials you could touch. Copy is intimate and sensory — describes how things feel, smell, taste. Photography bleeds out of its frames. The brand feels handmade even at scale. Warmth is structural not decorative. Influence: Aesop, Kinfolk, farm-to-table restaurants, Patagonia, Glossier.",
        "spatial_dna": "Edges are never straight. Content containers use flowing curves. Sections overlap slightly, bleeding into each other like watercolor edges. Layout breathes unevenly — some sections are compressed, others vast and meadow-like. Photography breaks out of its containers. The grid underneath is loose, not rigid. Whitespace feels like outdoor air.",
    },
    "retrotech": {
        "id": "retrotech",
        "name": "Retro-Tech",
        "desc": "Terminal, grid-based, nostalgic edge",
        "swatches": ["#0a0f08", "#39ff14", "#ff6b35", "#1a1a1a"],
        "dna": "Retro-Tech/Brutalist-Digital: The grid is visible and celebrated — column lines show, structure is exposed rather than hidden. Monospace typography everywhere enforces rhythm and signals precision. Terminal greens and ambers on near-black reference early computing without being nostalgic. Copy reads like documentation — direct, numbered, no ornament. Every line is functional. The aesthetic communicates expertise and transparency — nothing hidden behind polish. Influence: early web, Figma early branding, Stripe documentation, Linear.",
        "spatial_dna": "The grid is exposed and celebrated. Column lines are visible. Content sits inside a visible structure like data in a terminal. Sections have headers that look like file directories. Horizontal rules divide content like command separators. Nothing is decorative — every line is structural. The page reads top to bottom like a log file. Monospace everywhere enforces rhythm.",
    },
    "corporate": {
        "id": "corporate",
        "name": "Corporate Elite",
        "desc": "Authority, power, institutional trust",
        "swatches": ["#001f4e", "#c8a94a", "#f0f4fa", "#1a2b4a"],
        "dna": "Corporate Elite: Authority is communicated before content is read — structured grid, controlled whitespace, serif headline type at institutional weight. Statistics and credentials displayed large as proof not decoration. Copy is measured and authoritative — complex sentences that demonstrate mastery, passive voice used deliberately to signal objectivity. Deep navy or charcoal backgrounds communicate seriousness and stability. Gold accents signal premium without excess. The brand communicates that it has been here before and will be here after. Influence: Goldman Sachs, McKinsey, NASA, J.P. Morgan, Skadden Arps.",
        "spatial_dna": "Structure signals authority. Content is precisely aligned to an invisible 12-column grid. Statistics and numbers are displayed large as proof statements. Above the fold contains the full value proposition — no mystery, no revelation. Whitespace is controlled not generous. Everything is justified to the grid. The page communicates reliability through repetition and order.",
    },
    "playful": {
        "id": "playful",
        "name": "Playful",
        "desc": "Rounded, vibrant, expressive type",
        "swatches": ["#ff6fb7", "#ffd93d", "#6bcb77", "#4d96ff"],
        "dna": "Playful/Vibrant: Rules exist to be bent visibly — elements tilt, cards bounce on hover, colors surprise. Rounded shapes communicate safety and approachability. Copy is conversational and uses contractions — sounds like a smart friend not a brand. Bright saturated palette where multiple colors coexist without fighting. Micro-interactions reward attention. The brand is in on the joke with you. Joy is not an afterthought — it is the primary communication. Influence: Duolingo, Notion early branding, Mailchimp, early Slack, Figma.",
        "spatial_dna": "Rules exist to be bent visibly. Elements are slightly off-center in ways that feel intentional. Cards tilt on hover. Sections have irregular heights. Illustrations break out of their zones. The page has rhythm like music — some beats are louder. Color zones are unequal. The layout feels handmade even though it is precise. Surprise is a design principle.",
    },
    "brutalist": {
        "id": "brutalist",
        "name": "Brutalist",
        "desc": "Raw, unconventional, visible structure",
        "swatches": ["#fff", "#000", "#ff0000", "#f5f500"],
        "dna": "Brutalist: Raw structure IS the aesthetic — 2px black borders define space instead of padding, visible grid lines are design elements not guides, the underlying HTML structure shows through intentionally. Copy is blunt and direct — no softening language, no hedging, declarative statements that end conversations. Primary colors used as aggressive signals not brand choices. Anti-decoration: if an element does not carry meaning it does not exist. Confrontational by design — the brand refuses the comfortable expectation. Influence: Bloomberg, Balenciaga digital, architectural brutalism.",
        "spatial_dna": "Space is not given — it is earned through structure. Elements touch their containers. Borders are the design, not the edges of design. Nothing floats in space — everything is anchored by a visible structural rule. Sections are defined by hard borders not padding. The absence of decoration IS the decoration. Raw containment. Grid lines visible.",
    },
}


# ─── ACCENT LIBRARY — port from accentLibrary.ts ──────────────────────

# Representative subset — full library is generative TS functions taking
# (color, opacity, size). Session 2's renderers will inline these directly
# or call thin Python adapters that emit equivalent SVG/CSS strings.
# Keys mirror the TS AccentDefinition style+label tuples.

ACCENT_LIBRARY: Dict[str, Dict[str, List[Dict[str, str]]]] = {
    "dividers": {
        "ceremonial": [
            {
                "label": "Gold Rule",
                "description": "Thin horizontal rule with center diamond",
                "template": '<div style="position:relative;height:20px;display:flex;align-items:center;margin:2rem 0;opacity:{opacity};"><div style="flex:1;height:1px;background:{color};"></div><svg width="12" height="12" viewBox="0 0 12 12" style="margin:0 12px;flex-shrink:0;"><rect x="6" y="0" width="6" height="6" transform="rotate(45 6 6)" fill="{color}"/></svg><div style="flex:1;height:1px;background:{color};"></div></div>',
            },
        ],
        "cultural-african": [
            {
                "label": "Kente Strip",
                "description": "Geometric kente-inspired divider",
                "template": '<div style="height:8px;margin:2rem 0;opacity:{opacity};background:repeating-linear-gradient(90deg,{color} 0px,{color} 8px,transparent 8px,transparent 16px,{color}80 16px,{color}80 20px,transparent 20px,transparent 28px);"></div>',
            },
        ],
        "editorial": [
            {
                "label": "Double Rule",
                "description": "Editorial double hairline",
                "template": '<div style="margin:2rem 0;opacity:{opacity};"><div style="height:3px;background:{color};margin-bottom:3px;"></div><div style="height:1px;background:{color};"></div></div>',
            },
        ],
        "structural": [
            {
                "label": "Hard Rule",
                "description": "Brutalist hard border",
                "template": '<div style="height:4px;background:{color};margin:2rem 0;opacity:{opacity};"></div>',
            },
        ],
        "botanical": [
            {
                "label": "Leaf Vine",
                "description": "Organic botanical divider",
                "template": '<div style="display:flex;align-items:center;margin:2rem 0;opacity:{opacity};"><div style="flex:1;height:1px;background:{color}40;"></div><svg width="60" height="20" viewBox="0 0 60 20" style="margin:0 8px;flex-shrink:0;" fill="none" stroke="{color}" stroke-width="1"><path d="M5,10 Q15,2 30,10 Q45,18 55,10"/><path d="M20,10 Q25,4 30,10"/><path d="M30,10 Q35,16 40,10"/></svg><div style="flex:1;height:1px;background:{color}40;"></div></div>',
            },
        ],
    },
    "textures": {
        "minimal": [
            {
                "label": "Dot Grid",
                "description": "Minimal dot grid texture",
                "css": "background-image:radial-gradient(circle,{color} 1px,transparent 1px);background-size:24px 24px;background-position:0 0;opacity:{opacity};",
            },
        ],
        "cultural-african": [
            {
                "label": "Kente Grid",
                "description": "Geometric kente-inspired grid pattern",
                "css": "background-image:repeating-linear-gradient(0deg,transparent,transparent 20px,{color}{opacity_hex} 20px,{color}{opacity_hex} 21px),repeating-linear-gradient(90deg,transparent,transparent 20px,{color}{opacity_hex} 20px,{color}{opacity_hex} 21px);",
            },
        ],
    },
    "corners": {
        "structural": [
            {
                "label": "Bracket Corners",
                "description": "L-shaped corner brackets",
                "template": '<div style="position:absolute;inset:0;pointer-events:none;"><div style="position:absolute;top:0;left:0;width:24px;height:24px;border-top:2px solid {color};border-left:2px solid {color};opacity:{opacity};"></div><div style="position:absolute;top:0;right:0;width:24px;height:24px;border-top:2px solid {color};border-right:2px solid {color};opacity:{opacity};"></div><div style="position:absolute;bottom:0;left:0;width:24px;height:24px;border-bottom:2px solid {color};border-left:2px solid {color};opacity:{opacity};"></div><div style="position:absolute;bottom:0;right:0;width:24px;height:24px;border-bottom:2px solid {color};border-right:2px solid {color};opacity:{opacity};"></div></div>',
            },
        ],
    },
}


# ─── IMAGE COMPOSITION — port from imageComposition.ts ────────────────

# Per-strand image presentation rules. Session 2 will use these to wrap
# product/gallery/hero images with consistent treatments per strand.

IMAGE_COMPOSITION: Dict[str, Dict[str, str]] = {
    "luxury": {
        "container": "rectangular 3/4 aspect",
        "frame_css": "border: 1px solid var(--accent); padding: 16px;",
        "hover_css": "filter: brightness(1.05); transition: filter 0.6s cubic-bezier(0.23,1,0.32,1);",
        "spatial_css": "padding: clamp(2rem, 4vw, 4rem);",
        "design_notes": "Gallery mat effect — thin accent border with generous padding between border and image. No border-radius. Hover is subtle brightness shift; luxury does not move.",
    },
    "editorial": {
        "container": "rectangular full-width",
        "frame_css": "border-bottom: 1px solid var(--text);",
        "hover_css": "transform: translateY(-2px); transition: transform 0.4s ease;",
        "spatial_css": "margin: 4rem 0;",
        "design_notes": "Image runs to the edge with a hairline rule below. Movement is slight; the page still reads like a magazine.",
    },
    "bold": {
        "container": "rectangular full-bleed",
        "frame_css": "border: 4px solid var(--text);",
        "hover_css": "transform: scale(1.02); transition: transform 0.3s ease;",
        "spatial_css": "margin: 0;",
        "design_notes": "Hard border, full bleed, no padding. The image is part of the structural composition.",
    },
    "minimal": {
        "container": "rectangular 4/5 aspect",
        "frame_css": "border: none;",
        "hover_css": "opacity: 0.92; transition: opacity 0.3s ease;",
        "spatial_css": "padding: clamp(1rem, 2vw, 2rem);",
        "design_notes": "No frame. White space around the image is the frame.",
    },
    "dark": {
        "container": "rectangular 16/9 aspect",
        "frame_css": "box-shadow: 0 24px 64px rgba(0,0,0,0.4), 0 0 40px color-mix(in srgb, var(--accent) 12%, transparent);",
        "hover_css": "transform: scale(1.01); transition: transform 0.5s ease;",
        "spatial_css": "padding: 2rem;",
        "design_notes": "Glow + shadow — image emits light into the dark surrounding space.",
    },
    "organic": {
        "container": "rounded 1/1 aspect",
        "frame_css": "border-radius: 24px; overflow: hidden;",
        "hover_css": "transform: rotate(-1deg); transition: transform 0.4s ease;",
        "spatial_css": "padding: 1.5rem;",
        "design_notes": "Rounded corners, slight tilt on hover. Feels handmade.",
    },
    "retrotech": {
        "container": "rectangular 1/1 aspect",
        "frame_css": "border: 1px solid var(--accent); filter: contrast(1.1) saturate(0.85);",
        "hover_css": "filter: contrast(1.2) saturate(1) hue-rotate(2deg); transition: filter 0.2s ease;",
        "spatial_css": "padding: 8px;",
        "design_notes": "Hairline border, subtle desaturation, hover shift mimics CRT recalibration.",
    },
    "corporate": {
        "container": "rectangular 16/9 aspect",
        "frame_css": "border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);",
        "hover_css": "transform: translateY(-2px); transition: transform 0.3s ease;",
        "spatial_css": "padding: 2rem;",
        "design_notes": "Hairline border, subtle lift. Professional, never showy.",
    },
    "playful": {
        "container": "rounded 4/5 aspect",
        "frame_css": "border-radius: 28px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);",
        "hover_css": "transform: scale(1.04) rotate(-2deg); transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);",
        "spatial_css": "padding: 1.25rem;",
        "design_notes": "Rounded, elastic hover, slight tilt. Movement is invitation.",
    },
    "brutalist": {
        "container": "rectangular full-bleed",
        "frame_css": "border: 4px solid var(--text); filter: grayscale(0.3);",
        "hover_css": "filter: grayscale(0); transition: filter 0.2s ease;",
        "spatial_css": "padding: 0;",
        "design_notes": "Thick black border, slight desaturation by default, hover restores color. Hard structural framing.",
    },
}


# ─── CRAFT TECHNIQUES — port from craftTechniques.ts ──────────────────

CRAFT_TECHNIQUES: Dict[str, str] = {
    "stat_counter": """
function animateCounters() {
  document.querySelectorAll('[data-counter]').forEach(el => {
    const target = parseInt(el.dataset.counter);
    const suffix = el.textContent.replace(/[0-9]/g, '');
    let current = 0;
    const step = Math.ceil(target / 40);
    const timer = setInterval(() => {
      current += step;
      if (current >= target) { current = target; clearInterval(timer); }
      el.textContent = current + suffix;
    }, 30);
  });
}
""",
    "scroll_header": """
const header = document.querySelector('.site-header');
if (header) {
  window.addEventListener('scroll', () => {
    header.classList.toggle('scrolled', window.scrollY > 60);
  }, { passive: true });
}
""",
    "stagger_reveal": """
const staggerObserver = new IntersectionObserver((entries) => {
  const visible = entries.filter(e => e.isIntersecting);
  visible.forEach((entry, i) => {
    setTimeout(() => entry.target.classList.add('visible'), i * 100);
    staggerObserver.unobserve(entry.target);
  });
}, { threshold: 0.1 });
document.querySelectorAll('.reveal').forEach(el => staggerObserver.observe(el));
""",
    "focus_ring": """
input:focus, select:focus, textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 8%, transparent);
  outline: none;
}
""",
    "card_lift_hover": """
.card:hover {
  transform: translateY(-4px);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--accent) 15%, transparent),
    0 18px 40px rgba(0,0,0,0.25),
    0 0 20px color-mix(in srgb, var(--accent) 6%, transparent);
}
""",
    "portfolio_overlay": """
.overlay {
  background: linear-gradient(180deg, rgba(0,0,0,0.05), rgba(0,0,0,0.7));
}
""",
    "reduced_motion": """
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .reveal { opacity: 1; transform: none; }
}
""",
}


# ─── AESTHETIC PRESETS — port from aestheticPresets.ts (representative) ───

# Studio's full preset catalog is large and overlaps heavily with vocabularies
# + curated palettes. Smart Sites consumes vocabularies directly, so this
# section keeps just enough preset metadata to surface in the editor as
# named "looks" the user can pick. Not load-bearing for v1 rendering.

AESTHETIC_PRESETS: Dict[str, Dict[str, Any]] = {
    "founder-spotlight": {
        "id": "founder-spotlight",
        "name": "Founder Spotlight",
        "tagline": "Gold & Bold — Your Story, Front and Center",
        "vocabulary_match": ["sovereign-authority", "established-authority", "legacy-builder"],
        "layout_match": ["empire-platform", "throne", "authority"],
        "font_pairing": "oswald-open-sans",
        "best_for": ["personal brand", "consultant", "coach", "founder-led business"],
    },
    "warm-sanctuary": {
        "id": "warm-sanctuary",
        "name": "Warm Sanctuary",
        "tagline": "Soft Earth Tones — Healing, Trust, Restoration",
        "vocabulary_match": ["wellness-healing", "warm-community", "organic-natural"],
        "layout_match": ["story-arc", "community-hub"],
        "font_pairing": "lora-source-sans",
        "best_for": ["therapist", "wellness practitioner", "retreat", "spa"],
    },
    "kingdom-platform": {
        "id": "kingdom-platform",
        "name": "Kingdom Platform",
        "tagline": "Sacred Authority — Ministry With Weight",
        "vocabulary_match": ["faith-ministry", "legacy-builder", "sovereign-authority"],
        "layout_match": ["empire-platform", "movement", "throne"],
        "font_pairing": "cinzel-libre-baskerville",
        "best_for": ["pastor", "ministry", "faith leader", "speaker"],
    },
    "studio-portfolio": {
        "id": "studio-portfolio",
        "name": "Studio Portfolio",
        "tagline": "Work-Forward — Let The Art Speak",
        "vocabulary_match": ["creative-artist", "expressive-vibrancy", "editorial"],
        "layout_match": ["studio-portfolio", "gallery", "magazine"],
        "font_pairing": "abril-poppins",
        "best_for": ["designer", "photographer", "agency", "artist"],
    },
    "scholar-platform": {
        "id": "scholar-platform",
        "name": "Scholar Platform",
        "tagline": "Credibility First — Knowledge as Brand",
        "vocabulary_match": ["scholar-educator", "established-authority", "universal-premium"],
        "layout_match": ["authority", "story-arc"],
        "font_pairing": "merriweather-inter",
        "best_for": ["course creator", "educator", "thought leader", "author"],
    },
}


# ─── HELPERS ─────────────────────────────────────────────────────────


def get_vocabulary(vocab_id: str) -> Optional[CulturalVocabulary]:
    return VOCABULARIES.get(vocab_id)


def get_layout(layout_id: str) -> Optional[LayoutStyle]:
    return LAYOUTS.get(layout_id)


def get_layouts_for_vocabulary(vocab_id: str) -> List[LayoutStyle]:
    layout_ids = VOCAB_LAYOUT_MAP.get(vocab_id, [])
    return [LAYOUTS[lid] for lid in layout_ids if lid in LAYOUTS]


def all_vocabulary_ids() -> List[str]:
    return list(VOCABULARIES.keys())


def all_layout_ids() -> List[str]:
    return list(LAYOUTS.keys())


def get_font_pairing(pairing_id: str) -> Optional[FontPairing]:
    return FONT_PAIRINGS.get(pairing_id)


def detect_font_pairing(vocabulary_id: str, layout_id: str) -> FontPairing:
    """Port of fontLibrary.ts:detectFontPairing — vocab match = 2 pts, layout match = 1 pt."""
    best = next(iter(FONT_PAIRINGS.values()))
    best_score = -1
    for fp in FONT_PAIRINGS.values():
        score = 0
        if vocabulary_id in fp["vocabulary_match"]:
            score += 2
        if layout_id in fp["layout_match"]:
            score += 1
        if score > best_score:
            best_score = score
            best = fp
    return best


# ─── INTEGRITY ASSERTIONS ─────────────────────────────────────────────
# Run at import time. If any fail, the port is incomplete.

assert len(VOCABULARIES) == 23, f"Expected 23 vocabularies, got {len(VOCABULARIES)}"
assert len(LAYOUTS) == 12, f"Expected 12 layouts, got {len(LAYOUTS)}"
assert len(VOCAB_LAYOUT_MAP) == 23, f"Expected 23 vocab→layout mappings, got {len(VOCAB_LAYOUT_MAP)}"
for _vocab_id in VOCABULARIES:
    assert _vocab_id in VOCAB_LAYOUT_MAP, f"Vocab {_vocab_id} missing from VOCAB_LAYOUT_MAP"
    for _lid in VOCAB_LAYOUT_MAP[_vocab_id]:
        # 'organic' appears in indigenous-earth's affinity in the source TS but
        # is not a real layout — it's a typo/legacy reference. Tolerate it by
        # stripping during access (get_layouts_for_vocabulary already filters).
        if _lid not in LAYOUTS and _lid != "organic":
            raise AssertionError(f"Vocab {_vocab_id} maps to unknown layout {_lid}")
assert len(FONT_PAIRINGS) == 12, f"Expected 12 font pairings, got {len(FONT_PAIRINGS)}"
assert len(STYLE_STRANDS) == 10, f"Expected 10 style strands, got {len(STYLE_STRANDS)}"
