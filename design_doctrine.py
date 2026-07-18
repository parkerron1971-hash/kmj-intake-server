# design_doctrine.py
# ─────────────────────────────────────────────────────────────────────
# THE DOCTRINE — Kimi K3 Design Integration, Phase 1 (Kevin's spec,
# 2026-07-18). One shared law block that becomes part of the system
# prompt on every creative stage, FOR BOTH PROVIDERS.
#
# THE SYMMETRY RULE (from the spec, load-bearing): prompt content is
# NEVER gated on provider. The only provider-specific deltas are
# transport-level (sampling params; Kimi's reasoning-token headroom),
# both handled inside site_llm. If prompt text differed by provider, a
# mid-build fallback would produce a Frankenstein build — early stages
# designed under the doctrine, later stages composed without it.
#
# Return point: git tag `return-point-pre-kimi-design` on both repos.
# ─────────────────────────────────────────────────────────────────────

DOCTRINE = """THE DOCTRINE (design law for every creative decision in this system)

D1 FLOOR, NOT CEILING. Every stated constraint in the brief is honored
verbatim. Then you add. Restating the brief back is failure.
D2 STATED = EVIDENCE. Every stated detail implies an unstated decision.
Derive it, state the derivation, then obey both. (Example shape:
"eyebrow flanked by rules" → implies centered composition → hero is
centered, not left-aligned.)
D3 MOTIF PROPAGATION. Every accent color appears at least once per
screenful as a NON-typographic material: a glow, rule, tag, divider,
icon ground, or hover state. Accents that live only in type read as
template.
D4 THE ECHO RULE. The loudest typographic moment on the page gets one
atmospheric echo (glow, tint, or texture in its own color) elsewhere
in the same viewport. Loud type floating in dead space is unfinished.
D5 ONE RHYTHM. All vertical spacing comes from the page's spacing scale.
No ad-hoc margins. Rhythm breaks only at intentional section seams.
D6 RESTRAINT BUDGET. At most two accent behaviors active per section.
One section per page is deliberately quiet (the hard silence). If
everything shouts, nothing is heard.
D7 MOTION IS PHYSICS. Durations 0.25-0.7s, ease-out cubic or softer,
stagger 60-90ms, hover lift 2-5px, scroll reveals ~20px. Animate
opacity and transform only. Nothing bounces unless the brief says
playful.
D8 CONTRAST OF SCALE. Each viewport gets one oversized element against
restrained surroundings. Big type earns its size; small details stay
small.
D9 PROMINENCE FOLLOWS WEIGHT. Layout prominence is allocated by business
weight (identity offering vs. revenue offering vs. proof), never
evenly. Even distribution is the builder look.
D10 REAL OR REMOVED. Never invent proof: no fake clients, projects,
stats, or testimonials. Sample content is labeled as sample. A
section with no real data removes itself. (System rule #2 governs;
this doctrine may never override it.)
D11 TEMPLATE SMELLS (banned): purple-blue gradient heroes; three-icon
feature rows with generic copy; centered-everything monotony; stock
handshake imagery; cold blue on dark; lorem-flavored filler; identical
cards with swapped icons and no hierarchy.
D12 COMPOSE, DON'T PICK. Wherever a spec offers axes, compose across
them. Where it doesn't, author within the doctrine. Never select the
first adequate option."""

# K1 — instructed diversity. On Kimi it replaces temperature (the API
# rejects sampling params); on Claude it stacks with temperature
# harmlessly. Appended to every creative call, both providers.
DIVERSITY_LINE = (
    "Consider three materially different directions before answering. "
    "Ship the boldest coherent one. The safest adequate option is a "
    "failure mode."
)

# The creative contract, restated in doctrine terms (spec §4-A).
CREATIVE_CONTRACT = """THE CREATIVE CONTRACT
- The practitioner's answers are the floor, not the ceiling. Honor every
  one; then add your own taste on top. Never merely restate them.
- Sections on the same page must not look like siblings. Vary composition,
  density, and where the eye lands first — while sharing one palette, one
  type system, one rhythm.
- REAL DATA is law. Names, prices, quotes, and stats in the REAL DATA
  block are used exactly. Anything not there is not invented; it is
  omitted. (D10)"""


def with_doctrine(system_prompt: str) -> str:
    """Prepend the shared doctrine to a stage's system prompt."""
    return DOCTRINE + "\n\n" + system_prompt


def art_direction_string(enriched_brief=None, designer_pick=None) -> str:
    """One deterministic art-direction string per build (spec §3-I) —
    prefixed to every Unsplash query and generation prompt so the image
    set coheres as one shoot instead of six strangers. No LLM call."""
    brief = enriched_brief or {}
    pick = designer_pick or {}
    vibe = str(brief.get("inferred_vibe") or "").lower()
    accent = str(pick.get("accent_style") or "").lower()

    if any(w in vibe for w in ("bold", "dramatic", "electric", "confident")):
        light = "dramatic contrast lighting"
    elif any(w in vibe for w in ("warm", "cozy", "earthy", "heritage")):
        light = "golden-hour warmth"
    elif any(w in vibe for w in ("calm", "quiet", "minimal", "soft", "serene")):
        light = "soft diffused light"
    elif any(w in vibe for w in ("luxur", "premium", "elegant")):
        light = "moody studio lighting"
    else:
        light = "natural editorial lighting"

    material = ("crisp geometric accents" if accent in ("block_mark", "block")
                else "soft organic accents" if accent in ("soft_rule", "soft")
                else "fine hairline details")

    return f"{light}, {material}, consistent art direction, one cohesive photo shoot"
