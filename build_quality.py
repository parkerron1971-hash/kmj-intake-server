"""
build_quality.py — the second look a module proposal gets before the
practitioner sees it.

WHY THIS EXISTS
───────────────
The generator was one model call: generate, validate the shape, show the
card. Validation says "this will render"; it says nothing about whether
the module is GOOD — whether a tracker landed on the plain list when the
palette had a tracker, whether "tell me when they hit 720" produced a
trigger, whether the empty state says "No data yet". Kevin's ask
(2026-09-05): not just able to build, able to build things that are
creative, needed and great quality.

This is the critique. It is DETERMINISTIC — a rubric over the produced
specs and the intake, no model call — so it is testable, free, and the
same every time. The generator runs it after validation and, when it
finds something worth fixing, asks the model ONCE to revise with the
findings spelled out; it keeps the revision only if it validates and
scores no worse. The eval harness prints the same findings, so quality
is measured, not felt.

A finding is advice to the model, phrased as the instruction that would
have prevented it. Severity:
  revise — worth a second call (the archetype, a missing trigger, a
           generic feel)
  note   — recorded, not acted on (taste, minor)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import build_skills

# A skill that fires on the intake is a strong signal for the archetype
# the shape wants. Selected before generation, compared after.
SKILL_ARCHETYPE: Dict[str, str] = {
    "tracker-module": "progress_tracker",
    "pipeline-module": "work_pipeline",
    "booking-module": "booking_calendar",
}

# Words in an intake that mean the practitioner wants to be TOLD.
_ALERT_WORDS = re.compile(
    r"\b(remind|reminder|alert|notify|notification|tell me|let me know|"
    r"flag|warn|heads.?up|ping me|the day someone|when (?:someone|they|it)|"
    r"overdue|late|expir)\w*", re.I)

# Empty-state lines that say nothing. The rubric forbids them; this
# catches the ones that slip through.
_GENERIC_EMPTY = re.compile(
    r"^\s*(no (data|entries|items|records|rows)( yet)?|nothing (here|yet)|"
    r"empty|get started|add (an|your first) (entry|item|record))\.?\s*$", re.I)

_PERSON_NAMES = {"client", "customer", "member", "student", "patient",
                 "donor", "volunteer", "attendee", "guest", "tenant", "party"}


@dataclass
class Finding:
    code: str
    severity: str            # 'revise' | 'note'
    spec: Optional[str]      # slug, or None when it is about the proposal as a whole
    message: str             # the instruction that would have prevented it

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "severity": self.severity,
                "spec": self.spec, "message": self.message}


@dataclass
class QualityReport:
    findings: List[Finding] = field(default_factory=list)

    @property
    def needs_revision(self) -> bool:
        return any(f.severity == "revise" for f in self.findings)

    @property
    def score(self) -> int:
        """Lower is better: a revise counts 3, a note 1."""
        return sum(3 if f.severity == "revise" else 1 for f in self.findings)

    def as_dict(self) -> Dict[str, Any]:
        return {"needs_revision": self.needs_revision, "score": self.score,
                "findings": [f.as_dict() for f in self.findings]}

    def revision_block(self) -> str:
        """What the model is told on the second pass."""
        lines = ["REVISE — a review of your proposal found these. Fix each one "
                 "and return the whole envelope again (every spec, every field):"]
        for f in self.findings:
            if f.severity != "revise":
                continue
            where = f" [{f.spec}]" if f.spec else ""
            lines.append(f"  - {f.code}{where}: {f.message}")
        lines.append("Keep everything that was already right. Do not add fields "
                     "the intake did not ask for to satisfy a finding.")
        return "\n".join(lines)


def _fields(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    sch = spec.get("schema") or {}
    return [f for f in (sch.get("fields") or []) if isinstance(f, dict)]


def _triggers(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = spec.get("agent_config") or {}
    return [t for t in (cfg.get("triggers") or []) if isinstance(t, dict)]


def assess(specs: List[Dict[str, Any]], intake: str, business_type: str = "",
           skills: Optional[List[str]] = None) -> QualityReport:
    """The rubric. Pure: same specs + intake → same findings."""
    rep = QualityReport()
    intake = intake or ""
    specs = [s for s in (specs or []) if isinstance(s, dict)]
    if not specs:
        return rep

    # ─── The archetype the intake wanted ───────────────────────────────
    if skills is None:
        try:
            skills = [s["name"] for s in build_skills.select_skills(intake, business_type)]
        except Exception:                                    # never on the build path
            skills = []
    wanted = [SKILL_ARCHETYPE[s] for s in skills if s in SKILL_ARCHETYPE]
    used = {s.get("archetype") for s in specs}
    for arch in wanted[:1]:                                  # the best-scoring skill only
        if arch not in used and "fallback_generic" in used:
            fb = next(s for s in specs if s.get("archetype") == "fallback_generic")
            rep.findings.append(Finding(
                "archetype_fits", "revise", fb.get("slug"),
                f"the intake describes the shape {arch} is built for, but this spec "
                f"is on fallback_generic — pick archetype '{arch}' and fill its "
                f"archetype_params from the fields you already designed"))

    # ─── The alert they asked for ───────────────────────────────────────
    wants_alert = bool(_ALERT_WORDS.search(intake))
    any_trigger = any(_triggers(s) for s in specs)
    if wants_alert and not any_trigger:
        rep.findings.append(Finding(
            "no_trigger", "revise", None,
            "the practitioner asked to be told when something happens, and no "
            "spec carries a trigger — add the trigger that answers it (overdue on "
            "the date field, target_reached on a tracker, field_change on the "
            "status) with both type and action"))

    for s in specs:
        slug = s.get("slug")
        arch = s.get("archetype")
        fields = _fields(s)
        by_name = {f.get("name"): f for f in fields}
        types = {f.get("type") for f in fields}
        pres = s.get("presentation") or {}
        params = s.get("archetype_params") or {}

        # ─── A tracker's promise ────────────────────────────────────────
        if arch == "progress_tracker":
            if not any(t.get("type") == "target_reached" for t in _triggers(s)):
                rep.findings.append(Finding(
                    "tracker_no_alert", "revise", slug,
                    "a progress tracker's whole point is the moment someone crosses "
                    "the goal — add {type: target_reached, action: draft_notification}"))
            for f in fields:
                if f.get("type") == "select" and str(f.get("name", "")).lower() in (
                        "status", "progress", "stage", "on_track"):
                    rep.findings.append(Finding(
                        "tracker_status_select", "revise", slug,
                        f"remove the '{f.get('name')}' select — a tracker's state is "
                        f"computed from the numbers and a stored copy goes stale"))
            if params.get("milestones") and not (pres.get("milestone_labels") or {}):
                rep.findings.append(Finding(
                    "milestones_unnamed", "revise", slug,
                    "the milestones have no names — fill presentation.milestone_labels "
                    "with the words the trade uses for each number"))
            if not (pres.get("reached_line") or "").strip():
                rep.findings.append(Finding(
                    "no_reached_line", "revise", slug,
                    "write presentation.reached_line — what the celebration says in "
                    "the trade's words when the goal is reached"))

        # ─── A person is a link, not text ───────────────────────────────
        for f in fields:
            name = str(f.get("name", "")).lower()
            if f.get("type") == "text" and name in _PERSON_NAMES and "contact_link" not in types:
                rep.findings.append(Finding(
                    "person_as_text", "revise", slug,
                    f"'{f.get('name')}' holds a person as free text — make it "
                    f"contact_link so the same person is one person across modules"))
                break

        # ─── Finished work stops being chased ───────────────────────────
        status_sel = next((f for f in fields if f.get("type") == "select"
                           and str(f.get("name", "")).lower() in ("status", "stage")), None)
        closed = (s.get("agent_config") or {}).get("closed_statuses") or []
        if status_sel and not closed and arch != "progress_tracker":
            rep.findings.append(Finding(
                "no_closed_statuses", "revise", slug,
                f"'{status_sel.get('name')}' has options but agent_config.closed_statuses "
                f"is empty — name the finished ones so done work stops being chased"))

        # ─── The feel ───────────────────────────────────────────────────
        empty = (pres.get("empty_line") or "").strip()
        if not empty:
            rep.findings.append(Finding(
                "no_empty_line", "revise", slug,
                "write presentation.empty_line — one sentence in their voice, with a "
                "verb, about the first entry"))
        elif _GENERIC_EMPTY.match(empty):
            rep.findings.append(Finding(
                "generic_empty_line", "revise", slug,
                f"'{empty}' is the generic empty state — say what the first entry "
                f"starts, in the trade's words"))

        # ─── Taste (recorded, not acted on) ─────────────────────────────
        required = [f for f in fields if f.get("required")]
        if len(required) > 4:
            rep.findings.append(Finding(
                "many_required", "note", slug,
                f"{len(required)} required fields — a form that refuses until five "
                f"things are typed gets abandoned"))
        if len(fields) > 12:
            rep.findings.append(Finding(
                "many_fields", "note", slug,
                f"{len(fields)} fields — the practitioner will scroll past most of them"))
        if "date" in types and not any(t.get("type") == "overdue" for t in _triggers(s)) \
                and any("due" in str(f.get("name", "")).lower() or "deadline" in
                        str(f.get("name", "")).lower() for f in fields):
            rep.findings.append(Finding(
                "deadline_without_overdue", "note", slug,
                "there is a due date and no overdue trigger"))

    return rep
