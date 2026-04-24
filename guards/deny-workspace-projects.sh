#!/usr/bin/env bash
set -euo pipefail

# Guard: detect project directories incorrectly created under OpenClaw workspace.
# Mode: ALERT ONLY (no destructive action). Produces a JSON payload suitable for
# insertion into iarvis_comms.db agent_signals by a runner.
#
# This script intentionally does NOT write to the DB directly to keep it safe;
# use a separate Python runner to emit the signal.

WORKSPACE_ROOT="/home/openclaw/.openclaw/workspace"
MAXDEPTH="2"

# Heuristics (extend cautiously):
# - explicit forbidden root
# - common project name patterns
FIND_EXPR=(
  -type d \
  \( -name 'projetos_ia' -o -name '*gerente*' -o -name '*emails*' -o -name '*email*' \)
)

matches="$({
  if [ -d "${WORKSPACE_ROOT}/projetos_ia" ]; then
    echo "${WORKSPACE_ROOT}/projetos_ia"
  fi
  find "${WORKSPACE_ROOT}" -maxdepth "${MAXDEPTH}" "${FIND_EXPR[@]}" 2>/dev/null || true
} | sort -u)"

if [ -n "$matches" ]; then
  ts_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Emit JSON to stdout for a runner to store in comms DB.
  cat <<JSON
{
  "type": "workspace_project_guard_alert",
  "severity": "warning",
  "ts_utc": "${ts_utc}",
  "workspace_root": "${WORKSPACE_ROOT}",
  "maxdepth": ${MAXDEPTH},
  "matches": $(printf '%s\n' "$matches" | python3 - <<'PY'
import json,sys
items=[l.rstrip('\n') for l in sys.stdin if l.strip()]
print(json.dumps(items, ensure_ascii=False))
PY
)
}
JSON
  exit 0
fi

# No findings
exit 0
