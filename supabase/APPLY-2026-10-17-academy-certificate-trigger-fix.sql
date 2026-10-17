-- Apply after APPLY-2026-10-17-academy-student-side.sql.
-- Fix: an owner marking a student's class finished in Course Studio (a
-- signed-in PATCH of academy_enrollments.status = 'completed') failed with
-- "permission denied for function academy_new_certificate_code". The
-- certificate trigger ran as the signed-in user, and the code maker is
-- server-only. The trigger now runs as its owner, as the code maker needs;
-- the student's own path (academy_complete_lesson) already did.
begin;
alter function public.academy_issue_certificate() security definer;
commit;
