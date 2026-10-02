"""Apply/verify video storage; dry-run rolls schema and fixtures back together."""
from pathlib import Path
import sys,json
from verify_backup import live_query
root=Path(__file__).resolve().parents[1]
migration=(root/'supabase/APPLY-2026-09-07-video-studio.sql').read_text()
tests=r'''
DO $$
DECLARE b uuid; actor uuid; p uuid; r jsonb; j jsonb; c jsonb; retry jsonb; a uuid; denied boolean; spec jsonb;
BEGIN
 SELECT id,owner_id INTO b,actor FROM businesses WHERE owner_id IS NOT NULL LIMIT 1;
 IF b IS NULL THEN RAISE EXCEPTION 'No verification parent'; END IF;
 INSERT INTO video_projects(business_id,created_by,title) VALUES(b,actor,'Rollback-only verification') RETURNING id INTO p;
 spec:='{"version":1,"title":"Verification","format":"landscape","theme":"midnight","accent":"#4BA9FF","voice":"none","captions":true,"music_asset_id":null,"scenes":[{"id":"intro","layout":"title","title":"Hello","seconds":6}]}'::jsonb;
 r:=save_video_revision(b,p,actor,0,spec,'test');
 IF (r->>'revision')::integer<>1 THEN RAISE EXCEPTION 'Revision not saved'; END IF;
 IF save_video_revision(b,p,actor,0,spec,'stale')->>'conflict'<>'true' THEN RAISE EXCEPTION 'Stale revision accepted'; END IF;
 denied:=false;
 BEGIN PERFORM save_video_revision(b,p,gen_random_uuid(),1,spec,'unauthorized'); EXCEPTION WHEN raise_exception THEN denied:=true; END;
 IF NOT denied THEN RAISE EXCEPTION 'Foreign actor accepted'; END IF;
 j:=enqueue_video_job(b,p,actor,'render',(r->>'id')::uuid,1,gen_random_uuid(),'{"approved":true}');
 IF j->>'status'<>'queued' THEN RAISE EXCEPTION 'Render not queued'; END IF;
 c:=enqueue_video_job(b,p,actor,'render',(r->>'id')::uuid,1,(j->>'request_id')::uuid,'{}');
 IF c->>'id'<>j->>'id' THEN RAISE EXCEPTION 'Duplicate request queued twice'; END IF;
 c:=claim_video_job();
 IF c->>'id'<>j->>'id' OR claim_video_job() IS NOT NULL THEN RAISE EXCEPTION 'Concurrent worker claim'; END IF;
 UPDATE video_jobs SET lease_until=now()-interval '1 minute' WHERE id=(j->>'id')::uuid;
 retry:=claim_video_job();
 IF retry->>'lease_id'=c->>'lease_id' OR (retry->>'attempt')::integer<>2 THEN RAISE EXCEPTION 'Lease retry not fenced'; END IF;
 IF finish_video_plan((j->>'id')::uuid,(c->>'lease_id')::uuid,NULL,'stale')->>'cancelled'<>'true' THEN RAISE EXCEPTION 'Stale worker completed'; END IF;
 denied:=false;
 BEGIN INSERT INTO video_assets(business_id,project_id,created_by,name,mime_type,byte_size,sha256,object_path,purpose)
 VALUES(b,p,actor,'in-flight.png','image/png',10,repeat('a',64),'rollback-'||p,'include');
 EXCEPTION WHEN raise_exception THEN denied:=true; END;
 IF NOT denied THEN RAISE EXCEPTION 'Media changed during queued render'; END IF;
 UPDATE video_jobs SET status='cancelled' WHERE id=(j->>'id')::uuid;
 INSERT INTO video_assets(business_id,project_id,created_by,name,mime_type,byte_size,sha256,object_path,purpose)
 VALUES(b,p,actor,'reference.png','image/png',10,repeat('a',64),'rollback-'||p,'reference') RETURNING id INTO a;
 spec:=jsonb_set(spec,'{scenes,0,asset_id}',to_jsonb(a::text));
 r:=save_video_revision(b,p,actor,1,spec,'reference');
 denied:=false;
 BEGIN PERFORM enqueue_video_job(b,p,actor,'render',(r->>'id')::uuid,2,gen_random_uuid(),'{}');
 EXCEPTION WHEN raise_exception THEN denied:=true; END;
 IF NOT denied THEN RAISE EXCEPTION 'Reference-only source reached queue'; END IF;
 IF has_table_privilege('authenticated','public.video_projects','SELECT') OR
 has_function_privilege('authenticated','public.claim_video_job()','EXECUTE') THEN RAISE EXCEPTION 'Browser boundary open'; END IF;
END $$;
'''
mode=sys.argv[1]
if mode=='dry-run':
    answer=live_query(migration.replace('COMMIT;',tests+'ROLLBACK; SELECT true AS transaction_and_boundary_checks_passed;'))
elif mode=='apply':answer=live_query(migration)
elif mode=='verify':
    answer=live_query("SELECT count(*)=5 AS private_tables FROM pg_class WHERE relname IN ('video_projects','video_assets','video_revisions','video_messages','video_jobs') AND relrowsecurity; SELECT public=false AS private_bucket FROM storage.buckets WHERE id='video-studio';")
else:raise SystemExit('Use dry-run, apply or verify')
print(json.dumps(answer,indent=2))
