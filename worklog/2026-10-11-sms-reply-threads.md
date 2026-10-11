---
title: "A reply on the shared number reaches the business that texted them"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "we need to figure out how are we going to manage the other companies on 1 phone number... we need to make sure that is good (Kevin, 2026-10-11); then: build in the right order so it's fixed"
status: waiting on review
prs: [kmj-intake-server#1372]
migrations: []
left_undone: ["a STOP to the shared number still stops every business on it (that's how a shared number must work); a business's own number scopes STOP to itself", "everyone still texts under the platform brand (the Direct model); registering each business as its own brand (ISV) is the step before numbers for every plan", "a business with its own number that texted someone, who then writes to the shared number, is also a candidate (sms_messages doesn't record which number a text went from)"]
decisions: ["threads are read from sms_messages (either direction, last 30 days) and never written to sms_bindings, because a binding is also consent for automated alerts (has_sms_consent) and a business texting someone is not that person's consent", "one candidate takes the reply; among several, the conversation active within 72 hours wins; otherwise they choose, bound businesses first and then by id, so 'Reply 2' means the same business when it comes back", "choosing a business they were only texting with is kept as a system line in that thread, not a binding, so the next message continues there", "a failed history read means the keyword prompt, as before, never a guess"]
related: [2026-10-09-outreach-journeys.md]
---
On the shared platform number, a customer only reached a business by
texting its keyword (a binding). A business that texted them first (a
booking confirmation, a reminder, a note from the owner) made no binding,
so the reply "running 10 min late" got "Which business are you trying to
reach? Text their keyword". Live volume is tiny (25 texts, 2 bindings), so
nobody had hit it yet.

Now the businesses this person has texted with in the last 30 days are
candidates alongside their bindings. The routing rules stay as they were
(one goes straight there, the active conversation within 72 hours wins,
otherwise "Reply 1 for ..."), and nothing about consent changes.
