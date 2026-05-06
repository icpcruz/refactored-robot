#!/usr/bin/env python3
"""Task tools for Workflow Iarvis.

Objetivo: dar aos subagentes um mecanismo padrão e auditável para:
- completar tasks
- falhar tasks
- pedir rework (requeued)
- escrever signals no `iarvis_comms.db`

Uso típico (subagente):
  python3 task_tools.py complete --task-id 123 --result-json '{"ok":true,"artifact":"/path"}'

Regras:
- Sempre setar `status` terminal (`completed`/`failed`) ao encerrar o trabalho.
- Para rework: setar `status=requeued` + incrementar `rework_round`.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

PROJ_ROOT = "/home/openclaw/projetos_ia"
DEFAULT_DB_PATH = os.path.join(PROJ_ROOT, "comms_manager/iarvis_comms.db")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_task(db_path: str, task_id: int) -> Optional[Dict[str, Any]]:
    with db_conn(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_task(
    db_path: str,
    task_id: int,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    assigned_agent_id: Optional[str] = None,
    rework_round: Optional[int] = None,
) -> None:
    # NOTE: schema is forward-compatible. Some installs may not have the
    # monitoring columns yet; we try to update them best-effort.
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

    # Best-effort monitoring fields (if present)
    sets.append("last_progress_at=?")
    params.append(datetime.now(timezone.utc).isoformat())
    sets.append("stalemate_cycles=0")

    params.append(task_id)

    q = f"UPDATE tasks SET {', '.join(sets)} WHERE id=?"
    with db_conn(db_path) as conn:
        cur = conn.cursor()
        try:
            cur.execute(q, tuple(params))
        except sqlite3.OperationalError:
            # Older schema: retry without monitoring columns
            sets = ["status=?"]
            params = [status]
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
            q2 = f"UPDATE tasks SET {', '.join(sets)} WHERE id=?"
            cur.execute(q2, tuple(params))
        conn.commit()


def add_signal(
    db_path: str,
    sender_agent: str,
    receiver_agent: str,
    message_type: str,
    payload: Dict[str, Any],
    status: str = "pending",
) -> None:
    with db_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status, timestamp)
            VALUES (?,?,?,?,?,?)
            """,
            (
                sender_agent,
                receiver_agent,
                message_type,
                json.dumps(payload, ensure_ascii=False),
                status,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()


def parse_json(s: str) -> Dict[str, Any]:
    try:
        val = json.loads(s)
        if not isinstance(val, dict):
            raise ValueError("result-json must be a JSON object")
        return val
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}")


def cmd_complete(args: argparse.Namespace) -> None:
    task = fetch_task(args.db, args.task_id)
    if not task:
        print(f"ERROR: task {args.task_id} not found", file=sys.stderr)
        raise SystemExit(2)

    result = parse_json(args.result_json) if args.result_json else {}
    result.setdefault("completed_at", utcnow_iso())
    result.setdefault("by", args.sender)

    update_task(args.db, args.task_id, "completed", result=result, assigned_agent_id=args.assigned_agent_id)
    add_signal(
        args.db,
        sender_agent=args.sender,
        receiver_agent="iarvis_worker",
        message_type="task_completed",
        payload={"task_id": args.task_id, "result": result},
        status="pending",
    )

    print(f"OK: task {args.task_id} completed")


def cmd_fail(args: argparse.Namespace) -> None:
    task = fetch_task(args.db, args.task_id)
    if not task:
        print(f"ERROR: task {args.task_id} not found", file=sys.stderr)
        raise SystemExit(2)

    result = parse_json(args.result_json) if args.result_json else {}
    result.setdefault("failed_at", utcnow_iso())
    result.setdefault("by", args.sender)

    update_task(args.db, args.task_id, "failed", result=result, assigned_agent_id=args.assigned_agent_id)
    add_signal(
        args.db,
        sender_agent=args.sender,
        receiver_agent="iarvis_worker",
        message_type="task_failed",
        payload={"task_id": args.task_id, "result": result},
        status="pending",
    )

    print(f"OK: task {args.task_id} failed")


def cmd_requeue(args: argparse.Namespace) -> None:
    task = fetch_task(args.db, args.task_id)
    if not task:
        print(f"ERROR: task {args.task_id} not found", file=sys.stderr)
        raise SystemExit(2)

    current_round = int(task.get("rework_round") or 0)
    next_round = current_round + 1

    result = parse_json(args.result_json) if args.result_json else {}
    result.setdefault("requeued_at", utcnow_iso())
    result.setdefault("by", args.sender)
    result.setdefault("rework_round", next_round)

    update_task(
        args.db,
        args.task_id,
        "requeued",
        result=result,
        assigned_agent_id=args.assigned_agent_id,
        rework_round=next_round,
    )

    add_signal(
        args.db,
        sender_agent=args.sender,
        receiver_agent="iarvis_worker",
        message_type="rework_requested",
        payload={"task_id": args.task_id, "rework_round": next_round, "result": result},
        status="pending",
    )

    print(f"OK: task {args.task_id} requeued (round={next_round})")


def _add_common(subp: argparse.ArgumentParser) -> None:
    subp.add_argument("--sender", required=True, help="Nome do agente/remetente (dev/aud/sys/doc/Iarvis)")
    subp.add_argument("--assigned-agent-id", default=None, help="assigned_to_agent_id para auditoria")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Workflow Iarvis - task tools")
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Path do DB (iarvis_comms.db)")

    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("complete", help="Marca task como completed + signal task_completed")
    _add_common(c)
    c.add_argument("--task-id", type=int, required=True)
    c.add_argument("--result-json", default=None)
    c.set_defaults(func=cmd_complete)

    f = sub.add_parser("fail", help="Marca task como failed + signal task_failed")
    _add_common(f)
    f.add_argument("--task-id", type=int, required=True)
    f.add_argument("--result-json", default=None)
    f.set_defaults(func=cmd_fail)

    r = sub.add_parser("requeue", help="Marca task como requeued + incrementa rework_round")
    _add_common(r)
    r.add_argument("--task-id", type=int, required=True)
    r.add_argument("--result-json", default=None)
    r.set_defaults(func=cmd_requeue)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
