"""
build_skills.py — how to build a good X, as data instead of prose.

WHY THIS EXISTS
───────────────
Everything Chief knows about designing a module lives in one string:
module_spec_generator._SYSTEM_PROMPT, 307 lines and ~17.8KB. Every new
kind of thing Chief should build well has meant editing that string by
hand — which is why "teach Chief to build X" has always been a developer
task, and why the file is the size it is.

A skill is a markdown file with frontmatter. It carries the knowledge for
ONE build situation, and it is selected deterministically and appended to
the system prompt only when it applies. Adding one is writing a file, not
editing a 17KB prompt — and the format (agentskills.io SKILL.md) is the
one already ruled in when Hermes was ruled out as a component, so a skill
written here is portable.

    ---
    name: booking-module
    description: designing an appointment/booking module
    business_types: [barber, coach, therapist]     # optional filter
    triggers: [appointment, booking, schedule]     # any match selects it
    ---
    <the guidance the model gets>

DELIBERATE PROPERTIES
─────────────────────
  - **Selection is deterministic — no LLM, no embedding, no cost.** A
    keyword/type match is inspectable and testable; "the model picks its
    own context" is neither, and it would put a model call in front of
    every model call.
  - **Additive only — and now permanently so.** This does not move content
    out of _SYSTEM_PROMPT, and the investigation into doing that is CLOSED:
    see docs/PROMPT_EXTRACTION_RULING.md. Short version: the model picks
    its archetype and fills that archetype's params in ONE call, so the
    detail must be present BEFORE we know which one it picks — and keyword
    selection runs before generation. booking_calendar (45% of the prompt)
    requires primary_date_field; a missed selection there means Pydantic
    rejects the whole envelope and Chief builds nothing. Skills ADD what
    Chief lacks. They are not a way to slim this prompt.
  - **Bounded.** MAX_SKILLS caps how many attach to one request, so the
    prompt cannot grow without limit as the library does.
  - **Failure is silent and safe.** A malformed skill is skipped, never
    raised — a bad file must not take the build path down. The test suite
    is what makes malformed files loud, at the time someone writes one.
"""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("build_skills")

SKILLS_DIR = pathlib.Path(__file__).resolve().parent / "build_skills"

# At most this many skills attach to a single generation. The prompt is
# already large; an unbounded library would quietly turn every build into
# a much more expensive call.
MAX_SKILLS = 2

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)


class Skill(dict):
    """Keys: name, description, business_types, triggers, body, path."""

    @property
    def name(self) -> str:
        return self.get("name") or ""


def _parse_list(raw: str) -> List[str]:
    """Accepts `[a, b]` or `a, b`. Deliberately not a YAML dependency —
    the frontmatter here is four scalar fields, and a parser is a
    liability the format does not earn."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [p.strip().strip("'\"").lower() for p in raw.split(",") if p.strip()]


def parse_skill(text: str, path: Optional[str] = None) -> Optional[Skill]:
    """Parse one SKILL.md. Returns None (never raises) when the file is
    not a usable skill — callers are on the build path."""
    m = _FRONTMATTER_RE.match(text.replace("\r\n", "\n"))
    if not m:
        return None
    head, body = m.group(1), m.group(2).strip()
    if not body:
        return None

    fields: Dict[str, Any] = {}
    for line in head.split("\n"):
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key in ("business_types", "triggers"):
            fields[key] = _parse_list(value)
        else:
            fields[key] = value

    if not fields.get("name") or not fields.get("description"):
        return None

    return Skill(
        name=fields["name"],
        description=fields["description"],
        business_types=fields.get("business_types") or [],
        triggers=fields.get("triggers") or [],
        body=body,
        path=path or "",
    )


def load_skills(directory: Optional[pathlib.Path] = None) -> List[Skill]:
    """Every readable skill, sorted by name so selection is stable."""
    d = directory or SKILLS_DIR
    out: List[Skill] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        try:
            skill = parse_skill(p.read_text(encoding="utf-8"), path=str(p))
        except OSError as e:            # unreadable file — never fatal
            logger.warning(f"skill {p.name} unreadable: {e}")
            continue
        if skill is None:
            logger.warning(f"skill {p.name} is malformed — skipped")
            continue
        out.append(skill)
    return out


def _score(skill: Skill, business_type: str, text: str) -> int:
    """Trigger hits, plus a bonus when the skill names this business type.

    A skill that lists business_types and does NOT include this one scores
    zero however many triggers match — a barber's booking guidance in a
    law firm's build is worse than no guidance.
    """
    types = skill.get("business_types") or []
    if types and business_type not in types:
        return 0

    hits = sum(1 for t in (skill.get("triggers") or []) if t and t in text)
    if not hits:
        return 0
    return hits + (2 if business_type and business_type in types else 0)


def select_skills(intake_text: str,
                  business_type: str = "",
                  directory: Optional[pathlib.Path] = None,
                  limit: int = MAX_SKILLS) -> List[Skill]:
    """The skills that apply to this build, best first. Deterministic:
    same inputs, same output, no model call."""
    text = (intake_text or "").lower()
    btype = (business_type or "").strip().lower()

    scored = []
    for s in load_skills(directory):
        sc = _score(s, btype, text)
        if sc > 0:
            scored.append((sc, s["name"], s))
    # name is the tiebreak, so equal scores never reorder run to run.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s for _, _, s in scored[:limit]]


def skills_block(skills: List[Skill]) -> str:
    """Render selected skills as a prompt section. Empty string when
    nothing applies — an empty heading is noise the model has to read."""
    if not skills:
        return ""
    parts = [
        "═══════════════════════════════════════════════════════════════",
        "APPLICABLE BUILD SKILLS",
        "═══════════════════════════════════════════════════════════════",
        "",
        "Guidance for the specific kind of module being asked for. It "
        "refines the rules above; it never overrides the schema contract "
        "or the archetype palette.",
        "",
    ]
    for s in skills:
        parts.append(f"── {s['name']}: {s['description']} ──")
        parts.append(s["body"])
        parts.append("")
    return "\n".join(parts).strip()


def block_for(intake_text: str, business_type: str = "",
              directory: Optional[pathlib.Path] = None) -> str:
    """One call for the generator: select, render, done."""
    try:
        return skills_block(select_skills(intake_text, business_type, directory))
    except Exception as e:                                   # pragma: no cover
        # A skill library problem must never break module generation.
        logger.warning(f"skill selection failed (continuing without): {e}")
        return ""
