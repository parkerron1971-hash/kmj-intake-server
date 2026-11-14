-- APPLY-2026-11-14-church-mail-signature.sql
--
-- Each person's own signature for church mail (church_mail_room.py).
-- Kevin, 2026-11-14: "add where the signature can be edited. just incase
-- they want to change up how it looks."
--
--   church_mail_people   + signature   the login's own signature, as typed
--                                        (at most 8 lines, 600 characters);
--                                        null = the standard one: their
--                                        name, the church, the address the
--                                        mail goes from
--
-- Additive only: one column, nullable, no default, so nothing is rewritten
-- and every existing row keeps the standard signature. One transaction,
-- safe to run twice. Until it is applied the room reads every signature as
-- the standard one and saving one says it can't be saved yet.
begin;

set local lock_timeout = '5s';

alter table public.church_mail_people add column if not exists signature text;

alter table public.church_mail_people drop constraint if exists church_mail_people_signature_length;
alter table public.church_mail_people add constraint church_mail_people_signature_length
  check (signature is null or char_length(signature) between 1 and 600);

comment on column public.church_mail_people.signature is
  'The login''s own signature under church mail it sends from the Email room (church_mail_room.signature_lines). Null: the standard one (name, church, the address it goes from).';

commit;

-- Check:
--   select data_type, is_nullable from information_schema.columns
--     where table_schema = 'public' and table_name = 'church_mail_people' and column_name = 'signature';
--   -- text, YES
--   select pg_get_constraintdef(oid) from pg_constraint where conname = 'church_mail_people_signature_length';
--   -- CHECK (((signature IS NULL) OR ((char_length(signature) >= 1) AND (char_length(signature) <= 600))))
--
-- Rollback (everyone goes back to the standard signature):
--   alter table public.church_mail_people drop constraint if exists church_mail_people_signature_length;
--   alter table public.church_mail_people drop column if exists signature;
