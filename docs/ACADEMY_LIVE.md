# Native live classes on Railway

The existing Python backend owns LiveKit access and controls. Supabase stores
the class data and enforces enrollment/teaching permissions. LiveKit carries media.

## Activation

1. Apply `supabase/APPLY-2026-09-09-academy-live.sql` after the existing
   September 8 academy-school migration (already recorded in `MIGRATIONS.md`).
2. In this Railway service, set `LIVEKIT_URL` (`wss://...`), `LIVEKIT_API_KEY`,
   and `LIVEKIT_API_SECRET`. Reuse `SUPABASE_URL`, `SUPABASE_ANON`, and
   `SUPABASE_SERVICE_ROLE_KEY`. Never prefix secrets with `VITE_`.
3. Release this backend normally. It adds `livekit-api==1.1.0` and mounts
   `academy_live_router.router` before the public-site catch-all.
4. Register this URL in LiveKit with the same API key:

   `https://kmj-intake-server-production.up.railway.app/academy-live/webhook`

   Deliver participant_joined, participant_left, and room_finished events.
5. Release the frontend's Live classes feature. It posts to `/academy-live`.
   No Supabase Edge Functions or separate Railway service are needed.
6. Verify a published test course with teacher/student browser profiles: start,
   join, camera/mic, screen sharing, chat, hand raising, invite/listen/remove,
   ending, and attendance. Media has not been tested with real credentials yet.

`POST /academy-live` with `{"action":"status"}` reports configuration and table
availability without minting a token or creating a room. It does not validate
provider credentials or webhook setup. A missing table disables joining.

## Security

Requests are limited to 4 KB, webhooks to 256 KB, and join tokens to 60 seconds.
The access RPC uses the caller's JWT (verified by PostgREST) or the anon role with
an enrollment token, never service-role identity. Portal links always select a
student identity, even with a teacher JWT. The RPC checks course/business scope,
confirmed teaching assignments, active/completed enrollment, publication and blocks.

Only then may Railway use service role for session/participant writes. Targets
must belong to the same business and course. Only teachers may start/end/moderate;
student grants exclude screen sharing. No client receives room-admin permissions.
Moderation persists across reconnects. Ending denies new join requests before room
deletion; failed deletion can be retried even after the session is marked ended.

Webhooks fail closed on missing keys, invalid signatures or changed bodies. The
attendance RPC handles repeated/out-of-order participant events. Database failures
return 500 for provider retries. Bodies/credentials are not logged by the router;
the Sentry scrubber excludes live endpoint request data and headers.

Default capacity is 30, maximum 100 including teachers. Project quotas are shared.
Recording, replay, reminders, and per-school usage billing are not included.

## Tests

`python -m pytest -q __tests__/test_academy_live.py`

Tests use synthetic data and mocked DB/provider calls with real SDK token and
webhook verification. No provider rooms or live database writes are made.
Frontend database tests exercise the actual migration under PGlite.
