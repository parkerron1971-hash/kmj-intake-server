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
            {"slug": "matter-tracker", "archetype": "work_pipeline",
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
            {"slug": "project-tracker", "archetype": "work_pipeline",
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
            {"slug": "event-rsvp", "archetype": "event_roster",
             "headline": "Track RSVPs for upcoming events (childcare, dietary, accessibility)."},
            {"slug": "serving-roster", "archetype": "event_roster",
             "headline": "Build the serving roster each week — greeters, nursery, sound — and see what's still unfilled."},
        ],
    }),
    # Secular donation-funded orgs. Distinct from ministry (faith) but the
    # same nonprofit ACCOUNTING family (restricted funds, donor/990) — see
    # vertical_family.py. Previously fell through to GENERIC, so a nonprofit
    # got generic voice + generic "customer/discovery call" offerings that
    # read wrong for a mission org.
    "nonprofit": VerticalProfile({
        "voice": {
            "register": "mission-driven, warm, stewardship-minded",
            "formality": "professional + heartfelt",
            "hallmarks": [
                "uses 'Donor' and 'Program'",
                "frames gifts as mission support, never a sale",
                "stewardship + transparency (restricted vs unrestricted)",
                "impact-focused without over-promising outcomes",
            ],
            "taboo": ["treating donations as transactional revenue", "guaranteeing specific impact"],
        },
        "onboarding_questions": [
            {"id": "cause_area", "prompt": "What cause or mission does the organization serve?", "kind": "text"},
            {"id": "tax_status", "prompt": "Are you a registered 501(c)(3) (or equivalent)?", "kind": "boolean"},
            {"id": "funding_mix", "prompt": "Where does most funding come from?", "kind": "multiselect",
             "options": ["individual_gifts", "grants", "events", "memberships", "earned_program_fees"]},
            {"id": "org_size", "prompt": "Roughly how many active donors/supporters?", "kind": "select",
             "options": ["under_50", "50_500", "500_5000", "over_5000"]},
        ],
        "offering_suggestions": [
            {"name": "Membership", "price": 50, "duration_min": 0,
             "description": "Annual supporting membership."},
            {"name": "Program Enrollment", "price": 0, "duration_min": 0,
             "description": "Sign-up for a program or service you offer (free or fee-based)."},
            {"name": "Event Ticket", "price": 40, "duration_min": 0,
             "description": "Registration for a fundraiser, gala, or program event."},
            {"name": "Sponsorship", "price": 1000, "duration_min": 0,
             "description": "Corporate or individual sponsorship of a program or event."},
        ],
        "invoice_line_templates": [
            {"description": "Membership dues", "kind": "flat"},
            {"description": "Program fee", "kind": "flat"},
            {"description": "Event ticket", "kind": "flat"},
            {"description": "Sponsorship", "kind": "flat"},
            {"description": "Restricted gift", "kind": "flat",
             "hint": "Designate to a restricted fund — books to restricted net assets, not general operating."},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Warm and mission-forward. Confirm time. Thank them for supporting the cause; note any event logistics (parking, dietary).",
            },
        },
        "empty_state_nudges": {
            "bookings": "No meetings scheduled. Want to open availability for donor meetings or program intake?",
            "customers": "No donors logged here yet. They'll appear as people give or enroll.",
            "invoices": "No invoices yet. Common: membership dues, program fees, event tickets, sponsorships.",
            "offerings": "No offerings yet. Common: Membership + Program Enrollment + Event Ticket + Sponsorship.",
        },
        "module_suggestions": [
            # Grants first. It is a CORE blueprint module for this vertical
            # and the onboarding card names it, yet it was the one
            # suggestion missing — so the surface that offers modules never
            # offered the one already being provisioned.
            {"slug": "grants", "archetype": "work_pipeline",
             "headline": "Track every grant from research to report, with its deadlines."},
            {"slug": "programs", "archetype": "fallback_generic",
             "headline": "Track your programs and who's enrolled in each."},
            {"slug": "event-rsvp", "archetype": "event_roster",
             "headline": "Track event RSVPs and sponsorships."},
            {"slug": "volunteer-roster", "archetype": "event_roster",
             "headline": "Schedule volunteers per event and see which shifts are still open."},
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
                "uses 'Client' and 'Service' — never 'Customer'",
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
            {"id": "payment_methods", "prompt": "How do clients pay?", "kind": "multiselect",
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
            "customers": "No clients yet. Share your booking link to get the first one in the chair.",
            "invoices": "No invoices yet. Set up your service prices first.",
            "offerings": "No services yet. Common: 2-3 main services + a popular add-on.",
        },
        "module_suggestions": [
            {"slug": "bookings", "archetype": "booking_calendar",
             "headline": "Start with a Booking Calendar so clients can schedule their visit."},
        ],
    }),
    "contractor": VerticalProfile({
        "voice": {
            "register": "practical, dispatch-minded, straight about cost",
            "formality": "plain",
            "hallmarks": [
                "uses 'Customer' and 'Job' — never 'Client' or 'Engagement'",
                "quotes before work starts, never after",
                "separates materials from labor",
                "treats a change order as a new agreement, not a favor",
            ],
            "taboo": [
                "vague pricing ('we'll see what it runs')",
                "committing to a date without a window",
                "advice that needs a license the practitioner may not hold",
            ],
        },
        "onboarding_questions": [
            {"id": "trades", "prompt": "What trades or work do you take on?", "kind": "text"},
            {"id": "crew_size", "prompt": "Do you work solo or run a crew?", "kind": "select",
             "options": ["solo", "small_crew", "multiple_crews"]},
            {"id": "pricing_model", "prompt": "How do you price a job?", "kind": "multiselect",
             "options": ["hourly", "flat_bid", "time_and_materials", "cost_plus"]},
            {"id": "deposit_policy", "prompt": "Do you take a deposit before starting?", "kind": "boolean"},
            {"id": "emergency_calls", "prompt": "Do you take emergency or after-hours calls?", "kind": "boolean"},
            {"id": "licensed_trades", "prompt": "Which of your trades require a license or permit?", "kind": "text"},
        ],
        "offering_suggestions": [
            {"name": "Estimate Visit", "price": 0, "duration_min": 45,
             "description": "On-site look at the work before quoting. Free or credited toward the job."},
            {"name": "Service Call", "price": 150, "duration_min": 60,
             "description": "Standard call-out — diagnose and fix small work in one visit."},
            {"name": "Emergency Call-Out", "price": 300, "duration_min": 90,
             "description": "After-hours or same-day response at a premium rate."},
            {"name": "Project Bid", "price": 0, "duration_min": 0,
             "description": "Quoted per job. Deposit up front, progress billing, balance on completion."},
        ],
        "invoice_line_templates": [
            {"description": "Labor", "kind": "hourly", "hint": "rate × hours, per worker"},
            {"description": "Materials", "kind": "flat", "hint": "Itemize or attach the supplier receipt."},
            {"description": "Deposit received", "kind": "flat", "hint": "Credit against the job total."},
            {"description": "Change order", "kind": "flat", "hint": "Work added after the original bid was accepted."},
            {"description": "Permit / inspection fee", "kind": "flat"},
            {"description": "Trip / call-out charge", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Short and practical. Confirm the DATE AND ARRIVAL WINDOW, not a "
                             "precise time. Say what the customer needs to do first — clear "
                             "access, move vehicles, pets away, someone over 18 on site.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No visits scheduled. Set your arrival windows so customers can book a slot that works.",
            "customers": "No customers yet. They'll appear here after their first estimate or call-out.",
            "invoices": "No invoices yet. Most trades bill a deposit first, then the balance on completion.",
            "offerings": "No services yet. Common: an estimate visit, a standard service call, and an emergency rate.",
        },
        "module_suggestions": [
            {"slug": "jobs", "archetype": "work_pipeline",
             "headline": "Track jobs from estimate through completion — site address, scope, and status."},
            {"slug": "visits", "archetype": "booking_calendar",
             "headline": "Set up a Visit calendar with arrival windows instead of exact times."},
            {"slug": "estimates", "archetype": "work_pipeline",
             "headline": "Log estimates so you can see what you bid, what you won, and at what price."},
        ],
    }),
    "therapist": VerticalProfile({
        "voice": {
            "register": "careful, sparse, non-clinical",
            "formality": "professional and quiet",
            "hallmarks": [
                "uses 'Client' and 'Session'",
                "says less rather than more about any individual",
                "treats the cancellation policy as a boundary, not a preference",
                "keeps to scheduling, billing and admin",
            ],
            "taboo": [
                "clinical language — diagnosis, symptoms, treatment",
                "speculating about a client's state",
                "summarising session content",
                "therapeutic warmth — this is an admin tool",
            ],
        },
        "onboarding_questions": [
            {"id": "license_type", "prompt": "What license do you practise under?", "kind": "select",
             "options": ["lcsw", "lmft", "lpc", "psychologist", "psychiatrist", "other"]},
            {"id": "practice_model", "prompt": "Private pay, insurance, or both?", "kind": "select",
             "options": ["private_pay", "insurance", "both", "sliding_scale"]},
            {"id": "session_cadence", "prompt": "Typical session cadence?", "kind": "select",
             "options": ["weekly", "biweekly", "monthly", "varies"]},
            {"id": "cancellation_policy", "prompt": "What is your cancellation window and fee?", "kind": "text"},
            # Deliberately NOT asked: anything about presenting concerns,
            # modality specifics, or client population. The system does not
            # need it and should not hold it.
        ],
        "offering_suggestions": [
            {"name": "Initial Consultation", "price": 0, "duration_min": 15,
             "description": "Brief no-charge call to check fit before scheduling."},
            {"name": "Individual Session", "price": 150, "duration_min": 50,
             "description": "Standard 50-minute session."},
            {"name": "Extended Session", "price": 220, "duration_min": 80,
             "description": "Longer session where the work calls for it."},
        ],
        "invoice_line_templates": [
            {"description": "Individual session (50 min)", "kind": "flat"},
            {"description": "Extended session (80 min)", "kind": "flat"},
            {"description": "Late cancellation fee", "kind": "flat",
             "hint": "Per your stated cancellation window."},
            {"description": "Superbill — client submits to insurer", "kind": "flat",
             "hint": "A receipt for the client to file. The platform does not "
                     "bill insurers."},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Short, plain and warm-neutral. Confirm the time and "
                             "the cancellation window. Say NOTHING about the "
                             "content or purpose of the session — a confirmation "
                             "email is often read by someone other than the client.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No sessions scheduled. Set your weekly availability and cancellation window first.",
            "customers": "No clients yet. They'll appear here once you schedule or invoice.",
            "invoices": "No invoices yet. Set your session rate and whether you issue superbills.",
            "offerings": "No session types yet. Common: a brief consult, a standard 50-minute session, and an extended one.",
        },
        "module_suggestions": [
            # Scheduling and billing only, by design. Nothing here proposes a
            # clinical record, and vertical_scope refuses one if asked.
            {"slug": "sessions", "archetype": "booking_calendar",
             "headline": "Set up a Session calendar with your cancellation window built in."},
            {"slug": "superbills", "archetype": "fallback_generic",
             "headline": "Track superbills issued so clients can file with their insurer."},
        ],
    }),
    # Selling products, not time. The unit is an ORDER that has to be
    # picked, packed and shipped — stock runs out, a carrier owns the
    # delivery date, and sales tax is collected for a state rather than
    # earned. No service vertical above models any of that.
    "ecommerce": VerticalProfile({
        "voice": {
            "register": "practical, product-forward, logistics-aware",
            "formality": "plain",
            "hallmarks": [
                "uses 'Customer' and 'Product' — an order, never a booking",
                "treats stock, shipping and returns as first-class, not afterthoughts",
                "separates what SOLD from what SHIPPED",
                "quotes the delivered price, not the list price",
            ],
            "taboo": [
                "promising a delivery date the carrier controls",
                "treating a return as a failure rather than a cost of selling online",
                "calling collected sales tax revenue",
            ],
        },
        "onboarding_questions": [
            {"id": "sales_channels", "prompt": "Where do you sell?", "kind": "multiselect",
             "options": ["own_site", "marketplace", "social", "in_person", "wholesale"]},
            {"id": "fulfillment_model", "prompt": "Who ships your orders?", "kind": "select",
             "options": ["self_ship", "third_party_logistics", "dropship",
                         "print_on_demand", "digital_only"]},
            {"id": "catalog_size", "prompt": "Roughly how many products do you sell?", "kind": "select",
             "options": ["under_10", "10_to_50", "50_to_500", "over_500"]},
            {"id": "inventory_tracking", "prompt": "Do you track stock levels?", "kind": "boolean"},
        ],
        "offering_suggestions": [
            {"name": "Core Product", "price": 35, "duration_min": 0,
             "description": "Your best seller — the one most customers arrive for."},
            {"name": "Bundle", "price": 90, "duration_min": 0,
             "description": "Two or more products sold together, priced better than separately."},
            {"name": "Subscription / Refill", "price": 25, "duration_min": 0,
             "description": "A consumable customers re-order on a schedule."},
            {"name": "Digital Download", "price": 15, "duration_min": 0,
             "description": "A file customers get instantly — no stock, no shipping."},
        ],
        "invoice_line_templates": [
            {"description": "Product sale", "kind": "quantity", "hint": "unit price × quantity"},
            {"description": "Shipping", "kind": "flat"},
            {"description": "Sales tax", "kind": "flat",
             "hint": "Collected on behalf of the state — not revenue."},
            {"description": "Discount / promo", "kind": "flat"},
            {"description": "Restocking fee", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Order-focused and short. Confirm what was bought, when it ships "
                             "and how to reach a human. Give a shipping WINDOW, never a "
                             "guaranteed date.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No orders yet. Add your first product so there's something to buy.",
            "customers": "No customers yet. They'll appear here as orders come in.",
            "invoices": "No invoices yet. Most stores get paid at checkout — invoices are for wholesale and custom orders.",
            "offerings": "No products yet. Add your best seller first; the rest can follow.",
        },
        "module_suggestions": [
            {"slug": "orders", "archetype": "work_pipeline",
             "headline": "Track orders from paid through packed to delivered."},
            {"slug": "products", "archetype": "fallback_generic",
             "headline": "Your catalog, with the stock level beside each item."},
            {"slug": "returns", "archetype": "work_pipeline",
             "headline": "Log returns so you can see what comes back, and why."},
        ],
    }),
    # Recurring revenue. The money is subscribed rather than sold once, so
    # an annual plan is cash today and revenue spread across a year, and
    # churn is decided weeks before the renewal that reveals it.
    "saas": VerticalProfile({
        "voice": {
            "register": "clear, product-led, retention-aware",
            "formality": "plain",
            "hallmarks": [
                "uses 'Customer' and 'Plan' — a subscription, never a project",
                "distinguishes trial, active, past-due and churned",
                "treats recurring revenue as the number that matters",
                "reads usage as the leading indicator and billing as the lagging one",
            ],
            "taboo": [
                "quoting a signup count without the retention behind it",
                "committing to a roadmap date",
                "counting an annual payment as one month's revenue",
            ],
        },
        "onboarding_questions": [
            {"id": "pricing_model", "prompt": "How do you charge?", "kind": "multiselect",
             "options": ["monthly", "annual", "per_seat", "usage_based", "one_time"]},
            {"id": "trial_model", "prompt": "How do people try it before paying?", "kind": "select",
             "options": ["free_trial", "freemium", "demo_only", "paid_only"]},
            {"id": "target_customer", "prompt": "Who is it for?", "kind": "select",
             "options": ["consumers", "small_business", "mid_market", "enterprise"]},
            {"id": "self_serve", "prompt": "Can someone sign up and pay without talking to you?",
             "kind": "boolean"},
        ],
        "offering_suggestions": [
            {"name": "Starter Plan", "price": 29, "duration_min": 0,
             "description": "Monthly entry plan — the smallest thing worth paying for."},
            {"name": "Pro Plan", "price": 99, "duration_min": 0,
             "description": "Monthly plan for customers using it seriously."},
            {"name": "Annual Plan", "price": 990, "duration_min": 0,
             "description": "A year paid up front, usually below twelve months at the monthly rate."},
            {"name": "Onboarding & Setup", "price": 500, "duration_min": 60,
             "description": "One-off implementation help for larger accounts."},
        ],
        "invoice_line_templates": [
            {"description": "Subscription — monthly", "kind": "flat"},
            {"description": "Subscription — annual", "kind": "flat",
             "hint": "Paid up front, earned across twelve months."},
            {"description": "Additional seats", "kind": "quantity", "hint": "seat price × seats"},
            {"description": "Usage / overage", "kind": "quantity"},
            {"description": "Onboarding & setup", "kind": "flat"},
            {"description": "Proration credit", "kind": "flat"},
        ],
        "email_voice": {
            "booking_confirmation": {
                "tone_note": "Direct and short. Confirm the plan, the amount and the next "
                             "renewal date. No marketing language in a billing email.",
            },
        },
        "empty_state_nudges": {
            "bookings": "No demos booked yet. Add a demo or onboarding call so prospects can pick a time.",
            "customers": "No customers yet. They'll appear here as accounts sign up.",
            "invoices": "No invoices yet. Subscriptions usually bill themselves — invoices are for annual and enterprise deals.",
            "offerings": "No plans yet. Add an entry plan and one step up; two is enough to start.",
        },
        "module_suggestions": [
            {"slug": "accounts", "archetype": "work_pipeline",
             "headline": "Track accounts through trial, active, past-due and churned."},
            {"slug": "demos", "archetype": "booking_calendar",
             "headline": "Let prospects book a demo without emailing you first."},
            {"slug": "feature-requests", "archetype": "fallback_generic",
             "headline": "Capture what customers ask for, and who asked."},
        ],
    }),
    "service_provider": GENERIC,
    "custom": GENERIC,
}


# ─── Public helpers ─────────────────────────────────────────────────


def _registry():
    """Imported lazily, not at the module header.

    vertical_registry imports vertical_family, and this module is imported
    by vertical_context, vertical_knowledge and the router. Keeping the
    import inside the call means nothing here depends on import ORDER — a
    cycle introduced later surfaces as an honest ImportError at call time
    rather than as a half-initialised module handing back empty dicts."""
    import vertical_registry
    return vertical_registry


def get_profile(business_type: Optional[str]) -> VerticalProfile:
    """Resolve a vertical to its full profile. Always returns a valid
    profile (falls back to GENERIC). Case-insensitive + trim.

    Goes through `vertical_registry.resolve()`, so every ALIAS the registry
    recognises lands on its vertical's profile. This was a raw dict lookup,
    and the keys here are canonical-only — so `businesses.type` values like
    'agency', 'church', 'attorney' and 'plumber', which the registry maps
    to creative / ministry / lawyer / contractor, all fell through to
    GENERIC. Not hypothetical strings: 'agency' was the single most common
    type in the live table, and every one of those businesses got a generic
    Chief while its own screens read the vertical dictionary. A church read
    'Member' on screen and Chief was told 'customer=Customer' in the same
    breath. The frontend hit the identical bug and fixed it in
    verticalCanonical.ts; this is the backend half.

    A type the registry does NOT recognise still resolves to 'custom',
    which is itself a profile — deliberately the generic catch-all. Use
    `is_mapped()` when you need to tell "explicitly mapped" from "fell
    back", because `get_profile` alone can no longer answer that."""
    key = _registry().resolve(business_type)
    return VERTICAL_INTELLIGENCE.get(key) or GENERIC


def is_mapped(business_type: Optional[str]) -> bool:
    """True when this type is a canonical key or a registry alias — i.e.
    the profile it gets is genuinely ITS profile rather than the fallback.

    'custom' and its aliases count as mapped: landing on the catch-all
    because you asked for the catch-all is not the same as landing there
    because nothing recognised you."""
    bt = (business_type or "").lower().strip().replace("-", "_").replace(" ", "_")
    return bt in _registry().alias_to_canonical()


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


# ─── Phase G — Chief bookkeeping intelligence (per-archetype) ─────────
# Kept as a side map (not woven into each VerticalProfile) so existing
# profile consumers are untouched. Generic baseline + one entry per
# canonical vertical that has distinct bookkeeping framing — which is all
# of them except 'custom', where the vertical itself is still unknown.
#
# SCOPE: this is CATEGORISATION framing — which bucket a transaction
# belongs in, and what a practitioner in this trade routinely gets wrong.
# It is read by chief_bookkeeping when Chief proposes how to book
# something. It is not tax advice and must not grow into it: anything
# genuinely jurisdiction- or circumstance-dependent (a housing allowance,
# a nexus question) names the boundary and points at the practitioner's
# accountant rather than answering for them.
_BOOKKEEPING_GENERIC: Dict[str, Any] = {
    "category_note": "",
    "nudges": ["Set aside for taxes as money comes in."],
}
BOOKKEEPING_BY_VERTICAL: Dict[str, Dict[str, Any]] = {
    "lawyer": {
        "category_note": "Keep client trust/IOLTA funds separate from operating money — "
                         "trust deposits are not income.",
        "nudges": ["Quarterly estimated taxes are due if self-employed.",
                   "Don't categorize trust-account movement as revenue."],
    },
    "consultant": {
        "category_note": "Most deposits are project revenue; reimbursed expenses pass through.",
        "nudges": ["Quarterly estimated taxes apply to self-employment income.",
                   "Tax-payment season is approaching — keep the Tax bucket funded."],
    },
    "creative": {
        "category_note": "Separate client funds (e.g. ad spend, licensing pass-through) from your fees.",
        "nudges": ["Quarterly estimated taxes apply to self-employment income."],
    },
    "coach": {
        "category_note": "Package and session deposits are revenue; refunds reduce it.",
        "nudges": ["Quarterly estimated taxes apply to self-employment income."],
    },
    "financial_educator": {
        "category_note": "Course and coaching revenue vs. affiliate/sponsorship income may be taxed differently.",
        "nudges": ["Quarterly estimated taxes apply to self-employment income."],
    },
    # ── Added 2026-08-30. The five above shipped with Phase G and the
    # other nine verticals fell to _BOOKKEEPING_GENERIC — a single line
    # ("Set aside for taxes as money comes in") for a contractor holding
    # customer deposits, a church holding designated gifts and a nonprofit
    # holding restricted grants alike. Each entry below names the ONE
    # miscategorisation that vertical actually makes, because Chief reads
    # this when it proposes how to book a transaction.
    "contractor": {
        "category_note": "A deposit taken before work starts is money owed until the job is "
                         "done, not revenue on the day it lands. Keep materials apart from "
                         "labor — job costing and, in most states, sales tax both turn on "
                         "the split.",
        "nudges": ["Subcontractors paid $600+ across the year need a 1099.",
                   "Quarterly estimated taxes apply to self-employment income."],
    },
    "personal_services": {
        "category_note": "Tips belong to whoever earned them and are not shop revenue. Keep "
                         "retail product sales apart from service revenue — product is "
                         "typically sales-taxable where the service is not.",
        "nudges": ["Booth rent collected from stylists is rental income, not service revenue.",
                   "Quarterly estimated taxes apply to self-employment income."],
    },
    "fitness_wellness": {
        "category_note": "Memberships and class packs are paid up front but earned over time "
                         "— the unused balance is sessions still owed, not revenue yet.",
        "nudges": ["Retail (supplements, gear) is usually taxed differently from service revenue.",
                   "Quarterly estimated taxes apply to self-employment income."],
    },
    "course_creator": {
        "category_note": "A sale is earned when the refund window closes, not when the payment "
                         "lands. Record the GROSS and the platform or affiliate fee separately "
                         "— netting them hides the fee and understates revenue.",
        "nudges": ["Digital products can trigger sales tax or VAT where the BUYER is, not where you are.",
                   "Affiliates paid $600+ across the year need a 1099."],
    },
    "service_provider": {
        # service_provider is the deliberate generic baseline for VOICE
        # (see vertical_registry.KNOWN_GAPS) — that ruling is about tone,
        # not about money. Deposits and pass-through expenses are concrete
        # and get mis-booked the same way whatever the trade.
        "category_note": "Deposits and retainers are work owed until delivered. Reimbursed "
                         "expenses pass through — they are not income you keep.",
        "nudges": ["Contractors you pay $600+ across the year need a 1099.",
                   "Quarterly estimated taxes apply to self-employment income."],
    },
    "therapist": {
        # Money only. Clinical records stay out of scope (vertical_scope);
        # nothing here reads, stores or infers session content, and a
        # no-show fee is a billing fact, not a clinical one.
        "category_note": "Private pay and insurance reimbursement behave differently — a claim "
                         "paid months later still belongs to the date of service. Track the two "
                         "apart, and sliding-scale discounts as a reduction rather than a write-off.",
        "nudges": ["No-show and late-cancellation fees are taxable revenue.",
                   "Quarterly estimated taxes apply to self-employment income."],
    },
    "ministry": {
        "category_note": "A designated gift is restricted — given for a stated purpose, it "
                         "cannot fund general operations. Track designated apart from "
                         "undesignated giving; the distinction is the books' whole job here.",
        "nudges": ["A gift of $250+ needs a written acknowledgment before the giver files.",
                   "A minister's housing allowance is treated differently from salary — "
                   "worth confirming with your accountant."],
    },
    "nonprofit": {
        "category_note": "Restricted funds carry the donor's conditions with them and are not "
                         "available for general operating until released. Grant money usually "
                         "arrives with reporting attached — book it so the report is possible.",
        "nudges": ["A gift of $250+ needs a written acknowledgment before the donor files.",
                   "Form 990 is due the 15th day of the 5th month after your fiscal year ends."],
    },
    "ecommerce": {
        "category_note": "Sales tax collected is money held for the state, not revenue. Cost "
                         "of goods belongs against the sale it funded, and inventory bought is "
                         "not an expense until it sells. Shipping charged to the customer is "
                         "revenue; shipping you pay is a cost — netting them hides the margin.",
        "nudges": ["Marketplace and processor fees come out of gross — record the gross, then the fee.",
                   "Sales tax registration depends on where your BUYERS are, not only where you are."],
    },
    "saas": {
        "category_note": "An annual plan is cash today and revenue earned across twelve months "
                         "— the unearned remainder is deferred revenue, not profit. Refunds and "
                         "prorations reduce the period they belong to, not the one they are "
                         "processed in.",
        "nudges": ["Processor fees come out of gross — record the gross, then the fee.",
                   "Whether software is sales-taxable varies by state and by how it is delivered "
                   "— worth confirming with your accountant."],
    },
    # 'custom' is deliberately absent. vertical_registry.KNOWN_GAPS marks it
    # "intentionally GENERIC — triggers Chief interactive discovery": the
    # whole point is that the system does not yet know what the business
    # does, so inventing a bookkeeping note for it would be inventing the
    # vertical. It stays on _BOOKKEEPING_GENERIC until discovery names one.
}


def get_bookkeeping(business_type: Optional[str]) -> Dict[str, Any]:
    """Per-archetype bookkeeping framing for Chief's context. Always returns
    a valid dict (generic baseline).

    Alias-resolved like the rest: 'attorney' has to reach the lawyer entry,
    or a firm gets the generic "set aside for taxes" line instead of the one
    telling it not to book trust-account movement as revenue."""
    key = _registry().resolve(business_type)
    return BOOKKEEPING_BY_VERTICAL.get(key) or _BOOKKEEPING_GENERIC


def list_known_verticals() -> List[str]:
    """Stable order — for tests + admin probes."""
    return sorted(VERTICAL_INTELLIGENCE.keys())
