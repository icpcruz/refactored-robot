# TEST REPORT — Piloto real (gerente_emails) + Workflow (Worker v1)

Data (UTC): 2026-04-24

## Objetivo
Executar o case piloto real do **gerente_emails**, garantindo que:
- A tabela `classification_rules` exista e esteja populada no DB `email_manager.db`.
- A rotina `email_routine.py` rode sem quebrar e gere relatório.
- Um sinal `email_report` seja inserido no `iarvis_comms.db` (fallback delivery via `check_email_reports.py`).
- O worker v1 processe a cadeia do workflow (com dry-run para etapas de review/guard/doc/close_cycle).

## Guardrails / Rollback
Backups criados:
- `/home/openclaw/projetos_ia/governança_ambiente/rollback_snapshots/2026-04-24_iarvis_worker_hotfix_iarvis_comms.db.bak`
- `/home/openclaw/projetos_ia/governança_ambiente/rollback_snapshots/2026-04-24_gerente_emails_email_manager.db.bak`

## Execução — classificação (rules)
DB: `/home/openclaw/projetos_ia/gerente_emails/email_manager.db`
- `classification_rules`: criada + populada via:
  - `python3 /home/openclaw/projetos_ia/gerente_emails/src/populate_rules.py`
- Total regras: 73

## Execução — piloto real email routine
Comando:
- `/home/openclaw/projetos_ia/venv_openclaw/bin/python /home/openclaw/projetos_ia/gerente_emails/src/email_routine.py`

Resultado observado:
- Rotina completou sem crash
- Encontrou 0 e-mails novos para processar
- Gerou relatório com `__REPORT_START__/__REPORT_END__`
- Inseriu sinal em `iarvis_comms.db`:
  - `sender_agent=EmailManager`
  - `receiver_agent=Iarvis`
  - `message_type=email_report`
  - `status=pending`

## Workflow/Worker v1
Worker: `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py`

Workflow run criado:
- `workflow_runs.id = 9`
- `run_name = pilot_fix_classification_rules_2026-04-24T12:41Z`
- status final: `completed`

Tasks:
- 34 Iarvis→dev `fix_classification_rules_schema` completed
- 35 dev→Aud `review_fix` completed (dry-run)
- 36 Aud→Sys `run_smoketest` completed (dry-run)
- 37 Sys→Doc `update_docs` completed (dry-run)
- 38 Doc→Iarvis `close_cycle` completed (dry-run)

## Observações
- Os agentes isolados `dev/aud/sys/doc` foram criados no OpenClaw para permitir dispatch real futuro.
- O worker ainda está em fase de hardening; dispatch real usa `openclaw agent --agent <id>` via subprocess.
