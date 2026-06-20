[TOC]

# Iarvis Worker Protocolo v0.2 (2026-04-24)

Este documento detalha o protocolo de operação para o Worker Iarvis, responsável por gerenciar o ciclo de vida das tarefas e subagentes.

Mudanças relevantes (2026-04-24):
- `task_tools.py` virou o **contrato obrigatório** de finalização de tasks (complete/fail/requeue) + emissão de signals.
- Worker passou a usar **claim atômico** de task para evitar double-consume.
- Dispatch real via `openclaw agent --agent <id>` (não depende de import Python `openclaw`).
- Execução contínua em **systemd user service** + healthcheck via timer.

## 1. Definição

O Iarvis Worker é um processo autônomo que monitora a fila de tarefas (`tasks` table em `iarvis_comms.db`) e despacha as tarefas para os agentes apropriados.

Implementação atual:
- Worker: `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker.py`
- Task tools (obrigatório): `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/task_tools.py`
- DB source-of-truth: `/home/openclaw/projetos_ia/comms_manager/iarvis_comms.db`
- Infra map: `/home/openclaw/projetos_ia/governança_ambiente/infra_map.json`

O Worker gerencia estado, chaining e rework/escalation driven-by-DB (nada fica só “na memória do processo”).

## 2. Fluxo de Operação (Control Loop)

### 2.1 Claim atômico
Para evitar dois workers pegarem a mesma task:
- O worker faz `UPDATE tasks SET status='in_progress', assigned_to_agent_id=? WHERE id=? AND status IN ('pending','requeued')`.
- Se `rowcount != 1`, ele ignora a task e segue.

1.  **Poll:** Worker consulta `tasks` buscando por `status IN ('pending', 'requeued')`.
2.  **Dispatch:** Se encontrar uma tarefa:
    *   Claim atômico → marca `in_progress` + `assigned_to_agent_id`.
    *   Determina `target_agent` + `action`.
    *   Constrói prompt com o **contrato obrigatório** de finalização via `task_tools.py`.
    *   Dispara agente via Gateway CLI:
        - `openclaw agent --agent <agent_id> --message <prompt>`
    *   Logs do dispatch ficam em: `/home/openclaw/projetos_ia/governança_ambiente/workflow_logs/`
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

Utilizado por subagentes para notificar o Worker ou outros agentes.

Tabela (atual): `agent_signals(sender_agent, receiver_agent, message_type, payload_json, status, timestamp)`

Signals relevantes para o workflow:
- `task_completed` (receiver=`iarvis_worker`)
- `task_failed` (receiver=`iarvis_worker`)
- `rework_requested` (receiver=`iarvis_worker`)
- `escalation_needed` (receiver=`Iarvis` ou `iarvis_worker` dependendo do fluxo)
- `worker_health_alert` (receiver=`Iarvis`)
- `cycle_completed` (receiver=`iarvis_worker`)

Observação: o `task_tools.py` é o caminho padrão para atualizar task + gravar signal com payload_json consistente.

## 5. Produção contínua (daemon) + Healthcheck

## 5.4 Contrato obrigatório de finalização (task_tools)

O agente **deve** finalizar cada task via:
- `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/task_tools.py`

Exemplos:
- SUCCESS:
  - `python3 task_tools.py complete --sender dev --task-id 123 --result-json '{"ok":true,"notes":"...","artifacts":{}}'`
- FAIL:
  - `python3 task_tools.py fail --sender sys --task-id 123 --result-json '{"ok":false,"error":"..."}'`
- REWORK:
  - `python3 task_tools.py requeue --sender aud --task-id 123 --result-json '{"ok":false,"notes":"requer ajustes"}'`

Sem isso, o worker não consegue encadear e a fila trava.


### 5.1 systemd (user)
Serviços instalados:
- `~/.config/systemd/user/iarvis-worker.service`
- `~/.config/systemd/user/iarvis-worker-healthcheck.service`
- `~/.config/systemd/user/iarvis-worker-healthcheck.timer`

Comandos:
- `systemctl --user status iarvis-worker.service`
- `systemctl --user restart iarvis-worker.service`
- `systemctl --user status iarvis-worker-healthcheck.timer`

### 5.2 Launcher com lockfile
- `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/iarvis_worker_launcher.sh`
- Lock: `/tmp/iarvis_worker.lock`

### 5.3 Healthcheck
- Script: `/home/openclaw/projetos_ia/governança_ambiente/workflow_iarvis/healthcheck_worker.py`
- Frequência: 5 min (timer)
- Se detectar tasks pendentes acima do limite ou logs stale, grava `agent_signals.message_type='worker_health_alert'` com `status=pending`.

## 6. Segurança e Rollback

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
## 7. Lições Aprendidas: O "Script Python Perfeito" (Pylint 8.0+)

Para garantir manutenibilidade e nota alta em auditorias automáticas, todo novo script deve seguir estes padrões antes da primeira submissão:

1.  **Docstrings:** Obrigatório no topo do módulo, classes e todas as funções públicas/privadas.
2.  **Context Managers:** Usar `with open(...)` ou `with db_conn()` para todo recurso alocável.
3.  **Tratamento de Erros:** Proibido `except Exception:`. Usar exceções específicas (ex: `FileNotFoundError`, `sqlite3.Error`).
4.  **Subprocess:** Sempre usar `check=True` para disparar erros em falhas externas e capturar stdout/stderr.
5.  **Clean Code:**
    - Nomes de variáveis em `snake_case` (mínimo 3 caracteres, evitar `e`, `ts`, `df`).
    - Limite de 100 caracteres por linha.
    - Máximo de 15 variáveis locais por função e 12 ramos de decisão (`if/elif`).
6.  **Tooling:** Rodar `./lint_and_format.sh` antes de qualquer `git commit`.

*Ref: Auditoria Noturna 2026-05-06*
