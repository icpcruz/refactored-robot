Iarvis Worker v1 — Governance (auto-generated README)

Este README acompanha a consolidação de governança para o Iarvis Worker, incluindo suporte a multi-project via project_id, inventário de SOPs, pointers de memória, e patches para auditoria.

Arquivos principais:
- workflow_iarvis/iarvis_worker.py
- workflow_iarvis/task_tools.py
- workflow_iarvis/healthcheck_worker.py
- workflow_iarvis/iarvis_worker_launcher.sh
- docs/sop_registry/SOP_INVENTORY_*.md/.csv
- docs/SOP_REFERENCES.md
- memory/pointers/SOP_REFERENCES.md
- MEMORY.md (anchors de SOP)

Como rodar rapidamente:
- Dry-run: /home/openclaw/projetos_ia/venv_openclaw/bin/python3 /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --dry-run
- Um ciclo completo (single project, default): /home/openclaw/projetos_ia/venv_openclaw/bin/python3 /home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py --once

Observação de governança:
- Backups sensíveis são mantidos em /home/openclaw/projetos_ia/governança_ambiente/backups com permissão 700/600.
- ## Diretriz de Orquestração (Maestro)

As tarefas escaladas pelo Watchdog são de responsabilidade do **Iarvis**. O Iarvis deve:
1. Analisar a falha no banco de dados.
2. Identificar o agente ideal para correção (`Sys` para infra, `Dev` para bugs, `Aud` para qualidade).
3. Criar uma nova tarefa de correção/remedy.
4. Monitorar até o fechamento do ciclo.
O Iarvis gerencia o débito técnico sistemicamente.

