"""Does the Design Coach understand what people ask for? Simulated owners, the real Coach.

Each owner below talks the way real owners do: a few words, vague, on a phone. A cheap
model plays the owner from a private list of facts, and the real run_turn plays the
Coach, starting from Chief's real hand-off. Then the session is scored on things a
strong brief needs: did it hear the ask, ask what the site needs, skip what is on file,
recommend a layout that fits the ask, and promise nothing it can't do.

The scores find the failures. Read the transcripts too (they are saved beside the
scores): whether a question was a good one is still a judgment.

Nothing here can touch production:
  * every secret except the Anthropic key is deleted before anything is imported
  * the database address doesn't exist, and the dossier lives in memory
  * real database, messaging and payment hosts are refused at the socket
It costs real money, on production's key: about 35 cents an owner, so about $5 for all 14.

usage (from the Railway-linked checkout, so the Anthropic key is present):
  railway run python scripts/coach_ask_bench.py --dry                 no model calls
  railway run python scripts/coach_ask_bench.py --label after         every owner
  railway run python scripts/coach_ask_bench.py --tree <worktree> --only barber --label x
"""
import argparse
import asyncio
import concurrent.futures
import copy
import json
import os
import re
import socket
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--dry", action="store_true", help="prove the setup; no model calls")
parser.add_argument("--tree", default=str(Path(__file__).resolve().parent.parent),
                    help="the checkout whose Coach is tested")
parser.add_argument("--only", default="", help="comma-separated owner keys")
parser.add_argument("--label", default="run", help="name of this run's results file")
parser.add_argument("--out", default="", help="where results go (default: the system temp folder)")
parser.add_argument("--rescore", default="", help="score a saved run again, with no model calls")
parser.add_argument("--max-turns", type=int, default=13)
parser.add_argument("--cap-cents", type=float, default=600, help="start no new owner past this")
ARGS = parser.parse_args()

keep = os.environ.get("ANTHROPIC_API_KEY", "")
for name in list(os.environ):
    upper = name.upper()
    if name != "ANTHROPIC_API_KEY" and any(w in upper for w in (
            "KEY", "SECRET", "TOKEN", "PASSWORD", "DSN", "CREDENTIAL", "PRIVATE")):
        del os.environ[name]
os.environ.update(SUPABASE_URL="http://bench.invalid", SUPABASE_SERVICE_ROLE_KEY="bench",
                  SUPABASE_ANON="bench", PYTHONIOENCODING="utf-8")
if not keep and not ARGS.dry:
    sys.exit("No ANTHROPIC_API_KEY: run it with `railway run` from the linked checkout.")

_real_getaddrinfo = socket.getaddrinfo
REFUSED = ("supabase", "twilio", "resend", "stripe", "sentry", "docuseal", "livekit", "plaid", "bench.invalid")


def _guarded(host, *a, **k):
    if isinstance(host, str) and any(r in host.lower() for r in REFUSED):
        raise OSError(f"refused in the Coach bench: {host}")
    return _real_getaddrinfo(host, *a, **k)


socket.getaddrinfo = _guarded
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
TREE = Path(ARGS.tree).resolve()
os.chdir(TREE)
sys.path.insert(0, str(TREE))

import api_usage_logger  # noqa: E402
import chief_site_design  # noqa: E402
import design_coach as dc  # noqa: E402
import discovery  # noqa: E402
import offering_profiles  # noqa: E402
import sb_clients  # noqa: E402
import site_concept  # noqa: E402

ROWS = api_usage_logger.capture_in_memory()
OWNER_MODEL = "claude-haiku-5-5"

# ── the owners ───────────────────────────────────────────────────────
# ask: what they typed to Chief. knows: what they will say if asked, and only then.
# heard / job: words that show the Coach understood what the site is for (heard None:
# they said too little to echo). never_say: a promise this owner's ask tempts.
# fits: layouts that serve the ask. needs_where: must the Coach ask where they are?
OWNERS = [
    {"key": "barber", "name": "Marcus Cuts", "type": "barbershop", "booking": True,
     "offerings": [{"name": "Fade", "current_price": 35, "duration_min": 45},
                   {"name": "Lineup", "current_price": 20, "duration_min": 20}],
     "ask": "i need a website for my shop. nothing fancy i just want people to be able to find me and book",
     "voice": "short, lower case, no punctuation to speak of",
     "knows": "The shop is at 412 Grand Ave. Open tues thru sat 10 to 7. Mostly fades. All your photos are "
              "on your Instagram, none on this phone's app. Clients nod in the mirror and take a pic.",
     "heard": ["find", "book"], "job": ["find", "book"], "needs_where": True, "on_file": True,
     "fits": ["booking", "minimal", "split", "statement"]},
    {"key": "braids", "name": "Crowned by Dee", "type": "hair braiding", "booking": False, "offerings": [],
     "ask": "need a site so ppl stop dm'ing me for prices",
     "voice": "casual, abbreviations, a bit tired",
     "knows": "Works from a suite at 88 Peachtree St, by appointment. Knotless $180, boho $220, cornrows $90. "
              "Tues-Sat. Photos are on IG. A client cried happy tears over their wedding braids.",
     "heard": ["price", "dm"], "job": ["price", "dm"], "needs_where": True, "on_file": False,
     "fits": ["booking", "showcase", "grid", "split", "minimal"]},
    {"key": "tacos", "name": "La Esquina", "type": "restaurant", "booking": False,
     "offerings": [{"name": "Lunch plate", "current_price": 12}],
     "ask": "we need a website with the menu and hours. people keep calling asking if were open",
     "voice": "busy, plain, in the middle of a shift",
     "knows": "Corner of 5th and Mill. Mon-Sat 11 to 9, closed Sunday. Family recipes from Jalisco, 22 years. "
              "Has a few photos on the phone. Smell of carnitas hits you at the door.",
     "heard": ["menu", "hours", "open"], "job": ["menu", "hours", "open"], "needs_where": True, "on_file": True,
     "fits": ["bulletin", "minimal", "statement", "grid", "split", "showcase", "fullscreen", "magazine"]},
    {"key": "church", "name": "New Hope Fellowship", "type": "church", "booking": False, "offerings": [],
     "ask": "our church needs a website so visitors know when to come and what to expect",
     "voice": "warm, polite, a church office volunteer, not technical",
     "knows": "1200 Oak Rd. Sundays at 9 and 11, Wednesday 7pm. About 150 people. Casual dress, kids church, "
              "and greeters who will walk you in. There is no photo library yet.",
     "heard": ["visitor", "expect", "when"], "job": ["visitor", "expect", "when"], "needs_where": True, "on_file": False,
     "fits": ["bulletin", "minimal", "statement", "split", "editorial", "fullscreen", "story", "leader"]},
    {"key": "coach", "name": "Clarity with Jo", "type": "life coach", "booking": False, "offerings": [],
     "ask": "i want something professional and clean that gets me clients",
     "voice": "earnest, uses words like authentic and journey, vague at first",
     "knows": "Works over Zoom with people leaving corporate jobs. A 3-month package is $1,500. A free 30 minute "
              "call starts it. One client quit a hated job and opened a bakery.",
     "heard": ["professional", "clean", "client"], "job": ["client", "call", "trust"], "needs_where": False, "on_file": False,
     "fits": ["editorial", "statement", "split", "story", "minimal", "leader", "booking"]},
    {"key": "accountant", "name": "Reyes Tax & Books", "type": "accountant", "booking": False,
     "offerings": [{"name": "Personal return", "current_price": 250},
                   {"name": "Monthly books", "current_price": 400}],
     "ask": "i just need something that looks legit. not trying to win any awards",
     "voice": "dry, direct, a bit skeptical of all this",
     "knows": "Office at 300 Commerce St suite 4. Mon-Fri 9 to 5. Twenty years, mostly small contractors. Clients "
              "call when the IRS writes them. No photos, and you don't want your face on it.",
     "heard": ["legit", "award"], "job": ["legit", "trust"], "needs_where": False, "on_file": True,
     "fits": ["minimal", "statement", "editorial", "split", "bulletin", "sidebar"]},
    {"key": "boutique", "name": "Wren & Thread", "type": "clothing boutique", "booking": False, "offerings": [],
     "ask": "I sell dresses. I want my site to look like Aritzia",
     "voice": "quick, fashion-minded, knows what they like",
     "knows": "Shop at 71 Market St, Thu-Sun noon to 6. Dresses run $80-$200, small runs, sourced yourself. You "
              "like Aritzia because it's calm and the clothes get all the room. Photos on Instagram and your phone.",
     "heard": ["aritzia", "dress"], "job": ["dress", "shop", "buy"], "needs_where": True, "on_file": False,
     "fits": ["showcase", "grid", "magazine", "editorial", "bento", "fullscreen", "asymmetric",
              "statement", "minimal"]},
    {"key": "lawn", "name": "Big Mike's Lawn", "type": "lawn care", "booking": False, "offerings": [],
     "ask": "idk just a basic site. whatever you think looks good",
     "voice": "says idk a lot, very short, doesn't care about design",
     "knows": "Mows lawns in the north side suburbs, no shop, one truck, 9 years. $45 a cut. People call or text "
              "555-0142. Before and after pics on your phone. Customers say you never miss a week.",
     "heard": ["basic", "simple"], "job": ["call", "text", "lawn", "customers"], "needs_where": False, "on_file": False,
     "fits": ["minimal", "split", "bulletin", "showcase"]},
    # ── held out: added after the fixes were tuned on the owners above, so these
    # are the honest measure. Keep adding here; don't tune until they've run once.
    {"key": "oneword", "name": "Polished by Kim", "type": "nail salon", "booking": False, "offerings": [],
     "ask": "website",
     "voice": "one to three words whenever possible, never explains",
     "knows": "22 Bay St. Tue-Sat 10 to 6. Gel $45, acrylic $60. Photos on your phone. Clients can't stop "
              "looking at their hands in the car.",
     "heard": None, "job": ["nail", "book", "find", "polish", "hands", "site"], "needs_where": True, "on_file": False,
     "fits": ["booking", "showcase", "minimal", "split", "statement", "grid"]},
    {"key": "spanish", "name": "Taller Hermanos", "type": "auto repair", "booking": False, "offerings": [],
     "ask": "necesito una pagina para mi taller, que la gente sepa donde estoy y que hago",
     "voice": "Spanish only, short and plain, never writes in English",
     "knows": "Calle 8 #220. Lunes a sabado de 8 a 6. Frenos $120, cambio de aceite $40. 15 anos. Fotos en el "
              "telefono. Los clientes dicen que no les cobras de mas.",
     "heard": ["taller", "donde", "dónde"], "job": ["taller", "donde", "dónde", "encuentr"], "needs_where": True,
     "on_file": False, "language": "es",
     "fits": ["minimal", "statement", "split", "bulletin", "editorial", "grid"]},
    {"key": "impatient", "name": "Sparkle Home Cleaning", "type": "house cleaning", "booking": False, "offerings": [],
     "ask": "just build it already. i dont have time for 20 questions",
     "voice": "impatient, one line, annoyed by questions, wants it over with",
     "knows": "Covers the east valley, no office. $150 a house. Text 555-0199. No photos. Customers say the "
              "house smells like nobody lives there, in a good way.",
     "heard": ["quick", "fast", "time", "question", "few", "short"], "job": ["text", "clean", "call", "book"],
     "needs_where": False, "on_file": False, "max_q": 7,
     "fits": ["minimal", "statement", "split", "bulletin"]},
    {"key": "impossible", "name": "Still Waters Yoga", "type": "yoga studio", "booking": False, "offerings": [],
     "ask": "i want a site that gets me on the first page of google and has a member login and takes payments",
     "voice": "excited, full of ideas",
     "knows": "410 Pine St. Classes Mon-Sat 7am and 6pm. $20 a class, $120 a month. A few photos on your phone. "
              "People say the room goes quiet the moment they walk in.",
     "heard": ["google", "member", "payment"], "job": ["class", "google", "member", "pay", "join"], "needs_where": True,
     "on_file": False,
     "never_say": r"(first page|top of|rank|number one|#1)[^.?!]{0,60}\bgoogle\b|\bgoogle\b[^.?!]{0,60}(first page|top|rank|number one|#1)",
     "fits": ["bulletin", "minimal", "statement", "fullscreen", "split", "editorial", "booking", "grid"]},
    {"key": "daycare", "name": "Little Sprouts", "type": "daycare", "booking": False, "offerings": [],
     "ask": "parents need to trust us",
     "voice": "careful, warm, worried about getting this right",
     "knows": "55 Maple Ave. Mon-Fri 7 to 6. Licensed for 40 kids, 11 years. Tours by appointment. A parent cried "
              "on the first day and now sends every friend. No photos of the children online, ever.",
     "heard": ["trust", "parent"], "job": ["trust", "parent"], "needs_where": True, "on_file": False,
     "never_say": r"\b(photos?|pictures?|shots?) of (the |your |those )?(kids|children)\b[^.?!]{0,40}\b(add|upload|send|show)\b",
     "fits": ["editorial", "story", "minimal", "statement", "split", "bulletin", "leader"]},
    {"key": "foodtruck", "name": "Smoke Signal BBQ", "type": "food truck", "booking": False, "offerings": [],
     "ask": "ok so me and my husband started a food truck 3 yrs ago, we do bbq, and we move around so people always "
            "ask where we are. i want something that shows where we'll be this week but i also want it to look "
            "really nice like a real restaurant, not cheap. also we do catering which is where the money is",
     "voice": "chatty, friendly, tends to ramble a little",
     "knows": "Tuesdays at Ironworks Brewery, Fridays downtown at 3rd and Main, it changes. Brisket is the thing. "
              "Catering from $18 a head. Photos on Instagram.",
     "heard": ["where", "truck", "catering"], "job": ["where", "catering", "week"], "needs_where": False, "on_file": False,
     "fits": ["bulletin", "fullscreen", "split", "statement", "grid", "minimal", "magazine", "editorial", "booking"]},
]

# ── the in-memory world ──────────────────────────────────────────────
_DOSSIERS = {}
_BY_ID = {o["key"]: o for o in OWNERS}


def _fake_get(path, *a, **k):
    m = re.search(r"(?:business_id|id)=eq\.([a-z]+)", path)
    owner = _BY_ID.get(m.group(1)) if m else None
    if not owner:
        return []
    if path.startswith("/businesses"):
        return [{"name": owner["name"], "business_type": owner["type"],
                 "settings": {"owner_name": ""}}]
    if path.startswith("/offerings"):
        return copy.deepcopy(owner["offerings"])
    return []


def _fake_state(business_id, *a, **k):
    owner = _BY_ID[business_id]
    return {"store_url": "", "booking_enabled": owner["booking"],
            "booking_url": f"https://{business_id}.example/book" if owner["booking"] else ""}


sb_clients.sb_get_as_service = _fake_get
offering_profiles.business_state = _fake_state
site_concept.recent_layouts = lambda *a, **k: []
discovery.get_dossier = lambda bid: copy.deepcopy(_DOSSIERS.get(bid))
discovery.save_dossier = lambda bid, d: bool(_DOSSIERS.__setitem__(bid, copy.deepcopy(d)) or True)
chief_site_design._hand_built_block = lambda *a, **k: ""

_OWNER_SYSTEM = """You are playing a busy small-business owner texting with a design assistant in an app, to test it. Stay in character.
Reply the way real people text: one or two short sentences, never more than 30 words. Your voice: {voice}.
Answer only what was asked. Never volunteer a fact nobody asked about. If you have no answer, say so. Don't compliment the assistant.
Your business: {name}, a {type}. What you know: {knows}
Output only your message."""


def _owner_says(client, owner, transcript, screen):
    # the owner's side of the conversation, so the Coach's lines are its "user" turns
    msgs = [{"role": "assistant" if m["role"] == "user" else "user", "content": m["content"]}
            for m in transcript]
    if screen:
        msgs[-1] = {"role": "user", "content": f"{msgs[-1]['content']}\n\n[{screen}]"}
    resp = client.messages.create(
        model=OWNER_MODEL, max_tokens=120, thinking={"type": "disabled"},
        system=_OWNER_SYSTEM.format(**owner), messages=msgs)
    return "".join(b.text for b in resp.content if b.type == "text").strip(), resp.usage


# ── a session ────────────────────────────────────────────────────────
def run_owner(owner, client):
    bid = owner["key"]
    _DOSSIERS.pop(bid, None)
    asyncio.run(chief_site_design.handle_start_design_session(
        None, {"id": bid}, {"brief_notes": owner["ask"]}))
    transcript, turns, sim_tokens = [], [], [0, 0]
    photo_answers = 0
    for _ in range(ARGS.max_turns):
        turn = dc.run_turn(bid, transcript, mode="quick")
        if turn.get("error"):
            turns.append({"error": turn["error"]})
            break
        turns.append({k: turn.get(k) for k in ("reply", "stage", "ask", "gallery", "pair", "chips", "reflect_back")})
        transcript.append({"role": "assistant", "content": turn["reply"]})
        if turn.get("done") or (turn.get("stage") == "brief" and turn.get("reflect_back")):
            break
        gallery = turn.get("gallery") or {}
        if gallery.get("options"):
            # tapping the card the Coach marked: what most owners do
            pick = gallery.get("recommended") or gallery["options"][0]
            transcript.append({"role": "user", "content": f"I'll take {pick}"})
            continue
        screen = ""
        if turn.get("ask") == "photos":
            screen = ("An upload card for photos is on your screen. You don't add any now" if photo_answers
                      else "An upload card for photos is on your screen. Say where your photos are and don't add any")
            photo_answers += 1
        elif turn.get("pair"):
            screen = f"Two choices on screen: {turn['pair'].get('a')} or {turn['pair'].get('b')}. Pick one"
        said, usage = _owner_says(client, owner, transcript, screen)
        sim_tokens[0] += usage.input_tokens
        sim_tokens[1] += usage.output_tokens
        transcript.append({"role": "user", "content": said or "not sure"})
    return {"key": bid, "ask": owner["ask"], "transcript": transcript, "turns": turns,
            "dossier": _DOSSIERS.get(bid) or {}, "sim_tokens": sim_tokens}


# ── the score ────────────────────────────────────────────────────────
_ASKED_WHERE = re.compile(r"\bwhere('s| is| are|abouts)\b|\baddress\b|\blocated\b|\blocation\b|\bneighbou?rhood\b|"
                          r"\bstreet\b|\bpart of town\b|\bwhat area\b", re.I)
_REASKED_OFFERS = re.compile(r"\bwhat (do|does) .{0,30}(cost|charge)\b|\bwhat do you (sell|offer|charge)\b|"
                             r"\bwhat are your (services|prices)\b|\bwhat (services|people buy)\b|"
                             r"\bwhat .{0,20}\b(buy|book) from you\b|\b(need|have|get) your (prices|services|rates)\b",
                             re.I)
_FETCH = re.compile(
    r"\b(pull|grab|lift|borrow|work from|draw from|bring in|import|take|use|scrape|fetch)\b[^.?!]{0,70}"
    r"\b(instagram|insta|ig|facebook|tiktok|feed|from there)\b|"
    r"\b(straight|right|directly) (from|off) (your |the )?(instagram|insta|ig|facebook|feed)\b|"
    r"\b(cuts|photos|pics|pictures|shots|images) come\b[^.?!]{0,40}\b(instagram|insta|ig|facebook|feed)\b|"
    r"\b(until|once|when) the (ig|insta|instagram|facebook) (photos|pics|shots)\b", re.I)
_SPANISH = re.compile(r"\b(el|la|los|las|que|qué|tu|tus|para|donde|dónde|con|una|un|de|y|es|por)\b", re.I)
_HONEST = re.compile(r"\b(can't|cannot|can not|won't|no way|save|screenshot|download|add them|upload|no promise|"
                     r"not promise|nobody can|isn't something)\b", re.I)
_MADE_UP = re.compile(r"\$\s?\d[\d,]*|\b\d+\+? (?:years?|clients?|reviews?|customers?|locations?)\b", re.I)


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or "")) if s.strip()]


def score(owner, run):
    turns = [t for t in run["turns"] if not t.get("error")]
    replies = [str(t.get("reply") or "") for t in turns]
    all_coach = " ".join(replies)
    reflect = [str(x) for t in turns for x in (t.get("reflect_back") or [])]
    said = " ".join(m["content"] for m in run["transcript"] if m["role"] == "user") + " " + owner["ask"]
    known = said + " " + json.dumps(owner["offerings"])
    d = run["dossier"]
    truth = d.get("truth") or {}
    identity = d.get("identity") or {}

    def has(words, text):
        return any(w.lower() in text.lower() for w in words)

    checks = {}
    checks["reached_the_brief"] = bool(reflect)
    if owner["heard"]:
        checks["heard_the_ask"] = bool(replies) and has(owner["heard"], replies[0])
    if owner.get("language") == "es":
        checks["answered_in_their_language"] = bool(replies) and all(
            len(_SPANISH.findall(r)) >= 3 for r in replies)
        checks["brief_in_their_language"] = bool(reflect) and len(_SPANISH.findall(" ".join(reflect))) >= 6
    if owner.get("never_say"):
        tempted = [x for text in replies + reflect for x in _sentences(text)
                   if re.search(owner["never_say"], x, re.I) and not _HONEST.search(x)]
        checks["no_tempted_promise"] = not tempted
        promises_extra = tempted
    else:
        promises_extra = []
    checks["kept_the_job"] = has(owner["job"], reflect[0]) if reflect else False
    if owner["needs_where"]:
        checks["asked_where"] = bool(_ASKED_WHERE.search(all_coach)) or bool(truth.get("address"))
        checks["saved_where"] = bool(truth.get("address"))
    if owner["on_file"]:
        checks["no_reask_of_offers"] = not _REASKED_OFFERS.search(all_coach)
    promises = [s for text in replies + reflect for s in _sentences(text)
                if _FETCH.search(s) and not _HONEST.search(s)]
    checks["no_false_promise"] = not promises
    known_numbers = set(re.findall(r"\d+", known.replace(",", "")))
    invented = [m.group(0) for line in reflect for m in _MADE_UP.finditer(line)
                if re.search(r"\d+", m.group(0).replace(",", "")).group(0) not in known_numbers]
    checks["nothing_invented"] = not invented
    pages = [t["gallery"] for t in turns if (t.get("gallery") or {}).get("kind") == "page"]
    recommended = pages[0].get("recommended") if pages else ""
    recommended = str(recommended or "").replace("page-", "")
    if pages:
        checks["layout_fits_the_ask"] = recommended in owner["fits"]
    if has(["book", "appointment"], owner["ask"]):
        checks["saved_the_main_action"] = bool(identity.get("primary_action"))
    questions = sum(1 for m in run["transcript"] if m["role"] == "user")
    checks["few_questions"] = questions <= owner.get("max_q", 9)
    return {"key": owner["key"], "checks": checks, "questions": questions,
            "recommended": recommended, "promises": promises + promises_extra, "invented": invented,
            "page_reasons": (pages[0].get("notes") if pages else None)}


def main():
    owners = [o for o in OWNERS if not ARGS.only or o["key"] in ARGS.only.split(",")]
    if ARGS.rescore:
        saved = json.loads(Path(ARGS.rescore).read_text(encoding="utf-8"))
        passed = total = 0
        for run in saved["runs"]:
            s = score(_BY_ID[run["key"]], run)
            bad = [k for k, v in s["checks"].items() if not v]
            passed += len(s["checks"]) - len(bad)
            total += len(s["checks"])
            print(f"{run['key']:<11} {len(s['checks']) - len(bad)}/{len(s['checks'])} "
                  f"q={s['questions']} layout={s['recommended'] or '-'} misses={bad}")
        print(f"\nTOTAL {passed}/{total}")
        return
    if ARGS.dry:
        for o in owners:
            ctx = dc._known_context(o["key"])
            print(f"{o['key']}: known context {len(ctx)} chars")
        print("dry run: no model calls")
        return
    from anthropic import Anthropic
    client = Anthropic(api_key=keep, timeout=60.0, max_retries=2)
    out = Path(ARGS.out) if ARGS.out else Path(os.environ.get("TEMP") or "/tmp") / "coach-ask-bench"
    out.mkdir(parents=True, exist_ok=True)

    def spent():
        return sum(float(r.get("cents") or 0) for r in ROWS)

    def one(o):
        if spent() > ARGS.cap_cents:
            print(f"{o['key']}: skipped, past the cap")
            return None
        run = run_owner(o, client)
        run["score"] = score(o, run)
        s = run["score"]
        bad = [k for k, v in s["checks"].items() if not v]
        print(f"{o['key']:<11} {len(s['checks']) - len(bad)}/{len(s['checks'])} "
              f"q={s['questions']} layout={s['recommended'] or '-'} misses={bad}")
        return run

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        runs = [r for r in pool.map(one, owners) if r]
    total = sum(len(r["score"]["checks"]) for r in runs)
    passed = sum(sum(r["score"]["checks"].values()) for r in runs)
    sim = sum(r["sim_tokens"][0] * 0.10 + r["sim_tokens"][1] * 0.50 for r in runs) / 10000  # cents
    print(f"\nTOTAL {passed}/{total}  spent {spent() + sim:.1f} cents")
    (out / f"{ARGS.label}.json").write_text(
        json.dumps({"label": ARGS.label, "tree": str(TREE), "passed": passed, "total": total,
                    "cents": spent() + sim, "runs": runs}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"saved {out / (ARGS.label + '.json')}")


if __name__ == "__main__":
    main()
