cron_jobs - Ingestão de Relatórios Cron em Tasks (cron_jobs) - Dry-run

Objetivo
- Fornecer um ambiente de dry-run para ingestão de relatórios_cron transformando-os em tasks, sem afetar o DB de produção.
- Capacidade de validar estrutura de ingestão, artefatos de auditoria e fluxo de aprovação (Dev → Aud → Doc → Iarvis).

Estrutura
- sample_report.txt  (exemplo de relatório cron)
- dry_run_example.py (exemplo de disparo de ingestão em modo dry-run)
- README.md (este arquivo)

Como usar
- Preencha sample_report.txt com conteúdo de teste (linhas começando com '-' ou contendo ERROR/Exception).
- Execute dry_run_example.py para simular ingestão.
- Verifique a pasta cron-jobs-tests para os artifacts gerados (dry-run JSON).
