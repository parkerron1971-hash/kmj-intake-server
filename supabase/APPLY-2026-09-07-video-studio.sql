BEGIN;
-- Private media follows the existing media-library boundary: browser roles
-- have no table/storage grants; every API operation verifies a manager seat.
CREATE TABLE public.video_projects (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL REFERENCES public.businesses ON DELETE CASCADE,
 created_by uuid NOT NULL, title text NOT NULL CHECK(length(title) BETWEEN 1 AND 160), brief text NOT NULL DEFAULT '',
 format text NOT NULL DEFAULT 'landscape' CHECK(format IN ('landscape','portrait','square')),
 revision integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.video_assets (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL REFERENCES public.businesses ON DELETE CASCADE,
 project_id uuid NOT NULL REFERENCES public.video_projects ON DELETE CASCADE, created_by uuid NOT NULL,
 name text NOT NULL, mime_type text NOT NULL, byte_size bigint NOT NULL CHECK(byte_size BETWEEN 1 AND 104857600),
 sha256 text NOT NULL, object_path text NOT NULL UNIQUE, duration_seconds double precision,
 purpose text NOT NULL CHECK(purpose IN ('include','reference')), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.video_revisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL REFERENCES public.businesses ON DELETE CASCADE,
 project_id uuid NOT NULL REFERENCES public.video_projects ON DELETE CASCADE, revision integer NOT NULL,
 label text NOT NULL, composition jsonb NOT NULL, assets jsonb NOT NULL, created_by uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(project_id,revision), UNIQUE(project_id,id)
);
CREATE TABLE public.video_messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL REFERENCES public.businesses ON DELETE CASCADE,
 project_id uuid NOT NULL REFERENCES public.video_projects ON DELETE CASCADE,
 role text NOT NULL CHECK(role IN ('user','assistant')), content text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.video_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL REFERENCES public.businesses ON DELETE CASCADE,
 project_id uuid NOT NULL REFERENCES public.video_projects ON DELETE CASCADE, created_by uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('plan','render')), revision_id uuid, expected_revision integer NOT NULL,
 request_id uuid NOT NULL, request jsonb NOT NULL, status text NOT NULL DEFAULT 'queued'
 CHECK(status IN ('queued','working','completed','failed','cancelled')),
 stage text NOT NULL DEFAULT 'queued', progress integer CHECK(progress BETWEEN 0 AND 100),
 attempt integer NOT NULL DEFAULT 0, lease_id uuid, lease_until timestamptz,
 output_path text, output_sha256 text, output_bytes bigint, duration_seconds double precision, error text,
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 UNIQUE(project_id,request_id), FOREIGN KEY(project_id,revision_id) REFERENCES public.video_revisions(project_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX video_project_one_job ON public.video_jobs(project_id) WHERE status IN ('queued','working');
CREATE INDEX video_jobs_queue ON public.video_jobs(status,created_at);
CREATE INDEX video_projects_business ON public.video_projects(business_id,updated_at DESC);
CREATE INDEX video_assets_project ON public.video_assets(project_id);
CREATE INDEX video_messages_project ON public.video_messages(project_id,created_at);
ALTER TABLE public.video_projects ADD UNIQUE(id,business_id);
ALTER TABLE public.video_assets ADD FOREIGN KEY(project_id,business_id) REFERENCES public.video_projects(id,business_id) ON DELETE CASCADE;
ALTER TABLE public.video_revisions ADD FOREIGN KEY(project_id,business_id) REFERENCES public.video_projects(id,business_id) ON DELETE CASCADE;
ALTER TABLE public.video_messages ADD FOREIGN KEY(project_id,business_id) REFERENCES public.video_projects(id,business_id) ON DELETE CASCADE;
ALTER TABLE public.video_jobs ADD FOREIGN KEY(project_id,business_id) REFERENCES public.video_projects(id,business_id) ON DELETE CASCADE;

CREATE FUNCTION public.guard_video_asset() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE p uuid; b uuid;
BEGIN
 p:=CASE WHEN TG_OP='DELETE' THEN OLD.project_id ELSE NEW.project_id END;
 b:=CASE WHEN TG_OP='DELETE' THEN OLD.business_id ELSE NEW.business_id END;
 PERFORM id FROM businesses WHERE id=b FOR UPDATE;
 PERFORM id FROM video_projects WHERE id=p FOR UPDATE;
 IF EXISTS(SELECT 1 FROM video_jobs WHERE project_id=p AND status IN ('queued','working')) THEN
  RAISE EXCEPTION 'Cancel or finish the active job before changing media'; END IF;
 IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'purpose') IS DISTINCT FROM (to_jsonb(OLD)-'purpose') THEN
  RAISE EXCEPTION 'Uploaded media is immutable'; END IF;
 IF TG_OP='INSERT' AND ((SELECT count(*) FROM video_assets WHERE project_id=p)>=12 OR
  (SELECT coalesce(sum(byte_size),0) FROM video_assets WHERE project_id=p)+NEW.byte_size>314572800 OR
  (SELECT coalesce(sum(byte_size),0) FROM video_assets WHERE business_id=b)+NEW.byte_size>5368709120) THEN
  RAISE EXCEPTION 'Video media allowance reached'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_video_asset BEFORE INSERT OR UPDATE OR DELETE ON public.video_assets FOR EACH ROW EXECUTE FUNCTION public.guard_video_asset();
CREATE FUNCTION public.immutable_video_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Save a new video revision instead of overwriting history'; END $$;
CREATE TRIGGER immutable_video_revision BEFORE UPDATE ON public.video_revisions FOR EACH ROW EXECUTE FUNCTION public.immutable_video_revision();

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['video_projects','video_assets','video_revisions','video_messages','video_jobs'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM anon,authenticated',t);
  EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
 END LOOP;
END $$;
INSERT INTO storage.buckets(id,name,public,file_size_limit) VALUES('video-studio','video-studio',false,536870912)
 ON CONFLICT(id) DO UPDATE SET public=false,file_size_limit=536870912;
CREATE POLICY private_video_studio_boundary ON storage.objects AS RESTRICTIVE FOR ALL TO anon,authenticated
 USING(bucket_id <> 'video-studio') WITH CHECK(bucket_id <> 'video-studio');

CREATE FUNCTION public.video_actor_allowed(b uuid,a uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=public AS $$
 SELECT EXISTS(SELECT 1 FROM businesses WHERE id=b AND owner_id=a) OR EXISTS(
 SELECT 1 FROM business_users WHERE business_id=b AND user_id=a AND status='active' AND role IN ('manager','admin'));
$$;

CREATE FUNCTION public.save_video_revision(p_business_id uuid,p_project_id uuid,p_actor_id uuid,p_expected integer,
 p_composition jsonb,p_label text,p_message text DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql SET search_path=public AS $$
DECLARE p video_projects; r video_revisions; snapshot jsonb;
BEGIN
 IF NOT video_actor_allowed(p_business_id,p_actor_id) THEN RAISE EXCEPTION 'Access denied'; END IF;
 SELECT * INTO p FROM video_projects WHERE id=p_project_id AND business_id=p_business_id FOR UPDATE;
 IF NOT FOUND OR p.revision<>p_expected THEN RETURN jsonb_build_object('conflict',true); END IF;
 IF EXISTS(SELECT 1 FROM video_jobs WHERE project_id=p.id AND kind='render' AND status IN ('queued','working')) THEN
  RETURN jsonb_build_object('refused','Finish or cancel the render before changing this project.'); END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(a)),'[]') INTO snapshot FROM video_assets a WHERE project_id=p.id AND business_id=p_business_id;
 INSERT INTO video_revisions(business_id,project_id,revision,label,composition,assets,created_by)
 VALUES(p_business_id,p.id,p.revision+1,p_label,p_composition,snapshot,p_actor_id) RETURNING * INTO r;
 UPDATE video_projects SET revision=r.revision,title=p_composition->>'title',format=p_composition->>'format',updated_at=now() WHERE id=p.id;
 IF p_message IS NOT NULL THEN INSERT INTO video_messages(business_id,project_id,role,content) VALUES(p_business_id,p.id,'assistant',p_message); END IF;
 RETURN to_jsonb(r);
END $$;

CREATE FUNCTION public.enqueue_video_job(p_business_id uuid,p_project_id uuid,p_actor_id uuid,p_kind text,
 p_revision_id uuid,p_expected integer,p_request_id uuid,p_request jsonb) RETURNS jsonb LANGUAGE plpgsql SET search_path=public AS $$
DECLARE p video_projects; j video_jobs; d double precision;
BEGIN
 IF NOT video_actor_allowed(p_business_id,p_actor_id) THEN RAISE EXCEPTION 'Access denied'; END IF;
 PERFORM id FROM businesses WHERE id=p_business_id FOR UPDATE;
 SELECT * INTO p FROM video_projects WHERE id=p_project_id AND business_id=p_business_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Project not found'; END IF;
 SELECT * INTO j FROM video_jobs WHERE project_id=p.id AND request_id=p_request_id;
 IF FOUND THEN RETURN to_jsonb(j); END IF;
 IF p.revision<>p_expected THEN RETURN jsonb_build_object('conflict',true); END IF;
 IF EXISTS(SELECT 1 FROM video_jobs WHERE project_id=p.id AND status IN ('queued','working')) THEN
  RETURN jsonb_build_object('refused','Chief is already working on this project.'); END IF;
 IF (SELECT count(*) FROM video_jobs WHERE business_id=p_business_id AND created_at>now()-interval '1 hour')>=20 THEN
  RETURN jsonb_build_object('refused','The hourly video limit has been reached. Try again later.'); END IF;
 IF p_kind='render' THEN
  SELECT sum((s->>'seconds')::double precision) INTO d FROM video_revisions r,
   LATERAL jsonb_array_elements(r.composition->'scenes') s WHERE r.id=p_revision_id AND r.project_id=p.id AND r.revision=p.revision;
  IF d IS NULL OR d>180 THEN RAISE EXCEPTION 'Choose the current revision, up to three minutes'; END IF;
  IF EXISTS(SELECT 1 FROM video_revisions r, LATERAL jsonb_array_elements(r.composition->'scenes') s
   WHERE r.id=p_revision_id AND s->>'asset_id' IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM video_assets a WHERE a.id=(s->>'asset_id')::uuid AND a.project_id=p.id AND a.purpose='include')) THEN
   RAISE EXCEPTION 'A scene uses missing or reference-only media'; END IF;
  IF EXISTS(SELECT 1 FROM video_revisions r WHERE r.id=p_revision_id AND r.composition->>'music_asset_id' IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM video_assets a WHERE a.id=(r.composition->>'music_asset_id')::uuid AND a.project_id=p.id AND a.purpose='include')) THEN
   RAISE EXCEPTION 'The soundtrack uses missing or reference-only media'; END IF;
  IF (SELECT coalesce(sum(duration_seconds),0) FROM video_jobs WHERE business_id=p_business_id AND kind='render'
   AND created_at>now()-interval '24 hours' AND status<>'cancelled')+d>1800 THEN
   RETURN jsonb_build_object('refused','Your daily video render allowance has been reached.'); END IF;
 END IF;
 INSERT INTO video_jobs(business_id,project_id,created_by,kind,revision_id,expected_revision,request_id,request,duration_seconds)
 VALUES(p_business_id,p.id,p_actor_id,p_kind,p_revision_id,p_expected,p_request_id,p_request,d) RETURNING * INTO j;
 IF p_kind='plan' THEN
  IF NOT EXISTS(SELECT 1 FROM video_messages WHERE project_id=p.id AND role='user') THEN
   UPDATE video_projects SET brief=p_request->>'message',updated_at=now() WHERE id=p.id;
  END IF;
  INSERT INTO video_messages(business_id,project_id,role,content) VALUES(p_business_id,p.id,'user',p_request->>'message');
 END IF;
 RETURN to_jsonb(j);
END $$;

CREATE FUNCTION public.claim_video_job() RETURNS jsonb LANGUAGE plpgsql SET search_path=public AS $$
DECLARE j video_jobs;
BEGIN
 IF NOT pg_try_advisory_xact_lock(20260907,82) THEN RETURN NULL; END IF;
 UPDATE video_jobs SET status=CASE WHEN kind='render' AND attempt<2 THEN 'queued' ELSE 'failed' END,
 stage='interrupted',error='Processing was interrupted. Your saved project is safe.',lease_id=NULL,lease_until=NULL
 WHERE status='working' AND lease_until<now();
 -- Bound simultaneous cloud renders even if another worker replica starts.
 IF EXISTS(SELECT 1 FROM video_jobs WHERE status='working') THEN RETURN NULL; END IF;
 SELECT * INTO j FROM video_jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 UPDATE video_jobs SET status='working',stage='preparing',attempt=attempt+1,lease_id=gen_random_uuid(),
 lease_until=now()+interval '2 minutes',error=NULL WHERE id=j.id RETURNING * INTO j;
 RETURN to_jsonb(j);
END $$;

CREATE FUNCTION public.finish_video_plan(p_job_id uuid,p_lease uuid,p_composition jsonb,p_message text) RETURNS jsonb
 LANGUAGE plpgsql SET search_path=public AS $$
DECLARE j video_jobs; result jsonb;
BEGIN
 SELECT * INTO j FROM video_jobs WHERE id=p_job_id AND lease_id=p_lease AND status='working' FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('cancelled',true); END IF;
 IF NOT video_actor_allowed(j.business_id,j.created_by) THEN RAISE EXCEPTION 'Access denied'; END IF;
 IF p_composition IS NOT NULL THEN
  result:=save_video_revision(j.business_id,j.project_id,j.created_by,j.expected_revision,p_composition,'Chief revision',p_message);
  IF result->>'conflict'='true' THEN
   UPDATE video_jobs SET status='failed',stage='failed',error='The project changed. Ask Chief again using your latest revision.',finished_at=now() WHERE id=j.id;
   RETURN result;
  END IF;
 ELSE
  INSERT INTO video_messages(business_id,project_id,role,content) VALUES(j.business_id,j.project_id,'assistant',p_message);
 END IF;
 UPDATE video_jobs SET status='completed',stage=CASE WHEN p_composition IS NULL THEN 'needs_input' ELSE 'ready_to_render' END,
 progress=100,finished_at=now() WHERE id=j.id;
 RETURN coalesce(result,'{}');
END $$;

DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT oid::regprocedure AS sig FROM pg_proc WHERE pronamespace='public'::regnamespace
 AND proname IN ('video_actor_allowed','save_video_revision','enqueue_video_job','claim_video_job','finish_video_plan') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated',f.sig);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',f.sig);
 END LOOP;
END $$;
COMMIT;
