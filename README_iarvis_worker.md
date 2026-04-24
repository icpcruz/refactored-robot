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
- SOPs são registrados em SOP Registry (DB) e inventariados em SOP_INVENTORY.*.
