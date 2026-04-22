# Workflow Iarvis (governança)

## O que é
Worker de orquestração baseado em fila de tarefas (SQLite) + infra_map.

## Arquivos
- `iarvis_worker.py` — Worker v1 (modo simulado)

## DB
- Source of truth: `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`
- Tabelas usadas/criadas:
  - `tasks`
  - `workflow_runs`
  - `agent_signals` (já existente no DB)

## Dry-run (regra de ouro)
Executa um fluxo linear simulado e valida chaining até `close_cycle`:

```bash
python3 /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --dry-run
```

## Lint (pylint >= 8)

```bash
/home/openclaw/projetos_ia/venv_py311_lint/bin/python -m pylint \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py \
  --fail-under=8
```
