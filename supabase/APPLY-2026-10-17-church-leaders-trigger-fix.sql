-- Leaders & follow-up: the same-business trigger refused every leader role
-- and every note (Kevin, 2026-10-17: "the ability to assign and save
-- leaders with invite is not working").
--
-- PL/pgSQL resolves every field an IF names before it tests the IF, so
--   if tg_table_name = 'church_follow_ups' and new.leader_contact_id is not null
-- raised "record new has no field leader_contact_id" on church_leader_roles
-- and church_follow_up_notes, which have no such column: no role could be
-- asked and no note written (a follow-up itself saved). Each table's field
-- is now read only inside an IF that has already picked the table.
-- Idempotent.
begin;

create or replace function public.church_leaders_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name in ('church_leader_roles','church_follow_ups') then
    if not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  if tg_table_name = 'church_follow_ups' then
    if new.leader_contact_id is not null then
      if not exists (select 1 from public.contacts c
                     where c.id = new.leader_contact_id and c.business_id = new.business_id) then
        raise exception 'That leader is not in this business';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_follow_up_notes' then
    if not exists (select 1 from public.church_follow_ups f
                   where f.id = new.follow_up_id and f.business_id = new.business_id) then
      raise exception 'That follow-up is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_leaders_same_business() from public, anon, authenticated;

commit;
