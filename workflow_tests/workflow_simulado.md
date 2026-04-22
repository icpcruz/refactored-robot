# Workflow Simulado — Dev → Aud → Sys → Doc → Iarvis

Objetivo: validar handoffs e ciclos (linear e com loop) via `iarvis_comms.db`.

## Execução 1 (Linear)
- [ ] Dev: cria artefato inicial + sinaliza Aud
- [ ] Aud: revisa + sinaliza Sys
- [ ] Sys: executa verificação/guard + sinaliza Doc
- [ ] Doc: atualiza doc simulada + sinaliza Iarvis
- [ ] Iarvis: fecha ciclo (marca DONE)

## Execução 2 (Com loop controlado)
- [ ] Dev: cria artefato inicial + sinaliza Aud
- [ ] Aud: encontra pendência (1) e devolve para Dev
- [ ] Dev: corrige e devolve para Aud
- [ ] Aud: aprova e segue para Sys
- [ ] Sys → Doc → Iarvis: igual ao linear

## Condição de parada (anti-loop infinito)
- `max_rework_rounds = 2`
- Aud só pode reabrir até 2x; na 3ª, deve escalar para Iarvis.
