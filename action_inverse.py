"""
action_inverse.py — what "undo" actually MEANS, per verb.

THE GAP THIS CLOSES
  action_registry classifies all 139 verbs by reversibility, and class A
  reads "cleanly undoable — a wrong one is an edit away from right". The
  readiness audit found that was a DESIGN JUDGMENT with nothing behind it:
  restore_previous_site was the only verb a practitioner could actually
  press to undo. Class A described a property nobody could use.

  This turns the judgment into an operation for the subset where an inverse
  is genuinely derivable, and — just as importantly — refuses to pretend for
  the subset where it is not.

THE THREE KINDS OF VERB
  1. PAIRED — the codebase already ships the opposite verb, and
     action_registry's own text says so ("add_block_range; remove_block_range
     is the exact undo"). These are the safest: the inverse is not invented
     here, it is an existing, tested handler.

  2. CREATE — the inverse is a delete or a soft-delete, and the id comes out
     of the ORIGINAL RESULT. This is why chief_undo_log stores the handler's
     return value and not just the payload: "create_module_entry" is not
     reversible from the request alone, only from what it produced.

  3. UPDATE — NOT SUPPORTED, deliberately. Reversing update_contact_status
     needs the status the row held BEFORE, and nothing captures before-images.
     Half-reversing an update (setting it to a guessed default) is worse than
     refusing, because it looks like it worked. undo_last says plainly that
     the action cannot be undone and why.

WHY THIS IS NOT DERIVED FROM THE REGISTRY
  Same reason action_registry is not derived from the code. "Class A" says a
  verb is conceptually reversible; it does not say by what. Every entry below
  is a human judgment naming a specific opposing operation, and a wrong entry
  destroys data rather than failing a lint.

SAFETY
  An inverse is only ever built for a verb listed here. Everything else —
  including every class C verb, every bulk verb, and anything unclassified —
  returns None and is reported as not undoable. There is no fallback that
  guesses, for the same reason action_registry has none.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# How long an action stays undoable. Undo is a short-window affordance, not
# an audit trail — chief_activity is the audit trail. A day is long enough to
# catch "that wasn't what I meant" and short enough that reversing something
# from last week never surprises anybody.
UNDO_WINDOW_HOURS = 24


class Inverse:
    """How to reverse one verb.

    `build(action, result)` returns the ACTION PAYLOAD that undoes it, or
    None when this particular instance cannot be reversed (typically because
    the id it needs is absent from the result).
    """

    def __init__(self, verb: str, describe: str,
                 build: Callable[[Dict[str, Any], Dict[str, Any]],
                                 Optional[Dict[str, Any]]]):
        self.verb = verb
        self.describe = describe
        self.build = build


def _first_id(result: Dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        v = result.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# ── 1. PAIRED verbs — the opposite handler already exists ────────────
# The inverse is an existing tested handler, not something invented here.

def _swap(verb: str, keys: tuple) -> Callable:
    """Reverse by calling `verb` with the same identifying arguments."""
    def build(action, result):
        out: Dict[str, Any] = {"type": verb}
        for k in keys:
            if action.get(k) is not None:
                out[k] = action[k]
        # If none of the identifying args came through, we cannot target the
        # inverse safely — better to refuse than to act on a partial payload.
        return out if len(out) > 1 else None
    return build


INVERSES: Dict[str, Inverse] = {

    "add_block_range": Inverse(
        "remove_block_range",
        "un-block those dates",
        _swap("remove_block_range", ("start_date", "end_date", "start", "end", "reason"))),

    "remove_block_range": Inverse(
        "add_block_range",
        "re-block those dates",
        _swap("add_block_range", ("start_date", "end_date", "start", "end", "reason"))),

    "add_voice_rule": Inverse(
        "remove_voice_rule",
        "remove that voice rule again",
        _swap("remove_voice_rule", ("rule", "rule_id", "text"))),

    "remove_voice_rule": Inverse(
        "add_voice_rule",
        "put that voice rule back",
        _swap("add_voice_rule", ("rule", "rule_id", "text"))),

    # remember → forget. The registry is explicit that forget is a
    # deactivation (is_active flip), not a delete, so this is genuinely
    # reversible in both directions.
    "remember": Inverse(
        "forget",
        "un-remember that",
        lambda a, r: ({"type": "forget",
                       "memory_id": _first_id(r, "memory_id", "id")}
                      if _first_id(r, "memory_id", "id")
                      else ({"type": "forget", "content": a["content"]}
                            if a.get("content") else None))),

    # ── 2. CREATE verbs — the id comes from the RESULT ───────────────

    "create_module_entry": Inverse(
        "delete_module_entry",
        "remove that entry",
        lambda a, r: ({"type": "delete_module_entry",
                       "module_id": a.get("module_id") or r.get("module_id"),
                       "entry_id": _first_id(r, "entry_id", "id")}
                      if _first_id(r, "entry_id", "id") else None)),

    # archive_offering is itself a soft delete; the undo is un-archiving.
    "archive_offering": Inverse(
        "update_offering",
        "restore that offering",
        lambda a, r: ({"type": "update_offering",
                       "offering_id": a.get("offering_id") or _first_id(r, "offering_id", "id"),
                       "is_active": True}
                      if (a.get("offering_id") or _first_id(r, "offering_id", "id"))
                      else None)),

    # complete_task flips a done flag the registry calls "re-openable".
    "complete_task": Inverse(
        "update_module_entry",
        "re-open that task",
        lambda a, r: ({"type": "update_module_entry",
                       "module_id": a.get("module_id") or r.get("module_id"),
                       "entry_id": _first_id(a, "task_id", "entry_id")
                                   or _first_id(r, "task_id", "entry_id", "id"),
                       "data": {"status": "open", "done": False}}
                      if (_first_id(a, "task_id", "entry_id")
                          or _first_id(r, "task_id", "entry_id", "id")) else None)),

    # The drawdown ledger is append-only, so its undo is a compensating row
    # rather than a deletion — which is exactly how a ledger should reverse.
    "grant_balance": Inverse(
        "consume_balance",
        "take that balance back off",
        lambda a, r: ({"type": "consume_balance",
                       "contact_id": a.get("contact_id"),
                       "amount": a.get("amount"),
                       "kind": a.get("kind"), "unit": a.get("unit"),
                       "reason": "Undo: " + str(a.get("reason") or "grant"),
                       "allow_overdraw": True}
                      if a.get("contact_id") and a.get("amount") else None)),

    "consume_balance": Inverse(
        "grant_balance",
        "put that balance back",
        lambda a, r: ({"type": "grant_balance",
                       "contact_id": a.get("contact_id"),
                       "amount": a.get("amount"),
                       "kind": a.get("kind"), "unit": a.get("unit"),
                       "reason": "Undo: " + str(a.get("reason") or "draw")}
                      if a.get("contact_id") and a.get("amount") else None)),

    # add_testimonial's result carries the generated id, and
    # remove_testimonial by id is an exact-match delete of one array
    # entry — the registry's own text says "re-addable".
    "add_testimonial": Inverse(
        "remove_testimonial",
        "take that testimonial back off",
        lambda a, r: ({"type": "remove_testimonial",
                       "testimonial_id": _first_id(r, "testimonial_id", "id")}
                      if _first_id(r, "testimonial_id", "id") else None)),

    # create_offering → archive_offering: the codebase's own delete for
    # offerings is the archive (is_active=false, history preserved), and
    # archive_offering is itself undoable (see its entry above) — so
    # this undo can be undone, which is the safest kind.
    "create_offering": Inverse(
        "archive_offering",
        "archive that offering again",
        lambda a, r: ({"type": "archive_offering",
                       "offering_id": _first_id(r, "offering_id", "id")}
                      if _first_id(r, "offering_id", "id") else None)),
    # ── site copy — an edit is an override row; reverting deletes it, and
    # re-applying the revert writes the same words back. The target path
    # comes from the RESULT (edit resolves `find` to it), so an undo never
    # re-runs a fuzzy match.
    "edit_site_text": Inverse(
        "revert_site_text",
        "put that site text back",
        lambda a, r: ({"type": "revert_site_text",
                       "target": _first_id(r, "target_path")}
                      if _first_id(r, "target_path") else None)),
    "revert_site_text": Inverse(
        "edit_site_text",
        "re-apply that site edit",
        lambda a, r: ({"type": "edit_site_text",
                       "target": _first_id(r, "target_path"),
                       "text": _first_id(r, "previous_text")}
                      if _first_id(r, "target_path") and _first_id(r, "previous_text")
                      else None)),
}

# S11 resolution (2026-07-31): write_off_time is GONE from INVERSES. It
# sat in both maps — a dead placeholder whose build always returned None,
# while NOT_UNDOABLE_REASON simultaneously refused it. The data model IS
# deterministic (write_off flips status 'unbilled'→'written_off' and
# nothing else), but no registered verb performs the reverse flip:
# log_time INSERTS a new row, it does not restore the old one. Until a
# restore verb exists in chief_of_staff (follow-up — that file is owned
# elsewhere this wave), the honest answer is the reason map's.

# Verbs whose class A status is real but whose inverse needs data nobody
# captures. Listed EXPLICITLY so undo_last can say WHY rather than giving the
# generic "can't undo that" — a practitioner told "I can't reverse a status
# change because I didn't keep the old value" learns something; one told
# "no" twice just stops trying.
NOT_UNDOABLE_REASON: Dict[str, str] = {
    "update_contact": "I'd need the values it held before, and I don't keep those yet.",
    "update_contact_status": "I'd need the previous status, and I don't keep those yet.",
    "update_contact_health": "I'd need the previous score, and I don't keep those yet.",
    "update_offering": "I'd need the previous values, and I don't keep those yet.",
    "update_session": "I'd need the previous values, and I don't keep those yet.",
    "update_project": "I'd need the previous values, and I don't keep those yet.",
    "update_module_entry": "I'd need the row as it was before, and I don't keep that yet.",
    "update_voice_style": "I'd need the previous style, and I don't keep those yet.",
    "update_business_profile_field": "I'd need the previous value, and I don't keep those yet.",
    "update_practitioner_profile_field": "I'd need the previous value, and I don't keep those yet.",
    "write_off_time": "Re-opening written-off time isn't wired yet — edit the entry directly.",
    "set_business_policy": "I'd need the previous policy text, and I don't keep those yet.",
    # ── S11 audit (2026-07-31): class-A creates REVIEWED and refused. ──
    # Each of these was studied for an inverse; the refusal is a
    # documented judgment, not an oversight.
    #
    # create_contact: the only deleting verb (delete_contact) is class C
    # in action_registry — a HARD delete — and the undo containment law
    # (test_no_inverse_is_a_class_c_verb) forbids reaching class C from
    # undo. Reclassifying or adding a guarded-delete lane is an
    # action_registry ruling, owned elsewhere this wave.
    "create_contact": ("Removing a contact is a hard delete, and undo never "
                       "reaches those — open the contact and use Delete there."),
    # No delete verb exists for these creates; inventing one belongs to
    # chief_of_staff (owned elsewhere this wave), not to undo.
    "create_task": "There's no verb that deletes a task yet — mark it done or edit it directly.",
    "create_goal": "There's no verb that removes a goal yet — edit it in Goals directly.",
    "create_note": "Contact notes have no delete verb yet — the note stays on the record.",
    # save_note rows carry no id back, and 'forget' matches by content
    # similarity — close enough to deactivate the WRONG memory. Refused.
    "save_note": "Notes don't come back with an id I can target safely — remove it in Notes directly.",
    # log_time's result carries no entry id, and writing it off is not
    # the same as it never happening.
    "log_time": "The entry's id isn't captured, and writing it off isn't an undo — edit the entry directly.",
    # save_email_template UPSERTS by name: undoing an update needs the
    # previous subject/body, which nothing captures.
    "save_email_template": "Saving over a template loses the old version, and I don't keep those yet.",
}


def can_undo(verb: str) -> bool:
    """Only verbs with a named, human-judged inverse. No fallback guess."""
    return verb in INVERSES and verb not in NOT_UNDOABLE_REASON


def why_not(verb: str) -> str:
    """The most useful sentence we can offer when undo is refused."""
    if verb in NOT_UNDOABLE_REASON:
        return NOT_UNDOABLE_REASON[verb]
    try:
        import action_registry
        rev = action_registry.reversibility(verb)
        if action_registry.is_bulk(verb):
            return ("That one acted on a whole set at once — undoing forty "
                    "rows isn't one operation, so I won't try.")
        if rev == "C":
            return ("That one left the system or touched money, so there's "
                    "nothing for me to take back.")
        if action_registry.effect(verb) == action_registry.READ:
            return "That didn't change anything, so there's nothing to undo."
    except Exception:
        pass
    return "I don't have a way to reverse that one."


def build_inverse(verb: str, action: Dict[str, Any],
                  result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The action payload that reverses this one, or None."""
    if not can_undo(verb):
        return None
    inv = INVERSES[verb]
    try:
        return inv.build(action or {}, result or {})
    except Exception:
        # A build that raises is a build that cannot be trusted to target the
        # right row. Refusing is the only safe answer.
        return None


def describe(verb: str) -> str:
    inv = INVERSES.get(verb)
    return inv.describe if inv else "reverse that"


def undoable_verbs() -> set:
    return {v for v in INVERSES if can_undo(v)}
