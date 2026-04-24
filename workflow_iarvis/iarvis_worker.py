# /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py

"""Iarvis Worker (v1 - dispatch real).

Orquestrador de workflows com dispatch real de subagentes via sessions_spawn.

- Source of truth: /home/openclaw/projetos_ia/comms_manager/iarvis_comms.db
- Infra map: /home/openclaw/projetos_ia/governança_ambiente/infra_map.json

Este worker v1:
- Polla o DB por tarefas pendentes.
- Chama sessions_spawn (real ou simulada, dependendo do ambiente).
- Monitora o status da tarefa no DB até conclusão/falha.
- Gerencia o encadeamento linear de tarefas.
- Implementa lógica de rework/escalonamento.

Regra de ouro: "você só garante aquilo que verifica".
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# === CONFIGURAÇÕES ===
PROJ_ROOT = "/home/openclaw/projetos_ia"
DB_PATH = os.path.join(PROJ_ROOT, "comms_manager/iarvis_comms.db")
INFRA_MAP_PATH = os.path.join(PROJ_ROOT, "governança_ambiente/infra_map.json")
WORKER_SESSION_PREFIX = "iarvis-worker-task-"
DEFAULT_MAX_REWORK_ROUNDS = 2
POLL_INTERVAL = 5  # segundos
WORKER_NAME = "iarvis_worker"
DEFAULT_TASK_TIMEOUT_SECONDS = 20 * 60
DISPATCH_LOG_DIR = os.path.join(PROJ_ROOT, "governança_ambiente/workflow_logs")

# Tarefas que geram próxima etapa automaticamente (workflow linear padrão)
DEFAULT_CHAIN = {
    "fix_classification_rules_schema": {
        "on_completed": {"target_agent": "Aud", "action": "review_fix"}
    },
    "review_fix": {
        "on_completed": {"target_agent": "Sys", "action": "run_smoketest"},
        # se Aud reprovou, ela deve setar status=requeued + rework_round++
    },
    "run_smoketest": {"on_completed": {"target_agent": "Doc", "action": "update_docs"}},
    "update_docs": {"on_completed": {"target_agent": "Iarvis", "action": "close_cycle"}},
}

# === FUNÇÕES DB ===
def db_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)

def execute(query: str, params: Tuple[Any, ...] = ()) -> Optional[int]:
    """Executa query e retorna lastrowid se aplicável, ou None."""
    try:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            return cur.lastrowid
    except sqlite3.Error as e:
        print(f"DB Error executing query: {query} with params {params}. Error: {e}")
        return None

def fetch_one(query: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    """Executa query e retorna a primeira linha (como dict) ou None."""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None

def fetch_all(query: str, params: Tuple[Any, ...] = ()) -> list[Dict[str, Any]]:
    """Executa query e retorna todas as linhas (como dicts)."""
    with db_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

def poll_pending_tasks() -> Optional[Dict[str, Any]]:
    """Busca a próxima tarefa pendente ou requeued para processamento."""
    query = """
        SELECT t.*, wr.mode as workflow_mode, wr.run_name as workflow_run_name
        FROM tasks t
        LEFT JOIN workflow_runs wr ON t.workflow_run_id = wr.id
        WHERE t.status IN ('pending', 'requeued')
        ORDER BY t.created_at ASC LIMIT 1
    """
    return fetch_one(query)

def update_task_status(
    task_id: int,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    assigned_agent_id: Optional[str] = None,
    rework_round: Optional[int] = None,
) -> None:
    """Atualiza o status e resultado de uma tarefa."""
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
    query = f"UPDATE tasks SET {', '.join(sets)} WHERE id=?"
    execute(query, tuple(params))

def add_task(
    source_agent: str,
    target_agent: str,
    action: str,
    payload: Dict[str, Any],
    workflow_run_id: Optional[int] = None,
    rework_round: int = 0,
    max_rework_rounds: int = DEFAULT_MAX_REWORK_ROUNDS,
) -> Optional[int]:
    """Adiciona uma nova tarefa no banco de dados."""
    query = """
        INSERT INTO tasks (
            source_agent, target_agent, action, payload_json,
            status, result_json, rework_round, max_rework_rounds, workflow_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """
    payload_json_str = json.dumps(payload, ensure_ascii=False)
    return execute(
        query,
        (
            source_agent,
            target_agent,
            action,
            payload_json_str,
            "pending",
            None,
            rework_round,
            max_rework_rounds,
            workflow_run_id,
        ),
    )

def add_signal(sender_agent: str, signal_type: str, task_id: int, payload: Dict[str, Any]) -> None:
    """Adiciona um sinal de evento para comunicação entre agentes."""
    query = """
        INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status)
        VALUES (?,?,?,?,?)
    """
    payload_json_str = json.dumps({"task_id": task_id, **payload}, ensure_ascii=False)
    execute(query, (sender_agent, "iarvis_worker", signal_type, payload_json_str, "pending"))

def get_workflow_run(run_id: int) -> Optional[Dict[str, Any]]:
    """Busca detalhes de um workflow run."""
    query = "SELECT * FROM workflow_runs WHERE id = ?"
    return fetch_one(query, (run_id,))

def update_workflow_run_status(run_id: int, status: str) -> None:
    """Atualiza o status de um workflow run."""
    query = "UPDATE workflow_runs SET status = ? WHERE id = ?"
    execute(query, (status, run_id))

def start_workflow_run(run_name: str, mode: str) -> Optional[int]:
    """Inicia um novo workflow run."""
    query = "INSERT INTO workflow_runs (run_name, mode, status) VALUES (?,?,?)"
    return execute(query, (run_name, mode, "in_progress"))

# === FUNÇÕES DE WORKER ===
def get_infra_map() -> Dict[str, Any]:
    """Carrega o mapa de infraestrutura."""
    try:
        with open(INFRA_MAP_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        print(f"INFO: Infra map not found at {INFRA_MAP_PATH}. Creating placeholder.")
        content = {
            "services": {"gerente_emails": {}},
            "defaults": {"lint_venv": "/home/openclaw/projetos_ia/venv_py311_lint"},
        }
        os.makedirs(os.path.dirname(INFRA_MAP_PATH), exist_ok=True)
        with open(INFRA_MAP_PATH, "w", encoding="utf-8") as handle:
            json.dump(content, handle, indent=2, ensure_ascii=False)
        return content
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON in infra map at {INFRA_MAP_PATH}.")
        return {}

def claim_task(task_id: int, assigned_id: str) -> bool:
    """Tenta "claim" atômico para evitar dois workers pegarem a mesma task."""
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tasks SET status='in_progress', assigned_to_agent_id=? "
            "WHERE id=? AND status IN ('pending','requeued')",
            (assigned_id, task_id),
        )
        conn.commit()
        return cur.rowcount == 1


def spawn_agent(task_details: Dict[str, Any], infra_map: Dict[str, Any]) -> str:
    """Dispara o subagente via Gateway (CLI), ou simula em dry-run.

    Retorna o session_id (ou um id simulado) para rastreio.
    """
    target_agent = task_details["target_agent"]
    action = task_details["action"]
    payload = json.loads(task_details.get("payload_json") or "{}")
    task_id = task_details["id"]
    workflow_mode = task_details.get("workflow_mode")
    workflow_run_name = task_details.get("workflow_run_name", "N/A")

    # Determinar modelo e runtime
    model = infra_map.get("defaults", {}).get("model", "openrouter/auto")
    if target_agent in infra_map.get("model_mapping", {}):
        model = infra_map["model_mapping"][target_agent]
    elif target_agent in ["Aud", "Iarvis"]:
        model = "openrouter/google/gemini-3.1-pro-preview"
    elif target_agent in ["Dev", "Sys"]:
        model = "openrouter/google/gemini-3-flash-preview"

    runtime = "acp"  # intenção; execução real usa CLI openclaw agent

    # Construir o prompt ('task') para o subagente
    task_prompt = f"Sua ação é: {action}\n"
    task_prompt += f"Contexto: Tarefa ID {task_id}, originada por {task_details['source_agent']}.\n"
    task_prompt += f"WorkflowRun: {workflow_run_name} ({workflow_mode or 'N/A'})\n"

    # CONTRATO OBRIGATÓRIO: o agente deve finalizar via task_tools.py
    task_prompt += "\n=== CONTRATO OBRIGATÓRIO (GOVERNANÇA) ===\n"
    task_prompt += "Você DEVE finalizar a task atualizando o SQLite (iarvis_comms.db) via helper:\n"
    task_prompt += "- Tool: /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/task_tools.py\n"
    task_prompt += "- DB:   /home/openclaw/projetos_ia/comms_manager/iarvis_comms.db\n"
    task_prompt += "Comandos permitidos (escolha 1):\n"
    task_prompt += f"1) SUCCESS: task_tools.py complete --sender {target_agent} --task-id {task_id} --result-json '<JSON>'\n"
    task_prompt += f"2) FAIL:    task_tools.py fail --sender {target_agent} --task-id {task_id} --result-json '<JSON>'\n"
    task_prompt += f"3) REWORK:  task_tools.py requeue --sender {target_agent} --task-id {task_id} --result-json '<JSON>'\n"
    task_prompt += "O JSON deve ser um objeto e incluir no mínimo: {\"ok\":true/false,\"notes\":\"...\"} e paths de artefatos se existirem.\n"
    task_prompt += "NÃO responda apenas em texto: sem update no DB a task fica travada.\n"
    task_prompt += "=== FIM CONTRATO ===\n\n"

    task_prompt += f"Payload (dados da task):\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n"

    # --- Argumentos conceituais (mantidos para auditoria) ---
    spawn_args = {
        "runtime": runtime,
        "agentId": target_agent,
        "task": task_prompt,
        "model": model,
        "thinking": "high" if target_agent in ["Aud", "Iarvis"] else "low",
        "label": f"{target_agent} - Task {task_id} ({action})",
        "streamTo": "parent",
    }

    print("--- DISPATCH ---")
    print(f"Target Agent: {target_agent}, Task ID: {task_id}, Action: {action}")
    print(f"Args (audit): {json.dumps(spawn_args, indent=2, ensure_ascii=False)}")

    session_id = f"{WORKER_SESSION_PREFIX}{task_id}"

    os.makedirs(DISPATCH_LOG_DIR, exist_ok=True)
    log_path = os.path.join(DISPATCH_LOG_DIR, f"task_{task_id}_{target_agent}_{action}.log")

    # Execução real via Gateway CLI (não depende de import python 'openclaw')
    message = task_prompt
    try:
        with open(log_path, "ab") as out:
            subprocess.Popen(
                [
                    "openclaw",
                    "agent",
                    "--agent",
                    str(target_agent).lower(),
                    "--message",
                    message,
                    "--thinking",
                    "high" if target_agent in ["Aud", "Iarvis"] else "low",
                    "--timeout",
                    "600",
                ],
                stdout=out,
                stderr=out,
            )
        print(f"--- DISPATCH: launched (log={log_path}) ---")
    except Exception as exc:
        print(f"ERROR: Failed to launch openclaw agent: {exc}")
        raise

    return session_id

def utcnow_iso() -> str:
    """Timestamp ISO-8601 em UTC."""
    return datetime.now(timezone.utc).isoformat()


def ensure_infra_map() -> Dict[str, Any]:
    """Garante que exista um infra_map válido (placeholder se necessário)."""
    infra_map = get_infra_map()
    return infra_map or {"services": {}, "defaults": {}}


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT * FROM tasks WHERE id=?", (task_id,))


def wait_task_terminal(task_id: int, timeout_seconds: int = DEFAULT_TASK_TIMEOUT_SECONDS) -> str:
    """Espera até task virar completed/failed (polling DB)."""
    start = time.time()
    while True:
        t = get_task(task_id)
        if not t:
            return "missing"
        if t.get("status") in {"completed", "failed"}:
            return t["status"]
        if time.time() - start > timeout_seconds:
            return "timeout"
        time.sleep(2)


def maybe_chain_next(task: Dict[str, Any]) -> Optional[int]:
    """Se a task concluiu e pertence a um workflow_run, cria próxima etapa.

    Também fecha o workflow_run quando a última ação (close_cycle) completar.
    """
    workflow_run_id = task.get("workflow_run_id")
    if not workflow_run_id:
        return None

    action = task.get("action")

    # Fechamento de ciclo
    if action == "close_cycle" and task.get("status") == "completed":
        update_workflow_run_status(int(workflow_run_id), "completed")
        add_signal(WORKER_NAME, "cycle_completed", int(task["id"]), {"workflow_run_id": workflow_run_id})
        log_worker("info", "workflow_completed", {"workflow_run_id": workflow_run_id})
        return None

    chain = DEFAULT_CHAIN.get(action)
    if not chain:
        return None

    # Só chain em sucesso
    if task.get("status") != "completed":
        return None

    next_spec = chain.get("on_completed")
    if not next_spec:
        return None

    payload = json.loads(task.get("payload_json") or "{}")
    result = json.loads(task.get("result_json") or "{}")

    next_payload = {
        "prev_task_id": task["id"],
        "prev_action": action,
        "prev_result": result,
        **payload,
    }

    return add_task(
        source_agent=task.get("target_agent", "Iarvis"),
        target_agent=next_spec["target_agent"],
        action=next_spec["action"],
        payload=next_payload,
        workflow_run_id=workflow_run_id,
    )


def log_worker(level: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
    execute(
        "INSERT INTO agent_logs (agent_name, log_level, message, details_json) VALUES (?,?,?,?)",
        (
            WORKER_NAME,
            level,
            message,
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )


def run_worker(dry_run: bool = False, once: bool = False) -> None:
    """Loop principal do worker."""
    print(f"[{utcnow_iso()}] Iarvis Worker iniciado. Monitorando {DB_PATH}...")

    # Garantir que o DB e schema existem
    try:
        subprocess.run(
            [
                "/usr/bin/python3",
                "/home/openclaw/projetos_ia/comms_manager/comms_manager.py",
                "initialize_comms_db",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("ERROR: python3 executable not found. Cannot initialize DB.")
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        print(f"FATAL ERROR: Failed to initialize comms DB: {e.stderr.decode()}")
        raise SystemExit(1)

    infra_map = ensure_infra_map()  # cria placeholder se necessário

    log_worker("info", "worker_started", {"dry_run": dry_run, "once": once})

    while True:
        task = poll_pending_tasks()
        if not task:
            if once:
                return
            time.sleep(POLL_INTERVAL)
            continue

        task_id = task["id"]
        agent = task["target_agent"]
        action = task["action"]

        log_worker("info", "task_polled", {"task_id": task_id, "agent": agent, "action": action})
        print(f"--- [TASK {task_id}] Despachando {agent} para {action} ---")

        payload = json.loads(task.get("payload_json") or "{}")

        # Anti-loop: escalona se excedeu rounds
        rework_round = int(task.get("rework_round") or 0)
        max_rounds = int(task.get("max_rework_rounds") or DEFAULT_MAX_REWORK_ROUNDS)
        if rework_round > max_rounds:
            update_task_status(
                task_id,
                "failed",
                result={"reason": "max_rework_rounds_exceeded", "rework_round": rework_round},
            )
            add_signal(
                WORKER_NAME,
                "escalation_needed",
                task_id,
                {"reason": "max_rework_rounds_exceeded", "rework_round": rework_round, "payload": payload},
            )
            log_worker("warn", "task_failed_max_rework", {"task_id": task_id})
            if once:
                return
            time.sleep(POLL_INTERVAL)
            continue

        # Claim atômico
        assigned_id = f"worker-{agent.lower()}-{task_id}"
        if not claim_task(task_id, assigned_id):
            log_worker("warn", "task_claim_failed", {"task_id": task_id})
            if once:
                return
            time.sleep(POLL_INTERVAL)
            continue

        if dry_run:
            # modo simulado: não dispara agente, marca completed e faz chaining
            update_task_status(
                task_id,
                "completed",
                result={"dry_run": True, "note": "auto-completed by worker dry-run", "payload": payload},
            )
            log_worker("info", "task_completed_dry_run", {"task_id": task_id})
        else:
            # Disparo real (subprocess openclaw agent)
            session_id = spawn_agent(task, infra_map)
            update_task_status(
                task_id,
                "in_progress",
                result={"session_id": session_id, "payload": payload},
                assigned_agent_id=f"worker-{agent.lower()}-{task_id}",
            )

            term = wait_task_terminal(task_id)
            log_worker("info", "task_terminal", {"task_id": task_id, "terminal": term})
            if term == "timeout":
                add_signal(
                    WORKER_NAME,
                    "escalation_needed",
                    task_id,
                    {"reason": "task_timeout", "timeout_seconds": DEFAULT_TASK_TIMEOUT_SECONDS},
                )
                log_worker("warn", "task_timeout", {"task_id": task_id})

        # chaining (se houver workflow_run)
        final_task = get_task(task_id) or task
        next_id = maybe_chain_next(final_task)
        if next_id:
            log_worker("info", "task_chained", {"from": task_id, "to": next_id})

        if once:
            return

        time.sleep(POLL_INTERVAL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Iarvis workflow worker")
    parser.add_argument("--dry-run", action="store_true", help="Não dispara agentes; marca tasks como completed")
    parser.add_argument("--once", action="store_true", help="Processa no máximo 1 task e sai")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_worker(dry_run=bool(args.dry_run), once=bool(args.once))
