"""
vertical_scope.py — what a vertical is deliberately NOT allowed to do.

WHY THIS EXISTS
  Every other vertical module in this codebase answers "what can this
  business do here". This one answers the opposite, and it exists because of
  one ruling: therapists launch with CLINICAL NOTES OUT OF SCOPE.

  That ruling is only real if the system enforces it. A comment in a profile
  and a line in a prompt are both advisory — the LLM can be talked past, and
  a practitioner can simply create a module called "Session Notes" by hand.
  So the boundary lives here, gets checked at the two seams where custom
  modules are actually created, and is asserted by tests.

THE HIPAA REASONING, STATED PLAINLY
  Storing session content or clinical detail makes the platform a business
  associate under HIPAA. That means a signed BAA with EVERY downstream
  processor that could touch the data — the model provider, Supabase,
  Twilio, Stripe — plus a hard gate on what Chief may read. None of that is
  in place, and none of it is a checklist row: it is a legal posture.

  So the vertical ships useful and narrow. Scheduling, billing, and admin
  are genuinely valuable to a private practice and carry no PHI beyond the
  contact record any business already keeps. Progress notes are the thing
  that would flip the platform's legal status, and they are refused.

  This is a NARROWED LAUNCH, not a permanent limitation. When a BAA posture
  exists, the entry here is deleted and the capability lands deliberately.

WHY KEYWORDS AND NOT AN LLM CLASSIFIER
  A blocked-substring list is crude and will produce the occasional false
  positive ("Note" on its own is allowed; "Clinical Note" is not). That is
  the correct direction to be wrong in. The alternative — asking a model
  whether a module is clinical — fails open under exactly the conditions
  that matter, and a false negative here is a HIPAA exposure rather than an
  inconvenience. The refusal message names the boundary so a practitioner is
  never left guessing.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


class ScopeRule:
    """One vertical's refusal.

    `reason` and `allowed_note` are the PRACTITIONER-facing explanation and
    can be as long as they need to be — they are shown once, on refusal.
    `prompt` is the CHIEF-facing version and is deliberately terse, because
    vertical_context ships on every Chief request under a ~1500 char budget.
    Reusing the long form there cost 400 characters of every prompt for a
    single vertical, which is how a budget quietly becomes a suggestion.

    `client_surface` is a SECOND KIND OF RULE, and it is asked at a
    different moment than `blocked`. check_module_scope() gates CREATION:
    it reads a module's name, slug, description and field labels, all of
    which a practitioner deliberately chose. The client layer introduces a
    risk that check never sees — CONTENT, typed by a client, into a box
    the practitioner legitimately created.

    A therapy client writing "the panic attacks started after the
    medication change" into a free-text field puts PHI in this database,
    and no keyword list applied at module-creation time was ever going to
    stop it. The HIPAA boundary moves from what a practitioner may BUILD
    to what a client may SAY, which is a much weaker place to hold it.

    So this is a CAPABILITY GATE, not a content scan, and the distinction
    is the whole point. Scanning client prose for clinical keywords would
    fail open constantly — client writing is unstructured, unprompted and
    nothing like a module name someone chose — and this module already
    argues why failing open here is the wrong direction to be wrong in:
    a false negative is a HIPAA exposure, not an inconvenience. Refusing
    the surface is answerable. Filtering its contents is theatre.

      'denied'       no client-facing surface for this vertical at all.
      'no_free_text' surface allowed, client-authored prose is not.
      'allowed'      the default for every vertical without a rule.
    """

    def __init__(self, blocked: List[str], reason: str, allowed_note: str,
                 prompt: str, client_surface: str = "allowed"):
        self.blocked = [b.lower() for b in blocked]
        self.reason = reason
        self.allowed_note = allowed_note
        self.prompt = prompt
        self.client_surface = client_surface


# Phrases that indicate a module would hold clinical content. Multi-word on
# purpose: "notes" alone is a legitimate module for any business, including a
# therapist keeping admin notes ("moved to Tuesdays", "invoice disputed").
# What is refused is the clinical record.
_CLINICAL = [
    "progress note", "progress notes",
    "clinical note", "clinical notes",
    "session note", "session notes",
    "therapy note", "therapy notes",
    "case note", "case notes",
    "chart note", "chart notes",
    "soap note", "soap notes",
    "psychotherapy", "treatment plan", "treatment plans",
    "diagnosis", "diagnoses", "diagnostic",
    "symptom", "symptoms",
    "mental status", "intake assessment", "clinical assessment",
    "medication", "medications", "prescription", "prescriptions",
    "phi", "protected health",
    "medical record", "medical records", "health record", "health records",
]

OUT_OF_SCOPE: Dict[str, ScopeRule] = {
    "therapist": ScopeRule(
        blocked=_CLINICAL,
        reason=(
            "Clinical records are out of scope on this platform. Storing "
            "session content or clinical detail would make the platform a "
            "HIPAA business associate, which requires signed agreements with "
            "every downstream service that could touch the data — and those "
            "are not in place."),
        allowed_note=(
            "Scheduling, billing, invoicing, client contact details and "
            "practice admin are all fully supported. Keep clinical records in "
            "your EHR."),
        prompt=(
            "OUT OF SCOPE: clinical records (notes, diagnoses, treatment, "
            "session content). HIPAA posture — the platform holds no PHI. "
            "Never offer or create one; say it is out of scope and offer the "
            "scheduling/billing/admin work instead."),
        # No client-facing surface for therapists in this arc. Until this
        # shipped, "therapists are out" was true only by accident: no
        # vertical had a client surface, so none was refused one. The
        # moment the first client surface exists, "out" has to be
        # something the code says rather than something a plan asserts.
        client_surface="denied",
    ),
}


def _norm(business_type: Optional[str]) -> str:
    try:
        import vertical_registry
        return vertical_registry.resolve(business_type)
    except Exception:
        return "custom"


def rule_for(business_type: Optional[str]) -> Optional[ScopeRule]:
    return OUT_OF_SCOPE.get(_norm(business_type))


def check_module_scope(business_type: Optional[str],
                       *parts: Optional[str]) -> Tuple[bool, Optional[str]]:
    """May this vertical have a module described by `parts`?

    Returns (allowed, refusal_message). Checks name, slug, description and
    any field labels the caller passes — a module called "Sessions" whose
    fields are "diagnosis" and "treatment plan" is exactly as out of scope as
    one called "Clinical Notes", and checking the name alone would miss it.
    """
    rule = rule_for(business_type)
    if not rule:
        return True, None

    haystack = " ".join(p for p in parts if p).lower()
    if not haystack.strip():
        return True, None
    # Collapse punctuation so "clinical-notes" and "clinical_notes" match the
    # same way "clinical notes" does.
    haystack = re.sub(r"[^a-z0-9]+", " ", haystack)

    for phrase in rule.blocked:
        if phrase in haystack:
            return False, (f"“{phrase}” is out of scope here. {rule.reason} "
                           f"{rule.allowed_note}")
    return True, None


def client_surface(business_type: Optional[str]) -> str:
    """'allowed' | 'no_free_text' | 'denied' for this vertical.

    Defaults to 'allowed' — a vertical with no rule has no restriction,
    the same way rule_for() returns None for one. The refusal is the
    exception and must be declared.
    """
    rule = rule_for(business_type)
    return rule.client_surface if rule else "allowed"


def client_surface_allowed(business_type: Optional[str]) -> bool:
    """May this vertical have a client-facing surface at all?

    Called at the seam where a client surface is ENABLED for a business,
    not on every request — this answers a question about the vertical,
    which does not change between requests.
    """
    return client_surface(business_type) != "denied"


def client_free_text_allowed(business_type: Optional[str]) -> bool:
    """May a client TYPE PROSE into this vertical's surface?

    Separate from client_surface_allowed because the two refusals differ:
    a vertical can be safe to show a client their next appointment and
    unsafe to hand them a notes box. 'denied' answers False here too — a
    vertical with no surface cannot have free text on it.
    """
    return client_surface(business_type) == "allowed"


def client_surface_refusal(business_type: Optional[str]) -> Optional[str]:
    """The practitioner-facing sentence for a refused client surface, or
    None when it is allowed. Reuses the rule's own reason rather than
    inventing a second explanation of the same boundary."""
    rule = rule_for(business_type)
    if not rule or rule.client_surface != "denied":
        return None
    return (f"A client-facing portal is not available for this practice. "
            f"{rule.reason} {rule.allowed_note}")


def prompt_block(business_type: Optional[str]) -> str:
    """Injected into Chief's system prompt so it never OFFERS what the guard
    would refuse. Belt and braces: the guard is the enforcement, this stops
    Chief proposing something it will then be blocked from building."""
    rule = rule_for(business_type)
    return rule.prompt if rule else ""
