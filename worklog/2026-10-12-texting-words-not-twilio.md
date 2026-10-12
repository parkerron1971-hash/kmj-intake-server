---
title: "Your name on texts: the owner never hears Twilio"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "then why does it talk about setting up an account with twilio? this shouldn't have that then right? ... instead of it saying carrier, can it say something like solutionist? (Kevin, 2026-10-12)"
status: waiting on review
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone: ["the reasons Twilio itself gives for a rejection are passed on in its own words (prefixed 'The registration came back:'), and the sole proprietor's verification text is written by Twilio's side, not us"]
decisions: ["Solutionist (or 'we') for what we do: checking the details, sending the registration, setting up the number; 'the phone companies' for the approval they control, so a rejection never reads as Solutionist turning the owner down; Twilio and 'carriers' nowhere the owner reads", "the step labels: 'Your business is verified', 'You reply YES to the verification text on your cell', 'The phone companies review how you text'", "a guard test reads every update, step label, readiness check, HTTP error and fix-it reason in texting_registration and texting_isv for 'Twilio' or 'carrier'"]
related: [2026-10-11-isv-step-3.md, 2026-10-11-isv-sole-prop.md, 2026-10-12-texting-form-from-about.md]
---
Texting under each business's own name is Solutionist's service to the
owner; Twilio is the plumbing behind it (sms_numbers_router already holds
"the practitioner never hears 'Twilio'"). The registration's steps, the
updates the owner gets in the app, by push and by email, and its error
messages named Twilio and "the carriers". They now say who does what in
plain words. The screen's matching change is solutionist-studio#1208.
