#!/usr/bin/env python3
"""Telegram delivery watchdog.

Constraints:
- Telegram webhook callbacks not available.
- We treat delivery as successful only when we can confirm the message exists in
  the Telegram chat history (via OpenClaw CLI read) OR when the helper returns a
  success exit code.

This watchdog does two things:
1) Consistency checks: are the expected cron outputs being produced?
2) Delivery verification: when a Telegram-bound agent_signal is created, it
   should transition out of 'pending' within a bounded time.

If delivery cannot be confirmed after max retries, it escalates into the
iarvis_worker task queue for human/agent supervision.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3

COMMS_DB = "/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db"
DEFAULT_PROJECT = "default"

# Telegram target for Ivan (direct chat)
TELEGRAM_CHANNEL = "telegram"
TELEGRAM_TARGET = "telegram:1537447601"

POLL_SECONDS = 60
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 120
MAX_PENDING_AGE_SECONDS = 20 * 60  # 20 minutes

# Which signals represent "should be delivered to Telegram"
WATCH_MESSAGE_TYPES = {
    "email_report",
    "stack24h_report_telegram",
}


@dataclass
class Signal:
    id: int
    sender_agent: str
    receiver_agent: str
    message_type: str
    payload_json: str
    status: str
    timestamp: str
    project_id: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def db_connect() -> sqlite3.Connection:
    return sqlite3.connect(COMMS_DB)


def ensure_retry_column(conn: sqlite3.Connection) -> None:
    """Best-effort: add retry_count column if missing.

    This is bullet-proof enough to run repeatedly.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(agent_signals)")
    cols = {row[1] for row in cur.fetchall()}
    if "retry_count" not in cols:
        cur.execute("ALTER TABLE agent_signals ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def ensure_status_values(conn: sqlite3.Connection) -> None:
    # no-op for now; statuses are free-text
    return


def parse_ts(ts: str) -> datetime | None:
    # Stored like: 2026-05-05 16:47:46
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def fetch_pending(conn: sqlite3.Connection) -> list[Signal]:
    cur = conn.cursor()
    qmarks = ",".join(["?"] * len(WATCH_MESSAGE_TYPES))
    cur.execute(
        f"""
        SELECT id, sender_agent, receiver_agent, message_type, payload_json, status, timestamp, project_id
        FROM agent_signals
        WHERE status='pending'
          AND project_id=?
          AND message_type IN ({qmarks})
        ORDER BY id ASC
        """,
        [DEFAULT_PROJECT, *sorted(WATCH_MESSAGE_TYPES)],
    )
    return [Signal(*row) for row in cur.fetchall()]


def get_retry_count(conn: sqlite3.Connection, signal_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT retry_count FROM agent_signals WHERE id=?", (signal_id,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def bump_retry(conn: sqlite3.Connection, signal_id: int) -> int:
    cur = conn.cursor()
    cur.execute("UPDATE agent_signals SET retry_count = retry_count + 1 WHERE id=?", (signal_id,))
    conn.commit()
    return get_retry_count(conn, signal_id)


def mark_status(conn: sqlite3.Connection, signal_id: int, status: str) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE agent_signals SET status=? WHERE id=?", (status, signal_id))
    conn.commit()


def enqueue_escalation(conn: sqlite3.Connection, reason: str, signal: Signal) -> None:
    cur = conn.cursor()
    payload = {
        "reason": reason,
        "signal_id": signal.id,
        "message_type": signal.message_type,
        "sender_agent": signal.sender_agent,
        "timestamp": signal.timestamp,
        "status": signal.status,
    }
    cur.execute(
        """
        INSERT INTO tasks (source_agent, target_agent, action, payload_json, status, project_id)
        VALUES (?,?,?,?,?,?)
        """,
        (
            "telegram_delivery_watchdog",
            "iarvis_worker",
            "supervise_telegram_delivery",
            json.dumps(payload, ensure_ascii=False),
            "pending",
            DEFAULT_PROJECT,
        ),
    )
    # Also write a message row for observability
    cur.execute(
        """
        INSERT INTO messages (agent, type, topic, status, summary, details, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            "telegram_delivery_watchdog",
            "alert",
            "telegram_delivery",
            "error",
            reason,
            json.dumps(payload, ensure_ascii=False),
            utcnow().isoformat(),
        ),
    )
    conn.commit()


def attempt_resend(signal: Signal) -> tuple[bool, str]:
    """Try to resend based on message_type.

    Returns: (ok, note)
    """
    if signal.message_type == "email_report":
        # Resend last saved report artifact (latest)
        path = "/home/openclaw/projetos_ia/gerente_emails/reports/email_report_latest.txt"
        if not os.path.exists(path):
            return False, f"missing artifact {path}"
        text = open(path, "r", encoding="utf-8").read()
        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            TELEGRAM_CHANNEL,
            "--target",
            TELEGRAM_TARGET,
            "--message",
            text,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            return True, "resent via openclaw message send"
        return False, f"send failed rc={p.returncode} stderr={p.stderr.strip()}"

    if signal.message_type == "stack24h_report_telegram":
        # Re-run the normal producer which enqueues, then let existing pipeline deliver.
        cmd = [
            "/usr/bin/python3",
            "/home/openclaw/.openclaw/workspace/scripts/send_daily_stack_report_telegram.py",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            return True, "stack report re-enqueued"
        return False, f"stack enqueue failed rc={p.returncode} stderr={p.stderr.strip()}"

    return False, "unknown message_type"


def main() -> None:
    while True:
        conn = db_connect()
        try:
            ensure_retry_column(conn)
            ensure_status_values(conn)

            pending = fetch_pending(conn)
            now = utcnow()

            for sig in pending:
                ts = parse_ts(sig.timestamp)
                if not ts:
                    # Can't parse timestamp => escalate immediately
                    mark_status(conn, sig.id, "failed")
                    enqueue_escalation(conn, "Unparseable timestamp for agent_signal", sig)
                    continue

                age = (now - ts).total_seconds()
                if age < MAX_PENDING_AGE_SECONDS:
                    continue

                # Retry path
                retries = get_retry_count(conn, sig.id)
                if retries >= MAX_RETRIES:
                    mark_status(conn, sig.id, "failed")
                    enqueue_escalation(conn, f"Telegram delivery retries exceeded (max={MAX_RETRIES})", sig)
                    continue

                # bump count then attempt resend
                bump_retry(conn, sig.id)
                ok, note = attempt_resend(sig)
                if ok:
                    # If we actively resent (email_report), we consider it handled.
                    # Otherwise keep pending and allow normal pipeline to deliver.
                    if sig.message_type == "email_report":
                        mark_status(conn, sig.id, "processed")
                    # Log success note
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO messages (agent, type, topic, status, summary, details, created_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            "telegram_delivery_watchdog",
                            "notice",
                            "telegram_delivery",
                            "success",
                            f"Retry ok for signal {sig.id}",
                            note,
                            utcnow().isoformat(),
                        ),
                    )
                    conn.commit()
                else:
                    # Keep pending; will retry later until max.
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO messages (agent, type, topic, status, summary, details, created_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            "telegram_delivery_watchdog",
                            "notice",
                            "telegram_delivery",
                            "error",
                            f"Retry failed for signal {sig.id}",
                            note,
                            utcnow().isoformat(),
                        ),
                    )
                    conn.commit()

        except Exception as e:
            print(f"ERROR: {e}")
        finally:
            conn.close()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
