# SOP — OAuth Google separado para Gmail e rclone

Atualizada em 2026-07-11.

## Arquitetura

- Gmail usa o projeto `gerente-emails-pessoal`, o escopo `gmail.modify` e os arquivos
  `gmail_client_secrets.json` e `gmail_token.json`.
- O rclone usa o projeto `backup-vps-drive-pessoal`, o escopo `drive` e os arquivos
  `rclone/client_secrets.json` e `rclone/rclone_token.json`.
- Os dois grants são independentes. Revogar um não deve interromper o outro.
- Todos os arquivos ficam em `/home/openclaw/.secrets/google/`, com modo `0600`, e
  nunca entram no backup do Google Drive.

## Renovação normal

Não existe renovação semanal. Gmail e rclone renovam seus access tokens usando os
respectivos refresh tokens. Intervenção humana só é necessária após revogação do
grant, exclusão do cliente OAuth, mudança incompatível de escopo ou `invalid_grant`.

## Health checks

- Gmail: `gerente_emails/src/oauth_healthcheck.py` diariamente via systemd user timer.
- rclone: `validate_rclone_remote_v2.sh --yes --skip-about` confirma autenticação e
  listagem sem iniciar um backup.

## Reautorizar o rclone

No Windows, execute `scripts/rclone_oauth_authorizer.py` com o JSON do cliente do
projeto de backup. O script solicita exclusivamente `https://www.googleapis.com/auth/drive`
e grava `rclone_token.json` atomicamente.

Envie os dois arquivos para `/home/openclaw/.secrets/google/rclone/` e aplique:

```bash
/home/openclaw/apply_rclone_token_atomic_v2.sh --yes \
  --secrets-dir /home/openclaw/.secrets/google/rclone
/home/openclaw/validate_rclone_remote_v2.sh --yes --run-backup --notify-sys
```

O primeiro comando preserva uma cópia datada de `rclone.conf`. Não remova a cópia
anterior antes de a listagem, a quota e um backup real terminarem com sucesso.

## Resposta a falhas

1. `invalid_grant`: verificar se o grant ou o cliente foi revogado; reautorizar.
2. Falha de rede ou quota: preservar o token e repetir apenas a validação.
3. Falha após aplicação: restaurar o último `rclone.conf.bak.*` e investigar antes
   de gerar outro token.
4. Nunca reutilizar o cliente ou token do Gmail no rclone.
