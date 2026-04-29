import os
import sys

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workflow_iarvis import iarvis_worker as worker


def test_should_trigger_stalemate_false():
    task = {'status': 'in_progress', 'heartbeat_count': 9}
    assert worker.should_trigger_stalemate(task) is False


def test_should_trigger_stalemate_true():
    task = {'status': 'in_progress', 'heartbeat_count': 10}
    assert worker.should_trigger_stalemate(task) is True


def test_maybe_trigger_intervention_calls(monkeypatch):
    called = {}
    def fake_add_signal(sender_agent, signal_type, task_id, payload):
        called['signal_type'] = signal_type
        called['task_id'] = task_id
        called['payload'] = payload
    monkeypatch.setattr(worker, 'add_signal', fake_add_signal)
    task = {'id': 123, 'status': 'in_progress', 'heartbeat_count': 12}
    worker.maybe_trigger_intervention(task)
    assert called.get('signal_type') == 'escalation_needed'
    assert called.get('task_id') == 123
    assert 'heartbeat_count' in called.get('payload', {})
