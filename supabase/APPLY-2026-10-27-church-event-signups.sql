-- Paid sign-ups for church events, with a waitlist (church_event_signups.py;
-- Kevin approved the build list on the Church Menu Gaps check and said "ok
-- continue" on 2026-10-27: RSVP had capacity and volunteer roles, but no
-- payment and no waitlist. Planning Center Registrations and Subsplash
-- event payments are the bar). Three tables and three functions, all
-- server-only: RLS on, no policies, the browser's roles revoked.
--
--   church_event_signup_setups   one per event (a Services & Events entry):
--                                open, places, a sign-up deadline, the
--                                questions, the waitlist and how long an
--                                offer lasts, what to bring
--   church_event_ticket_types    what a place costs: Adult $25, Child $10,
--                                Family $60 (4 places). A price may be $0
--   church_event_registrations   one person's sign-up for one event, and the
--                                waitlist (status waiting / offered):
--
--     held       a place kept while they pay (hold_expires_at)
--     paid       Stripe's verified webhook said so; nothing else sets it
--     confirmed  a free sign-up (nothing to pay)
--     waiting    on the waitlist, in created_at order
--     offered    a place opened for them: a link to pay before
--                hold_expires_at (the link's hash is claim_hash)
--     expired    a hold or an offer that ran out; the place went back
--     cancelled  the office took it off
--     refunded   refunded in full in Stripe; the place went back
--
-- A place is taken by paid and confirmed sign-ups and by holds and offers
-- that haven't run out. Who gets a place is decided in ONE locked step per
-- event (church_event_take / church_event_settle lock the event's setup
-- row), so two people pressing at once for the last place can't both get
-- it, and the waitlist is strictly first come, first served.
--
-- A registration keeps the event's id and title but no foreign key to it:
-- a paid sign-up is a payment record and outlives the event's entry.
-- Idempotent.
begin;

create table if not exists public.church_event_signup_setups(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  entry_id uuid not null references public.module_entries(id) on delete cascade,
  open boolean not null default true,
  capacity int check (capacity is null or capacity between 1 and 100000),
  deadline timestamptz,
  questions jsonb not null default '[]'::jsonb check (jsonb_typeof(questions) = 'array'),
  waitlist boolean not null default true,
  offer_hours int not null default 24 check (offer_hours between 2 and 72),
  bring text not null default '' check (char_length(bring) <= 500),
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, entry_id),
  unique (business_id, id)
);

create table if not exists public.church_event_ticket_types(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  setup_id uuid not null,
  label text not null check (char_length(label) between 1 and 60),
  price_cents int not null check (price_cents between 0 and 1000000),
  seats int not null default 1 check (seats between 1 and 20),
  max_per_signup int check (max_per_signup is null or max_per_signup between 1 and 20),
  active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_event_ticket_types_setup foreign key (business_id, setup_id)
    references public.church_event_signup_setups(business_id, id) on delete cascade
);

create table if not exists public.church_event_registrations(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  entry_id uuid not null,
  event_title text not null default '' check (char_length(event_title) <= 200),
  contact_id uuid references public.contacts(id) on delete set null,
  name text not null check (char_length(name) between 1 and 120),
  email text not null check (char_length(email) between 3 and 200),
  phone text check (phone is null or char_length(phone) <= 40),
  texts_ok boolean not null default false,
  tickets jsonb not null default '[]'::jsonb check (jsonb_typeof(tickets) = 'array'),
  seats int not null check (seats between 1 and 100),
  amount_cents int not null check (amount_cents between 0 and 2500000),
  answers jsonb not null default '{}'::jsonb check (jsonb_typeof(answers) = 'object'),
  status text not null check (status in
    ('held', 'paid', 'confirmed', 'waiting', 'offered', 'expired', 'cancelled', 'refunded')),
  hold_expires_at timestamptz,
  claim_hash text,
  offered_at timestamptz,
  paid_at timestamptz,
  refunded_cents int not null default 0 check (refunded_cents >= 0),
  refunded_at timestamptz,
  stripe_session_id text,
  stripe_payment_intent text,
  stripe_account_id text,
  checkout_url text,
  source text not null default 'public' check (source in ('public', 'member', 'office')),
  request_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, request_key),
  constraint church_event_registrations_hold check
    (status not in ('held', 'offered') or hold_expires_at is not null)
);

create index if not exists church_event_setups_entry
  on public.church_event_signup_setups(business_id, entry_id);
create index if not exists church_event_ticket_types_setup
  on public.church_event_ticket_types(setup_id, sort_order);
create index if not exists church_event_registrations_event
  on public.church_event_registrations(business_id, entry_id, status, created_at);
create index if not exists church_event_registrations_running_out
  on public.church_event_registrations(hold_expires_at) where status in ('held', 'offered');
create unique index if not exists church_event_registrations_claim
  on public.church_event_registrations(claim_hash) where claim_hash is not null;
create index if not exists church_event_registrations_session
  on public.church_event_registrations(stripe_session_id) where stripe_session_id is not null;

alter table public.church_event_signup_setups enable row level security;
alter table public.church_event_ticket_types enable row level security;
alter table public.church_event_registrations enable row level security;
revoke all on public.church_event_signup_setups from anon, authenticated;
revoke all on public.church_event_ticket_types from anon, authenticated;
revoke all on public.church_event_registrations from anon, authenticated;
grant all on public.church_event_signup_setups to service_role;
grant all on public.church_event_ticket_types to service_role;
grant all on public.church_event_registrations to service_role;

-- Places taken right now: paid and free sign-ups, and holds and offers
-- that haven't run out.
create or replace function public.church_event_taken(p_business uuid, p_entry uuid)
returns int language sql stable set search_path to 'public', 'pg_temp' as $$
  select coalesce(sum(seats), 0)::int from public.church_event_registrations
  where business_id = p_business and entry_id = p_entry
    and (status in ('paid', 'confirmed')
         or (status in ('held', 'offered') and hold_expires_at > now()))
$$;
revoke all on function public.church_event_taken(uuid, uuid) from public, anon, authenticated;
grant execute on function public.church_event_taken(uuid, uuid) to service_role;

-- Holds and offers that ran out give their places back; then the waitlist
-- moves, first come first served, while the person at the front fits. A
-- free place is theirs at once (confirmed); a paid one is offered with a
-- link for offer_hours. Returns the people just offered or confirmed, with
-- each one's link (only its hash is kept), for the server to tell them.
-- The caller holds the setup row's lock.
create or replace function public.church_event_move(s public.church_event_signup_setups)
returns jsonb language plpgsql set search_path to 'public', 'pg_temp' as $$
declare taken int; w public.church_event_registrations; token text; out jsonb := '[]'::jsonb;
begin
  update public.church_event_registrations set status = 'expired', updated_at = now()
   where business_id = s.business_id and entry_id = s.entry_id
     and status in ('held', 'offered') and hold_expires_at <= now();
  if not s.open then
    return out;
  end if;
  loop
    taken := public.church_event_taken(s.business_id, s.entry_id);
    select * into w from public.church_event_registrations
     where business_id = s.business_id and entry_id = s.entry_id and status = 'waiting'
     order by created_at, id limit 1;
    exit when not found;
    exit when s.capacity is not null and taken + w.seats > s.capacity;
    if w.amount_cents = 0 then
      update public.church_event_registrations
         set status = 'confirmed', offered_at = now(), hold_expires_at = null, updated_at = now()
       where id = w.id;
      token := null;
    else
      token := replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '');
      update public.church_event_registrations
         set status = 'offered', offered_at = now(),
             hold_expires_at = now() + make_interval(hours => s.offer_hours),
             claim_hash = encode(sha256(convert_to(token, 'UTF8')), 'hex'), updated_at = now()
       where id = w.id;
    end if;
    out := out || jsonb_build_object(
      'id', w.id, 'status', case when token is null then 'confirmed' else 'offered' end,
      'token', token, 'name', w.name, 'email', w.email, 'phone', w.phone, 'texts_ok', w.texts_ok,
      'amount_cents', w.amount_cents, 'seats', w.seats, 'tickets', w.tickets,
      'hold_expires_at', case when token is null then null else now() + make_interval(hours => s.offer_hours) end);
  end loop;
  return out;
end $$;
revoke all on function public.church_event_move(public.church_event_signup_setups) from public, anon, authenticated;
grant execute on function public.church_event_move(public.church_event_signup_setups) to service_role;

-- One sign-up, decided under the event's lock. p_row: name, email, phone,
-- texts_ok, tickets, seats, amount_cents (the server priced it), answers,
-- source, request_key, contact_id, event_title. state:
--   held       a place is kept for p_hold_minutes while they pay
--   confirmed  a free place, theirs
--   waiting    full, and they joined the waitlist (position)
--   full       full; waitlist says whether they may join it
--   closed     sign-ups are closed or past the deadline
--   already    this request_key was already taken (the same press twice)
-- offers: the waitlist people this step moved (see church_event_move).
create or replace function public.church_event_take(
  p_business uuid, p_entry uuid, p_row jsonb, p_waitlist boolean, p_hold_minutes int)
returns jsonb language plpgsql set search_path to 'public', 'pg_temp' as $$
declare s public.church_event_signup_setups; r public.church_event_registrations;
        offers jsonb; taken int; seats int; queued int; amount int;
begin
  select * into s from public.church_event_signup_setups
   where business_id = p_business and entry_id = p_entry for update;
  if not found then
    return jsonb_build_object('state', 'closed', 'why', 'none');
  end if;
  if p_row->>'request_key' is not null then
    select * into r from public.church_event_registrations
     where business_id = p_business and request_key = p_row->>'request_key';
    if found then
      return jsonb_build_object('state', 'already', 'id', r.id, 'status', r.status,
        'checkout_url', r.checkout_url, 'hold_expires_at', r.hold_expires_at, 'offers', '[]'::jsonb);
    end if;
  end if;
  offers := public.church_event_move(s);
  if not s.open or (s.deadline is not null and s.deadline <= now()) then
    return jsonb_build_object('state', 'closed', 'why', case when s.open then 'deadline' else 'closed' end,
                              'offers', offers);
  end if;
  seats := (p_row->>'seats')::int;
  amount := (p_row->>'amount_cents')::int;
  taken := public.church_event_taken(p_business, p_entry);
  select count(*) into queued from public.church_event_registrations
   where business_id = p_business and entry_id = p_entry and status = 'waiting';
  if queued = 0 and (s.capacity is null or taken + seats <= s.capacity) then
    insert into public.church_event_registrations(
      business_id, entry_id, event_title, contact_id, name, email, phone, texts_ok, tickets, seats,
      amount_cents, answers, status, hold_expires_at, source, request_key)
    values (p_business, p_entry, coalesce(p_row->>'event_title', ''), (p_row->>'contact_id')::uuid,
      p_row->>'name', p_row->>'email', p_row->>'phone', coalesce((p_row->>'texts_ok')::boolean, false),
      coalesce(p_row->'tickets', '[]'::jsonb), seats, amount, coalesce(p_row->'answers', '{}'::jsonb),
      case when amount = 0 then 'confirmed' else 'held' end,
      case when amount = 0 then null else now() + make_interval(mins => p_hold_minutes) end,
      coalesce(p_row->>'source', 'public'), p_row->>'request_key')
    returning * into r;
    return jsonb_build_object('state', r.status, 'id', r.id, 'hold_expires_at', r.hold_expires_at,
                              'offers', offers);
  end if;
  if not (p_waitlist and s.waitlist) then
    return jsonb_build_object('state', 'full', 'waitlist', s.waitlist, 'offers', offers);
  end if;
  insert into public.church_event_registrations(
    business_id, entry_id, event_title, contact_id, name, email, phone, texts_ok, tickets, seats,
    amount_cents, answers, status, source, request_key)
  values (p_business, p_entry, coalesce(p_row->>'event_title', ''), (p_row->>'contact_id')::uuid,
    p_row->>'name', p_row->>'email', p_row->>'phone', coalesce((p_row->>'texts_ok')::boolean, false),
    coalesce(p_row->'tickets', '[]'::jsonb), seats, amount, coalesce(p_row->'answers', '{}'::jsonb),
    'waiting', coalesce(p_row->>'source', 'public'), p_row->>'request_key')
  returning * into r;
  return jsonb_build_object('state', 'waiting', 'id', r.id, 'position', queued + 1, 'offers', offers);
end $$;
revoke all on function public.church_event_take(uuid, uuid, jsonb, boolean, int) from public, anon, authenticated;
grant execute on function public.church_event_take(uuid, uuid, jsonb, boolean, int) to service_role;

-- Give back what ran out and move the waitlist, under the event's lock (the
-- sweep, a refund, the office cancelling or opening more places).
create or replace function public.church_event_settle(p_business uuid, p_entry uuid)
returns jsonb language plpgsql set search_path to 'public', 'pg_temp' as $$
declare s public.church_event_signup_setups;
begin
  select * into s from public.church_event_signup_setups
   where business_id = p_business and entry_id = p_entry for update;
  if not found then
    return jsonb_build_object('offers', '[]'::jsonb);
  end if;
  return jsonb_build_object('offers', public.church_event_move(s));
end $$;
revoke all on function public.church_event_settle(uuid, uuid) from public, anon, authenticated;
grant execute on function public.church_event_settle(uuid, uuid) to service_role;

commit;
