# TEST REPORT — Iarvis Worker DRY RUN

Data (UTC): 2026-04-24T12:34:38.911488+00:00
workflow_run_id: 8
task_seed_id: 25

## Tasks criadas pelo chaining (esperado: Dev→Aud→Sys→Doc→Iarvis)
- id=25 Iarvis→Dev action=fix_classification_rules_schema status=completed
- id=27 Dev→Aud action=review_fix status=completed
- id=29 Aud→Sys action=run_smoketest status=completed
- id=31 Sys→Doc action=update_docs status=pending

## Últimos logs do worker (agent_logs)
- 2026-04-24 12:34:38 [info] task_chained (id=391)
- 2026-04-24 12:34:38 [info] task_completed_dry_run (id=390)
- 2026-04-24 12:34:38 [info] task_polled (id=389)
- 2026-04-24 12:34:38 [info] worker_started (id=388)
- 2026-04-24 12:34:38 [info] task_chained (id=387)
- 2026-04-24 12:34:38 [info] task_completed_dry_run (id=386)
- 2026-04-24 12:34:38 [info] task_polled (id=385)
- 2026-04-24 12:34:38 [info] worker_started (id=384)
- 2026-04-24 12:34:38 [info] task_chained (id=383)
- 2026-04-24 12:34:38 [info] task_completed_dry_run (id=382)
- 2026-04-24 12:34:38 [info] task_polled (id=381)
- 2026-04-24 12:34:38 [info] worker_started (id=380)
- 2026-04-24 12:34:38 [info] task_chained (id=379)
- 2026-04-24 12:34:38 [info] task_completed_dry_run (id=378)
- 2026-04-24 12:34:38 [info] task_polled (id=377)
- 2026-04-24 12:34:38 [info] worker_started (id=376)
- 2026-04-24 12:34:38 [info] task_chained (id=375)
- 2026-04-24 12:34:38 [info] task_completed_dry_run (id=374)
- 2026-04-24 12:34:38 [info] task_polled (id=373)
- 2026-04-24 12:34:38 [info] worker_started (id=372)
- 2026-04-24 12:34:38 [info] task_chained (id=371)
- 2026-04-24 12:34:38 [info] task_completed_dry_run (id=370)
- 2026-04-24 12:34:38 [info] task_polled (id=369)
- 2026-04-24 12:34:38 [info] worker_started (id=368)
