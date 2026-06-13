-- 2026_06_13_drl_pr1.sql
-- Design Rationale Layer — PR1 foundation tables (fork F1 RULED: dedicated tables).
--
--   design_rationales — the auditable DRO Chief authors BEFORE generation.
--                       Stored per generation, history kept (superseded_by),
--                       renderable to the practitioner ("why your site looks
--                       this way"). Schema of the `dro` blob: agents/composer/
--                       drl/schema.json.
--   design_feedback   — accepted/edited/regenerated outcomes per DRO, with a
--                       structured axis diff (spec §6). Feeds exemplar
--                       win/loss weighting (v1 = a sort, no ML).
--
-- Writes go through the Railway service role (the DRO authoring pass + the
-- feedback hooks). RLS lets a practitioner READ only their own businesses'
-- rows. Owner-read uses a one-directional EXISTS against businesses
-- (businesses' own policy does not reference these tables → no 42P17 cycle;
-- matches the established plaid_schema per-business pattern).

-- ─── design_rationales ──────────────────────────────────────────────
create table if not exists public.design_rationales (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null,
  dro           jsonb not null,                 -- the Design Rationale Object (drl/schema.json)
  created_at    timestamptz not null default now(),
  superseded_by uuid references public.design_rationales(id)
);

create index if not exists idx_design_rationales_business
  on public.design_rationales (business_id, created_at desc);

alter table public.design_rationales enable row level security;

drop policy if exists design_rationales_select_own on public.design_rationales;
create policy design_rationales_select_own on public.design_rationales
  for select using (
    exists (
      select 1 from public.businesses b
      where b.id = design_rationales.business_id
        and b.owner_id = auth.uid()
    )
  );

grant select, insert, update, delete on public.design_rationales to service_role;

-- ─── design_feedback ────────────────────────────────────────────────
create table if not exists public.design_feedback (
  id                uuid primary key default gen_random_uuid(),
  business_id       uuid not null,
  dro_id            uuid references public.design_rationales(id),
  verdict           text not null check (verdict in
                      ('accepted_as_is','accepted_with_edits','regenerated','abandoned')),
  edited_axes       text[],                      -- subset of: palette,typography,layout,motion,hero_concept,whitespace,copy
  edit_detail       jsonb,                       -- structured diff: {"palette":{"from":"deep_dark","to":"warm_light"}}
  practitioner_note text,                         -- optional verbatim ("too dark", "love the arcs")
  created_at        timestamptz not null default now()
);

create index if not exists idx_design_feedback_business
  on public.design_feedback (business_id, created_at desc);
create index if not exists idx_design_feedback_dro
  on public.design_feedback (dro_id);

alter table public.design_feedback enable row level security;

drop policy if exists design_feedback_select_own on public.design_feedback;
create policy design_feedback_select_own on public.design_feedback
  for select using (
    exists (
      select 1 from public.businesses b
      where b.id = design_feedback.business_id
        and b.owner_id = auth.uid()
    )
  );

grant select, insert, update, delete on public.design_feedback to service_role;
