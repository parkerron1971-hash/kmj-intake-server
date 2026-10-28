-- ChurchSavvy Planning, step 5: the Sunday pack (design canvas
-- Ct88v7pxpq5a4PGYX3MuQQ, board 9 "Pack": "I'm here"). Server-only, like
-- the rest of serve_*.
--
--   serve_assignments.here_at   when someone serving that day tapped "I'm
--                               here" in the member app; the team's leader
--                               and the booth see who's arrived. Cleared when
--                               the place moves to someone else.
-- Idempotent.
begin;

alter table public.serve_assignments add column if not exists here_at timestamptz;

commit;
