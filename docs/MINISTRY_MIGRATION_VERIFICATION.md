# Ministry migration — production verification

Applied 2026-09-29 03:29 UTC to the production project `brqjgbpzackdihgjsorf` via the Supabase Management API, explicitly authorized by Kevin.

Preflight confirmed no duplicate `GIVE-` numbers, the required columns, RLS enabled on all financial tables, and a completed backup from 2026-09-28 06:57 UTC. Two production differences were corrected before application: intake drafts use `dismissed` (not `rejected`), and explicit default grants to `anon` must be revoked as well as PUBLIC function grants. The regression fixture now includes both production constraints.

The final transaction was rehearsed with ROLLBACK. During application, brief write locks on invoices, contacts, events, and agent_queue prevented concurrent changes to the archive inputs. A transaction-local manifest verified every selected contact/event/draft copy was preserved in private storage before COMMIT; any missing archive would have aborted the transaction. PostgREST schema reload was notified at commit.

Independent post-commit verification returned:

```json
{
  "indexes": 3,
  "triggers": 3,
  "gift_count": 0,
  "verified_at": "2026-09-29T03:30:23.790736+00:00",
  "gift_columns": 2,
  "archive_kinds": {
    "draft": 1,
    "event": 1,
    "contact": 1
  },
  "private_tables": [
    {
      "rls": true,
      "name": "ministry_care_requests",
      "anon_select": false,
      "service_insert": true,
      "authenticated_insert": false,
      "authenticated_select": false
    },
    {
      "rls": true,
      "name": "ministry_gift_history",
      "anon_select": false,
      "service_insert": true,
      "authenticated_insert": false,
      "authenticated_select": false
    }
  ],
  "private_archives": 3,
  "finance_tables_rls": true,
  "financial_policies": 9,
  "unclassified_gifts": 0,
  "gift_event_policies": 3,
  "anon_finance_function": false,
  "browser_finance_function": true,
  "private_events_remaining": 0,
  "private_contacts_remaining": 0,
  "unsanitized_private_drafts": 0
}
```

Read-only HTTP checks passed: `/health` and `/health/ready` returned 200; the giving records endpoint without authentication returned 401; anonymous reads of both private tables returned 401; the API recognized `is_gift` and `gift_fund` (200). No synthetic customers, gifts, or private requests were retained. Full signed-in user-flow testing was not part of this database application.

The corrected migration passed the local PostgreSQL-compatible regression suite for replay, gift classification, care archival, finance-role visibility, gift history, and stale roster writes. Historical copies outside the migration's identified sources (such as already-sent emails) remain outside its scope.
