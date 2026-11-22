# An event's sign-up link

Kevin, 2026-11-22:

> "when the event is made there is no way for someone to sign up with a link
> if there don't have the church app. can we fix this issue?"

The mock (https://claude.ai/artifact/HmdpXJJNgzKefxW5qoAF5e, four screens and
"Your calls") was approved with **"yes to both"** the same day, with the picks
as written there. He had also said yes to the two earlier offers: an Events
line on the office's Serving page and a field for an event's helper time.

This builds on `docs/EVENT_VOLUNTEERS.md` (the event's special roles, 6.10;
hours, 6.6; the flyer, 6.12). Section 10 here holds the decisions made while
building.

## 1. In one paragraph

Every Services & Events entry gets **one sign-up link** the office can copy,
show as a QR code, text, email or post. Whoever opens it sees that one event
(its flyer, day, time and place, and the roles it still needs) and signs up
with a name and a phone number or an email, with no app and no sign-in. The
sign-up lands on the event like any other, marked **by link**. It earns
serving hours only after the office says who the person is. "Make a new link"
stops the old one working.

## 2. Kevin's calls (2026-11-22, "yes to both")

1. **Roles.** A link takes every role that isn't a kids role. The public
   events page keeps showing only roles that aren't `open: false`
   (`events_rsvp_router.public_role`), as decided on 11-20.
2. **Hours.** A link sign-up counts nothing until the office confirms who it
   is ("That's someone on Members", or "Add to Members").
3. **Confirmation.** The page says "You're on the list" with the day, time and
   place, and an email goes out when they gave one. **No text** (section 7).
4. **Serving page.** An Events column (count and hours) on each person's row,
   and "Helpers serve about" on each event (`_serve_minutes`, 30 minutes to 12
   hours, 2 hours unless changed). Past events keep counting 2 hours each.

## 3. The data: no migration

### 3.1 The link: `module_entries.data._link`

```
_link: {"n": "<32 lowercase hex>", "at": "<iso time it was made>"}
```

`n` is a random nonce (128 bits, `secrets.token_hex(16)`). The **code** in the
link is never stored anywhere:

```
key  = customer_token.derive_key("event-signup-link", business_id)   # HKDF from CUSTOMER_TOKEN_SECRET
code = base32(HMAC-SHA256(key, "<entry_id>|<n>")) lowercased, first 26 characters   (130 bits)
link = https://<slug>.mysolutionist.app/e/<code>
```

- **Unguessable**: 130 bits from a keyed hash.
- **Never derivable from the entry id alone**, nor from the entry's data: both
  are inputs, but the key lives only on the server.
- **Make a new link** writes a new `n`. The old code no longer matches
  anything, so it is a 404 at once.
- **Every read validates it**: `n` must be exactly 32 lowercase hex characters
  and `at` a string; anything else is no link (the office's Get makes a fresh
  one).
- **Checking a code**: the code's shape first (26 of `a-z2-7`, else a 404 with
  no read). Then each active entry of the church's active events rooms that
  carries a valid `_link` has its code worked out and compared with
  `hmac.compare_digest`, every one of them, with no early exit.

**Why the entry's data and not a server-only table.** Office logins read and
write `module_entries` from the browser (every seat reads, Member and up
write: `APPLY-2026-07-31-seat-access-data-plane.sql`).
- *Read*: a login reading the entry sees `n`, never the code. The code needs
  the server's key. So the row gives nothing to anyone, and the office's own
  route is the only way to the link.
- *Forge*: a login that writes the entry could put any `n` there. That only
  makes a new link, with a code it still can't work out without asking the
  server, which hands the link only to office logins (the same people). It is
  what "Make a new link" does, and that login can already add anyone to a
  role by name, which is more than a link lets a visitor do.
- *Resurrect*: a stale browser save carrying an old `n` would bring a voided
  link back. Every office save of an event carries the row's `updated_at`
  (`event_roster/internal.tsx`), and `zz_module_revision` moves it on every
  write, so a save made before "Make a new link" is refused. The office app
  must keep `_link` byte for byte, like every other key.
- Rotating `CUSTOMER_TOKEN_SECRET` ends every link (and every booking link
  already). With it unset, the routes answer 503 "Sign-up links aren't ready
  here yet." and nothing breaks.

A table would need a migration Kevin applies by hand, and buys nothing the
keyed code doesn't: nothing in the row is the secret.

### 3.2 A sign-up by link

Appended to the entry's signups list, the shape every reader already reads:

```
{sid, name, status: "yes", via: "link", role?, phone? | email?, at}
```

- `sid`: 16 random hex characters, so the office can act on this one sign-up.
- `phone` (E.164) or `email` (lowercase): what they typed, normalized. Never
  matched to a contact at sign-up: **`contact_id` is never set from typed
  data.**
- "Just coming" has no `role`, like the public page's.
- Confirmed by the office: `contact_id`, `confirmed: true`, `confirmed_by`,
  `confirmed_at`, and `name` becomes the person's name on Members (what they
  typed stays in `typed_name`).

### 3.3 `_serve_minutes`

Unchanged on the server (`event_volunteers._minutes`, held to 15 to 720,
default 120). The office's "Helpers serve about" field writes 30 to 720.

## 4. The switch

`EVENT_SIGNUP_LINKS = off | owner | on`, default **owner**: the platform
owner's own church only (`member_asks.platform_church`, read from the church,
never from who is signed in). It opens only where EVENT_VOLUNTEERS is open
too (`event_volunteers.open_for`). A typo reads as off.

- **It gates**: the link page and its sign-up, and every office route here.
  Closed, they are the same 404 as a wrong code; the status route says
  `enabled: false`.
- **It never hides**: sign-ups already made, and their hours once confirmed.
- The Events column and the helper time ride EVENT_VOLUNTEERS (on).
- **Rollback**: `EVENT_SIGNUP_LINKS=off` on kmj-intake-server.

## 5. Who may do what

| who | get the link | make a new link | confirm, add to Members, remove a sign-up | see a sign-up's phone or email |
|---|---|---|---|---|
| Owner, Admin, Manager, office Member login (`event_volunteers._login`) | yes (made if missing) | yes | yes; Add to Members also needs the roll's own gate | yes |
| Viewer | only one already made | no (403) | no (403) | no |
| Member app, anyone else | no | no | no | no |
| Whoever has the link | signs up | no | no | no (counts only, never names) |

"Add to Members" goes through `church_roll_edit.add_people`, behind the roll's
gate (`church_roll._areas_ok`, a Manager and up, CHURCH_ROLL_EDIT open), as a
guest who found us at an event. Nothing automatic ever makes someone a member.

## 6. Rules

### 6.1 The link's page: `GET https://<church host>/e/<code>`

The church's subdomain and its own domain alike, served by `public_site`
before the site's offline and coming-soon checks (it is a sign-up, not the
website).

- Shows: the church's name and logo, the flyer (`flyer_of`), the title, day
  and time on the church's clock, the place, then "How would you like to
  help?": each role open by link with how many are still needed, or "Full";
  a kids role reads "Ask the office about this one" with nothing to pick;
  "Just coming". Then the name, "Phone or email", and Sign me up.
- **Never another person's name.** Counts only.
- The church's public theme (`public_form_theme`), phone-first, like `/events`.
- `noindex, nofollow` (the meta tag and `X-Robots-Tag`), `Referrer-Policy:
  strict-origin` (the code never leaves in a Referer), no-store.
- **Not taking sign-ups** (one plain page, status 404, the same words and
  bytes for each): a code that doesn't match, a sample church, the switch
  closed, an event archived, deleted, in a room that's off, or already past
  (its start time passed; a bare date, once that day is over). A wrong code
  can't be told from a real one that ended.
- "Just coming" isn't offered when the event is full (its capacity), or when
  it takes sign-ups (`church_event_signups.blocks_free_rsvp`: those go through
  the events page). Roles still work.

### 6.2 Signing up: `POST /public/event-link/{slug}`

`{code, name, reach, role?, website?}`. The code is in the body, never the
address, so it stays out of request logs.

1. The public RSVP's rate limit first (`events_rsvp_router._check_rsvp_rate`,
   10 a minute an address), before any read.
2. `website` is the honeypot (hidden from people). Filled, the answer is the
   ordinary success and nothing is written or sent.
3. `name` 1 to 120 characters: "Please tell us your name." `reach`: an email
   (`church_roll_edit.EMAIL_RE`, lowercased) when it has an @, else a phone
   (7 to 15 digits; ten digits are +1, eleven starting with 1 get a +, a +
   keeps its digits): "Add a phone number or an email so the church can
   reach you." / "That email doesn't look right." / "That phone number
   doesn't look right."
4. The church from its slug; a sample church, a closed switch, a wrong code
   and an event not taking sign-ups are all the same 404: "This event isn't
   taking sign-ups."
5. The role: unknown is a 400 "Pick one of the ways to help on the page.";
   **a kids role is a 403 "Ask the office about this one."**, whatever was
   posted; full is a 409 "{Role} just filled up." from the church's own data.
   No role on an event that's full is a 409 "This event is full."; on one
   that takes sign-ups, a 409 "This event takes sign-ups on the church's
   events page."
6. Already on the list (a link sign-up with the same phone or email, or the
   public page's registration for that email): the same success, with
   nothing written and no second email.
7. The write: a read-modify-write of `data` as the server, guarded by
   `updated_at`, tried five times.
8. The email (section 7) when they gave one.
9. The answer: `{ok, role, when, place, emailed}`; the page says "You're on
   the list." with the role or "Coming", the day and time, the place, and
   "We sent the details to {email}." when one went.

### 6.3 The office routes (`/church/event-links`)

Every one: `require_user`, then `event_volunteers._login` (an office login of
a church whose teams have owners, the church checked by
`business_access.assert_access`, independent of RLS), then the switch (404),
then the event must be one of this church's (`event_volunteers.event_entry`,
else 404). Writes refuse a Viewer (`event_volunteers._ask_gate`, 403). Ids are
parsed as UUIDs before they reach an address; every value is quoted.

| method | path | does |
|---|---|---|
| GET | `/status?business_id=` | `{enabled}`: links are open here for this login |
| GET | `/{entry_id}?business_id=` | the link (made if missing, unless a Viewer), `made_at`, `visibility`, `page_url` for a public event (`/events?event=<id>`), and the event's link sign-ups |
| POST | `/{entry_id}/new` `{business_id}` | a new `n`: the old link stops working |
| POST | `/{entry_id}/signups/{sid}/confirm` `{business_id, contact_id}` | set `contact_id` to a person on THIS church's Members (not merged away), and confirm it |
| POST | `/{entry_id}/signups/{sid}/add` `{business_id}` | add them to Members (guest, found us at an event) through `church_roll_edit.add_people`, then confirm |
| DELETE | `/{entry_id}/signups/{sid}?business_id=` | take this sign-up off the event |

The sign-ups list: `{sid, name, role_id, role, at, confirmed, contact_id?}`;
for a login that isn't a Viewer also `phone`/`email`, and, while
unconfirmed, `maybe: {contact_id, name}` when that phone or email is already
on Members (a hint for the office, never written).

Write answers carry the whole new `data` and `updated_at`, so the office
saves on top of them.

### 6.4 The public events page

`/events?event=<id>` shows **only that event**, with its flyer and its card,
and a link to everything coming up. Its rules are the public page's (public
events only, `public_role` roles, an email). An id that isn't a public event
coming up shows the whole list, as before, so it says nothing about other
events.

### 6.5 Hours

`church_serving.event_credits` counts a `via: "link"` sign-up only when
`confirmed` is true (and, as for everyone, `contact_id` set, a yes, a role of
the event). A confirmed link sign-up is the office's word, so it skips the
public-registration check. Nothing else changes: public sign-ups still never
count.

### 6.6 The Serving page and My serving

The Serving page's people already carry `events` and `event_minutes`. My
serving gains `event_minutes` beside `events`.

## 7. Notices

- **Email**: when they gave one, once, through the church's own sender
  (`church_event_signups._send_email`: `send_via_resend` from the church's
  name and verified domain, with its suppression list and the sample church's
  refusal; Resend is a flat cost, nothing is metered per send). Idempotency
  key `evlink-{entry}-{sid}`. "You're on the list for {title}", the role, the
  day and time and the place, and "If anything changes, {church} will be in
  touch."
- **No text.** The only church texts to someone who didn't sign in go to a
  person who ticked "text me" on a paid sign-up, under that event's own
  consent. A phone typed on this page is not consent to texts, and adding a
  new opt-in would change what the church's texting registration describes.
  Texts are left for later (section 9).
- The office isn't told of each sign-up (forty sign-ups must not be forty
  pings, as for the public page); they show on the event.

## 8. Tests

`__tests__/test_event_signup_links.py`: codes (unguessable, void after a new
link, compared in constant time, a wrong code the same 404 as a missing
event); church-only and invite events only by code, a public one by its page
too; kids roles refused; a full role; name and phone-or-email; `via: "link"`
and no contact from typed data; no hours until confirmed, then counted;
confirm only with this church's person; every office route's gate (Viewer,
another church, signed out); the switch off, owner and on; a sample church;
the rate limit; no other names; `noindex`; the email once.

## 9. Left for later

- A text to confirm, once the church's texting has a consent step for it.
- Matching a link sign-up to Members automatically (Kevin's call 2: the
  office confirms).
- A count of link sign-ups in the office's Today.

## 10. Decisions made while building

- **Every event's office link is the coded `/e/<code>`, public events
  included.** A public event's own page (`/events?event=<id>`) shows only that
  event now, but it follows the public page's rules. Entry ids are printed on
  the public list, so if that page took every role, `open: false` would mean
  nothing (call 1 keeps it). The office gets both for a public event: the link
  and the page.
- The link is on the church's subdomain, which always answers, even for a
  church with its own domain.
- The page is served before the site's offline and coming-soon checks: taking
  the website down to work on it shouldn't stop people signing up.
