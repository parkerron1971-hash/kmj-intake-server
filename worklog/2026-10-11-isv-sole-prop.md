---
title: "Texting under each business's own name: the sole proprietor way (no EIN)"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin, 2026-10-11, on the plan's D5 (a business without an EIN): \"Build it now.\""
status: waiting on review
prs: [kmj-intake-server#1395]
migrations: []
left_undone: ["the owner's screen (mobile field, the 'reply YES' panel, 'Send a new text'): the next PR, in solutionist-studio", "goes live with the rest of registration: Twilio relabels our primary profile 'ISV Reseller or Partner' (ticket #29903903), then TEXTING_REGISTRATION_OPEN names the pilot"]
decisions: ["same flow as an EIN business, path = sole_prop in the registration's twilio record: a Starter customer profile (policy RN806dd6cd175f314e1f96a9727ee271f4: first and last name, email, phone), the Sole Proprietor trust bundle (RN670d5d2e282a6130ae063b234b6019c8: brand name and the owner's own cell), BrandType SOLE_PROPRIETOR, then a SOLE_PROPRIETOR campaign and one number", "only a sole proprietor may register without an EIN (Twilio: every LLC has one); a sole proprietor with an EIN registers as the type on the EIN", "once the brand is approved Twilio texts the owner's cell from +1 (915) 278-2000 and the brand stays UNVERIFIED until they reply YES within 24 hours; the owner is told in the app, by push and by email, and the screen shows a 'confirm' step", "'Send a new text' (POST BrandRegistrations/{sid}/SmsOtp) at most every ten minutes, owner only", "the owner's cell is the one place a real mobile is required: never a provider's number"]
related: [2026-10-11-isv-step-3.md, 2026-10-11-isv-step-4a.md, 2026-10-11-isv-step-4b.md]
---
A business without an EIN can't take the Low-Volume Standard path. Twilio's
Sole Proprietor path takes the owner's own details instead, then asks the
owner to confirm by replying YES to one text on their own cell. This builds
that path into the same send, sweep and updates as step 3, with one extra
step the owner can see and a way to ask for a new text.
