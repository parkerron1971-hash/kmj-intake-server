// A private class on a real Postgres (PGlite): supabase/APPLY-2026-11-08-academy-private-class.sql
// over the policies production has today (read from pg_policies 2026-11-08).
// Each person below signs in as themselves and reads through RLS, so this holds
// what a string check can't: an office login reads none of a private class, its
// owner and teachers still do, no policy recurses, and nobody but the owner can
// turn private off.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/academy_private_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const db = new PGlite();
const church = '11111111-1111-4111-8111-111111111111', other = '22222222-2222-4222-8222-222222222222';
const pastor = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', office = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const teacher = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', stranger = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const openClass = 'e0000000-0000-4000-8000-000000000001', quiet = 'e0000000-0000-4000-8000-000000000002';

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ select nullif(current_setting('app.uid', true), '')::uuid $$;
  GRANT USAGE ON SCHEMA auth TO authenticated;
  GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated;
  CREATE TABLE auth.users(id uuid PRIMARY KEY, email text, email_confirmed_at timestamptz);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.business_users(business_id uuid, user_id uuid, status text, role text);
  CREATE TABLE public.academy_courses(id uuid PRIMARY KEY, business_id uuid NOT NULL, title text,
    status text NOT NULL DEFAULT 'published', self_join boolean NOT NULL DEFAULT true, product_id uuid);
  CREATE TABLE public.academy_lessons(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL, course_id uuid NOT NULL, title text);
  CREATE TABLE public.academy_enrollments(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL, course_id uuid NOT NULL,
    contact_id uuid, portal_token uuid DEFAULT gen_random_uuid(), notes text);
  CREATE TABLE public.academy_schedule_items(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL, course_id uuid NOT NULL, title text);
  CREATE TABLE public.academy_teachers(course_id uuid, email text, role text);

  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    select exists (select 1 from public.business_users bu where bu.business_id = b and bu.user_id = auth.uid() and bu.status = 'active') $$;
  CREATE FUNCTION public.academy_can_teach(p_course uuid, p_edit boolean DEFAULT false) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    select exists(select 1 from public.academy_courses c join public.businesses b on b.id = c.business_id where c.id = p_course and b.owner_id = auth.uid())
      or exists(select 1 from public.academy_teachers t join auth.users u on lower(u.email) = t.email
                 where t.course_id = p_course and u.id = auth.uid() and u.email_confirmed_at is not null and (not p_edit or t.role = 'teacher')) $$;

  ALTER TABLE public.academy_courses ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.academy_lessons ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.academy_enrollments ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.academy_schedule_items ENABLE ROW LEVEL SECURITY;
  GRANT SELECT, UPDATE ON public.academy_courses, public.academy_lessons, public.academy_enrollments, public.academy_schedule_items TO authenticated;
  GRANT SELECT ON public.businesses TO authenticated;

  -- The policies production has today, as pg_policies reads them.
  CREATE POLICY academy_courses_owner ON public.academy_courses FOR ALL
    USING (EXISTS (SELECT 1 FROM public.businesses b WHERE b.id = academy_courses.business_id AND b.owner_id = auth.uid()));
  CREATE POLICY academy_courses_teacher_read ON public.academy_courses FOR SELECT TO authenticated USING (public.academy_can_teach(id));
  CREATE POLICY tenant_member_read ON public.academy_courses FOR SELECT TO authenticated USING (public.is_business_member(business_id));
  CREATE POLICY academy_lessons_owner ON public.academy_lessons FOR ALL
    USING (EXISTS (SELECT 1 FROM public.businesses b WHERE b.id = academy_lessons.business_id AND b.owner_id = auth.uid()));
  CREATE POLICY academy_lessons_teacher_read ON public.academy_lessons FOR SELECT TO authenticated USING (public.academy_can_teach(course_id));
  CREATE POLICY academy_lessons_teacher_write ON public.academy_lessons FOR ALL TO authenticated USING (public.academy_can_teach(course_id, true));
  CREATE POLICY tenant_member_read ON public.academy_lessons FOR SELECT TO authenticated USING (public.is_business_member(business_id));
  CREATE POLICY academy_enrollments_owner ON public.academy_enrollments FOR ALL
    USING (EXISTS (SELECT 1 FROM public.businesses b WHERE b.id = academy_enrollments.business_id AND b.owner_id = auth.uid()));
  CREATE POLICY tenant_member_read ON public.academy_enrollments FOR SELECT TO authenticated USING (public.is_business_member(business_id));
  CREATE POLICY academy_schedule_items_read ON public.academy_schedule_items FOR SELECT TO authenticated
    USING (public.academy_can_teach(course_id) OR public.is_business_member(business_id));
  CREATE POLICY academy_schedule_items_write ON public.academy_schedule_items FOR ALL TO authenticated USING (public.academy_can_teach(course_id, true));`);

await db.query('INSERT INTO businesses VALUES ($1,$2),($3,$4)', [church, pastor, other, stranger]);
await db.query(`INSERT INTO business_users VALUES ($1,$2,'active','manager'),($1,$3,'active','member')`, [church, office, teacher]);
await db.query(`INSERT INTO auth.users VALUES ($1,'teacher@church.test',now())`, [teacher]);
await db.query(`INSERT INTO academy_courses(id, business_id, title) VALUES ($1,$3,'New Members'),($2,$3,'Ordination Training')`, [openClass, quiet, church]);
await db.query(`INSERT INTO academy_teachers VALUES ($1,'teacher@church.test','teacher')`, [quiet]);
for (const c of [openClass, quiet]) {
  await db.query(`INSERT INTO academy_lessons(business_id, course_id, title) VALUES ($1,$2,'Week 1')`, [church, c]);
  await db.query(`INSERT INTO academy_enrollments(business_id, course_id, notes) VALUES ($1,$2,'a teacher''s note')`, [church, c]);
  await db.query(`INSERT INTO academy_schedule_items(business_id, course_id, title) VALUES ($1,$2,'Homework')`, [church, c]);
}

const sql = await readFile(new URL('../supabase/APPLY-2026-11-08-academy-private-class.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);   // idempotent

let checks = 0;
const TABLES = { academy_courses: 'id', academy_lessons: 'course_id', academy_enrollments: 'course_id', academy_schedule_items: 'course_id' };
// Every row this person can read in each class table, as that person, through RLS.
const reads = async who => {
  await db.exec(`SET app.uid = '${who}'; SET ROLE authenticated;`);
  const out = {};
  for (const [table, col] of Object.entries(TABLES)) {
    out[table] = (await db.query(`SELECT ${col} AS course FROM public.${table}`)).rows.map(r => r.course).sort();
  }
  await db.exec(`RESET ROLE; SET app.uid = '';`);
  return out;
};
const sees = (got, want, who) => {
  for (const table of Object.keys(TABLES)) {
    assert.deepEqual(got[table], [...want].sort(), `${who} on ${table}`);
    checks++;
  }
};
const flip = async (who, value) => {
  await db.exec(`SET app.uid = '${who}'; SET ROLE authenticated;`);
  const r = await db.query('UPDATE public.academy_courses SET private = $1 WHERE id = $2', [value, quiet]);
  await db.exec(`RESET ROLE; SET app.uid = '';`);
  return r.affectedRows;
};
const openToJoin = async id => (await db.query(
  'SELECT public.academy_course_open(c) AS open FROM public.academy_courses c WHERE id = $1', [id])).rows[0].open;

// Off by default: running the migration changes nothing for anyone.
sees(await reads(office), [openClass, quiet], 'an office login, before anything is private');
assert.equal(await openToJoin(quiet), true); checks++;

// The owner makes it private.
assert.equal(await flip(pastor, true), 1); checks++;

sees(await reads(office), [openClass], 'an office login');
sees(await reads(pastor), [openClass, quiet], 'the owner');
sees(await reads(stranger), [], "another church's owner");

// A named teacher who also holds an office login keeps the whole class, roster included.
sees(await reads(teacher), [openClass, quiet], 'a named teacher');

// Nobody can reach it by asking for its id.
await db.exec(`SET app.uid = '${office}'; SET ROLE authenticated;`);
assert.equal((await db.query('SELECT portal_token FROM public.academy_enrollments WHERE course_id = $1', [quiet])).rows.length, 0,
  "her class link isn't readable by id"); checks++;
assert.equal((await db.query('SELECT title FROM public.academy_courses WHERE id = $1', [quiet])).rows.length, 0); checks++;
await db.exec(`RESET ROLE; SET app.uid = '';`);

// Only the owner can turn it off.
assert.equal(await flip(office, false), 0, 'an office login can not'); checks++;
assert.equal(await flip(teacher, false), 0, 'a teacher can not'); checks++;
assert.equal((await db.query('SELECT private FROM public.academy_courses WHERE id = $1', [quiet])).rows[0].private, true); checks++;

// It takes no sign-ups, whatever self_join says; any other class still does.
assert.equal(await openToJoin(quiet), false); checks++;
assert.equal(await openToJoin(openClass), true); checks++;

// The helper is false for a class that isn't there, and anon can't call it.
assert.equal((await db.query('SELECT public.academy_course_private($1) AS p', [other])).rows[0].p, false); checks++;
await db.exec('SET ROLE anon;');
await assert.rejects(db.query('SELECT public.academy_course_private($1)', [quiet]), /permission denied/); checks++;
await db.exec('RESET ROLE;');

// The owner can open it back up, and the office sees it again.
assert.equal(await flip(pastor, false), 1); checks++;
sees(await reads(office), [openClass, quiet], 'an office login, after the owner turned it off');

await db.close();
console.log(`academy_private_db: ${checks} checks passed`);
