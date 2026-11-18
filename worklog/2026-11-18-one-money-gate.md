---
title: One money gate. Every door that asks "may this login see or work the church's money?" asks it in one place, and nobody's answer changes
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18, on giving as its own tick on a person''s sheet: "yes build with C." This is the first piece of that build (step three of One sheet per person): the groundwork, with no change in who gets in.'
status: in progress
prs: []
migrations: []
left_undone:
  - "Not pushed: local commits on the branch one-money-gate, for the parent session to open as a PR after an independent review."
  - "The giving tick itself is NOT here. It becomes one more standing in church_money_gate._Facts.has() and one more name in the rows that take it."
  - "THE LEGACY AREA ROW IS KEPT, NOT CLOSED. A non-Admin office login whose areas (as Who sees what works them out) include Giving & money still opens check requests (church_checks.treasurer) and the treasurer's side of help requests (church_help.view_of). The app's own saves refuse that area for a login, so in practice it is Chief's guess from a leader role the login's person holds, or a direct write to business_users.areas. The tick replaces it. The count query below says who it admits today."
  - "NOT MOVED, on purpose: the every-business read ladders behind the gate's wall (gl_router._access, reports_router._owner_or_reader, plaid_router._require_reader: owner, accountant, any seat), reports_router's owner-only writes and its seat ladders for sends and budgets, and stripe_payments_router's charge and refund ladders. They decide for every kind of business; a church asks the gate's wall first on the ledger, the reports and the bank."
  - "NOT MOVED, and worth a decision: payroll_router, contractors_router, accounting_periods_router, grants_router, customer_balances_router and suppliers_router never ask the church wall at all, so through the server any seat on a church (a Viewer too) reads them. The ledger, the reports and the bank refuse the same login. Left exactly as it was."
  - "NOT MOVED: Chief's scope (chief_areas.MONEY) reads the same guessed areas as a first filter; every money verb behind it asks the gate. church_help.treasurers (who to TELL that a request is ready to pay) reads the same guess. church_sheet's money_ok is what a sheet shows, not a door."
decisions:
  - "The table is keyed by (part, need). The two needs share a row everywhere except the books, the bank and the bills, where reading and changing were already different gates."
  - "The old names stay (giving_records.require_finance, require_ministry_finance, church_money_gate.require_money_writer) and ask the gate, so about 40 routes did not change."
  - "A door that already resolved the person's role, the business row or their areas passes it in, so no door reads more than it did. church_checks passes the role it resolved itself, so a Manager who is also the accountant is still not the treasurer by that, as before."
  - "Reopening a closed count now asks the gate by the seat instead of reading require_finance's answer; test_giving_counts_close sets the seat."
  - "ownership_sweep sees the gate by a code anchor (the hint require_money( ), not by words in its docstring; may_money is not a hint because it refuses nothing."
  - "The church-wall rows (books and bank at see) are not a full answer: a business that is not a church or nonprofit comes back NOT_ASKED, and may_money refuses to answer for those rows."
related: [2026-11-18-sheet-login-level.md, 2026-11-18-help-treasurer-pays.md]
---
Until this change the answer to "may this login see or work the church's
money?" was written about forty times, in ten slightly different ways:
`giving_records.require_finance` (20 call sites), `require_ministry_finance`,
`church_money_gate.require_money_writer`, and hand-written copies in check
requests, reports, the members roll, My week, rooms and rentals, bills, the
count sheets, and each owner-only door.

**Now.** `church_money_gate.require_money(business_id, user, need, part)` and
its yes-or-no twin `may_money`. `RULES` at the top of the module is the whole
rule: one row per part and need, each with a comment naming the old gate it
reproduces.

| part | see | work |
|---|---|---|
| giving | owner, Admin, accountant | the same |
| books, bank | church or nonprofit: owner, Admin, accountant; any other business: not asked | owner; in a church an Admin too |
| bills | owner, accountant; church: Admin; other: any seat | owner; in a church an Admin too |
| store | owner; in a church an Admin too | the same |
| checks | owner, Admin, accountant, or the legacy area row | the same |
| help (the treasurer's side) | the legacy area row | the same |
| rentals, my_week | owner, Admin | the same |
| count_reopen | (none) | owner, Admin |
| setup | owner | owner |

**Proof nobody's answer changed.** `__tests__/test_one_money_gate.py` keeps a
copy of each old gate as it stood on main (f859d05a) and compares it with the
door that replaced it for eleven kinds of person (owner, Admin, accountant, a
Manager with the treasurer lane, a Manager with a guessed giving area, a plain
Manager, Member, Viewer, a stranger, a Manager who is also the accountant, a
removed Admin) on four businesses (a church, a nonprofit that isn't a church, a
shop, one that doesn't exist): the same yes or no, the same status, the same
words, the same value handed back. A source scan fails if a money module reads
a role, the accountant or the owner to decide access itself; every other such
line in those modules is on a list with its reason.

**Who the legacy area row admits.** A login that is not the owner, an Admin or
the accountant, when Who sees what is on and either (a) its saved areas include
Giving & money (the app refuses to save that, so only a direct database write),
or (b) it has no saved areas and its person (the member whose email is the
login's) holds an ACTIVE leader role that sits in Giving & money: by the
church's own placement of that role or its team, or by Chief's guess from the
role's title ("treasurer", "finance", "counter", "stewardship", "budget",
"bookkeeper", "accountant", "trustee"). A lane or a church job never does it:
neither can carry Giving & money.

Count them (read-only; counts only; a church with an open leaders map may be
off by a role or two, since its departments also place roles):

```sql
with seats as (
  select bu.business_id, bu.user_id, lower(btrim(bu.invited_email)) as email,
         coalesce(bu.areas, '{}') as areas
    from public.business_users bu
    join public.businesses b on b.id = bu.business_id
   where bu.status = 'active' and bu.role in ('viewer', 'member', 'manager')
     and b.type in ('church', 'ministry')
), by_write as (
  select business_id, user_id from seats where 'giving_money' = any(areas)
), by_guess as (
  select distinct s.business_id, s.user_id
    from seats s
    join public.contacts c on c.business_id = s.business_id and lower(btrim(c.email)) = s.email and s.email <> ''
    join public.church_leader_roles h on h.business_id = s.business_id and h.contact_id = c.id and h.status = 'active'
    join public.church_role_defs d on d.business_id = s.business_id and d.key = h.role
    left join public.church_area_places pr on pr.business_id = s.business_id and pr.kind = 'role' and pr.key = d.key
    left join public.church_area_places pt on pt.business_id = s.business_id and pt.kind = 'team' and pt.key = h.scope
   where not (s.areas && array['worship_media','people_care','giving_money','kids_youth','groups_classes',
                               'messages_safety','website_outreach','office'])
     and (
       pr.area = 'giving_money'
       or (d.job = 'team' and h.scope <> '' and pt.area = 'giving_money')
       or (pr.area is null and d.job not in ('kids', 'teach')
           and lower(d.title || ' ' || array_to_string(d.oversees_teams, ' '))
               ~ 'treasur|financ|\ycount|stewardship|budget|bookkeep|accountant|trustee'
           and lower(d.title || ' ' || array_to_string(d.oversees_teams, ' '))
               !~ '\yweb|social|communicat|marketing|outreach|evangel|\yevents?\y|\ydesign|newsletter|announce|media|\ytech|sound|audio|\ya/?v\y|video|camera|stream|broadcast|production|lighting|\ylights?\y|projection|slides|photo|worship|music|choir|praise|\yband\y|psalm|creative|\yarts?\y|\ykids?\y|child|youth|\yteens?\y|nursery|student|\yywd\y|\yvbs\y')
     )
)
select business_id,
       count(*) filter (where how = 'saved areas') as by_saved_areas,
       count(*) filter (where how = 'guess')       as by_guess
  from (select business_id, user_id, 'saved areas' as how from by_write
        union
        select business_id, user_id, 'guess' from by_guess
         where (business_id, user_id) not in (select business_id, user_id from by_write)) x
 group by business_id
 order by business_id;
```

No rows back means the legacy row admits nobody today.

**Run on production, 2026-11-18** (by the parent session, read-only): 0
churches, 0 logins by saved areas, 0 by guess. The legacy area row admits
nobody today, so the tick can replace it without taking anything from anyone.

**After the independent review** (no access change found; five hardening
changes, still no change in anyone's answer):

1. The ownership sweep sees the gate by its code. `ownership_sweep.HINTS`
   gains `"require_money("`; the gate's docstring no longer carries any hint
   word. `may_money` is deliberately not a hint: it refuses nothing. Measured
   on main (f859d05a) and here: 1148 handlers, 47 unguarded, 0 outside the
   public-by-design list; without the anchor it would be 68.
2. Check requests' whole rule is in the gate: the accountant counts only with
   no seat (`ACCOUNTANT_NO_SEAT`), and someone with no login gets the door's
   404, never the 503 of an unread areas view. `church_checks.treasurer` no
   longer passes an override.
3. Who owns a business is read from its row for every row-based rule (setup,
   the writers, the bills list). A `role="owner"` passed in is ignored there.
4. `giving_records.require_finance(business_id, user, need="see")`. The giving
   doors that write now ask at "work": `giving_router.create_manual_gift`,
   `.correct_manual_gift`; `giving_statement_mail.statements_mail_send`;
   `church_pledges.create_campaign`, `.edit_campaign`, `.record_pledge`,
   `.remove_pledge`; `giving_services.add_service`, `.change_service`,
   `.remove_service`, `.record_gifts`, `.move_gift`, `.close_count`,
   `.reopen_count`; `giving_sheets.upload_photo`, `.photo_used`. Same people at
   both needs today. Left at "see" because one gate serves reads and writes
   alike: Chief's count verbs (`chief_giving_counts._chief`) and Chief's
   statement verbs (`chief_giving_actions._authorize`).
5. "books" and "bank" at "see" are named THE CHURCH WALL ONLY in the table and
   the module's note. A business that isn't a church or nonprofit comes back
   `NOT_ASKED`, `may_money` raises for those two rows instead of answering,
   and `money_standing()` says which it was.
