"""chief_memory_review.py — Chief's notes for a business, checked for tidying.

Kevin, 2026-11-24, on Chief's memory: "ok great. lets build this." The second
of three: the notes Chief keeps (public.chief_memories) only ever grow. Chief
carries the top 50 on every reply (chief_of_staff._blend_memories); past that,
the rest drop out of view without a word, and nothing ever looks for two notes
that say the same thing, or that disagree.

This is a READ, `review_memories`. It changes nothing. It tells Chief, and
through Chief the owner:

    kept / carried     how many notes there are, and how many ride each reply
    not_carried        the ones that don't (past the top 50)
    look_alike         notes that share most of their words: the same thing
                       said twice, or two that DISAGREE
    unused             notes nothing has touched in UNUSED_DAYS, least important first

WHY IT ONLY READS. Tidying a note is the owner's call, one note at a time:

  * Two notes that share their words are not the same note. The dedup at the
    write path matched on shared words until it erased a correction ("do not
    take Friday calls" read as "take Friday calls"; chief_of_staff
    ._find_duplicate_memory). So a look-alike pair that differs by a "not", a
    number, a day or an amount is marked may_disagree, and Chief is told to
    show both and ask which is true, never to merge them.
  * A note nobody has used in a year may be the one that matters next week
    (a birthday, a boundary). Nothing is retired for being old.

The change itself is the verbs that already exist, with the owner's word:
`forget` (now by the note's own id, so the right one of two look-alikes goes)
and `remember` for the wording to keep. Both are in the undo log.

Insights (the weekly engine caps its own), the Notes pad and Chief's own
bookkeeping rows are left out: they aren't notes the owner tidies here.
"""
from __future__ import annotations

import re
import json
from typing import Any, Dict, List, Optional, Set

ATYPE = "review_memories"
CARRIED = 50            # chief_of_staff._blend_memories keep
POOL = 100              # what the turn's context reads before it ranks (chief_of_staff._gather_context)
READ_MAX = 400
ALIKE = 0.6             # shared words over all words, for two notes to look alike
UNUSED_DAYS = 180
LIST_MAX = 10
GROUPS_MAX = 6
GROUP_NOTES = 4
TEXT_CHARS = 200
FIT_CHARS = 9000        # the answer stops here so it reaches Chief whole (the loop's cap for this read is 12000)
SKIP_CATEGORIES = {"insight", "jit_asked", "note"}
_NOT = {"not", "no", "never", "dont", "don't", "doesnt", "doesn't", "stop", "without", "except", "only", "cant",
        "can't", "wont", "won't", "avoid"}
_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon", "tue", "tues", "wed",
         "thu", "thur", "thurs", "fri", "sat", "sun", "am", "pm", "morning", "afternoon", "evening", "weekly",
         "monthly", "daily"}

TOOL = {
    "name": ATYPE,
    "description": (
        "The notes you keep for this business, checked for tidying. It says how many notes there are and how many "
        "you carry on every reply (the top 50); lists the ones you are NOT carrying; notes that look alike (the "
        "same thing said twice, or two that disagree); and notes nothing has used in six months. Use it when the "
        "owner asks 'what do you remember about us', 'tidy up what you remember', 'why didn't you remember that', "
        "or when your notes block says some aren't carried. It changes nothing. To change a note, the owner says "
        "which to keep; then use forget with that note's memory_id, and remember for new wording. A pair marked "
        "may_disagree is NOT a duplicate: show both and ask which is true. Never drop a note just because it is old."),
    "input_schema": {"type": "object", "properties": {}},
}


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _cut(text: str, n: int = TEXT_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _tokens(content: Any) -> List[str]:
    return re.findall(r"[a-z0-9$%']+", _plain(content).lower())


def _words(content: Any) -> Set[str]:
    """What a note is about: the door's own signature (stop words out)."""
    from chief_of_staff import _memory_signature
    return _memory_signature(_plain(content))


def _sharp(content: Any) -> Set[str]:
    """The words that turn a note into a different note: a not, a number, a day, an amount."""
    return {t for t in _tokens(content) if t in _NOT or t in _DAYS or any(c.isdigit() for c in t)}


def is_ordinary(m: Dict[str, Any]) -> bool:
    return ((m.get("category") or "").lower() not in SKIP_CATEGORIES
            and not _plain(m.get("content")).startswith("[note:"))


def _age(m: Dict[str, Any]) -> Optional[int]:
    from chief_of_staff import _days_since
    return _days_since(m.get("last_referenced_at") or m.get("created_at"))


def _show(m: Dict[str, Any]) -> Dict[str, Any]:
    age = _age(m)
    return {"memory_id": str(m.get("id") or ""), "note": _cut(_plain(m.get("content"))),
            "importance": m.get("importance") or 5, "kind": (m.get("category") or "other"),
            "last_used_days_ago": age if age is not None else "unknown"}


def carried_ids(rows: List[Dict[str, Any]]) -> Set[str]:
    """The notes a reply carries, picked the way the turn's context picks them."""
    from chief_of_staff import _blend_memories
    # Importance first, newest first within it (the context's own order), the top POOL, then the blend.
    pool = sorted(rows, key=lambda m: str(m.get("created_at") or ""), reverse=True)
    pool = sorted(pool, key=lambda m: float(m.get("importance") or 5), reverse=True)[:POOL]
    return {str(m.get("id")) for m in _blend_memories(pool, keep=CARRIED)}


def look_alike(notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups of notes that share most of their words, each marked for whether they may disagree."""
    sig = [(m, _words(m.get("content"))) for m in notes]
    sig = [(m, w) for m, w in sig if len(w) >= 2]
    parent = list(range(len(sig)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(sig)):
        for j in range(i + 1, len(sig)):
            a, b = sig[i][1], sig[j][1]
            if len(a & b) / max(len(a | b), 1) >= ALIKE:
                parent[find(i)] = find(j)
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for i, (m, _) in enumerate(sig):
        groups.setdefault(find(i), []).append(m)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        sharp = [_sharp(m.get("content")) for m in members]
        same_words = len({" ".join(_tokens(m.get("content"))) for m in members}) == 1
        disagree = any(s != sharp[0] for s in sharp[1:])
        out.append({"may_disagree": disagree,
                    "why": ("They differ by a not, a number, a day or an amount: they may say opposite things. "
                            "Show both and ask which is true." if disagree else
                            "The same words twice." if same_words else
                            "They share most of their words. Ask which wording to keep."),
                    "notes": [_show(m) for m in members[:GROUP_NOTES]]})
    out.sort(key=lambda g: (not g["may_disagree"], -len(g["notes"])))
    return out[:GROUPS_MAX]


def review(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The whole review off the business's active notes. Pure."""
    notes = [m for m in rows if isinstance(m, dict) and is_ordinary(m)]
    carried = carried_ids([m for m in rows if isinstance(m, dict)])
    out_of_view = [m for m in notes if str(m.get("id")) not in carried]
    out_of_view.sort(key=lambda m: (float(m.get("importance") or 5), -(_age(m) or 0)))
    alike = look_alike(notes)
    unused = [m for m in notes if (_age(m) or 0) >= UNUSED_DAYS]
    unused.sort(key=lambda m: (float(m.get("importance") or 5), -(_age(m) or 0)))
    n, c = len(notes), len(notes) - len(out_of_view)
    parts = [f"{n} note{'s' if n != 1 else ''} kept"]
    if out_of_view:
        parts.append(f"{c} carried on every reply and {len(out_of_view)} not carried (only the top {CARRIED} are)")
    else:
        parts.append("all of them carried on every reply")
    if alike:
        d = sum(1 for g in alike if g["may_disagree"])
        parts.append(f"{len(alike)} group{'s' if len(alike) != 1 else ''} that look alike"
                     + (f", {d} of which may disagree" if d else ""))
    if unused:
        parts.append(f"{len(unused)} not used in {UNUSED_DAYS} days")
    clean = not (out_of_view or alike or unused)
    return _fit({
        "type": ATYPE,
        "label": "Nothing to tidy" if clean else _cut(f"{n} notes: {len(out_of_view)} not carried, {len(alike)} alike", 80),
        "result": "; ".join(parts) + "." + (" Nothing needs tidying." if clean else ""),
        "kept": n, "carried": c,
        "not_carried": [_show(m) for m in out_of_view[:LIST_MAX]], "not_carried_count": len(out_of_view),
        "look_alike": alike,
        "unused": [_show(m) for m in unused[:LIST_MAX]], "unused_count": len(unused),
        "how_to_change": ("Nothing here changes a note. The owner says which to keep; then forget with that note's "
                          "memory_id, and remember for new wording. A may_disagree pair is not a duplicate. "
                          "Never drop a note only because it is old."),
    })


def _fit(out: Dict[str, Any]) -> Dict[str, Any]:
    """Shorten the lists, longest first, until the answer fits. The counts
    stay whole, and a list that was cut says so by its count."""
    def size() -> int:
        return len(json.dumps(out, default=str))
    while size() > FIT_CHARS:
        longest = max(("unused", "not_carried", "look_alike"), key=lambda k: len(out[k]))
        if len(out[longest]) <= 1:
            break
        out[longest] = out[longest][:-1]
    if (len(out["not_carried"]) < out["not_carried_count"] or len(out["unused"]) < out["unused_count"]):
        out["shown"] = ("Not every note is listed here: the counts are whole, the lists are the first of each. "
                        "Tidy these, then look again.")
    return out


def _fail(msg: str) -> Dict[str, Any]:
    return {"type": ATYPE, "result": f"Failed: {msg}", "label": msg[:80], "failed": True}


async def handle_review_memories(client, biz, action) -> Dict[str, Any]:
    from chief_of_staff import _sb
    bid = (biz or {}).get("id")
    if not bid:
        return _fail("I couldn't tell whose notes to read.")
    # Read the way the turn's own context reads them (the caller's sign-in; the table's rule decides).
    rows = await _sb(client, "GET",
                     f"/chief_memories?business_id=eq.{bid}&is_active=eq.true"
                     f"&order=importance.desc,created_at.desc&limit={READ_MAX}"
                     f"&select=id,category,content,importance,source,created_at,last_referenced_at")
    if not isinstance(rows, list):
        return _fail("I couldn't read the notes just now. Nothing is known either way.")
    out = review(rows)
    if len(rows) >= READ_MAX:
        out["result"] += f" Only the first {READ_MAX} notes were read."
    return out
