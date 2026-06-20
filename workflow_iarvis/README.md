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

## Papel do Iarvis: Maestro e SCRUM Master

- **Identidade:** Iarvis atua como orquestrador, Maestro e SCRUM Master do Squad de agentes.
- **Não Executor:** O Iarvis não executa tarefas técnicas (como edição de código) diretamente em workflows de produção; ele toma decisões e delega via `tasks` para agentes especializados (`Dev`, `Aud`, `Sys`, etc.).
- **Escalonamento:** O Watchdog escalona tarefas presas ou com falha para o **Iarvis**. Cabe ao Iarvis analisar a causa no DB, gerenciar o débito técnico e criar novas tarefas de correção/investigação para os subagentes.
- **Responsabilidade:** Iarvis é o último elo do workflow, certificando o resultado antes da entrega final ao Ivan.


```bash
python3 /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --dry-run
```

## Lint (pylint >= 8)

```bash
/home/openclaw/projetos_ia/venv_py311_lint/bin/python -m pylint \
  /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py \
  --fail-under=8
```
