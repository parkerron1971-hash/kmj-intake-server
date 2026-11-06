---
title: A church's import makes members, guests and families
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06, after the run-through report: "yes build the import fix ... fix the issues that we have ran into"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio church-import (the dialog)]
migrations: []
left_undone:
  - "Families are made only from a Household column. A file without one still relies on the Families page's suggestions (members only, as before)"
  - "Two different people with the same name and no email, phone or birthdate are matched as one on a church import; rare, and the preview shows it as 'already in your contacts'"
decisions:
  - "Only a church (vertical ministry) is offered the household fields; a business's import is unchanged, and household fields a browser sends for a business are kept as details"
  - "A church's membership column beats a plain Status column (Planning Center exports both). A gym's 'Membership' is still a detail"
  - "Member → active, Visitor/Guest → lead, Elder/Deacon/Staff/Pastor/Leader → vip, Former member/Transferred/Deceased → inactive. Where the roll's word says less (Regular Attender → Guest) the church's own word stays in metadata.imported"
  - "'Child' in a membership column is a place in the family, not a status: the child takes the family's status (a member family's child is a member)"
  - "A birthdate decides child or adult; without one, the file's household role (Child, Son, Head, Spouse, or a Child yes/no column) decides"
  - "Two or more people with the same Household make one family through church_families.make_family (households, household_adults, children with contact_id), all or nothing. A household of one stays a person. Status doesn't gate it: a visiting family's child must be findable at Kids check-in"
  - "Someone already in a family stays in it; new people in the same Household join that family (join_family). Members already in two different families are left alone and named"
  - "contacts.birthdate is set from a full birthday (YYYY-MM-DD, M/D/YYYY, 'March 14, 1979'); metadata.birthday keeps it as written"
  - "A church row with no email and no phone matches an existing person by name (and birthdate when both have one), so a second import doesn't add the children twice"
  - "Imported guests get first_response_at so they never sit in 'nobody has replied' (as subsplash_import does). Church only"
related: []
---
The 2026-11-05 run-through imported the church's own 12-person file (Membership Status, Household, Birthdate). Everyone came in as a Guest, nobody was in a family, and Kids check-in found nobody until the Hale family was made by hand. Membership Status had no synonym, Household was kept as a detail, and the birthday went to metadata.birthday while the families code reads contacts.birthdate. __tests__/test_church_import_families.py runs that same file through the import.
