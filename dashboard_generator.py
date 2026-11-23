import json
import logging
import os
from datetime import datetime
from urllib.request import urlopen
from urllib.parse import urlencode

METRICAS_ARQUIVO = "historico_metricas.json"
DASHBOARD_ARQUIVO = "dashboard_acompanhamento.html"


def obter_membros_telegram(bot_token, chat_id):
    """Consulta a contagem atual de membros do canal no Telegram (100% gratuito)."""
    if not bot_token or not chat_id:
        return None
    try:
        qs = urlencode({"chat_id": chat_id})
        url = f"https://api.telegram.org/bot{bot_token}/getChatMemberCount?{qs}"
        with urlopen(url, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return int(data.get("result", 0))
    except Exception as e:
        logging.warning(f"Não foi possível consultar membros do Telegram: {e}")
    return None


def _http_get_json(url, timeout=12):
    """Helper stdlib GET JSON sem dependências externas."""
    try:
        with urlopen(url, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


def obter_metricas_facebook_page(page_token, page_id=None):
    """
    Coleta métricas oficiais da Página do Facebook via Meta Graph API (100% gratuito):
      - Seguidores e Curtidas (followers_count / fan_count)
      - Ranking dos Top 10 posts recentes por engajamento (curtidas, comentários, compartilhamentos)
      - Alcance de 28 dias (se a permissão opcional read_insights estiver ativa)
    """
    if not page_token:
        return None

    # 1. Converte User Token -> Page Token se necessário via /me/accounts
    acc_url = f"https://graph.facebook.com/v21.0/me/accounts?{urlencode({'fields': 'id,name,access_token', 'access_token': page_token})}"
    acc_data = _http_get_json(acc_url)
    if acc_data and acc_data.get("data"):
        paginas = acc_data["data"]
        escolhida = next((p for p in paginas if page_id and str(p.get("id")) == str(page_id)), paginas[0])
        page_id = escolhida.get("id")
        if escolhida.get("access_token"):
            page_token = escolhida["access_token"]

    # 2. Dados gerais da Página (nome, seguidores, curtidas)
    alvo = page_id or "me"
    info_url = f"https://graph.facebook.com/v21.0/{alvo}?{urlencode({'fields': 'id,name,followers_count,fan_count,category', 'access_token': page_token})}"
    info = _http_get_json(info_url)
    if not info or not info.get("id"):
        return None

    page_id = info["id"]
    resultado = {
        "page_name": info.get("name", "Página Facebook"),
        "followers": info.get("followers_count"),
        "fans": info.get("fan_count"),
        "category": info.get("category", ""),
        "reach_28d": None,
        "top_posts": [],
    }

    # 3. Últimos 25 posts para ranking de performance (curtidas, comentários, compartilhamentos)
    posts_qs = urlencode({
        "fields": "id,message,created_time,shares,likes.summary(true),comments.summary(true)",
        "limit": 25,
        "access_token": page_token,
    })
    posts_data = _http_get_json(f"https://graph.facebook.com/v21.0/{page_id}/posts?{posts_qs}")
    if posts_data and posts_data.get("data"):
        posts_norm = []
        for p in posts_data["data"]:
            likes = int(((p.get("likes") or {}).get("summary") or {}).get("total_count", 0) or 0)
            comments = int(((p.get("comments") or {}).get("summary") or {}).get("total_count", 0) or 0)
            shares = int((p.get("shares") or {}).get("count", 0) or 0)
            msg = str(p.get("message") or "(Post sem texto / Mídia)").replace("\n", " ").strip()
            posts_norm.append({
                "date": str(p.get("created_time", ""))[:16].replace("T", " "),
                "title": (msg[:75] + "...") if len(msg) > 78 else msg,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "score": likes + (comments * 2) + (shares * 3),
            })
        posts_norm.sort(key=lambda x: x["score"], reverse=True)
        resultado["top_posts"] = posts_norm[:10]

    # 4. Alcance de 28 dias (opcional — funciona se read_insights estiver ativo)
    ins_qs = urlencode({
        "metric": "page_impressions_unique",
        "period": "days_28",
        "access_token": page_token,
    })
    ins_data = _http_get_json(f"https://graph.facebook.com/v21.0/{page_id}/insights?{ins_qs}")
    if ins_data and ins_data.get("data"):
        try:
            vals = ins_data["data"][0].get("values", [])
            if vals:
                resultado["reach_28d"] = int(vals[-1].get("value", 0) or 0)
        except Exception:
            pass

    logging.info(
        f"📘 Métricas Facebook ({resultado['page_name']}): "
        f"{resultado['followers']} seguidores | {len(resultado['top_posts'])} posts analisados."
    )
    return resultado


def carregar_historico_metricas(caminho=METRICAS_ARQUIVO):
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
            return dados if isinstance(dados, list) else []
    except Exception as e:
        logging.warning(f"Erro ao ler {caminho}: {e}")
        return []


def registrar_metricas_execucao(
    raspados_ml=0,
    raspados_magalu=0,
    postados_telegram=0,
    postados_threads=0,
    postados_facebook=0,
    postados_x=0,
    membros_telegram=None,
    fb_insights=None,
    oportunidades_dict=None,
    caminho=METRICAS_ARQUIVO,
):
    """Registra a telemetria da execução atual em historico_metricas.json (até 500 rodadas)."""
    historico = carregar_historico_metricas(caminho)

    categorias = {}
    if oportunidades_dict and "oportunidades" in oportunidades_dict:
        for op in oportunidades_dict.get("oportunidades", []):
            cat = str(op.get("categoria") or op.get("loja") or "Geral").strip()
            categorias[cat] = categorias.get(cat, 0) + 1

    # Custo estimado no X em Modo Econômico (US$ 0.015/post sem URL)
    custo_x_usd = round(int(postados_x or 0) * 0.015, 4)

    status = "OK"
    if postados_telegram == 0:
        status = "ALERTA_TG"
    elif raspados_ml == 0 or raspados_magalu == 0:
        status = "PARCIAL"

    # Remove top_posts_fb de registros antigos para manter o JSON compacto
    for item in historico:
        item.pop("top_posts_fb", None)

    registro = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "raspados_ml": int(raspados_ml or 0),
        "raspados_magalu": int(raspados_magalu or 0),
        "postados_telegram": int(postados_telegram or 0),
        "postados_threads": int(postados_threads or 0),
        "postados_facebook": int(postados_facebook or 0),
        "postados_x": int(postados_x or 0),
        "membros_telegram": membros_telegram,
        "seguidores_facebook": fb_insights.get("followers") if fb_insights else None,
        "alcance_fb_28d": fb_insights.get("reach_28d") if fb_insights else None,
        "pagina_fb_nome": fb_insights.get("page_name") if fb_insights else None,
        "top_posts_fb": fb_insights.get("top_posts", []) if fb_insights else [],
        "custo_x_usd": custo_x_usd,
        "categorias": categorias,
        "status": status,
    }

    historico.append(registro)
    historico = historico[-500:]

    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
        logging.info(f"📊 Métricas da execução registradas ({len(historico)} rodadas no histórico).")
    except Exception as e:
        logging.warning(f"Erro ao salvar {caminho}: {e}")

    return historico


def gerar_dashboard_html(historico=None, arquivo_saida=DASHBOARD_ARQUIVO):
    """
    Gera um arquivo HTML 100% standalone (funciona offline no navegador) com:
      - Aba 1: Saúde & Execuções do Bot (telemetria automática do GitHub Actions)
      - Aba 2: Controle de Vendas & Comissões Reais (lançamento manual salvo no localStorage)
    """
    if historico is None:
        historico = carregar_historico_metricas()

    dados_json = json.dumps(historico, ensure_ascii=False)
    atualizado_em = datetime.now().strftime("%d/%m/%Y às %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Alpha-Profit — Dashboard de Acompanhamento</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: #121a2e;
      --card2: #18233d;
      --border: #253252;
      --text: #eef2ff;
      --muted: #94a3b8;
      --primary: #3b82f6;
      --green: #10b981;
      --yellow: #f59e0b;
      --red: #ef4444;
      --purple: #8b5cf6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 20px;
    }}
    .container {{ max-width: 1120px; margin: 0 auto; }}
    header {{
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
      gap: 16px; background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 20px 24px; margin-bottom: 20px;
    }}
    h1 {{ margin: 0; font-size: 20px; }}
    .subtitle {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .tab-btn {{
      border: 1px solid var(--border); background: var(--card2); color: var(--text);
      padding: 9px 16px; border-radius: 10px; font-size: 13px; font-weight: 600;
      cursor: pointer; transition: 0.15s;
    }}
    .tab-btn.active {{ background: var(--primary); border-color: var(--primary); color: #fff; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .grid-4 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-bottom: 18px; }}
    .grid-2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; margin-bottom: 18px; }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 18px;
    }}
    .kpi-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .kpi-value {{ font-size: 26px; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }}
    .kpi-sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .text-green {{ color: var(--green); }}
    .text-yellow {{ color: var(--yellow); }}
    .text-red {{ color: var(--red); }}
    .text-blue {{ color: var(--primary); }}
    h2 {{ margin: 0 0 12px 0; font-size: 15px; }}
    canvas {{ width: 100%; height: 240px; display: block; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 8px; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--muted); font-weight: 600; font-size: 12px; }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .badge {{
      display: inline-block; padding: 2px 8px; border-radius: 999px;
      font-size: 11px; font-weight: 600;
    }}
    .badge-ok {{ background: rgba(16,185,129,0.16); color: var(--green); }}
    .badge-warn {{ background: rgba(245,158,11,0.18); color: var(--yellow); }}
    .badge-err {{ background: rgba(239,68,68,0.18); color: var(--red); }}
    .badge-ml {{ background: rgba(245,158,11,0.18); color: #fbbf24; }}
    .badge-magalu {{ background: rgba(59,130,246,0.18); color: #60a5fa; }}
    .form-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px; align-items: end; margin-bottom: 14px;
    }}
    label {{ display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }}
    input, select {{
      background: var(--bg); color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 10px; font-size: 13px;
    }}
    .btn {{
      background: var(--primary); color: #fff; border: none; border-radius: 8px;
      padding: 9px 14px; font-size: 13px; font-weight: 600; cursor: pointer;
    }}
    .btn-outline {{
      background: transparent; color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 7px 12px; font-size: 12px; font-weight: 600; cursor: pointer;
    }}
    .btn-del {{
      background: transparent; color: var(--red); border: 1px solid rgba(239,68,68,0.35);
      border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer;
    }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 12px; }}
    .cat-bar-wrap {{ margin-bottom: 10px; }}
    .cat-bar-head {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }}
    .cat-bar-bg {{ height: 8px; background: var(--bg); border-radius: 999px; overflow: hidden; }}
    .cat-bar-fill {{ height: 100%; background: var(--primary); border-radius: 999px; }}
    .empty {{ text-align: center; color: var(--muted); padding: 24px; font-size: 13px; }}
    .overflow-x {{ overflow-x: auto; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>📊 Alpha-Profit — Painel de Acompanhamento</h1>
        <div class="subtitle">Telegram (@promosgeektech) • Threads • Facebook • X (Modo Econômico) | Gerado em {atualizado_em}</div>
      </div>
      <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('bot', this)">🤖 Operação do Bot</button>
        <button class="tab-btn" onclick="switchTab('vendas', this)">💰 Vendas & Comissões Reais</button>
      </div>
    </header>

    <!-- ABA 1: OPERAÇÃO DO BOT -->
    <div id="tab-bot" class="tab-panel active">
      <div class="grid-4" id="bot-kpis"></div>

      <div class="grid-2">
        <div class="card">
          <h2>📈 Evolução de Membros no Telegram (@promosgeektech)</h2>
          <canvas id="membersChart"></canvas>
        </div>
        <div class="card">
          <h2>🏷️ Categorias Mais Mineradas pelo Bot</h2>
          <div id="categories-box"></div>
        </div>
      </div>

      <div class="card" style="margin-bottom: 18px;">
        <h2>📘 Performance da Página Facebook (Gamestore) — Top Posts Recentes</h2>
        <div class="overflow-x">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Publicação</th>
                <th class="num">Curtidas</th>
                <th class="num">Comentários</th>
                <th class="num">Compart.</th>
              </tr>
            </thead>
            <tbody id="fb-top-posts"></tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h2>🕒 Histórico de Execuções do Bot (GitHub Actions)</h2>
        <div class="overflow-x">
          <table>
            <thead>
              <tr>
                <th>Data / Hora</th>
                <th class="num">Raspados (ML / Magalu)</th>
                <th class="num">Telegram</th>
                <th class="num">Threads</th>
                <th class="num">Facebook</th>
                <th class="num">X</th>
                <th class="num">Membros TG</th>
                <th class="num">Custo X</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id="bot-table"></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ABA 2: VENDAS & COMISSÕES REAIS -->
    <div id="tab-vendas" class="tab-panel">
      <div class="grid-4" id="sales-kpis"></div>

      <div class="card" style="margin-bottom: 18px;">
        <h2>➕ Lançar Fechamento Real (Mercado Livre / Magalu)</h2>
        <form id="sales-form" class="form-grid" onsubmit="addSaleEntry(event)">
          <label>Data
            <input type="date" id="s-date" required />
          </label>
          <label>Plataforma
            <select id="s-platform">
              <option value="Mercado Livre">Mercado Livre</option>
              <option value="Magalu">Magalu</option>
            </select>
          </label>
          <label>Cliques
            <input type="number" id="s-clicks" min="0" value="0" required />
          </label>
          <label>Vendas Concluídas
            <input type="number" id="s-sales" min="0" value="0" required />
          </label>
          <label>Comissão Real (R$)
            <input type="number" id="s-commission" min="0" step="0.01" value="0.00" required />
          </label>
          <label>Observação (opcional)
            <input type="text" id="s-note" placeholder="Ex: SSD, Black Friday..." />
          </label>
          <button type="submit" class="btn">Salvar Lançamento</button>
        </form>
        <div style="font-size: 12px; color: var(--muted);">
          💡 Os lançamentos ficam salvos no seu navegador (<code>localStorage</code>). Use o botão <b>Exportar Backup</b> periodicamente para guardar uma cópia segura.
        </div>
      </div>

      <div class="card">
        <div class="toolbar">
          <h2 style="margin: 0;">📑 Lançamentos de Cliques e Comissões Reais</h2>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button class="btn-outline" onclick="exportSalesCSV()">⬇️ Exportar CSV</button>
            <button class="btn-outline" onclick="exportSalesJSON()">💾 Backup JSON</button>
            <label class="btn-outline" style="flex-direction: row; align-items: center; cursor: pointer; margin: 0;">
              📂 Importar JSON
              <input type="file" accept=".json" onchange="importSalesJSON(event)" style="display:none;" />
            </label>
          </div>
        </div>
        <div class="overflow-x">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Plataforma</th>
                <th class="num">Cliques</th>
                <th class="num">Vendas</th>
                <th class="num">Conv. %</th>
                <th class="num">Comissão (R$)</th>
                <th>Obs.</th>
                <th class="num">Ação</th>
              </tr>
            </thead>
            <tbody id="sales-table"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script>
    const BOT_HISTORY = {dados_json};
    const STORAGE_KEY = "alpha_profit_sales_v1";
    const USD_BRL = 5.80;

    function switchTab(name, btn) {{
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.getElementById("tab-" + name).classList.add("active");
      btn.classList.add("active");
      if (name === "bot") drawMembersChart();
    }}

    const fmtBRL = (v) => "R$ " + Number(v || 0).toLocaleString("pt-BR", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    const fmtUSD = (v) => "US$ " + Number(v || 0).toLocaleString("pt-BR", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});

    function getTotalBotXCostUSD() {{
      return BOT_HISTORY.reduce((acc, r) => acc + Number(r.custo_x_usd || 0), 0);
    }}

    function renderBotTab() {{
      const totalRuns = BOT_HISTORY.length;
      const totalTG = BOT_HISTORY.reduce((a, r) => a + (r.postados_telegram || 0), 0);
      const totalThreads = BOT_HISTORY.reduce((a, r) => a + (r.postados_threads || 0), 0);
      const totalFB = BOT_HISTORY.reduce((a, r) => a + (r.postados_facebook || 0), 0);
      const totalX = BOT_HISTORY.reduce((a, r) => a + (r.postados_x || 0), 0);
      const totalXUsd = getTotalBotXCostUSD();

      const validMembers = BOT_HISTORY.filter(r => r.membros_telegram !== null && r.membros_telegram !== undefined);
      const latestMembers = validMembers.length ? validMembers[validMembers.length - 1].membros_telegram : null;
      const firstMembers = validMembers.length ? validMembers[0].membros_telegram : null;
      const deltaMembers = (latestMembers !== null && firstMembers !== null) ? (latestMembers - firstMembers) : 0;

      const validFb = BOT_HISTORY.filter(r => r.seguidores_facebook !== null && r.seguidores_facebook !== undefined);
      const latestFb = validFb.length ? validFb[validFb.length - 1].seguidores_facebook : null;
      const firstFb = validFb.length ? validFb[0].seguidores_facebook : null;
      const deltaFb = (latestFb !== null && firstFb !== null) ? (latestFb - firstFb) : 0;
      const latestReach = validFb.length ? validFb[validFb.length - 1].alcance_fb_28d : null;

      document.getElementById("bot-kpis").innerHTML = `
        <div class="card">
          <div class="kpi-label">Membros no Telegram</div>
          <div class="kpi-value text-blue">${{latestMembers !== null ? latestMembers.toLocaleString("pt-BR") : "—"}}</div>
          <div class="kpi-sub">${{deltaMembers >= 0 ? "+" + deltaMembers : deltaMembers}} desde o início do tracking</div>
        </div>
        <div class="card">
          <div class="kpi-label">Seguidores Facebook</div>
          <div class="kpi-value text-blue">${{latestFb !== null ? latestFb.toLocaleString("pt-BR") : "—"}}</div>
          <div class="kpi-sub">${{deltaFb >= 0 ? "+" + deltaFb : deltaFb}} seg.${{latestReach !== null ? " • Alcance 28d: " + latestReach.toLocaleString("pt-BR") : ""}}</div>
        </div>
        <div class="card">
          <div class="kpi-label">Ofertas Publicadas</div>
          <div class="kpi-value text-green">${{(totalTG + totalThreads + totalFB + totalX).toLocaleString("pt-BR")}}</div>
          <div class="kpi-sub">TG: ${{totalTG}} • Threads: ${{totalThreads}} • FB: ${{totalFB}} • X: ${{totalX}}</div>
        </div>
        <div class="card">
          <div class="kpi-label">Custo Estimado API X</div>
          <div class="kpi-value text-yellow">${{fmtUSD(totalXUsd)}}</div>
          <div class="kpi-sub">≈ ${{fmtBRL(totalXUsd * USD_BRL)}} (${{totalRuns}} execuções)</div>
        </div>
      `;

      // Top Posts do Facebook (Gamestore)
      const latestWithPosts = [...BOT_HISTORY].reverse().find(r => Array.isArray(r.top_posts_fb) && r.top_posts_fb.length > 0);
      const fbTbody = document.getElementById("fb-top-posts");
      if (!latestWithPosts) {{
        fbTbody.innerHTML = `<tr><td colspan="5" class="empty">Aguardando próxima execução com FACEBOOK_PAGE_TOKEN para listar os melhores posts da Gamestore!</td></tr>`;
      }} else {{
        fbTbody.innerHTML = latestWithPosts.top_posts_fb.map(p => `
          <tr>
            <td>${{p.date}}</td>
            <td>${{p.title}}</td>
            <td class="num">${{p.likes}}</td>
            <td class="num">${{p.comments}}</td>
            <td class="num">${{p.shares}}</td>
          </tr>
        `).join("");
      }}

      // Categorias
      const catCounts = {{}};
      BOT_HISTORY.forEach(r => {{
        Object.entries(r.categorias || {{}}).forEach(([k, v]) => {{
          catCounts[k] = (catCounts[k] || 0) + v;
        }});
      }});
      const sortedCats = Object.entries(catCounts).sort((a, b) => b[1] - a[1]).slice(0, 7);
      const maxCat = sortedCats.length ? sortedCats[0][1] : 1;
      document.getElementById("categories-box").innerHTML = sortedCats.length
        ? sortedCats.map(([cat, count]) => `
            <div class="cat-bar-wrap">
              <div class="cat-bar-head"><span>${{cat}}</span><span>${{count}} ofertas</span></div>
              <div class="cat-bar-bg"><div class="cat-bar-fill" style="width:${{Math.round((count / maxCat) * 100)}}%"></div></div>
            </div>
          `).join("")
        : `<div class="empty">Ainda sem execuções registradas neste arquivo. Assim que o GitHub Actions rodar, os dados aparecerão aqui automaticamente!</div>`;

      // Tabela de execuções
      const tbody = document.getElementById("bot-table");
      if (!BOT_HISTORY.length) {{
        tbody.innerHTML = `<tr><td colspan="9" class="empty">Nenhuma execução registrada ainda. Rode o workflow no GitHub Actions para começar a coletar métricas!</td></tr>`;
      }} else {{
        tbody.innerHTML = [...BOT_HISTORY].reverse().slice(0, 40).map(r => {{
          const badgeClass = r.status === "OK" ? "badge-ok" : (r.status === "PARCIAL" ? "badge-warn" : "badge-err");
          return `
            <tr>
              <td>${{r.timestamp}}</td>
              <td class="num">${{r.raspados_ml}} / ${{r.raspados_magalu}}</td>
              <td class="num">${{r.postados_telegram}}</td>
              <td class="num">${{r.postados_threads}}</td>
              <td class="num">${{r.postados_facebook ?? 0}}</td>
              <td class="num">${{r.postados_x}}</td>
              <td class="num">${{r.membros_telegram ?? "—"}}</td>
              <td class="num">${{fmtUSD(r.custo_x_usd)}}</td>
              <td><span class="badge ${{badgeClass}}">${{r.status}}</span></td>
            </tr>
          `;
        }}).join("");
      }}

      drawMembersChart();
    }}

    function drawMembersChart() {{
      const canvas = document.getElementById("membersChart");
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width) return;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      const ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);

      const W = rect.width, H = rect.height;
      ctx.clearRect(0, 0, W, H);

      const pts = BOT_HISTORY.filter(r => r.membros_telegram !== null && r.membros_telegram !== undefined).slice(-30);
      if (pts.length < 1) {{
        ctx.fillStyle = "#94a3b8";
        ctx.font = "13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Aguardando primeiras execuções para plotar a curva de membros...", W / 2, H / 2);
        return;
      }}

      const pad = {{ top: 22, right: 20, bottom: 28, left: 46 }};
      const plotW = W - pad.left - pad.right;
      const plotH = H - pad.top - pad.bottom;
      const vals = pts.map(p => p.membros_telegram);
      const minV = Math.max(0, Math.min(...vals) - 2);
      const maxV = Math.max(...vals) + 2;
      const range = (maxV - minV) || 1;

      ctx.strokeStyle = "#253252";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#94a3b8";
      ctx.font = "11px monospace";
      ctx.textAlign = "right";
      for (let i = 0; i <= 3; i++) {{
        const v = minV + (range / 3) * i;
        const y = pad.top + plotH - ((v - minV) / range) * plotH;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
        ctx.fillText(Math.round(v), pad.left - 8, y + 4);
      }}

      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      pts.forEach((p, idx) => {{
        const x = pts.length === 1 ? pad.left + plotW / 2 : pad.left + (plotW / (pts.length - 1)) * idx;
        const y = pad.top + plotH - ((p.membros_telegram - minV) / range) * plotH;
        if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }});
      ctx.stroke();

      pts.forEach((p, idx) => {{
        const x = pts.length === 1 ? pad.left + plotW / 2 : pad.left + (plotW / (pts.length - 1)) * idx;
        const y = pad.top + plotH - ((p.membros_telegram - minV) / range) * plotH;
        ctx.fillStyle = "#60a5fa";
        ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
      }});
    }}

    // --- ABA 2: VENDAS REAIS (LOCALSTORAGE) ---
    function loadSales() {{
      try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }}
      catch {{ return []; }}
    }}

    function saveSales(list) {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
      renderSalesTab();
    }}

    function addSaleEntry(ev) {{
      ev.preventDefault();
      const list = loadSales();
      list.push({{
        id: Date.now(),
        date: document.getElementById("s-date").value,
        platform: document.getElementById("s-platform").value,
        clicks: Number(document.getElementById("s-clicks").value || 0),
        sales: Number(document.getElementById("s-sales").value || 0),
        commission: Number(document.getElementById("s-commission").value || 0),
        note: document.getElementById("s-note").value.trim()
      }});
      saveSales(list);
      document.getElementById("s-clicks").value = 0;
      document.getElementById("s-sales").value = 0;
      document.getElementById("s-commission").value = "0.00";
      document.getElementById("s-note").value = "";
    }}

    function deleteSaleEntry(id) {{
      const list = loadSales().filter(x => x.id !== id);
      saveSales(list);
    }}

    function renderSalesTab() {{
      const list = loadSales().sort((a, b) => (b.date || "").localeCompare(a.date || ""));
      const totalClicks = list.reduce((a, x) => a + x.clicks, 0);
      const totalSales = list.reduce((a, x) => a + x.sales, 0);
      const totalComm = list.reduce((a, x) => a + x.commission, 0);
      const mlComm = list.filter(x => x.platform === "Mercado Livre").reduce((a, x) => a + x.commission, 0);
      const mgComm = list.filter(x => x.platform === "Magalu").reduce((a, x) => a + x.commission, 0);

      const xCostBRL = getTotalBotXCostUSD() * USD_BRL;
      const netProfit = totalComm - xCostBRL;
      const convRate = totalClicks > 0 ? ((totalSales / totalClicks) * 100).toFixed(2) : "0,00";

      document.getElementById("sales-kpis").innerHTML = `
        <div class="card">
          <div class="kpi-label">Comissão Bruta Real</div>
          <div class="kpi-value text-green">${{fmtBRL(totalComm)}}</div>
          <div class="kpi-sub">ML: ${{fmtBRL(mlComm)}} • Magalu: ${{fmtBRL(mgComm)}}</div>
        </div>
        <div class="card">
          <div class="kpi-label">Lucro Líquido (vs API X)</div>
          <div class="kpi-value ${{netProfit >= 0 ? "text-green" : "text-red"}}">${{fmtBRL(netProfit)}}</div>
          <div class="kpi-sub">Custo rastreado API X: ${{fmtBRL(xCostBRL)}}</div>
        </div>
        <div class="card">
          <div class="kpi-label">Cliques & Conversão</div>
          <div class="kpi-value text-blue">${{totalClicks.toLocaleString("pt-BR")}}</div>
          <div class="kpi-sub">${{totalSales}} vendas (${{String(convRate).replace(".", ",")}}% conv.)</div>
        </div>
        <div class="card">
          <div class="kpi-label">Comissão Média / Venda</div>
          <div class="kpi-value">${{totalSales > 0 ? fmtBRL(totalComm / totalSales) : "R$ 0,00"}}</div>
          <div class="kpi-sub">Meta conservadora: R$ 9,00/venda</div>
        </div>
      `;

      const tbody = document.getElementById("sales-table");
      if (!list.length) {{
        tbody.innerHTML = `<tr><td colspan="8" class="empty">Nenhum lançamento manual ainda. Use o formulário acima para registrar seus resultados semanais do Mercado Livre e Magalu!</td></tr>`;
      }} else {{
        tbody.innerHTML = list.map(x => {{
          const conv = x.clicks > 0 ? ((x.sales / x.clicks) * 100).toFixed(1).replace(".", ",") + "%" : "—";
          const bClass = x.platform === "Mercado Livre" ? "badge-ml" : "badge-magalu";
          return `
            <tr>
              <td>${{x.date}}</td>
              <td><span class="badge ${{bClass}}">${{x.platform}}</span></td>
              <td class="num">${{x.clicks}}</td>
              <td class="num">${{x.sales}}</td>
              <td class="num">${{conv}}</td>
              <td class="num text-green"><b>${{fmtBRL(x.commission)}}</b></td>
              <td>${{x.note || "—"}}</td>
              <td class="num"><button class="btn-del" onclick="deleteSaleEntry(${{x.id}})">Excluir</button></td>
            </tr>
          `;
        }}).join("");
      }}
    }}

    function exportSalesJSON() {{
      const blob = new Blob([JSON.stringify(loadSales(), null, 2)], {{ type: "application/json" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "vendas_afiliados_backup.json";
      a.click();
    }}

    function exportSalesCSV() {{
      const rows = [["Data", "Plataforma", "Cliques", "Vendas", "Comissao_BRL", "Observacao"]];
      loadSales().forEach(x => rows.push([x.date, x.platform, x.clicks, x.sales, x.commission.toFixed(2), `"${{(x.note || "").replace(/"/g, '""')}}"`]));
      const csv = "\\uFEFF" + rows.map(r => r.join(";")).join("\\n");
      const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8;" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "vendas_afiliados_reais.csv";
      a.click();
    }}

    function importSalesJSON(ev) {{
      const file = ev.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {{
        try {{
          const data = JSON.parse(reader.result);
          if (Array.isArray(data)) saveSales(data);
        }} catch {{ alert("Arquivo JSON inválido."); }}
      }};
      reader.readAsText(file);
    }}

    document.getElementById("s-date").value = new Date().toISOString().slice(0, 10);
    window.addEventListener("resize", drawMembersChart);
    renderBotTab();
    renderSalesTab();
  </script>
</body>
</html>
"""
    with open(arquivo_saida, "w", encoding="utf-8") as f:
        f.write(html)
    logging.info(f"📈 Dashboard HTML de acompanhamento gerado em: {arquivo_saida}")
    return arquivo_saida


if __name__ == "__main__":
    gerar_dashboard_html()
