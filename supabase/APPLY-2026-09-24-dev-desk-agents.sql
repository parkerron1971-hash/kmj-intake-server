-- Dev Desk agents (2026-09-24). A local task names the coding agent that
-- works it in Solution Space: Claude Code (the default, and every task before
-- this file) or Codex. The device records which agents its build can open,
-- so the Dev Desk can say whether Codex is reachable, and the queue only
-- hands a Codex task to a Solution Space that can open one — an older build
-- that ignores the field would otherwise open it as Claude.
--
-- The agent joins the authorized scope that the immutability trigger guards:
-- a task approved for Codex cannot be quietly handed to another agent.
--
-- Additive and idempotent. Safe to apply BEFORE the code ships: old code
-- neither reads nor writes these columns, and the default keeps its inserts
-- valid.
begin;

alter table public.dev_tasks
  add column if not exists agent text not null default 'claude';
alter table public.dev_tasks drop constraint if exists dev_tasks_agent_check;
alter table public.dev_tasks
  add constraint dev_tasks_agent_check check (agent in ('claude', 'codex'));

alter table public.dev_bridge_devices
  add column if not exists agents text[];

create or replace function public.dev_task_authority_immutable() returns trigger
language plpgsql set search_path=public as $$
begin
  if old.authority_record is not null and
     (new.authority_record,new.lane,new.repo,new.project_path,new.title,new.details,new.agent)
     is distinct from
     (old.authority_record,old.lane,old.repo,old.project_path,old.title,old.details,old.agent) then
    raise exception 'Authorized development scope is immutable';
  end if;
  return new;
end $$;

commit;
