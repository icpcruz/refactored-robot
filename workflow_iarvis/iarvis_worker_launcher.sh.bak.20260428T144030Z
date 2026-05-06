#!/usr/bin/env bash
set -euo pipefail

# Iarvis Worker launcher
# - uses lockfile to prevent double-run
# - writes logs to governança_ambiente/workflow_logs

PROJ_ROOT="/home/openclaw/projetos_ia"
WORKDIR="$PROJ_ROOT/governança_ambiente/workflow_iarvis"
LOG_DIR="$PROJ_ROOT/governança_ambiente/workflow_logs"
LOCK_DIR="/tmp/iarvis_worker.lock"

mkdir -p "$LOG_DIR"

exec 9>"$LOCK_DIR"
if ! flock -n 9; then
  echo "[launcher] Another instance is running (lock=$LOCK_DIR). Exiting." >&2
  exit 0
fi

echo "[launcher] starting worker at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
cd "$WORKDIR"

# Unbuffered logs
exec /usr/bin/python3 -u "$WORKDIR/iarvis_worker.py" 2>&1 | tee -a "$LOG_DIR/iarvis_worker_daemon.log"
