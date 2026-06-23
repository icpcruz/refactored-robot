# OPERATIONS.md — governança_ambiente

## Purpose
Agent governance, workflow orchestration, health monitoring, and cron job management for the Iarvis multi-agent system.

## Key Components

| Component | Role | Entry Point |
|-----------|------|-------------|
| `workflow_iarvis/iarvis_worker.py` | Task consumer and workflow runner | systemd timer or cron |
| `workflow_iarvis/healthcheck_worker.py` | Watchdog + stale-task alerts | systemd timer |
| `workflow_iarvis/task_tools.py` | CLI utilities for task creation/updates | Manual / scripts |
| `cron-jobs/` | Recurrent audit and ingest tasks | cron |
| `oauth_guard/` | OAuth token validity guard | Imported by email_manager |

## Databases
- **Primary:** `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db` (shared with comms_manager)
- **Legacy (inactive):** `iarvis_logs.db.LEGACY.empty` (archived; do not use)

## Startup
### Iarvis Worker
```bash
# Manual (dry-run / once)
/home/openclaw/projetos_ia/venv_openclaw/bin/python \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --once --dry-run

# Daemon-style (continuous)
/home/openclaw/projetos_ia/venv_openclaw/bin/python \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py
```

### Healthcheck
```bash
/home/openclaw/projetos_ia/venv_openclaw/bin/python \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/healthcheck_worker.py \
  --stale-minutes 15 --max-pending 5
```

## Health Checks
```bash
# Check systemd unit
systemctl --user is-active iarvis-worker.service

# Pending tasks
sqlite3 /home/openclaw/projetos_ia/comms_manager/iarvis_comms.db \
  "SELECT COUNT(*) FROM tasks WHERE status IN ('pending','requeued');"

# Stale escalated tasks
sqlite3 /home/openclaw/projetos_ia/comms_manager/iarvis_comms.db \
  "SELECT COUNT(*) FROM tasks WHERE status='escalated';"

# Recent worker logs
sqlite3 /home/openclaw/projetos_ia/comms_manager/iarvis_comms.db \
  "SELECT * FROM agent_logs WHERE agent_name='iarvis_worker' ORDER BY id DESC LIMIT 5;"
```

## Important Notes
- **No own DB** — all state lives in `comms_manager/iarvis_comms.db` (shared schema, see `comms_manager/SCHEMA.md`).
- **Migration runner:** Use `comms_manager/migrations/apply_migrations.py` for schema changes.
- **Auto-remediation:** `iarvis_worker.py` auto-closes escalated tasks marked as example/dry-run after 2h or 10 heartbeats. Real escalations emit `agent_signals`.
- **Backup:** Archive `comms_manager/iarvis_comms.db` to secure state.

## Schema Version
Current: managed by `comms_manager` migrations (`schema_version` table).
