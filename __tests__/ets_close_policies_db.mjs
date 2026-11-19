// Closing the Embrace the Shift tables, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-19-close-ets-policies.sql and its rollback, over
// the ten ets_* tables with the policies, grants and triggers production
// showed on 2026-11-19.
//
// 1. BEFORE, the hole as production has it: the public key reads every
//    inquiry, email and virtual link, deletes events, any login uploads to
//    the bucket, and the live site's own calls work (select "*" on events,
//    INSERT ... RETURNING id, reading the registrations table).
// 2. The file's own "Check before applying" queries run as written and say
//    what the file says they say. Then the file runs twice.
// 3. THE PUBLIC SITE (anon), after: the events list and the event page with
//    exactly the columns the new site build asks for, tiers and files
//    nested (published and sold out only; no draft, cancelled or hidden
//    tier); the virtual link and "*" on events refused; an inquiry and a
//    free registration go in the way the new site sends them (no row asked
//    back, as PostgREST's return=minimal does it), and the live site's
//    INSERT ... RETURNING is refused. A confirmed paid registration, a wrong
//    amount, a hidden tier, another event's tier, a draft or sold-out event,
//    and every staff-only field are refused. No inquiry, registration, staff
//    row or view is readable; nothing can be updated, deleted or truncated
//    anywhere. The count triggers still count a registration the public
//    added (and the same insert fails if they run as the caller).
// 4. ets_registration_confirmation: the one registration by id and by
//    Stripe session id, only the fields the page shows (no phone, notes,
//    organization, check-in or Stripe fields), the virtual link only once
//    confirmed, null for anything else (empty, too long, a pattern, a
//    prefix, a session id two registrations share); the venue address where
//    the event has no address column, the address where it has one.
// 5. A signed-in login that is not the platform owner reads no row of the
//    ten, truncates nothing, uploads and deletes nothing in the bucket; the
//    platform owner (JWT email, any case) reads and writes everything,
//    virtual link and views included, and works the bucket.
// 6. The file's "Check after" queries say what the file says. The rollback
//    puts the policies (storage's too), grants, functions and production's
//    two views back exactly as they were (and the hole with them), leaves a
//    view that already ran as the caller as it is, runs twice, and the file
//    applies again.
// All of it twice: tables owned by the superuser, and by a role that is not
// a superuser and has no BYPASSRLS (as Supabase's postgres owns them), which
// runs both files (storage.objects is another role's, as on Supabase).
//
// The fixture: the six tables of the frontend's supabase/ets-schema.sql
// (module-system), with the columns production's site writes to inquiries
// (email, phone, org_type) and the internal ones the brief names
// (processed_at, converted_to_engagement); ets_events with production's
// columns in production's order (read from its catalog 2026-11-19: no
// address column; every event has a timezone and require_phone set), the
// other event tables from the columns the site and the app use, the tier
// flags as production showed them (is_visible default true, is_free
// default false, both not null), and the enums production has
// (ets_event_status as production showed; the registration status labels
// are those the site and the app use, a guess beyond pending and confirmed).
// Production's two views: ets_pending_agent_actions as ets-schema.sql makes
// it, ets_event_summary a plausible stand-in (its text was not read), both
// with no options; and a third view that already runs as the caller. The
// two count trigger functions with production's shape (+1 / -1, unqualified
// table names), plpgsql, invoker, no search_path. The bucket's three
// policies as production has them. is_platform_owner() as production
// defines it, with a made-up owner email, and stricter here: anon may not
// call it, so a policy that leaned on it for the public fails.
//
// Made-up events, made-up people.
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/ets_close_policies_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const APPLY = await sql('APPLY-2026-11-19-close-ets-policies.sql');
const ROLLBACK = await sql('ROLLBACK-2026-11-19-close-ets-policies.sql');

const OWNER_EMAIL = 'owner@example.test';
const u = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const TABLES = ['ets_events', 'ets_event_tiers', 'ets_event_files', 'ets_registrations', 'ets_inquiries',
  'ets_engagements', 'ets_emails', 'ets_agent_log', 'ets_signatures', 'ets_sessions_log'];
const STAFF = ['ets_engagements', 'ets_emails', 'ets_agent_log', 'ets_signatures', 'ets_sessions_log'];
// Production's two views (no options on 2026-11-19), and one that already
// runs as the caller, which the rollback must leave so.
const VIEWS = ['ets_event_summary', 'ets_pending_agent_actions'];
const INVOKER_VIEW = 'ets_tier_overview';
// The columns the new site build asks for (ets-web close-public-reads, each
// page's fields as the deployed build reads them).
const LIST_COLUMNS = 'id, slug, title, short_description, event_date, start_time, end_time, timezone, format, venue_name, '
  + 'city, capacity, registrations_count, status, cover_image';
const LIST_TIER_COLUMNS = 'price, is_free';
const LIST_FILE_COLUMNS = 'file_url, is_cover';
const PAGE_COLUMNS = 'id, title, short_description, description, event_date, start_time, end_time, timezone, format, '
  + 'venue_name, venue_address, city, state, capacity, registrations_count, require_phone, cover_image';
const PAGE_TIER_COLUMNS = 'id, name, description, price, is_free, quantity, sold_count, stripe_payment_link';
const PAGE_FILE_COLUMNS = 'id, file_name, file_url, file_type, is_cover';
const BUCKET = 'ets-event-files';
// A column each table has, for "update it to itself".
const SOME_COLUMN = {
  ets_events: 'title', ets_event_tiers: 'name', ets_event_files: 'file_url', ets_registrations: 'first_name',
  ets_inquiries: 'contact_name', ets_engagements: 'notes', ets_emails: 'subject', ets_agent_log: 'summary',
  ets_signatures: 'signer_name', ets_sessions_log: 'notes',
};

// Ids. Events: published, published virtual, sold out, draft, cancelled.
const E = { pub: u(101), virt: u(102), sold: u(103), draft: u(104), canc: u(105) };
const T = { free: u(201), paid: u(202), hidden: u(203), vfree: u(204), vpaid: u(205), sold: u(206), draft: u(207), canc: u(208) };
const F = { pubCover: u(301), pubDoc: u(302), sold: u(303), draft: u(304), canc: u(305) };
// Registrations' ids carry letters, so a reference in capitals is a different text.
const ur = n => `abcdef00-0000-4000-8000-${String(n).padStart(12, '0')}`;
const R = { pending: ur(401), session: ur(402), dup1: ur(403), dup2: ur(404), vpending: ur(405), vconf: ur(406) };
const LIVE_TIERS = [T.free, T.paid, T.vfree, T.vpaid, T.sold].sort();
const LIVE_FILES = [F.pubCover, F.pubDoc, F.sold].sort();
const LIVE_EVENTS = [E.pub, E.virt, E.sold].sort();

let checks = 0;
const ok = (v, m) => { assert.ok(v, m); checks++; };
const eq = (a, b, m) => { assert.deepEqual(a, b, m); checks++; };
const REFUSAL = /permission denied|row-level security|violates row-level/i;
const refused = (r, m) => {
  assert.equal(r.ok, false, `${m}: expected a refusal, it went through`);
  assert.match(r.error, REFUSAL, `${m}: refused for the wrong reason: ${r.error}`);
  checks++;
};
const went = (r, m) => { assert.equal(r.ok, true, `${m}: ${r.error}`); checks++; return r; };

const WHO = {
  anon: { role: 'anon', claims: { role: 'anon' } },
  stranger: { role: 'authenticated', claims: { sub: u(7), email: 'someone@example.test', role: 'authenticated' } },
  noEmail: { role: 'authenticated', claims: { sub: u(8), role: 'authenticated' } },
  owner: { role: 'authenticated', claims: { sub: u(1), email: 'Owner@Example.Test', role: 'authenticated' } },
};

function schema(ownedBy) {
  const owner = ownedBy ? `FOR ROLE ${ownedBy} ` : '';
  return `
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
${ownedBy ? `CREATE ROLE ${ownedBy} NOSUPERUSER NOBYPASSRLS;` : ''}
-- Storage, as Supabase has it: storage.objects is another role's, which the
-- role running the file is a member of; RLS on; the bucket's three policies
-- as production showed them (2026-08-09 storage-write-lockdown for the two).
CREATE ROLE storage_admin NOSUPERUSER NOBYPASSRLS;
${ownedBy ? `GRANT storage_admin TO ${ownedBy};` : ''}
CREATE SCHEMA storage;
GRANT USAGE ON SCHEMA storage TO anon, authenticated, service_role${ownedBy ? `, ${ownedBy}` : ''};
CREATE TABLE storage.objects (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bucket_id text, name text, owner uuid);
ALTER TABLE storage.objects OWNER TO storage_admin;
GRANT ALL ON storage.objects TO anon, authenticated, service_role;
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role${ownedBy ? `, ${ownedBy}` : ''};
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
${ownedBy ? `GRANT CREATE, USAGE ON SCHEMA public TO ${ownedBy};` : ''}
CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE
  AS $$ SELECT coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $$;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT nullif(auth.jwt() ->> 'sub', '')::uuid $$;
-- Supabase's default privileges: every new table, view and function in
-- public is handed to all three roles unless a file takes it back.
ALTER DEFAULT PRIVILEGES ${owner}IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES ${owner}IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
${ownedBy ? `SET ROLE ${ownedBy};` : ''}

-- is_platform_owner() as production defines it (made-up email).
CREATE FUNCTION public.is_platform_owner() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
  AS $$ SELECT COALESCE(lower(auth.jwt() ->> 'email') = '${OWNER_EMAIL}', false) $$;
REVOKE ALL ON FUNCTION public.is_platform_owner() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_platform_owner() TO authenticated;

CREATE TYPE public.ets_event_status AS ENUM ('draft', 'published', 'sold_out', 'cancelled', 'completed');
CREATE TYPE public.ets_registration_status AS ENUM ('pending', 'confirmed', 'checked_in', 'cancelled', 'refunded');

-- The six of supabase/ets-schema.sql, with production's added columns.
CREATE TABLE public.ets_inquiries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_name TEXT NOT NULL,
  contact_email TEXT,
  contact_phone TEXT,
  email TEXT,
  phone TEXT,
  organization_name TEXT,
  organization_type TEXT CHECK (organization_type IN ('church', 'nonprofit', 'school', 'business', 'other')),
  org_type TEXT,
  organization_size INTEGER,
  package_interest TEXT CHECK (package_interest IN ('foundations', 'mastery', 'not_sure')),
  message TEXT,
  lead_score TEXT CHECK (lead_score IN ('hot', 'warm', 'cold')) DEFAULT 'warm',
  agent_notes TEXT,
  processed BOOLEAN DEFAULT FALSE,
  processed_at TIMESTAMPTZ,
  converted_to_engagement BOOLEAN DEFAULT FALSE,
  source TEXT DEFAULT 'website',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE public.ets_engagements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  inquiry_id UUID REFERENCES public.ets_inquiries(id),
  organization_name TEXT NOT NULL,
  contact_name TEXT NOT NULL,
  contact_email TEXT,
  package_type TEXT NOT NULL CHECK (package_type IN ('foundations', 'mastery')),
  status TEXT NOT NULL DEFAULT 'signed' CHECK (status IN (
    'signed', 'proposal_sent', 'deposit_paid', 'in_progress', 'completed', 'cancelled')),
  total_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
  deposit_amount NUMERIC(10,2) DEFAULT 0,
  deposit_paid BOOLEAN DEFAULT FALSE,
  balance_amount NUMERIC(10,2) DEFAULT 0,
  balance_paid BOOLEAN DEFAULT FALSE,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE public.ets_signatures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id UUID NOT NULL REFERENCES public.ets_engagements(id) ON DELETE CASCADE,
  signer_name TEXT NOT NULL,
  signer_email TEXT NOT NULL,
  signature_data TEXT,
  signed_at TIMESTAMPTZ DEFAULT NOW(),
  -- ets-schema.sql: encode(gen_random_bytes(32), 'hex'); PGlite has no pgcrypto.
  token TEXT UNIQUE NOT NULL DEFAULT md5(random()::text) || md5(random()::text)
);
CREATE TABLE public.ets_sessions_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id UUID NOT NULL REFERENCES public.ets_engagements(id) ON DELETE CASCADE,
  session_number INTEGER NOT NULL,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE public.ets_agent_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_name TEXT NOT NULL,
  action_type TEXT NOT NULL,
  inquiry_id UUID REFERENCES public.ets_inquiries(id),
  engagement_id UUID REFERENCES public.ets_engagements(id),
  summary TEXT NOT NULL,
  draft_email_body TEXT,
  reviewed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE public.ets_emails (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id UUID REFERENCES public.ets_engagements(id),
  inquiry_id UUID REFERENCES public.ets_inquiries(id),
  to_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  body_html TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ets_events with production's columns in production's order (its catalog,
-- 2026-11-19; the types beyond what the pages show are a guess). The other
-- event tables from the columns the site and the app use, and the tier flags
-- as production showed them.
CREATE TABLE public.ets_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  title TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  description TEXT,
  short_description TEXT,
  format TEXT DEFAULT 'in_person',
  venue_name TEXT,
  venue_address TEXT,
  city TEXT,
  state TEXT,
  virtual_link TEXT,
  event_date DATE NOT NULL,
  start_time TIME,
  end_time TIME,
  timezone TEXT,
  cover_image TEXT,
  capacity INTEGER,
  registrations_count INTEGER NOT NULL DEFAULT 0,
  status public.ets_event_status NOT NULL DEFAULT 'draft',
  require_phone BOOLEAN DEFAULT FALSE,
  allow_free_registration BOOLEAN DEFAULT FALSE,
  confirmation_message TEXT,
  tags TEXT[],
  notes TEXT
);
CREATE TABLE public.ets_event_tiers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES public.ets_events(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  price NUMERIC(10,2) NOT NULL DEFAULT 0,
  is_free BOOLEAN NOT NULL DEFAULT FALSE,
  quantity INTEGER,
  sold_count INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER DEFAULT 0,
  is_visible BOOLEAN NOT NULL DEFAULT TRUE,
  stripe_payment_link TEXT
);
CREATE TABLE public.ets_event_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES public.ets_events(id) ON DELETE CASCADE,
  file_name TEXT,
  file_url TEXT NOT NULL,
  file_type TEXT,
  file_size INTEGER,
  is_cover BOOLEAN DEFAULT FALSE,
  sort_order INTEGER DEFAULT 0
);
CREATE TABLE public.ets_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES public.ets_events(id),
  tier_id UUID REFERENCES public.ets_event_tiers(id),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT,
  organization TEXT,
  status public.ets_registration_status NOT NULL DEFAULT 'pending',
  amount_paid NUMERIC(10,2) DEFAULT 0,
  stripe_session_id TEXT,
  stripe_payment_intent TEXT,
  checked_in BOOLEAN DEFAULT FALSE,
  checked_in_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Production's two views, no options: ets_event_summary a stand-in (its text
-- was not read: every event column, the virtual link among them, and its
-- registrations' totals and emails), ets_pending_agent_actions as
-- ets-schema.sql makes it. And one that already runs as the caller.
CREATE VIEW public.ets_event_summary AS
SELECT e.*, count(r.id) AS reg_total, coalesce(sum(r.amount_paid), 0) AS revenue, string_agg(r.email, ',') AS emails
  FROM public.ets_events e LEFT JOIN public.ets_registrations r ON r.event_id = e.id
 GROUP BY e.id;
CREATE VIEW public.${INVOKER_VIEW} WITH (security_invoker = true) AS
SELECT t.id, t.name, t.price FROM public.ets_event_tiers t;
CREATE VIEW public.ets_pending_agent_actions AS
SELECT al.*, i.contact_name as inquiry_contact, i.organization_name as inquiry_org,
       e.organization_name as engagement_org, e.contact_name as engagement_contact
FROM public.ets_agent_log al
LEFT JOIN public.ets_inquiries i ON al.inquiry_id = i.id
LEFT JOIN public.ets_engagements e ON al.engagement_id = e.id
WHERE al.reviewed = FALSE
ORDER BY al.created_at DESC;

-- The count triggers, of the shape production showed: +1 on an insert, -1 on
-- a delete, unqualified table names, plpgsql, invoker, no search_path.
CREATE FUNCTION public.ets_update_registration_count() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE ets_events SET registrations_count = registrations_count + 1 WHERE id = NEW.event_id;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE ets_events SET registrations_count = registrations_count - 1 WHERE id = OLD.event_id;
    RETURN OLD;
  END IF;
  RETURN NULL;
END $$;
CREATE FUNCTION public.ets_update_tier_sold_count() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE ets_event_tiers SET sold_count = sold_count + 1 WHERE id = NEW.tier_id;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE ets_event_tiers SET sold_count = sold_count - 1 WHERE id = OLD.tier_id;
    RETURN OLD;
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER ets_reg_count_trigger AFTER INSERT OR DELETE ON public.ets_registrations
  FOR EACH ROW EXECUTE FUNCTION public.ets_update_registration_count();
CREATE TRIGGER ets_tier_sold_trigger AFTER INSERT OR DELETE ON public.ets_registrations
  FOR EACH ROW EXECUTE FUNCTION public.ets_update_tier_sold_count();

-- RLS and the 26 policies production showed on 2026-11-19 (all permissive, TO public).
${TABLES.map(t => `ALTER TABLE public.${t} ENABLE ROW LEVEL SECURITY;`).join('\n')}
CREATE POLICY "Allow all for anon" ON public.ets_events FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY ets_auth_events ON public.ets_events FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY ets_public_read_events ON public.ets_events FOR SELECT USING (status = 'published' OR status = 'sold_out');
CREATE POLICY "Allow all for anon" ON public.ets_event_tiers FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY ets_auth_tiers ON public.ets_event_tiers FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY ets_public_read_tiers ON public.ets_event_tiers FOR SELECT USING (is_visible = true);
CREATE POLICY "Allow all for anon" ON public.ets_event_files FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY ets_auth_files ON public.ets_event_files FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY ets_public_read_files ON public.ets_event_files FOR SELECT USING (true);
CREATE POLICY "Allow all for anon" ON public.ets_registrations FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY ets_auth_registrations ON public.ets_registrations FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY ets_public_insert_registration ON public.ets_registrations FOR INSERT WITH CHECK (true);
CREATE POLICY ets_public_read_own_registration ON public.ets_registrations FOR SELECT USING (true);
CREATE POLICY ets_auth_inquiries ON public.ets_inquiries FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY ets_public_insert ON public.ets_inquiries FOR INSERT WITH CHECK (true);
CREATE POLICY ets_public_read ON public.ets_inquiries FOR SELECT USING (true);
${[['ets_engagements', 'engagements'], ['ets_emails', 'emails'], ['ets_agent_log', 'agent_log'],
    ['ets_signatures', 'signatures'], ['ets_sessions_log', 'sessions']].map(([t, x]) => `
CREATE POLICY ets_auth_${x} ON public.${t} FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY ets_read_${x} ON public.${t} FOR SELECT USING (true);`).join('')}
-- anon holds SELECT/INSERT/UPDATE/DELETE on all ten.
REVOKE ALL ON ${TABLES.map(t => `public.${t}`).join(', ')} FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON ${TABLES.map(t => `public.${t}`).join(', ')} TO anon;
${ownedBy ? 'RESET ROLE;' : ''}
CREATE POLICY "Allow public read" ON storage.objects FOR SELECT USING (bucket_id = '${BUCKET}');
CREATE POLICY "ets write: ets-event-files insert" ON storage.objects
  FOR INSERT TO authenticated WITH CHECK (bucket_id = '${BUCKET}');
CREATE POLICY "ets write: ets-event-files delete" ON storage.objects
  FOR DELETE TO authenticated USING (bucket_id = '${BUCKET}');
`;
}

const SEED = `
INSERT INTO storage.objects (bucket_id, name) VALUES ('${BUCKET}', 'covers/cover.jpg'), ('${BUCKET}', 'files/agenda.pdf');
-- Like production: every event has a time zone and asks for a phone (one
-- here does not, so the page rule is seen both ways), and has staff notes.
INSERT INTO public.ets_events (id, slug, title, event_date, start_time, end_time, format, venue_name, venue_address, city, state, virtual_link, confirmation_message, cover_image, status, timezone, require_phone, notes) VALUES
  ('${E.pub}', 'money-basics', 'Money Basics Workshop', '2026-12-05', '10:00', '12:00', 'in_person', 'Fellowship Hall', '100 Main St', 'Springfield', 'IL', NULL, 'Bring a notebook.', NULL, 'published', 'CT', true, 'staff only'),
  ('${E.virt}', 'online-budgeting', 'Online Budgeting Night', '2026-12-10', '19:00', '20:30', 'virtual', NULL, NULL, NULL, NULL, 'https://meet.example.test/room-1', NULL, NULL, 'published', 'ET', false, NULL),
  ('${E.sold}', 'full-house', 'Full House Seminar', '2026-12-12', '09:00', NULL, 'in_person', 'Main Hall', NULL, 'Springfield', 'IL', NULL, NULL, NULL, 'sold_out', 'CT', true, NULL),
  ('${E.draft}', 'not-yet', 'Not Yet Announced', '2027-01-15', NULL, NULL, 'hybrid', NULL, NULL, NULL, NULL, 'https://meet.example.test/secret', NULL, NULL, 'draft', 'CT', true, NULL),
  ('${E.canc}', 'called-off', 'Called Off', '2026-11-30', NULL, NULL, 'in_person', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'cancelled', 'CT', true, NULL);
INSERT INTO public.ets_event_tiers (id, event_id, name, price, is_free, is_visible, sort_order) VALUES
  ('${T.free}', '${E.pub}', 'Community', 0, true, true, 0),
  ('${T.paid}', '${E.pub}', 'Workbook Included', 49.00, false, true, 1),
  ('${T.hidden}', '${E.pub}', 'Staff Comp', 10.00, false, false, 2),
  ('${T.vfree}', '${E.virt}', 'Free Seat', 0, false, true, 0),
  ('${T.vpaid}', '${E.virt}', 'Supporter', 25.00, false, true, 1),
  ('${T.sold}', '${E.sold}', 'General', 20.00, false, true, 0),
  ('${T.draft}', '${E.draft}', 'Early', 0, true, true, 0),
  ('${T.canc}', '${E.canc}', 'General', 15.00, false, true, 0);
INSERT INTO public.ets_event_files (id, event_id, file_name, file_url, file_type, is_cover, sort_order) VALUES
  ('${F.pubCover}', '${E.pub}', 'cover.jpg', 'https://files.example.test/cover.jpg', 'image', true, 0),
  ('${F.pubDoc}', '${E.pub}', 'agenda.pdf', 'https://files.example.test/agenda.pdf', 'application/pdf', false, 1),
  ('${F.sold}', '${E.sold}', 'map.png', 'https://files.example.test/map.png', 'image', false, 0),
  ('${F.draft}', '${E.draft}', 'draft.png', 'https://files.example.test/draft.png', 'image', false, 0),
  ('${F.canc}', '${E.canc}', 'old.png', 'https://files.example.test/old.png', 'image', false, 0);
INSERT INTO public.ets_registrations (id, event_id, tier_id, first_name, last_name, email, phone, organization, status, amount_paid, stripe_session_id, notes) VALUES
  ('${R.pending}', '${E.pub}', '${T.paid}', 'Avery', 'Stone', 'avery@example.test', '555-0101', 'Grace Chapel', 'pending', 49, NULL, NULL),
  ('${R.session}', '${E.pub}', '${T.paid}', 'Blake', 'Rivers', 'blake@example.test', '555-0102', 'Hope Center', 'confirmed', 49, 'cs_test_one', 'paid at the door'),
  ('${R.dup1}', '${E.pub}', '${T.paid}', 'Casey', 'Hill', 'casey@example.test', NULL, NULL, 'pending', 49, 'cs_test_dup', NULL),
  ('${R.dup2}', '${E.pub}', '${T.paid}', 'Drew', 'Lake', 'drew@example.test', NULL, NULL, 'pending', 49, 'cs_test_dup', NULL),
  ('${R.vpending}', '${E.virt}', '${T.vpaid}', 'Emery', 'Fields', 'emery@example.test', NULL, NULL, 'pending', 25, NULL, NULL),
  ('${R.vconf}', '${E.virt}', '${T.vfree}', 'Finley', 'Brooks', 'finley@example.test', NULL, NULL, 'confirmed', 0, NULL, NULL);
INSERT INTO public.ets_inquiries (id, contact_name, email, organization_name, package_interest, message) VALUES
  ('${u(501)}', 'Gray Morgan', 'gray@example.test', 'Unity Fellowship', 'foundations', 'Tell me more'),
  ('${u(502)}', 'Harper Quinn', 'harper@example.test', 'New Day Center', 'mastery', NULL);
INSERT INTO public.ets_engagements (id, inquiry_id, organization_name, contact_name, package_type, total_amount, deposit_amount, deposit_paid)
  VALUES ('${u(601)}', '${u(501)}', 'Unity Fellowship', 'Gray Morgan', 'foundations', 3000, 1500, true);
INSERT INTO public.ets_emails (id, inquiry_id, to_email, subject, body_html) VALUES ('${u(701)}', '${u(501)}', 'gray@example.test', 'Welcome', '<p>Hi</p>');
INSERT INTO public.ets_agent_log (id, agent_name, action_type, inquiry_id, summary) VALUES ('${u(801)}', 'intake', 'score', '${u(501)}', 'Scored the lead warm');
INSERT INTO public.ets_signatures (id, engagement_id, signer_name, signer_email) VALUES ('${u(901)}', '${u(601)}', 'Gray Morgan', 'gray@example.test');
INSERT INTO public.ets_sessions_log (id, engagement_id, session_number, notes) VALUES ('${u(951)}', '${u(601)}', 1, 'Kickoff');
`;

async function build({ ownedBy }) {
  const db = new PGlite();
  await db.exec(schema(ownedBy));
  await db.exec(SEED);
  return db;
}

// Run one statement as a role with its JWT claims. `keep`: commit a write that
// went through (otherwise every probe is rolled back and changes nothing).
async function as(db, who, q, params = [], { keep = false } = {}) {
  await db.exec('BEGIN');
  try {
    await db.query(`SELECT set_config('request.jwt.claims', $1, true)`, [JSON.stringify(WHO[who].claims)]);
    await db.exec(`SET LOCAL ROLE ${WHO[who].role}`);
    const r = await db.query(q, params);
    await db.exec(keep ? 'COMMIT' : 'ROLLBACK');
    return { ok: true, rows: r.rows, n: r.affectedRows ?? 0 };
  } catch (e) {
    await db.exec('ROLLBACK');
    return { ok: false, error: String(e?.message || e) };
  }
}
const su = async (db, q, params = []) => (await db.query(q, params)).rows;
const ids = rows => rows.map(r => r.id).sort();

// A check block's query, as the role that runs the file would run it.
async function asRunner(db, ownedBy, q) {
  if (ownedBy) await db.exec(`SET ROLE ${ownedBy}`);
  try { return (await db.query(q)).rows; } finally { if (ownedBy) await db.exec('RESET ROLE'); }
}

async function runFile(db, text, ownedBy) {
  if (ownedBy) await db.exec(`SET ROLE ${ownedBy}`);
  try {
    await db.exec(text);
  } catch (e) {
    await db.exec('ROLLBACK');
    throw e;
  } finally {
    if (ownedBy) await db.exec('RESET ROLE');
  }
}

// The queries of a "-- Check ..." block, as written in the file's comments.
function checkBlock(text, heading) {
  const lines = text.split('\n');
  const start = lines.findIndex(l => l.startsWith(heading));
  assert.ok(start >= 0, `the file has "${heading}"`);
  const body = [];
  for (const l of lines.slice(start + 1)) {
    if (!l.startsWith('--')) break;
    body.push(l.replace(/^--   ?/, ''));
  }
  return body.join('\n').split(/;\s*$/m).map(s => s.trim())
    .filter(s => s.split('\n').some(l => l.trim() && !l.trim().startsWith('--')));
}

// What the site sends, as PostgREST runs it with return=minimal (RETURNING 1).
const minimal = (table, row) => {
  const cols = Object.keys(row);
  return [`WITH pgrst_source AS (INSERT INTO public.${table} (${cols.join(', ')}) VALUES (${cols.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING 1) SELECT count(*)::int AS n FROM pgrst_source`, Object.values(row)];
};
const inquiry = (n, extra = {}) => ({
  id: u(5000 + n), contact_name: 'Jordan Pike', organization_name: 'River Church', email: 'jordan@example.test',
  phone: '555-0199', package_interest: 'not_sure', message: null, org_type: 'church', ...extra,
});
const registration = (n, tier, extra = {}) => {
  const free = tier === T.free || tier === T.vfree || tier === T.draft;
  const price = { [T.paid]: 49, [T.hidden]: 10, [T.vpaid]: 25, [T.sold]: 20, [T.canc]: 15 }[tier] ?? 0;
  const event = { [T.free]: E.pub, [T.paid]: E.pub, [T.hidden]: E.pub, [T.vfree]: E.virt, [T.vpaid]: E.virt,
    [T.sold]: E.sold, [T.draft]: E.draft, [T.canc]: E.canc }[tier];
  return { id: u(6000 + n), event_id: event, tier_id: tier, first_name: 'Kai', last_name: 'Reed',
    email: 'kai@example.test', phone: null, organization: null,
    status: free ? 'confirmed' : 'pending', amount_paid: free ? 0 : price, ...extra };
};
const counts = async db => Object.fromEntries(await Promise.all(TABLES.map(async t =>
  [t, (await su(db, `SELECT count(*)::int AS n FROM public.${t}`))[0].n])));
const grantsOf = role => `SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) AS p
    FROM information_schema.role_table_grants WHERE grantee = '${role}' AND table_schema = 'public'
    AND table_name IN (${TABLES.map(t => `'${t}'`).join(', ')}) GROUP BY 1 ORDER BY 1`;
const snapshot = async db => ({
  policies: await su(db, `SELECT tablename, policyname, cmd, roles::text AS roles, qual, with_check FROM pg_policies
    WHERE schemaname = 'public' AND tablename LIKE 'ets\\_%' ORDER BY 1, 2`),
  storage: await su(db, `SELECT policyname, cmd, roles::text AS roles, qual, with_check FROM pg_policies
    WHERE schemaname = 'storage' AND tablename = 'objects' ORDER BY 1`),
  grants: await su(db, grantsOf('anon')),
  authenticatedGrants: await su(db, grantsOf('authenticated')),
  anonEventColumns: await su(db, `SELECT column_name FROM information_schema.column_privileges
    WHERE grantee = 'anon' AND table_schema = 'public' AND table_name = 'ets_events' AND privilege_type = 'SELECT'
    ORDER BY 1`),
  functions: await su(db, `SELECT proname, prosecdef, proconfig FROM pg_proc
    WHERE proname IN ('ets_update_registration_count', 'ets_update_tier_sold_count') ORDER BY 1`),
  views: await su(db, `SELECT relname, reloptions, has_table_privilege('anon', oid, 'select') AS anon_reads
    FROM pg_class WHERE relname IN (${VIEWS.map(v => `'${v}'`).join(', ')}) ORDER BY 1`),
});
const confirm = async (db, who, ref) => {
  const r = await as(db, who, 'SELECT public.ets_registration_confirmation($1) AS c', [ref]);
  assert.equal(r.ok, true, `the confirmation function for ${who}: ${r.error}`);
  return r.rows[0].c;
};

async function scenario({ ownedBy }) {
  const label = ownedBy ? `owned by ${ownedBy}` : 'owned by the superuser';
  const db = await build({ ownedBy });
  const seeded = await counts(db);
  eq(seeded, { ets_events: 5, ets_event_tiers: 8, ets_event_files: 5, ets_registrations: 6, ets_inquiries: 2,
    ets_engagements: 1, ets_emails: 1, ets_agent_log: 1, ets_signatures: 1, ets_sessions_log: 1 }, `${label}: seeded`);

  // ─── 1. Before: the hole, and the live site's calls ────────────────────
  for (const t of TABLES) {
    const r = await as(db, 'anon', `SELECT count(*)::int AS n FROM public.${t}`);
    ok(r.ok && r.rows[0].n > 0, `${label}: before, anon reads ${t}`);
  }
  eq((await as(db, 'anon', 'DELETE FROM public.ets_event_files')).n, 5, `${label}: before, anon may delete every event file`);
  eq((await as(db, 'anon', `DELETE FROM public.ets_events WHERE id = $1`, [E.canc])).n, 1, `${label}: and an event`);
  ok((await as(db, 'stranger', 'SELECT * FROM public.ets_emails')).rows.length === 1, `${label}: before, any login reads the emails`);
  for (const view of VIEWS) {
    ok((await as(db, 'anon', `SELECT * FROM public.${view}`)).ok, `${label}: before, anon reads ${view}`);
  }
  eq((await as(db, 'anon', `SELECT virtual_link FROM public.ets_events WHERE id = $1`, [E.virt])).rows,
    [{ virtual_link: 'https://meet.example.test/room-1' }], `${label}: before, anon reads a virtual link`);
  ok((await as(db, 'anon', 'SELECT * FROM public.ets_events')).ok, `${label}: before, the live site's "*" works`);
  went(await as(db, 'stranger', `INSERT INTO storage.objects (bucket_id, name) VALUES ('${BUCKET}', 'x.png')`),
    `${label}: before, any login uploads to the bucket`);
  eq((await as(db, 'stranger', `DELETE FROM storage.objects WHERE bucket_id = '${BUCKET}'`)).n, 2,
    `${label}: and deletes from it`);
  {
    const row = inquiry(0);
    const cols = Object.keys(row);
    const r = await as(db, 'anon', `INSERT INTO public.ets_inquiries (${cols.join(', ')}) VALUES (${cols.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING id`, Object.values(row));
    ok(r.ok && r.rows[0].id === row.id, `${label}: before, the live site's insert-and-read-back works`);
  }
  const before = await snapshot(db);
  eq(before.policies.length, 26, `${label}: production's 26 policies`);
  eq(await counts(db), seeded, `${label}: the probes changed nothing`);

  // ─── 2. The file's own checks before, then the file, twice ─────────────
  const pre = checkBlock(APPLY, '-- Check before applying (read-only):');
  eq(pre.length, 13, `${label}: thirteen checks before`);
  const preAnswers = [];
  for (const q of pre) preAnswers.push(await asRunner(db, ownedBy, q));
  const [cPolicies, cColumns, cFlags, cHidden, cEnums, cAnonColumns, cTriggers, cFunctions, cHelper, cViews, cGrants,
    cBucket, cLooseStorage] = preAnswers;
  eq(cPolicies.length, 26, `${label}: check 1 lists the 26 policies`);
  eq(cColumns.length, 56, `${label}: check 2 finds the 56 columns`);
  for (const col of ['timezone', 'require_phone', 'venue_address']) {
    ok(cColumns.some(r => r.table_name === 'ets_events' && r.column_name === col), `${label}: check 2 lists ets_events.${col}`);
  }
  ok(!cColumns.some(r => r.column_name === 'address'), `${label}: check 2 asks for no address column (production has none)`);
  eq(cFlags.map(r => [r.column_name, r.column_default, r.is_nullable]), [['is_free', 'false', 'NO'], ['is_visible', 'true', 'NO']],
    `${label}: check 3, the tier flags`);
  eq(Number(cHidden[0].tiers_that_disappear), 1, `${label}: check 4 counts the one hidden tier the fixture has on a live event (production: 0)`);
  ok(cEnums[0].registration_statuses.includes('pending') && cEnums[0].event_statuses.includes('sold_out'),
    `${label}: check 5 shows the statuses`);
  const eventColumns = (await su(db, `SELECT attname FROM pg_attribute WHERE attrelid = 'public.ets_events'::regclass
    AND attnum > 0 AND NOT attisdropped ORDER BY attnum`)).map(r => r.attname);
  const PRIVATE = ['virtual_link', 'notes'];
  eq(cAnonColumns[0].anon_may_read.split(', '), eventColumns.filter(c => !PRIVATE.includes(c)),
    `${label}: check 6 lists every event column but the virtual link and the notes`);
  eq(cAnonColumns[0].anon_may_read, 'id, created_at, updated_at, title, slug, description, short_description, format, '
    + 'venue_name, venue_address, city, state, event_date, start_time, end_time, timezone, cover_image, capacity, '
    + 'registrations_count, status, require_phone, allow_free_registration, confirmation_message, tags',
    `${label}: check 6, on production's columns, is the list the file says to expect`);
  eq(cTriggers.map(r => r.tgname), ['ets_reg_count_trigger', 'ets_tier_sold_trigger'], `${label}: check 7, the two triggers`);
  eq(cFunctions.map(r => [r.owner === r.running_as, r.security_definer, r.settings]), [[true, false, null], [true, false, null]],
    `${label}: check 8, owned by the role running the file, invoker today`);
  ok(cFunctions.every(r => /UPDATE ets_(events|event_tiers) SET (registrations_count|sold_count) = \2 \+ 1/.test(r.definition)),
    `${label}: check 8 shows the bodies`);
  eq(cHelper.map(r => [r.security_definer, r.authenticated_may_call]), [[true, true]], `${label}: check 9, the owner helper`);
  eq(cViews.map(r => [String(r.view), r.reloptions]).sort(), [['ets_event_summary', null], ['ets_pending_agent_actions', null],
    [INVOKER_VIEW, ['security_invoker=true']]], `${label}: check 10, the views`);
  eq(cGrants.map(r => r.table_name).sort(), [...TABLES, ...VIEWS, INVOKER_VIEW].sort(), `${label}: check 11, anon on all ten and the views`);
  for (const r of cGrants.filter(r => TABLES.includes(r.table_name))) eq(r.anon_may, 'DELETE, INSERT, SELECT, UPDATE', `${label}: check 11, ${r.table_name}`);
  eq(cBucket.map(r => [r.policyname, r.cmd]), [['Allow public read', 'SELECT'], ['ets write: ets-event-files delete', 'DELETE'],
    ['ets write: ets-event-files insert', 'INSERT']], `${label}: check 12, the bucket's three policies`);
  eq(cLooseStorage, [], `${label}: check 13, no storage write policy without a bucket`);

  await runFile(db, APPLY, ownedBy);
  await runFile(db, APPLY, ownedBy);
  eq(await counts(db), { ...seeded, ets_inquiries: 2 }, `${label}: the file changed no row`);

  // ─── 3. The public site, after ─────────────────────────────────────────
  {
    // EventsPage, with exactly the columns the new site asks for, its tiers
    // and files nested the way PostgREST embeds them, published or sold out.
    const nested = (cols, alias) => `json_build_object(${cols.split(', ').map(c => `'${c}', ${alias}.${c}`).join(', ')})`;
    const r = went(await as(db, 'anon', `SELECT ${LIST_COLUMNS.split(', ').map(c => `e.${c}`).join(', ')},
        (SELECT coalesce(json_agg(${nested(LIST_TIER_COLUMNS, 't')} ORDER BY t.price), '[]')
           FROM public.ets_event_tiers t WHERE t.event_id = e.id) AS tiers,
        (SELECT coalesce(json_agg(${nested(LIST_FILE_COLUMNS, 'f')} ORDER BY f.file_url), '[]')
           FROM public.ets_event_files f WHERE f.event_id = e.id) AS files
      FROM public.ets_events e WHERE e.status IN ('published', 'sold_out') ORDER BY e.event_date`), `${label}: the events list`);
    eq(Object.keys(r.rows[0]).sort(), [...LIST_COLUMNS.split(', '), 'tiers', 'files'].sort(), `${label}: every column the list asks for`);
    eq(r.rows.map(x => [x.id, x.timezone, x.tiers.map(t => Number(t.price)), x.files.length]), [
      [E.pub, 'CT', [0, 49], 2],
      [E.virt, 'ET', [0, 25], 0],
      [E.sold, 'CT', [20], 1],
    ], `${label}: the events list has each event's time zone and its live tiers and files, no hidden tier`);
    eq(ids((await as(db, 'anon', 'SELECT id FROM public.ets_events')).rows), LIVE_EVENTS, `${label}: anon sees no draft or cancelled event`);
    eq(ids((await as(db, 'anon', 'SELECT id FROM public.ets_event_tiers')).rows), LIVE_TIERS, `${label}: anon sees only live, visible tiers`);
    eq(ids((await as(db, 'anon', 'SELECT id FROM public.ets_event_files')).rows), LIVE_FILES, `${label}: anon sees only live events' files`);
    // EventRegister: one event by slug, published, with its page's columns.
    const one = went(await as(db, 'anon', `SELECT ${PAGE_COLUMNS.split(', ').map(c => `e.${c}`).join(', ')},
        (SELECT json_agg(json_build_object(${PAGE_TIER_COLUMNS.split(', ').map(c => `'${c}', t.${c}`).join(', ')}))
           FROM public.ets_event_tiers t WHERE t.event_id = e.id) AS tiers,
        (SELECT json_agg(json_build_object(${PAGE_FILE_COLUMNS.split(', ').map(c => `'${c}', f.${c}`).join(', ')}))
           FROM public.ets_event_files f WHERE f.event_id = e.id) AS files
      FROM public.ets_events e WHERE e.slug = 'money-basics' AND e.status = 'published'`), `${label}: the register page`);
    eq(Object.keys(one.rows[0]).sort(), [...PAGE_COLUMNS.split(', '), 'tiers', 'files'].sort(), `${label}: every column the page asks for`);
    eq([one.rows.length, one.rows[0].venue_address, one.rows[0].timezone, one.rows[0].require_phone,
      one.rows[0].tiers.length, one.rows[0].files.length],
      [1, '100 Main St', 'CT', true, 2, 2], `${label}: the register page gets its address, time zone, phone rule, tiers and files`);
    // The register page's own rule, as the deployed build has it: the phone
    // field is `required` when event.require_phone is set (ets-web
    // EventRegister; its scripts/check-selects.mjs holds the page to it), so
    // the browser refuses the form without a phone there and sends it
    // without one elsewhere. The rule only works if the page gets the flag.
    const pageRefuses = (ev, phone) => Boolean(ev.require_phone) && !String(phone || '').trim();
    for (const slug of ['money-basics', 'online-budgeting']) {
      const ev = (await as(db, 'anon', `SELECT require_phone FROM public.ets_events WHERE slug = $1`, [slug])).rows[0];
      const expected = slug === 'money-basics';
      eq([pageRefuses(ev, ''), pageRefuses(ev, '555-0100')], [expected, false],
        `${label}: ${slug}: the page ${expected ? 'refuses' : 'accepts'} a registration with no phone, as the deployed build did`);
    }
    refused(await as(db, 'anon', `SELECT notes FROM public.ets_events`), `${label}: the staff notes are not the public's either`);
    eq((await as(db, 'anon', `SELECT id FROM public.ets_events WHERE slug = 'not-yet'`)).rows, [], `${label}: a draft's page is not found`);
    // The virtual link is not the public's: by name, by "*", or by a view.
    refused(await as(db, 'anon', `SELECT virtual_link FROM public.ets_events`), `${label}: anon cannot read a virtual link`);
    refused(await as(db, 'anon', `SELECT * FROM public.ets_events`), `${label}: the live site's "*" on events is refused`);
    refused(await as(db, 'anon', `SELECT id FROM public.ets_events WHERE virtual_link IS NOT NULL`), `${label}: nor filter by it`);
    refused(await as(db, 'anon', `SELECT e FROM public.ets_events e`), `${label}: nor read the whole row`);
    // The bucket: the public still reads it, and writes nothing.
    eq((await as(db, 'anon', `SELECT name FROM storage.objects WHERE bucket_id = '${BUCKET}' ORDER BY 1`)).rows.map(r => r.name),
      ['covers/cover.jpg', 'files/agenda.pdf'], `${label}: anon reads the bucket`);
    refused(await as(db, 'anon', `INSERT INTO storage.objects (bucket_id, name) VALUES ('${BUCKET}', 'y.png')`), `${label}: anon uploads nothing`);
    eq((await as(db, 'anon', `DELETE FROM storage.objects WHERE bucket_id = '${BUCKET}'`)).n, 0, `${label}: anon deletes nothing`);
  }

  // Inquiries.
  {
    const [q, p] = minimal('ets_inquiries', inquiry(1));
    const r = went(await as(db, 'anon', q, p, { keep: true }), `${label}: anon sends an inquiry, nothing asked back`);
    eq(r.rows[0].n, 1, `${label}: one inquiry added`);
    const plain = inquiry(2);
    went(await as(db, 'anon', `INSERT INTO public.ets_inquiries (id, contact_name, email, package_interest) VALUES ($1, $2, $3, $4)`,
      [plain.id, plain.contact_name, plain.email, plain.package_interest], { keep: true }), `${label}: a plain INSERT, no RETURNING`);
    const back = inquiry(3);
    refused(await as(db, 'anon', `INSERT INTO public.ets_inquiries (id, contact_name) VALUES ($1, $2) RETURNING id`, [back.id, back.contact_name]),
      `${label}: the live site's insert-and-read-back is refused`);
    for (const [field, value] of [['processed', true], ['processed_at', '2026-11-19T10:00:00Z'], ['agent_notes', 'hot lead'],
      ['lead_score', 'hot'], ['lead_score', 'cold'], ['converted_to_engagement', true]]) {
      const [q2, p2] = minimal('ets_inquiries', inquiry(10, { [field]: value }));
      refused(await as(db, 'anon', q2, p2), `${label}: the public may not set ${field} = ${value}`);
    }
    const [q3, p3] = minimal('ets_inquiries', inquiry(11, { lead_score: 'warm', processed: false, converted_to_engagement: false }));
    went(await as(db, 'anon', q3, p3), `${label}: the defaults written out are the defaults`);
    const stored = await su(db, `SELECT processed, lead_score, converted_to_engagement FROM public.ets_inquiries WHERE id = $1`, [inquiry(1).id]);
    eq(stored, [{ processed: false, lead_score: 'warm', converted_to_engagement: false }], `${label}: the new inquiry has the defaults`);
  }

  // Registrations.
  const freeReg = registration(1, T.free);
  const paidReg = registration(2, T.paid);
  {
    const evBefore = (await su(db, `SELECT registrations_count FROM public.ets_events WHERE id = $1`, [E.pub]))[0].registrations_count;
    const tiersBefore = await su(db, `SELECT id, sold_count FROM public.ets_event_tiers WHERE id IN ($1, $2) ORDER BY id`, [T.free, T.paid]);

    // The same insert fails if the count triggers run as the caller.
    await db.exec('BEGIN');
    await db.exec('ALTER FUNCTION public.ets_update_registration_count() SECURITY INVOKER; ALTER FUNCTION public.ets_update_tier_sold_count() SECURITY INVOKER');
    await db.query(`SELECT set_config('request.jwt.claims', $1, true)`, [JSON.stringify(WHO.anon.claims)]);
    await db.exec('SET LOCAL ROLE anon');
    let invokerError = '';
    try { const [q, p] = minimal('ets_registrations', freeReg); await db.query(q, p); } catch (e) { invokerError = String(e.message); }
    await db.exec('ROLLBACK');
    ok(REFUSAL.test(invokerError), `${label}: as the caller, the count triggers would fail the public's registration (${invokerError})`);

    for (const reg of [freeReg, paidReg]) {
      const [q, p] = minimal('ets_registrations', reg);
      const r = went(await as(db, 'anon', q, p, { keep: true }), `${label}: anon registers (${reg.status}, ${reg.amount_paid})`);
      eq(r.rows[0].n, 1, `${label}: one registration added`);
    }
    const virtFree = registration(3, T.vfree);   // free by price 0, is_free false
    const [qv, pv] = minimal('ets_registrations', virtFree);
    went(await as(db, 'anon', qv, pv, { keep: true }), `${label}: a tier free by its price is free`);
    const pendingFree = registration(4, T.free, { status: 'pending' });
    const [qp, pp] = minimal('ets_registrations', pendingFree);
    went(await as(db, 'anon', qp, pp), `${label}: a free tier may also be pending`);

    // The counts moved, as the triggers count (+1 a registration added).
    const evAfter = (await su(db, `SELECT registrations_count FROM public.ets_events WHERE id = $1`, [E.pub]))[0].registrations_count;
    eq(evAfter, evBefore + 2, `${label}: the event's count went up by the two added`);
    const recount = (await su(db, `SELECT count(*)::int AS n FROM public.ets_registrations WHERE event_id = $1`, [E.pub]))[0].n;
    eq(evAfter, recount, `${label}: and it is right`);
    const tiersAfter = await su(db, `SELECT id, sold_count FROM public.ets_event_tiers WHERE id IN ($1, $2) ORDER BY id`, [T.free, T.paid]);
    eq(tiersAfter.map(t => t.sold_count), tiersBefore.map(t => t.sold_count + 1), `${label}: each tier counted its one`);
    eq((await su(db, `SELECT registrations_count FROM public.ets_events WHERE id = $1`, [E.virt]))[0].registrations_count, 3,
      `${label}: the virtual event's count too`);

    const bad = [
      ['a confirmed paid registration', registration(20, T.paid, { status: 'confirmed' })],
      ['a paid one for nothing', registration(21, T.paid, { amount_paid: 0 })],
      ['a paid one for less', registration(22, T.paid, { amount_paid: 48.99 })],
      ['a paid one with no amount', registration(23, T.paid, { amount_paid: null })],
      ['a free one with an amount', registration(24, T.free, { amount_paid: 5 })],
      ['a hidden tier', registration(25, T.hidden)],
      ["another event's tier", registration(26, T.paid, { event_id: E.virt })],
      ['no tier', registration(27, T.free, { tier_id: null })],
      ['a draft event', registration(28, T.draft)],
      ['a sold-out event', registration(29, T.sold)],
      ['a cancelled event', registration(30, T.canc)],
      ['checked in', registration(31, T.free, { checked_in: true })],
      ['a check-in time', registration(32, T.free, { checked_in_at: '2026-11-19T10:00:00Z' })],
      ['a Stripe session', registration(33, T.paid, { stripe_session_id: 'cs_test_forged' })],
      ['a Stripe payment', registration(34, T.paid, { stripe_payment_intent: 'pi_forged' })],
      ['notes', registration(35, T.free, { notes: 'VIP' })],
      ['status checked_in', registration(36, T.free, { status: 'checked_in' })],
      ['status refunded', registration(37, T.free, { status: 'refunded' })],
    ];
    for (const [what, reg] of bad) {
      const [q, p] = minimal('ets_registrations', reg);
      refused(await as(db, 'anon', q, p), `${label}: the public may not register ${what}`);
    }
    refused(await as(db, 'anon', `INSERT INTO public.ets_registrations (event_id, tier_id, first_name, last_name, email, status, amount_paid)
      VALUES ($1, $2, 'A', 'B', 'c@example.test', 'confirmed', 0) RETURNING id`, [E.pub, T.free]), `${label}: the live site's registration read-back is refused`);
  }

  // Nothing read, changed or removed past that.
  for (const t of ['ets_inquiries', 'ets_registrations', ...STAFF, ...VIEWS, INVOKER_VIEW]) {
    refused(await as(db, 'anon', `SELECT * FROM public.${t}`), `${label}: anon reads no ${t}`);
  }
  for (const t of TABLES) {
    refused(await as(db, 'anon', `UPDATE public.${t} SET ${SOME_COLUMN[t]} = ${SOME_COLUMN[t]}`), `${label}: anon updates no ${t}`);
    refused(await as(db, 'anon', `DELETE FROM public.${t}`), `${label}: anon deletes no ${t}`);
    refused(await as(db, 'anon', `TRUNCATE public.${t} CASCADE`), `${label}: anon truncates no ${t}`);
  }
  for (const t of ['ets_events', 'ets_event_tiers', 'ets_event_files', ...STAFF]) {
    refused(await as(db, 'anon', `INSERT INTO public.${t} DEFAULT VALUES`), `${label}: anon adds no ${t} row`);
  }
  const afterPublic = await counts(db);
  eq(afterPublic, { ...seeded, ets_inquiries: 4, ets_registrations: 9 }, `${label}: only the public's own rows were added`);

  // ─── 4. The confirmation function ──────────────────────────────────────
  const KEYS = ['amount_paid', 'email', 'ets_event_tiers', 'ets_events', 'first_name', 'id', 'last_name', 'status'];
  const EVENT_KEYS = ['address', 'city', 'confirmation_message', 'cover_image', 'end_time', 'ets_event_files', 'event_date',
    'format', 'start_time', 'state', 'timezone', 'title', 'venue_name', 'virtual_link'];
  {
    const c = await confirm(db, 'anon', R.pending);
    eq(Object.keys(c).sort(), KEYS, `${label}: the function answers only the page's fields`);
    eq(Object.keys(c.ets_events).sort(), EVENT_KEYS, `${label}: and the event's`);
    eq([c.id, c.first_name, c.last_name, c.email, c.status, Number(c.amount_paid)],
      [R.pending, 'Avery', 'Stone', 'avery@example.test', 'pending', 49], `${label}: by id, the registration`);
    eq([c.ets_events.title, c.ets_events.event_date, c.ets_events.start_time, c.ets_events.virtual_link,
      c.ets_events.address, c.ets_events.timezone],
      ['Money Basics Workshop', '2026-12-05', '10:00:00', null, '100 Main St', 'CT'],
      `${label}: its event, its time zone, the venue address as its address (no address column, no failure)`);
    eq(c.ets_events.ets_event_files, [{ file_url: 'https://files.example.test/cover.jpg', is_cover: true },
      { file_url: 'https://files.example.test/agenda.pdf', is_cover: false }], `${label}: its files, url and cover only`);
    eq([c.ets_event_tiers.name, Number(c.ets_event_tiers.price)], ['Workbook Included', 49], `${label}: its tier`);
    const s = await confirm(db, 'anon', 'cs_test_one');
    eq([s.id, s.status], [R.session, 'confirmed'], `${label}: by Stripe session id`);
    for (const hidden of ['phone', 'organization', 'notes', 'stripe_session_id', 'stripe_payment_intent', 'checked_in', 'checked_in_at', 'created_at']) {
      ok(!(hidden in s) && !JSON.stringify(s).includes(hidden === 'notes' ? 'paid at the door' : hidden), `${label}: never ${hidden}`);
    }
    ok(!JSON.stringify(s).includes('555-0102') && !JSON.stringify(s).includes('Hope Center'), `${label}: no phone or organization value`);
    eq((await confirm(db, 'anon', freeReg.id)).status, 'confirmed', `${label}: the public's own free registration reads back`);
    eq((await confirm(db, 'anon', paidReg.id)).ets_event_tiers.name, 'Workbook Included', `${label}: and its paid one`);
    // The virtual link only once confirmed.
    eq((await confirm(db, 'anon', R.vpending)).ets_events.virtual_link, null, `${label}: a pending registration gets no link`);
    eq((await confirm(db, 'anon', R.vconf)).ets_events.virtual_link, 'https://meet.example.test/room-1', `${label}: a confirmed one does`);
    for (const [what, ref] of [['an unknown id', u(4999)], ['nothing', ''], ['null', null], ['too long', 'x'.repeat(201)],
      ['a pattern', '%'], ['a pattern on the session', 'cs_test_%'], ['an id prefix', R.pending.slice(0, 8)],
      ['an id in capitals', R.pending.toUpperCase()], ['an id with a space', ` ${R.pending}`], ['a quote', "' or 1=1 --"],
      ['a session id two share', 'cs_test_dup'], ['a session prefix', 'cs_test_on']]) {
      eq(await confirm(db, 'anon', ref), null, `${label}: ${what} is no registration`);
    }
    eq((await confirm(db, 'stranger', R.pending)).id, R.pending, `${label}: a signed-in login uses it the same`);
  }

  // ─── 5. A login that is not the owner; the owner ───────────────────────
  for (const who of ['stranger', 'noEmail']) {
    // The public reads are anon's: a login that is not the owner reads no row of the ten.
    for (const t of [...TABLES, ...VIEWS, INVOKER_VIEW]) {
      const r = went(await as(db, who, `SELECT * FROM public.${t}`), `${label}: ${who} reads ${t}`);
      eq(r.rows.length, 0, `${label}: ${who} reads no ${t} row`);
    }
    eq((await as(db, who, 'SELECT virtual_link FROM public.ets_events')).rows, [], `${label}: ${who} reads no virtual link`);
    for (const t of TABLES) {
      eq((await as(db, who, `UPDATE public.${t} SET ${SOME_COLUMN[t]} = ${SOME_COLUMN[t]}`)).n, 0, `${label}: ${who} updates no ${t}`);
      eq((await as(db, who, `DELETE FROM public.${t}`)).n, 0, `${label}: ${who} deletes no ${t}`);
      refused(await as(db, who, `TRUNCATE public.${t} CASCADE`), `${label}: ${who} truncates no ${t}`);
    }
    for (const t of STAFF) {
      refused(await as(db, who, `INSERT INTO public.${t} DEFAULT VALUES`), `${label}: ${who} adds no ${t} row`);
    }
    refused(await as(db, who, `INSERT INTO public.ets_events (slug, title, event_date, status) VALUES ('x', 'X', '2027-01-01', 'published')`),
      `${label}: ${who} adds no event`);
    const [q, p] = minimal('ets_registrations', registration(40, T.paid, { status: 'confirmed' }));
    refused(await as(db, who, q, p), `${label}: ${who} may not mark a paid registration confirmed either`);
    const [q1, p1] = minimal('ets_registrations', registration(42, T.free));
    refused(await as(db, who, q1, p1), `${label}: ${who} sees no event, so registers for none`);
    const [q2, p2] = minimal('ets_inquiries', inquiry(41));
    went(await as(db, who, q2, p2), `${label}: ${who} may still send the public form's inquiry`);
    // The bucket: reads it like anyone, writes nothing.
    eq((await as(db, who, `SELECT count(*)::int AS n FROM storage.objects WHERE bucket_id = '${BUCKET}'`)).rows[0].n, 2, `${label}: ${who} reads the bucket`);
    refused(await as(db, who, `INSERT INTO storage.objects (bucket_id, name) VALUES ('${BUCKET}', 'z.png')`), `${label}: ${who} uploads nothing`);
    eq((await as(db, who, `DELETE FROM storage.objects WHERE bucket_id = '${BUCKET}'`)).n, 0, `${label}: ${who} deletes nothing`);
  }
  eq(await counts(db), afterPublic, `${label}: the logins changed nothing`);

  const all = await counts(db);
  for (const t of TABLES) {
    const r = went(await as(db, 'owner', `SELECT count(*)::int AS n FROM public.${t}`), `${label}: the owner reads ${t}`);
    eq(r.rows[0].n, all[t], `${label}: the owner reads every ${t} row`);
  }
  eq((await as(db, 'owner', 'SELECT * FROM public.ets_pending_agent_actions')).rows.length, 1, `${label}: the owner reads the agent's pending actions`);
  eq((await as(db, 'owner', 'SELECT count(*)::int AS n FROM public.ets_event_summary')).rows[0].n, all.ets_events,
    `${label}: and the event summary`);
  eq((await as(db, 'owner', `SELECT virtual_link FROM public.ets_events WHERE id = $1`, [E.draft])).rows,
    [{ virtual_link: 'https://meet.example.test/secret' }], `${label}: the owner reads a virtual link, a draft's too`);
  for (const t of ['ets_events', 'ets_emails']) {
    refused(await as(db, 'owner', `TRUNCATE public.${t} CASCADE`), `${label}: not even the owner truncates ${t} (no browser call needs it)`);
  }
  went(await as(db, 'owner', `INSERT INTO storage.objects (bucket_id, name) VALUES ('${BUCKET}', 'covers/new.jpg')`), `${label}: the owner uploads`);
  eq((await as(db, 'owner', `DELETE FROM storage.objects WHERE bucket_id = '${BUCKET}' AND name = 'files/agenda.pdf'`)).n, 1,
    `${label}: and deletes`);
  eq((await as(db, 'owner', `UPDATE public.ets_registrations SET status = 'confirmed', amount_paid = 25 WHERE id = $1`, [R.vpending], { keep: true })).n, 1,
    `${label}: the owner confirms a paid registration`);
  eq((await confirm(db, 'anon', R.vpending)).ets_events.virtual_link, 'https://meet.example.test/room-1',
    `${label}: and the page's poll then gets the link`);
  went(await as(db, 'owner', `INSERT INTO public.ets_emails (to_email, subject, body_html) VALUES ('x@example.test', 'S', 'B')`), `${label}: the owner adds an email`);
  went(await as(db, 'owner', `INSERT INTO public.ets_events (slug, title, event_date) VALUES ('owner-draft', 'Draft', '2027-02-01')`), `${label}: the owner adds a draft event`);
  eq((await as(db, 'owner', `UPDATE public.ets_inquiries SET processed = true, lead_score = 'hot'`)).n, all.ets_inquiries, `${label}: the owner works the inquiries`);
  eq((await as(db, 'owner', 'DELETE FROM public.ets_agent_log')).n, 1, `${label}: the owner clears the agent log`);
  eq((await as(db, 'owner', `UPDATE public.ets_event_tiers SET is_visible = true WHERE id = $1`, [T.hidden])).n, 1, `${label}: the owner sees and changes a hidden tier`);

  // ─── 6. The checks after; the rollback ─────────────────────────────────
  const post = checkBlock(APPLY, '-- Check after (read-only):');
  eq(post.length, 9, `${label}: nine checks after`);
  const postAnswers = [];
  for (const q of post) postAnswers.push(await asRunner(db, ownedBy, q));
  const [aPolicies, aOpen, aGrants, aEvents, aAuthenticated, aFunctions, aViews, aBucket, aAnswers] = postAnswers;
  const roles = r => Array.isArray(r) ? `{${r.join(',')}}` : String(r);
  eq(aPolicies.map(r => `${r.tablename}.${r.policyname}.${r.cmd}.${roles(r.roles)}`), [
    'ets_agent_log.ets_owner_all.ALL.{authenticated}',
    'ets_emails.ets_owner_all.ALL.{authenticated}',
    'ets_engagements.ets_owner_all.ALL.{authenticated}',
    'ets_event_files.ets_owner_all.ALL.{authenticated}',
    'ets_event_files.ets_public_read_live_files.SELECT.{anon}',
    'ets_event_tiers.ets_owner_all.ALL.{authenticated}',
    'ets_event_tiers.ets_public_read_live_tiers.SELECT.{anon}',
    'ets_events.ets_owner_all.ALL.{authenticated}',
    'ets_events.ets_public_read_events.SELECT.{anon}',
    'ets_inquiries.ets_owner_all.ALL.{authenticated}',
    'ets_inquiries.ets_public_send_inquiry.INSERT.{anon,authenticated}',
    'ets_registrations.ets_owner_all.ALL.{authenticated}',
    'ets_registrations.ets_public_register.INSERT.{anon,authenticated}',
    'ets_sessions_log.ets_owner_all.ALL.{authenticated}',
    'ets_signatures.ets_owner_all.ALL.{authenticated}',
  ], `${label}: check after 1, the 15 policies`);
  eq(Number(aOpen[0].open_policies), 0, `${label}: check after 2, nothing open`);
  eq(aGrants.map(r => `${r.table_name}:${r.anon_may}`), ['ets_event_files:SELECT', 'ets_event_tiers:SELECT',
    'ets_inquiries:INSERT', 'ets_registrations:INSERT'], `${label}: check after 3, anon's table grants`);
  eq([aEvents[0].reads_virtual_link, aEvents[0].reads_notes, aEvents[0].reads_table, aEvents[0].columns],
    [false, false, false, eventColumns.filter(c => !PRIVATE.includes(c)).sort().join(', ')], `${label}: check after 4, anon on ets_events`);
  eq(Number(aAuthenticated[0].left_over), 0, `${label}: check after 5, authenticated truncates nothing`);
  eq(aFunctions.map(r => [r.security_definer, r.settings]), [[true, ['search_path=public']], [true, ['search_path=public']],
    [true, ['search_path=public']]], `${label}: check after 6, the functions`);
  eq(aFunctions.find(r => String(r.function).startsWith('ets_registration_confirmation')).anon_may_call, true,
    `${label}: check after 6, anon may call the confirmation`);
  eq(aViews.map(r => [String(r.view), r.reloptions, r.anon_may_read]).sort((a, b) => a[0].localeCompare(b[0])),
    [...VIEWS, INVOKER_VIEW].sort().map(v => [v, ['security_invoker=true'], false]), `${label}: check after 7, the views`);
  eq(aBucket.map(r => [r.policyname, r.cmd, /is_platform_owner\(\)/.test(`${r.qual} ${r.with_check}`)]), [
    ['Allow public read', 'SELECT', false], ['ets write: ets-event-files delete', 'DELETE', true],
    ['ets write: ets-event-files insert', 'INSERT', true]], `${label}: check after 8, the bucket`);
  eq([aAnswers[0].empty_ref, aAnswers[0].finds_one], [true, true], `${label}: check after 9, the function answers`);

  await runFile(db, ROLLBACK, ownedBy);
  await runFile(db, ROLLBACK, ownedBy);
  const back = await snapshot(db);
  eq(back, before, `${label}: the rollback puts the policies (storage's too), grants, functions and views back as they were`);
  eq((await su(db, `SELECT reloptions, has_table_privilege('anon', oid, 'select') AS anon_reads FROM pg_class WHERE relname = $1`, [INVOKER_VIEW])),
    [{ reloptions: ['security_invoker=true'], anon_reads: false }], `${label}: a view that already ran as the caller still does`);
  eq((await as(db, 'anon', `SELECT virtual_link FROM public.ets_events WHERE id = $1`, [E.virt])).rows.length, 1,
    `${label}: the rollback gives anon the virtual link back`);
  went(await as(db, 'stranger', `INSERT INTO storage.objects (bucket_id, name) VALUES ('${BUCKET}', 'x.png')`),
    `${label}: and any login the bucket`);
  ok((await as(db, 'anon', 'SELECT * FROM public.ets_inquiries')).rows.length > 0, `${label}: and reopens the hole: anon reads inquiries`);
  went(await as(db, 'anon', 'DELETE FROM public.ets_emails'), `${label}: anon may delete again`);
  ok((await as(db, 'stranger', 'SELECT * FROM public.ets_engagements')).rows.length === 1, `${label}: any login reads again`);
  ok((await as(db, 'anon', 'SELECT * FROM public.ets_pending_agent_actions')).ok, `${label}: the views are open again`);
  {
    const reg = registration(50, T.free);
    const cols = Object.keys(reg);
    const r = await as(db, 'anon', `INSERT INTO public.ets_registrations (${cols.join(', ')}) VALUES (${cols.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING id`, Object.values(reg));
    ok(r.ok, `${label}: the live site's registration works again (${r.error || ''})`);
  }
  eq((await confirm(db, 'anon', R.pending)).id, R.pending, `${label}: the rollback keeps the confirmation function for the new site`);

  await runFile(db, APPLY, ownedBy);
  refused(await as(db, 'anon', 'SELECT * FROM public.ets_inquiries'), `${label}: the file applies again after the rollback`);
  eq((await snapshot(db)).policies.length, 15, `${label}: with its 15 policies`);
  await db.close();
}

// Production has no address column. If a database does: the function
// answers it over the venue address, and anon's column list, read from the
// catalog, takes it in.
async function addressColumns() {
  const label = 'with an address column';
  const db = await build({ ownedBy: null });
  await db.exec(`ALTER TABLE public.ets_events ADD COLUMN address text;
    UPDATE public.ets_events SET address = '7 Hand Entered Way' WHERE id = '${E.pub}';`);
  await runFile(db, APPLY, null);
  const c = await confirm(db, 'anon', R.pending);
  eq([c.ets_events.address, c.ets_events.timezone], ['7 Hand Entered Way', 'CT'], `${label}: the event's own address`);
  await db.exec(`UPDATE public.ets_events SET address = NULL WHERE id = '${E.pub}'`);
  eq((await confirm(db, 'anon', R.pending)).ets_events.address, '100 Main St', `${label}: no address, the venue address`);
  went(await as(db, 'anon', 'SELECT address, timezone FROM public.ets_events'), `${label}: anon reads the added column`);
  refused(await as(db, 'anon', 'SELECT virtual_link FROM public.ets_events'), `${label}: and still not the link`);
  await db.close();
}

await scenario({ ownedBy: null });
await scenario({ ownedBy: 'ets_admin' });
await addressColumns();
console.log(`ets_close_policies_db: ${checks} checks passed`);
