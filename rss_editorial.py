from email.utils import parsedate_to_datetime
from html import unescape
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import feedparser
    FEEDPARSER_DISPONIVEL = True
except ImportError:
    feedparser = None
    FEEDPARSER_DISPONIVEL = False

try:
    import google.generativeai as genai
    GENAI_DISPONIVEL = True
except ImportError:
    genai = None
    GENAI_DISPONIVEL = False

try:
    import tweepy
    TWEEPY_DISPONIVEL = True
except ImportError:
    tweepy = None
    TWEEPY_DISPONIVEL = False

import storage_db

FEEDS_PADRAO = [
    ("Adrenaline", "https://www.adrenaline.com.br/feed/"),
    ("Tecnoblog", "https://tecnoblog.net/feed/"),
    ("Canaltech", "https://canaltech.com.br/rss/"),
    ("Voxel", "https://rss.tecmundo.com.br/voxel/feed"),
]

_STOPWORDS_PT = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "pro", "pra", "com", "sem", "sob",
    "sobre", "entre", "ate", "apos", "e", "ou", "mas", "que", "se", "como", "mais",
    "menos", "ja", "nao", "sim", "novo", "nova", "novos", "novas", "seu", "sua",
    "seus", "suas", "ao", "aos", "a", "pelo", "pela", "via", "tem", "sao", "vai",
}

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_TME_RE = re.compile(r"\bt\.me/\S+", re.IGNORECASE)
_DOMINIO_SOLTO_RE = re.compile(
    r"(?<![@\w.-])\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|net|org|br|io|gg|tv|co|me|ly|app|tech)(?:\.[a-z]{2})?(?:/[^\s]*)?",
    re.IGNORECASE,
)

EDITORIAL_SYSTEM_PROMPT = """
Você é o Editor-Chefe de Tecnologia & Games do Alpha-Profit / Gamestore.

REGRAS OBRIGATÓRIAS (INVIOLÁVEIS):
1. Escolha APENAS 1 (UMA) notícia entre os candidatos inéditos enviados, priorizando impacto prático em "bolso, setup e decisão de compra" (ex: corte de preço, lançamento que barateia geração anterior, custo-benefício de hardware/console/periféricos).
2. BLINDAGEM FACTUAL: é estritamente proibido inventar especificações técnicas, preços, datas ou porcentagens que não constem explicitamente no título ou resumo do feed recebido.
3. CRÉDITO OBRIGATÓRIO: inclua crédito curto da fonte escolhida ("Via [Fonte]") em `texto_threads` e `texto_facebook`.
4. PONTE CONDICIONAL DE OFERTA: analise as ofertas do dia enviadas no prompt. Só defina `tem_match_oferta: true` e preencha `sku_oferta_relacionada` se houver correspondência REAL e DIRETA de produto ou subcategoria exata (ex: notícia de placa RTX <-> oferta de GPU; notícia de PS5/DualSense <-> oferta de PS5/DualSense). Caso contrário, defina `tem_match_oferta: false`, `sku_oferta_relacionada: ""` e entregue conteúdo 100% editorial puro, sem forçar venda.
5. X (TWITTER) MODO ECONÔMICO: `texto_x` deve ter NO MÁXIMO 260 caracteres, ZERO links, ZERO URLs, ZERO domínios (nem t.me/..., nem .com/.br), com pergunta curta para gerar debate. Menção sutil a `@promosgeektech` somente se fizer sentido.
6. FACEBOOK GAMESTORE: `texto_facebook` NÃO deve conter nenhum link externo no corpo principal (se houver match real de oferta, o sistema postará o link no 1º comentário).

FORMATO DE SAÍDA (JSON ESTRITO):
{
  "url_escolhida": "URL exata de um dos candidatos",
  "fonte": "Nome da fonte escolhida",
  "titulo_original": "Título original da notícia",
  "tema_normalizado": "palavras chave principais sem acentos",
  "tem_match_oferta": false,
  "sku_oferta_relacionada": "",
  "texto_x": "Texto curto sem URLs com pergunta de engajamento",
  "texto_threads": "Post conversacional com Via [Fonte] e pergunta no final",
  "texto_facebook": "Post para página Gamestore com Via [Fonte] e foco em debate/setup",
  "texto_telegram": "Resumo objetivo da notícia com Via [Fonte]"
}
"""


def _env_bool(nome, default=False):
    val = os.getenv(nome)
    if val is None or str(val).strip() == "":
        return bool(default)
    return str(val).strip().lower() in ("1", "true", "sim", "yes", "on")


def agora_brt(agora=None):
    """Retorna datetime timezone-aware no fuso America/Sao_Paulo (UTC-3 fallback)."""
    tz_brt = timezone(timedelta(hours=-3))
    if ZoneInfo is not None:
        try:
            tz_brt = ZoneInfo("America/Sao_Paulo")
        except Exception:
            pass

    if agora is None:
        return datetime.now(tz_brt)
    if agora.tzinfo is None:
        return agora.replace(tzinfo=tz_brt)
    return agora.astimezone(tz_brt)


def deve_executar_editorial(forcar_execucao=False, agora=None, editorial_enabled=None):
    """
    Controla execução do bloco editorial:
      - Feature flag EDITORIAL_ENABLED (default true)
      - Janela diária das 15h BRT (14:00..16:59 BRT) ou --run-editorial
    """
    habilitado = (
        _env_bool("EDITORIAL_ENABLED", default=True)
        if editorial_enabled is None
        else bool(editorial_enabled)
    )
    if not habilitado:
        return False, "editorial_desabilitado_env"

    if forcar_execucao:
        return True, "flag_cli_run_editorial"

    dt_brt = agora_brt(agora)
    if 14 <= dt_brt.hour <= 16:
        return True, "janela_15h_brt"

    return False, f"fora_janela_15h_brt (hora={dt_brt.hour:02d}h)"


def obter_feeds_configurados():
    """Carrega feeds de EDITORIAL_RSS_FEEDS (JSON ou 'Nome|URL;...') com fallback em FEEDS_PADRAO."""
    raw = os.getenv("EDITORIAL_RSS_FEEDS", "").strip()
    if not raw:
        return list(FEEDS_PADRAO)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            feeds = []
            for item in parsed:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    feeds.append((str(item[0]).strip(), str(item[1]).strip()))
                elif isinstance(item, dict) and item.get("url"):
                    feeds.append((str(item.get("fonte") or item.get("name") or "Feed").strip(), str(item["url"]).strip()))
            if feeds:
                return feeds
    except Exception:
        pass

    feeds = []
    for bloco in raw.split(";"):
        if "|" in bloco:
            nome, url = bloco.split("|", 1)
            if nome.strip() and url.strip():
                feeds.append((nome.strip(), url.strip()))
    return feeds or list(FEEDS_PADRAO)


def limpar_html_resumo(texto, max_chars=280):
    """Remove tags HTML, decodifica entidades e compacta espaços do resumo RSS."""
    limpo = re.sub(r"<[^>]+>", " ", unescape(str(texto or "")))
    limpo = re.sub(r"\s+", " ", limpo).strip()
    if max_chars and len(limpo) > max_chars:
        limpo = limpo[: max_chars - 3].rstrip() + "..."
    return limpo


def parsear_data_entry(entry):
    """Converte data de entrada RSS/Atom para datetime UTC timezone-aware (ou None)."""
    for attr in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr, None) if not isinstance(entry, dict) else entry.get(attr)
        if st:
            try:
                ts = time.mktime(st)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass

    for attr in ("published", "updated", "pubDate"):
        raw = getattr(entry, attr, None) if not isinstance(entry, dict) else entry.get(attr)
        if not raw:
            continue
        raw_str = str(raw).strip()
        try:
            dt = parsedate_to_datetime(raw_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        try:
            iso = raw_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return None


def _parsear_xml_rss_stdlib(xml_text):
    """Parser fallback em stdlib ElementTree caso feedparser não esteja instalado."""
    entries = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return entries

    # RSS 2.0 (<channel>/<item>)
    for item in root.findall(".//item"):
        entries.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "summary": (item.findtext("description") or "").strip(),
            "published": (item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip(),
        })

    # Atom (<entry>)
    if not entries:
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(f".//{ns}entry") + root.findall(".//entry"):
            link_el = entry.find(f"{ns}link") or entry.find("link")
            href = link_el.attrib.get("href", "") if link_el is not None else ""
            entries.append({
                "title": (entry.findtext(f"{ns}title") or entry.findtext("title") or "").strip(),
                "link": href.strip(),
                "summary": (entry.findtext(f"{ns}summary") or entry.findtext(f"{ns}content") or entry.findtext("summary") or "").strip(),
                "published": (entry.findtext(f"{ns}updated") or entry.findtext(f"{ns}published") or entry.findtext("updated") or "").strip(),
            })
    return entries


def _extrair_entries_feed(xml_content):
    if FEEDPARSER_DISPONIVEL and feedparser is not None:
        parsed = feedparser.parse(xml_content)
        return list(getattr(parsed, "entries", []) or [])
    txt = xml_content.decode("utf-8", errors="ignore") if isinstance(xml_content, bytes) else str(xml_content)
    return _parsear_xml_rss_stdlib(txt)


def filtrar_noticias_24h(itens, agora_utc=None, horas=24):
    """Mantém apenas notícias com publicação válida dentro das últimas N horas."""
    ref_utc = agora_utc if isinstance(agora_utc, datetime) else datetime.now(timezone.utc)
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)
    else:
        ref_utc = ref_utc.astimezone(timezone.utc)

    limite_inf = ref_utc - timedelta(hours=int(horas))
    limite_sup = ref_utc + timedelta(minutes=15)

    filtrados = []
    for item in itens:
        pub_dt = item.get("_pub_dt") or parsear_data_entry(item)
        if pub_dt is None:
            continue
        if limite_inf <= pub_dt <= limite_sup:
            item_limpo = dict(item)
            item_limpo["publicado_em"] = pub_dt.isoformat()
            item_limpo.pop("_pub_dt", None)
            filtrados.append(item_limpo)
    return filtrados


def coletar_noticias_rss(feeds=None, timeout=10, horas=24, agora_utc=None, fetcher=None):
    """Coleta notícias recentes de feeds Tech/Gamer PT-BR com isolamento de timeout/falha por feed."""
    feeds_alvo = feeds if feeds is not None else obter_feeds_configurados()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AlphaProfitBot/1.0; +https://github.com/rdsmelobsb/bot_afiliados_magalu)"
    }

    brutos = []
    urls_vistas = set()

    for fonte, url_feed in feeds_alvo:
        try:
            if fetcher is not None:
                conteudo = fetcher(url_feed, timeout=timeout)
            else:
                resp = requests.get(url_feed, headers=headers, timeout=timeout)
                resp.raise_for_status()
                conteudo = resp.content

            for entry in _extrair_entries_feed(conteudo):
                titulo = (getattr(entry, "title", None) if not isinstance(entry, dict) else entry.get("title")) or ""
                link = (getattr(entry, "link", None) if not isinstance(entry, dict) else entry.get("link")) or ""
                resumo_raw = (
                    (getattr(entry, "summary", None) or getattr(entry, "description", ""))
                    if not isinstance(entry, dict)
                    else (entry.get("summary") or entry.get("description") or "")
                )
                titulo = str(titulo).strip()
                link = str(link).strip()
                if not titulo or not link:
                    continue

                u_hash = storage_db.gerar_url_hash(link)
                if u_hash in urls_vistas:
                    continue
                urls_vistas.add(u_hash)

                pub_dt = parsear_data_entry(entry)
                brutos.append({
                    "fonte": fonte,
                    "titulo": titulo,
                    "resumo": limpar_html_resumo(resumo_raw, max_chars=280),
                    "url": link,
                    "tema_normalizado": storage_db.normalizar_tema(titulo),
                    "_pub_dt": pub_dt,
                })
        except Exception as exc:
            logging.warning(f"⚠️ Feed RSS indisponível ({fonte}): {exc}")
            continue

    recentes = filtrar_noticias_24h(brutos, agora_utc=agora_utc, horas=horas)
    recentes.sort(key=lambda x: x.get("publicado_em", ""), reverse=True)
    logging.info(f"📰 RSS coletado: {len(recentes)} notícias inéditas nas últimas {horas}h (de {len(brutos)} totais).")
    return recentes


def _palavras_relevantes_tema(tema_norm):
    return {
        p for p in str(tema_norm or "").split()
        if len(p) >= 3 and p not in _STOPWORDS_PT
    }


def temas_similares(tema_a, tema_b, limiar=0.55):
    """Compara similaridade temática (Jaccard sobre tokens significativos) entre portais diferentes."""
    a_norm = storage_db.normalizar_tema(tema_a)
    b_norm = storage_db.normalizar_tema(tema_b)
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True
    toks_a = _palavras_relevantes_tema(a_norm)
    toks_b = _palavras_relevantes_tema(b_norm)
    if not toks_a or not toks_b:
        return False
    inter = len(toks_a & toks_b)
    uniao = len(toks_a | toks_b)
    if inter >= 3 and (inter / float(min(len(toks_a), len(toks_b)))) >= 0.60:
        return True
    return (inter / float(uniao)) >= float(limiar)


def filtrar_pautas_ineditas(conn, candidatos, dias=7, agora=None):
    """Remove notícias já cobertas nos últimos N dias no SQLite (URL ou tema similar)."""
    if not candidatos:
        return []

    ref_dt = agora if isinstance(agora, datetime) else datetime.now()
    limite_iso = (ref_dt - timedelta(days=int(dias))).isoformat()
    rows = conn.execute(
        "SELECT url_hash, tema_normalizado FROM pautas_rss WHERE publicado_em >= ?",
        (limite_iso,),
    ).fetchall()
    temas_recentes = [str(r["tema_normalizado"]) for r in rows if r["tema_normalizado"]]

    ineditas = []
    for item in candidatos:
        url = str(item.get("url", "") or "").strip()
        tema = item.get("tema_normalizado") or storage_db.normalizar_tema(item.get("titulo", ""))
        if not url:
            continue
        if storage_db.pauta_ja_publicada(conn, url, tema_normalizado=tema, dias=dias, agora=ref_dt):
            continue
        if any(temas_similares(tema, t_hist) for t_hist in temas_recentes):
            continue
        ineditas.append(item)

    return ineditas


def editorial_ja_publicado_hoje(conn, agora=None):
    """Evita duplicar pauta editorial no mesmo dia BRT caso a janela das 15h rode mais de uma vez."""
    hoje_brt = agora_brt(agora).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT id FROM pautas_rss WHERE substr(publicado_em, 1, 10) = ? LIMIT 1",
        (hoje_brt,),
    ).fetchone()
    return row is not None


def sanitizar_texto_sem_urls(texto, max_chars=None):
    """Remove qualquer URL, t.me/... ou domínio solto para cumprir modo econômico do X e texto limpo no FB."""
    limpo = str(texto or "")
    limpo = _URL_RE.sub("", limpo)
    limpo = _TME_RE.sub("", limpo)
    limpo = _DOMINIO_SOLTO_RE.sub("", limpo)
    limpo = re.sub(r"[ \t]+", " ", limpo)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo)
    limpo = re.sub(r" ?([,.;:!?])", r"\1", limpo).strip()
    if max_chars and len(limpo) > max_chars:
        limpo = limpo[: max_chars - 3].rstrip() + "..."
    return limpo


def _resumir_ofertas_para_editorial(oportunidades_dict, limite=10):
    ops = (oportunidades_dict or {}).get("oportunidades", [])
    resumo = []
    for op in ops[:limite]:
        resumo.append({
            "sku": op.get("sku_selecionado", ""),
            "titulo": (op.get("nome_produto") or op.get("copy_venda", {}).get("titulo") or "")[:90],
            "categoria": op.get("categoria", "Geral"),
            "loja": op.get("loja", ""),
            "preco_atual": op.get("preco_atual", 0.0),
        })
    return resumo


def gerar_pauta_editorial_gemini(candidatos, ofertas_resumo=None, model_name=None):
    """Chama o Gemini para escolher 1 pauta RSS e gerar os textos multi-canal em JSON estrito."""
    if not GENAI_DISPONIVEL or genai is None:
        raise RuntimeError("Biblioteca 'google-generativeai' indisponível.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY ausente para curadoria editorial.")

    genai.configure(api_key=api_key)
    modelo = model_name or os.getenv("GEMINI_MODEL", "gemini-4-hydrogen")
    model = genai.GenerativeModel(
        model_name=modelo,
        system_instruction=EDITORIAL_SYSTEM_PROMPT,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.45,
            "max_output_tokens": 2048,
        },
    )

    payload_usuario = {
        "candidatos_rss": [
            {
                "fonte": c.get("fonte", ""),
                "titulo": c.get("titulo", ""),
                "resumo": c.get("resumo", ""),
                "url": c.get("url", ""),
                "publicado_em": c.get("publicado_em", ""),
            }
            for c in candidatos[:15]
        ],
        "ofertas_do_dia": ofertas_resumo or [],
    }
    prompt = (
        "Escolha EXATAMENTE 1 pauta editorial entre os candidatos abaixo seguindo todas as regras "
        "do sistema e devolva o JSON estruturado:\n\n"
        + json.dumps(payload_usuario, ensure_ascii=False, indent=2)
    )
    resp = model.generate_content(prompt)
    return str(getattr(resp, "text", "") or "")


def parsear_resposta_editorial(raw_text, candidatos, ofertas_rodada=None):
    """Valida JSON editorial do Gemini, garante crédito 'Via [Fonte]', zero URLs no X e match real de oferta."""
    limpo = str(raw_text or "").strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo).strip()

    if not limpo:
        return None

    try:
        dados = json.loads(limpo)
    except json.JSONDecodeError:
        ini, fim = limpo.find("{"), limpo.rfind("}")
        if ini == -1 or fim <= ini:
            return None
        try:
            dados = json.loads(limpo[ini:fim + 1])
        except json.JSONDecodeError:
            return None

    if not isinstance(dados, dict) or not candidatos:
        return None

    url_esc = str(dados.get("url_escolhida") or "").strip()
    titulo_esc = str(dados.get("titulo_original") or "").strip().lower()

    candidato_ref = next(
        (c for c in candidatos if str(c.get("url", "")).strip() == url_esc),
        None,
    )
    if candidato_ref is None and titulo_esc:
        candidato_ref = next(
            (c for c in candidatos if str(c.get("titulo", "")).strip().lower() == titulo_esc),
            None,
        )
    if candidato_ref is None:
        return None

    fonte = str(candidato_ref.get("fonte") or dados.get("fonte") or "Redação Tech").strip()
    titulo_orig = str(candidato_ref.get("titulo") or dados.get("titulo_original") or "").strip()
    url_real = str(candidato_ref.get("url")).strip()
    tema_norm = storage_db.normalizar_tema(dados.get("tema_normalizado") or titulo_orig)

    credito_tag = f"Via {fonte}"

    def _garantir_credito(txt):
        base = str(txt or "").strip()
        if not base:
            return f"{titulo_orig}\n\n{credito_tag}"
        if f"via {fonte.lower()}" not in base.lower():
            return f"{base}\n\n{credito_tag}"
        return base

    texto_x = sanitizar_texto_sem_urls(dados.get("texto_x") or f"{titulo_orig} — {credito_tag}", max_chars=260)
    texto_threads = _garantir_credito(dados.get("texto_threads"))[:495]
    texto_facebook = sanitizar_texto_sem_urls(_garantir_credito(dados.get("texto_facebook")))
    texto_telegram = _garantir_credito(dados.get("texto_telegram"))

    tem_match = bool(dados.get("tem_match_oferta", False))
    sku_rel = str(dados.get("sku_oferta_relacionada") or "").strip()
    url_oferta_comentario = None
    if tem_match and sku_rel and ofertas_rodada:
        oferta = next(
            (op for op in ofertas_rodada if str(op.get("sku_selecionado", "")).strip() == sku_rel),
            None,
        )
        if oferta and oferta.get("url_afiliado"):
            url_oferta_comentario = str(oferta["url_afiliado"]).strip()
        else:
            tem_match = False
            sku_rel = ""
    else:
        tem_match = False
        sku_rel = ""

    return {
        "url_escolhida": url_real,
        "fonte": fonte,
        "titulo_original": titulo_orig,
        "tema_normalizado": tema_norm,
        "tem_match_oferta": tem_match,
        "sku_oferta_relacionada": sku_rel,
        "url_oferta_comentario": url_oferta_comentario,
        "texto_x": texto_x,
        "texto_threads": texto_threads,
        "texto_facebook": texto_facebook,
        "texto_telegram": texto_telegram,
    }


def publicar_editorial_x(texto_x):
    """Publica pauta editorial no X em modo econômico (garantindo zero URLs)."""
    if not TWEEPY_DISPONIVEL or tweepy is None:
        return False
    creds = [
        os.getenv("X_API_KEY"),
        os.getenv("X_API_SECRET"),
        os.getenv("X_ACCESS_TOKEN"),
        os.getenv("X_ACCESS_TOKEN_SECRET"),
    ]
    if not all(creds):
        return False

    texto_limpo = sanitizar_texto_sem_urls(texto_x, max_chars=275)
    if not texto_limpo:
        return False
    try:
        client = tweepy.Client(
            consumer_key=creds[0],
            consumer_secret=creds[1],
            access_token=creds[2],
            access_token_secret=creds[3],
        )
        client.create_tweet(text=texto_limpo)
        logging.info("🐦 Pauta editorial publicada no X (zero URLs)!")
        return True
    except Exception as exc:
        logging.warning(f"Falha ao publicar editorial no X: {exc}")
        return False


def publicar_editorial_threads(texto_threads):
    """Publica pauta editorial em formato texto no Threads (100% gratuito)."""
    access_token = os.getenv("THREADS_ACCESS_TOKEN")
    if not access_token or not str(texto_threads or "").strip():
        return False
    try:
        user_id = os.getenv("THREADS_USER_ID")
        if not user_id:
            me_r = requests.get(
                "https://graph.threads.net/v1.0/me",
                params={"fields": "id", "access_token": access_token},
                timeout=12,
            )
            if me_r.status_code != 200:
                return False
            user_id = me_r.json().get("id")
        if not user_id:
            return False

        r_c = requests.post(
            f"https://graph.threads.net/v1.0/{user_id}/threads",
            data={"media_type": "TEXT", "text": texto_threads[:495], "access_token": access_token},
            timeout=15,
        )
        if r_c.status_code != 200 or not r_c.json().get("id"):
            return False
        creation_id = r_c.json()["id"]
        time.sleep(2)
        r_p = requests.post(
            f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
            data={"creation_id": creation_id, "access_token": access_token},
            timeout=15,
        )
        if r_p.status_code == 200:
            logging.info("🧵 Pauta editorial publicada no Threads!")
            return True
    except Exception as exc:
        logging.warning(f"Falha ao publicar editorial no Threads: {exc}")
    return False


def publicar_editorial_facebook(texto_facebook, url_oferta_comentario=None):
    """
    Publica pauta editorial na Página Gamestore (sem link no post principal).
    Se houver match real de oferta, publica o link de afiliado no 1º comentário.
    """
    page_token = os.getenv("FACEBOOK_PAGE_TOKEN")
    if not page_token or not str(texto_facebook or "").strip():
        return False

    page_id = os.getenv("FACEBOOK_PAGE_ID")
    try:
        acc_r = requests.get(
            "https://graph.facebook.com/v21.0/me/accounts",
            params={"fields": "id,name,access_token", "access_token": page_token},
            timeout=12,
        )
        if acc_r.status_code == 200:
            paginas = acc_r.json().get("data", [])
            if paginas:
                esc = next((p for p in paginas if page_id and str(p.get("id")) == str(page_id)), paginas[0])
                page_id = esc.get("id")
                if esc.get("access_token"):
                    page_token = esc["access_token"]
    except Exception:
        pass

    if not page_id:
        try:
            me_r = requests.get(
                "https://graph.facebook.com/v21.0/me",
                params={"fields": "id", "access_token": page_token},
                timeout=12,
            )
            if me_r.status_code == 200:
                page_id = me_r.json().get("id")
        except Exception:
            return False

    if not page_id:
        return False

    try:
        texto_limpo = sanitizar_texto_sem_urls(texto_facebook)
        resp_feed = requests.post(
            f"https://graph.facebook.com/v21.0/{page_id}/feed",
            data={"message": texto_limpo, "access_token": page_token},
            timeout=15,
        )
        if resp_feed.status_code != 200:
            logging.warning(f"Facebook editorial /feed falhou ({resp_feed.status_code}): {resp_feed.text}")
            return False
        post_id = resp_feed.json().get("id")
        logging.info(f"📘 Pauta editorial publicada na Página Facebook (post_id: {post_id})!")

        if post_id and url_oferta_comentario:
            time.sleep(2)
            requests.post(
                f"https://graph.facebook.com/v21.0/{post_id}/comments",
                data={
                    "message": f"🛒 Oferta relacionada citada na pauta: {url_oferta_comentario}",
                    "access_token": page_token,
                },
                timeout=12,
            )
        return True
    except Exception as exc:
        logging.warning(f"Falha ao publicar editorial no Facebook: {exc}")
        return False


def publicar_editorial_telegram(texto_telegram, url_oferta=None):
    """Publica editorial no Telegram APENAS quando EDITORIAL_TELEGRAM_ENABLED=true."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id or not str(texto_telegram or "").strip():
        return False
    payload = {
        "chat_id": chat_id,
        "text": f"📰 <b>GIRO GAMESTORE</b>\n\n{texto_telegram}",
        "parse_mode": "HTML",
    }
    if url_oferta:
        payload["reply_markup"] = json.dumps(
            {"inline_keyboard": [[{"text": "🛒 VER OFERTA RELACIONADA", "url": url_oferta}]]}
        )
    try:
        resp = requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", data=payload, timeout=12)
        if resp.status_code == 200:
            logging.info("📢 Pauta editorial publicada no Telegram!")
            return True
    except Exception as exc:
        logging.warning(f"Falha ao publicar editorial no Telegram: {exc}")
    return False


def executar_bloco_editorial(
    conn,
    oportunidades_dict=None,
    ofertas_selecionadas=None,
    forcar_execucao=False,
    agora=None,
    fetcher=None,
    gerador_ia=None,
    publicadores=None,
):
    """
    Orquestra o motor editorial diário (15h BRT ou --run-editorial) em modo 100% isolado:
    nenhuma exceção é propagada para o fluxo principal de ofertas.
    """
    try:
        executar, motivo = deve_executar_editorial(forcar_execucao=forcar_execucao, agora=agora)
        if not executar:
            logging.info(f"📰 Editorial RSS ignorado nesta rodada: {motivo}.")
            return {"executado": False, "motivo": motivo, "canais": []}

        if not forcar_execucao and editorial_ja_publicado_hoje(conn, agora=agora):
            logging.info("📰 Editorial RSS já publicado hoje no SQLite. Pulando duplicação.")
            return {"executado": False, "motivo": "ja_publicado_hoje", "canais": []}

        agora_utc = agora.astimezone(timezone.utc) if isinstance(agora, datetime) and agora.tzinfo else None
        noticias = coletar_noticias_rss(horas=24, agora_utc=agora_utc, fetcher=fetcher)
        if not noticias:
            return {"executado": False, "motivo": "sem_noticias_24h", "canais": []}

        ineditas = filtrar_pautas_ineditas(conn, noticias, dias=7, agora=agora_brt(agora).replace(tzinfo=None))
        if not ineditas:
            logging.info("📰 Nenhuma pauta RSS inédita nos últimos 7 dias.")
            return {"executado": False, "motivo": "sem_pautas_ineditas_7d", "canais": []}

        ofertas_lista = (
            list(ofertas_selecionadas)
            if ofertas_selecionadas is not None
            else list((oportunidades_dict or {}).get("oportunidades", []))
        )
        ofertas_resumo = _resumir_ofertas_para_editorial({"oportunidades": ofertas_lista}, limite=10)

        raw_ia = (
            gerador_ia(ineditas, ofertas_resumo)
            if gerador_ia is not None
            else gerar_pauta_editorial_gemini(ineditas, ofertas_resumo=ofertas_resumo)
        )
        pauta = parsear_resposta_editorial(raw_ia, candidatos=ineditas, ofertas_rodada=ofertas_lista)
        if not pauta:
            logging.warning("⚠️ Editorial RSS: Gemini não retornou pauta válida. Abortando sem erro.")
            return {"executado": False, "motivo": "resposta_editorial_invalida", "canais": []}

        pubs = publicadores or {}
        fn_x = pubs.get("x", publicar_editorial_x)
        fn_th = pubs.get("threads", publicar_editorial_threads)
        fn_fb = pubs.get("facebook", publicar_editorial_facebook)
        fn_tg = pubs.get("telegram", publicar_editorial_telegram)

        canais_ok = []
        if fn_x(pauta["texto_x"]):
            canais_ok.append("x")
        if fn_th(pauta["texto_threads"]):
            canais_ok.append("threads")
        if fn_fb(pauta["texto_facebook"], url_oferta_comentario=pauta.get("url_oferta_comentario")):
            canais_ok.append("facebook")
        if _env_bool("EDITORIAL_TELEGRAM_ENABLED", default=False):
            if fn_tg(pauta["texto_telegram"], url_oferta=pauta.get("url_oferta_comentario")):
                canais_ok.append("telegram")

        if canais_ok:
            storage_db.registrar_pauta_rss(
                conn,
                url=pauta["url_escolhida"],
                fonte=pauta["fonte"],
                titulo=pauta["titulo_original"],
                tema_normalizado=pauta["tema_normalizado"],
                canais_postados=",".join(canais_ok),
                publicado_em=agora_brt(agora).replace(tzinfo=None).isoformat(),
            )

        return {
            "executado": True,
            "motivo": motivo,
            "fonte": pauta["fonte"],
            "titulo": pauta["titulo_original"],
            "tem_match_oferta": pauta["tem_match_oferta"],
            "canais": canais_ok,
        }
    except Exception as exc:
        logging.warning(f"⚠️ Erro isolado no motor editorial RSS: {exc}")
        return {"executado": False, "motivo": f"erro_isolado: {exc}", "canais": []}
