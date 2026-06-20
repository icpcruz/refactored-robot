#!/usr/bin/env python3
"""cron_ingest_code_audit.py - Ingest relatórios_cron into tasks (cron_jobs project).

Objetivo
- Ler um relatório gerado por crons ("relatórios_cron") e transformar em tasks no
  SQLite `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`.
- O `iarvis_worker` consome essas tasks no próximo heartbeat.

Requisitos
- Holístico: não fixar quantidade de tasks; criar tasks conforme o conteúdo do report.
- Dry-run: sempre gerar artefato JSON em `cron-jobs-tests/` e NÃO tocar o DB.

Exemplos
  python3 cron_ingest_code_audit.py \
    --report /path/to/report.txt \
    --project cron_jobs \
    --dry-run

  python3 cron_ingest_code_audit.py \
    --report /path/to/report.txt \
    --project cron_jobs
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PRJ_ROOT = "/home/openclaw/projetos_ia"
DEFAULT_ARTIFACTS_ROOT = Path(f"{PRJ_ROOT}/governança_ambiente/cron-jobs-tests")
DEFAULT_DB_PATH = Path(f"{PRJ_ROOT}/comms_manager/iarvis_comms.db")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def report_freshness(path: Path, max_age_hours: float) -> Dict[str, Any]:
    """Return freshness metadata for the report based on filesystem mtime."""
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    age_hours = (now - mtime).total_seconds() / 3600
    return {
        "mtime_utc": mtime.isoformat(),
        "age_hours": round(age_hours, 3),
        "max_age_hours": max_age_hours,
        "is_stale": age_hours > max_age_hours,
        "size_bytes": stat.st_size,
    }


def parse_report(path: Path, *, max_age_hours: float, allow_stale: bool = False) -> Dict[str, Any]:
    """Parser minimalista.

    Regras atuais:
    - itens acionáveis: linhas começando com '-' OU contendo ERROR/Error/Exception.
    - segurança operacional: relatório stale (> max_age_hours) vira noop, salvo
      override explícito. Isso evita recriar diariamente findings antigos/dry-run.
    """
    freshness = report_freshness(path, max_age_hours)
    if freshness["is_stale"] and not allow_stale:
        return {
            "report_path": str(path),
            "items": [],
            "summary": "Stale report ignored; noop required",
            "freshness": freshness,
            "noop_reason": "report_mtime_older_than_max_age",
        }

    text = path.read_text(encoding="utf-8", errors="ignore")
    items: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("-") or "ERROR" in s or "Error" in s or "Exception" in s:
            items.append(s)

    return {
        "report_path": str(path),
        "items": items,
        "summary": f"{len(items)} findings" if items else "No actionable items",
        "freshness": freshness,
    }


def _db_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(db_path: str) -> None:
    """Ensure the minimal schema needed by this ingester exists.

    We cannot assume `/comms_manager/setup_comms_db.py` was executed or that it
    contains all tables used here.
    """
    with _db_conn(db_path) as conn:
        cur = conn.cursor()

        # Projects
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT
            )
            """
        )

        # Tasks (consumed by iarvis_worker)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_agent TEXT NOT NULL,
                target_agent TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                project_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            )
            """
        )

        # Agent signals (extend the base comms DB if needed)
        # Historical DBs may exist without `project_id`; we add it if missing.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_agent TEXT NOT NULL,
                receiver_agent TEXT NOT NULL,
                message_type TEXT NOT NULL,
                payload_json TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
            """
        )
        try:
            cur.execute("ALTER TABLE agent_signals ADD COLUMN project_id TEXT")
        except sqlite3.OperationalError:
            # duplicate column name / cannot alter (already present)
            pass

        # Helpful indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON agent_signals(status)")

        conn.commit()


def ensure_project(db_path: str, project_id: str) -> None:
    ensure_schema(db_path)
    with _db_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO projects (project_id, name, description, created_at) VALUES (?,?,?,?)",
            (project_id, project_id, "cron_jobs: ingestão de relatórios_cron", utcnow_iso()),
        )
        conn.commit()


def insert_task(
    db_path: str,
    project_id: str,
    source_agent: str,
    target_agent: str,
    action: str,
    payload: Dict[str, Any],
    status: str = "pending",
) -> int:
    ensure_schema(db_path)
    with _db_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (source_agent, target_agent, action, payload_json, status, project_id)
            VALUES (?,?,?,?,?,?)
            """,
            (source_agent, target_agent, action, json.dumps(payload, ensure_ascii=False), status, project_id),
        )
        conn.commit()
        return int(cur.lastrowid)


def emit_signal(db_path: str, project_id: str, payload: Dict[str, Any]) -> None:
    ensure_schema(db_path)
    with _db_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status, project_id)
            VALUES (?,?,?,?,?,?)
            """,
            (
                "cron_jobs_ingest",
                "iarvis_worker",
                "cron_report_ingested",
                json.dumps(payload, ensure_ascii=False),
                "pending",
                project_id,
            ),
        )
        conn.commit()


def write_artifact(artifacts_root: Path, payload: Dict[str, Any]) -> Path:
    artifacts_root.mkdir(parents=True, exist_ok=True)
    artefact = artifacts_root / f"ingest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.json"
    artefact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return artefact


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest relatórios_cron into cron_jobs tasks")
    parser.add_argument("--report", required=False, help="Path to the latest relatórios_cron file")
    parser.add_argument("--project", default="cron_jobs", help="Project id for new tasks")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no DB write)")
    parser.add_argument(
        "--max-report-age-hours",
        type=float,
        default=24.0,
        help="Maximum report mtime age before treating it as stale/noop (default: 24)",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Override stale-report guard and ingest old reports anyway",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to iarvis_comms.db")
    parser.add_argument(
        "--artifacts-root",
        default=str(DEFAULT_ARTIFACTS_ROOT),
        help="Onde escrever artefatos (default: cron-jobs-tests)",
    )
    args = parser.parse_args()

    artifacts_root = Path(args.artifacts_root)

    report_path = Path(args.report) if args.report else None
    if report_path and report_path.exists():
        report_meta = parse_report(
            report_path,
            max_age_hours=args.max_report_age_hours,
            allow_stale=bool(args.allow_stale),
        )
    else:
        report_meta = {
            "report_path": str(report_path) if report_path else None,
            "items": [],
            "summary": "No report provided",
            "noop_reason": "report_missing_or_not_provided",
        }

    ingest_payload: Dict[str, Any] = {
        "project": args.project,
        "report": report_meta,
        "dry_run": bool(args.dry_run),
        "created_at": utcnow_iso(),
    }
    artefact = write_artifact(artifacts_root, ingest_payload)

    if args.dry_run:
        print(f"DRY-RUN: artefato criado em {artefact}")
        print("Relatório processado (resumo):", report_meta.get("summary"))
        if report_meta.get("noop_reason"):
            print("NOOP reason:", report_meta.get("noop_reason"))
        if report_meta.get("freshness"):
            print("Freshness:", report_meta.get("freshness"))
        print("Itens encontrados (amostra):", (report_meta.get("items") or [])[:5])
        return

    # Produção: criar tasks + signal pro worker.
    db_path = str(args.db)
    ensure_project(db_path, args.project)

    created_task_ids: List[int] = []

    items = report_meta.get("items") or []
    if not items:
        tid = insert_task(
            db_path,
            project_id=args.project,
            source_agent="cron_jobs_ingest",
            target_agent="Doc",
            action="cron_report_noop",
            payload={
                "summary": report_meta.get("summary"),
                "report_path": report_meta.get("report_path"),
                "noop_reason": report_meta.get("noop_reason"),
                "freshness": report_meta.get("freshness"),
                "artifact": str(artefact),
            },
        )
        created_task_ids.append(tid)
    else:
        for it in items:
            tid = insert_task(
                db_path,
                project_id=args.project,
                source_agent="cron_jobs_ingest",
                target_agent="Dev",
                action="triage_cron_finding",
                payload={
                    "finding": it,
                    "report_path": report_meta.get("report_path"),
                    "summary": report_meta.get("summary"),
                    "artifact": str(artefact),
                },
            )
            created_task_ids.append(tid)

    emit_signal(
        db_path,
        project_id=args.project,
        payload={
            "task_ids": created_task_ids,
            "report_path": report_meta.get("report_path"),
            "artifact": str(artefact),
            "summary": report_meta.get("summary"),
        },
    )

    print("OK: ingestão concluída")
    print("Tasks criadas:", created_task_ids)
    print("Artefato:", artefact)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise
