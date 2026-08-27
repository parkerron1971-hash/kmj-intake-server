"""
workspace_archetypes.py — the one decision Chief makes in phase one.

Chief reads the intake answers and picks one of five presets. It does not
compose, it does not author blocks, it does not invent a sixth archetype.
Classification, and then it shows its work.

Deterministic on purpose — no LLM call. Three reasons: the same intake must
always land on the same workspace (a practitioner who re-runs onboarding and
gets a different building is looking at a bug), a model is not needed to
tell a barbershop from a law firm, and a rule that fires can be NAMED in the
narration. "You said chairs and walk-ins" is a better explanation than
"I thought so", and the override is only meaningful if the user can see what
Chief actually keyed on.

Signals, strongest first:

  1 declared vertical   the onboarding picker's business type, resolved
                        through vertical_registry so aliases count
  2 keyword evidence    weighted terms found in the free-text answers
  3 shape evidence      what they said they schedule, and against what

A tie or a thin margin lowers confidence; it never blocks. Chief always
picks something, says why, and leaves the override in plain sight.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import workspace_layouts

logger = logging.getLogger("workspace_archetypes")

ARCHETYPES = workspace_layouts.ARCHETYPES

# Fallback when the intake says essentially nothing. `consultant` is the
# least wrong default: a stage-sorted docket is the shape that degrades
# most gracefully for a business we know nothing about, because every
# business has work at stages, and not every business has chairs or a
# congregation.
DEFAULT_ARCHETYPE = "consultant"


# ─── signal 1: the declared vertical ─────────────────────────────────
# Weighted heavily. Someone who picked "Lawyer / Law Firm" in the picker
# has told us more than any adjective in a text box will.
VERTICAL_WEIGHT = 10.0

# Verticals that don't own an archetype outright still lean somewhere. A
# therapist runs a chair-shaped day; a creative agency runs engagements.
VERTICAL_LEAN: Dict[str, Dict[str, float]] = {
    "personal_services":  {"salon": 10.0},
    "lawyer":             {"law_firm": 10.0},
    "ministry":           {"ministry": 10.0},
    "nonprofit":          {"nonprofit": 10.0},
    "consultant":         {"consultant": 10.0},
    "coach":              {"consultant": 8.0},
    "contractor":         {"trades": 10.0},
    "therapist":          {"therapist": 10.0},
    "fitness_wellness":   {"salon": 6.0, "consultant": 3.0},
    "counselor":          {"therapist": 10.0},
    "psychologist":       {"therapist": 10.0},
    "charity":            {"nonprofit": 10.0},
    "foundation":         {"nonprofit": 8.0},
    "creative":           {"consultant": 7.0},
    "course_creator":     {"consultant": 6.0},
    "financial_educator": {"consultant": 6.0},
    "service_provider":   {"consultant": 4.0, "trades": 3.0},
    "custom":             {},

    # `personal_services` is the canonical key but carries no aliases in
    # vertical_registry, so a practitioner who typed "barbershop" arrives
    # here unresolved. These are the self-descriptions that actually show
    # up in intake, mapped straight through rather than left to the
    # keyword pass — what someone calls their business is signal 1, not
    # signal 2.
    "salon":              {"salon": 10.0},
    "barber":             {"salon": 10.0},
    "barbershop":         {"salon": 10.0},
    "hair_salon":         {"salon": 10.0},
    "spa":                {"salon": 9.0},
    "nail_salon":         {"salon": 9.0},
    "med_spa":            {"salon": 8.0},
}


# ─── signal 2: keyword evidence ──────────────────────────────────────
# Each entry is (regex, archetype, weight, what to tell the user). The
# narration string is the point — it is what Chief quotes back.
_KEYWORDS: List[Tuple[str, str, float, str]] = [
    # salon / barber
    (r"\b(salon|barber|barbershop|stylist|hairdress\w*|blowout|balayage)\b",
     "salon", 6.0, "you described a salon floor"),
    (r"\b(chair|chairs|booth rent\w*|walk[- ]?in\w*)\b",
     "salon", 4.0, "you mentioned chairs and walk-ins"),
    (r"\b(nail|lash\w*|brow\w*|barbering|spa|massage|esthetic\w*)\b",
     "salon", 3.5, "the services you listed are booked by the chair"),
    (r"\b(rebook\w*|standing appointment|every (four|six|eight) weeks)\b",
     "salon", 3.0, "you talked about clients rebooking on a cycle"),

    # law firm
    (r"\b(law firm|attorney|attorneys|lawyer|solicitor|counsel|paralegal)\b",
     "law_firm", 6.0, "you described a legal practice"),
    (r"\b(matter|matters|docket|filing|filings|litigation|deposition|discovery)\b",
     "law_firm", 5.0, "you work in matters and filings"),
    (r"\b(statute of limitations|court date|retainer agreement|iolta|trust account)\b",
     "law_firm", 4.5, "you named deadlines with legal consequences"),
    (r"\b(billable hour\w*|conflict check\w*)\b",
     "law_firm", 3.0, "you bill in hours against matters"),

    # ministry
    (r"\b(church|ministry|ministries|congregation|parish|pastor|worship|chapel)\b",
     "ministry", 6.0, "you described a congregation"),
    (r"\b(sunday|midweek|small group\w*|bible study|service times?)\b",
     "ministry", 4.0, "your week has a Sunday shape"),
    (r"\b(first[- ]time guest\w*|visitor\w*|newcomer\w*|assimilation)\b",
     "ministry", 4.0, "you care about first-time guests"),
    (r"\b(giving|tithe\w*|offering plate|volunteer\w*|serving team)\b",
     "ministry", 2.5, "you talked about giving and volunteers"),

    # consultant / coach
    (r"\b(consultan\w*|coach|coaching|advisory|advisor|strateg\w*)\b",
     "consultant", 5.5, "you described advisory work"),
    (r"\b(engagement\w*|retainer|scope of work|sow|deliverab\w*|discovery phase)\b",
     "consultant", 5.0, "you work in engagements against a retainer"),
    (r"\b(client roster|book of business|pipeline stage\w*|proposal\w*)\b",
     "consultant", 3.5, "your work moves through stages"),

    # trades
    (r"\b(contractor|contracting|plumb\w*|electric(ian|al)|hvac|roof\w*|remodel\w*)\b",
     "trades", 6.0, "you described trades work"),
    (r"\b(landscap\w*|paint\w*|carpent\w*|handyman|flooring|drywall|excavat\w*)\b",
     "trades", 5.5, "the work you named happens on site"),
    (r"\b(crew|crews|truck\w*|job site|jobsite|dispatch\w*|service call\w*)\b",
     "trades", 5.0, "you dispatch crews to sites"),
    (r"\b(deposit\w*|estimate\w*|quote\w*|change order\w*|punch list)\b",
     "trades", 3.0, "you take deposits and carry a balance"),
    (r"\b(drive time|travel time|route|routing|mileage)\b",
     "trades", 3.0, "travel between jobs is a cost you track"),
]

_COMPILED = [(re.compile(p, re.I), a, w, why) for p, a, w, why in _KEYWORDS]


# ─── signal 3: what they schedule, and against what ──────────────────
# Structured intake answers, when present, are stronger than prose.
_SHAPE_SIGNALS: Dict[str, List[Tuple[str, str, float, str]]] = {
    # answer key -> [(matching value fragment, archetype, weight, why)]
    "schedules_against": [
        ("staff", "salon", 5.0, "you schedule against named staff"),
        ("chair", "salon", 6.0, "you schedule against chairs"),
        ("crew", "trades", 6.0, "you schedule against crews"),
        ("room", "ministry", 4.0, "you schedule against rooms"),
        ("deadline", "law_firm", 6.0, "you schedule against deadlines"),
        ("stage", "consultant", 5.0, "your work moves by stage, not by clock"),
        ("nothing", "consultant", 2.0, "you do not schedule against a resource"),
    ],
    "unit_of_work": [
        ("appointment", "salon", 5.0, "your unit of work is an appointment"),
        ("matter", "law_firm", 6.0, "your unit of work is a matter"),
        ("case", "law_firm", 5.0, "your unit of work is a case"),
        ("job", "trades", 6.0, "your unit of work is a job"),
        ("engagement", "consultant", 6.0, "your unit of work is an engagement"),
        ("gathering", "ministry", 6.0, "your unit of work is a gathering"),
        ("event", "ministry", 4.0, "your unit of work is an event"),
        ("session", "consultant", 3.0, "your unit of work is a session"),
    ],
    "billing_shape": [
        ("deposit", "trades", 4.0, "you take a deposit before the work"),
        ("retainer", "consultant", 4.5, "you bill against a retainer"),
        ("trust", "law_firm", 5.0, "you hold client funds in trust"),
        ("point of sale", "salon", 4.0, "you settle at the chair"),
        ("donation", "ministry", 5.0, "your income is giving, not invoicing"),
        ("giving", "ministry", 5.0, "your income is giving, not invoicing"),
    ],
}


# Free-text answer keys worth reading. Everything else in the intake is
# ignored rather than scanned — a business name containing the word "Trust"
# should not push a barber toward a law firm.
_TEXT_KEYS = (
    "what_you_do", "description", "services", "offerings", "who_you_serve",
    "typical_week", "biggest_headache", "notes", "elevator_pitch",
    "how_you_work", "summary",
)


def _resolve_vertical(raw: Optional[str]) -> Optional[str]:
    """Canonicalise a declared business type to a key VERTICAL_LEAN knows.

    `vertical_registry.resolve` collapses anything unregistered to
    "custom", which is right for the registry and wrong here: "barbershop"
    is not a canonical vertical but it IS a clear statement about the shape
    of the business. So the raw string gets first refusal, and the registry
    is consulted only when we have no opinion of our own.
    """
    if not raw:
        return None
    v = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if v in VERTICAL_LEAN:
        return v
    try:
        import vertical_registry
        resolved = vertical_registry.resolve(v)
        # "custom" is the registry shrugging, not an answer. Keep the raw
        # string so the keyword pass still has something to work with.
        if resolved and resolved != "custom":
            return resolved
    except Exception:  # pragma: no cover - registry is a soft dependency here
        logger.debug("vertical_registry.resolve unavailable", exc_info=True)
    return v


def _text_blob(answers: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in _TEXT_KEYS:
        val = answers.get(key)
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, (list, tuple)):
            parts.extend(str(v) for v in val)
    return " \n ".join(parts)


def score(answers: Dict[str, Any]) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """Raw scores per archetype plus the signals that produced them.

    Separated from `classify` so the tests — and Chief's narration — can
    ask "what fired?" without re-running the decision.
    """
    scores: Dict[str, float] = {a: 0.0 for a in ARCHETYPES}
    signals: List[Dict[str, Any]] = []

    answers = answers or {}

    # 1. declared vertical
    vertical = _resolve_vertical(
        answers.get("vertical")
        or answers.get("business_type")
        or answers.get("type")
    )
    if vertical:
        direct = workspace_layouts.for_vertical(vertical)
        lean = VERTICAL_LEAN.get(vertical)
        if lean:
            for arch, weight in lean.items():
                scores[arch] += weight
            top = max(lean, key=lean.get) if lean else None
            if top:
                signals.append({
                    "kind": "vertical",
                    "archetype": top,
                    "weight": lean[top],
                    "why": f"you told us you are a {vertical.replace('_', ' ')}",
                })
        elif direct:
            scores[direct] += VERTICAL_WEIGHT
            signals.append({
                "kind": "vertical",
                "archetype": direct,
                "weight": VERTICAL_WEIGHT,
                "why": f"you told us you are a {vertical.replace('_', ' ')}",
            })

    # 2. keyword evidence in the free text
    blob = _text_blob(answers)
    if blob:
        for pattern, arch, weight, why in _COMPILED:
            if pattern.search(blob):
                scores[arch] += weight
                signals.append({
                    "kind": "keyword",
                    "archetype": arch,
                    "weight": weight,
                    "why": why,
                })

    # 3. structured shape answers
    for key, rules in _SHAPE_SIGNALS.items():
        raw = answers.get(key)
        if raw is None:
            continue
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        haystack = " ".join(str(v).lower() for v in values)
        for fragment, arch, weight, why in rules:
            if fragment in haystack:
                scores[arch] += weight
                signals.append({
                    "kind": "shape",
                    "archetype": arch,
                    "weight": weight,
                    "why": why,
                })

    return scores, signals


def classify(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Pick one archetype and explain the pick.

    Never raises and never returns None — an empty intake still gets a
    workspace, at low confidence, with the override in plain sight. A blank
    screen while we wait for better answers is worse than a defensible
    default the user can change in one tap.
    """
    scores, signals = score(answers or {})
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], ARCHETYPES.index(kv[0])))

    top_arch, top_score = ranked[0]
    runner_arch, runner_score = ranked[1] if len(ranked) > 1 else (None, 0.0)

    if top_score <= 0:
        top_arch, top_score = DEFAULT_ARCHETYPE, 0.0
        runner_arch, runner_score = None, 0.0
        confidence = "none"
    else:
        margin = top_score - runner_score
        if top_score >= 10 and margin >= 5:
            confidence = "high"
        elif margin >= 3:
            confidence = "medium"
        else:
            confidence = "low"

    preset = workspace_layouts.get_preset(top_arch)
    why = [s["why"] for s in signals if s["archetype"] == top_arch]
    # De-duplicate while keeping order — two keyword rules can land on the
    # same sentence and repeating it reads like padding.
    seen = set()
    why = [w for w in why if not (w in seen or seen.add(w))]

    return {
        "archetype": top_arch,
        "label": preset["label"],
        "confidence": confidence,
        "score": round(top_score, 2),
        "runner_up": runner_arch,
        "runner_up_score": round(runner_score, 2),
        "rationale": preset["rationale"],
        "evidence": why,
        "signals": signals,
        "scores": {a: round(s, 2) for a, s in scores.items()},
        "alternatives": workspace_layouts.summaries(),
    }


def narrate(decision: Dict[str, Any], *, term: Optional[Dict[str, str]] = None) -> str:
    """What Chief says out loud. Practitioner-facing: no archetype slugs, no
    primitive names, no talk of schemas or presets — the practitioner is
    being shown a workspace, not a configuration menu."""
    label = decision.get("label") or "your workspace"
    evidence = decision.get("evidence") or []
    lines: List[str] = []

    if evidence:
        if len(evidence) == 1:
            because = evidence[0]
        else:
            because = ", ".join(evidence[:-1]) + f", and {evidence[-1]}"
        lines.append(f"I've set you up as a {label} — {because}.")
    else:
        lines.append(
            f"I've set you up as a {label} to start with. I didn't have much "
            f"to go on, so this is a starting point rather than a conclusion."
        )

    lines.append(decision.get("rationale") or "")

    if decision.get("confidence") in ("low", "none") and decision.get("runner_up"):
        alt = next(
            (a for a in decision.get("alternatives") or []
             if a["archetype"] == decision["runner_up"]),
            None,
        )
        if alt:
            lines.append(
                f"It was close between this and a {alt['label']} setup. "
                f"If that sounds more like you, switch it and I'll rebuild."
            )
    else:
        lines.append("If that's not how you think about the work, change it and I'll rebuild.")

    return "\n\n".join(l for l in lines if l)
