#!/usr/bin/env python3
"""Migration: add multi-project support to iarvis_comms.db.

- Adds `project_id` column to: tasks, workflow_runs, agent_signals, agent_logs
- Adds `projects` registry table
- Seeds initial projects

Safe to run multiple times (idempotent best-effort).
"""

from __future__ import annotations

import datetime
import sqlite3

DB = "/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db"

PROJECTS = [
    ("default", "Iarvis Core", "Default single-squad project"),
    ("gerente_emails", "Gerente de E-mails", "Pipeline de e-mail de produção"),
    ("youtube_Isummary", "YouTube iSummary", "Projeto de sumarização YouTube"),
    ("insta_arcaprot", "Instagram ArcaProt", "Projeto de conteúdo Instagram"),
    ("workflow_iarvis", "Workflow Iarvis", "Governança e orquestração interna"),
]


def has_column(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def add_project_id(cur: sqlite3.Cursor, table: str) -> None:
    if has_column(cur, table, "project_id"):
        return
    cur.execute(
        f"ALTER TABLE {table} ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'"
    )


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1) Add project_id columns
    for t in ("tasks", "workflow_runs", "agent_signals", "agent_logs"):
        add_project_id(cur, t)

    # 2) Indices
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks (project_id)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_project ON workflow_runs (project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_signals_project ON agent_signals (project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_project ON agent_logs (project_id)"
    )

    # 3) Projects registry
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
          project_id TEXT PRIMARY KEY,
          name TEXT,
          description TEXT,
          created_at TEXT
        )
        """
    )

    now = datetime.datetime.utcnow().isoformat() + "Z"
    for pid, name, desc in PROJECTS:
        cur.execute(
            """
            INSERT OR IGNORE INTO projects (project_id, name, description, created_at)
            VALUES (?,?,?,?)
            """,
            (pid, name, desc, now),
        )

    # 4) Ensure existing rows have default project_id (defensive)
    for table in ("tasks", "workflow_runs", "agent_signals", "agent_logs"):
        cur.execute(
            f"UPDATE {table} SET project_id='default' WHERE project_id IS NULL OR project_id=''"
        )

    con.commit()
    con.close()

    print("OK: multi-project migration applied")


if __name__ == "__main__":
    main()
