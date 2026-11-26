"""church_room_lookups.py — for every page on a church's menu, the Chief lookups that read it.

Kevin, 2026-11-22: "any person that we add in, it seems like Chief doesn't get
the information about the church". One reason was rooms Chief could not read
and did not know it could not: the treasurer asked what came in, and the
lookup that answers it was missing (fixed in BE #2072). Nothing caught it.

This is the list that catches the next one. Every page of a church's menu
(church_findway.json, the frontend's export) is in exactly one of:

    LOOKUPS ....... page -> the read actions that answer what is on it
    NO_LOOKUP ..... page -> why Chief can't read it yet (a gap, said plainly)
    NOT_A_ROOM .... page -> why it holds nothing to read (a help page, a builder)

__tests__/test_church_room_lookups.py fails when a page is in none of them
(a new room nobody decided about), when one is in two, or when a lookup named
here isn't one of Chief's read actions. So a new church room can't ship with
Chief silently unable to see it.

Chief is told the NO_LOOKUP rooms by name (church_facts), so that for one of
them it says what the page is and offers to open it, instead of guessing
what is on it. That line is the only thing here a turn reads.

A lookup is listed only where its own description says it reads that room.
Several rooms are read in part (Members by church_people's first-time guests
and drift, not each record): what is listed is what Chief can say, not that
it sees everything on the page.
"""
from __future__ import annotations

from typing import Dict, Tuple

LOOKUPS: Dict[str, Tuple[str, ...]] = {
    # Home
    "operate:move-in": ("move_in_status",),
    "operate:my-week": ("my_work",),
    "operate:team": ("team_week",),
    "operate:dashboard": ("catch_up",),
    "operate:overview": ("catch_up",),
    "operate:reports": ("monthly_report_draft", "growth_report"),
    "grow:briefing": ("catch_up",),
    # Sunday
    "operate:sunday-home": ("serving_week", "giving_counts"),
    "operate:serve-schedule": ("serving_week",),
    "operate:@roster": ("event_volunteers",),
    "operate:serve-teams": ("serving_week",),
    "operate:attendance": ("church_people",),
    "operate:volunteer-week": ("serving_week",),
    "operate:volunteer-teams": ("serving_week",),
    "operate:volunteer-schedule": ("serving_week",),
    "operate:serving": ("serving_week",),
    # People
    "operate:contacts": ("church_people", "contact_deep_dive"),
    "operate:directory": ("church_people",),
    "operate:groups": ("church_people",),
    "build:course-studio": ("inspect_course",),
    "grow:funnel": ("church_people",),
    "operate:care": ("church_people",),
    "grow:retention": ("church_people",),
    "build:intake-forms": ("list_client_forms",),
    "operate:leaders": ("list_map",),
    "operate:leaders-dates": ("who_is_away", "check_dates", "time_off_asks"),
    # Giving
    "operate:bookkeeping": ("giving_summary", "giving_counts", "giving_deposits"),
    "operate:payments": ("show_revenue", "giving_summary"),
    "operate:statements": ("giving_statements_run", "giving_statement"),
    "grow:intelligence": ("giving_summary",),
    "operate:offerings-manager": ("list_offerings", "list_products", "check_inventory"),
    "operate:giving-page": ("fund_status",),
    # Messages
    "operate:email": ("email_setup_status", "church_email"),
    "operate:sms": ("sms_status",),
    "build:email-setup": ("email_setup_status",),
    # Office
    "operate:tasks": ("list_tasks",),
    "operate:projects": ("list_projects",),
    "operate:invoices": ("bills",),
    "operate:inventory": ("check_inventory",),
    "operate:monthly-report": ("monthly_report_draft",),
    "grow:goals": ("check_goals",),
    "build:custom-modules": ("list_module_entries", "summarize_module"),
    # Media (Video studio and Video Clips are tabs of Create: church_findway.TAKEN_BY)
    "build:media-library": ("find_images",),
    # Reach
    "grow:marketing": ("marketing_desk",),
    "grow:create": ("marketing_desk",),
    "build:social-media": ("marketing_desk",),
    "grow:campaigns": ("campaign_status",),
    "grow:getfound": ("site_health",),
    # Web
    "build:my-site": ("site_health", "view_website"),
    "build:website-concierge": ("site_health",),
    "build:booking-share": ("list_availability",),
    # Settings
    "operate:areas": ("sheet_of", "list_church_jobs", "church_structure_status"),
    "build:about-your-business": ("recall_business_knowledge",),
    "operate:history": ("search_ledger",),
}

# Rooms with records Chief can't read yet. Each is a gap, not a decision: a
# lookup for one moves it to LOOKUPS. The words are the room's, for the line
# Chief reads.
NO_LOOKUP: Dict[str, str] = {
    "operate:serve-order": "the order of service",
    "operate:kids": "this week's kids check-in",
    "operate:worship-announcements": "the announcements",
    "build:print-materials": "bulletins and print",
    "operate:sundays": "past Sundays",
    "operate:stations": "the check-in stations",
    "operate:worship-media": "screen pictures and videos",
    "operate:worship-setup": "worship setup",
    "operate:families": "families",
    "operate:follow-up": "the follow-up board",
    "operate:help": "help requests",
    "operate:shepherding": "shepherding",
    "build:next-steps": "next steps",
    "operate:recurring-gifts": "recurring gifts",
    "operate:pledges": "pledges and campaigns",
    "operate:grants": "grants",
    "operate:pay-staff": "staff pay",
    "operate:contractors": "contractors",
    "operate:money-controls": "money controls",
    "operate:queue": "the approvals waiting",
    "operate:messaging": "member messaging",
    "operate:news": "news and celebrations",
    "build:email-templates": "email templates",
    "operate:notifications": "notifications",
    "operate:calendar": "the calendar",
    "operate:documents": "files and policies",
    "operate:spaces": "rooms and their bookings",
    "operate:rentals": "rentals",
    "operate:checks": "check requests",
    "operate:register": "the church records (baptisms, weddings, funerals)",
    "operate:board": "the board and its minutes",
    "operate:leaders-note": "the leaders note",
    "grow:notes": "the notes pad",
    "grow:ideas": "ideas",
    "grow:timeline": "the timeline",
    "operate:outcomes": "program results",
    "grow:sermons": "sermons",
    "grow:live": "live services",
    "build:devotionals": "devotionals",
    "build:reading-plan": "the Bible reading plan",
    "grow:reviews": "testimonies",
    "build:link-page": "the links page",
    "build:brand": "the brand",
    "build:member-app": "the member app",
    "build:events-page": "the events page",
    "build:integrations": "integrations",
    "operate:agents": "autopilot",
}

# Pages that hold no church records of their own.
NOT_A_ROOM: Dict[str, str] = {
    "build:module-builder": "where a new tracker is made",
    "build:settings": "the settings list",
    "operate:help-center": "the Help Center's answers (church_findway hands Chief the matching one)",
    "build:strategy-track": "the planning course",
    "build:structure-import": "where a file is brought over",
    "build:resources": "reading for church leaders",
}


def menu_pages() -> Dict[str, str]:
    """Every page on a church's menu: key -> its name, as church_findway shows it."""
    import church_findway
    out: Dict[str, str] = {}
    for door in church_findway._map().get("doors") or []:
        for group in door.get("groups") or []:
            for p in group.get("pages") or []:
                if p.get("key") and p.get("key") not in church_findway.NOT_ON_THE_MENU:
                    out[p["key"]] = str(p.get("name") or p["key"])
    return out


def cant_read_line() -> str:
    """The rooms Chief can't read, in one line for the fact sheet; '' when none."""
    pages = menu_pages()
    names = [pages[k] for k in NO_LOOKUP if k in pages]
    if not names:
        return ""
    return ("Rooms you can't read yet (" + str(len(names)) + "): " + ", ".join(names) + ". Asked about one, use only "
            "what this prompt already shows you of it; past that, say what the room is for and offer to open it. Never "
            "guess what is in it, and never say it is empty.")
