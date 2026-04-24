#!/usr/bin/env python3
"""Inventory and register SOP documents.

Goals:
- Scan /home/openclaw for files named SOP*.md
- Classify scope (active/archive/memory_snapshot/unknown)
- Compute sha256 + size + mtime
- Upsert into comms DB table `sop_registry`
- Emit inventory report (md + csv) under governança_ambiente/docs/sop_registry/

Designed as a lightweight ISO9001-ish document register without heavy bureaucracy.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import sqlite3
from pathlib import Path

BASE = "/home/openclaw"
DB_PATH = "/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db"
OUT_DIR = "/home/openclaw/projetos_ia/governança_ambiente/docs/sop_registry"

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "site-packages",
    ".venv",
    "venv",
    ".pytest_cache",
    "node_modules",
}


def _utc_iso(ts: float) -> str:
    return _dt.datetime.utcfromtimestamp(ts).isoformat() + "Z"


def scope_for(path: str) -> str:
    pl = path.lower()

    # snapshots and archival copies are not canonical
    if "/.openclaw/workspace/memory/" in pl:
        return "memory_snapshot"

    if any(x in pl for x in ("gerente_emails_backup_", "smoketests")):
        return "archive"

    if any(x in pl for x in ("backup", "/backups/", "rollback", "archive")):
        return "archive"

    if any(x in pl for x in ("/projetos_ia/", "/.openclaw/workspace/")):
        return "active"

    return "unknown"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_sops() -> list[str]:
    out: list[str] = []

    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            fnl = fn.lower()
            if fnl.endswith(".md") and fnl.startswith("sop"):
                out.append(os.path.join(root, fn))

    out.sort()
    return out


def ensure_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sop_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            path TEXT UNIQUE,
            scope TEXT,
            version TEXT,
            status TEXT DEFAULT 'inventory',
            last_seen TEXT,
            sha256 TEXT,
            size_bytes INTEGER,
            mtime_utc TEXT,
            approved_by TEXT,
            approved_at TEXT,
            notes TEXT
        )
        """
    )


def main() -> int:
    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

    inventory_ts = _dt.datetime.utcnow().isoformat() + "Z"
    sop_files = walk_sops()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    ensure_table(cur)

    md_lines = [
        f"# SOP Inventory ({inventory_ts})",
        "",
        f"Total found: {len(sop_files)}",
        "",
        "Legend: scope=active|archive|memory_snapshot|unknown",
        "",
        "## Files",
    ]

    csv_lines = ["path,filename,scope,mtime_utc,size_bytes,sha256"]

    for p in sop_files:
        try:
            st = os.stat(p)
            mtime = _utc_iso(st.st_mtime)
            size = st.st_size
            sha = sha256_file(p)
            scope = scope_for(p)
            fname = os.path.basename(p)

            cur.execute(
                """
                INSERT INTO sop_registry (filename, path, scope, last_seen, sha256, size_bytes, mtime_utc)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    sha256=excluded.sha256,
                    size_bytes=excluded.size_bytes,
                    scope=excluded.scope,
                    filename=excluded.filename,
                    mtime_utc=excluded.mtime_utc
                """,
                (fname, p, scope, inventory_ts, sha, size, mtime),
            )

            md_lines.append(
                f"- [{scope}] `{p}` (mtime={mtime}, size={size}, sha256={sha[:12]}...)"
            )
            csv_lines.append(f'"{p}","{fname}",{scope},{mtime},{size},{sha}')

        except Exception as e:
            md_lines.append(f"- [error] `{p}`: {e}")

    con.commit()

    # Provide a small summary to console
    cur.execute("SELECT scope, COUNT(*) FROM sop_registry GROUP BY scope ORDER BY COUNT(*) DESC")
    summary = cur.fetchall()
    con.close()

    date_str = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    out_md = os.path.join(OUT_DIR, f"SOP_INVENTORY_{date_str}.md")
    out_csv = os.path.join(OUT_DIR, f"SOP_INVENTORY_{date_str}.csv")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    with open(out_csv, "w", encoding="utf-8") as f:
        f.write("\n".join(csv_lines) + "\n")

    print("OK")
    print(out_md)
    print(out_csv)
    print("SUMMARY scopes:")
    for scope, cnt in summary:
        print(f"- {scope}: {cnt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
