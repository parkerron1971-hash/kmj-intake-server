"""business_marketing_engine.py — a business's week, decided by rules (the pure half).

B7 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D2). Solutionist's own
desk diagnoses one problem with the number that proves it and picks plays
from a fixed library (marketing_engine); every business gets the same
engine over its own numbers (marketing_signals), its own facts
(creative_director.business_facts) and its own profile (marketing_profile).

  diagnose(signals)                          one problem, the sentence that proves it, its numbers
  pick_plays(problem, n, signals, profile)   up to three plays and n slots, each with its reason
  verified_facts(facts)                      what a caption may state (a hidden price stays out)
  check_caption / check_flyer                the platform's checks, with the business's own site,
                                             its own prices, and up to three hashtags in a caption

The slot assignment, the ranking by results, the number rule and the link
rule are marketing_engine's own functions, called with the business's
parameters; Solutionist's desk is unchanged by them.

PURE. No reads, no writes, no model call. The weekly suggestion
(business_marketing_planner, B8) and the preview call it; the five-post week
comes with B9.

THE RULES, first match wins. A rule whose signal is None (it could not be
read) is skipped: a failed read is never an empty calendar or a quiet week.
  1. bookings_down         fill_the_calendar        next 7 days < 70% of the 4-week weekly average (at least 3 a week)
  2. empty_week            fill_the_calendar        nothing booked in the next 7 days and open times on 2 or more of them
  3. something_new         tell_about_new           an offering or news post from the last 21 days no plan has been about
  4. visits_without_leads  turn_visits_into_leads   20 or more visits in 7 days and no new contact
  5. traffic_down          get_found                visits < 70% of the weekly average before (at least 10 a week)
  6. gone_quiet            stay_visible             nothing posted in 14 days and nothing approved ahead
  7. barely_seen           get_found                fewer than 10 visits in 7 days on a site whose counter works
  8. steady                stay_visible             nothing is off
The calendar comes first because an empty chair this week cannot be sold
next week; the rest follow the platform's order.

SOLUTIONIST'S OWN (B15). The platform business on the suite
(platform_suite.is_platform) keeps the platform desk's own engine: its
signals carry profile 'platform' (marketing_signals.platform_signals) and its
profile platform True (marketing_profile.platform_profile), and diagnose,
pick_plays, check_caption and check_flyer then answer with
marketing_engine's rules (its problems, its five plays, no hashtag, no
address in a caption, a founding-seat post quotes only the founding price).
platform_facts is its facts. PLAYS still lists only the business plays; a
platform play's entry is found through it (PLAYS[id]) for the planner's
caption request and flyer, and never offered to a business.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import marketing_engine as platform
from marketing_profile import HASHTAGS_MAX
from marketing_signals import news_key, offering_key

# ── the closed library ─────────────────────────────────────────────────

PROBLEMS = {
    'fill_the_calendar': 'Fill the calendar',
    'turn_visits_into_leads': 'Turn visits into leads',
    'get_found': 'Get found by more people',
    'tell_about_new': 'Tell people about something new',
    'stay_visible': 'Stay in front of people',
}

NO_NAMES = 'Name no person: no owner, staff, client or customer.'


class _Library(dict):
    """The business plays. A missing id is looked up among Solutionist's own
    plays (B15), so the planner's PLAYS[play_id] serves both; `in`,
    iteration and .get() see the business plays alone."""

    def __missing__(self, key):
        return PLATFORM_PLAYS[key]


PLAYS = _Library({
    'offer_spotlight': {
        'label': 'Show one offering',
        'solves': ('fill_the_calendar', 'turn_visits_into_leads', 'tell_about_new', 'stay_visible', 'get_found'),
        'needs': 'offering',
        'max_per_week': 2,
        'eyebrow': 'FEATURED',
        'brief': 'Feature the subject offering: what it is and who it is for, in plain words, from its name and '
                 'description in the facts. Give its price only exactly as the facts give it for this offering. '
                 + NO_NAMES,
    },
    'book_a_time': {
        'label': 'Invite a booking',
        'solves': ('fill_the_calendar', 'turn_visits_into_leads'),
        'needs': 'booking',
        'max_per_week': 2,
        'eyebrow': 'BOOK NOW',
        'brief': 'Invite the reader to book a time online. Do not say how many openings are left, which times are '
                 'open, or that anything is limited or ending; the facts do not say so. ' + NO_NAMES,
    },
    'whats_new': {
        'label': 'Share something new',
        'solves': ('tell_about_new', 'stay_visible'),
        'needs': 'new',
        'max_per_week': 2,
        'eyebrow': 'NEW',
        'brief': 'Tell people about the subject, a new offering or a news post from the site, using only what the '
                 'facts say about it. ' + NO_NAMES,
    },
    'useful_tip': {
        'label': 'Share a useful tip',
        'solves': ('get_found', 'stay_visible', 'turn_visits_into_leads', 'fill_the_calendar', 'tell_about_new'),
        'needs': None,
        'max_per_week': 3,        # needs no subject, so it is what fills a thin week
        'eyebrow': 'TIP',
        'brief': 'One practical tip the audience can use today, in the business\'s own field, then one line on how '
                 'the business helps, drawn only from the facts. Promise no results. ' + NO_NAMES,
    },
    'meet_us': {
        'label': 'Meet us',
        'solves': ('get_found', 'turn_visits_into_leads', 'stay_visible'),
        'needs': None,
        'max_per_week': 1,
        'eyebrow': 'MEET US',
        'brief': 'Introduce the business as "we": what we do, where, and what we care about, from the facts '
                 '(tagline, offerings, city). ' + NO_NAMES + ' Not even the owner.',
    },
    'come_back': {
        'label': 'Welcome people back',
        'solves': ('fill_the_calendar', 'stay_visible'),
        'needs': None,
        'max_per_week': 1,
        'eyebrow': 'WELCOME BACK',
        'brief': 'A warm invitation to people who have been before to come back. No discount, offer or deadline '
                 'unless the facts state it. ' + NO_NAMES,
    },
})

# Solutionist's own plays (marketing_engine.PLAYS), with a flyer eyebrow
# each, for the platform business on the suite (B15).
PLATFORM_EYEBROWS = {'feature_spotlight': 'NEW', 'founder_invitation': 'FOUNDING SEAT', 'workflow_tip': 'TIP',
                     'behind_the_build': 'WHY WE BUILT IT', 'question_answered': 'YOUR QUESTION'}
PLATFORM_PLAYS = {k: {**v, 'eyebrow': PLATFORM_EYEBROWS.get(k, 'SOLUTIONIST')} for k, v in platform.PLAYS.items()}

# Which plays each problem reaches for first, before any results exist.
PREFERENCE = {
    'fill_the_calendar': ('book_a_time', 'offer_spotlight', 'come_back'),
    'turn_visits_into_leads': ('book_a_time', 'offer_spotlight', 'meet_us'),
    'get_found': ('useful_tip', 'meet_us', 'offer_spotlight'),
    'tell_about_new': ('whats_new', 'offer_spotlight', 'useful_tip'),
    'stay_visible': ('useful_tip', 'offer_spotlight', 'meet_us'),
}
FILLER = 'useful_tip'
SUBJECTS_PER_PLAY = 5

# ── diagnosis ─────────────────────────────────────────────────────────

BOOKINGS_DOWN = 0.7
MIN_WEEKLY_BOOKINGS = 3
EMPTY_WEEK_OPEN_DAYS = 2
LEADS_MIN_VISITS = 20
TRAFFIC_DOWN = 0.7
TRAFFIC_MIN_BEFORE = 10
QUIET_DAYS = 14
FEW_VISITS = 10
RULES = ('bookings_down', 'empty_week', 'something_new', 'visits_without_leads', 'traffic_down', 'gone_quiet',
         'barely_seen', 'steady')


def _zone(name: Any) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(str(name)) if name else None
    except Exception:
        return None


def _s(n: Any) -> str:
    return '' if n == 1 else 's'


def _found(problem, rule, urgency, evidence, **numbers):
    return {'primary_problem': problem, 'rule': rule, 'urgency': urgency, 'evidence': evidence, 'numbers': numbers}


def diagnose(s: Dict[str, Any]) -> Dict[str, Any]:
    """One problem from the closed set, the sentence that proves it, its
    numbers and how urgent it is. Dates are on the business's clock
    (signals['time_zone']). Solutionist's own signals (profile 'platform',
    B15) get the platform desk's own rules."""
    if s.get('profile') == 'platform':
        return platform_diagnose(s)
    tz = _zone(s.get('time_zone')) or ZoneInfo('UTC')
    t, leads, b, cap, p = s.get('traffic'), s.get('leads'), s.get('bookings'), s.get('capacity'), s.get('posts')

    if b and b['weekly_before'] >= MIN_WEEKLY_BOOKINGS and b['next_7_days'] < BOOKINGS_DOWN * b['weekly_before']:
        n, avg = b['next_7_days'], b['weekly_before']
        return _found('fill_the_calendar', 'bookings_down', 'high',
                      f'{n} booking{_s(n)} in the next 7 days so far, against about {round(avg)} at this point in '
                      f'each of the last 4 weeks.', bookings_next_7_days=n, weekly_bookings_before=avg)
    if b is not None and b['next_7_days'] == 0 and cap and cap.get('open_days', 0) >= EMPTY_WEEK_OPEN_DAYS:
        return _found('fill_the_calendar', 'empty_week', 'high',
                      f'Nothing is booked for the next 7 days, and {cap["open_days"]} of them still have open times.',
                      bookings_next_7_days=0, open_days=cap['open_days'])

    offers, news = s.get('unmarketed_offerings') or [], s.get('unmarketed_news') or []
    if offers or news:
        more = len(offers) + len(news) - 1
        tail = f' ({more} more new thing{_s(more)} too)' if more else ''
        if offers:
            o = offers[0]
            evidence = (f'"{o["name"]}" was added on {platform._day(o.get("created_at"), tz)} and no post has told '
                        f'anyone yet{tail}.')
        else:
            n = news[0]
            evidence = (f'"{n["title"]}" went up on the site\'s news page on {platform._day(n.get("published_at"), tz)} '
                        f'and no post has told anyone yet{tail}.')
        return _found('tell_about_new', 'something_new', 'medium', evidence, new_things=len(offers) + len(news))

    if t and leads and t['visits'] >= LEADS_MIN_VISITS and leads['last_7_days'] == 0:
        return _found('turn_visits_into_leads', 'visits_without_leads', 'high',
                      f'{t["visits"]} people visited the site in the last 7 days and no new contact came in.',
                      visits=t['visits'], new_contacts=0)
    before = (t or {}).get('weekly_visits_before')
    if t and before is not None and before >= TRAFFIC_MIN_BEFORE and t['visits'] < TRAFFIC_DOWN * before:
        drop = round(100 * (1 - t['visits'] / before))
        return _found('get_found', 'traffic_down', 'medium',
                      f'Site visits are down {drop}%: {t["visits"]} in the last 7 days, against about '
                      f'{round(before)} a week before that.', visits=t['visits'], weekly_visits_before=before)
    if p is not None and p['published_last_14_days'] == 0 and p['approved_next_7_days'] == 0:
        since = (f'since {platform._day(p["last_published"], tz)}' if p.get('last_published')
                 else f'in the last {p.get("looked_back_days") or 90} days')
        return _found('stay_visible', 'gone_quiet', 'high',
                      f'No post has gone out {since}, and none is approved for the week ahead.',
                      published_last_14_days=0, approved_next_7_days=0)
    if t and t.get('counted_any') and t['visits'] < FEW_VISITS and (before is None or before < FEW_VISITS):
        v = t['visits']
        evidence = ('Nobody visited the site in the last 7 days.' if v == 0
                    else f'Only {v} {"person" if v == 1 else "people"} visited the site in the last 7 days.')
        return _found('get_found', 'barely_seen', 'medium', evidence, visits=v)

    if t:
        evidence = (f'Nothing is off this week ({t["visits"]} visit{_s(t["visits"])} to the site in the last 7 '
                    'days). Showing up steadily keeps it that way.')
    else:
        evidence = "The site's numbers could not be read just now, so this week plans for steady presence."
    return _found('stay_visible', 'steady', 'low', evidence)


# ── facts: only what the business's own site publishes ─────────────────

FACT_KEYS = ('name', 'type', 'tagline', 'phone', 'email', 'address', 'city', 'region')
MAX_OFFERINGS = 20


def _price_text(o: Dict[str, Any]) -> Optional[str]:
    """The price as the site shows it, or None when hidden or unknown."""
    if o.get('show_price_to_customer') is False or o.get('price_hidden'):
        return None
    price = o.get('price', o.get('current_price'))
    if isinstance(price, str):
        return price.strip() or None
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        import creative_director
        return creative_director._price({'price': price, 'currency': str(o.get('currency') or 'USD').upper()})
    return None


def _offering_fact(o: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(o, dict) or o.get('is_active') is False or o.get('archived_at'):
        return None
    name = ' '.join(str(o.get('name') or '').split())
    if not name:
        return None
    item: Dict[str, Any] = {'name': name}
    price = _price_text(o)
    if price:
        item['price'] = price
    minutes = o.get('minutes', o.get('duration_min'))
    if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
        item['minutes'] = minutes
    if isinstance(o.get('description'), str) and o['description'].strip():
        item['about'] = o['description'].strip()[:300]
    return item


def verified_facts(facts: Optional[Dict[str, Any]], *, new_offerings: Optional[List[Dict[str, Any]]] = None,
                   news: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """What a caption may state as fact. facts: creative_director.business_facts
    (what the business's own site publishes: hidden prices are already out).
    new_offerings and news: from marketing_signals. A price marked hidden, or
    an offering that is inactive or archived, stays out even if a caller
    passes it in. Brand colours and web addresses are left out: their digits
    are not facts a caption may quote, and the link is added after it."""
    facts = facts or {}
    out: Dict[str, Any] = {}
    for key in FACT_KEYS:
        value = facts.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    out['books_online'] = bool(facts.get('booking_url'))
    offerings, seen = [], set()
    for raw in list(facts.get('offerings') or []) + list(new_offerings or []):
        item = _offering_fact(raw)
        if item and item['name'].lower() not in seen:
            seen.add(item['name'].lower())
            offerings.append(item)
    if offerings:
        out['offerings'] = offerings[:MAX_OFFERINGS]
    if news:
        out['news'] = [{'title': n.get('title'), 'body': str(n.get('body') or '')[:1500],
                        'published_at': n.get('published_at')} for n in news[:5] if n.get('title')]
    return out


_AMOUNT = re.compile(r'\d[\d,]*(?:\.\d+)?')


def _amount(price: Any) -> Optional[float]:
    match = _AMOUNT.search(str(price or ''))
    return float(match.group(0).replace(',', '')) if match else None


def offering_prices(facts: Dict[str, Any], offering: Optional[str] = None) -> set:
    """The prices the facts state: every offering's, or one offering's."""
    items = (facts or {}).get('offerings') or []
    if offering is not None:
        wanted = ' '.join(str(offering).split()).lower()
        items = [o for o in items if o.get('name', '').lower() == wanted]
    return {a for a in (_amount(o.get('price')) for o in items) if a is not None}


def price_problem(text: str, facts: Dict[str, Any], offering: Optional[str] = None) -> Optional[str]:
    """A dollar amount must be a price the facts state; in a post about one
    offering, that offering's own price (marketing_engine.price_problem's
    rule: a real price of the wrong offering is still the wrong price)."""
    amounts = {float(a.replace(',', '')) for a in platform._DOLLARS.findall(text or '')}
    if not amounts:
        return None
    if not amounts <= offering_prices(facts, offering):
        return "a price that is not this offering's price" if offering else 'a price that is not in the facts'
    return None


def allowed_numbers(facts: Dict[str, Any]) -> set:
    return platform._numbers(json.dumps(facts or {}, default=str))


def own_hosts(profile: Dict[str, Any]) -> List[str]:
    """The hosts a business's caption may name: its own site's (none: no address at all)."""
    return list((profile or {}).get('own_hosts') or [])


def check_caption(text: str, facts: Dict[str, Any], profile: Dict[str, Any],
                  offering: Optional[str] = None, *, max_hashtags: int = HASHTAGS_MAX) -> Optional[str]:
    """Why a caption cannot be used, or None: the platform's rules (length,
    every number from the facts) with the business's own site as the only
    address it may name, its own prices, and up to three hashtags (Kevin,
    2026-10-07; Solutionist's own desk still takes none). The flyer takes
    no hashtag (check_flyer). Solutionist's own profile (B15) gets the
    platform desk's rules."""
    if (profile or {}).get('platform'):
        return platform_check_caption(text, facts, offering)
    return (platform.check_caption(text, allowed_numbers(facts), own_hosts=own_hosts(profile),
                                   max_hashtags=max_hashtags)
            or price_problem(text, facts, offering))


def check_flyer(copy: Any, facts: Dict[str, Any], profile: Dict[str, Any],
                offering: Optional[str] = None) -> Optional[str]:
    if (profile or {}).get('platform'):
        return platform_check_flyer(copy, facts, offering)          # B15
    problem = platform.check_flyer(copy, allowed_numbers(facts), own_hosts=own_hosts(profile))
    if problem:
        return problem
    return price_problem(' '.join(str(v) for v in copy.values()), facts, offering)


# ── plays and slots ───────────────────────────────────────────────────

def _subjects(play: str, signals: Dict[str, Any], facts: Dict[str, Any], profile: Dict[str, Any]):
    """What each slot of this play would be about, in the order to use them,
    each with the page its link opens (always the business's own)."""
    need = PLAYS[play]['needs']
    landing = profile.get('landing_url')
    booking = profile.get('booking_url')
    site = profile.get('site_url')
    used = set(signals.get('used_subjects') or [])
    if need == 'offering':
        items = (facts or {}).get('offerings') or []
        new = {offering_key(o.get('name')) for o in signals.get('unmarketed_offerings') or []}

        def subject(o):
            return {'subject_key': offering_key(o['name']), 'subject': o['name'], 'offering': o['name'],
                    'landing_url': booking if booking and o.get('minutes') else landing}
        first = [o for o in items if offering_key(o['name']) in new]
        unused = [o for o in items if o not in first and offering_key(o['name']) not in used]
        again = [o for o in items if o not in first and o not in unused]
        return [subject(o) for o in first + unused + again]
    if need == 'booking':
        if not booking:
            return []
        return [{'subject_key': None, 'subject': 'a time to book', 'landing_url': booking}] * PLAYS[play]['max_per_week']
    if need == 'new':
        offers = [{'subject_key': offering_key(o.get('name')), 'subject': o.get('name'), 'offering': o.get('name'),
                   'landing_url': booking if booking and o.get('bookable') else landing}
                  for o in signals.get('unmarketed_offerings') or [] if o.get('name')]
        news = [{'subject_key': news_key(n), 'subject': n['title'],
                 'landing_url': f"{site}news/{n['slug']}" if site and n.get('slug') else landing}
                for n in signals.get('unmarketed_news') or [] if n.get('title')]
        return offers + news
    page = {'come_back': booking or landing, 'meet_us': site or landing}.get(play, landing)
    return [{'subject_key': None, 'subject': None, 'landing_url': page}] * SUBJECTS_PER_PLAY


LEAD_REASON = {
    'offer_spotlight': 'Leads the week because one clear offering, shown well, is the shortest road to a booking.',
    'book_a_time': 'Leads the week because the calendar has room, and the booking page is one tap away.',
    'whats_new': 'Leads the week because something new went up and nobody has been told.',
    'useful_tip': 'Leads the week because useful posts are what get shared and found.',
    'meet_us': 'Leads the week because people choose a business they feel they know.',
    'come_back': 'Leads the week because people who have been before are the easiest to welcome back.',
}
SUPPORT_REASON = {
    'offer_spotlight': 'Shows one real offering, from the site, so people know what to book.',
    'book_a_time': 'Gives people who are ready a direct next step.',
    'whats_new': 'Shares what is new, so the week is not all asks.',
    'useful_tip': 'Useful on its own, so people who are not ready yet still get something.',
    'meet_us': 'Puts the business itself in front of people, which a name on a feed needs.',
    'come_back': 'Invites people who have been before to come back.',
}


def _reason(play: str, lead: str, signals: Dict[str, Any]) -> str:
    score = (signals.get('play_scores') or {}).get(play)
    proven = (f' Posts like this have done well through their own links ({score["samples"]} so far).'
              if score and score['samples'] >= platform.PROVEN else '')
    return (LEAD_REASON if play == lead else SUPPORT_REASON)[play] + proven


def pick_plays(problem: Any, n: int, signals: Dict[str, Any], profile: Dict[str, Any],
               facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Up to three plays and n slots, each with the reason it is there.

    problem: diagnose()'s result or its primary_problem. facts: verified_facts()
    (offerings to spotlight; none without them). The slots have no times yet:
    the week's posting times belong to the planner (B8/B9). Every slot's
    landing_url is the business's own page. Solutionist's own profile (B15)
    picks from the platform desk's library."""
    if (profile or {}).get('platform'):
        return platform_pick_plays(problem, n, signals, facts or {})
    problem_id = problem['primary_problem'] if isinstance(problem, dict) else str(problem)
    if problem_id not in PREFERENCE:
        raise ValueError(f'Unknown problem: {problem_id}')
    facts = facts or {}
    ranked = platform._rank([p for p in PREFERENCE[problem_id] if _subjects(p, signals, facts, profile)],
                            signals.get('play_scores') or {})
    if FILLER not in ranked:
        ranked.append(FILLER)              # needs nothing, so a week can always be filled
    ranked = ranked[:3]
    queues = {p: list(_subjects(p, signals, facts, profile)) for p in ranked}
    slots, counts = platform.fill_slots(ranked, queues, {p: PLAYS[p]['max_per_week'] for p in ranked}, max(0, int(n)))
    for i, slot in enumerate(slots):
        slot['slot'] = i + 1
        slot.setdefault('offering', None)
        slot['landing_url'] = slot.get('landing_url') or profile.get('landing_url')
    chosen = [p for p in ranked if counts[p]]
    return {'plays': [{'play_id': p, 'label': PLAYS[p]['label'], 'posts': counts[p],
                       'reason': _reason(p, ranked[0], signals)} for p in chosen],
            'slots': slots}


def library() -> Dict[str, Any]:
    return {'problems': PROBLEMS,
            'plays': {k: {'label': v['label'], 'solves': list(v['solves'])} for k, v in PLAYS.items()}}


# ── Solutionist's own (B15) ───────────────────────────────────────────
# The platform business on the suite keeps the platform desk's engine
# (marketing_engine): its problems, plays, facts and caption rules. Only its
# posting times and its store are the suite's.

FOUNDING = 'founding seat'        # a founder_invitation slot's offering: its price is the founding price


def platform_facts(signals: Dict[str, Any]) -> Dict[str, Any]:
    """marketing_engine.verified_facts: live pricing and trial settings, the
    founding-seat offer as billing reads it, the public pages' own claims
    and the news page. Reads the pages it quotes (no database)."""
    return platform.verified_facts(signals)


def platform_diagnose(s: Dict[str, Any]) -> Dict[str, Any]:
    return {**platform.diagnose(s), 'numbers': {}}


def merge_scores(*parts: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Play results from both stores (the Buffer desk's and the suite's),
    weighted by their samples."""
    total: Dict[str, List[float]] = {}
    for part in parts:
        for play, score in (part or {}).items():
            n = int((score or {}).get('samples') or 0)
            if n > 0 and isinstance(score.get('average'), (int, float)):
                acc = total.setdefault(play, [0, 0.0])
                acc[0] += n
                acc[1] += n * float(score['average'])
    return {play: {'samples': n, 'average': round(s / n, 2)} for play, (n, s) in total.items()}


def platform_pick_plays(problem: Any, n: int, signals: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """marketing_engine.pick_plays without its times (the planner owns them):
    up to three plays and n slots, each with its reason and its landing page
    on mysolutionist.app. The plays lean on what did well through the links
    of both desks once a play has three results."""
    diagnosis = problem if isinstance(problem, dict) else {'primary_problem': str(problem)}
    problem_id = diagnosis['primary_problem']
    if problem_id not in platform.PREFERENCE:
        raise ValueError(f'Unknown problem: {problem_id}')
    scores = merge_scores(signals.get('play_scores'), signals.get('buffer_play_scores'))
    sig = {**signals, 'play_scores': scores}
    ranked = platform._rank([p for p in platform.PREFERENCE[problem_id] if platform._subjects(p, sig, facts)], scores)
    if 'workflow_tip' not in ranked:
        ranked.append('workflow_tip')          # needs nothing, so a week can always be filled
    ranked = ranked[:3]
    queues = {p: list(platform._subjects(p, sig, facts)) for p in ranked}
    slots, counts = platform.fill_slots(ranked, queues, {p: platform.PLAYS[p]['max_per_week'] for p in ranked},
                                        max(0, int(n)))
    for i, slot in enumerate(slots):
        slot['slot'] = i + 1
        slot['offering'] = FOUNDING if slot['play_id'] == 'founder_invitation' else None
        slot['landing_url'] = (slot.get('landing_url') or platform.LANDING.get(slot['play_id'])
                               or 'https://mysolutionist.app/')
    plays = [{'play_id': p, 'label': platform.PLAYS[p]['label'], 'posts': counts[p],
              'reason': platform._reason(p, diagnosis, sig)} for p in ranked if counts[p]]
    return {'plays': plays, 'slots': slots}


def _founder_price(text: str, facts: Dict[str, Any], offering: Optional[str]) -> Optional[str]:
    return platform.price_problem(text, 'founder_invitation' if offering == FOUNDING else None, facts)


def platform_check_caption(text: str, facts: Dict[str, Any], offering: Optional[str] = None) -> Optional[str]:
    """The platform desk's caption rules: 20 to 220 characters, no address
    (the post adds its own link), no hashtag, every number from the facts,
    and a founding-seat post quotes only the founding price."""
    return (platform.check_caption(text, allowed_numbers(facts))
            or _founder_price(text or '', facts, offering))


def platform_check_flyer(copy: Any, facts: Dict[str, Any], offering: Optional[str] = None) -> Optional[str]:
    problem = platform.check_flyer(copy, allowed_numbers(facts))
    if problem:
        return problem
    return _founder_price(' '.join(str(v) for v in copy.values()), facts, offering)
