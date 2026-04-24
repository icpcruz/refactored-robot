"""Iarvis Worker v1 — harness de teste (dry-run) para validar lógica integral.

Este script NÃO deve ser usado em produção.

Ele importa o worker real e roda em modo --dry-run/--once, criando um workflow_run
isolado e uma task inicial. O objetivo é validar:
- schema/DB acessível
- polling da próxima task
- marcação de status
- chaining padrão DEFAULT_CHAIN
- logs em agent_logs

Artefatos e relatório: ver workflow_tests/artifacts e reports gerados.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

# Ajuste de path para importar a partir de /home/openclaw/projetos_ia
import sys

sys.path.insert(0, "/home/openclaw/projetos_ia")

# Importa worker real
from governança_ambiente.workflow_iarvis.iarvis_worker import (
    DB_PATH,
    add_task,
    execute,
    run_worker,
    start_workflow_run,
)

ART_DIR = "/home/openclaw/projetos_ia/governança_ambiente/workflow_tests/artifacts"
REPORT_PATH = "/home/openclaw/projetos_ia/governança_ambiente/workflow_tests/TEST_REPORT_WORKER_DRY_RUN_2026-04-24.md"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def fetch_all(q: str, params=()):
    with db_conn() as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


def main() -> None:
    os.makedirs(ART_DIR, exist_ok=True)

    run_name = f"dry_run_worker_{utcnow()}"
    run_id = start_workflow_run(run_name, "linear")

    t1 = add_task(
        source_agent="Iarvis",
        target_agent="Dev",
        action="fix_classification_rules_schema",
        payload={"marker": "DRYRUN_2026-04-24", "notes": "test harness"},
        workflow_run_id=run_id,
    )

    # Rodar o worker várias vezes em --once para processar a cadeia completa em dry-run
    # (cada invocação processa 1 task e cria a próxima via chaining)
    for _ in range(6):
        run_worker(dry_run=True, once=True)

    tasks = fetch_all(
        "SELECT id, source_agent, target_agent, action, status, workflow_run_id FROM tasks WHERE workflow_run_id=? ORDER BY id",
        (run_id,),
    )

    logs = fetch_all(
        "SELECT id, log_level, message, timestamp FROM agent_logs WHERE agent_name='iarvis_worker' ORDER BY id DESC LIMIT 30"
    )

    # Relatório
    lines = []
    lines.append(f"# TEST REPORT — Iarvis Worker DRY RUN\n\n")
    lines.append(f"Data (UTC): {utcnow()}\n")
    lines.append(f"workflow_run_id: {run_id}\n")
    lines.append(f"task_seed_id: {t1}\n\n")

    lines.append("## Tasks criadas pelo chaining (esperado: Dev→Aud→Sys→Doc→Iarvis)\n")
    for t in tasks:
        lines.append(
            f"- id={t['id']} {t['source_agent']}→{t['target_agent']} action={t['action']} status={t['status']}\n"
        )

    lines.append("\n## Últimos logs do worker (agent_logs)\n")
    for l in logs:
        lines.append(f"- {l['timestamp']} [{l['log_level']}] {l['message']} (id={l['id']})\n")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print(f"OK: report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
