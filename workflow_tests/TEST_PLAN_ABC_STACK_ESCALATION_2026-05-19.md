# TEST PLAN A/B/C — Stack report + escalations watchdog

Date (UTC): 2026-05-19
Owner: Iarvis

## Scope
- Stack daily report scripts (DB schema alignment)
- Iarvis worker escalation auto-remediation
- Live cron-equivalent execution path

## Plan A — Report regression (schema)
### Goal
No static artifact; no missing-column errors; escalation count uses status='escalated'.

### Steps
1. Run:
   - `python3 /home/openclaw/.openclaw/workspace/scripts/daily_stack_report_24h.py`
   - `python3 /home/openclaw/.openclaw/workspace/scripts/daily_stack_report.py`
2. Assert:
   - exit code 0
   - no `sqlite3.OperationalError`

### Results
(TBD)

## Plan B — Escalation remediation behavior
### Goal
- Example escalation auto-closes after >=10 heartbeats OR >=2h.
- Real escalation triggers alert signal.

### Steps
1. Insert 2 synthetic tasks into DB (source_agent='test_suite'):
   - Example payload with `Exemplo:` marker
   - Real payload without marker
   Both with status='escalated', heartbeat_count=10, escalated_at ~ now-3h.
2. Run worker once:
   - `python3 .../iarvis_worker.py --once`
3. Assert:
   - Example task -> status=completed + result_json auto_closed
   - Real task -> remains escalated + agent_signal `escalated_task_stale`
4. Cleanup:
   - delete test_suite tasks + related signals (keep only report artifacts).

### Results
(TBD)

## Plan C — Live test (cron-equivalent)
### Goal
Trigger real producer path and observe:
- DB updated
- Worker stable
- Telegram stack report signal queued

### Steps
1. Run cron-equivalent:
   - `python3 /home/openclaw/.openclaw/workspace/scripts/send_daily_stack_report_telegram.py`
2. (Optional) Trigger ingest if report exists:
   - `python3 .../cron_ingest_code_audit.py --report .../reports/relatorios_cron/latest.txt --project cron_jobs --db .../iarvis_comms.db`
   - run worker once
3. Assert:
   - latest agent_signal `stack24h_report_telegram` queued
   - report file updated: `reports/stack24h_report_dynamic.txt`

### Results
(TBD)
