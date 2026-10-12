---
title: "The website stops offering therapy and health care practices"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "go ... update the website and anything else you need to (Kevin, 2026-10-12, after deciding to pause therapist and health care businesses)"
status: waiting on review
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: ["the design concept the home template was built from (solutionist-studio/design/bridgemind-hero-concept/solutionist-hero-concept.html) still has the therapist demo; regenerating the template from it would bring it back", "the static social card image (/assets/og) was not inspected for a therapist picture", "product code for the therapist vertical (desks, scope rules, site concierge fence, marketing_profile defaults) is untouched on purpose: the signup pause is a separate PR and the code stays dormant for a reopen"]
decisions: ["attorney takes the therapist's demo slot on the home page (the product has a full lawyer desk)", "nonprofits replace therapists in the trade list, so 'seven trades' stays true: barbers, attorneys, contractors, coaches, consultants, ministries, nonprofits", "typing a therapy or health trade into the home page's box gets 'Solutionist isn't taking on therapy or health care practices yet' instead of 'it learns yours on day one'", "the attorney cost calculator states its own assumption (a third of unbilled hours caught, half of quiet consultations booked, each at one billed hour)"]
related: [2026-10-11-business-brain.md]
---
Kevin paused therapist and health care businesses on 2026-10-12: a real HIPAA
setup (BAAs with every vendor, Supabase's HIPAA tier and the rest) isn't worth
paying for at today's size. The public site still demoed a counseling practice,
counted therapists among the seven trades and promised "clinical notes stay in
your EHR". This removes all of it from every routed page (home, Get Started)
and from the unrouted home v1, and pins it with a test. "Counsel that holds up /
Family mediation" on the features page is legal-mediation copy and stays.
