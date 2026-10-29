---
title: Each office login is its own person (not the owner)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28: "I sent the access for the others to get in. they went to sign up and it greeted them as Kevin. Which means they are not given the ability to set their account up as themselves or tie it to the account as a member". Also: a lane login''s phone should work for their lane, and should a key holder''s app look different from the admin''s'
status: shipped
prs: [kmj-intake-server#1638, solutionist-studio#1400]
migrations: [supabase/APPLY-2026-10-28-seat-person.sql]
left_undone:
  - "A seat with no record and no name (signed up before this) is greeted by no name; nothing lets them set one yet"
  - "The member's photo isn't the seat's picture: member photos are served by the member app (/my/photo) behind its own sign-in"
decisions:
  - "A seat's person is the business's record of them (contacts.id on business_users.contact_id): named at the invite (InviteBody.contact_id, one of the business's own) or found by the invite's email, else by the address they signed up with. The member app finds the same record by the same email, so the office login and the member app are one person"
  - "An email names a person only exactly (any case; the ilike is filtered again in Python, so ann@ never names joann@). A shared family address names no one unless the name they gave at sign-up picks one first name: a guess would greet the wrong person"
  - "business_users.name keeps the name they gave, for a login no record names"
  - "/team/my-role returns `me` ({name, first_name, contact_id}) for a seat; the owner gets none (the business's settings name them). /team/validate adds the name, first name and lane label, so the invite page welcomes them as themselves; the token is the secret, as before. /team/accept takes `name` and ties the person on a second write, so a seat that can't be named still gets in. The team list adds `person`"
---

Love City's office logins signed up and were greeted as Kevin: a seat had no name of its own, so the app used the business's name for its owner. Each seat is now tied to the church's record of that person.

Shipped 2026-10-28: #1638 merged at 23:48 UTC (deployed; migration applied before it), the app's half (solutionist-studio#1400) at 23:52. Chief saying who it's helping came from the other session in #1641 (merged 2026-10-29 01:27 UTC), on seat_person. The church's own office door followed (worklog 2026-10-28-office-door).
