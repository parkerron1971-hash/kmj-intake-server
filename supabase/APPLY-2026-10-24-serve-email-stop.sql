-- ChurchSavvy Planning by email (design canvas UZu4VsoY9KemkUGorz234j,
-- board 12 "The ask, by email": "Stop these emails works in one tap").
-- Server-only, like the rest of serve_*.
--
--   serve_prefs.email_stopped_at   when someone used "Stop these emails" in
--                                  a serving email from this church. While
--                                  it's set, no serving email reaches them,
--                                  not even an ask their phone missed. Turning
--                                  the email copy back on clears it.
-- Idempotent.
begin;

alter table public.serve_prefs add column if not exists email_stopped_at timestamptz;

commit;
