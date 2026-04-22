[TOC]

# Iarvis Worker Protocolo v0.1

Este documento detalha o protocolo de operação para o Worker Iarvis, responsável por gerenciar o ciclo de vida das tarefas e subagentes.

## 1. Definição

O Iarvis Worker é um processo autônomo que monitora a fila de tarefas (`tasks` table em `iarvis_comms.db`) e despacha as tarefas para os agentes apropriados utilizando `sessions_spawn`. Ele também gerencia o estado das tarefas e a lógica de encadeamento ou reprocessamento.

## 2. Fluxo de Operação (Control Loop)

1.  **Poll:** Worker consulta `tasks` buscando por `status IN ('pending', 'requeued')`.
2.  **Dispatch:** Se encontrar uma tarefa:
    *   Marca a task como `in_progress` com `assigned_to_agent_id` (identificador do worker).
    *   Determina o `target_agent` e `action`.
    *   Prepara o payload, `model`, `runtime` (`acp` por padrão para persistência).
    *   Invoca `sessions_spawn` (ou API equivalente) para iniciar o subagente.
3.  **Monitor & Chain:**
    *   Worker aguarda a conclusão da tarefa (via sinal do subagente ou poll do status da task no DB).
    *   Se `status = 'completed'`:
        *   Verifica se há uma próxima etapa definida na arquitetura (ex: `next_agent` no payload do signal). Se sim, cria nova task.
        *   Se for a etapa final (`close_cycle`), marca workflow como `done`.
    *   Se `status = 'failed'` ou `reworked`:
        *   Implementa lógica de retry/rework com base em `rework_round` e `max_rework_rounds`.
        *   Se `rework_round > max_rework_rounds`, marca como `failed` e cria task de `escalation` para Iarvis (ou humano).
4.  **Backoff:** Se nenhuma tarefa pendente for encontrada, aguarda `POLL_INTERVAL` segundos antes do próximo poll.

## 3. Contrato de Tarefas (Table `tasks`)

Campos essenciais para o Worker:
- `id`: Chave primária.
- `source_agent`: Quem originou a tarefa.
- `target_agent`: Quem deve executar.
- `action`: O que fazer (ex: `fix_code`, `review_artifact`, `run_smoketest`).
- `payload_json`: Dados de entrada (ex: `{"file_path": "...", "commit": "...", "reason": "..."}`).
- `status`: ('pending', 'in_progress', 'completed', 'failed', 'requeued').
- `result_json`: Resultado da execução (artefato, logs, erro).
- `rework_round`: Contador para loops de retrabalho.
- `max_rework_rounds`: Limite de retrabalhos aceitáveis.

## 4. Contrato de Sinais (Table `agent_signals`)

Utilizado por subagentes para notificar o Worker ou outros agentes:
- `sender_agent`: Quem enviou o sinal.
- `signal_type`: Tipo de evento (ex: `artifact_ready`, `rework_requested`, `escalation_needed`).
- `task_id`: Tarefa associada.
- `payload`: Dados adicionais (ex: `'{"next_agent": "Aud", "artifact": "...", "rework_round": 1}'`).

## 5. Segurança e Rollback

- **Worker roda como usuário `openclaw`:** Não necessita de `elevated=true` por padrão.
- **Atomicidade:** Operações no DB são transacionais.
- **Rollback:** Em caso de falha crítica do Worker, o estado das tasks (`pending`, `requeued`) permite reinício sem perda de trabalho. Scripts de rollback (git, snapshots) configurados pelo Iarvis.

## 6. Conhecimento Adquirido

- **A lição "você só garante aquilo que verifica" é implementada pelo Worker:** Ele força o ciclo de feedback, o que valida a qualidade do trabalho.
- **Loops controlados são essenciais:** O `max_rework_rounds` previne loops infinitos e força escalonamento.
- **DB como Source of Truth:** A centralização em `iarvis_comms.db` garante rastreabilidade e estado consistente.

---
*Este documento será atualizado conforme o Worker evoluir.*
 Meade Meade /home/openclaw/projetos_ia/governança_ambiente/docs/KNOWLEDGE_BASE.md