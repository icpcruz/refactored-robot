import os
import json
import sqlite3
from datetime import datetime, timezone

DB = "/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db"
ART_DIR = "/home/openclaw/projetos_ia/governança_ambiente/workflow_tests/artifacts"
os.makedirs(ART_DIR, exist_ok=True)

# Ensure schema exists (non-destructive)
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        source_agent TEXT NOT NULL,
        target_agent TEXT NOT NULL,
        action TEXT NOT NULL,
        payload_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        result_json TEXT,
        rework_round INTEGER DEFAULT 0,
        max_rework_rounds INTEGER DEFAULT 2
    );""",
    """CREATE TABLE IF NOT EXISTS workflow_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        run_name TEXT NOT NULL,
        mode TEXT NOT NULL, -- linear|loop
        status TEXT NOT NULL DEFAULT 'in_progress'
    );""",
]


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def db_conn():
    return sqlite3.connect(DB)


def ensure_schema():
    with db_conn() as con:
        cur = con.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        con.commit()


def insert_task(source, target, action, payload, status="pending", rework_round=0, max_rework_rounds=2):
    with db_conn() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO tasks (source_agent, target_agent, action, payload_json, status, rework_round, max_rework_rounds) VALUES (?,?,?,?,?,?,?)",
            (source, target, action, json.dumps(payload), status, rework_round, max_rework_rounds),
        )
        con.commit()
        return cur.lastrowid


def update_task(task_id, status, result=None, rework_round=None):
    with db_conn() as con:
        cur = con.cursor()
        sets = ["status=?", "result_json=?"]
        params = [status, json.dumps(result or {})]
        if rework_round is not None:
            sets.append("rework_round=?")
            params.append(int(rework_round))
        params.append(task_id)
        cur.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)
        con.commit()


def start_run(run_name, mode):
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO workflow_runs (run_name, mode, status) VALUES (?,?,?)", (run_name, mode, "in_progress"))
        con.commit()
        return cur.lastrowid


def finish_run(run_id, status):
    with db_conn() as con:
        cur = con.cursor()
        cur.execute("UPDATE workflow_runs SET status=? WHERE id=?", (status, run_id))
        con.commit()


def write_artifact(name, content):
    path = os.path.join(ART_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def simulate_linear():
    run_id = start_run(f"workflow_linear_{utcnow()}", "linear")

    dev_art = write_artifact("linear_01_dev.md", f"[{utcnow()}] Dev: artefato inicial\n")
    t1 = insert_task("Dev", "Aud", "review_artifact", {"artifact": dev_art, "marker": "L1"})

    aud_art = write_artifact("linear_02_aud.md", f"[{utcnow()}] Aud: revisado OK (marker L1)\n")
    update_task(t1, "completed", {"approved": True, "aud_artifact": aud_art})

    sys_art = write_artifact("linear_03_sys.txt", f"[{utcnow()}] Sys: guard ok (marker L1)\n")
    t2 = insert_task("Aud", "Sys", "run_guard", {"input": aud_art, "marker": "L1"})
    update_task(t2, "completed", {"guard_ok": True, "sys_artifact": sys_art})

    doc_art = write_artifact("linear_04_doc.md", f"[{utcnow()}] Doc: doc atualizada (marker L1)\n")
    t3 = insert_task("Sys", "Doc", "update_docs", {"input": sys_art, "marker": "L1"})
    update_task(t3, "completed", {"doc_path": doc_art})

    t4 = insert_task("Doc", "Iarvis", "close_cycle", {"summary": "linear ok", "marker": "L1"})
    update_task(t4, "completed", {"closed": True})

    finish_run(run_id, "completed")
    return run_id


def simulate_loop():
    run_id = start_run(f"workflow_loop_{utcnow()}", "loop")

    dev_art = write_artifact("loop_01_dev.md", f"[{utcnow()}] Dev: artefato inicial (loop)\n")
    t1 = insert_task("Dev", "Aud", "review_artifact", {"artifact": dev_art, "marker": "LP"}, rework_round=0, max_rework_rounds=2)

    # Aud requests rework round 1
    update_task(t1, "requeued", {"approved": False, "notes": "pendência 1"}, rework_round=1)

    # Dev responds
    dev_fix = write_artifact("loop_02_dev_fix.md", f"[{utcnow()}] Dev: correção round 1 aplicada\n")
    update_task(t1, "in_progress", {"dev_fix": dev_fix}, rework_round=1)

    # Aud requests rework round 2
    update_task(t1, "requeued", {"approved": False, "notes": "pendência 2"}, rework_round=2)

    # Dev responds round 2
    dev_fix2 = write_artifact("loop_03_dev_fix2.md", f"[{utcnow()}] Dev: correção round 2 aplicada\n")
    update_task(t1, "in_progress", {"dev_fix": dev_fix2}, rework_round=2)

    # Aud approves (stop condition: max 2 reached; approve or escalate)
    aud_art = write_artifact("loop_04_aud_ok.md", f"[{utcnow()}] Aud: aprovado após 2 reworks (marker LP)\n")
    update_task(t1, "completed", {"approved": True, "aud_artifact": aud_art}, rework_round=2)

    # Continue flow
    sys_art = write_artifact("loop_05_sys.txt", f"[{utcnow()}] Sys: guard ok (marker LP)\n")
    t2 = insert_task("Aud", "Sys", "run_guard", {"input": aud_art, "marker": "LP"})
    update_task(t2, "completed", {"guard_ok": True, "sys_artifact": sys_art})

    doc_art = write_artifact("loop_06_doc.md", f"[{utcnow()}] Doc: doc atualizada (marker LP)\n")
    t3 = insert_task("Sys", "Doc", "update_docs", {"input": sys_art, "marker": "LP"})
    update_task(t3, "completed", {"doc_path": doc_art})

    t4 = insert_task("Doc", "Iarvis", "close_cycle", {"summary": "loop ok", "marker": "LP"})
    update_task(t4, "completed", {"closed": True})

    finish_run(run_id, "completed")
    return run_id


def main():
    ensure_schema()
    r1 = simulate_linear()
    r2 = simulate_loop()
    print(f"OK: workflow linear run_id={r1}")
    print(f"OK: workflow loop run_id={r2}")
    print(f"DB: {DB}")
    print(f"Artifacts: {ART_DIR}")


if __name__ == "__main__":
    main()
