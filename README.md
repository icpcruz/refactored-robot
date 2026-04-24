# refactored-robot — Iarvis Worker & Governance

Este repositório contém o **Iarvis Worker v1** e a base de **governança operacional** para orquestração multi-agente via SQLite.

## Componentes

- **Iarvis Worker**: `workflow_iarvis/iarvis_worker.py`
- **Contrato de finalização de tasks (obrigatório)**: `workflow_iarvis/task_tools.py`
- **Healthcheck**: `workflow_iarvis/healthcheck_worker.py`
- **Daemon (systemd user service)**: `workflow_iarvis/iarvis_worker_launcher.sh` + units em `~/.config/systemd/user/`
- **Docs / KB**: `docs/KNOWLEDGE_BASE.md`
- **Test harness**: `workflow_tests/iarvis_worker_test.py`

## DB (source of truth)

Banco de comunicação / fila:
- `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`

Tabelas principais:
- `tasks` — fila de trabalho
- `workflow_runs` — execuções/rodadas
- `agent_signals` — sinais e mensagens entre agentes
- `agent_logs` — logs do worker/agentes
- `projects` — catálogo de projetos (multi-projeto)

## Multi-projeto (isolamento)

O isolamento entre projetos é feito via coluna `project_id` nas tabelas centrais (Model A). A tabela `projects` mantém o catálogo.

Projetos seed (atual):
- `default` (Iarvis Core)
- `gerente_emails`
- `youtube_summary`
- `insta_arcaprot`
- `workflow_iarvis`

## Operação rápida

### Dry-run (teste de integridade)

```bash
/home/openclaw/projetos_ia/venv_openclaw/bin/python \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_tests/iarvis_worker_test.py
```

### Rodar worker uma vez

```bash
/home/openclaw/projetos_ia/venv_openclaw/bin/python \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --once
```

### Healthcheck manual

```bash
/home/openclaw/projetos_ia/venv_openclaw/bin/python \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/healthcheck_worker.py --stale-minutes 15
```

## Segurança

- **Nunca** commitar tokens/keys/credenciais.
- Backups/logs/snapshots sensíveis devem ficar em:
  - `/home/openclaw/projetos_ia/governança_ambiente/backups/` (700 dir / 600 files)

## Documentos (SOP)

- Ponteiro: `docs/SOP_REFERENCES.md`
- Registro de SOPs (DB): tabela `sop_registry` em `iarvis_comms.db`
