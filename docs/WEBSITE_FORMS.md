# Website contact submissions

POST /sites/{business_id}/contact-submit accepts JSON. Existing sites can keep
sending name, email, message, optional phone and sms_consent unchanged.

Optional form values connect_card and prayer_request (also connect-card and
prayer-request for older church pages) select the church paths. Both accept an
optional fields object; unknown structured fields are rejected rather than lost.
Name and email remain required. A plain submission requires message. Structured
cards can omit message; structured prayer requests require fields.request.
A legacy church form with no fields retains its entire message.

## Limits

Lengths count Unicode characters before trimming surrounding whitespace.
Over-limit or incorrectly typed answers return HTTP 400 with ok:false and a
field-specific error. No message or structured answer is silently shortened.

| Field | Limit |
| --- | --- |
| name, email | 200 characters each |
| phone | 40 characters |
| message | 5,000 characters |
| form | 80 characters |
| fields.first_name, fields.last_name | 90 characters each |
| Connect: fields.visits | 120 characters |
| Connect: fields.heard_from | 200 characters |
| Connect: fields.notes | 2,500 characters |
| Connect: fields.interests | List of up to 20 strings, 120 characters each |
| Prayer: fields.request | 4,000 characters |
| Prayer: fields.follow_up | Boolean; requests personal follow-up only |

## Storage and privacy

Connect cards use contacts (shown as Members for ministry businesses), deduped
within the business using the existing email/phone/name identity rules. New
records use source "website connect card". Existing status, consent and office
metadata are preserved. Full answers and the original phone are kept in
metadata.website_form_messages; latest structured answers also live in
metadata.website_connect_card. Phone is normalized into the contact column when
possible. Messages are never evicted. Updates use updated_at compare-and-swap,
retrying up to three times so concurrent submissions do not overwrite messages.
Concurrent first-time visitors may still produce duplicate contacts because the
existing schema deliberately permits shared household email addresses.

Prayer requests use the existing ministry_care_requests table, visible through
the owner-only Prayer & care endpoint. They do not create/update contacts, record
SMS consent, capture attribution, emit lead events, score leads, enter marketing
or autopilot, or send visitor auto-replies. Connect cards also skip lead scoring
and automatic lead events. No database migration is needed.

Church notification recipients come exclusively from the business's verified
sending settings. Public email overrides and platform fallback addresses are
never used for these notifications. Plain contact forms keep their existing
server-side recipient rules. The visitor cannot choose a recipient.

## Responses

- HTTP 200, {"ok":true,"notification_sent":true}: durably stored, notification accepted.
- HTTP 200, {"ok":true,"notification_sent":false}: durably stored, notification unavailable
  or failed. Do not ask the visitor to resend; the church can read it in Solutionist.
- HTTP 400, {"ok":false,"error":"..."}: invalid or over-limit answer; nothing saved.
- HTTP 429, {"ok":false,"error":"..."}: rate limited; nothing saved.
- HTTP 503, {"ok":false,"error":"..."}: storage failed or could not be confirmed.

The existing per-IP limit is five attempts per minute. Storage is confirmed from
the database write result before any notification. Optional lead processing for
plain contact forms cannot turn a saved submission into a failed response.
