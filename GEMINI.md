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
- **Foco Exclusivo de Canais (`Gamestore` + `@promosgeektech`):**
  - Manter **X (Twitter)** e **Threads** rigorosamente desativados por padrão (`X_ENABLED=false` e `THREADS_ENABLED=false` no código e no workflow) por serem contas pessoais; jamais disparar chamadas HTTP nesses canais sem ativação explícita.
  - Toda distribuição social concentra-se na **Página do Facebook `Gamestore`** + **Telegram `@promosgeektech`** (+ E-mail diário de ofertas).
- **Página do Facebook (`Gamestore`) — Alcance & Nicho:**
  - Publicar **Top 5 no Feed** (foto JPEG limpa **sem URL** + link de afiliado automático no **1º comentário**), **1 Reel MP4** e **2 Stories 9:16** por execução (100% gratuito).
  - Sempre validar/converter `FACEBOOK_PAGE_TOKEN` via `/v21.0/me/accounts` para evitar erro `403 publish_actions is deprecated` caso o secret seja um User Token.
  - Manter `_bonus_nicho_gamestore` ativo para priorizar **Games, Hardware Gamer e Áudio** nos Reels, Stories e Feed da `Gamestore`, penalizando itens de casa (*fechadura, cadeado, vitrola*).
- **Reels Animados, Safe Zones & Stories 9:16 (`media_generator.py` — Custo R$ 0):**
  - Usar **HeyGen HyperFrames** (HTML/GSAP 1080×1920) como motor principal e **Pillow + `ffmpeg`** como fallback automático.
  - **Invariante HyperFrames:** aplicar `class="clip"` apenas no container raiz `#stage` (nunca em filhos flex individuais), evitando sobreposição por `position: absolute`.
  - **Safe Zone Reels 9:16:** manter livres **`224px` no topo**, **`164px` na lateral direita** e **`540px` (~28%) na base** (HTML `#stage` e fallback Pillow `modo="reel"`), ajustando `#scrim` e tipografia para que avatar, legenda e botões não cubram a manchete ou o rodapé.
  - **Safe Zone Stories 9:16:** manter `y_top=224` e `footer_bottom_margin=310` livres em cards estáticos `1080×1920` (sem narração).
  - Usar a voz **`pt-BR-ThalitaMultilingualNeural`** (`edge-tts`) e ajustar a duração do MP4 dinamicamente via `ffprobe` (`duração + 0,8s`) para nunca cortar a fala.
- **Radar de Preços 180d, Blindagem Gemini & Dashboard Offline:**
  - Consultar `obter_estatisticas_sku(..., dias=180)` **antes** de gravar os preços da rodada (`excluir_data=hoje`), usando `mediana_180d` como referência e só ativando `menor_preco_historico = True` quando `dias_observados >= 5` **e** `preco_atual < min_180d`.
  - Não enviar nem exigir `url_afiliado`/`imagem_url` no JSON da IA (re-hidratar pelo `sku_selecionado` em `enriquecer_oportunidades_com_radar`), proibir menção a mínima histórica quando `menor_preco_historico` for `false`, e manter `parsear_resposta_gemini` com recuperação parcial + fallback/top-up determinístico (`15 ML + 5 Magalu`).
  - Persistir apenas `historico_metricas.json` no `actions/cache@v4` (além do SQLite via Releases) e manter `dashboard_generator.py` 100% stdlib (`urllib.request`).
- **Motor Editorial RSS (`rss_editorial.py`) & Testes Locais:**
  - Rodar o bloco editorial 1x/dia na janela das `15h BRT` (`14h–16h59` em `America/Sao_Paulo`, ou via `--run-editorial` / `--editorial-only`) dentro de `try/except` 100% isolado — inclusive quando os scrapers de ofertas retornarem 0 itens ou sofrerem bloqueio WAF (logado via `_diagnosticar_bloqueio_http`).
  - Deduplicar por URL e similaridade temática em `pautas_rss` (7 dias), usar seleção por inteiro curto `noticia_id` (`1..30`, sem ecoar URLs longas), `max_output_tokens=4096` (`application/json`), logs diagnósticos (`finish_reason`, motivo e snippet), **1 retry automático**, fallbacks por campo (se `roteiro_reel` faltar, pular só o Reel) e regras anti-IA apenas no prompt (nunca rejeitar toda a pauta por palavra).
  - Publicar os 3 formatos de forma independente: **Card 4:5 sem narração** no Feed `Gamestore` (zero URLs no corpo; link de oferta só no 1º comentário quando houver match) + Telegram (`EDITORIAL_TELEGRAM_ENABLED=true`), **Story 9:16 sem narração** em `story_editorial.jpg` via `photo_stories` (`EDITORIAL_STORY_ENABLED=true`) e **Reel 9:16 HyperFrames + Thalita** (`EDITORIAL_REEL_ENABLED=true`).
  - Manter importações pesadas opcionais (`pandas`, `bs4`, `google.generativeai`, `tweepy`, `feedparser`) no topo dos módulos para que `python -m unittest discover -s tests -v` execute localmente no Windows sem exigir pacotes fora do ambiente padrão.
