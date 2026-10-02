-- Member portal sign-in codes (member_portal.py). Service role only: the
-- backend stores an HMAC of each code, never the code. Idempotent.
begin;
create table if not exists public.member_login_codes(
 id uuid primary key default gen_random_uuid(),
 business_id uuid not null references public.businesses(id) on delete cascade,
 email text not null check (email = lower(btrim(email))),
 code_hash text not null,
 expires_at timestamptz not null,
 attempts int not null default 0 check (attempts >= 0),
 consumed_at timestamptz,
 succeeded boolean not null default false,
 created_at timestamptz not null default now());
alter table public.member_login_codes enable row level security;
revoke all on public.member_login_codes from anon, authenticated;
grant all on public.member_login_codes to service_role;
alter table public.member_login_codes add column if not exists succeeded boolean not null default false;
create index if not exists member_login_codes_lookup
 on public.member_login_codes(business_id, email, created_at desc);
commit;
