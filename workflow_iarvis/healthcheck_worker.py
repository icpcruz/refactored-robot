#!/usr/bin/env python3
"""Healthcheck do Iarvis Worker.

Critérios:
- Se o serviço systemd user `iarvis-worker.service` não estiver ativo -> alerta.
- Se existirem tasks `pending/requeued` (acima de um limite) -> alerta.
- Se existirem tasks pendentes e o worker não tiver logs recentes (`agent_logs`) -> alerta.

Efeito:
- Insere `agent_signals` para Iarvis com `message_type='worker_health_alert'` e `status=pending`.

Uso (systemd timer):
  python3 healthcheck_worker.py --stale-minutes 15
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

DB = "/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db"
WORKER_NAME = "iarvis_worker"
SYSTEMD_UNIT = "iarvis-worker.service"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def systemd_is_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", SYSTEMD_UNIT],
            check=False,
        )
        return r.returncode == 0
    except Exception:
        logger.exception("Failed to check systemd status for %s", SYSTEMD_UNIT)
        return False


def add_signal(payload: dict) -> None:
    with sqlite3.connect(DB) as con:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status, timestamp)
            VALUES (?,?,?,?,?,?)
            """,
            (
                WORKER_NAME,
                "Iarvis",
                "worker_health_alert",
                json.dumps(payload, ensure_ascii=False),
                "pending",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        con.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-minutes", type=int, default=15)
    ap.add_argument("--max-pending", type=int, default=0, help="se pending > max -> alerta")
    args = ap.parse_args()

    stale_cutoff = utcnow() - timedelta(minutes=args.stale_minutes)

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute(
            """
            SELECT id, created_at, source_agent, target_agent, action, status, workflow_run_id
            FROM tasks
            WHERE status IN ('pending','requeued')
            ORDER BY created_at ASC
            """
        )
        pending = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT timestamp FROM agent_logs
            WHERE agent_name=?
            ORDER BY id DESC LIMIT 1
            """,
            (WORKER_NAME,),
        )
        last_log = cur.fetchone()

    alerts = []

    if not systemd_is_active():
        alerts.append({"kind": "systemd_inactive", "unit": SYSTEMD_UNIT})

    if len(pending) > args.max_pending:
        alerts.append(
            {
                "kind": "pending_tasks",
                "count": len(pending),
                "max_pending": args.max_pending,
                "examples": pending[:5],
            }
        )

    if pending:
        if not last_log:
            alerts.append({"kind": "no_worker_logs", "details": "agent_logs has no entries for worker"})
        else:
            # agent_logs timestamp é localtime string; parse best-effort
            try:
                last_ts = datetime.fromisoformat(str(last_log["timestamp"]).replace(" ", "T"))
            except Exception:
                logger.exception("Failed to parse last log timestamp: %s", last_log["timestamp"])
                last_ts = None

            if last_ts and last_ts.replace(tzinfo=None) < stale_cutoff.replace(tzinfo=None):
                alerts.append({"kind": "worker_stale_logs", "last_log": str(last_log["timestamp"])})

    if alerts:
        add_signal(
            {
                "stale_minutes": args.stale_minutes,
                "alerts": alerts,
                "checked_at": utcnow().isoformat(),
            }
        )
        print("ALERT_SENT")
    else:
        print("OK")


if __name__ == "__main__":
    main()
