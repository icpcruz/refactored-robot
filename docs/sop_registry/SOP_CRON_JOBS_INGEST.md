# SOP: Cron Jobs — Ingestão de relatórios_cron → tasks (cron_jobs)

## 1) Objetivo
Evitar que relatórios gerados por crons ("relatórios_cron") fiquem órfãos.

Este SOP define o fluxo padrão para:
- armazenar relatórios_cron em pasta padrão
- ingerir relatórios_cron no `iarvis_comms.db` como `tasks` + `agent_signals`
- garantir que o `iarvis_worker` processe no próximo heartbeat

## 2) Fonte da verdade (paths)
- Repo governança (código):
  - `/home/openclaw/projetos_ia/governança_ambiente/cron-jobs/`
- Dry-run harness + artefatos de validação:
  - `/home/openclaw/projetos_ia/governança_ambiente/cron-jobs-tests/`
- DB inter-agentes (source of truth):
  - `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`

## 3) Pasta padrão de relatórios_cron
Padrão proposto (estável e sem acento para compatibilidade com tools/cron):
- `/home/openclaw/projetos_ia/governança_ambiente/reports/relatorios_cron/`

Convenções:
- `latest.txt` → o último relatório consolidado do dia (se houver)
- `YYYY-MM-DD_*.txt` → históricos do dia (opcional)

## 4) Ingestão (script)
Script oficial:
- `/home/openclaw/projetos_ia/governança_ambiente/cron-jobs/cron_ingest_code_audit.py`

Modo dry-run (não toca DB; gera artefato JSON):
- `python3 cron_ingest_code_audit.py --report <path> --project cron_jobs --dry-run`

Modo produção (cria tasks + emite signal para `iarvis_worker`):
- `python3 cron_ingest_code_audit.py --report <path> --project cron_jobs`

O script:
- sempre grava um artefato `ingest_*.json` em `cron-jobs-tests/` (ou `--artifacts-root`)
- cria tasks em `tasks(project_id='cron_jobs')`
- emite signal em `agent_signals(project_id='cron_jobs', receiver_agent='iarvis_worker')`

## 5) Cron de ingestão (fallback padrão)
Política:
- Execução diária às **02:15** no TZ **America/Sao_Paulo** (evita conflitos comuns das 02:00).

Cron job cadastrado no Gateway:
- Nome: `Iarvis - Ingest relatorios_cron -> cron_jobs`
- Schedule: `15 2 * * *` (America/Sao_Paulo)

## 6) Governança (ciclo Dev → Aud → Sys → Doc → Iarvis)
- Dev: implementa, roda dry-run e salva artefatos em `cron-jobs-tests/`
- Aud: revisa artefatos + conformidade (schema, idempotência, qualidade)
- Sys: entra apenas se houver risco (segredos, permissões, rede, hardening)
- Doc: revisa custo/clareza/operabilidade e atualiza documentação
- Iarvis: aprova e fecha o ciclo

## 7) Retenção / limpeza
- `cron-jobs-tests/`: manter enxuto (artefatos de dry-run são perecíveis). Recomenda-se retenção <= 24h para artefatos não-auditáveis.
- Auditorias detalhadas (RCA / lições aprendidas / KB): arquivar em `docs/` ou `reports/` conforme política ISO/qualidade.

---
Atualize este SOP quando mudar:
- a pasta padrão de relatórios
- o horário do cron
- o schema/contratos do DB (tasks/signals)
