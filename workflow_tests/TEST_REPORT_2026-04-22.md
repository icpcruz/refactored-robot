# Teste de Workflow Multiagente (Simulado)

Data (UTC): 2026-04-22

DB: `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`
Artefatos: `/home/openclaw/projetos_ia/governança_ambiente/workflow_tests/artifacts/`
Executor: `/home/openclaw/projetos_ia/governança_ambiente/workflow_tests/simulate_workflow.py`

## Objetivo
Validar (1) fluxo linear Dev→Aud→Sys→Doc→Iarvis, (2) loop controlado Aud↔Dev, garantindo:
- (a) loops acontecem quando necessários
- (b) não entram em loop infinito (condição de parada)

## Execução 1 — Linear
Status: OK (`workflow_runs.id=1`, `status=completed`)

Tasks registradas:
- `id=1` Dev→Aud `review_artifact` (marker `L1`)
- `id=2` Aud→Sys `run_guard` (marker `L1`)
- `id=3` Sys→Doc `update_docs` (marker `L1`)
- `id=4` Doc→Iarvis `close_cycle` (marker `L1`)

## Execução 2 — Loop Controlado
Status: OK (`workflow_runs.id=2`, `status=completed`)

- Tarefa principal: `id=5` Dev→Aud `review_artifact`
- Loop simulado via `rework_round`: 0 → 1 → 2
- Condição anti-loop infinito:
  - `max_rework_rounds = 2`
  - Ao atingir o limite, a Aud aprova e o fluxo segue.

Tasks registradas (continuação do fluxo):
- `id=6` Aud→Sys `run_guard`
- `id=7` Sys→Doc `update_docs`
- `id=8` Doc→Iarvis `close_cycle`

## Evidências
- Queries executadas (exemplos):
  - `sqlite3 ... "select id, run_name, mode, status, created_at from workflow_runs"`
  - `sqlite3 ... "select id, source_agent, target_agent, action, status, rework_round, max_rework_rounds from tasks"`

## Próximo passo para virar “real”
Implementar worker de orquestração:
- poll `tasks status=pending`
- disparar agente correto via `sessions_spawn` (ACP)
- exigir artefatos e update de status
- se `rework_round > max_rework_rounds`: `failed` + escalonamento para Iarvis
