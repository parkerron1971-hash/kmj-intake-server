-- APPLY-2026-07-28-site-events.sql
-- First-party, anonymous traffic analytics for mysolutionist.app.
--
-- WHY THIS SHAPE: the columns below are chosen so the table cannot
-- identify a person. There is deliberately NO ip address, NO user-agent
-- string, and NO cookie. session_id is a random value held in
-- sessionStorage that dies when the tab closes, so it cannot follow a
-- visitor across visits or across sites. referrer_host stores the HOST
-- only, never the full URL, because full referrer URLs routinely carry
-- search terms and other personal data in their query strings.
--
-- That is what lets this run without a cookie-consent banner. If anyone
-- ever adds an ip/user-agent column, that stops being true and the
-- privacy policy + a consent banner both have to change.

create table if not exists public.site_events (
  id            bigserial   primary key,
  ts            timestamptz not null default now(),
  session_id    text        not null,
  path          text        not null,
  referrer_host text,
  device        text,
  event         text        not null default 'view'
);

comment on table  public.site_events         is 'Anonymous marketing-site traffic. No IP, no user agent, no cookies — see APPLY-2026-07-28-site-events.sql.';
comment on column public.site_events.session_id    is 'Random, sessionStorage-scoped. Dies with the tab. Not a cookie, not cross-site.';
comment on column public.site_events.referrer_host is 'Host only. Never the full URL — query strings leak search terms.';

create index if not exists site_events_ts_idx      on public.site_events (ts desc);
create index if not exists site_events_session_idx on public.site_events (session_id);
create index if not exists site_events_path_idx    on public.site_events (path);

-- Locked down. No policies are defined on purpose: anon and authenticated
-- roles get nothing at all. Only the backend's service-role key (which
-- bypasses RLS) reads or writes this table, so the browser can never
-- query raw traffic rows.
alter table public.site_events enable row level security;
