# TEST REPORT — Escalation remediation (example vs real)

Date (UTC): 2026-05-19

## Goal
Validate new policy:
- Escalated tasks with EXAMPLE_MARKERS auto-close after >=10 heartbeats OR >=2h age.
- Escalated tasks without markers emit alert signal for Iarvis intervention.

## Setup
DB: `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`
Worker: `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py`

Inserted 2 synthetic tasks into `tasks`:
- Task A (example): payload.finding = `"Exemplo: teste auto-close"`, status=`escalated`, heartbeat_count=10, escalated_at ~ now-3h.
- Task B (real): payload.finding = `"REAL: stale escalation must alert"`, status=`escalated`, heartbeat_count=10, escalated_at ~ now-3h.

IDs created by DB at runtime:
- Example task id: 61
- Real task id: 62

## Execution
Command:
- `python3 /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --once`

Observed stdout:
- `Alert: 1 escalated tasks require intervention (signal emitted).`

## Results
### Tasks table
Post-run:
- id=61 -> status=`completed`; result_json contains `auto_closed=true` and policy fields.
- id=62 -> status=`escalated` (kept for intervention).

### agent_signals
Post-run:
- `message_type='escalated_task_stale'` inserted by `iarvis_worker` with receiver `Iarvis` and project_id `cron_jobs`.
- Latest IDs observed: 9118, 9119 (pending).

## Conclusion
Policy works for both branches:
- Example escalations self-heal.
- Real escalations produce alert signal for Iarvis action.

## Notes / follow-ups
- Synthetic tasks remain in DB (61 completed, 62 escalated). Decide retention policy for test_suite artifacts or add cleanup step.
