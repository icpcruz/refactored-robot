import json
import os
import sqlite3
import logging

TOKEN_STATUS_PATH = '/home/openclaw/.openclaw/workspace/memory/oauth_status.json'
COMMS_DB_PATH = '/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db'
AGENT_NAME = 'EmailManagerGuard'

logger = logging.getLogger(__name__)


def load_oauth_guard_status():
    try:
        with open(TOKEN_STATUS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load OAuth guard status from %s", TOKEN_STATUS_PATH)
        return {"status": "active", "requires_manual_reauth": False}


def is_reauth_required():
    s = load_oauth_guard_status()
    return bool(s.get('requires_manual_reauth', False))


def signal_requires_reauth(reason="OAuth token invalid or expired"):
    try:
        conn = sqlite3.connect(COMMS_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            '''INSERT INTO agent_signals (sender_agent, receiver_agent, message_type, payload_json, status)
               VALUES (?, ?, ?, ?, ?)''',
            (AGENT_NAME, 'Iarvis', 'requires_email_manager_reauth', json.dumps({'reason': reason}), 'pending')
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Failed to signal reauth requirement to comms DB")
        # Silently degrade — the guard should not crash the email flow
