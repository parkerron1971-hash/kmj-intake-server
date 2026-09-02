"""room_orientation.py — what every room is for, so Chief can say it first.

Kevin, 2 September 2026: "Chief is reactive when she needs to be proactive.
The person lands, and nobody's telling them what this room is or what to
do in it." Until now Chief knew only a route string ("OPERATE → contacts")
and would explain any room if asked; nobody new knows to ask.

This module is the map behind three things the app now sends:

  [SYSTEM:room_first_visit]   the first time a practitioner opens a room:
                              ONE line — what it is for them, the one thing
                              to do here. Shown in a strip on the page.
  [SYSTEM:room_orientation]   the "What is this room?" door, anywhere, on
                              day one or day ninety: three things, in
                              their words — what this room does for a
                              business like theirs, what is in it right
                              now (real numbers), the one next thing —
                              and an offer to do it together.
  [SYSTEM:guided_walk]        Chief walks them room by room, one per turn,
                              in her own voice, navigating as she goes.

Every entry is written from the practitioner's side of the screen and in
generic nouns; Chief translates into the vertical's words (regulars,
members, donors, matters) the way the rest of the prompt already asks it
to. `next_rule` names what "the one next thing" usually is here; the live
answer comes from BUSINESS STATE and SETUP STATUS, which are already in
the prompt on every turn.

Keys are the app's route keys: the four tabs, OPERATE subs, GROW subs and
BUILD pages, exactly as SolutionistLayout / SolutionistSidebar name them.
Unknown routes fall back to the tab, and an unknown tab to a generic line,
so the door always opens.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# The prompt sentinels. The frontend sends these as HIDDEN user turns
# (never shown in the transcript), the same convention as
# [SYSTEM:opening_greeting].
FIRST_VISIT_SENTINEL = "[SYSTEM:room_first_visit]"
ORIENTATION_SENTINEL = "[SYSTEM:room_orientation]"
GUIDED_WALK_SENTINEL = "[SYSTEM:guided_walk]"
SENTINELS = (FIRST_VISIT_SENTINEL, ORIENTATION_SENTINEL, GUIDED_WALK_SENTINEL)

# The walk's order: the rooms a new practitioner meets, one per turn.
WALK_ORDER = ["home", "operate", "grow", "build"]

TABS: Dict[str, Dict[str, str]] = {
    "home": {
        "label": "Home",
        "purpose": "The one page that says how the business is doing today and what needs them next: "
                   "the numbers that matter, what Chief is waiting on, and (in the first weeks) the next thing to plug in.",
        "next_rule": "Whatever the setup card names as the next move; once setup is done, whatever Chief flagged for today.",
    },
    "operate": {
        "label": "Operate",
        "purpose": "Where the day's work happens: the people they serve, the calendar, approvals, messages, "
                   "invoices and payments, the books, and the tools built for their trade.",
        "next_rule": "Bring their people in if the contact list is empty; otherwise whatever is waiting for approval or overdue.",
    },
    "grow": {
        "label": "Grow",
        "purpose": "Where the business gets bigger: the briefing, revenue, who is drifting away, reviews, "
                   "content and campaigns, goals, and how new people find them.",
        "next_rule": "Read the briefing first; set one goal with a number; then turn on how strangers find them.",
    },
    "build": {
        "label": "Build",
        "purpose": "Where the business's public face and its tools get made: the site, brand, booking, "
                   "client forms, custom solutions, integrations, and the sit-down with Chief.",
        "next_rule": "Whatever the setup card names; usually the site or the booking page, once what they sell is in.",
    },
}

ROOMS: Dict[str, Dict[str, str]] = {
    # ── OPERATE ────────────────────────────────────────────────────────
    "operate/dashboard": {"label": "Today",
        "purpose": "The working deck for today: what needs them, in the order it matters.",
        "next_rule": "Clear whatever is at the top of the deck; if it is empty, that is good news, say so."},
    "operate/contacts": {"label": "Contacts",
        "purpose": "Everyone they serve or might: history, notes, messages and money for each person, in one place.",
        "next_rule": "If it is empty, bring their list over (Bring a file over, or one name at a time). If not, the person Chief flagged as drifting."},
    "operate/sessions": {"label": "Sessions",
        "purpose": "Every appointment or session, past and upcoming, with notes and follow-ups.",
        "next_rule": "Book or log the next one; confirm today's."},
    "operate/queue": {"label": "Approvals",
        "purpose": "Everything Chief drafted on their behalf and is waiting for a yes: emails, texts, posts, replies.",
        "next_rule": "Approve or edit what is waiting; nothing here sends without them."},
    "operate/email": {"label": "Email",
        "purpose": "Their business inbox, connected here so Chief can read, sort and draft replies.",
        "next_rule": "Connect the mailbox if it is not; otherwise reply to what Chief flagged."},
    "operate/sms": {"label": "Text",
        "purpose": "Text conversations with the people they serve, confirmations and reminders included.",
        "next_rule": "Reply to anything unread; turn on reminders once hours are set."},
    "operate/calendar": {"label": "Calendar",
        "purpose": "Their schedule: bookings, sessions, blocked time, and what the booking page offers.",
        "next_rule": "Set the hours they actually work so the booking page offers the right times."},
    "operate/tasks": {"label": "Tasks",
        "purpose": "Their to-do list, including what Chief has taken on and what is waiting on them.",
        "next_rule": "Close the oldest open one, or hand one to Chief."},
    "operate/projects": {"label": "Projects",
        "purpose": "Longer pieces of work with stages, deliverables and dates.",
        "next_rule": "Open one for the biggest thing in flight."},
    "operate/invoices": {"label": "Invoices",
        "purpose": "Everything they have billed and what is still owed; Chief chases what is overdue.",
        "next_rule": "Send the first invoice, or connect how they get paid so invoices turn into money."},
    "operate/payments": {"label": "Payments",
        "purpose": "How money comes in: the processors connected, payment links, what has landed.",
        "next_rule": "Connect a way to get paid if none is; otherwise check what landed this week."},
    "operate/bookkeeping": {"label": "Bookkeeping",
        "purpose": "The books, kept as money moves: categorised transactions, what is unmatched, what the accountant needs.",
        "next_rule": "Link the bank; then clear the unmatched pile Chief proposes categories for."},
    "operate/documents": {"label": "Documents",
        "purpose": "Contracts, agreements and templates for their trade, sent for signature from here.",
        "next_rule": "Send the agreement their next client should sign."},
    "operate/offerings-manager": {"label": "Services & Products",
        "purpose": "What they sell, with prices and durations; it drives booking, invoices, the site and every quote Chief writes.",
        "next_rule": "Add the one thing people come to them for most, with the real price."},
    "operate/inventory": {"label": "Inventory",
        "purpose": "What they have in stock and what is running low.",
        "next_rule": "Count what they have; set the reorder point on what runs out."},
    "operate/agents": {"label": "Autopilot",
        "purpose": "The recurring work Chief does for them on a schedule: the weekly briefing, follow-ups, reminders.",
        "next_rule": "Nothing to do here on day one; the vertical's default is already queued."},
    "operate/history": {"label": "History",
        "purpose": "Every action taken in the business, by whom and to whom.",
        "next_rule": "Nothing to do; it is the record."},
    "operate/notifications": {"label": "Notifications",
        "purpose": "What Chief wants them to know, in one list.",
        "next_rule": "Read and clear."},
    "operate/grants": {"label": "Find a Grant",
        "purpose": "Grants their kind of organisation can apply for, with deadlines.",
        "next_rule": "Shortlist one; Chief drafts the first pass."},
    "operate/trust": {"label": "Client Trust",
        "purpose": "Client funds held in trust, tracked separately from the operating account, as the bar requires.",
        "next_rule": "Record the first retainer against its matter."},
    # ── GROW ───────────────────────────────────────────────────────────
    "grow/dashboard": {"label": "Overview",
        "purpose": "The growth picture at a glance: revenue trend, who is drifting, what is working.",
        "next_rule": "Read the briefing; pick one number to move this month."},
    "grow/briefing": {"label": "Briefing",
        "purpose": "Chief's read on the business, written for them, refreshed as things change.",
        "next_rule": "Read it; act on the first item."},
    "grow/revenue": {"label": "Revenue",
        "purpose": "Money over time: by month, by what they sell, by who pays.",
        "next_rule": "Once invoices flow, come back here weekly."},
    "grow/retention": {"label": "Retention",
        "purpose": "Who is drifting away and who is due to hear from them.",
        "next_rule": "Reach out to the first person on the list; Chief can draft it."},
    "grow/reviews": {"label": "Reviews",
        "purpose": "Asking happy clients for reviews, and what came back.",
        "next_rule": "Send the first review request after a good session."},
    "grow/getfound": {"label": "Get Found",
        "purpose": "How strangers find them: search, their Google listing, the basics that make them show up.",
        "next_rule": "Claim the Google Business Profile."},
    "grow/googleprofile": {"label": "Google Profile",
        "purpose": "Their Google Business listing, managed from here.",
        "next_rule": "Connect it; keep hours and photos current."},
    "grow/ideas": {"label": "Ideas",
        "purpose": "The board of ideas and the bigger picture they are building toward.",
        "next_rule": "Pin the one idea they keep coming back to."},
    "grow/goals": {"label": "Goals",
        "purpose": "Goals with real numbers, tracked against what actually happens.",
        "next_rule": "Set one goal with a number and a month."},
    "grow/content": {"label": "Content Plan",
        "purpose": "What to say and when: posts, emails and topics planned ahead.",
        "next_rule": "Approve the first week Chief drafted."},
    "grow/campaigns": {"label": "Campaigns",
        "purpose": "Emails and texts sent to many people at once, with results.",
        "next_rule": "Send the first one to their existing people, not strangers."},
    "grow/funnel": {"label": "Lead Flow",
        "purpose": "How new people move from first contact to paying.",
        "next_rule": "Bring the leads in first; the flow shows once there are some."},
    "grow/timeline": {"label": "Timeline",
        "purpose": "The story of the business over time, milestones included.",
        "next_rule": "Nothing to do; it writes itself."},
    "grow/notes": {"label": "Notes",
        "purpose": "Everything they told Chief to remember, and notes they typed themselves.",
        "next_rule": "Nothing to do; ask Chief to file a note any time."},
    # ── BUILD ──────────────────────────────────────────────────────────
    "build/my-site": {"label": "My Site",
        "purpose": "Their website, built from what they told Chief and kept current as the business changes.",
        "next_rule": "Put it up once what they sell is in; then send the link to one person."},
    "build/booking": {"label": "Booking",
        "purpose": "The hours they work and how people book them.",
        "next_rule": "Set the days and hours they actually work."},
    "build/booking-share": {"label": "Booking Link",
        "purpose": "The link people use to book them, ready to text or post.",
        "next_rule": "Send it to one regular tonight."},
    "build/brand": {"label": "Brand Studio",
        "purpose": "Colors, type and logo; everything the system makes inherits them.",
        "next_rule": "Pick the colors; the rest follows."},
    "build/media-library": {"label": "Media Library",
        "purpose": "Photos and files the site, posts and print pull from.",
        "next_rule": "Upload four to six photos of the work if theirs is a business people choose by eye."},
    "build/print-materials": {"label": "Print Materials",
        "purpose": "Flyers, cards and signs in their brand, ready to print.",
        "next_rule": "Make the one piece they hand out most."},
    "build/link-page": {"label": "My Links",
        "purpose": "One link that holds all their links, for bios and texts.",
        "next_rule": "Put the booking link and the site on it."},
    "build/intake-forms": {"label": "Client Forms",
        "purpose": "The forms new clients fill out before or at the first visit.",
        "next_rule": "Send the intake form to the next new client."},
    "build/custom-modules": {"label": "Custom Solutions",
        "purpose": "The tools built for their trade: trackers, registries, boards, logs. Chief builds new ones on request.",
        "next_rule": "Ask Chief for the one tracker they keep in a notebook."},
    "build/module-builder": {"label": "Build a Solution",
        "purpose": "Where a new custom tool gets made, with Chief.",
        "next_rule": "Describe the thing they track by hand."},
    "build/structure-import": {"label": "Bring a file over",
        "purpose": "Their spreadsheets, read by shape: people become contacts, everything else becomes a solution built to their columns.",
        "next_rule": "Drop in the file they already keep."},
    "build/social-media": {"label": "Social Media",
        "purpose": "Posts drafted, scheduled and published to their accounts.",
        "next_rule": "Connect Facebook and Instagram; approve the first post."},
    "build/email-templates": {"label": "Email Templates",
        "purpose": "The emails Chief sends on their behalf, in their voice.",
        "next_rule": "Read one; change a line if it does not sound like them."},
    "build/resources": {"label": "Resources",
        "purpose": "Guides and downloads for their trade.",
        "next_rule": "Nothing to do on day one."},
    "build/integrations": {"label": "Integrations",
        "purpose": "The connections: how they get paid, the bank, QuickBooks, their email domain, Facebook and Instagram.",
        "next_rule": "Connect how they get paid first."},
    "build/settings": {"label": "Settings",
        "purpose": "The business's details, terminology, notifications, billing and the website concierge.",
        "next_rule": "Check the timezone; set what they call their people."},
    "build/business-profile": {"label": "About My Business",
        "purpose": "The facts contracts and policies are written from: entity, state, how they deliver.",
        "next_rule": "Fill what Chief asks for when it needs it; not a day-one chore."},
    "build/about-me": {"label": "About Me",
        "purpose": "Who they are, as it appears on documents and the site.",
        "next_rule": "Name and title; the rest later."},
    "build/foundation-track": {"label": "Legal & Tax Setup",
        "purpose": "The legal and tax basics for their kind of business, walked step by step.",
        "next_rule": "Only if they have not formed the business yet."},
    "build/business-track": {"label": "Business Track",
        "purpose": "The twenty-minute sit-down where Chief learns how they actually run: what they sell, who they serve, how money moves.",
        "next_rule": "Do it when they have twenty minutes; it picks up where they left off."},
    "build/strategy-track": {"label": "The Academy",
        "purpose": "For an idea that is not a business yet: model, market, price, launch plan, with Chief.",
        "next_rule": "Continue where they left off."},
    "build/course-studio": {"label": "Course Studio",
        "purpose": "Building a course: lessons, materials, enrollment.",
        "next_rule": "Outline the first lesson."},
    "build/products": {"label": "Products",
        "purpose": "Physical or digital things they sell, for the store.",
        "next_rule": "Add the first three products."},
    "build/analytics": {"label": "Site Analytics",
        "purpose": "Who visits the site and what they do there.",
        "next_rule": "Nothing until the site is up."},
}


def room_key(tab: Optional[str], sub: Optional[str] = None, page: Optional[str] = None) -> str:
    """The route key for a view: 'operate/contacts', 'build/my-site', or the bare tab."""
    t = (tab or "").strip().lower()
    if t in ("command_center", "my_dashboard", "mission_control"):
        t = "home"
    leaf = (page if t == "build" else sub) or ""
    leaf = str(leaf).strip().lower()
    if leaf.startswith("module:"):
        return f"{t}/module"
    return f"{t}/{leaf}" if leaf else t


def describe(tab: Optional[str], sub: Optional[str] = None, page: Optional[str] = None) -> Dict[str, Any]:
    """The orientation entry for a view. Always returns one: the leaf if
    known, else the tab, else a generic line. `known` says which."""
    key = room_key(tab, sub, page)
    if key in ROOMS:
        return {"key": key, "known": True, **ROOMS[key]}
    t = key.split("/")[0]
    if key.endswith("/module"):
        return {"key": key, "known": True, "label": "a custom solution",
                "purpose": "One of the tools built for their trade; the entries in it are theirs.",
                "next_rule": "Add the first entry, or ask Chief to."}
    if t in TABS:
        return {"key": key, "known": False, **TABS[t]}
    return {"key": key or "unknown", "known": False, "label": "this page",
            "purpose": "A part of their system.",
            "next_rule": "Whatever the setup card names next."}


def orientation_block(tab: Optional[str], sub: Optional[str] = None, page: Optional[str] = None) -> str:
    """The lines appended to CURRENTLY VIEWING on every turn: what this
    room is for and what the next thing usually is. Short — it ships
    with every request that carries a view."""
    d = describe(tab, sub, page)
    return "\n".join([
        f"THIS ROOM: {d['label']} — {d['purpose']}",
        f"  The one next thing here is usually: {d['next_rule']}",
        "  If they ask what this is or what to do here, answer from this and the live numbers "
        "above, in their vertical's words, then offer to do the next thing with them.",
    ])


def sentinel_kind(message: str) -> Optional[str]:
    """'first_visit' | 'orientation' | 'walk' | None."""
    s = (message or "").strip()
    if s.startswith(FIRST_VISIT_SENTINEL):
        return "first_visit"
    if s.startswith(ORIENTATION_SENTINEL):
        return "orientation"
    if s.startswith(GUIDED_WALK_SENTINEL):
        return "walk"
    return None


def mode_clause(kind: Optional[str], tab: Optional[str] = None, sub: Optional[str] = None,
                page: Optional[str] = None) -> str:
    """What replaces the day-read when the turn is one of the three
    orientation sentinels. Empty for a normal turn."""
    if not kind:
        return ""
    d = describe(tab, sub, page)
    if kind == "first_visit":
        return f"""

FIRST VISIT TO A ROOM — they just opened {d['label']} for the first time. Say ONE sentence, two at most: what this room is for a business like theirs, and the one thing to do here (see THIS ROOM). Their vertical's words, not the system's. No greeting, no day-read, no list, no actions. Warm and brief; it appears as a strip at the top of the page."""
    if kind == "orientation":
        return f"""

WHAT IS THIS ROOM — they tapped the door on {d['label']} and asked what it is and what to do here. Answer three things, in that order, four sentences at most, in their vertical's words:
1. What this room does for a business like theirs (THIS ROOM above).
2. What is in it RIGHT NOW — real numbers from BUSINESS STATE and SETUP STATUS ("you have 12 regulars in here, none booked this week"), never a description of what could be here.
3. The one next thing (THIS ROOM's next rule, made specific by their data), and offer to do it with them now.
No greeting, no day-read. No actions in this turn; on their yes, the next turn does it."""
    if kind == "walk":
        return f"""

GUIDED WALK — they asked to be shown around. Walk them through their rooms ONE PER TURN in this order: Home, Operate, Grow, Build. This turn: the first room not yet described in this conversation (start at Home if none). For that room say, in their vertical's words: what it is for a business like theirs, what is in it right now (real numbers from BUSINESS STATE; on day one that may be "nothing yet, and here is what will fill it"), and the one thing to do there this week. Emit exactly ONE navigate to that room so they see it while you talk: [ACTION:{{"type":"navigate","tab":"<room>"}}]. End with "Next room?" — or, after Build, close by naming the sendable thing from SETUP STATUS as where all of this is going, and ask which room they want to start in. Four to five sentences per room. Never describe two rooms in one turn."""
    return ""
