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
- **Persistência SQLite & Anti-Repetição (`storage_db.py`):**
  - Persistir `historico_precos`, `historico_postados` (trava 72h com fallback se `< 25` inéditos), `pautas_rss` e `metadados_sync` em `alpha_profit.db` usando `PRAGMA journal_mode=DELETE;` (sem `-wal`/`-shm`) e fechamento limpo antes do `gzip`.
  - No GitHub Actions, restaurar/publicar `alpha_profit.db.gz` via GitHub Releases (`DATA_REPO_OWNER_NAME` + `DATA_REPO_TOKEN`, tag `db-latest`, snapshot semanal idempotente aos domingos `backup-YYYY-Www` e artifact 30d), validando `PRAGMA integrity_check == 'ok'` e queda máxima tolerada antes do upload.
  - Nunca versionar `*.db`, `*.db.gz`, `*.db-wal` ou `*.db-shm` (manter no `.gitignore`).
- **X (Twitter) — Modo Econômico (Pay-Per-Use):**
  - Nunca incluir URLs ou domínios (nem `t.me/...`) no texto dos tweets, pois o X cobra **US$ 0,20/post** por links contra **US$ 0,015/post** sem links.
  - Manter o limite padrão de **Top 2 ofertas por execução** (6/dia) com foto JPEG e chamada para `@promosgeektech (link na bio!)`.
- **Threads (Meta) — Publicação Gratuita:**
  - Publicar **Top 5 ofertas por execução** (15/dia) com link direto de afiliado (API gratuita, sem taxa de link).
  - Descobrir `THREADS_USER_ID` automaticamente via `GET https://graph.threads.net/v1.0/me` usando apenas `THREADS_ACCESS_TOKEN`.
  - Usar `media_type=IMAGE` apenas para URLs `.jpg`/`.jpeg`/`.png`; fazer fallback automático para `media_type=TEXT` + `link_attachment` quando a imagem for `.webp` ou falhar.
- **Página do Facebook (`Gamestore`) — Alcance & Nicho:**
  - Publicar **Top 5 no Feed** (foto JPEG limpa **sem URL** + link de afiliado automático no **1º comentário**), **1 Reel MP4** e **2 Stories 9:16** por execução (100% gratuito).
  - Sempre validar/converter `FACEBOOK_PAGE_TOKEN` via `/v21.0/me/accounts` para evitar erro `403 publish_actions is deprecated` caso o secret seja um User Token.
  - Manter `_bonus_nicho_gamestore` ativo para priorizar **Games, Hardware Gamer e Áudio** nos Reels, Stories e Feed da `Gamestore`, penalizando itens de casa (*fechadura, cadeado, vitrola*).
- **Reels Animados (HyperFrames + `edge-tts` — Custo R$ 0):**
  - Usar **HeyGen HyperFrames** (HTML/GSAP 1080×1920) como motor principal e **Pillow + `ffmpeg`** como fallback automático.
  - **Invariante HyperFrames:** aplicar `class="clip"` apenas no container raiz `#stage` (nunca em filhos flex individuais), evitando sobreposição por `position: absolute`.
  - Usar a voz **`pt-BR-ThalitaMultilingualNeural`** (`edge-tts`) e ajustar a duração do MP4 dinamicamente via `ffprobe` (`duração + 0,8s`) para nunca cortar a fala.
- **Radar de Preços 180d, Blindagem Gemini & Dashboard Offline:**
  - Consultar `obter_estatisticas_sku(..., dias=180)` **antes** de gravar os preços da rodada (`excluir_data=hoje`), usando `mediana_180d` como referência e só ativando `menor_preco_historico = True` quando `dias_observados >= 5` **e** `preco_atual < min_180d`.
  - Não enviar nem exigir `url_afiliado`/`imagem_url` no JSON da IA (re-hidratar pelo `sku_selecionado` em `enriquecer_oportunidades_com_radar`), proibir menção a mínima histórica quando `menor_preco_historico` for `false`, e manter `parsear_resposta_gemini` com recuperação parcial + fallback/top-up determinístico (`15 ML + 5 Magalu`).
  - Persistir apenas `historico_metricas.json` no `actions/cache@v4` (além do SQLite via Releases) e manter `dashboard_generator.py` 100% stdlib (`urllib.request`).
- **Motor Editorial RSS (`rss_editorial.py`) & Testes Locais:**
  - Rodar o bloco editorial 1x/dia na janela das `15h BRT` (`14h–16h59` em `America/Sao_Paulo`, ou via `--run-editorial`) dentro de `try/except` 100% isolado, deduplicado em `pautas_rss` (7 dias), com crédito `"Via [Fonte]"`, **zero URLs no X e no corpo do Facebook** (`EDITORIAL_TELEGRAM_ENABLED=false` por padrão).
  - Manter importações pesadas opcionais (`pandas`, `bs4`, `google.generativeai`, `tweepy`, `feedparser`) no topo dos módulos para que `python -m unittest discover -s tests -v` execute localmente no Windows sem exigir pacotes fora do ambiente padrão.
