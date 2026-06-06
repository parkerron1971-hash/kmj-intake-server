"""
vertical_intelligence.py — Phase VABI v1.

Single source of truth for "what does the system know about each
vertical." Drives:

  - Chief reply tone + vocabulary (via vertical_context.py)
  - Email voice (booking_confirmation_emails, future invoice/reminder paths)
  - Onboarding question library (BusinessProfileReview)
  - Offering creation defaults (frontend mirror)
  - Invoice line item templates (frontend mirror)
  - Empty-state vertical nudges
  - Chief proactive module-suggestion intelligence

Storage choice: Python module (not DB table) — matches the
vertical_terminology.py pattern from C.1.4 v1. Reasons:
  - Authoring + version control via Git, not Supabase Studio
  - Zero migration risk; no row-write coupling
  - Engineering iterations are small + frequent in v1
  - DB normalization comes in VABI v2 if/when practitioner overrides land

Frontend mirror (subset needed by forms): solutionist-studio/src/core/
intelligence/vertical_intelligence.ts. Kept in lockstep manually for
v1; v1.5 plan moves to shared JSON.

The keys here mirror the business_type_archetypes seed (coach,
consultant, course_creator, creative, custom, financial_educator,
fitness_wellness, lawyer, ministry, personal_services, service_provider).
Unmapped verticals (agency, ecommerce, none) fall back to GENERIC.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ─── Core knowledge unit per vertical ────────────────────────────────


class VerticalProfile(Dict[str, Any]):
    """Structural dict alias for type-hint clarity. Always shaped:
        {
          voice: { register, formality, hallmarks, taboo },
          onboarding_questions: [{ id, prompt, kind, options? }, ...],
          offering_suggestions: [{ name, price, duration_min, description }, ...],
          invoice_line_templates: [{ description, kind, hint? }, ...],
          email_voice: { booking_confirmation: {greeting, body_hints, sign_off} },
          empty_state_nudges: { bookings, customers, invoices, offerings },
          module_suggestions: [{ slug, archetype, headline }, ...],
        }
    """
    pass


# Generic fallback — every unmapped vertical resolves here.
GENERIC: VerticalProfile = VerticalProfile({
    "voice": {
        "register": "professional but warm",
        "formality": "balanced",
        "hallmarks": ["clear", "outcome-focused", "no jargon"],
        "taboo": [],
    },
    "onboarding_questions": [
        {"id": "service_model", "prompt": "How do you typically work with customers — one-on-one, in groups, or projects?", "kind": "select",
         "options": ["one_on_one", "group_program", "project", "mixed"]},
        {"id": "engagement_length", "prompt": "How long is a typical engagement?", "kind": "select",
         "options": ["single_session", "weeks", "package_3_12_months", "ongoing_retainer"]},
        {"id": "pricing_model", "prompt": "How do you price your work?", "kind": "multiselect",
         "options": ["hourly", "flat_fee", "package", "retainer"]},
    ],
    "offering_suggestions": [
        {"name": "Discovery Call", "price": 0, "duration_min": 30,
         "description": "Free introductory call so customers can see if you're a fit."},
        {"name": "Standard Service", "price": 100, "duration_min": 60,
         "description": "Your core paid service."},
    ],
    "invoice_line_templates": [
        {"description": "Service rendered", "kind": "flat"},
        {"description": "Materials / expenses", "kind": "flat"},
    ],
    "email_voice": {
        "booking_confirmation": {
            "tone_note": "Friendly + clear. Confirm the time, give one prep nudge if relevant.",
        },
    },
    "empty_state_nudges": {
        "bookings": "No bookings yet. Share your booking link or create your first offering to start.",
        "customers": "No customers yet. They'll appear here as people book or pay.",
        "invoices": "No invoices yet. Create your first invoice to start getting paid.",
        "offerings": "No offerings yet. Add a service or package so customers can pick one when they book.",
    },
    "module_suggestions": [
        {"slug": "bookings", "archetype": "booking_calendar", "headline": "Start with a Booking Calendar."},
    ],
})


# ─── Per-vertical profiles ───────────────────────────────────────────


VERTICAL_INTELLIGENCE: Dict[str, VerticalProfile] = {
    "lawyer": VerticalProfile({
        "voice": {
            "register": "precise, professional, jurisdiction-aware",
            "formality": "formal",
            "hallmarks": [
                "uses 'Client' and 'Matter' consistently",
                "mentions conflict checks + privilege when relevant",
                "treats deadlines as binding, not flexible",
                "avoids speculation on legal outcomes",
            ],
            "taboo": [
                "casual emoji",
                "treating Stripe like a trust account (IOLTA is separate)",
                "promising results",
            ],
        },
        "onboarding_questions": [
            {"id": "practice_areas", "prompt": "What practice areas do you focus on?", "kind": "text"},
            {"id": "firm_size", "prompt": "Are you solo or part of a firm?", "kind": "select",
             "options": ["solo", "small_firm", "mid_firm", "large_firm"]},
            {"id": "pricing_model", "prompt": "How do you bill clients?", "kind": "multiselect",
             "options": ["hourly", "flat_fee", "retainer", "contingency", "hybrid"]},
            {"id": "trust_account", "prompt": "Do you hold trust funds (IOLTA / client deposits)?", "kind": "boolean"},
            {"id": "conflict_check_workflow", "prompt": "Do you run conflict checks before engagement?", "kind": "boolean"},
        ],
        "offering_suggestions": [
            {"name": "Initial Consultation", "price": 250, "duration_min": 60,
             "description": "First meeting to scope the matter and discuss representation."},
            {"name": "Document Review", "price": 500, "duration_min": 90,
             "description": "Flat-fee review of contracts, agreements, or filings."},
            {"name": "Hourly Legal Work", "price": 350, "duration_min": 60,
             "description": "Hourly rate for ongoing matter work — billed against retainer or invoice."},
            {"name": "Retainer Agreement", "price": 5000, "duration_min": 0,
             "description": "Upfront retainer deposit — drawn down against billable hours."},
        ],
        "invoice_line_templates": [
            {"description": "Legal services (hourly)", "kind": "hourly", "hint": "rate × hours"},
            {"description": "Court filing fees", "kind": "flat"},
            {"description": "Document preparation (flat)", "kind": "flat"},
            {"description": "Trust deposit", "kind": "flat", "hint": "Apply against IOLTA; do not deposit into operating account."},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Formal. Confirm the matter (in general terms — privilege-aware). Remind the client to bring relevant documents. Note confidentiality.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No consultations scheduled. Want to set up your conflict check workflow before taking your first client?",
            "customers": "No clients yet. They'll appear here once you've taken your first matter.",
            "invoices": "No bills sent yet. Set your hourly rate and retainer terms first.",
            "offerings": "No services defined yet. Common: Initial Consultation, hourly work, and flat-fee document review.",
        },
        "module_suggestions": [
            {"slug": "consultations", "archetype": "booking_calendar",
             "headline": "Set up a Consultation calendar so prospective clients can book with conflict-check time built in."},
            {"slug": "intake-form", "archetype": "fallback_generic",
             "headline": "Build an intake form to capture matter type + parties involved before each consultation."},
            {"slug": "matter-tracker", "archetype": "fallback_generic",
             "headline": "Track active matters with status, deadlines, and trust account balances."},
        ],
    }),
    "coach": VerticalProfile({
        "voice": {
            "register": "warm, framework-aware, outcome-focused",
            "formality": "balanced + personal",
            "hallmarks": [
                "uses 'Client' and 'Session' consistently",
                "references session outcomes + frameworks",
                "celebrates wins; reflects on stuck points",
                "treats confidentiality as central",
            ],
            "taboo": ["clinical/medical claims", "promising specific results"],
        },
        "onboarding_questions": [
            {"id": "coaching_framework", "prompt": "What coaching framework or modality do you use?", "kind": "text"},
            {"id": "format", "prompt": "1:1 only, group programs, or both?", "kind": "select",
             "options": ["one_on_one", "group_program", "both"]},
            {"id": "session_length", "prompt": "Typical session length?", "kind": "select",
             "options": ["30min", "60min", "90min"]},
            {"id": "package_length", "prompt": "Do you sell single sessions, packages, or both?", "kind": "select",
             "options": ["single", "packages", "both"]},
        ],
        "offering_suggestions": [
            {"name": "Discovery Call", "price": 0, "duration_min": 30,
             "description": "Free intro call so clients can see if your coaching style is a fit."},
            {"name": "1:1 Coaching Session", "price": 200, "duration_min": 60,
             "description": "Single session — drop in when you need it."},
            {"name": "3-Month Coaching Package", "price": 1800, "duration_min": 60,
             "description": "Six biweekly sessions + email support between."},
        ],
        "invoice_line_templates": [
            {"description": "Coaching session — 1hr", "kind": "flat"},
            {"description": "Coaching package — 6 sessions", "kind": "flat"},
            {"description": "Initial assessment fee", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Warm and personal. Confirm time. Invite them to bring a goal or intention to the session. Mention any prep materials.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No sessions scheduled. Want to set up your intake assessment template first?",
            "customers": "No clients yet. They'll appear here as people book sessions.",
            "invoices": "No invoices sent yet. Set up your session and package prices first.",
            "offerings": "No offerings yet. Common: Discovery Call + 1:1 Session + a multi-session Package.",
        },
        "module_suggestions": [
            {"slug": "discovery-calls", "archetype": "booking_calendar",
             "headline": "Start with a Discovery Call so prospective clients can sample your style for free."},
            {"slug": "session-notes", "archetype": "fallback_generic",
             "headline": "Track session notes per client — capture themes, breakthroughs, and homework."},
        ],
    }),
    "consultant": VerticalProfile({
        "voice": {
            "register": "professional, strategic, results-oriented",
            "formality": "formal",
            "hallmarks": [
                "uses 'Client' and 'Engagement'",
                "references deliverables, scope, milestones",
                "respects the client's time + senior position",
            ],
            "taboo": ["overselling outcomes", "filler"],
        },
        "onboarding_questions": [
            {"id": "engagement_model", "prompt": "Project-based, retainer, or hybrid?", "kind": "select",
             "options": ["project", "retainer", "hybrid"]},
            {"id": "industry_focus", "prompt": "Which industries do you serve?", "kind": "text"},
            {"id": "engagement_length", "prompt": "Typical engagement length?", "kind": "select",
             "options": ["weeks", "1-3_months", "3-12_months", "ongoing"]},
            {"id": "deliverables", "prompt": "What deliverables do you typically produce?", "kind": "text"},
        ],
        "offering_suggestions": [
            {"name": "Discovery Call", "price": 0, "duration_min": 30,
             "description": "Free scoping conversation to align on the problem and the engagement shape."},
            {"name": "Strategy Workshop", "price": 2500, "duration_min": 240,
             "description": "Half-day workshop — outputs a decision document or roadmap."},
            {"name": "Monthly Retainer", "price": 5000, "duration_min": 0,
             "description": "Recurring monthly retainer for ongoing advisory work."},
        ],
        "invoice_line_templates": [
            {"description": "Consulting hours", "kind": "hourly", "hint": "rate × hours"},
            {"description": "Project milestone payment", "kind": "flat"},
            {"description": "Monthly retainer", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Professional. Confirm time + agenda. Note any pre-read materials.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No meetings scheduled. Want to set up your discovery call template first?",
            "customers": "No clients yet. They'll appear here as engagements start.",
            "invoices": "No invoices yet. Define your retainer and project rates first.",
            "offerings": "No offerings yet. Common: Discovery Call + Strategy Workshop + a monthly retainer.",
        },
        "module_suggestions": [
            {"slug": "discovery-calls", "archetype": "booking_calendar",
             "headline": "Start with a Discovery Call calendar so prospects can scope engagements with you."},
            {"slug": "project-tracker", "archetype": "fallback_generic",
             "headline": "Track active engagements with milestones, deliverables, and retainer balances."},
        ],
    }),
    "course_creator": VerticalProfile({
        "voice": {
            "register": "encouraging, instructional, clear",
            "formality": "balanced",
            "hallmarks": [
                "uses 'Student' and 'Course' / 'Class'",
                "references learning outcomes + progress",
                "treats curriculum as the product",
            ],
            "taboo": ["over-promising career outcomes"],
        },
        "onboarding_questions": [
            {"id": "course_format", "prompt": "Self-paced, cohort-based, or both?", "kind": "select",
             "options": ["self_paced", "cohort", "both"]},
            {"id": "audience", "prompt": "Who's your typical student?", "kind": "text"},
            {"id": "pricing_model", "prompt": "One-time purchase, subscription, or both?", "kind": "select",
             "options": ["one_time", "subscription", "both"]},
        ],
        "offering_suggestions": [
            {"name": "Free Intro Lesson", "price": 0, "duration_min": 30,
             "description": "Free sample lesson so prospects can see your teaching style."},
            {"name": "Full Course", "price": 297, "duration_min": 0,
             "description": "Your complete curriculum — self-paced access."},
            {"name": "Cohort Program", "price": 1200, "duration_min": 0,
             "description": "Live cohort with weekly classes and group accountability."},
        ],
        "invoice_line_templates": [
            {"description": "Course access", "kind": "flat"},
            {"description": "Cohort tuition", "kind": "flat"},
            {"description": "1:1 coaching add-on", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Encouraging. Welcome them to class. Share what to expect in this session.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No classes scheduled. Want to set up your first cohort or office hours?",
            "customers": "No students yet. They'll appear here once they enroll.",
            "invoices": "No invoices yet. Set up course pricing first.",
            "offerings": "No offerings yet. Common: a free intro lesson + your main Course + a Cohort.",
        },
        "module_suggestions": [
            {"slug": "office-hours", "archetype": "booking_calendar",
             "headline": "Open office hours so students can book 1:1 time with you."},
        ],
    }),
    "creative": VerticalProfile({
        "voice": {
            "register": "creative, professional, project-focused",
            "formality": "balanced",
            "hallmarks": [
                "uses 'Client' and 'Project'",
                "references scope, timeline, revisions",
                "respects creative process + client constraints",
            ],
            "taboo": ["over-promising on creative outcomes"],
        },
        "onboarding_questions": [
            {"id": "discipline", "prompt": "What's your creative discipline (design, photography, writing, video, etc.)?", "kind": "text"},
            {"id": "engagement_model", "prompt": "Project-based, retainer, or both?", "kind": "select",
             "options": ["project", "retainer", "both"]},
            {"id": "client_type", "prompt": "Who's your typical client (brand, agency, individual)?", "kind": "text"},
        ],
        "offering_suggestions": [
            {"name": "Discovery Call", "price": 0, "duration_min": 30,
             "description": "Free intro call to scope the project."},
            {"name": "Project Deposit", "price": 1000, "duration_min": 0,
             "description": "50% deposit to kick off a project."},
            {"name": "Monthly Retainer", "price": 3000, "duration_min": 0,
             "description": "Recurring monthly creative support."},
        ],
        "invoice_line_templates": [
            {"description": "Project deposit (50%)", "kind": "flat"},
            {"description": "Project completion (50%)", "kind": "flat"},
            {"description": "Additional revisions", "kind": "flat"},
            {"description": "Stock / licensing", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Professional and warm. Confirm time. Note any materials you'll need them to bring (brief, references).",
            },
        },
        "empty_state_nudges": {
            "bookings": "No meetings scheduled. Want to set up your project scoping call?",
            "customers": "No clients yet. They'll appear here as projects start.",
            "invoices": "No invoices yet. Set up your project rates first.",
            "offerings": "No offerings yet. Common: Discovery Call + Project Deposit + Retainer.",
        },
        "module_suggestions": [
            {"slug": "scoping-calls", "archetype": "booking_calendar",
             "headline": "Start with a Scoping Call calendar so prospects can book project conversations."},
        ],
    }),
    "fitness_wellness": VerticalProfile({
        "voice": {
            "register": "motivating, supportive, body-aware",
            "formality": "casual + warm",
            "hallmarks": [
                "uses 'Client' and 'Session' / 'Class'",
                "encourages consistency",
                "respects body autonomy + recovery",
            ],
            "taboo": ["medical/clinical advice without licensure", "shame language about bodies"],
        },
        "onboarding_questions": [
            {"id": "modality", "prompt": "What's your modality (PT, yoga, pilates, group fitness, nutrition, etc.)?", "kind": "text"},
            {"id": "format", "prompt": "1:1 sessions, group classes, or both?", "kind": "select",
             "options": ["one_on_one", "group_class", "both"]},
            {"id": "pricing_model", "prompt": "Drop-in, package, or membership?", "kind": "select",
             "options": ["drop_in", "package", "membership", "all"]},
        ],
        "offering_suggestions": [
            {"name": "First Session", "price": 60, "duration_min": 60,
             "description": "Intro session — assess goals and create a plan."},
            {"name": "10-Session Package", "price": 500, "duration_min": 60,
             "description": "Discounted package of 10 sessions."},
            {"name": "Drop-in Class", "price": 25, "duration_min": 60,
             "description": "Single class drop-in."},
        ],
        "invoice_line_templates": [
            {"description": "Personal session", "kind": "flat"},
            {"description": "Class package (10 sessions)", "kind": "flat"},
            {"description": "Monthly membership", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Motivating + supportive. Confirm time. Remind them about water, clothing, or specific prep for the session.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No sessions scheduled. Want to set up your intro/assessment template first?",
            "customers": "No clients yet. They'll appear here as people book.",
            "invoices": "No invoices yet. Set up your session and package prices first.",
            "offerings": "No offerings yet. Common: First Session + Multi-Session Package + Drop-in.",
        },
        "module_suggestions": [
            {"slug": "sessions", "archetype": "booking_calendar",
             "headline": "Set up a session calendar so clients can book training time."},
        ],
    }),
    "ministry": VerticalProfile({
        "voice": {
            "register": "pastoral, caring, faith-aware",
            "formality": "warm + reverent",
            "hallmarks": [
                "uses 'Member' and 'Ministry'",
                "respects faith tradition without preaching",
                "treats giving as access-isolated (not transactional)",
                "minor-aware: children's ministry consent matters",
            ],
            "taboo": ["treating tithes/giving as a sales product", "monetizing pastoral care"],
        },
        "onboarding_questions": [
            {"id": "campus_model", "prompt": "Single campus or multi-site?", "kind": "select",
             "options": ["single_campus", "multi_site"]},
            {"id": "member_count", "prompt": "Roughly how many active members?", "kind": "select",
             "options": ["under_50", "50_200", "200_1000", "over_1000"]},
            {"id": "service_schedule", "prompt": "When do you hold your main services?", "kind": "text"},
            {"id": "children_ministry", "prompt": "Do you offer children's ministry (which would need RSVP + consent)?", "kind": "boolean"},
        ],
        "offering_suggestions": [
            {"name": "Counseling Session", "price": 0, "duration_min": 60,
             "description": "Pastoral counseling appointment (free; suggested donations welcome)."},
            {"name": "Event Registration", "price": 25, "duration_min": 0,
             "description": "Ticket for an event (retreats, conferences, workshops)."},
        ],
        "invoice_line_templates": [
            {"description": "Event registration", "kind": "flat"},
            {"description": "Ministry partnership / sponsorship", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Pastoral and welcoming. Confirm time. Mention childcare or dietary options if registering for an event.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No meetings scheduled. Want to set up pastoral counseling availability or open events?",
            "customers": "No members logged here yet. They'll appear as people RSVP or sign up.",
            "invoices": "No invoices yet. Most ministry surfaces are free; bills are usually for events or partnerships.",
            "offerings": "No offerings yet. Common: Counseling availability + Event Registration.",
        },
        "module_suggestions": [
            {"slug": "counseling", "archetype": "booking_calendar",
             "headline": "Open pastoral counseling availability so members can request time."},
            {"slug": "event-rsvp", "archetype": "fallback_generic",
             "headline": "Track RSVPs for upcoming events (childcare, dietary, accessibility)."},
        ],
    }),
    "financial_educator": VerticalProfile({
        "voice": {
            "register": "educational, regulated-aware, careful with claims",
            "formality": "formal",
            "hallmarks": [
                "uses 'Client' and 'Program'",
                "does NOT give individual financial advice without licensure",
                "references education, not recommendations",
            ],
            "taboo": ["promising returns", "treating educational content as investment advice"],
        },
        "onboarding_questions": [
            {"id": "audience", "prompt": "Who do you typically teach (beginners, intermediates, professionals)?", "kind": "text"},
            {"id": "delivery_format", "prompt": "Live cohort, self-paced, or 1:1?", "kind": "select",
             "options": ["cohort", "self_paced", "one_on_one", "mixed"]},
            {"id": "licensure", "prompt": "Do you hold any financial licenses (CFP, CFA, etc.)?", "kind": "text"},
        ],
        "offering_suggestions": [
            {"name": "Free Workshop", "price": 0, "duration_min": 60,
             "description": "Intro workshop — covers fundamentals."},
            {"name": "Core Program", "price": 497, "duration_min": 0,
             "description": "Full program — multi-week curriculum."},
            {"name": "1:1 Consultation (Education Only)", "price": 200, "duration_min": 60,
             "description": "Personalized education session (not financial advice)."},
        ],
        "invoice_line_templates": [
            {"description": "Program tuition", "kind": "flat"},
            {"description": "Workshop registration", "kind": "flat"},
            {"description": "1:1 consultation (education)", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Professional and careful. Confirm time. Clearly note this is education, not personalized financial advice.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No consultations scheduled. Want to set up your intro workshop or 1:1 education calendar?",
            "customers": "No clients yet. They'll appear here once they enroll.",
            "invoices": "No invoices yet. Set up your program tuition first.",
            "offerings": "No offerings yet. Common: Free Workshop + Core Program + 1:1 Consultation.",
        },
        "module_suggestions": [
            {"slug": "workshops", "archetype": "booking_calendar",
             "headline": "Open a workshop calendar so prospects can attend your intro session."},
        ],
    }),
    "personal_services": VerticalProfile({
        "voice": {
            "register": "friendly, practical, neighborhood-aware",
            "formality": "casual",
            "hallmarks": [
                "uses 'Customer' and 'Service'",
                "respects regulars + walk-ins both",
                "speaks plainly about price + time",
            ],
            "taboo": ["over-formal language"],
        },
        "onboarding_questions": [
            {"id": "shop_size", "prompt": "Solo or shop with multiple chairs/stations?", "kind": "select",
             "options": ["solo", "small_shop", "multi_chair_shop"]},
            {"id": "booking_model", "prompt": "Appointment-only, walk-ins, or both?", "kind": "select",
             "options": ["appointment_only", "walk_ins", "both"]},
            {"id": "payment_methods", "prompt": "How do customers pay?", "kind": "multiselect",
             "options": ["cash", "card", "venmo_cashapp", "online_only"]},
        ],
        "offering_suggestions": [
            {"name": "Standard Service", "price": 30, "duration_min": 30,
             "description": "Your most-booked service."},
            {"name": "Premium Service", "price": 50, "duration_min": 60,
             "description": "Longer or higher-end version of your standard service."},
            {"name": "Add-on", "price": 15, "duration_min": 15,
             "description": "Quick add-on customers stack onto a main service."},
        ],
        "invoice_line_templates": [
            {"description": "Service rendered", "kind": "flat"},
            {"description": "Product purchase", "kind": "flat"},
            {"description": "Tip", "kind": "flat", "hint": "Many practitioners include this as a separate line for transparency."},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Friendly and brief. Confirm time and remind them about arrival, parking, or cancellation policy.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No bookings yet. Want to enable walk-in scheduling alongside appointments?",
            "customers": "No customers yet. Share your booking link to get the first one in.",
            "invoices": "No invoices yet. Set up your service prices first.",
            "offerings": "No offerings yet. Common: 2-3 main services + a popular add-on.",
        },
        "module_suggestions": [
            {"slug": "bookings", "archetype": "booking_calendar",
             "headline": "Start with a Booking Calendar so customers can schedule their visit."},
        ],
    }),
    "service_provider": GENERIC,
    "custom": GENERIC,
}


# ─── Public helpers ─────────────────────────────────────────────────


def get_profile(business_type: Optional[str]) -> VerticalProfile:
    """Resolve a vertical to its full profile. Always returns a valid
    profile (falls back to GENERIC). Case-insensitive + trim."""
    bt = (business_type or "").lower().strip()
    return VERTICAL_INTELLIGENCE.get(bt) or GENERIC


def get_voice(business_type: Optional[str]) -> Dict[str, Any]:
    return get_profile(business_type).get("voice") or GENERIC["voice"]


def get_onboarding_questions(business_type: Optional[str]) -> List[Dict[str, Any]]:
    return list(get_profile(business_type).get("onboarding_questions") or [])


def get_offering_suggestions(business_type: Optional[str]) -> List[Dict[str, Any]]:
    return list(get_profile(business_type).get("offering_suggestions") or [])


def get_invoice_line_templates(business_type: Optional[str]) -> List[Dict[str, Any]]:
    return list(get_profile(business_type).get("invoice_line_templates") or [])


def get_email_voice(business_type: Optional[str], kind: str = "booking_confirmation") -> Dict[str, Any]:
    voice = get_profile(business_type).get("email_voice") or {}
    return voice.get(kind) or GENERIC["email_voice"].get(kind) or {}


def get_empty_state_nudge(business_type: Optional[str], surface: str) -> str:
    nudges = get_profile(business_type).get("empty_state_nudges") or {}
    return (
        nudges.get(surface)
        or (GENERIC["empty_state_nudges"].get(surface) or "")
    )


def get_module_suggestions(business_type: Optional[str]) -> List[Dict[str, Any]]:
    return list(get_profile(business_type).get("module_suggestions") or [])


def list_known_verticals() -> List[str]:
    """Stable order — for tests + admin probes."""
    return sorted(VERTICAL_INTELLIGENCE.keys())
