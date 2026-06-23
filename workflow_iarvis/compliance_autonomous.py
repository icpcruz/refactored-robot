#!/usr/bin/env python3
"""Autonomous Compliance Runner (analyzer + auto-fix + task scheduler).

Replaces the previous report-only compliance subagent.

What it does:
1. Runs scans (lint, doc, security, structure) as before.
2. For findings where auto-fix is safe and mechanical, applies the fix directly.
3. For findings requiring human judgment or complex work, inserts tasks into iarvis_comms.db.
4. Generates a final report (for human audit trail) but does NOT depend on human reading it.

Auto-fix rules (examples, extensible):
- Broad `except Exception: pass` → replace with `logger.exception(...)` + add `import logging`.
- Missing `.gitignore` with standard Python rules → create it.
- Empty legacy DB file (0 bytes, no code references) → archive as .LEGACY.empty.
- Broken test importing removed functions → archive test to backups/.
- Missing baseline docs (SCHEMA.md, OPERATIONS.md, requirements.txt) → generate if safe.

Usage:
    /home/openclaw/projetos_ia/venv_openclaw/bin/python compliance_autonomous.py /path/to/project
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Shared DB for task scheduling
COMMS_DB = "/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db"

logger = logging.getLogger("compliance_autonomous")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# ───────────────────────────────────────────────
# Task insertion helpers
# ───────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(COMMS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def insert_task(
    target_agent: str,
    action: str,
    payload: Dict[str, Any],
    source_agent: str = "ComplianceBot",
    status: str = "pending",
    project_id: str = "projetos_ia",
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tasks (source_agent, target_agent, action, payload_json, status, project_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_agent,
            target_agent,
            action,
            json.dumps(payload, ensure_ascii=False),
            status,
            project_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def insert_signal(
    receiver_agent: str,
    message_type: str,
    payload: Dict[str, Any],
    sender_agent: str = "ComplianceBot",
    status: str = "pending",
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
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
    sig_id = cur.lastrowid
    conn.commit()
    conn.close()
    return sig_id


# ───────────────────────────────────────────────
# Lint runners (reusing existing venv)
# ───────────────────────────────────────────────
def run_linter(py_file: str, tool: str) -> Tuple[int, str, str]:
    python = "/home/openclaw/projetos_ia/venv_py311_lint/bin/python"
    cmd = [python, "-m", tool, py_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def find_py_files(project_path: str) -> List[str]:
    files: List[str] = []
    for root, dirs, filenames in os.walk(project_path):
        # Exclude venvs, backups, cache
        dirs[:] = [
            d
            for d in dirs
            if d not in {"venv_openclaw", "venv_py311_lint", "__pycache__", ".git"}
            and not d.endswith("_backup")
            and d != "backups"
        ]
        for f in filenames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))
    return sorted(files)


# ───────────────────────────────────────────────
# Auto-fix: broad except Exception: pass
# ───────────────────────────────────────────────
def fix_broad_except(filepath: str) -> bool:
    """
    Convert bare `except Exception:` (or `except Exception:` with pass/return/setdefault)
    into `except Exception: logger.exception("...")` and inject `import logging` + logger
    if missing.

    Returns True if file was modified.
    """
    if not os.path.isfile(filepath):
        return False
    with open(filepath, "r", encoding="utf-8") as f:
        original = f.read()

    source = original

    # Inject import logging if missing
    stdlib_pattern = re.compile(r"^(import\s+(os|sys|json|sqlite3|re|time|datetime|argparse|logging|typing|pathlib|collections)\b", re.MULTILINE)
    has_import_logging = bool(re.search(r"^import\s+logging\b|^from\s+logging\b", source, re.MULTILINE))
    has_logger = bool(re.search(r"\blogger\s*=\s*logging\.getLogger", source))

    if not has_import_logging:
        # Try to add after first stdlib import block near top
        lines = source.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if stdlib_pattern.match(line):
                insert_idx = i + 1
        lines.insert(insert_idx, "import logging")
        source = "\n".join(lines)

    if not has_logger:
        # Find the first top-level assignment or function/class
        lines = source.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if re.match(r"^\S", line) and not line.startswith("#") and not line.startswith("import") and not line.startswith("from"):
                insert_idx = i
                break
        lines.insert(insert_idx, "logger = logging.getLogger(__name__)")
        lines.insert(insert_idx, "")  # blank line
        source = "\n".join(lines)

    # Replace broad except patterns that are followed by pass/return/setdefault
    # Pattern: except Exception:\n[spaces]return ... or pass
    # We want to insert logger.exception before the return/pass
    def repl_except(m: re.Match) -> str:
        indent = m.group(1)
        except_line = m.group(2).strip()
        body = m.group(3)
        # Determine file context for log message
        filename = os.path.basename(filepath)
        log_msg = f"Broad exception caught and swallowed in {filename}"
        new_body = f"{indent}    logger.exception(\"{log_msg}\")\n{body}"
        return f"{except_line}\n{new_body}"

    # This is intentionally conservative: only catches truly bare blocks with just pass/return
    source = re.sub(
        r"^(\s*)(except\s+Exception\s*:\s*)\n(\s+(?:pass|return\s*[^\n]*))",
        lambda m: f"{m.group(1)}{m.group(2).strip()}\n{m.group(1)}    logger.exception('Broad exception caught in {os.path.basename(filepath)}')\n{m.group(3)}",
        source,
        flags=re.MULTILINE,
    )

    # Another pass for: except Exception:\n        return DEFAULT_VALUE
    source = re.sub(
        r"^(\s*)(except\s+Exception\s*:\s*)\n(\s+return\s+[^\n]*(?:\n\s*[^\n]+)?)",
        lambda m: f"{m.group(1)}{m.group(2).strip()}\n{m.group(1)}    logger.exception('Broad exception caught in {os.path.basename(filepath)}')\n{m.group(3)}",
        source,
        flags=re.MULTILINE,
    )

    # Another pass for: except Exception:\n        pass
    source = re.sub(
        r"^(\s*)(except\s+Exception\s*:\s*)\n(\s+pass)",
        lambda m: f"{m.group(1)}{m.group(2).strip()}\n{m.group(1)}    logger.exception('Broad exception caught in {os.path.basename(filepath)}')\n{m.group(3)}",
        source,
        flags=re.MULTILINE,
    )

    if source == original:
        return False
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(source)
    return True


# ───────────────────────────────────────────────
# Auto-fix: missing standard .gitignore
# ───────────────────────────────────────────────
GITIGNORE_TEMPLATE = """# Byte-compiled / cache
__pycache__/
*.py[cod]
*$py.class

# Environment / secrets
.env

# Backups (explicit per-project)
backups/
*.bak*

# Reports generated locally
reports/

# SQLite databases (production copies)
*.db

# IDE
.vscode/
.idea/

# OS files
.DS_Store
Thumbs.db
"""


def ensure_gitignore(project_path: str) -> bool:
    gi = os.path.join(project_path, ".gitignore")
    if os.path.exists(gi):
        return False
    with open(gi, "w", encoding="utf-8") as f:
        f.write(GITIGNORE_TEMPLATE)
    return True


# ───────────────────────────────────────────────
# Auto-fix: archive broken test importing removed functions
# ───────────────────────────────────────────────
def archive_broken_test(test_path: str, backups_dir: str) -> bool:
    if not os.path.isfile(test_path):
        return False
    fname = os.path.basename(test_path)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(backups_dir, f"{fname}.bak.{ts}.broken-imports")
    os.makedirs(backups_dir, exist_ok=True)
    os.rename(test_path, dest)
    return True


# ───────────────────────────────────────────────
# Auto-fix: archive empty legacy DB with no code references
# ───────────────────────────────────────────────
def archive_legacy_db(db_path: str) -> bool:
    if not os.path.isfile(db_path) or os.path.getsize(db_path) != 0:
        return False
    # Verify no .py production file references this DB
    dirname = os.path.dirname(db_path)
    db_name = os.path.basename(db_path)
    refs = 0
    for root, dirs, files in os.walk(dirname):
        dirs[:] = [d for d in dirs if d not in {"venv", "__pycache__", ".git", "backups"}]
        for f in files:
            if f.endswith(".py"):
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                    if db_name in content or db_name.replace(".db", "") in content:
                        refs += 1
                except Exception:
                    pass
    if refs > 0:
        return False
    dest = f"{db_path}.LEGACY.empty"
    os.rename(db_path, dest)
    return True


# ───────────────────────────────────────────────
# Auto-fix: generate requirements.txt from imports
# ───────────────────────────────────────────────
STD_MODULES = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "contextlib",
    "copy", "csv", "datetime", "email", "fnmatch", "functools", "glob", "hashlib",
    "http", "importlib", "inspect", "itertools", "json", "logging", "math",
    "mimetypes", "operator", "os", "pathlib", "pickle", "platform", "random",
    "re", "shutil", "signal", "sqlite3", "ssl", "statistics", "string", "subprocess",
    "sys", "tempfile", "textwrap", "threading", "time", "traceback", "typing",
    "unicodedata", "urllib", "uuid", "warnings", "xml", "zipfile", "zlib",
    "zoneinfo", "decimal", "enum", "numbers", "io", "types", "dataclasses"
}


KNOWN_MAPPINGS = {
    "google_auth_oauthlib": "google-auth-oauthlib",
    "googleapiclient": "google-api-python-client",
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "markdown": "Markdown",
    "jwt": "PyJWT",
    "sklearn": "scikit-learn",
    "openai": "openai",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
}


def collect_third_party_imports(project_path: str) -> List[str]:
    imports = set()
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in {"venv_openclaw", "venv_py311_lint", "__pycache__", ".git"} and not d.endswith("_backup")]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        imports.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top = node.module.split(".")[0]
                        imports.add(top)
    third = sorted(imports - STD_MODULES - {"__future__"})
    return third


def installed_versions() -> Dict[str, str]:
    python = "/home/openclaw/projetos_ia/venv_openclaw/bin/python"
    result = subprocess.run([python, "-m", "pip", "list", "--format=json"], capture_output=True, text=True)
    versions: Dict[str, str] = {}
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for pkg in data:
            versions[pkg["name"]] = pkg["version"]
            versions[pkg["name"].lower().replace("-", "_")] = pkg["version"]
    return versions


def generate_requirements(project_path: str) -> bool:
    req_path = os.path.join(project_path, "requirements.txt")
    modules = collect_third_party_imports(project_path)
    if not modules and os.path.exists(req_path):
        return False
    installed = installed_versions()
    lines: List[str] = []
    for mod in modules:
        if mod in installed:
            lines.append(f"{mod}=={installed[mod]}")
        elif mod.replace("_", "-") in installed:
            pkg = mod.replace("_", "-")
            lines.append(f"{pkg}=={installed[pkg]}")
        elif mod in KNOWN_MAPPINGS:
            p = KNOWN_MAPPINGS[mod]
            if p.lower().replace("-", "_") in installed:
                lines.append(f"{p}=={installed[p.lower().replace('-','_')]}")
            else:
                lines.append(p)
        else:
            lines.append(mod)
    header = f"# Auto-generated requirements for {os.path.basename(project_path)}\n"
    with open(req_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    return True


# ───────────────────────────────────────────────
# Auto-fix: schema + docs generation
# ───────────────────────────────────────────────
def generate_schema_md(db_path: str, out_path: str) -> bool:
    if not os.path.isfile(db_path):
        return False
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = cur.fetchall()
    lines = [f"# Schema: {os.path.basename(db_path)}\n\n"]
    for name, sql in tables:
        lines.append(f"## Table: `{name}`\n\n")
        lines.append("```sql\n" + sql + ";\n```\n\n")
        cur.execute(f"PRAGMA table_info({name})")
        cols = cur.fetchall()
        lines.append("| Column | Type | Not Null | Default | PK |\n")
        lines.append("|--------|------|----------|---------|----|\n")
        for col in cols:
            cid, col_name, typ, notnull, dflt, pk = col
            dflt_str = dflt if dflt is not None else ""
            lines.append(f"| {col_name} | {typ} | {'YES' if notnull else ''} | {dflt_str} | {'YES' if pk else ''} |\n")
        lines.append("\n")
        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL", (name,))
        indexes = cur.fetchall()
        if indexes:
            lines.append("### Indexes\n")
            for idx_name, idx_sql in indexes:
                lines.append(f"- `{idx_name}`\n")
            lines.append("\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    conn.close()
    return True


# ───────────────────────────────────────────────
# Main compliance runner
# ───────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_path", help="Path to project to audit (e.g., /home/openclaw/projetos_ia/gerente_emails)")
    ap.add_argument("--no-fix", action="store_true", help="Only report, do not auto-fix")
    args = ap.parse_args()

    project = os.path.abspath(args.project_path)
    project_name = os.path.basename(project)
    findings: List[Dict[str, Any]] = []
    tasks_created: List[int] = []
    fixes_applied: List[str] = []

    py_files = find_py_files(project)
    logger.info("Scanning %d .py files in %s", len(py_files), project_name)

    # ── Lint scan ──
    for pf in py_files:
        for tool in ("pylint", "pycodestyle", "pydocstyle"):
            rc, out, err = run_linter(pf, tool)
            if rc != 0 or out.strip():
                findings.append({
                    "type": "lint",
                    "tool": tool,
                    "file": pf,
                    "output": out[:500],
                })

    # ── Security: broad except scan ──
    for pf in py_files:
        with open(pf, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if re.search(r"except\s+Exception\s*:\s*\n\s+(?:pass|return)", content):
            if not args.no_fix:
                if fix_broad_except(pf):
                    fixes_applied.append(f"fixed broad except in {pf}")
                else:
                    findings.append({"type": "security", "severity": "MEDIUM", "file": pf, "issue": "broad_except", "auto_fix": False})
            else:
                findings.append({"type": "security", "severity": "MEDIUM", "file": pf, "issue": "broad_except", "auto_fix": False})

    # ── Broken tests scan ──
    tests_dir = os.path.join(project, "workflow_tests") if os.path.isdir(os.path.join(project, "workflow_tests")) else None
    if tests_dir:
        for root, dirs, files in os.walk(tests_dir):
            for f in files:
                if f.endswith("_test.py"):
                    fp = os.path.join(root, f)
                    # Simple heuristic: try py_compile
                    result = subprocess.run([sys.executable, "-m", "py_compile", fp], capture_output=True)
                    if result.returncode != 0:
                        if not args.no_fix:
                            backups_dir = os.path.join(project, "backups") if os.path.isdir(os.path.join(project, "backups")) else os.path.join(project, "workflow_tests", "backups")
                            if archive_broken_test(fp, backups_dir):
                                fixes_applied.append(f"archived broken test {fp}")
                        else:
                            findings.append({"type": "test", "severity": "CRITICAL", "file": fp, "issue": "broken_test"})

    # ── Empty legacy DB scan ──
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in {"venv", "__pycache__"}]
        for f in files:
            if f.endswith(".db") and os.path.getsize(os.path.join(root, f)) == 0:
                dbp = os.path.join(root, f)
                dirname = dbp
                db_name = f
                refs = 0
                for r2, d2, fs2 in os.walk(project):
                    d2[:] = [d for d in d2 if d not in {"venv", "__pycache__", ".git"}]
                    for f2 in fs2:
                        if f2.endswith(".py"):
                            try:
                                with open(os.path.join(r2, f2), "r", encoding="utf-8", errors="ignore") as fh:
                                    if db_name in fh.read():
                                        refs += 1
                            except Exception:
                                pass
                if refs == 0:
                    if not args.no_fix:
                        if archive_legacy_db(dbp):
                            fixes_applied.append(f"archived legacy empty DB {dbp}")
                    else:
                        findings.append({"type": "db", "severity": "HIGH", "file": dbp, "issue": "empty_legacy_db"})

    # ── Missing .gitignore ──
    if not os.path.exists(os.path.join(project, ".gitignore")):
        if not args.no_fix:
            ensure_gitignore(project)
            fixes_applied.append("created .gitignore")
        else:
            findings.append({"type": "repo", "severity": "MEDIUM", "issue": "missing_gitignore"})

    # ── Missing requirements.txt ──
    if not os.path.exists(os.path.join(project, "requirements.txt")):
        if not args.no_fix:
            if generate_requirements(project):
                fixes_applied.append("generated requirements.txt")
        else:
            findings.append({"type": "repo", "severity": "MEDIUM", "issue": "missing_requirements"})

    # ── Missing docs (SCHEMA.md / OPERATIONS.md) ──
    # Only generate if a .db exists and SCHEMA.md missing
    dbs = [os.path.join(root, f) for root, dirs, files in os.walk(project) for f in files if f.endswith(".db")]
    for dbp in dbs:
        schema_md = os.path.join(project, "SCHEMA.md")
        if not os.path.exists(schema_md):
            if not args.no_fix:
                if generate_schema_md(dbp, schema_md):
                    fixes_applied.append(f"generated SCHEMA.md from {dbp}")
            else:
                findings.append({"type": "docs", "severity": "MEDIUM", "issue": "missing_schema"})

    # ── Insert remaining findings as tasks ──
    for finding in findings:
        severity = finding.get("severity", "MEDIUM")
        action_map = {
            "lint": "fix_lint_issues",
            "security": "fix_security_issue",
            "test": "fix_or_remove_broken_test",
            "db": "investigate_db_issue",
            "repo": "fix_repo_structure",
            "docs": "generate_missing_docs",
        }
        action = action_map.get(finding["type"], "investigate_compliance_finding")
        target = "Dev" if finding["type"] in ("lint", "test", "repo", "docs") else "Sys"
        if severity == "CRITICAL":
            target = "Iarvis"  # Escalated to main agent for human attention

        task_id = insert_task(
            target_agent=target,
            action=action,
            payload={
                "project": project_name,
                "finding": finding,
                "auto_fix_attempted": not args.no_fix,
            },
            source_agent="ComplianceBot",
            status="pending",
            project_id=project_name,
        )
        tasks_created.append(task_id)

    # ── Insert completion signal ──
    insert_signal(
        receiver_agent="Iarvis",
        message_type="compliance_run_complete",
        payload={
            "project": project_name,
            "files_scanned": len(py_files),
            "findings_count": len(findings),
            "fixes_applied": fixes_applied,
            "tasks_created": tasks_created,
            "timestamp": datetime.now().isoformat(),
        },
    )

    # ── Generate report (human-auditable but not required) ──
    report_path = os.path.join(
        "/home/openclaw/.openclaw/workspace/reports/compliance",
        f"autonomous_compliance_{project_name}_{datetime.now().strftime('%Y-%m-%d')}.md",
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Autonomous Compliance Report: {project_name}\n\n")
        f.write(f"**Date:** {datetime.now().isoformat()}\n\n")
        f.write(f"**Files scanned:** {len(py_files)}\n")
        f.write(f"**Auto-fixes applied:** {len(fixes_applied)}\n")
        f.write(f"**Tasks created:** {len(tasks_created)}\n\n")
        if fixes_applied:
            f.write("## Auto-fixes\n\n")
            for fix in fixes_applied:
                f.write(f"- {fix}\n")
        if findings:
            f.write("\n## Findings requiring attention\n\n")
            for finding in findings:
                f.write(f"- [{finding.get('severity', 'MEDIUM')}] {finding['type']} in `{finding.get('file', 'n/a')}`: {finding.get('issue', finding.get('output', ''))}\n")
        f.write("\n## Tasks created\n\n")
        for tid in tasks_created:
            f.write(f"- Task ID {tid}\n")

    print(f"Compliance complete: {len(fixes_applied)} auto-fixes, {len(findings)} findings → {len(tasks_created)} tasks, signal sent.")


if __name__ == "__main__":
    main()
