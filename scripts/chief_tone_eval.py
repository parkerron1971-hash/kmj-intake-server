"""Does Chief put tone notes on the right replies? (chief_tone, 2026-10-18)

Thirty spoken questions against one fictional business: about half are
routine (a schedule, a figure, a how-to, small talk) and should come back
with NO notes; the rest carry news, and should open with the right note —
[pleased] for everyday good news, [proud] for a big win, [gentle] for
hardship, [steady] for money owed or a problem, and [breathe] [steady]
where good news turns to bad.

The prompt is the live voice turn's: Chief's system prompt, the voice
delivery block, the tone-notes block and the answer-accuracy rules, on the
voice lane's model and effort. No business records are loaded and no
generated actions run. Provider usage is metered normally. Run --live.

  railway run python -X utf8 scripts/chief_tone_eval.py --live --out replies.json
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chief_of_staff as chief  # noqa: E402
import chief_models  # noqa: E402
import chief_tone  # noqa: E402
import chief_truth as truth  # noqa: E402

RECORDS = """
FICTIONAL BUSINESS RECORDS (test data — treat as this business's current records; today is Monday, October 19, 2026):
- Business: Bright Path Coaching, run by the owner, Kevin. 20 active clients (goal: 20 — reached today when Jordan Price signed).
- Payments today: Monica Walton paid invoice INV-104, $1,200, at 8:40 this morning.
- Overdue invoices: Derek Hayes INV-097 $650 (due Sep 30); Lena Brooks INV-099 $450 (due Oct 2). Together $1,100.
- New booking: Jordan Price bought the 12-week Growth package ($3,600) yesterday — the biggest single sale this month.
- Revenue: October so far $14,800 — the best month since the business started (previous best $12,100 in May).
- Calendar: Tue Oct 20 9:00am call with Aisha Grant (proposal review); Thu Oct 22 2:00pm session with Carlos Diaz (60 min); Fri Oct 23 11:00am team meeting.
- Cancellation: Denise Moore cancelled her Thursday 4:00pm session; she wrote that money is tight right now.
- Client news: Carlos Diaz's mother passed away last week; he asked to keep Thursday but go lighter.
- Reviews: new 5-star review from Priya Shah yesterday: "Changed how I run my business."
- Tasks due today: send proposal to Aisha Grant; update website pricing; renew business insurance.
- Insurance renewal: $380, due Oct 25.
- Inbox: 4 unread emails, one from the bank about the insurance payment.
- The 12-week Growth package is $3,600; the 6-week Starter is $1,500.
"""

# (id, message, kind, acceptable first notes). "none" = no notes at all;
# "turn" = an opening good-news note, then [breathe] [steady].
CASES = [
    ("cal_tomorrow", "What's on my calendar tomorrow?", "routine", {"none"}),
    ("team_meeting", "When's the team meeting?", "routine", {"none"}),
    ("unread", "How many unread emails do I have?", "routine", {"none"}),
    ("tasks", "What do I need to get done today?", "routine", {"none"}),
    ("package_price", "Remind me what the 12-week package costs.", "routine", {"none"}),
    ("howto_client", "How do I add a new client in the app?", "routine", {"none"}),
    ("thanks", "Thanks, that's all for now.", "routine", {"none"}),
    ("who_tomorrow", "Who's my call with tomorrow?", "routine", {"none"}),
    ("insurance_when", "When is the insurance due?", "routine", {"none", "steady"}),
    ("monica_last", "What's Monica's last name again?", "routine", {"none"}),
    ("good_morning", "Good morning!", "routine", {"none"}),
    ("insta_ideas", "What should I post on Instagram this week?", "routine", {"none"}),
    ("thursday_len", "How long is Carlos's session on Thursday?", "routine", {"none", "gentle"}),
    ("starter_vs", "What's the difference between the Starter and the Growth package?", "routine", {"none"}),
    ("pricing_advice", "Should I raise my prices next year?", "routine", {"none"}),
    ("monica_paid", "Did Monica pay yet?", "news", {"pleased"}),
    ("reviews", "Any new reviews?", "news", {"pleased", "proud"}),
    ("bookings", "Did anyone book recently?", "news", {"pleased", "proud"}),
    ("month", "How's this month going?", "news", {"proud", "turn"}),
    ("goal", "Where am I on my client goal?", "news", {"proud"}),
    ("owes", "Who owes me money right now?", "news", {"steady"}),
    ("denise", "Did Denise cancel?", "news", {"steady", "gentle"}),
    ("at_risk", "Is anything at risk this week?", "news", {"steady"}),
    ("carlos", "How's Carlos doing?", "news", {"gentle"}),
    ("exhausted", "I'm exhausted, honestly. Everything feels like too much right now.", "news", {"gentle"}),
    ("lost_client", "I just lost a big client and I'm pretty down about it.", "news", {"gentle"}),
    ("rundown", "Give me a quick rundown of today.", "news", {"turn", "pleased"}),
    ("money_news", "Any money news?", "news", {"turn"}),
    ("business_look", "How's business looking overall?", "news", {"turn", "proud"}),
    ("week_ahead", "Good news and bad news for this week?", "news", {"turn"}),
]

_ANY_BRACKET = re.compile(r"\[[^\]\[]{1,40}\]")


def label(reply: str) -> str:
    notes = chief_tone.notes_in(reply)
    if not notes:
        return "none"
    first = notes[0]
    rest = notes[1:]
    if first in ("pleased", "proud") and rest[:2] == ["breathe", "steady"]:
        return "turn"
    return first


def shape_problems(reply: str) -> list:
    """The recipe: a note opens the reply, at most one change, made with a
    breath and steady, never more than three notes, nothing else bracketed."""
    out = []
    notes = chief_tone.notes_in(reply)
    if notes and not reply.lstrip().startswith("["):
        out.append("first note is not at the start")
    if len(notes) > 3:
        out.append("more than three notes")
    changes = [n for n in notes[1:] if n in chief_tone.TONES]
    if len(changes) > 1:
        out.append("more than one change")
    if changes and (changes != ["steady"] or "breathe" not in notes):
        out.append("a change that is not [breathe] [steady]")
    stray = [b for b in _ANY_BRACKET.findall(chief_tone.strip(reply)) if not b.startswith("[ACTION")]
    if stray:
        out.append(f"other bracketed text: {stray}")
    return out


async def main(out_path, only):
    ctx = {key: [] for key in ("queue", "events", "sessions", "insights", "modules", "at_risk",
                               "contacts_lookup")}
    ctx.update(business={"name": "Bright Path Coaching"}, module_counts={},
               contacts_total=20, contacts_by_status={}, avg_health=None)
    system = (chief._build_system_prompt(ctx, False) + chief_models.VOICE_DELIVERY_BLOCK
              + chief_tone.PROMPT_BLOCK + truth.AUTHOR_RULES + RECORDS)
    model = chief_models.model_for("voice")
    rows, tally = [], {"routine": [0, 0], "news": [0, 0]}
    async with httpx.AsyncClient(timeout=90) as client:
        for cid, message, kind, ok in CASES:
            if only and cid not in only:
                continue
            raw = await chief._call_claude_once(
                client, system, [{"role": "user", "content": message}], model=model,
                max_tokens=chief_models.max_tokens_for("voice", model=model),
                effort=chief_models.effort_for("voice", model=model), enable_web_search=False)
            _, reply = chief._extract_actions_and_clean(raw)
            got = label(reply)
            problems = shape_problems(reply)
            passed = got in ok and not problems
            tally[kind][0] += passed
            tally[kind][1] += 1
            row = {"id": cid, "kind": kind, "message": message, "expected": sorted(ok),
                   "got": got, "pass": passed, "problems": problems, "reply": reply,
                   "words": len(chief_tone.strip(reply).split())}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {k: f"{v[0]}/{v[1]}" for k, v in tally.items()}
    toned = sum(1 for r in rows if r["got"] != "none")
    summary["replies_with_notes"] = f"{toned}/{len(rows)}"
    print(json.dumps({"summary": summary}), flush=True)
    if out_path:
        Path(out_path).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1,
                                             ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; configured provider calls are metered")
    asyncio.run(main(args.out, set(args.only or [])))
