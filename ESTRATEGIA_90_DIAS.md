# 🎯 Estratégia Técnica e de Crescimento — 90 Dias (`Gamestore` + `@promosgeektech`)

> **Escopo definido:** Operação 100% automatizável em **Facebook (`Gamestore`) + Instagram (`Gamestore`) + Telegram (`@promosgeektech`)**, com expansão de catálogo para **Amazon Brasil** no Mês 2.  
> **Regra rígida de escopo:** **WhatsApp fora dos próximos 6 meses** (mantido exclusivamente para o roadmap do **Mês 7+**). **X (Twitter)** e **Threads** permanecem desligados (`X_ENABLED=false`, `THREADS_ENABLED=false`). **Custo de infraestrutura alvo: R\$ 0/mês.**

---

## 1. Arquitetura Real Atual (Baseline Técnica)

Todo este plano parte da stack já operando em produção no repositório:
- **Orquestração & Agendamento (`alpha-profit-bot.yml`):** 3 disparos diários às **10h, 15h e 20h BRT** acionados externamente via **`cron-job.org` → GitHub API `workflow_dispatch`** (o bloco `schedule:` nativo fica comentado para evitar atrasos da fila do GitHub e disparos duplicados).
- **Persistência SQLite 180d (`storage_db.py`):** banco `alpha_profit.db` (`PRAGMA journal_mode=DELETE;`) versionado via **GitHub Releases** em repositório privado (`db-latest` + backup semanal aos domingos + Artifact 30d), com **mediana de 180 dias**, **warm-up `>= 5` dias** e trava anti-repetição de **72h**.
- **Motor de Ofertas (`magalu_scrapper.py`):** minera **Mercado Livre** (`ML_`, tag `matt_tool=61727000` / `matt_word=rafaelmelo825`) e **Magalu** (`MAGALU_`), seleciona 20 oportunidades por rodada com fallback determinístico e envia E-mail + CSV + Telegram + Facebook.
- **Motor Editorial RSS (`rss_editorial.py`):** 1x/dia na janela das **15h BRT** (desacoplado de eventuais bloqueios WAF nas lojas), seleção por `noticia_id` com retry automático, copy humanizada anti-IA e 3 formatos independentes (**Card 4:5**, **Story 9:16** sem narração e **Reel 9:16**).
- **Fábrica Visual 9:16 & 4:5 (`media_generator.py`):** **HeyGen HyperFrames** + voz **`pt-BR-ThalitaMultilingualNeural`** (`edge-tts`) + fallback **Pillow + `ffmpeg`**, respeitando Safe Zones de Reels (`224px` topo, `164px` direita, `540px` base) e Stories (`224px` topo, `310px` base).
- **Telemetria (`dashboard_generator.py`):** Dashboard HTML offline com Aba 1 automática (Telegram + Facebook Insights) e Aba 2 manual (cliques, vendas e comissões no `localStorage`).

---

## 2. North Star Metric & OKRs (30, 60 e 90 Dias)

### North Star Metric (NSM)
**Vendas Afiliadas Confirmadas / Semana** (rastreadas na Aba 2 do `dashboard_acompanhamento.html` + painéis ML, Magalu e Amazon Associados), sustentadas por **Cliques Qualificados no 1º Comentário / Telegram / Link na Bio** e **Alcance Orgânico de Reels**.

### Baseline Atual (Dia 0)
- **Facebook `Gamestore`:** 22 seguidores.
- **Instagram `Gamestore`:** conta a criar/vincular no Mês 1 (`0` seguidores).
- **Telegram `@promosgeektech`:** canal ativo, ~1–5 membros iniciais.
- **Lojas ativas:** Mercado Livre + Magalu (`15 ML + 5 Magalu`).
- **Cadência calibrada na Semana 1:** 3 ofertas no Feed FB/rodada + 10 ofertas no Telegram/rodada + 4 Reels/dia + 7 Stories/dia + 1 Editorial RSS às 15h BRT.

### OKRs por Marco

| Horizonte | Seguidores & Comunidade | Retenção & Engajamento (Reels/Cards) | Cliques Qualificados & Receita (Aba 2) |
| :--- | :--- | :--- | :--- |
| **30 Dias (Mês 1)** | FB `Gamestore`: **>= 120** seguidores<br/>IG `Gamestore`: **>= 150** seguidores<br/>TG `@promosgeektech`: **>= 40** membros | **>= 25%** retenção média nos primeiros 3s dos Reels; **>= 1,5%** engajamento nos Cards 4:5 | **>= 150** cliques/semana no Link na Bio + Telegram; **>= 5** vendas confirmadas no mês |
| **60 Dias (Mês 2)** | FB `Gamestore`: **>= 350** seguidores<br/>IG `Gamestore`: **>= 600** seguidores<br/>TG `@promosgeektech`: **>= 120** membros | **>= 30%** retenção 3s nos Reels; **3 plataformas** (ML + Magalu + Amazon BR) rodando sem queda | **>= 450** cliques/semana; **>= 20** vendas confirmadas/mês com ticket médio > R\$ 180 |
| **90 Dias (Mês 3)** | FB `Gamestore`: **>= 800** seguidores<br/>IG `Gamestore`: **>= 1.500** seguidores<br/>TG `@promosgeektech`: **>= 300** membros | Top 20% categorias/horários escalados via dados; **>= 35%** retenção 3s em Reels | **>= 1.000** cliques/semana; **>= 50** vendas confirmadas/mês e fluxo recorrente no TG |

---

## 3. Plano por Fase (Meses 1, 2 e 3)

### Mês 1 (Dias 1–30) — Calibração de Cadência, Criação do Instagram & Funil Bio/Telegram
**Objetivo:** eliminar fadiga de feed/canal, estruturar o Instagram Profissional como segundo motor de descoberta e direcionar tráfego orgânico de Reels/Stories para o `@promosgeektech`.

1. **Calibração Anti-Fadiga (Implantada na Semana 1):**
   - **Facebook Feed `Gamestore`:** reduzir de 5 para **3 ofertas/rodada** (9/dia + 1 Card Editorial 4:5 às 15h BRT), filtrando com prioridade máxima itens com **`menor_preco_historico=True`** e maior **`queda_real_percent`**.
   - **Telegram `@promosgeektech`:** reduzir de 20 para **10 ofertas/rodada** (30/dia + 1 Card Editorial 4:5 às 15h BRT), mantendo a seleção das 10 melhores por **mínima histórica + queda real + desconto + lucro**.
   - **Motor de Descoberta Inalterado:** manter **4 Reels/dia** (3 de ofertas + 1 *Giro Gamestore* às 15h) e **7 Stories/dia** (6 de ofertas + 1 Story Editorial às 15h).
2. **Setup Instagram Profissional (`Gamestore`) & Funil Link na Bio:**
   - Criar conta `@gamestore...` no Instagram em modo **Profissional (Criador/Negócios)** e vincular diretamente à Página `Gamestore` no Meta Business Suite.
   - Configurar página gratuita de **Link na Bio** (Bento / Linktree / GitHub Pages estático) com 3 botões prioritários: (1) Canal VIP `@promosgeektech`, (2) Vitrine Mercado Livre (`rafaelmelo825`), (3) Vitrine Magalu (`magazinedealz`).
   - Preparar permissões da Meta Graph API (`instagram_basic`, `instagram_content_publish`, `pages_read_engagement`) e secrets `IG_USER_ID` / `IG_ENABLED='false'`.
3. **Reuso Zero-Infra de CDN da Meta:**
   - Em vez de pagar S3/Cloudinary para hospedar MP4 e JPG antes de publicar no Instagram, o fluxo já planejado consulta a URL pública hospedada pela própria Meta após o upload no Facebook (`GET /{video_id}?fields=source` ou `GET /{photo_id}?fields=images`), passando essa URL diretamente ao container `/{ig_user_id}/media`.

### Mês 2 (Dias 31–60) — Instagram Graph API (`IG_ENABLED`) + Expansão Amazon Brasil (`AMAZON_ENABLED`)
**Objetivo:** multiplicar distribuição vertical sem custo extra e ampliar o inventário com a maior vitrine tech/gamer do país (Amazon Brasil).

1. **Publicação Automatizada no Instagram (`IG_ENABLED=true`):**
   - Criar módulo/funções dedicadas para `/{ig_user_id}/media` → polling `status_code=FINISHED` → `/{ig_user_id}/media_publish`:
     - **Reels (4/dia):** replicar Reels de ofertas + Reel *Giro Gamestore* com legenda limpa (`copy-editing` / `humanizer`) e CTA explícito para **Link na Bio + `@promosgeektech`**.
     - **Feed 4:5 (`1080×1350`) + Stories 9:16 (`1080×1920`):** replicar Card Editorial e top ofertas selecionadas sem links clicáveis na legenda.
   - **Degradação isolada:** falha na API do Instagram gera apenas `WARNING` e nunca bloqueia Facebook, Telegram ou SQLite.
2. **Expansão Amazon Brasil (`AMAZON_ENABLED=true` + `AMAZON_ASSOCIATE_TAG`):**
   - Acoplar coletor de ofertas Tech/Gamer da Amazon Brasil (ex.: Ofertas do Dia / Mais Vendidos em Eletrônicos, Games, Computadores e Periféricos) injetando `?tag={AMAZON_ASSOCIATE_TAG}` em toda URL.
   - Padronizar SKUs com prefixo **`AMZ_`** (`AMZ_<ASIN>`) no `storage_db.py` (`inferir_loja_por_sku` + `historico_precos`), garantindo **zero colisão** com `ML_` e `MAGALU_`.
   - **Comparativo Inteligente + Radar 180d:** quando uma oferta Amazon bater a mediana de 180d (após warm-up `>= 5` dias), aplicar badge `🟠 [AMAZON BR]` e priorizá-la contra itens equivalentes de ML/Magalu.
3. **Resiliência Anti-WAF nas 3 Lojas:**
   - Implementar helper único de sessão HTTP com backoff exponencial (jitter), rotação de `User-Agent`/headers realistas e isolamento estrito por plataforma (`Mercado Livre`, `Magalu`, `Amazon Brasil`): bloqueio WAF em uma vitrine loga via `_diagnosticar_bloqueio_http` e deixa as outras duas rodarem normalmente.

### Mês 3 (Dias 61–90) — Otimização de Conversão (CRO) & Escala Orientada a Dados
**Objetivo:** usar 60 dias de dados reais para concentrar cadência apenas no que gera clique e comissão.

1. **Dashboard Consolidado (`dashboard_generator.py`):**
   - Estender Aba 1 com seguidores/alcance do **Instagram**, contagem de itens raspados/postados da **Amazon Brasil** (`AMZ_`), e breakdown de envios por formato (Feed, Story, Reel, Telegram).
   - Estender Aba 2 (`localStorage`) com tags de **Origem/Formato** (`FB Feed`, `FB Reel`, `IG Reel`, `Story`, `Telegram`) e **Horário** (`10h`, `15h`, `20h`) + **Loja** (`ML`, `Magalu`, `Amazon BR`).
2. **Cortes & Escala Baseados em Evidência:**
   - **Poda de subnichos:** remover do `POOL_ML`, `POOL_MAGALU` e lista Amazon categorias com zero vendas e baixo CTR após 60 dias.
   - **Alocação de Reels/Stories:** dobrar peso de `_bonus_nicho_gamestore` para categorias campeãs de conversão (ex.: SSDs, controles, periféricos ou monitores) e calibrar os horários de pico entre 10h, 15h e 20h BRT.
3. **Rito Semanal (`da-workflow-ops`):**
   - Toda semana: revisar Aba 1 + Aba 2 do dashboard (15 min), rodar retrospectiva rápida e registrar ajustes no `GEMINI.md` via `/learn`.

---

## 4. Backlog Técnico Semana a Semana (Semanas 1 a 12)

| Semana | Entregável Principal | Arquivos Afetados | Esforço | Risco & Mitigação | Critério de Aceite |
| :---: | :--- | :--- | :---: | :--- | :--- |
| **S1** | **Calibração anti-fadiga (FB 3 / TG 10)** + flags `IG_ENABLED=false` e `AMAZON_ENABLED=false` + `ESTRATEGIA_90_DIAS.md` | `magalu_scrapper.py`, `.github/workflows/alpha-profit-bot.yml`, `README.md`, `tests/test_radar_e_parser.py`, `ESTRATEGIA_90_DIAS.md` | **P** | Risco: regressão em testes antigos de contagem.<br/>Mitigação: teste unitário dedicado validando limites `3` e `10` com prioridade por mínima/queda. | `unittest` 100% verde; Feed FB envia Top 3, TG envia Top 10; `schedule:` comentado para `cron-job.org`. |
| **S2** | **Setup Instagram Profissional + Link na Bio + Permissões Meta** + validação visual do `--editorial-only` | Meta Business Suite, Secrets GitHub (`IG_USER_ID`), `cron-job.org` | **P** | Risco: token sem permissão `instagram_content_publish`.<br/>Mitigação: testar `/me/accounts?fields=instagram_business_account` antes de codar. | Conta IG vinculada à Página `Gamestore`; Link na Bio ativo apontando para `@promosgeektech`; `cron-job.org` disparando 10h/15h/20h. |
| **S3** | **Helper de Reuso CDN Meta** (extrair URL pública de foto/vídeo do FB para IG) + rascunho cliente IG | `magalu_scrapper.py` (ou `instagram_publisher.py`), `rss_editorial.py` | **M** | Risco: URL temporária ou atraso de processamento de vídeo no FB.<br/>Mitigação: backoff curto antes de consultar `source` e fallback seguro se ausente. | Teste unitário simulando obtenção da URL pública e criação do container sem upload externo. |
| **S4** | **Retrospectiva Mês 1 (`da-workflow-ops`)** + ajuste de copy/ganchos de Reels e Card 4:5 com base nos primeiros 30d | `media_generator.py`, `rss_editorial.py`, `dashboard_acompanhamento.html` | **P** | Risco: baixa retenção nos primeiros 3s.<br/>Mitigação: ajustar ganchos no prompt do Gemini e contraste de headline usando métricas reais. | Relatório Mês 1 fechado comparando OKRs vs. realizado; 0 erros recorrentes no Actions. |
| **S5** | **Integração Instagram Reels (`IG_ENABLED=true`)** — ofertas + Reel Editorial *Giro Gamestore* | `magalu_scrapper.py`, `rss_editorial.py`, `tests/` | **M** | Risco: erro de aspect ratio ou container `IN_PROGRESS`.<br/>Mitigação: polling com timeout (máx. 60s) em `try/except` isolado; manter safe zones já validadas. | 1º Reel publicado automaticamente no IG `Gamestore` com legenda sem links e CTA para Bio + TG. |
| **S6** | **Integração Instagram Feed 4:5 + Stories 9:16** (Editorial + Ofertas) | `magalu_scrapper.py`, `rss_editorial.py`, `tests/` | **M** | Risco: rate limit da Meta API.<br/>Mitigação: respeitar intervalos de 5–8s entre publicações e limite diário calibrado. | Card 4:5 editorial e Stories 9:16 espelhados no IG sem afetar FB nem Telegram. |
| **S7** | **Suporte `AMZ_` no `storage_db.py` + Esqueleto Scraper Amazon BR (`AMAZON_ENABLED=false`)** | `storage_db.py`, `magalu_scrapper.py`, `tests/test_storage_db.py` | **M** | Risco: colisão de SKUs ou HTML bloqueado por CAPTCHA.<br/>Mitigação: prefixo obrigatório `AMZ_`, zero tentativa de burlar CAPTCHA, degradação segura. | `inferir_loja_por_sku("AMZ_B0...") == "Amazon Brasil"` e testes de upsert 180d passando. |
| **S8** | **Coleta Amazon Brasil ativa (`AMAZON_ENABLED=true` + `AMAZON_ASSOCIATE_TAG`)** + mistura na cota IA/Fallback + Resiliência WAF | `magalu_scrapper.py`, `.github/workflows/alpha-profit-bot.yml`, `tests/test_radar_e_parser.py` | **G** | Risco: WAF bloquear GitHub runner.<br/>Mitigação: backoff, headers rotativos, diagnóstico HTTP explícito e isolamento total por loja. | Ofertas Amazon com `?tag=` aparecendo no Telegram/FB/IG junto com ML e Magalu, com Radar 180d ativo. |
| **S9** | **Dashboard v2 (`dashboard_generator.py`):** KPIs Instagram + Amazon BR + atribuição por canal/horário/formato | `dashboard_generator.py`, `magalu_scrapper.py`, `tests/` | **M** | Risco: quebra de histórico antigo em `historico_metricas.json`.<br/>Mitigação: campos novos sempre opcionais (`None`/0 por default) com retrocompatibilidade total. | `dashboard_acompanhamento.html` renderizando séries IG, Amazon BR, ML e Magalu offline sem erros JS. |
| **S10** | **Auditoria de Conversão & Otimização de Catálogo/Horários (CRO)** | `magalu_scrapper.py` (pools + `_bonus_nicho_gamestore`), `cron-job.org` | **P** | Risco: cortar subnicho cedo demais sem amostra.<br/>Mitigação: manter regra de `>= 14 dias` de amostra mínima antes de podar categoria. | Pools atualizados removendo 20% piores categorias e reforçando subnichos líderes de clique/venda. |
| **S11** | **Testes A/B de CTA e Copy (Bio vs. `@promosgeektech`, preço vs. desconto no Card/Reel)** | `rss_editorial.py`, `magalu_scrapper.py`, `media_generator.py` | **M** | Risco: poluição visual no card.<br/>Mitigação: manter padrão *Impeccable* e Safe Zones intactas; variar apenas 1 elemento por teste. | Registro comparativo de 7–14 dias identificando CTA com maior conversão para o Telegram. |
| **S12** | **Fechamento 90 Dias, Hardening & Preparação Mês 7+ (Roadmap WhatsApp)** | `ESTRATEGIA_90_DIAS.md`, `GEMINI.md`, `README.md` | **P** | Risco: regressões acumuladas no fim do trimestre.<br/>Mitigação: auditoria completa de testes + `/learn` consolidando lições dos 90 dias. | OKRs de 90d auditados, base SQLite 180d saudável e plano do Trimestre 2 aprovado. |

---

## 5. Backlog Futuro — Mês 7+ (Fora de Escopo Atual)
- **WhatsApp (Canal/Comunidade Oficial `Gamestore`):** mantido **fora dos Meses 1–6** para evitar custos de API oficial (Cloud API) ou risco de banimento em automações não oficiais antes de validar retenção orgânica e receita recorrente no trio **Facebook + Instagram + Telegram**. Reavaliar apenas a partir do **Mês 7** quando o canal `@promosgeektech` tiver massa crítica consolidada.
