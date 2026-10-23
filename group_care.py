"""
group_care.py — a note to each person who's been missing, drafted by Chief,
sent by the leader.

From the approved canvas "Church Groups, Together" (board Lead: "Haven't
been in 3 weeks · Brenda, Faith and Gloria · Send the 3 notes / Read them
first · Sent from you. Replies come to your messages.").

  * on My group (group_lead), a leader with people who've missed the last
    three gatherings presses "Draft a note to each": Chief writes one short,
    warm note per person (first names only go to the model); if Chief
    can't, a plain note to start from, said so
  * each note's "Send to <name>" opens the leader's private chat with that
    person with the note written in: the leader changes anything, then
    sends it themselves, through messaging's own rules and the check every
    message gets (a teen and an adult who isn't their parent can't chat
    privately, so a teen gets no Send, only "talk at the gathering")
  * only when the church has messaging on; a few drafts an hour per leader

POST /my/lead/groups/notes (member_portal_lead).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

MODEL = os.environ.get("GROUP_CARE_MODEL") or "claude-haiku-5-5"
NOTE_MAX = 400
PEOPLE_MAX = 8

PROMPT = """You help a church small-group leader reach out to people who have missed the group's last few gatherings.

You get the group's name, the leader's first name, when the group meets next (if known) and a list of people by id and first name. Write one short note from the leader to each person.

- Warm and personal: they're missed, and the leader hopes they're doing well. Ask how they're doing.
- No guilt, no pressure, no mention of attendance numbers or how many times they missed.
- Mention the next gathering only if it's given, as an easy invitation.
- One or two sentences, under 40 words. Start with "Hi" and their first name. Plain words. No emoji, no signature.

Return only a JSON object mapping each id to its note."""


def plain(first: str, group: str, next_text: str) -> str:
    """The note to start from when Chief can't draft."""
    come = f" We’d love to see you {next_text}." if next_text else " We’d love to see you next time."
    return f"Hi {first}, we’ve missed you at {group}. I hope you’re doing well. How are you?{come}"


def parse(raw: str, ids: List[str]) -> Optional[Dict[str, str]]:
    a, b = (raw or "").find("{"), (raw or "").rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        got = json.loads(raw[a:b + 1])
    except ValueError:
        return None
    if not isinstance(got, dict):
        return None
    out = {i: " ".join(str(got[i]).split())[:NOTE_MAX] for i in ids if isinstance(got.get(i), str) and got[i].strip()}
    return out if len(out) == len(ids) else None


def draft(business_id: str, group: str, leader_first: str, next_text: str,
          people: List[Dict[str, str]]) -> Tuple[Dict[str, str], bool]:
    """({id: note}, by_chief). Never fails: a plain note when Chief can't."""
    ids = [p["id"] for p in people]
    fallback = {p["id"]: plain(p["first"], group, next_text) for p in people}
    if not os.environ.get("ANTHROPIC_API_KEY") or not people:
        return fallback, False
    import httpx
    import llm_call
    import model_ladder
    facts = json.dumps({"group": group, "leader": leader_first, "next_gathering": next_text or None,
                        "people": [{"id": p["id"], "first_name": p["first"]} for p in people]}, ensure_ascii=False)
    payload = {"model": MODEL, "max_tokens": 900, **model_ladder.thinking_off_kwargs(MODEL),
               "system": [{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}],
               "messages": [{"role": "user", "content": facts}]}
    try:
        with httpx.Client() as client:
            resp = llm_call.post_with(client, payload, timeout=30, task="group_care", business_id=str(business_id), units=0)
        if resp.status_code != 200:
            return fallback, False
        body = resp.json()
        if body.get("stop_reason") == "refusal":
            return fallback, False
        got = parse(llm_call.text_of(body), ids)
        return (got, True) if got else (fallback, False)
    except Exception:
        logger.warning("group care notes: draft failed", exc_info=True)
        return fallback, False


def render(g: Dict[str, Any], rows: List[Dict[str, Any]], notes: Dict[str, str], by_chief: bool, *, ic, esc, face, name) -> str:
    """The drafts page body: one card per person."""
    cards = []
    for p in sorted(rows, key=lambda p: bool(p.get("teen"))):          # the notes to send first
        text = notes.get(p["id"], "")
        if p.get("teen"):
            act = (f'<p class="gm-fine">{esc(name(p))} is a teen, so private messages from an adult who isn’t their parent '
                   f'aren’t allowed. A word at the next gathering, or a note to the group, works well.</p>')
        else:
            act = (f'<p class="gc-note-text">{esc(text)}</p>'
                   f'<a class="gs-btn sm" href="/my/messages/to/{esc(p["id"])}?say={quote(text, safe="")}">'
                   f'{ic("send", 15)}Send to {esc(name(p).split(" ")[0])}</a>')
        cards.append(f'<section class="gs-card gc-note"><div class="gs-ph">{face(p)}<span class="gs-t"><b>{esc(name(p))}</b>'
                     f'<small>Missed the last three gatherings</small></span></div>{act}</section>')
    lead = ("Chief drafted these from you. " if by_chief else "Here’s a note to start from. ")
    return (f'<div class="gc-list"><p class="gm-fine" style="margin:0 0 12px">{lead}Send opens your private chat with them with the note written in. '
            f'Change anything you like, then send it. Replies come to your messages.</p>{"".join(cards)}'
            f'<p style="margin-top:14px"><a class="gs-mini" href="/my/lead/groups/{esc(g["id"])}">Back to {esc(g.get("name") or "your group")}</a></p></div>')


CARE_CSS = """
.gc-list{max-width:720px;}
.gc-note-text{margin:0;padding:12px 14px;border-radius:var(--r-md);background:var(--s2);font-size:15px;line-height:1.5;}
.gc-note .gs-btn{align-self:flex-start;}
"""
