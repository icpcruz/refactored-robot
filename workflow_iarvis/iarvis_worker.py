"""Iarvis Worker (v1 - simulado).

Objetivo
--------
Worker de orquestração que usa SQLite como *source of truth* (fila de tarefas).

- DB: /home/openclaw/projetos_ia/comms_manager/iarvis_comms.db
- Infra map: /home/openclaw/projetos_ia/governança_ambiente/infra_map.json

Este v1 roda em modo **simulado**:
- Ele NÃO chama sessions_spawn de verdade.
- Ele valida: polling, transições de status, chaining e emissão de signals.

Regra de ouro: "você só garante aquilo que verifica".
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


PROJ_ROOT = "/home/openclaw/projetos_ia"
DB_PATH = os.path.join(PROJ_ROOT, "comms_manager/iarvis_comms.db")
INFRA_MAP_PATH = os.path.join(PROJ_ROOT, "governança_ambiente/infra_map.json")
WORKER_SESSION_PREFIX = "iarvis-worker-task-"
DEFAULT_MAX_REWORK_ROUNDS = 2


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def execute(query: str, params: Tuple[Any, ...] = ()) -> int:
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur.lastrowid


def fetch_one(query: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def ensure_schema() -> None:
    """Cria tabelas do worker se não existirem (não-destrutivo)."""

    execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            run_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress'
        );
        """
    )

    execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            source_agent TEXT NOT NULL,
            target_agent TEXT NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            rework_round INTEGER DEFAULT 0,
            max_rework_rounds INTEGER DEFAULT 2,
            workflow_run_id INTEGER
        );
        """
    )


def ensure_infra_map() -> Dict[str, Any]:
    if os.path.exists(INFRA_MAP_PATH):
        with open(INFRA_MAP_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)

    os.makedirs(os.path.dirname(INFRA_MAP_PATH), exist_ok=True)
    content = {
        "services": {
            "gerente_emails": {
                "entrypoint": "/home/openclaw/projetos_ia/gerente_emails/src/email_routine.py",
                "launcher": "/home/openclaw/projetos_ia/run_email_manager.sh",
                "docs": "/home/openclaw/projetos_ia/gerente_emails/docs/",
                "venvs": {
                    "prod": "/home/openclaw/projetos_ia/venv_openclaw",
                    "lint": "/home/openclaw/projetos_ia/venv_py311_lint",
                },
            }
        },
        "defaults": {"lint_venv": "/home/openclaw/projetos_ia/venv_py311_lint"},
    }
    with open(INFRA_MAP_PATH, "w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, ensure_ascii=False)
    return content


def start_workflow_run(run_name: str, mode: str) -> int:
    return execute(
        "INSERT INTO workflow_runs (run_name, mode, status) VALUES (?,?,?)",
        (run_name, mode, "in_progress"),
    )


def update_workflow_run_status(run_id: int, status: str) -> None:
    execute("UPDATE workflow_runs SET status=? WHERE id=?", (status, run_id))


def add_task(
    source_agent: str,
    target_agent: str,
    action: str,
    payload: Dict[str, Any],
    workflow_run_id: Optional[int] = None,
    rework_round: int = 0,
    max_rework_rounds: int = DEFAULT_MAX_REWORK_ROUNDS,
) -> int:
    return execute(
        """
        INSERT INTO tasks (
            source_agent, target_agent, action, payload_json,
            status, result_json, rework_round, max_rework_rounds, workflow_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            source_agent,
            target_agent,
            action,
            json.dumps(payload, ensure_ascii=False),
            "pending",
            None,
            rework_round,
            max_rework_rounds,
            workflow_run_id,
        ),
    )


def poll_pending_task() -> Optional[Dict[str, Any]]:
    query = (
        "SELECT t.*, wr.mode AS workflow_mode, wr.run_name AS workflow_run_name "
        "FROM tasks t "
        "LEFT JOIN workflow_runs wr ON t.workflow_run_id = wr.id "
        "WHERE t.status IN ('pending','requeued') "
        "ORDER BY t.created_at ASC LIMIT 1"
    )
    return fetch_one(query)


def update_task_status(
    task_id: int,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    assigned_agent_id: Optional[str] = None,
    rework_round: Optional[int] = None,
) -> None:
    sets = ["status=?"]
    params: list[Any] = [status]

    if result is not None:
        sets.append("result_json=?")
        params.append(json.dumps(result, ensure_ascii=False))

    if assigned_agent_id is not None:
        sets.append("assigned_to_agent_id=?")
        params.append(assigned_agent_id)

    if rework_round is not None:
        sets.append("rework_round=?")
        params.append(int(rework_round))

    params.append(task_id)
    execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", tuple(params))


def add_signal(sender_agent: str, signal_type: str, task_id: int, payload: Dict[str, Any]) -> None:
    """Compatível com a tabela existente agent_signals (schema antigo).

    Observação: o DB atual tem colunas: sender_agent, receiver_agent, message_type,
    payload_json, status. Vamos preencher receiver_agent='iarvis_worker'.
    """

    execute(
        """
        INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status)
        VALUES (?,?,?,?,?)
        """,
        (
            sender_agent,
            "iarvis_worker",
            signal_type,
            json.dumps({"task_id": task_id, **payload}, ensure_ascii=False),
            "pending",
        ),
    )


def decide_chain_next(action: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Chaining linear mínimo (pode ser evoluído com um workflow DSL depois)."""

    if action == "fix_code":
        return ("Aud", "review_code", {"marker": "WF"})
    if action == "review_code":
        return ("Sys", "run_smoketest", {"marker": "WF"})
    if action == "run_smoketest":
        return ("Doc", "update_docs", {"marker": "WF"})
    if action == "update_docs":
        return ("Iarvis", "close_cycle", {"marker": "WF"})
    return None


def spawn_agent_simulated(task: Dict[str, Any]) -> str:
    """Simula o spawn do agente (v1)."""

    target_agent = task["target_agent"]
    action = task["action"]
    task_id = task["id"]

    model = "openrouter/auto"
    if target_agent in ("Aud", "Iarvis"):
        model = "openrouter/google/gemini-3.1-pro-preview"
    elif target_agent in ("Dev", "Sys"):
        model = "openrouter/google/gemini-3-flash-preview"

    payload = json.loads(task.get("payload_json") or "{}")

    print("--- SPAWN (SIMULATED) ---")
    print(f"task_id={task_id} agent={target_agent} action={action} model={model}")
    print(f"payload={json.dumps(payload, ensure_ascii=False)}")
    print("--- END SPAWN ---")

    return f"{WORKER_SESSION_PREFIX}{task_id}"


def process_one_task(simulate_completion: bool = True) -> bool:
    """Processa 1 tarefa pendente. Retorna True se processou algo."""

    task = poll_pending_task()
    if not task:
        return False

    task_id = int(task["id"])
    target_agent = task["target_agent"]
    action = task["action"]

    rework_round = int(task.get("rework_round") or 0)
    max_rework_rounds = int(task.get("max_rework_rounds") or DEFAULT_MAX_REWORK_ROUNDS)

    if rework_round > max_rework_rounds:
        update_task_status(
            task_id,
            "failed",
            result={"error": "max_rework_rounds_exceeded", "rework_round": rework_round},
        )
        add_signal(
            target_agent,
            "escalation_needed",
            task_id,
            {"reason": "max_rework_rounds_exceeded", "rework_round": rework_round},
        )
        return True

    assigned_id = spawn_agent_simulated(task)
    update_task_status(task_id, "in_progress", assigned_agent_id=assigned_id)

    if simulate_completion:
        result = {
            "status": "simulated_completed",
            "worker_notes": "Simulated execution",
            "assigned_agent_id": assigned_id,
            "completed_at": utcnow_iso(),
        }
        update_task_status(task_id, "completed", result=result, assigned_agent_id=assigned_id)
        add_signal(target_agent, "task_completed", task_id, {"result": result})

    workflow_run_id = task.get("workflow_run_id")
    workflow_mode = task.get("workflow_mode")

    if workflow_run_id and workflow_mode == "linear" and action != "close_cycle":
        chain = decide_chain_next(action)
        if chain:
            next_agent, next_action, next_payload = chain
            next_id = add_task(
                source_agent=target_agent,
                target_agent=next_agent,
                action=next_action,
                payload=next_payload,
                workflow_run_id=int(workflow_run_id),
            )
            print(f"CHAIN: created task {next_id} -> {next_agent}:{next_action}")

    if workflow_run_id and workflow_mode == "linear" and action == "close_cycle":
        update_workflow_run_status(int(workflow_run_id), "completed")

    return True


def run_loop(poll_interval: int) -> None:
    print(f"[{utcnow_iso()}] Iarvis Worker started (simulado). DB={DB_PATH}")
    while True:
        did = process_one_task(simulate_completion=True)
        if not did:
            time.sleep(poll_interval)


def cmd_dry_run() -> int:
    ensure_schema()
    ensure_infra_map()

    run_id = start_workflow_run(f"dry_run_{utcnow_iso()}", "linear")
    first = add_task("Iarvis", "Dev", "fix_code", {"marker": "WF"}, workflow_run_id=run_id)
    print(f"Created workflow_run_id={run_id} first_task_id={first}")

    # process until workflow completes or max steps
    steps = 0
    max_steps = 20
    while steps < max_steps:
        did = process_one_task(simulate_completion=True)
        steps += 1
        if not did:
            break

        wf = fetch_one("SELECT status FROM workflow_runs WHERE id=?", (run_id,))
        if wf and wf.get("status") == "completed":
            print(f"Dry-run OK: workflow_run_id={run_id} completed in steps={steps}")
            return 0

    print(f"Dry-run FAILED/INCOMPLETE: workflow_run_id={run_id} steps={steps}")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Executa um dry-run do workflow linear")
    parser.add_argument("--run", action="store_true", help="Roda o loop do worker")
    parser.add_argument("--poll-interval", type=int, default=10)
    args = parser.parse_args()

    # mantém init legado, mas não falha se não existir
    try:
        subprocess.run(
            [
                "/usr/bin/python3",
                "/home/openclaw/projetos_ia/comms_manager/comms_manager.py",
                "initialize_comms_db",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass

    ensure_schema()
    ensure_infra_map()

    if args.dry_run:
        return cmd_dry_run()

    if args.run:
        run_loop(args.poll_interval)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
