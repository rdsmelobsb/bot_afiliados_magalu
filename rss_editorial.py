from email.utils import parsedate_to_datetime
from html import unescape
from io import BytesIO
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

import requests

try:
    from PIL import Image
    PILLOW_DISPONIVEL = True
except ImportError:
    Image = None
    PILLOW_DISPONIVEL = False

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
    "seus", "suas", "ao", "aos", "pelo", "pela", "via", "tem", "sao", "vai",
}

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_TME_RE = re.compile(r"\bt\.me/\S+", re.IGNORECASE)
_DOMINIO_SOLTO_RE = re.compile(
    r"(?<![@\w.-])\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|net|org|br|io|gg|tv|co|me|ly|app|tech)(?:\.[a-z]{2})?(?:/[^\s]*)?",
    re.IGNORECASE,
)

EDITORIAL_SYSTEM_PROMPT = """
Você é o Editor-Chefe de Hardware, Games & Tech do canal Gamestore / @promosgeektech.
Sua escrita segue padrão editorial humano rigoroso (zero cara de texto gerado por IA).

REGRAS OBRIGATÓRIAS DE COPY (ANTI-IA / HUMANIZER):
1. BANA CLICHÊS DE IA:
   - NUNCA comece com "Pensando em...", "Você sabia...", "No mundo atual...", "Com o avanço...", "Se você é gamer...".
   - PROIBIDO jargão corporativo/vazio: "consolidar a marca", "marcou o amadurecimento", "segmento mainstream", "cenário atual", "ecossistema", "revolucionar", "elevar o nível", "impulsionar".
   - PROIBIDO estruturas artificiais de IA: "Não é apenas X, é Y", "O resultado?", "A melhor parte:", listas de 3 negações ("Sem X, sem Y, sem Z").
   - PROIBIDO encerrar com frases genéricas como "Deixe sua opinião nos comentários!" ou "O que você acha?".
2. VOZ E RITMO HUMANO:
   - Escreva como um entusiasta brasileiro de hardware/games conversando direto com outro gamer no feed: claro, opinativo na medida certa, concreto e sem enrolação.
   - Alterne frases curtas com frases de contexto; use parágrafos curtos separados por linha em branco (`\\n\\n`).
3. ESTRUTURA EXATA DE `texto_facebook` E `texto_telegram` (300–450 caracteres):
   - Parágrafo 1: Gancho curto indo direto no fato principal (sem rodeios).
   - Parágrafo 2: 2–3 linhas objetivas explicando por que isso muda o jogo para o bolso, desempenho ou setup de quem compra hardware/jogos.
   - Parágrafo 3: Pergunta prática e provocativa de escolha real (ex: "Você arriscaria uma Intel ARC hoje ou ainda vai sem pensar em NVIDIA/AMD?").
   - Linha final isolada: `📰 Fonte: [Fonte]`
4. CAMPOS VISUAIS PARA CARD 4:5 E REEL NARRADOR (THALITA):
   - `headline_card`: manchete curta e de alto impacto para imagem (**MÁXIMO 8–9 PALAVRAS**).
   - `destaque_card`: 1 ou 2 palavras exatas da `headline_card` para destaque em cor neon.
   - `tag_categoria`: escolha entre `HARDWARE`, `GAMES` ou `TECH`.
   - `roteiro_reel`: fala natural, solta e direta (**35–45 palavras**, 15–20s) para a voz da Thalita narrar em áudio sem parecer leitura de enciclopédia. Sem links, emojis ou tags.
5. BLINDAGEM FACTUAL E PONTE CONDICIONAL DE OFERTA:
   - Escolha APENAS 1 (UMA) notícia entre os candidatos enviados, priorizando impacto prático em "bolso, setup e decisão de compra".
   - Nunca invente especificações, preços, datas ou porcentagens ausentes do título/resumo recebido.
   - Só defina `tem_match_oferta: true` e preencha `sku_oferta_relacionada` se houver correspondência DIRETA com alguma oferta da lista enviada; caso contrário, `tem_match_oferta: false` e zero menção a compras.
   - Facebook Gamestore NÃO leva link externo no corpo do texto principal.

FORMATO DE SAÍDA (JSON ESTRITO):
- Retorne APENAS um objeto JSON válido (nunca lista, nunca texto fora do JSON).
- Identifique a notícia escolhida obrigatoriamente pelo inteiro `noticia_id` (campo `id` de 1 a 30 enviado em `candidatos_rss`), sem precisar reescrever URLs longas.
{
  "noticia_id": 1,
  "fonte": "Nome da fonte escolhida",
  "titulo_original": "Título original da notícia",
  "tema_normalizado": "palavras chave principais sem acentos",
  "tag_categoria": "HARDWARE",
  "headline_card": "Manchete curta de até 8 palavras",
  "destaque_card": "1-2 palavras",
  "roteiro_reel": "Fala natural de 35 a 45 palavras para narração em voz alta.",
  "tem_match_oferta": false,
  "sku_oferta_relacionada": "",
  "texto_facebook": "Gancho curto.\n\nImpacto direto no bolso ou setup.\n\nPergunta de escolha real?\n\n📰 Fonte: Adrenaline",
  "texto_telegram": "Gancho curto.\n\nImpacto direto no bolso ou setup.\n\nPergunta de escolha real?\n\n📰 Fonte: Adrenaline"
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


def _validar_url_imagem(url_cand):
    u = str(url_cand or "").strip()
    if not u or u.startswith("data:"):
        return None
    if u.startswith("//"):
        u = f"https:{u}"
    if u.startswith("http"):
        return u
    return None


def extrair_imagem_entry_rss(entry):
    """Extrai URL de imagem de entries do feedparser/dict (media_content, enclosure, thumbnail ou <img>)."""
    is_dict = isinstance(entry, dict)
    if is_dict and entry.get("image_url"):
        ok = _validar_url_imagem(entry.get("image_url"))
        if ok:
            return ok

    # 1. media_content / media_thumbnail (padrão feedparser)
    for campo in ("media_content", "media_thumbnail"):
        val = entry.get(campo) if is_dict else getattr(entry, campo, None)
        if isinstance(val, list):
            for m in val:
                url_m = m.get("url") if isinstance(m, dict) else getattr(m, "url", None)
                ok = _validar_url_imagem(url_m)
                if ok:
                    return ok

    # 2. enclosures / links de imagem
    for campo in ("enclosures", "links"):
        val = entry.get(campo) if is_dict else getattr(entry, campo, None)
        if isinstance(val, list):
            for item in val:
                tipo = str(item.get("type", "") if isinstance(item, dict) else getattr(item, "type", "")).lower()
                href = item.get("href") or item.get("url") if isinstance(item, dict) else (getattr(item, "href", None) or getattr(item, "url", None))
                if ("image" in tipo or str(href or "").lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp"))):
                    ok = _validar_url_imagem(href)
                    if ok:
                        return ok

    # 3. <img src="..."> dentro de summary/description/content
    textos_html = []
    for campo in ("summary", "description"):
        v = entry.get(campo) if is_dict else getattr(entry, campo, None)
        if v:
            textos_html.append(str(v))
    content_val = entry.get("content") if is_dict else getattr(entry, "content", None)
    if isinstance(content_val, list):
        for c in content_val:
            c_txt = c.get("value") if isinstance(c, dict) else getattr(c, "value", None)
            if c_txt:
                textos_html.append(str(c_txt))

    for html_frag in textos_html:
        m = re.search(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', html_frag, re.IGNORECASE)
        if m:
            ok = _validar_url_imagem(unescape(m.group(1)))
            if ok:
                return ok

    return None


def extrair_og_image_pagina(url, timeout=6):
    """Fallback seguro: busca <meta property='og:image'> na URL da notícia."""
    if not url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        html_txt = resp.text[:120000]
        padroes = (
            r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
            r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
        )
        for pat in padroes:
            m = re.search(pat, html_txt, re.IGNORECASE)
            if m:
                ok = _validar_url_imagem(unescape(m.group(1)))
                if ok:
                    return ok
    except Exception as exc:
        logging.debug(f"Falha ao extrair og:image de {url}: {exc}")
    return None


def baixar_imagem_editorial_bytes(imagem_url, timeout=10):
    """Baixa foto da notícia e normaliza para JPEG em memória via Pillow."""
    if not imagem_url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/jpeg,image/png,*/*;q=0.8",
    }
    try:
        resp = requests.get(imagem_url, headers=headers, timeout=timeout)
        if resp.status_code != 200 or len(resp.content) < 1000:
            return None
        raw = resp.content
        if PILLOW_DISPONIVEL and Image is not None:
            im = Image.open(BytesIO(raw))
            if im.mode in ("RGBA", "LA", "P"):
                fundo = Image.new("RGB", im.size, (10, 11, 14))
                if im.mode == "P":
                    im = im.convert("RGBA")
                fundo.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                im = fundo
            else:
                im = im.convert("RGB")
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=92)
            return buf.getvalue()
        return raw
    except Exception as exc:
        logging.warning(f"Não foi possível baixar imagem da notícia ({imagem_url}): {exc}")
        return None


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
    """Parser fallback em stdlib ElementTree (captura também media:content/enclosure)."""
    entries = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return entries

    media_ns = "{http://search.yahoo.com/mrss/}"

    for item in root.findall(".//item"):
        img_url = None
        for tag_img in (f"{media_ns}content", f"{media_ns}thumbnail", "enclosure"):
            el = item.find(tag_img)
            if el is not None:
                cand = el.attrib.get("url")
                if tag_img == "enclosure" and "image" not in str(el.attrib.get("type", "")).lower():
                    cand = None
                img_url = _validar_url_imagem(cand)
                if img_url:
                    break
        summary = (item.findtext("description") or "").strip()
        if not img_url and summary:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.IGNORECASE)
            if m:
                img_url = _validar_url_imagem(unescape(m.group(1)))

        entries.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "summary": summary,
            "published": (item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip(),
            "image_url": img_url,
        })

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
                "image_url": None,
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
                    "imagem_url": extrair_imagem_entry_rss(entry),
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


def selecionar_candidatos_balanceados(candidatos, limite=30):
    """Seleciona até `limite` notícias recentes balanceadas por round-robin entre os feeds."""
    if not candidatos or len(candidatos) <= int(limite):
        return list(candidatos or [])

    ordenados = sorted(candidatos, key=lambda c: str(c.get("publicado_em", "")), reverse=True)
    grupos = {}
    ordem_fontes = []
    for item in ordenados:
        fonte = str(item.get("fonte") or "Outros")
        if fonte not in grupos:
            grupos[fonte] = []
            ordem_fontes.append(fonte)
        grupos[fonte].append(item)

    selecionados = []
    idx = 0
    while len(selecionados) < int(limite):
        adicionou = False
        for fonte in ordem_fontes:
            lista_f = grupos[fonte]
            if idx < len(lista_f):
                selecionados.append(lista_f[idx])
                adicionou = True
                if len(selecionados) >= int(limite):
                    break
        if not adicionou:
            break
        idx += 1
    return selecionados


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
    """Remove qualquer URL, t.me/... ou domínio solto para manter posts limpos sem links no corpo."""
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


def _extrair_texto_resposta_gemini_editorial(resp):
    """Extrai (texto, finish_reason) com segurança de objetos GenerateContentResponse."""
    finish_reason = None
    partes = []
    try:
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            cand0 = candidates[0]
            finish_reason = getattr(cand0, "finish_reason", None)
            content = getattr(cand0, "content", None)
            for part in getattr(content, "parts", None) or []:
                txt_part = getattr(part, "text", None)
                if txt_part:
                    partes.append(str(txt_part))
    except Exception:
        pass

    if partes:
        return "".join(partes), finish_reason

    try:
        texto = str(getattr(resp, "text", "") or "")
    except Exception:
        texto = ""
    return texto, finish_reason


def _logar_rejeicao_editorial(motivo, raw_text, finish_reason=None):
    """Registra motivo exato da rejeição e snippets da resposta bruta para diagnóstico real."""
    bruto = str(raw_text or "")
    inicio = bruto[:400]
    fim = bruto[-200:] if len(bruto) > 400 else ""
    logging.warning(
        f"⚠️ Editorial RSS rejeitado: motivo={motivo} | finish_reason={finish_reason} | "
        f"chars={len(bruto)} | inicio={inicio!r} | fim={fim!r}"
    )


def gerar_pauta_editorial_gemini(
    candidatos,
    ofertas_resumo=None,
    model_name=None,
    limite_candidatos=30,
    reforco_json=False,
    retornar_meta=False,
):
    """Chama o Gemini enviando até 30 notícias balanceadas com ID numérico curto para curadoria + copy."""
    if not GENAI_DISPONIVEL or genai is None:
        raise RuntimeError("Biblioteca 'google-generativeai' indisponível.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY ausente para curadoria editorial.")

    selecionados = selecionar_candidatos_balanceados(candidatos, limite=limite_candidatos)
    genai.configure(api_key=api_key)
    modelo = model_name or os.getenv("GEMINI_MODEL", "gemini-4-hydrogen")
    model = genai.GenerativeModel(
        model_name=modelo,
        system_instruction=EDITORIAL_SYSTEM_PROMPT,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.55 if not reforco_json else 0.35,
            "max_output_tokens": 4096,
        },
    )

    candidatos_payload = []
    for idx, c in enumerate(selecionados, start=1):
        try:
            nid = int(c.get("id")) if c.get("id") is not None else idx
        except (TypeError, ValueError):
            nid = idx
        candidatos_payload.append({
            "id": nid,
            "fonte": c.get("fonte", ""),
            "titulo": c.get("titulo", ""),
            "resumo": c.get("resumo", ""),
            "publicado_em": c.get("publicado_em", ""),
        })

    payload_usuario = {
        "candidatos_rss": candidatos_payload,
        "ofertas_do_dia": ofertas_resumo or [],
    }
    instrucao_base = (
        "Escolha EXATAMENTE 1 pauta editorial entre os candidatos abaixo seguindo todas as regras "
        "do sistema e devolva APENAS o objeto JSON estruturado informando `noticia_id` (int de 1 a "
        f"{len(candidatos_payload)}):"
    )
    if reforco_json:
        instrucao_base = (
            "ATENÇÃO (RETRY): sua resposta anterior falhou no parser JSON. "
            "Devolva ESTRITAMENTE um único objeto JSON válido (sem markdown, sem comentários, sem lista) "
            "contendo `noticia_id` (inteiro válido da lista), `texto_facebook`, `texto_telegram`, "
            "`headline_card`, `destaque_card` e `roteiro_reel`.\n\n" + instrucao_base
        )

    prompt = instrucao_base + "\n\n" + json.dumps(payload_usuario, ensure_ascii=False, indent=2)
    resp = model.generate_content(prompt)
    texto, finish_reason = _extrair_texto_resposta_gemini_editorial(resp)
    logging.info(f"🧠 Gemini editorial: finish_reason={finish_reason} | chars={len(texto)}")
    if retornar_meta:
        return texto, finish_reason
    return texto


def _extrair_noticia_id_int(valor):
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    txt = str(valor).strip()
    if txt.isdigit():
        return int(txt)
    m = re.search(r"\d+", txt)
    if m and txt == m.group(0):
        return int(m.group(0))
    return None


def _derivar_headline_curta(titulo_orig, max_palavras=9):
    palavras = str(titulo_orig or "").strip().split()
    return " ".join(palavras[:max_palavras]).strip()


def _validar_destaque_na_headline(destaque_card, headline_card):
    destaque = str(destaque_card or "").strip()
    if not destaque or not headline_card:
        return ""
    tokens_hl = set(re.findall(r"[a-z0-9à-ÿ]+", headline_card.lower()))
    tokens_dest = [t for t in re.findall(r"[a-z0-9à-ÿ]+", destaque.lower()) if len(t) >= 2]
    if tokens_dest and any(tok in tokens_hl for tok in tokens_dest):
        return destaque
    if destaque.lower() in headline_card.lower():
        return destaque
    return ""


def parsear_resposta_editorial(raw_text, candidatos, ofertas_rodada=None, finish_reason=None):
    """
    Valida JSON editorial do Gemini com seleção preferencial por `noticia_id`,
    logs diagnósticos detalhados e fallbacks por campo (sem descartar tudo por detalhe).
    """
    limpo = str(raw_text or "").strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo).strip()

    if not limpo:
        _logar_rejeicao_editorial("resposta_vazia", raw_text, finish_reason=finish_reason)
        return None

    if not candidatos:
        _logar_rejeicao_editorial("candidatos_vazios", raw_text, finish_reason=finish_reason)
        return None

    dados = None
    erro_json = None
    try:
        dados = json.loads(limpo)
    except json.JSONDecodeError as exc:
        erro_json = exc
        ini_obj, fim_obj = limpo.find("{"), limpo.rfind("}")
        ini_arr, fim_arr = limpo.find("["), limpo.rfind("]")
        trecho = None
        if ini_arr != -1 and fim_arr > ini_arr and (ini_obj == -1 or ini_arr < ini_obj):
            trecho = limpo[ini_arr:fim_arr + 1]
        elif ini_obj != -1 and fim_obj > ini_obj:
            trecho = limpo[ini_obj:fim_obj + 1]

        if trecho:
            try:
                dados = json.loads(trecho)
                erro_json = None
            except json.JSONDecodeError as exc2:
                erro_json = exc2

    if erro_json is not None or dados is None:
        _logar_rejeicao_editorial(f"json_invalido ({erro_json})", raw_text, finish_reason=finish_reason)
        return None

    if isinstance(dados, list):
        if len(dados) >= 1 and isinstance(dados[0], dict):
            dados = dados[0]
        else:
            _logar_rejeicao_editorial("estrutura_lista_vazia_ou_invalida", raw_text, finish_reason=finish_reason)
            return None

    if not isinstance(dados, dict):
        _logar_rejeicao_editorial(
            f"estrutura_nao_dict ({type(dados).__name__})", raw_text, finish_reason=finish_reason
        )
        return None

    # 1. Match determinístico por noticia_id (prioritário)
    candidato_ref = None
    nid = _extrair_noticia_id_int(dados.get("noticia_id"))
    if nid is not None:
        candidato_ref = next(
            (c for c in candidatos if _extrair_noticia_id_int(c.get("id")) == nid),
            None,
        )
        if candidato_ref is None and 1 <= nid <= len(candidatos):
            candidato_ref = candidatos[nid - 1]

    # 2. Fallback por url_escolhida (exata, normalizada ou hash)
    url_esc = str(dados.get("url_escolhida") or "").strip()
    if candidato_ref is None and url_esc:
        url_esc_norm = url_esc.rstrip("/").lower()
        url_esc_hash = storage_db.gerar_url_hash(url_esc)
        candidato_ref = next(
            (
                c for c in candidatos
                if str(c.get("url", "")).strip() == url_esc
                or str(c.get("url", "")).strip().rstrip("/").lower() == url_esc_norm
                or storage_db.gerar_url_hash(str(c.get("url", "")).strip()) == url_esc_hash
            ),
            None,
        )

    # 3. Fallback por titulo_original
    titulo_esc = str(dados.get("titulo_original") or "").strip().lower()
    if candidato_ref is None and titulo_esc:
        candidato_ref = next(
            (c for c in candidatos if str(c.get("titulo", "")).strip().lower() == titulo_esc),
            None,
        )

    if candidato_ref is None:
        _logar_rejeicao_editorial(
            f"noticia_nao_encontrada (noticia_id={dados.get('noticia_id')!r}, url_escolhida={url_esc[:120]!r})",
            raw_text,
            finish_reason=finish_reason,
        )
        return None

    fonte = str(candidato_ref.get("fonte") or dados.get("fonte") or "Redação Tech").strip()
    titulo_orig = str(candidato_ref.get("titulo") or dados.get("titulo_original") or "").strip()
    url_real = str(candidato_ref.get("url") or "").strip()
    tema_norm = storage_db.normalizar_tema(dados.get("tema_normalizado") or titulo_orig)

    # Fallbacks por campo: nunca descartar a pauta por campos secundários
    headline_bruta = str(dados.get("headline_card") or "").strip()
    headline_card = _derivar_headline_curta(headline_bruta or titulo_orig, max_palavras=9)
    destaque_card = _validar_destaque_na_headline(dados.get("destaque_card"), headline_card)
    tag_categoria = str(dados.get("tag_categoria") or "TECH").strip().upper()[:16] or "TECH"
    roteiro_reel = re.sub(r"\s+", " ", str(dados.get("roteiro_reel") or "")).strip()

    rodape_fonte = f"📰 Fonte: {fonte}"

    def _garantir_rodape_fonte(txt):
        base = sanitizar_texto_sem_urls(str(txt or "").strip())
        if not base:
            return ""
        if f"fonte: {fonte.lower()}" not in base.lower() and f"via {fonte.lower()}" not in base.lower():
            return f"{base}\n\n{rodape_fonte}"
        return base

    fb_limpo = _garantir_rodape_fonte(dados.get("texto_facebook"))
    tg_limpo = _garantir_rodape_fonte(dados.get("texto_telegram"))
    if not fb_limpo and tg_limpo:
        fb_limpo = tg_limpo
    if not tg_limpo and fb_limpo:
        tg_limpo = fb_limpo

    if not fb_limpo and not tg_limpo:
        _logar_rejeicao_editorial("sem_texto_editorial", raw_text, finish_reason=finish_reason)
        return None

    texto_facebook = fb_limpo
    texto_telegram = tg_limpo
    texto_x = sanitizar_texto_sem_urls(dados.get("texto_x") or f"{headline_card} — Via {fonte}", max_chars=260)
    texto_threads = sanitizar_texto_sem_urls(dados.get("texto_threads") or texto_facebook, max_chars=495)

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
        "noticia_id": _extrair_noticia_id_int(candidato_ref.get("id")) or nid,
        "url_escolhida": url_real,
        "fonte": fonte,
        "titulo_original": titulo_orig,
        "tema_normalizado": tema_norm,
        "imagem_url": candidato_ref.get("imagem_url"),
        "tag_categoria": tag_categoria,
        "headline_card": headline_card,
        "destaque_card": destaque_card,
        "roteiro_reel": roteiro_reel,
        "tem_match_oferta": tem_match,
        "sku_oferta_relacionada": sku_rel,
        "url_oferta_comentario": url_oferta_comentario,
        "texto_x": texto_x,
        "texto_threads": texto_threads,
        "texto_facebook": texto_facebook,
        "texto_telegram": texto_telegram,
    }


def _resolver_facebook_page_auth():
    """Resolve (page_id, page_token) convertendo User Token via /me/accounts se necessário."""
    page_token = os.getenv("FACEBOOK_PAGE_TOKEN")
    if not page_token:
        return None, None

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
            return None, None

    return page_id, page_token


def publicar_editorial_x(texto_x):
    """Desativado por padrão (X_ENABLED=false) por ser conta pessoal."""
    if not _env_bool("X_ENABLED", default=False):
        return False
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
        return True
    except Exception as exc:
        logging.warning(f"Falha ao publicar editorial no X: {exc}")
        return False


def publicar_editorial_threads(texto_threads):
    """Desativado por padrão (THREADS_ENABLED=false) por ser conta pessoal."""
    if not _env_bool("THREADS_ENABLED", default=False):
        return False
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
        return r_p.status_code == 200
    except Exception as exc:
        logging.warning(f"Falha ao publicar editorial no Threads: {exc}")
        return False


def publicar_editorial_facebook(texto_facebook, card_path=None, url_oferta_comentario=None):
    """
    Publica Card 4:5 editorial na Página Gamestore (/{page_id}/photos) sem link no texto.
    Se houver match real de oferta, publica o link de afiliado no 1º comentário.
    """
    page_id, page_token = _resolver_facebook_page_auth()
    if not page_id or not page_token or not str(texto_facebook or "").strip():
        return False

    texto_limpo = sanitizar_texto_sem_urls(texto_facebook)
    post_id = None

    if card_path and os.path.exists(card_path):
        try:
            with open(card_path, "rb") as f_img:
                img_bytes = f_img.read()
            resp_photo = requests.post(
                f"https://graph.facebook.com/v21.0/{page_id}/photos",
                data={
                    "caption": texto_limpo,
                    "published": "true",
                    "access_token": page_token,
                },
                files={"source": ("card_editorial_rss.jpg", img_bytes, "image/jpeg")},
                timeout=20,
            )
            if resp_photo.status_code == 200:
                dp = resp_photo.json()
                post_id = dp.get("post_id") or dp.get("id")
                logging.info(f"📘 Card 4:5 editorial publicado no Facebook Gamestore (post_id: {post_id})!")
            else:
                logging.warning(f"Facebook editorial /photos falhou ({resp_photo.status_code}), tentando /feed.")
        except Exception as exc:
            logging.warning(f"Erro ao subir card editorial no Facebook: {exc}")

    if not post_id:
        try:
            resp_feed = requests.post(
                f"https://graph.facebook.com/v21.0/{page_id}/feed",
                data={"message": texto_limpo, "access_token": page_token},
                timeout=15,
            )
            if resp_feed.status_code != 200:
                logging.warning(f"Facebook editorial /feed falhou ({resp_feed.status_code}): {resp_feed.text}")
                return False
            post_id = resp_feed.json().get("id")
            logging.info(f"📘 Pauta editorial publicada no /feed Facebook (post_id: {post_id})!")
        except Exception as exc:
            logging.warning(f"Falha ao publicar editorial no Facebook: {exc}")
            return False

    if post_id and url_oferta_comentario:
        time.sleep(2)
        try:
            requests.post(
                f"https://graph.facebook.com/v21.0/{post_id}/comments",
                data={
                    "message": f"🛒 Oferta relacionada citada na pauta: {url_oferta_comentario}",
                    "access_token": page_token,
                },
                timeout=12,
            )
        except Exception:
            pass
    return True


def publicar_reel_editorial_facebook(mp4_path, texto_facebook, url_oferta_comentario=None):
    """Publica o Reel Editorial 9:16 (HyperFrames + Thalita) na Página Gamestore."""
    if not mp4_path or not os.path.exists(mp4_path):
        return False
    page_id, page_token = _resolver_facebook_page_auth()
    if not page_id or not page_token:
        return False

    try:
        r_start = requests.post(
            f"https://graph.facebook.com/v21.0/{page_id}/video_reels",
            data={"upload_phase": "start", "access_token": page_token},
            timeout=15,
        )
        if r_start.status_code != 200:
            logging.warning(f"Facebook Reel editorial start falhou ({r_start.status_code}): {r_start.text}")
            return False
        video_id = r_start.json().get("video_id")
        upload_url = r_start.json().get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{video_id}"

        with open(mp4_path, "rb") as f_mp4:
            mp4_bytes = f_mp4.read()
        r_up = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {page_token}",
                "offset": "0",
                "file_size": str(len(mp4_bytes)),
            },
            data=mp4_bytes,
            timeout=60,
        )
        if r_up.status_code != 200:
            logging.warning(f"Facebook Reel editorial upload falhou ({r_up.status_code}): {r_up.text}")
            return False

        r_fin = requests.post(
            f"https://graph.facebook.com/v21.0/{page_id}/video_reels",
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": sanitizar_texto_sem_urls(texto_facebook),
                "access_token": page_token,
            },
            timeout=25,
        )
        if r_fin.status_code == 200:
            logging.info(f"🎬 Reel Editorial publicado no Facebook Gamestore (video_id: {video_id})!")
            if video_id and url_oferta_comentario:
                time.sleep(3)
                try:
                    requests.post(
                        f"https://graph.facebook.com/v21.0/{video_id}/comments",
                        data={
                            "message": f"🛒 Oferta relacionada citada na pauta: {url_oferta_comentario}",
                            "access_token": page_token,
                        },
                        timeout=12,
                    )
                except Exception:
                    pass
            return True
        logging.warning(f"Facebook Reel editorial finish falhou ({r_fin.status_code}): {r_fin.text}")
    except Exception as exc:
        logging.warning(f"Exceção ao publicar Reel editorial no Facebook: {exc}")
    return False


def publicar_editorial_telegram(texto_telegram, card_path=None, url_oferta=None):
    """Publica o Card 4:5 editorial no canal do Telegram (@promosgeektech) via sendPhoto."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id or not str(texto_telegram or "").strip():
        return False

    legenda_html = f"📰 <b>GIRO GAMESTORE</b>\n\n{texto_telegram}"
    reply_markup = (
        json.dumps({"inline_keyboard": [[{"text": "🛒 VER OFERTA RELACIONADA", "url": url_oferta}]]})
        if url_oferta
        else None
    )

    if card_path and os.path.exists(card_path):
        try:
            with open(card_path, "rb") as f_img:
                img_bytes = f_img.read()
            data = {
                "chat_id": chat_id,
                "caption": legenda_html[:1020],
                "parse_mode": "HTML",
            }
            if reply_markup:
                data["reply_markup"] = reply_markup
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                data=data,
                files={"photo": ("card_editorial_rss.jpg", img_bytes, "image/jpeg")},
                timeout=15,
            )
            if resp.status_code == 200:
                logging.info("📢 Card 4:5 editorial publicado no Telegram!")
                return True
            logging.warning(f"Telegram editorial sendPhoto falhou ({resp.status_code}), tentando texto.")
        except Exception as exc:
            logging.warning(f"Erro ao subir card editorial no Telegram: {exc}")

    payload = {
        "chat_id": chat_id,
        "text": legenda_html,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", data=payload, timeout=12)
        if resp.status_code == 200:
            logging.info("📢 Pauta editorial publicada em texto no Telegram!")
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
      - Focado exclusivamente em Facebook (Gamestore) e Telegram (@promosgeektech).
      - X e Threads permanecem desligados por padrão (X_ENABLED=false, THREADS_ENABLED=false).
      - Gera Card 4:5 (1080x1350) + Reel 9:16 (HyperFrames + Thalita, isolado).
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

        candidatos_ia = [
            dict(c, id=idx)
            for idx, c in enumerate(selecionar_candidatos_balanceados(ineditas, limite=30), start=1)
        ]
        ofertas_lista = (
            list(ofertas_selecionadas)
            if ofertas_selecionadas is not None
            else list((oportunidades_dict or {}).get("oportunidades", []))
        )
        ofertas_resumo = _resumir_ofertas_para_editorial({"oportunidades": ofertas_lista}, limite=10)

        pauta = None
        for tentativa in range(1, 3):
            finish_reason = None
            if gerador_ia is not None:
                res_ia = gerador_ia(candidatos_ia, ofertas_resumo)
                if isinstance(res_ia, tuple) and len(res_ia) == 2:
                    raw_ia, finish_reason = res_ia
                else:
                    raw_ia = res_ia
            else:
                raw_ia, finish_reason = gerar_pauta_editorial_gemini(
                    candidatos_ia,
                    ofertas_resumo=ofertas_resumo,
                    reforco_json=(tentativa > 1),
                    retornar_meta=True,
                )

            pauta = parsear_resposta_editorial(
                raw_ia,
                candidatos=candidatos_ia,
                ofertas_rodada=ofertas_lista,
                finish_reason=finish_reason,
            )
            if pauta:
                break
            if tentativa == 1:
                logging.warning("⚠️ Editorial RSS: 1ª tentativa retornou pauta inválida. Executando retry automático (2/2)...")

        if not pauta:
            logging.warning("⚠️ Editorial RSS: Gemini não retornou pauta válida após 2 tentativas. Abortando sem erro.")
            return {"executado": False, "motivo": "resposta_editorial_invalida", "canais": []}

        # 1. Foto real da notícia (RSS -> fallback og:image) + bytes JPEG
        img_url = pauta.get("imagem_url") or extrair_og_image_pagina(pauta["url_escolhida"])
        img_bytes = baixar_imagem_editorial_bytes(img_url) if img_url else None

        # 2. Card 4:5 (1080x1350) sempre gerado (usa background dark se sem foto)
        card_path = None
        try:
            import media_generator
            card_path = media_generator.gerar_card_editorial_rss(
                headline_card=pauta["headline_card"],
                destaque_card=pauta["destaque_card"],
                tag_categoria=pauta["tag_categoria"],
                fonte=pauta["fonte"],
                img_bytes=img_bytes,
            )
        except Exception as card_err:
            logging.warning(f"Falha ao gerar Card 4:5 editorial: {card_err}")

        pubs = publicadores or {}
        fn_fb = pubs.get("facebook", publicar_editorial_facebook)
        fn_tg = pubs.get("telegram", publicar_editorial_telegram)
        fn_fb_reel = pubs.get("facebook_reel", publicar_reel_editorial_facebook)

        canais_ok = []
        if fn_fb(
            pauta["texto_facebook"],
            card_path=card_path,
            url_oferta_comentario=pauta.get("url_oferta_comentario"),
        ):
            canais_ok.append("facebook")

        if _env_bool("EDITORIAL_TELEGRAM_ENABLED", default=True):
            if fn_tg(
                pauta["texto_telegram"],
                card_path=card_path,
                url_oferta=pauta.get("url_oferta_comentario"),
            ):
                canais_ok.append("telegram")

        # X e Threads ficam desligados por padrão (somente se flag explicitamente true)
        if _env_bool("X_ENABLED", default=False):
            fn_x = pubs.get("x", publicar_editorial_x)
            if fn_x(pauta["texto_x"]):
                canais_ok.append("x")
        if _env_bool("THREADS_ENABLED", default=False):
            fn_th = pubs.get("threads", publicar_editorial_threads)
            if fn_th(pauta["texto_threads"]):
                canais_ok.append("threads")

        # 3. Reel 9:16 (HyperFrames + Thalita) completamente isolado — nunca bloqueia o Card 4:5
        reel_path = None
        if _env_bool("EDITORIAL_REEL_ENABLED", default=True):
            if not str(pauta.get("roteiro_reel") or "").strip():
                logging.info("🎬 Reel editorial pulado: roteiro_reel ausente (Card 4:5 preservado).")
            else:
                try:
                    fn_gen_reel = pubs.get("gerar_reel")
                    if fn_gen_reel is not None:
                        reel_path = fn_gen_reel(pauta, img_bytes)
                    else:
                        import media_generator
                        reel_path = media_generator.gerar_reel_editorial_rss(
                            headline_card=pauta["headline_card"],
                            destaque_card=pauta["destaque_card"],
                            tag_categoria=pauta["tag_categoria"],
                            fonte=pauta["fonte"],
                            roteiro_reel=pauta["roteiro_reel"],
                            img_bytes=img_bytes,
                        )
                    if reel_path and fn_fb_reel(
                        reel_path,
                        pauta["texto_facebook"],
                        url_oferta_comentario=pauta.get("url_oferta_comentario"),
                    ):
                        canais_ok.append("facebook_reel")
                except Exception as reel_err:
                    logging.warning(f"Falha isolada no Reel editorial RSS (Card 4:5 preservado): {reel_err}")

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
            "headline_card": pauta["headline_card"],
            "tem_match_oferta": pauta["tem_match_oferta"],
            "card_path": card_path,
            "reel_path": reel_path,
            "canais": canais_ok,
        }
    except Exception as exc:
        logging.warning(f"⚠️ Erro isolado no motor editorial RSS: {exc}")
        return {"executado": False, "motivo": f"erro_isolado: {exc}", "canais": []}
