# Diretrizes de Desenvolvimento e Workflow - Antigravity

## 1. Controle de Versão (Git & GitHub)
- **Regra de Push:** O usuário **SEMPRE** realiza o `git push` manualmente direto pelo seu próprio terminal / CMD do Windows.
- O agente **NÃO DEVE** tentar rodar `git push` automaticamente nem solicitar autorização para disparar push contra o repositório remoto.
- **Workflow Padrão do Agente:**
  1. Criar e editar os arquivos necessários.
  2. Adicionar as alterações (`git add ...`).
  3. Realizar o commit local com mensagens claras e semânticas (`git commit -m "tipo: mensagem"`).
  4. Informar ao usuário que as alterações foram commitadas localmente e fornecer o comando `git push origin main` para que ele execute no seu próprio terminal / CMD.

## 2. Regras Técnicas do Bot de Afiliados (`bot_afiliados_magalu`)
- **Proporção e Agenda:** 20 ofertas por execução (**15 Mercado Livre + 5 Magalu**), disparadas 3x ao dia no GitHub Actions (`10h`, `15h` e `20h` BRT / `13:00`, `18:00` e `23:00` UTC).
- **Rastreamento Mercado Livre:** Toda URL de produto do Mercado Livre deve conter `matt_tool=61727000` e `matt_word=rafaelmelo825`.
- **Imagens do Mercado Livre no Telegram:**
  - Nunca usar `img.get("src")` cegamente: ignorar placeholders `data:image/...` (priorizar `data-src` / `data-srcset` / `srcset` em `img.poly-component__picture`).
  - Nunca renomear `.webp` para `.jpg` na URL (`mlstatic.com` retorna 404). Baixar os bytes originais e converter para **JPEG real em memória via Pillow** antes do upload multipart para `sendPhoto`.
- **Anti-Repetição:** Manter `historico_postados.json` (janela de 72h) persistido via `actions/cache@v4` no GitHub Actions e listado no `.gitignore`.
