---
title: "No new therapy, counseling or health care practices"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "I have been thinking of pausing therapist and heath care data ... go. there is no therapist business in the system (Kevin, 2026-10-12)"
status: waiting on review
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: ["website copy (separate PR) and the app's type pickers (frontend PR) drop therapists too", "the terms get a no-health-records clause in the privacy/terms PR", "reopening needs a separate health setup with BAAs from every vendor that would touch the data; trigger = a health tier that pays for it"]
decisions: ["paused at business creation, server side: canonical therapist plus therapy, counseling and clinical health words in a free-text type", "bare 'counsel', law, attorney, legal and massage never match, so lawyers and spas open normally", "env PAUSED_VERTICALS (default therapist,health_care; 'none' reopens); the therapist vertical's code stays, dormant", "corrected the HIPAA reasoning: for a practice that bills insurance, schedule and invoices are PHI, so admin-only was not out of business-associate territory"]
related: [2026-10-11-business-brain.md]
---
Kevin paused therapist and health care businesses on 2026-10-12: a HIPAA setup
(Supabase's HIPAA tier alone is about $1,000 a month, plus BAAs from every other
vendor) has no revenue behind it at today's size, and none exist. Business
creation now refuses those types with a plain message. The narrowed therapist
launch's code is kept so reopening is a decision, not a rebuild.
