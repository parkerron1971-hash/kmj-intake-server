"""
strategy_router.py — THE OBSERVATORY's server side (docs/STRATEGY_ROOM.md).

Phase 3c: RESEARCH A CARD. The practitioner pins an idea to the board and
asks what is actually out there. Chief already carries Anthropic's
web_search server tool (chief_of_staff.WEB_SEARCH_TOOL, enabled by
default, capped at 3 uses per request) — so this is not a new agent, it
is a narrow, owner-gated endpoint that points an existing capability at
one card and hands back something the board can pin underneath it.

Why an endpoint rather than the chat: research that lands in a
conversation is research the card never keeps. The board is the record.

All endpoints live under /strategy. Registered before public_site_router
in kmj_intake_automation.py (which still owns /{path:path}).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sb_clients
from auth_supabase import require_user, AuthedUser

router = APIRouter(prefix="/strategy", tags=["strategy"])
logger = logging.getLogger("strategy_router")

# Enough to research one idea properly; short enough that a runaway
# prompt can't turn a card into an essay.
_MAX_TOKENS = 1400
_TITLE_CAP = 300
_NOTE_CAP = 1200
_SHAPE_CAP = 400


def _require_owner(business_id: str, user_id: str) -> None:
    """Same gate the composer endpoints use: unknown business → 404; the
    owner passes, and so does an active seat at MEMBER or above."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,name&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) == str(user_id):
        return
    from business_users_router import require_role
    require_role(business_id, str(user_id), "member")


def _business_name(business_id: str) -> str:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=name&limit=1") or []
    return (rows[0].get("name") if rows else "") or "this business"


_SYSTEM = (
    "You are Chief, researching ONE idea a small-business owner is "
    "considering. You have web search. Use it.\n\n"
    "What you are for here: telling them what is ACTUALLY out there — who "
    "is already doing this, what it costs, what tends to go wrong, and "
    "whether the assumption underneath the idea holds up. You are not a "
    "cheerleader and you are not a brainstorm partner; they already had "
    "the idea. Bring back facts they did not have.\n\n"
    "Rules:\n"
    "- Search before you answer. Never present recalled knowledge as a "
    "finding.\n"
    "- If the evidence is thin or contradicts the idea, SAY SO. A finding "
    "that the idea looks crowded is worth more than encouragement.\n"
    "- Be specific: numbers, names, prices, dates. 'Some businesses do "
    "well with this' is worthless.\n"
    "- Stay in the owner's context — their size and their trade, not "
    "enterprise advice.\n\n"
    "Return ONLY a JSON object, no prose around it:\n"
    '{\n'
    '  "summary": "2-3 sentences: what you found and what it means for '
    'this idea specifically",\n'
    '  "findings": ["a specific fact, with the number or name in it", '
    '"another", "3-5 total"],\n'
    '  "watch_outs": ["what tends to go wrong with this", "0-3 items"],\n'
    '  "verdict": "one of: worth trying | worth testing small | crowded | '
    'thin evidence",\n'
    '  "sources": [{"title": "page title", "url": "https://..."}]\n'
    "}\n\n"
    "Every source you list must be one you actually opened in a search "
    "result. Do not pad the list from memory."
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """The model was asked for bare JSON; accept a fenced block too."""
    if not text:
        return None
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start = body.find("{")
    end = body.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        out = json.loads(body[start:end + 1])
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _clean_list(raw: Any, cap: int, limit: int) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        if isinstance(item, (str, int, float)):
            s = str(item).strip()[:cap]
            if s:
                out.append(s)
        if len(out) >= limit:
            break
    return out


_LINK_SYSTEM = (
    "You are Chief, looking at a practitioner's idea board. Every card is "
    "something they are considering; the strings between cards are "
    "relationships they have already drawn.\n\n"
    "Your job: find relationships they have NOT drawn yet and should. You "
    "are looking for the connection that changes what they would do — not "
    "for surface similarity. Two cards both mentioning clients is not a "
    "relationship; one card being the thing that makes another possible "
    "is.\n\n"
    "The three relations, and what each means:\n"
    "- feeds: doing the first makes the second easier, cheaper or possible "
    "at all.\n"
    "- contradicts: they compete for the same time, money or positioning; "
    "doing both properly is not realistic.\n"
    "- same: they are one move wearing two names, and keeping them apart is "
    "costing clarity.\n\n"
    "Rules:\n"
    "- NEVER suggest a pair that is already tied. They are listed.\n"
    "- Suggest at most 4. Two good ones beat six plausible ones, and an "
    "empty list is a correct answer for a board of unrelated cards.\n"
    "- 'because' must say something they could disagree with. 'They are "
    "related' is not a reason.\n\n"
    "Return ONLY a JSON object:\n"
    '{"suggestions": [{"from": "<card id>", "to": "<card id>", '
    '"kind": "feeds|contradicts|same", "because": "one sentence"}]}'
)


_SHAPE_QUESTIONS = {
    "who": "Who is this for?",
    "true": "What would have to be true for this to work?",
    "test": "What is the smallest way to test it?",
    "cost": "What does it cost — time and money, honestly?",
    "instead": "What would you stop doing to make room?",
}
_SHAPE_ORDER = ["who", "true", "test", "cost", "instead"]

_SHAPE_SYSTEM = (
    "You are Chief, sitting with a small-business owner while they think "
    "an idea through out loud. This is a CONVERSATION, and much of it is "
    "spoken aloud — so you are brief, you sound like a person, and you "
    "never read a list back at them.\n\n"
    "They have just answered one question about their idea. Do three "
    "things, in this order:\n"
    "1. React to what they ACTUALLY said. Name the specific thing. Never "
    "open with 'Great!' or 'That's a good point.'\n"
    "2. Decide whether the answer is USABLE — concrete enough that "
    "someone else could act on it. 'Everyone', 'more clients', 'not "
    "much' and 'we'll see' are not usable.\n"
    "3. If it is not usable, ask ONE sharper follow-up on the SAME "
    "question — a narrower question, not the same one repeated. If it is "
    "usable, say what it tells you and stop.\n\n"
    "Rules:\n"
    "- Two or three sentences. This is speech, not a document.\n"
    "- Push back when something does not add up. An owner who says a "
    "thing costs nothing and displaces nothing is describing a wish.\n"
    "- Never invent facts about their business.\n"
    "- Only ever push back ONCE per question. If they have already had a "
    "follow-up, accept what they gave you and move on — a coach who will "
    "not let go is a coach they stop talking to.\n\n"
    "Return ONLY a JSON object:\n"
    '{"reply": "what you say to them",\n'
    ' "answer": "their answer, tidied into one clear line — keep THEIR '
    'words and meaning, never upgrade the substance",\n'
    ' "usable": true|false}'
)


class ShapeTurnBody(BaseModel):
    business_id: str
    title: str
    note: Optional[str] = ""
    key: str
    answer: str
    shape: Optional[Dict[str, Any]] = None
    """True when this question has already had one follow-up."""
    second_pass: Optional[bool] = False


@router.post("/shape-turn")
async def shape_turn(
    body: ShapeTurnBody,
    user: AuthedUser = Depends(require_user),
) -> JSONResponse:
    """One turn of shaping an idea with Chief.

    The board's five questions already exist as a form. This is the same
    rubric held as a CONVERSATION: the practitioner answers (typing or out
    loud), Chief reacts to what they actually said, and pushes back once
    when the answer would not survive contact with a calendar.

    Fail-soft: on any failure the caller keeps the raw answer and moves
    on, so a dead endpoint costs the coaching, never the idea."""
    _require_owner(body.business_id, user.id)

    key = (body.key or "").strip()
    if key not in _SHAPE_QUESTIONS:
        raise HTTPException(status_code=400, detail="unknown question")
    answer = (body.answer or "").strip()[:_NOTE_CAP]
    if not answer:
        raise HTTPException(status_code=400, detail="nothing to react to")

    shape = body.shape if isinstance(body.shape, dict) else {}
    prior = []
    for k in _SHAPE_ORDER:
        if k == key:
            continue
        v = str(shape.get(k) or "").strip()
        if v:
            prior.append("- {} {}".format(_SHAPE_QUESTIONS[k], v[:_SHAPE_CAP]))

    lines = [
        "Business: {}.".format(_business_name(body.business_id)),
        'Their idea: "{}"'.format(str(body.title or "")[:_TITLE_CAP]),
    ]
    note = (body.note or "").strip()[:_NOTE_CAP]
    if note:
        lines.append("Their own notes on it: {}".format(note))
    if prior:
        lines.append("What they have already told me about it:\n" + "\n".join(prior))
    lines.append('The question on the table: "{}"'.format(_SHAPE_QUESTIONS[key]))
    lines.append('They answered: "{}"'.format(answer))
    if body.second_pass:
        lines.append(
            "This is their SECOND answer to this question — you have already "
            "pushed back once. Accept what they have given you and move on."
        )
    lines.append("Respond with the JSON object.")

    try:
        import chief_of_staff as cos
        async with httpx.AsyncClient(timeout=45.0) as client:
            text = await cos._call_claude(
                client,
                system=_SHAPE_SYSTEM,
                messages=[{"role": "user", "content": "\n\n".join(lines)}],
                max_tokens=500,
                enable_web_search=False,
                business_id=body.business_id,
            )
    except Exception as e:
        logger.warning(f"[strategy.shape] call failed: {type(e).__name__}: {e}")
        return JSONResponse({"ok": False, "error": "coach_unavailable"})

    data = _extract_json(text or "")
    if not data:
        return JSONResponse({"ok": False, "error": "unreadable_result"})

    # A second pass is always accepted, whatever the model thinks — the
    # prompt says so, and the server enforces it so one stubborn model
    # cannot trap someone on a question.
    usable = bool(data.get("usable")) or bool(body.second_pass)
    tidied = str(data.get("answer") or "").strip()[:_SHAPE_CAP]

    return JSONResponse({
        "ok": True,
        "reply": str(data.get("reply") or "").strip()[:900],
        # Never lose what they said if the model returns nothing usable.
        "answer": tidied or answer[:_SHAPE_CAP],
        "usable": usable,
    })


class SuggestBody(BaseModel):
    business_id: str
    cards: List[Dict[str, Any]]
    existing: Optional[List[Dict[str, str]]] = None


@router.post("/suggest-links")
async def suggest_links(
    body: SuggestBody,
    user: AuthedUser = Depends(require_user),
) -> JSONResponse:
    """Chief reads the board and proposes strings the practitioner has not
    drawn. Reasoning over their OWN cards, so web search stays OFF — it is
    cheaper, faster, and there is nothing out there to look up.

    Fail-soft: ok=False rather than a 500."""
    _require_owner(body.business_id, user.id)

    cards = [c for c in (body.cards or []) if isinstance(c, dict) and c.get("id")][:40]
    if len(cards) < 2:
        return JSONResponse({"ok": True, "suggestions": []})

    valid_ids = {str(c["id"]) for c in cards}
    lines: List[str] = [f"Business: {_business_name(body.business_id)}.", "", "The cards:"]
    for c in cards:
        bits = ['- id {}: "{}"'.format(c["id"], str(c.get("title") or "")[:_TITLE_CAP])]
        if c.get("note"):
            bits.append("    note: {}".format(str(c["note"])[:300]))
        shape = c.get("shape") if isinstance(c.get("shape"), dict) else {}
        for k, v in list(shape.items())[:5]:
            if str(v or "").strip():
                bits.append("    {}: {}".format(k, str(v).strip()[:200]))
        lines.append("\n".join(bits))

    existing = [e for e in (body.existing or []) if isinstance(e, dict)]
    lines.append("")
    if existing:
        lines.append("Already tied (do not repeat these):")
        for e in existing[:80]:
            lines.append("- {} {} {}".format(e.get("from"), e.get("kind"), e.get("to")))
    else:
        lines.append("Nothing is tied yet.")
    lines.append("")
    lines.append("Return the JSON object.")

    try:
        import chief_of_staff as cos
        async with httpx.AsyncClient(timeout=60.0) as client:
            text = await cos._call_claude(
                client,
                system=_LINK_SYSTEM,
                messages=[{"role": "user", "content": "\n".join(lines)}],
                max_tokens=900,
                enable_web_search=False,
                business_id=body.business_id,
            )
    except Exception as e:
        logger.warning(f"[strategy.suggest] call failed: {type(e).__name__}: {e}")
        return JSONResponse({"ok": False, "error": "suggest_unavailable"})

    data = _extract_json(text or "")
    if not data:
        return JSONResponse({"ok": False, "error": "unreadable_result"})

    # Validate hard: a suggestion pointing at a card that is not on the
    # board, or repeating a tie that already exists, is worse than none.
    tied = {(str(e.get("from")), str(e.get("to"))) for e in existing}
    tied |= {(b, a) for (a, b) in tied}
    kinds = {"feeds", "contradicts", "same"}
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in (data.get("suggestions") or []):
        if not isinstance(raw, dict) or len(out) >= 4:
            continue
        a, b = str(raw.get("from") or ""), str(raw.get("to") or "")
        kind = str(raw.get("kind") or "").strip().lower()
        if a not in valid_ids or b not in valid_ids or a == b:
            continue
        if kind not in kinds or (a, b) in tied or (a, b) in seen:
            continue
        seen.add((a, b))
        seen.add((b, a))
        out.append({
            "from": a, "to": b, "kind": kind,
            "because": str(raw.get("because") or "").strip()[:300],
        })

    return JSONResponse({"ok": True, "suggestions": out})


class ResearchBody(BaseModel):
    business_id: str
    title: str
    note: Optional[str] = ""
    shape: Optional[Dict[str, Any]] = None


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "strategy"})


@router.post("/research")
async def research_idea(
    body: ResearchBody,
    user: AuthedUser = Depends(require_user),
) -> JSONResponse:
    """Research one idea from the board. Returns findings + the sources
    it cites, so the card carries the evidence and not just the verdict.

    Fail-soft by contract: any failure returns ok=False with a reason
    rather than a 500. A research call that dies must never cost the
    practitioner the card they were working on."""
    _require_owner(body.business_id, user.id)

    title = (body.title or "").strip()[:_TITLE_CAP]
    if not title:
        raise HTTPException(status_code=400, detail="an idea needs a title to research")

    name = _business_name(body.business_id)
    parts: List[str] = [f"Business: {name}.", f'The idea: "{title}"']
    note = (body.note or "").strip()[:_NOTE_CAP]
    if note:
        parts.append(f"Their own notes on it: {note}")
    shape = body.shape if isinstance(body.shape, dict) else {}
    labels = {
        "who": "Who it is for",
        "true": "What would have to be true",
        "test": "The smallest test",
        "cost": "What it costs",
        "instead": "What they would stop doing",
    }
    shaped = [f"- {labels[k]}: {str(v).strip()[:_SHAPE_CAP]}"
              for k, v in shape.items() if k in labels and str(v or "").strip()]
    if shaped:
        parts.append("How they have shaped it so far:\n" + "\n".join(shaped))
    parts.append(
        "Research this and return the JSON object. Search the web first."
    )

    # _call_claude carries the spend circuit-breaker, the model ladder AND
    # the BE#376 multi-text-block handling: with server tools the response
    # is [text][server_tool_use][web_search_tool_result][text]… and each
    # text block is a separate thought, so joining them ships Chief's
    # working notes. It applies _text_from_content internally and returns
    # the ANSWER — which is why sources are requested inside the JSON
    # rather than scraped off tool-result blocks this layer never sees.
    # Self-reported citations are weaker than scraped ones; the prompt
    # says so plainly, and it is the honest trade for not duplicating the
    # spend guard here.
    try:
        import chief_of_staff as cos
        async with httpx.AsyncClient(timeout=90.0) as client:
            text = await cos._call_claude(
                client,
                system=_SYSTEM,
                messages=[{"role": "user", "content": "\n\n".join(parts)}],
                max_tokens=_MAX_TOKENS,
                enable_web_search=True,
                business_id=body.business_id,
            )
    except Exception as e:
        logger.warning(f"[strategy.research] call failed: {type(e).__name__}: {e}")
        return JSONResponse({"ok": False, "error": "research_unavailable"})

    data = _extract_json(text or "")
    if not data:
        logger.info("[strategy.research] no JSON in response; returning raw")
        return JSONResponse({"ok": False, "error": "unreadable_result"})

    # Sources, validated rather than trusted: anything that is not an
    # http(s) URL is dropped, and duplicates collapse.
    sources: List[Dict[str, str]] = []
    seen = set()
    for item in (data.get("sources") or []):
        if not isinstance(item, dict) or len(sources) >= 8:
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        sources.append({
            "url": url[:500],
            "title": (str(item.get("title") or "") or url).strip()[:200],
        })

    verdicts = {"worth trying", "worth testing small", "crowded", "thin evidence"}
    verdict = str(data.get("verdict") or "").strip().lower()

    return JSONResponse({
        "ok": True,
        "summary": str(data.get("summary") or "").strip()[:1200],
        "findings": _clean_list(data.get("findings"), 400, 6),
        "watch_outs": _clean_list(data.get("watch_outs"), 400, 4),
        "verdict": verdict if verdict in verdicts else "",
        "sources": sources,
    })
