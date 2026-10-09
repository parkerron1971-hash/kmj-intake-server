# Square connection pilot

This is the connection and read-only appointment preview foundation for businesses that already use Square Appointments. It is **disabled by default** and restricted to explicit pilot owner IDs. No booking import, Square booking write, payment access, webhook subscription, or reminder automation is enabled by this change. The connection/location/preview interface is being prepared separately for the existing Integrations page.

## Existing Square app

- App: Solutionist System
- Console: https://developer.squareup.com/console/en/apps/sq0idp-rrANPk--sCdVZlDJmZRtDg/oauth
- Production public application ID: sq0idp-rrANPk--sCdVZlDJmZRtDg
- Sandbox public application ID: sandbox-sq0idb-aDSr_m-KGVrl45amvHGwOg
- Sandbox redirect URL saved on 2026-10-08: https://kmj-intake-server-production.up.railway.app/connect/square/callback
- No application secrets or personal access tokens were copied into source, notes, or frontend settings.

## Deployment order

1. Review/merge the backend PR. Routes remain unavailable without the feature flag.
2. Apply **supabase/APPLY-2026-10-08-square-connections.sql**, then **supabase/APPLY-2026-10-09-square-locations.sql after merge**, following the repository's manual migration workflow. Together they add one service-only table and eight RPCs; it does not change existing bookings or customers.
3. Run the verification queries below. Browser roles must have no table or RPC access.
4. In Railway backend variables, set SQUARE_ENVIRONMENT=sandbox, SQUARE_SANDBOX_APPLICATION_ID, the Sandbox **Application secret from the OAuth page** as SQUARE_SANDBOX_APPLICATION_SECRET, and a newly generated Fernet key as SQUARE_TOKEN_ENCRYPTION_KEY. Do not use the personal access token on the Credentials page. Keep the encryption key backed up in the deployment secret manager; replacing it makes existing connections unreadable.
5. Set SQUARE_REDIRECT_URI to the exact saved callback URL above, SQUARE_APP_RETURN_URL=https://system.mysolutionist.app, and SQUARE_PILOT_OWNER_IDS to the authenticated test owner's auth.users UUID. An empty owner list fails closed. Finally set SQUARE_ENABLED=true for the sandbox pilot only.
6. From an authenticated client, POST /connect/square/start?business_id=<uuid>, then navigate the browser to authorize_url. Use the same browser through the callback. The short-lived handoff sets a Secure HttpOnly SameSite=Lax cookie on the backend host. Normal browser navigation is required; never exchange an authorization code from frontend JavaScript.
7. Verify status, location discovery, disconnect, and reconnect against a Square sandbox seller. Complete the live acceptance checklist before building the public connection UI or enabling production sellers.

The frontend will use authedFetch for owner endpoints and a top-level/popup navigation for authorize_url. It can refresh /square/status on return/focus. The callback shows a static success/error page with a return link; no tokens or wildcard postMessage are sent to the frontend.

## API contract

| Endpoint | Behavior |
|---|---|
| POST /connect/square/start?business_id=UUID | Owner + pilot gate; replaces previous pending attempt; returns a one-use authorize_url. Rejects an existing connected/revocation-pending account. |
| GET /connect/square/begin?ticket=... | Consumes hashed handoff, binds state to backend browser cookie, redirects to the selected Square environment. |
| GET /connect/square/callback | Claims state once, checks browser binding and current ownership, exchanges the code on the server, stores encrypted tokens. |
| GET /square/status?business_id=UUID | Owner-only safe status; booking_sync_enabled is always false in this phase. |
| GET /square/locations?business_id=UUID | Owner-only live location ID/name/status/timezone discovery and saved selection; on-demand token refresh. |
| PUT /square/locations?business_id=UUID | Save up to 20 active locations owned by the connected merchant; requires connection_id and selection_revision from the latest GET. Empty selection clears it. |
| POST /square/bookings/preview?business_id=UUID | JSON: connection_id, selection_revision, start_at and end_at (timezone-aware timestamps, end exclusive). Reads only saved locations, using <=31-day windows and cursor pagination. |
| DELETE /square/connection?business_id=UUID | Immediately disables local access and clears tokens, then revokes the Square grant. A 202 means revocation is pending; retry after 120 seconds. No reconnect until revocation completes. |

HTTP errors never echo upstream bodies. Database outages return 503 rather than pretending there is no connection. OAuth requests are omitted from access-log details and Square request events are excluded from Sentry to avoid storing codes, cookies, or token locals.

## Permissions and boundaries

Requested scopes: APPOINTMENTS_READ, APPOINTMENTS_ALL_READ, APPOINTMENTS_BUSINESS_SETTINGS_READ, CUSTOMERS_READ, ITEMS_READ, MERCHANT_PROFILE_READ. These prepare for reading a seller's existing appointments, services, customers and locations. No appointment-write, customer-write, payment or employee-directory scopes are requested.

Each merchant may connect to only one Solutionist business per environment. Sandbox and production cannot share state or tokens. State, ticket and browser secrets are stored only as hashes. Credentials use a dedicated Fernet key. All writes repeat ownership checks in the database where needed; callbacks and refreshes cannot restore a connection after disconnect. Table data is excluded from account export and cascades on business deletion.

If the token exchange succeeds but persistence fails or the merchant is already bound elsewhere, the callback refuses the connection. It deliberately does not revoke that merchant's entire grant, which would break the other business's valid connection. Check Solutionist status; an unpersisted grant can be removed from the Square seller dashboard when no valid connection relies on it. Authorization attempts expire in ten minutes and a new start invalidates older attempts.

Refresh is on demand seven days before expiry; there is no background refresh or revocation-retry worker yet. Revocation from the Square dashboard is detected on the next API call, not pushed to this pilot. An expired/invalid authorization yields a reconnect message. These are pilot limitations, not production-sync readiness.

## Verification (read-only)

~~~sql
SELECT relrowsecurity FROM pg_class WHERE oid='public.square_connections'::regclass; -- true
SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='square_connections'; -- 0
SELECT role_name,
  has_table_privilege(role_name,'public.square_connections','SELECT') AS can_read,
  has_table_privilege(role_name,'public.square_connections','INSERT,UPDATE,DELETE') AS can_write
FROM (VALUES ('anon'),('authenticated'),('service_role')) AS roles(role_name);
-- anon/authenticated: false,false; service_role: true,true
SELECT p.proname,
  has_function_privilege('anon',p.oid,'EXECUTE') AS anon_execute,
  has_function_privilege('authenticated',p.oid,'EXECUTE') AS user_execute,
  has_function_privilege('service_role',p.oid,'EXECUTE') AS service_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.proname IN
 ('square_start','square_begin','square_claim','square_finish','square_refresh','square_disconnect','square_finish_disconnect','square_save_locations');
-- eight rows; false,false,true for each
~~~

Do not SELECT credentials, ticket_hash, state_hash or browser_hash into shared logs. To roll back exposure, set SQUARE_ENABLED=false. Leave the additive schema in place; don't destroy saved connections to roll back application code. Disconnect pilot accounts before removing credentials or rotating keys.

## Validation

- Python: python -m pytest __tests__/test_square_connect.py __tests__/test_square_booking_preview.py __tests__/test_export_import.py __tests__/test_ledger_open_items.py __tests__/test_card_connections.py -q
- PostgreSQL: Set PGLITE_MODULE to the installed @electric-sql/pglite/dist/index.js path, then run node __tests__/square_connections_db.mjs. The existing CI database job installs pinned PGlite 0.5.8 and runs this check.
- The PostgreSQL harness runs in memory using a pinned PGlite development dependency. It never connects to live Supabase.
- Live acceptance still required: owner vs non-owner, allowlisted vs other owner, Square deny/success, same-browser binding, repeated callback, duplicate merchant across two businesses, location discovery, Square outage during disconnect then retry, disconnect/reconnect, and external Square grant revocation.

## Next implementation

1. Add the owner connection card and location selection, using existing responsive integration patterns. Hide the card when status.available is false.
2. Validate read scopes and booking profiles against sandbox and a consenting pilot seller. Location selection is stored now; an ACTIVE location alone does not prove bookability.
3. Build on the read-only preview to implement booking import (31-day API query windows with pagination), source identity/version fences, out-of-order-safe booking webhooks, replayable jobs, and revocation handling.
4. Map Square appointments into one canonical calendar projection. Guard native reminders, completion, billing and availability paths before exposing imported records. Square cancellation and no-show states must not become completed/paid sessions.
5. Add scheduled refresh/reconciliation, revocation retry, observability, and a production rollout gate. Customer matching must avoid automatic merges on ambiguous phone/email and must not infer marketing consent.

Official references: [OAuth overview](https://developer.squareup.com/docs/oauth-api/overview), [authorization URL](https://developer.squareup.com/docs/oauth-api/create-urls-for-square-authorization), [permissions](https://developer.squareup.com/docs/oauth-api/square-permissions), [token exchange](https://developer.squareup.com/reference/square/o-auth-api/obtain-token), [revocation](https://developer.squareup.com/reference/square/o-auth-api/revoke-token), [locations](https://developer.squareup.com/reference/square/locations-api/list-locations), [Bookings](https://developer.squareup.com/docs/bookings-api/use-the-api).

## Appointment preview contract

The preview is a bounded live read, not a snapshot or import. It requests no notes, customer details or service descriptions for display. Returned rows include appointment ID/version, time, Square status, location/timezone, all-day flag and service-duration minutes (the sum of segments, excluding intermission/transition time; never use this value as an availability block). Cancelled, declined and no-show records preserve their Square statuses; no status is converted into completed or paid.

Range: up to 93 elapsed days, explicit timezone required. Results use a half-open [start_at,end_at) interval and de-duplicate boundary rows by Square ID/version. Limits: 20 locations, 20 booking-page requests, 200 displayed appointments, 45-second endpoint deadline. If the row/page limit is reached, truncated=true and shown_count describes only displayed rows; the frontend must ask for a narrower range rather than show a full total. Provider failure returns an error, never an empty-success preview.

A stable connection_id changes on connect/disconnect; selection_revision changes on every saved selection. Both are checked before preview/save and again after loading. A concurrent disconnect or location change invalidates the result. Token refresh only rotates its separate credential revision and cannot invalidate a saved location list. Disconnect clears selections. Reselect after reconnect.

The second migration adds these three columns and the service-only square_save_locations RPC, and updates the existing connect/disconnect transactions. Both migrations are replay-tested; apply them in order. Verify connection_id, selected_location_ids and selection_revision exist using information_schema.columns; do not print connection credentials.
