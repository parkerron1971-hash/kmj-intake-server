-- Each office login is its own person (business_users_router.seat_person,
-- Kevin 2026-10-28: the people he invited "went to sign up and it greeted
-- them as Kevin"). Every "you" in the app read the business's own name for
-- its owner, because a seat had no name of its own and nothing tied it to
-- the church's record of that person.
--
--   business_users.contact_id   the person this login is (contacts): set at
--                               the invite when it names them, or at accept
--                               from the invite's email; the member app finds
--                               the same record by the same email
--   business_users.name         the name they gave when they signed up, for
--                               a login no record names
--
-- Additive only. Apply before the code: the team list and the invite page
-- read both columns. Rollback: drop the two columns.

alter table public.business_users
  add column if not exists contact_id uuid references public.contacts(id) on delete set null;
alter table public.business_users add column if not exists name text;
