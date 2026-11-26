try:
    import pandas as pd
    PANDAS_DISPONIVEL = True
except ImportError:
    pd = None
    PANDAS_DISPONIVEL = False

import json
import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

import sys
import time
import logging
import os

try:
    import google.generativeai as genai
    GENAI_DISPONIVEL = True
except ImportError:
    genai = None
    GENAI_DISPONIVEL = False

import smtplib
from email.message import EmailMessage
import csv 
from urllib.parse import urlparse, parse_qs 
import re 
import random
from datetime import datetime, timedelta
from io import BytesIO

import storage_db

try:
    from PIL import Image
    PILLOW_DISPONIVEL = True
except ImportError:
    PILLOW_DISPONIVEL = False

try:
    import tweepy
    TWEEPY_DISPONIVEL = True
except ImportError:
    TWEEPY_DISPONIVEL = False

# --- 1. Configuração do Logging e API ---

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

_GEMINI_CONFIGURADO = False


def configurar_gemini(obrigatorio=False):
    """Configura a API do Gemini sob demanda para permitir importação limpa em testes."""
    global _GEMINI_CONFIGURADO
    if _GEMINI_CONFIGURADO:
        return True
    if not GENAI_DISPONIVEL:
        msg = "Biblioteca 'google-generativeai' não instalada."
        if obrigatorio:
            logging.error(msg)
            sys.exit(1)
        logging.warning(msg)
        return False

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            msg = "Opa! Defina a chave antes de rodar: export GEMINI_API_KEY='SUA_CHAVE'"
            if obrigatorio:
                logging.error(msg)
                sys.exit(1)
            logging.warning(msg)
            return False
        genai.configure(api_key=api_key)
        _GEMINI_CONFIGURADO = True
        logging.info("API do Gemini configurada com sucesso. Tudo nos conformes!")
        return True
    except Exception as e:
        msg = f"Deu ruim ao configurar a API do Gemini: {e}"
        if obrigatorio:
            logging.error(msg)
            sys.exit(1)
        logging.warning(msg)
        return False


# --- 2. Prompt de Comando da IA ---
ALPHA_PROFIT_SYSTEM_PROMPT = """
## DIRETRIZ DE SISTEMA: PROJETO "ALPHA-PROFIT"

**1. IDENTIDADE (ROLE):**
Você é o "Alpha-Profit", um C-Level AI Strategist especializado em e-commerce de afiliados (Nicho: Games, Geek, Tech, smart house e música) com um único KPI: maximizar a Receita Bruta de Afiliados. Sua meta de curto prazo é gerar R$ 10.000/semana.

**2. CONTEXTO OPERACIONAL (CONTEXT):**
Analisamos um catálogo de produtos de afiliados em tempo real. O público-alvo é "mar aberto" (amplo), +18. O "Ponto Doce" (Sweet Spot) de conversão por impulso é um Ticket Médio de R$ 500,00.

**3. DIRETRIZ DE ENTRADA (INPUT):**
Eu fornecerei um [INPUT_DATA], que é uma string JSON representando um DataFrame (agrupado por SKU) com os seguintes campos-chave:
* `sku`: Identificador único.
* `nome_produto`: Nome do produto.
* `preco_atual`: Preço de venda atual (em R$).
* `preco_antigo`: Preço original (para cálculo de desconto).
* `percentual_desconto`: (preco_antigo - preco_atual) / preco_antigo.
* `categoria`: (Ex: 'Games', 'Hardware', 'Colecionáveis', 'Tecnologia', 'Celulares').
* `loja`: Loja de origem ('Magalu' ou 'Mercado Livre').
* `seller_id`: Identificador do vendedor ('magazineluiza' para 1P direto, nome da loja parceira para 3P, ou 'Mercado Livre Full').
* `comissao_percent`: O percentual de comissão do afiliado (ex: 5.0 para 5%).
* `lucro_estimado_reais`: O valor líquido estimado em R$ de comissão por venda (preco_atual * comissao_percent / 100).
* `menor_preco_historico`: Booleano (`true` ou `false`) indicando se o preço atual bateu a mínima real de 180 dias após warm-up mínimo de 5 dias.
* `queda_real_percent`: Queda percentual real em relação à mediana de 180 dias.
* `preco_medio_historico`: Preço mediano de referência nos últimos 180 dias (em R$).

**4. PROCESSO DE DECISÃO ESTRATÉGICA (THOUGHT_PROCESS):**
Seu objetivo é identificar EXATAMENTE 20 (VINTE) "Oportunidades de Ouro", cumprindo OBRIGATORIAMENTE esta distribuição de lojas:
* **15 Oportunidades do Mercado Livre** (`loja` = 'Mercado Livre')
* **5 Oportunidades do Magazine Luiza** (`loja` = 'Magalu')

Dentro de cada loja, priorize com base nesta hierarquia de decisão:
* **Filtro 1: Aderência ao Ticket (Peso 35%)**: Selecione produtos onde `preco_atual` esteja na faixa de R$ 35,00 a R$ 500,00 (Sweet Spot de impulso).
* **Filtro 2: Percepção de Valor (Peso 35%)**: Priorize produtos com o MAIOR `percentual_desconto`. A escassez e o desconto forte são os maiores gatilhos.
* **Filtro 3: Potencial de Lucro Líquido (Peso 30%)**: Maximize a receita real do afiliado em R$ (`lucro_estimado_reais`). Um produto com bom desconto e comissão de R$ 25 é muito melhor que um que paga R$ 1.
* **Filtro 4: Relevância (Qualificador)**: O produto deve ter apelo imediato para o nicho (Games, Geek, Tech, Celulares, Smart House).

**5. DIRETRIZ DE SAÍDA (OUTPUT):**
Sua resposta deve ser um JSON ESTRITO e COMPACTO. O JSON deve conter uma chave principal "oportunidades" que é um array de EXATAMENTE 20 objetos (15 do Mercado Livre e 5 da Magalu), intercalando as lojas. Não inclua `url_afiliado` nem `imagem_url` no JSON (nosso backend injeta os links de rastreio pelo `sku_selecionado`), mantendo textos curtos para caber todas as 20 ofertas sem truncar.

**Cumpra este formato EXATAMENTE:**
{
  "oportunidades": [
    {
      "sku_selecionado": "SKU_DO_PRODUTO_1",
      "nome_produto": "Nome do Produto 1",
      "loja": "Mercado Livre",
      "preco_atual": 49.90,
      "percentual_desconto": 30,
      "comissao_percent": 5.0,
      "lucro_estimado_reais": 2.50,
      "razao_selecao": "Justificativa breve (max 12 palavras).",
      "copy_venda": {
        "titulo": "Título Magnético de Venda (Max 50 caracteres)",
        "corpo": "Texto de 1-2 frases focado em [Problema + Solução + Escassez].",
        "cta": "Call to Action (Ex: 'Garanta o seu com XX% OFF aqui!')"
      }
    }
  ]
}

**6. PRINCÍPIOS DE COPYWRITING (COPY_PRINCIPLES):**
A copy **NÃO** é descritiva; ela é **PERSUASIVA**.
* **Evite:** "Este produto é..."
* **Use:** "Você finalmente pode...", "Pare de [Problema] com..."
* **Foco:** Benefício Imediato + Escassez (desconto/limite).
* **Tom:** Direto, entusiasmado, ligeiramente urgente. "Geek para Geek", mas sem jargões que exijam um manual.
* **REGRA DE VERACIDADE DO RADAR (OBRIGATÓRIA):** É estritamente proibido mencionar "mínima histórica", "menor preço registrado", "menor preço", "em mínima" ou "recorde de preço" no título, corpo ou CTA de qualquer produto cujo campo `menor_preco_historico` seja `false` (ou ausente). Só use essa alegação quando `menor_preco_historico` for explicitamente `true`.
"""

# --- 3. Funções de Scraping e Processamento ---

# Tabela Oficial de Comissionamento (Parceiro Magalu)
# Formato: "categoria_termo": (comissao_1p_magalu, comissao_3p_marketplace)
TABELA_COMISSAO_MAGALU = {
    "games": (6.0, 3.5),
    "game": (6.0, 3.5),
    "console": (4.5, 2.5),
    "ps5": (4.5, 2.5),
    "xbox": (4.5, 2.5),
    "nintendo": (4.5, 2.5),
    "informática": (4.0, 2.5),
    "informatica": (4.0, 2.5),
    "hardware": (4.5, 2.5),
    "computador": (3.5, 2.0),
    "notebook": (3.5, 2.0),
    "monitor": (4.0, 2.5),
    "periféricos": (6.5, 3.5),
    "perifericos": (6.5, 3.5),
    "mouse": (6.5, 3.5),
    "teclado": (6.5, 3.5),
    "headset": (6.5, 3.5),
    "acessórios": (7.0, 4.0),
    "acessorios": (7.0, 4.0),
    "casa inteligente": (5.0, 3.0),
    "áudio": (5.5, 3.5),
    "audio": (5.5, 3.5),
    "fone": (6.0, 3.5),
    "caixa de som": (5.5, 3.5),
    "smart house": (5.0, 3.0),
    "eletrônicos": (3.5, 2.0),
    "eletronicos": (3.5, 2.0),
    "celulares": (2.5, 1.5),
    "smartphones": (2.5, 1.5),
    "telefonia": (2.5, 1.5),
    "tv": (3.0, 2.0),
    "eletroportáteis": (5.0, 3.0),
    "eletrodomésticos": (3.5, 2.0),
}


def extrair_seller_id(product):
    """Extrai o vendedor do produto (identifica se é estoque Magalu 1P ou Marketplace 3P)."""
    seller = product.get("seller")
    if isinstance(seller, dict):
        s_id = seller.get("id") or seller.get("description")
        if s_id:
            return str(s_id).lower()
    elif isinstance(seller, str) and seller.strip():
        return seller.strip().lower()

    s_id = product.get("sellerId") or product.get("seller_id")
    if s_id:
        return str(s_id).lower()

    # Busca no query parameter da URL do produto
    url = product.get("url", "")
    if "seller_id=" in url:
        try:
            qs = parse_qs(urlparse(url).query)
            if "seller_id" in qs and qs["seller_id"]:
                return str(qs["seller_id"][0]).lower()
        except Exception:
            pass

    return "magazineluiza"


def extrair_imagem_produto(product):
    """Extrai a URL da imagem do produto em alta resolução."""
    img = product.get("image")
    img_url = None
    if isinstance(img, dict):
        img_url = img.get("url") or img.get("src")
    elif isinstance(img, str) and img.strip():
        img_url = img.strip()
    elif isinstance(product.get("images"), list) and len(product["images"]) > 0:
        first = product["images"][0]
        img_url = first.get("url") if isinstance(first, dict) else str(first)

    if img_url and img_url.startswith("//"):
        img_url = f"https:{img_url}"

    # Melhora resolução de miniaturas para alta qualidade (800x600) e resolve template {w}x{h}
    if img_url:
        img_url = (
            img_url.replace("{w}x{h}", "800x600")
            .replace("/186x140/", "/800x600/")
            .replace("/280x210/", "/800x600/")
        )

    return img_url


def calcular_comissao_magalu(categoria_nome, nome_produto, seller_id):
    """
    Calcula a porcentagem oficial de comissão do Parceiro Magalu
    com base na categoria, nome e vendedor (1P Magalu vs 3P Marketplace).
    """
    is_1p = (seller_id in ["magazineluiza", "magalu", "magazine luiza"])
    texto_busca = f"{categoria_nome or ''} {nome_produto or ''}".lower()

    comissao_1p = None
    comissao_3p = None

    for chave, (taxa_1p, taxa_3p) in TABELA_COMISSAO_MAGALU.items():
        if chave in texto_busca:
            comissao_1p = taxa_1p
            comissao_3p = taxa_3p
            break

    if comissao_1p is None:
        comissao_1p = 4.0
        comissao_3p = 2.5

    taxa = comissao_1p if is_1p else comissao_3p
    return round(float(taxa), 2)


def extrair_dados_magalu_live(url):
    """
    Entra na URL fornecida, raspa os produtos da página, 
    calcula descontos e descobre o total de páginas disponíveis.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    termos_banidos = ['cabo', 'pelicula', 'capinha', 'adaptador', 'suporte', 'conector', 'carregador', 'capa para']

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text
    except requests.exceptions.RequestException as e:
        logging.warning(f"Erro ao buscar a URL {url}: {e}")
        return None, 1

    soup = BeautifulSoup(html_content, "html.parser")
    next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})

    if not next_data_script:
        return None, 1

    try:
        json_data = json.loads(next_data_script.string)
        search_data = json_data["props"]["pageProps"]["data"]["search"]
        product_list = search_data["products"]
        pagination_data = search_data.get("pagination", {})
        total_pages = pagination_data.get("pages", 1)
    except (json.JSONDecodeError, KeyError):
        logging.warning("Erro: A estrutura do JSON da Magalu mudou.")
        return None, 1

    processed_products = []
    base_url = "https://www.magazinevoce.com.br"

    for product in product_list:
        try:
            nome = product.get("title", "")
            
            if any(termo in nome.lower() for termo in termos_banidos):
                continue

            price_data = product.get("price", {})
            preco_antigo_str = price_data.get("price")
            preco_atual_str = price_data.get("fullPrice")

            if preco_antigo_str is None or preco_atual_str is None:
                continue

            preco_antigo = float(preco_antigo_str)
            preco_atual = float(preco_atual_str)

            percentual_desconto = 0.0
            if preco_antigo > 0 and preco_atual > 0 and preco_antigo > preco_atual:
                percentual_desconto = round(
                    ((preco_antigo - preco_atual) / preco_antigo) * 100, 2
                )
            
            if percentual_desconto > 85:
                continue

            seller_id = extrair_seller_id(product)
            categoria_nome = product.get("category", {}).get("name") or "Geral"
            comissao_percent = calcular_comissao_magalu(categoria_nome, nome, seller_id)
            lucro_estimado_reais = round(preco_atual * (comissao_percent / 100), 2)
            imagem_url = extrair_imagem_produto(product)

            product_data = {
                "sku": f"MAGALU_{product.get('id')}",
                "nome_produto": nome,
                "loja": "Magalu",
                "preco_atual": preco_atual,
                "preco_antigo": preco_antigo,
                "percentual_desconto": percentual_desconto,
                "categoria": categoria_nome,
                "seller_id": seller_id,
                "comissao_percent": comissao_percent,
                "lucro_estimado_reais": lucro_estimado_reais,
                "imagem_url": imagem_url,
                "url_afiliado": base_url + product.get("url") if product.get("url") else None,
            }

            if product_data["sku"] and product_data["nome_produto"] and product_data["preco_atual"]:
                processed_products.append(product_data)

        except (ValueError, TypeError, AttributeError):
            continue

    if not processed_products:
        return pd.DataFrame(), total_pages

    df = pd.DataFrame(processed_products)
    return df, total_pages


# --- Módulo Mercado Livre Afiliados ---

TABELA_COMISSAO_MERCADOLIVRE = {
    "games": 6.5,
    "game": 6.5,
    "console": 5.0,
    "ps5": 5.0,
    "xbox": 5.0,
    "nintendo": 5.0,
    "jogos": 7.0,
    "informática": 5.0,
    "informatica": 5.0,
    "hardware": 4.5,
    "computador": 4.0,
    "notebook": 4.0,
    "mouse": 6.5,
    "teclado": 6.5,
    "headset": 6.5,
    "periféricos": 6.5,
    "perifericos": 6.5,
    "ssd": 5.0,
    "monitor": 4.5,
    "celulares": 3.5,
    "celular": 3.5,
    "smartphone": 3.5,
    "telefonia": 3.5,
    "áudio": 7.0,
    "audio": 7.0,
    "fone": 7.0,
    "caixa de som": 6.5,
    "casa inteligente": 6.0,
    "smart house": 6.0,
    "eletrônicos": 5.0,
    "eletronicos": 5.0,
}


def calcular_comissao_mercadolivre(categoria_nome, nome_produto):
    """Calcula a comissão oficial média do Programa de Afiliados do Mercado Livre."""
    texto = f"{categoria_nome or ''} {nome_produto or ''}".lower()
    for chave, taxa in TABELA_COMISSAO_MERCADOLIVRE.items():
        if chave in texto:
            return taxa
    return 5.0


def converter_link_afiliado_ml(url_produto, matt_tool="61727000", matt_word="rafaelmelo825"):
    """
    Injeta os parâmetros oficiais de rastreamento de afiliado do Rafael (matt_tool e matt_word).
    """
    if not url_produto:
        return None
    url_limpa = url_produto.split("#")[0]
    sep = "&" if "?" in url_limpa else "?"
    if "matt_tool" not in url_limpa:
        url_limpa = f"{url_limpa}{sep}matt_tool={matt_tool}&matt_word={matt_word}&forceInApp=true"
    return url_limpa


def limpar_preco_ml(texto):
    """Extrai número float a partir de texto de preço do Mercado Livre."""
    if not texto:
        return None
    try:
        limpo = re.sub(r"[^\d,\.]", "", str(texto))
        if "." in limpo and "," in limpo:
            limpo = limpo.replace(".", "").replace(",", ".")
        elif "," in limpo:
            limpo = limpo.replace(",", ".")
        elif "." in limpo:
            partes = limpo.split(".")
            if len(partes[-1]) == 3:
                limpo = "".join(partes)
        val = float(limpo)
        return val if val > 0 else None
    except Exception:
        return None


def extrair_dados_mercadolivre_live(url, categoria_padrao="Geral"):
    """
    Raspa produtos e ofertas do Mercado Livre (suporta Perfil Social de Criador e Vitrines de Categorias).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    }

    termos_banidos = ['cabo', 'pelicula', 'capinha', 'adaptador', 'suporte simples', 'conector']

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        logging.warning(f"Erro ao buscar URL do Mercado Livre ({url}): {e}")
        return pd.DataFrame()

    soup = BeautifulSoup(html, "html.parser")
    processed = []

    # 1. Procura cards Poly (layout moderno do ML, usado no Perfil Social e vitrines)
    poly_cards = soup.find_all("div", class_=re.compile(r"poly-card", re.I))

    # 2. Se não achar poly-cards, procura itens da busca tradicional (ui-search-layout__item)
    search_cards = soup.find_all("li", class_=re.compile(r"ui-search-layout__item", re.I)) if not poly_cards else []

    all_cards = poly_cards or search_cards

    for i, card in enumerate(all_cards):
        try:
            # Título e Link
            title_el = (
                card.find("a", class_=re.compile(r"poly-component__title", re.I)) or
                card.find("h2", class_=re.compile(r"poly-component__title|ui-search-item__title", re.I)) or
                card.find("h2") or
                card.find("a", class_=re.compile(r"ui-search-link", re.I))
            )
            if not title_el:
                continue

            nome = title_el.text.strip()
            if any(t in nome.lower() for t in termos_banidos):
                continue

            link_el = card.find("a", href=True)
            if not link_el or not link_el.get("href"):
                continue

            raw_url = link_el["href"]
            url_afiliado = converter_link_afiliado_ml(raw_url)

            # Imagem em alta resolução (busca especificamente a foto principal do produto)
            img_el = (
                card.find("img", class_=re.compile(r"poly-component__picture|ui-search-result-image__element", re.I)) or
                card.find("img")
            )
            imagem_url = None
            if img_el:
                candidatos = [
                    img_el.get("data-src"),
                    img_el.get("data-srcset"),
                    img_el.get("srcset"),
                    img_el.get("src")
                ]
                for c in candidatos:
                    if c and not str(c).strip().startswith("data:"):
                        # Limpa srcset (ex: "https://...webp 1x, https://...2x")
                        c_str = str(c).split(",")[0].strip().split()[0].strip()
                        if c_str.startswith("//"):
                            c_str = f"https:{c_str}"
                        if c_str.startswith("http"):
                            imagem_url = c_str
                            break

            # Preço atual
            preco_atual = None
            curr_price_el = (
                card.find("div", class_=re.compile(r"poly-price__current", re.I)) or
                card.find("span", class_=re.compile(r"price-tag-fraction", re.I)) or
                card.find("div", class_=re.compile(r"ui-search-price__second-line", re.I))
            )
            if curr_price_el:
                frac = curr_price_el.find(class_=re.compile(r"andes-money-amount__fraction|price-tag-fraction", re.I))
                cents = curr_price_el.find(class_=re.compile(r"andes-money-amount__cents", re.I))
                if frac:
                    p_str = frac.text.strip()
                    if cents:
                        p_str += f",{cents.text.strip()}"
                    preco_atual = limpar_preco_ml(p_str)
                else:
                    preco_atual = limpar_preco_ml(curr_price_el.text)

            # Preço antigo
            preco_antigo = None
            prev_price_el = (
                card.find("s", class_=re.compile(r"poly-price__previous|andes-money-amount", re.I)) or
                card.find("s", class_=re.compile(r"ui-search-price__part--original", re.I))
            )
            if prev_price_el:
                preco_antigo = limpar_preco_ml(prev_price_el.text)

            if not preco_atual:
                continue

            if not preco_antigo or preco_antigo <= preco_atual:
                preco_antigo = preco_atual

            # Desconto %
            percentual_desconto = 0.0
            disc_el = card.find(class_=re.compile(r"discount|disc-label", re.I))
            if disc_el:
                m = re.search(r"(\d+)\s*%", disc_el.text)
                if m:
                    percentual_desconto = float(m.group(1))

            if percentual_desconto == 0.0 and preco_antigo > preco_atual:
                percentual_desconto = round(((preco_antigo - preco_atual) / preco_antigo) * 100, 2)

            comissao = calcular_comissao_mercadolivre(categoria_padrao, nome)
            lucro = round(preco_atual * (comissao / 100), 2)

            sku_match = re.search(r"(MLB\d+|MLB-\d+)", raw_url, re.I)
            sku = f"ML_{sku_match.group(1)}" if sku_match else f"ML_{i}_{abs(hash(nome)) % 1000000}"

            item = {
                "sku": sku,
                "nome_produto": nome,
                "loja": "Mercado Livre",
                "preco_atual": preco_atual,
                "preco_antigo": preco_antigo,
                "percentual_desconto": percentual_desconto,
                "categoria": categoria_padrao,
                "seller_id": "Mercado Livre Full",
                "comissao_percent": comissao,
                "lucro_estimado_reais": lucro,
                "imagem_url": imagem_url,
                "url_afiliado": url_afiliado,
            }
            processed.append(item)
        except Exception:
            continue

    if not processed:
        return pd.DataFrame()

    return pd.DataFrame(processed)


def gerar_json_para_ia(df):
    if df is None or df.empty:
        return None
    colunas_pesadas = [c for c in ("url_afiliado", "imagem_url", "score_qualidade") if c in df.columns]
    df_enxuto = df.drop(columns=colunas_pesadas) if colunas_pesadas else df
    return df_enxuto.to_json(orient="records", force_ascii=False, indent=2)


def _extrair_texto_resposta_gemini(result):
    """Extrai texto bruto de result.text ou dos parts da primeira candidate com segurança."""
    texto = ""
    finish_reason = "desconhecido"
    try:
        candidates = getattr(result, "candidates", None) or []
        if candidates:
            finish_reason = str(getattr(candidates[0], "finish_reason", "desconhecido"))
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            partes_txt = [str(getattr(p, "text", "") or "") for p in parts if getattr(p, "text", None)]
            if partes_txt:
                texto = "".join(partes_txt)
    except Exception:
        pass

    if not texto:
        try:
            texto = str(getattr(result, "text", "") or "")
        except Exception as exc:
            logging.warning(f"Não foi possível ler result.text do Gemini (finish_reason={finish_reason}): {exc}")
            texto = ""

    return texto, finish_reason


def gemini_fx(dados_json):
    if not configurar_gemini(obrigatorio=False):
        return json.dumps(
            {"erro": "A análise da IA falhou", "motivo": "Gemini SDK ou GEMINI_API_KEY indisponível"},
            ensure_ascii=False,
        )

    model_name = os.getenv("GEMINI_MODEL", "gemini-4-hydrogen")
    try:
        logging.info(f"Iniciando a análise braba com o modelo Gemini ({model_name})...")
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=ALPHA_PROFIT_SYSTEM_PROMPT,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.65,
                "max_output_tokens": 8192,
            }
        )
        prompt_usuario = (
            "Analise o catálogo abaixo e retorne EXATAMENTE 20 Oportunidades de Ouro "
            "(15 do Mercado Livre e 5 da Magalu), priorizando variedade de produtos e categorias, "
            f"seguindo as regras do sistema:\n\n{dados_json}"
        )
        result = model.generate_content(
            prompt_usuario,
            safety_settings={
                "HARASSMENT": "block_none", "HARM_CATEGORY_SEXUALLY_EXPLICIT": "block_none",
                "HARM_CATEGORY_HATE_SPEECH": "block_none", "HARM_CATEGORY_DANGEROUS_CONTENT": "block_none",
            },
        )
        texto, finish_reason = _extrair_texto_resposta_gemini(result)
        logging.info(
            f"Análise concluída com sucesso! finish_reason={finish_reason} | chars={len(texto)}"
        )
        return texto
    except Exception as e:
        logging.error(f"Putz, a IA falhou: {e}")
        return json.dumps({"erro": "A análise da IA falhou", "motivo": str(e)}, ensure_ascii=False)


def _limpar_fences_json(texto):
    """Remove blocos markdown ```json ... ``` ou texto introdutório ao redor do JSON."""
    limpo = str(texto or "").strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo).strip()
    return limpo


def _recuperar_objetos_json_parciais(texto):
    """
    Caso o JSON venha truncado no fim (ex: MAX_TOKENS), resgata todos os objetos
    de oportunidade completos já fechados na resposta.
    """
    recuperados = []
    decoder = json.JSONDecoder()
    idx = 0
    n = len(texto)
    while idx < n:
        pos = texto.find("{", idx)
        if pos == -1:
            break
        try:
            obj, end = decoder.raw_decode(texto, pos)
            if isinstance(obj, dict) and (
                obj.get("sku_selecionado") or obj.get("nome_produto")
            ):
                recuperados.append(obj)
                idx = end
                continue
        except json.JSONDecodeError:
            pass
        idx = pos + 1
    return recuperados


def _extrair_lista_oportunidades_de_estrutura(parsed):
    """Normaliza dict/list retornado pelo Gemini para uma lista limpa de dicts de oportunidade."""
    candidatos = []
    if isinstance(parsed, list):
        candidatos = parsed
    elif isinstance(parsed, dict):
        chaves_preferidas = (
            "oportunidades",
            "oportunidades_de_ouro",
            "ofertas",
            "produtos",
            "items",
            "selecao",
        )
        for chave in chaves_preferidas:
            val = parsed.get(chave)
            if isinstance(val, list):
                candidatos = val
                break
        if not candidatos:
            for val in parsed.values():
                if isinstance(val, list) and any(isinstance(x, dict) for x in val):
                    candidatos = val
                    break

    return [
        op for op in candidatos
        if isinstance(op, dict) and (
            op.get("nome_produto") or op.get("sku_selecionado") or op.get("url_afiliado")
        )
    ]


def _converter_candidatas_para_lista(candidatas):
    """Aceita pandas.DataFrame ou list[dict] e devolve lista de dicts normalizada."""
    if candidatas is None:
        return []
    if hasattr(candidatas, "to_dict"):
        if getattr(candidatas, "empty", False):
            return []
        return candidatas.to_dict(orient="records")
    if isinstance(candidatas, list):
        return [dict(item) for item in candidatas if isinstance(item, dict)]
    return []


def gerar_oportunidades_fallback(candidatas, qtd_ml=15, qtd_magalu=5):
    """
    Gera seleção determinística (15 ML + 5 Magalu) a partir das candidatas ranqueadas
    caso o Gemini falhe, retorne JSON truncado ou lista vazia — evita perda silenciosa dos canais.
    """
    itens = _converter_candidatas_para_lista(candidatas)
    if not itens:
        return []

    def _chave_rank(row):
        if "score_qualidade" in row and row["score_qualidade"] is not None:
            try:
                return float(row["score_qualidade"])
            except (TypeError, ValueError):
                pass
        return calcular_score_qualidade_item(
            menor_preco_historico=row.get("menor_preco_historico", False),
            queda_real_percent=row.get("queda_real_percent", 0.0),
            percentual_desconto=row.get("percentual_desconto", 0.0),
            lucro_estimado_reais=row.get("lucro_estimado_reais", 0.0),
            preco_atual=row.get("preco_atual", 0.0),
        )

    ordenados = sorted(itens, key=_chave_rank, reverse=True)
    ml_itens = [x for x in ordenados if "mercado" in str(x.get("loja", "")).lower()]
    mg_itens = [x for x in ordenados if "magalu" in str(x.get("loja", "")).lower()]

    sel_ml = ml_itens[:qtd_ml]
    sel_mg = mg_itens[:qtd_magalu]

    total_alvo = qtd_ml + qtd_magalu
    if len(sel_ml) + len(sel_mg) < total_alvo:
        usados = {str(x.get("sku", "")) for x in sel_ml + sel_mg}
        sobras = [x for x in ordenados if str(x.get("sku", "")) not in usados]
        faltam = total_alvo - (len(sel_ml) + len(sel_mg))
        for item in sobras[:faltam]:
            if "magalu" in str(item.get("loja", "")).lower():
                sel_mg.append(item)
            else:
                sel_ml.append(item)

    # Intercala ML e Magalu (3 ML + 1 Magalu quando possível)
    intercalados = []
    i_ml, i_mg = 0, 0
    while i_ml < len(sel_ml) or i_mg < len(sel_mg):
        for _ in range(3):
            if i_ml < len(sel_ml):
                intercalados.append(sel_ml[i_ml])
                i_ml += 1
        if i_mg < len(sel_mg):
            intercalados.append(sel_mg[i_mg])
            i_mg += 1

    resultado = []
    for row in intercalados[:total_alvo]:
        nome = str(row.get("nome_produto") or "Oferta Selecionada").strip()
        preco = float(row.get("preco_atual", 0.0) or 0.0)
        desc = float(row.get("percentual_desconto", 0.0) or 0.0)
        loja = str(row.get("loja") or storage_db.inferir_loja_por_sku(row.get("sku", ""))).strip()
        is_min = bool(row.get("menor_preco_historico", False))
        queda = float(row.get("queda_real_percent", 0.0) or 0.0)

        titulo = (nome[:47] + "...") if len(nome) > 50 else nome
        if is_min:
            corpo = f"Atingiu o menor preço registrado em 180 dias ({queda:.0f}% abaixo da mediana recente)."
        elif desc >= 10:
            corpo = f"Baixou para R$ {preco:.2f} com {desc:.0f}% de desconto verificado na vitrine."
        else:
            corpo = f"Oportunidade selecionada por preço competitivo em {loja} por R$ {preco:.2f}."
        cta = f"Garanta com {desc:.0f}% OFF agora!" if desc >= 5 else "Confira os detalhes antes que acabe!"

        resultado.append({
            "sku_selecionado": str(row.get("sku", "")),
            "nome_produto": nome,
            "loja": loja,
            "categoria": row.get("categoria", "Geral"),
            "preco_atual": preco,
            "preco_antigo": float(row.get("preco_antigo", preco) or preco),
            "percentual_desconto": desc,
            "comissao_percent": row.get("comissao_percent"),
            "lucro_estimado_reais": row.get("lucro_estimado_reais"),
            "imagem_url": row.get("imagem_url"),
            "url_afiliado": row.get("url_afiliado", ""),
            "menor_preco_historico": is_min,
            "queda_real_percent": queda,
            "preco_medio_historico": float(row.get("preco_medio_historico", 0.0) or 0.0),
            "razao_selecao": "Seleção automática pelo ranking Alpha-Profit (fallback determinístico).",
            "copy_venda": {
                "titulo": titulo,
                "corpo": corpo,
                "cta": cta,
            },
        })
    return resultado


def parsear_resposta_gemini(raw_text, candidatas_fallback=None, qtd_ml=15, qtd_magalu=5):
    """
    Faz parsing tolerante da resposta do Gemini com log explícito de falhas (incluindo snippet bruto)
    e ativa fallback determinístico sobre candidatas ranqueadas se o retorno vier inválido ou vazio.
    """
    raw_str = str(raw_text or "")
    limpo = _limpar_fences_json(raw_str)
    parsed = None
    erro_parse = None

    if limpo:
        try:
            parsed = json.loads(limpo)
        except json.JSONDecodeError as e1:
            erro_parse = str(e1)
            # Tenta isolar objeto/array externo caso haja texto antes/depois do JSON
            ini_obj = limpo.find("{")
            fim_obj = limpo.rfind("}")
            ini_arr = limpo.find("[")
            fim_arr = limpo.rfind("]")
            trechos = []
            if ini_obj != -1 and fim_obj > ini_obj:
                trechos.append(limpo[ini_obj:fim_obj + 1])
            if ini_arr != -1 and fim_arr > ini_arr:
                trechos.append(limpo[ini_arr:fim_arr + 1])
            for trecho in trechos:
                try:
                    parsed = json.loads(trecho)
                    erro_parse = None
                    break
                except json.JSONDecodeError:
                    continue
    else:
        erro_parse = "resposta_vazia"

    oportunidades = _extrair_lista_oportunidades_de_estrutura(parsed) if parsed is not None else []
    origem = "gemini"

    if not oportunidades and limpo:
        parciais = _recuperar_objetos_json_parciais(limpo)
        if parciais:
            oportunidades = parciais
            origem = "gemini_parcial"
            logging.warning(
                f"⚠️ JSON do Gemini veio incompleto ({erro_parse}), mas {len(parciais)} ofertas "
                f"válidas foram resgatadas do retorno (chars={len(raw_str)})."
            )

    if oportunidades:
        total_alvo = int(qtd_ml) + int(qtd_magalu)
        if candidatas_fallback is not None and 0 < len(oportunidades) < total_alvo:
            lista_cand = _converter_candidatas_para_lista(candidatas_fallback)
            skus_usados = {
                str(op.get("sku_selecionado", "") or "").strip()
                for op in oportunidades
                if op.get("sku_selecionado")
            }
            nomes_usados = {
                str(op.get("nome_produto", "") or "").strip().lower()[:40]
                for op in oportunidades
                if op.get("nome_produto")
            }
            restantes = [
                row for row in lista_cand
                if str(row.get("sku", "") or "").strip() not in skus_usados
                and str(row.get("nome_produto", "") or "").strip().lower()[:40] not in nomes_usados
            ]
            atuais_ml = sum(1 for op in oportunidades if "mercado" in str(op.get("loja", "")).lower())
            atuais_mg = sum(1 for op in oportunidades if "magalu" in str(op.get("loja", "")).lower())
            faltam_ml = max(0, int(qtd_ml) - atuais_ml)
            faltam_mg = max(0, int(qtd_magalu) - atuais_mg)
            faltam_total = total_alvo - len(oportunidades)
            while faltam_ml + faltam_mg < faltam_total:
                faltam_ml += 1

            extras = gerar_oportunidades_fallback(
                restantes, qtd_ml=faltam_ml, qtd_magalu=faltam_mg
            )[:faltam_total]
            if extras:
                logging.warning(
                    f"⚠️ Gemini retornou apenas {len(oportunidades)}/{total_alvo} ofertas; "
                    f"complementando {len(extras)} via ranking determinístico."
                )
                oportunidades = list(oportunidades) + extras
                if origem == "gemini":
                    origem = "gemini_complementado"

        logging.info(f"🧠 Parser Gemini OK ({origem}): {len(oportunidades)} oportunidades carregadas.")
        return {"oportunidades": oportunidades, "_origem": origem}

    motivo_erro = erro_parse or (
        parsed.get("motivo") or parsed.get("erro") if isinstance(parsed, dict) else "lista_oportunidades_vazia"
    )
    snippet_inicio = raw_str[:400].replace("\n", " ")
    snippet_fim = raw_str[-250:].replace("\n", " ") if len(raw_str) > 400 else ""
    logging.warning(
        f"⚠️ Parser Gemini sem oportunidades válidas! motivo='{motivo_erro}' | chars={len(raw_str)} | "
        f"inicio='{snippet_inicio}'" + (f" | fim='{snippet_fim}'" if snippet_fim else "")
    )

    fallback_ops = gerar_oportunidades_fallback(
        candidatas_fallback, qtd_ml=qtd_ml, qtd_magalu=qtd_magalu
    )
    if fallback_ops:
        logging.warning(
            f"🛡️ Fallback determinístico ativado: {len(fallback_ops)} ofertas selecionadas pelo ranking "
            "para não perder a rodada dos canais!"
        )
        return {"oportunidades": fallback_ops, "_origem": "fallback_deterministico"}

    return {"oportunidades": [], "_origem": "vazio"}


def formatar_oportunidades_html(oportunidades_dict):
    html_out = ""
    try:
        for i, op in enumerate(oportunidades_dict.get("oportunidades", [])):
            copy = op.get("copy_venda", {})
            preco_atual = float(op.get('preco_atual', 0.0) or 0.0)
            desconto = float(op.get('percentual_desconto', 0.0) or 0.0)
            comissao = op.get('comissao_percent')
            lucro = op.get('lucro_estimado_reais')

            if lucro is None and comissao is not None:
                lucro = round(preco_atual * (float(comissao) / 100), 2)

            comissao_str = f"{comissao}%" if comissao is not None else "N/A"
            lucro_str = f"R$ {lucro:.2f}" if lucro is not None else "N/A"
            loja_nome = op.get('loja', 'Oferta')

            html_out += f"""
            <div style="border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; padding: 16px; background-color: #f9f9f9;">
                <h3 style="color: #0086ff; margin-top: 0;">[{loja_nome}] Oportunidade {i+1}: {op.get('nome_produto', 'N/A')}</h3>
                <p>
                    <strong>Preço:</strong> R$ {preco_atual:.2f} | 
                    <strong>Desconto:</strong> <span style="color: #c00;">{desconto}% OFF</span> | 
                    <strong>Comissão Afiliado:</strong> <span style="color: #008000; font-weight: bold;">{comissao_str} (~{lucro_str}/venda)</span>
                </p>
                <div style="background-color: #fff; border: 1px dashed #ccc; padding: 12px; margin-top: 15px;">
                    <p><strong>Título:</strong> {copy.get('titulo', 'N/A')}</p>
                    <p><strong>Corpo:</strong> {copy.get('corpo', 'N/A')}</p>
                    <p><strong>CTA:</strong> {copy.get('cta', 'N/A')}</p>
                </div>
                <a href="{op.get('url_afiliado', '#')}" style="display: inline-block; background-color: #0086ff; color: #ffffff; padding: 10px 15px; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 15px;">Ver Oferta</a>
            </div>
            """
        return html_out
    except Exception:
        return "<p>Erro na formatação.</p>"


def enviar_email_oportunidades(email_disparo, senha, email_destinatario, oportunidades_dict, df_todos_produtos=None, host="smtp.gmail.com", porta=587):
    if not email_disparo or not senha:
        logging.warning("Credenciais de e-mail ausentes. Pulando envio.")
        return

    msg = EmailMessage()
    msg["From"] = email_disparo
    msg["To"] = email_destinatario

    # Lógica de Contingência: Se a IA falhou, oportunidades_dict estará vazio ou sem a chave certa.
    if oportunidades_dict and "oportunidades" in oportunidades_dict:
        msg["Subject"] = f'Alpha-Profit: 20 Oportunidades! (15 Mercado Livre + 5 Magalu) ({time.strftime("%d/%m/%Y")})'
        oportunidades_html = formatar_oportunidades_html(oportunidades_dict)
        mensagem_html = f"<html><body><h2>Alpha-Profit AI Bot</h2>{oportunidades_html}</body></html>"
    else:
        msg["Subject"] = f'Alpha-Profit: Apenas CSV Diário ({time.strftime("%d/%m/%Y")}) - Alerta IA'
        mensagem_html = """
        <html><body>
            <h2>Alpha-Profit AI Bot</h2>
            <p>⚠️ <strong>Aviso:</strong> O robô concluiu a raspagem completa do site perfeitamente, 
            porém a Inteligência Artificial falhou na hora de gerar os textos de venda hoje (pode ter sido um erro temporário no servidor deles).</p>
            <p>De qualquer forma, o seu arquivo CSV com todos os dados raspados está salvo e anexado neste e-mail para você não perder oportunidades!</p>
        </body></html>
        """

    msg.set_content(mensagem_html, subtype="html")

    # Sempre anexa o CSV, independentemente do sucesso da IA
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        try:
            csv_str = df_todos_produtos.to_csv(
                index=False, 
                sep=';', 
                encoding='utf-8-sig',
                quoting=csv.QUOTE_ALL,   
                doublequote=True         
            )
            
            msg.add_attachment(
                csv_str.encode('utf-8-sig'), 
                maintype='text', 
                subtype='csv', 
                filename=f'todos_produtos_raspados_{time.strftime("%Y%m%d")}.csv'
            )
            logging.info(f"CSV com {len(df_todos_produtos)} produtos anexado ao e-mail!")
        except Exception as e:
            logging.error(f"Erro ao tentar anexar o CSV: {e}")

    try:
        with smtplib.SMTP(host, porta) as server:
            server.starttls()
            server.login(email_disparo, senha)
            server.send_message(msg)
            logging.info("Email enviado com sucesso (Com IA ou apenas contingência)!")
    except Exception as e:
        logging.error(f"Erro no envio de e-mail: {e}")


def baixar_imagem_jpeg(imagem_url):
    """
    Baixa a imagem do produto e converte qualquer formato (.webp, .png, etc.)
    para bytes JPEG genuínos em memória via Pillow (compatível com Telegram e X).
    """
    if not imagem_url:
        return None

    urls_tentativa = [imagem_url]
    if "/800x600/" in imagem_url:
        urls_tentativa.append(imagem_url.replace("/800x600/", "/420x420/"))
        urls_tentativa.append(imagem_url.replace("/800x600/", "/280x210/"))
    if imagem_url.endswith(".webp"):
        urls_tentativa.append(imagem_url[:-5] + ".jpg")
    elif imagem_url.endswith(".jpg"):
        urls_tentativa.append(imagem_url[:-4] + ".webp")

    headers_img = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/jpeg,image/png,*/*;q=0.8",
        "Referer": "https://www.mercadolivre.com.br/" if "mlstatic" in imagem_url else "https://www.magazinevoce.com.br/"
    }

    for url_img_atual in urls_tentativa:
        try:
            img_resp = requests.get(url_img_atual, headers=headers_img, timeout=12)
            if img_resp.status_code == 200 and len(img_resp.content) > 500:
                img_bytes = img_resp.content
                if PILLOW_DISPONIVEL:
                    try:
                        im = Image.open(BytesIO(img_bytes))
                        if im.mode in ("RGBA", "LA", "P"):
                            fundo = Image.new("RGB", im.size, (255, 255, 255))
                            if im.mode == "P":
                                im = im.convert("RGBA")
                            fundo.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                            im = fundo
                        else:
                            im = im.convert("RGB")
                        buf = BytesIO()
                        im.save(buf, format="JPEG", quality=90)
                        return buf.getvalue()
                    except Exception as conv_err:
                        logging.warning(f"Falha ao converter imagem via Pillow: {conv_err}")
                return img_bytes
        except Exception as e:
            logging.warning(f"Erro ao baixar imagem ({url_img_atual}): {e}")

    return None


def enviar_oportunidade_telegram(bot_token, chat_id, oportunidade, imagem_url=None, preco_antigo=None):
    """
    Publica uma oferta individual no canal do Telegram com foto,
    copy persuasiva, preços formatados e botão de compra direto.
    """
    copy = oportunidade.get("copy_venda", {})
    titulo = copy.get("titulo") or oportunidade.get("nome_produto", "Super Oferta!")
    corpo = copy.get("corpo", "")
    cta = copy.get("cta", "Garanta o seu com desconto!")
    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)
    url_afiliado = oportunidade.get("url_afiliado", "")
    loja = oportunidade.get("loja") or ("Mercado Livre" if "mercadolivre" in url_afiliado.lower() else "Magalu")

    badge = "🟡 <b>[MERCADO LIVRE - FULL]</b>" if "mercado" in loja.lower() else "🔵 <b>[MAGALU]</b>"
    btn_text = "🛒 VER NO MERCADO LIVRE" if "mercado" in loja.lower() else "🛒 GARANTIR OFERTA NO MAGALU"

    # Monta a legenda formatada com HTML suportado pelo Telegram
    selo_radar = ""
    if oportunidade.get("menor_preco_historico"):
        media_ant = float(oportunidade.get("preco_medio_historico") or 0.0)
        if media_ant > preco_atual:
            selo_radar = f"📉 <b>MENOR PREÇO REGISTRADO!</b> (Média anterior: R$ {media_ant:.2f})\n"
        else:
            selo_radar = "📉 <b>MENOR PREÇO REGISTRADO!</b>\n"

    texto_caption = f"{badge}\n{selo_radar}🔥 <b>{titulo}</b>\n\n"
    if corpo:
        texto_caption += f"{corpo}\n\n"

    if preco_antigo and float(preco_antigo) > preco_atual:
        texto_caption += f"❌ De: <s>R$ {float(preco_antigo):.2f}</s>\n"

    texto_caption += f"✅ <b>Por apenas: R$ {preco_atual:.2f}</b>\n"
    texto_caption += f"📉 <b>Desconto: {desconto:.0f}% OFF</b>\n\n"
    texto_caption += f"⚡ <i>{cta}</i>"

    # Botão de Ação Inline (Leva direto pro seu link de afiliado)
    reply_markup = None
    if url_afiliado:
        reply_markup = {
            "inline_keyboard": [
                [{"text": btn_text, "url": url_afiliado}]
            ]
        }

    # Tentativa 1: Enviar com a Foto do produto em alta resolução
    if imagem_url:
        # Método 1.1: Baixa e converte para JPEG real (via Pillow) antes do upload multipart
        img_bytes = baixar_imagem_jpeg(imagem_url)
        if img_bytes:
            try:
                url_api = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                files = {"photo": ("produto.jpg", img_bytes, "image/jpeg")}
                data = {
                    "chat_id": chat_id,
                    "caption": texto_caption,
                    "parse_mode": "HTML",
                }
                if reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup)

                resp = requests.post(url_api, data=data, files=files, timeout=15)
                if resp.status_code == 200:
                    logging.info(f"Oportunidade postada com foto (JPEG convertido) no Telegram: {titulo[:35]}...")
                    return True
                else:
                    logging.warning(f"Telegram retornou status {resp.status_code} no upload da foto: {resp.text}")
            except Exception as e:
                logging.warning(f"Erro no upload da foto ao Telegram: {e}")

        # Método 1.2: Envio direto por URL (caso o upload direto falhe)
        try:
            url_api = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": imagem_url,
                "caption": texto_caption,
                "parse_mode": "HTML",
            }
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup)

            resp = requests.post(url_api, data=payload, timeout=12)
            if resp.status_code == 200:
                logging.info(f"Oportunidade postada com foto (URL) no Telegram: {titulo[:35]}...")
                return True
            else:
                logging.warning(f"Telegram retornou status {resp.status_code} na foto via URL: {resp.text}")
        except Exception as e:
            logging.warning(f"Erro ao postar foto por URL no Telegram: {e}")

    # Tentativa 2 (Fallback): Enviar mensagem de texto caso a foto falhe
    try:
        url_api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": texto_caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        resp = requests.post(url_api, data=payload, timeout=12)
        if resp.status_code == 200:
            logging.info(f"Oportunidade postada em texto no Telegram: {titulo[:35]}...")
            return True
        else:
            logging.error(f"Erro ao postar texto no Telegram ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        logging.error(f"Erro na requisição sendMessage do Telegram: {e}")
        return False


def disparar_canal_telegram(bot_token, chat_id, oportunidades_dict, df_todos_produtos=None, intervalo_segundos=3):
    """
    Percorre a lista de oportunidades e dispara uma a uma no canal do Telegram,
    retornando a lista de SKUs publicados para registro no histórico anti-repetição.
    """
    skus_postados = []
    if not bot_token or not chat_id:
        logging.warning("Credenciais do Telegram ausentes (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID). Pulando envio para o canal.")
        return skus_postados

    oportunidades = oportunidades_dict.get("oportunidades", [])
    if not oportunidades:
        logging.info("Nenhuma oportunidade para enviar ao Telegram.")
        return skus_postados

    # Indexa imagem_url e preco_antigo por SKU, URL e Nome (evita perder foto se a IA alterar o SKU)
    mapa_por_sku = {}
    mapa_por_url = {}
    mapa_por_nome = {}
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        for _, row in df_todos_produtos.iterrows():
            info = {
                "sku": str(row.get("sku", "")),
                "imagem_url": row.get("imagem_url"),
                "preco_antigo": row.get("preco_antigo")
            }
            sku = info["sku"]
            url_af = str(row.get("url_afiliado", "") or "")
            nome_norm = str(row.get("nome_produto", "") or "").strip().lower()[:40]
            if sku:
                mapa_por_sku[sku] = info
            if url_af:
                mapa_por_url[url_af] = info
            if nome_norm:
                mapa_por_nome[nome_norm] = info

    logging.info(f"🚀 Iniciando postagem de {len(oportunidades)} ofertas no Canal do Telegram...")
    sucessos = 0

    for i, op in enumerate(oportunidades):
        sku = str(op.get("sku_selecionado", ""))
        url_op = str(op.get("url_afiliado", "") or "")
        nome_op = str(op.get("nome_produto", "") or "").strip().lower()[:40]

        extra = (
            mapa_por_sku.get(sku) or
            mapa_por_url.get(url_op) or
            mapa_por_nome.get(nome_op) or
            {}
        )
        imagem_url = op.get("imagem_url") or extra.get("imagem_url")
        preco_antigo = op.get("preco_antigo") or extra.get("preco_antigo")
        sku_real = extra.get("sku") or sku

        if enviar_oportunidade_telegram(bot_token, chat_id, op, imagem_url=imagem_url, preco_antigo=preco_antigo):
            sucessos += 1
            if sku_real:
                skus_postados.append(sku_real)

        if i < len(oportunidades) - 1:
            time.sleep(intervalo_segundos)

    logging.info(f"🎉 Finalizado: {sucessos}/{len(oportunidades)} ofertas publicadas no Telegram com sucesso!")
    return skus_postados


# --- 3.4. Publicação Automática no X (Twitter) ---

def formatar_texto_tweet(oportunidade, preco_antigo=None):
    """
    Formata a oferta no MODO ECONÔMICO para o X (Twitter) (<280 chars):
    SEM URLs ou domínios no texto (evita a taxa de US$ 0,20/post por link,
    reduzindo o custo para ~US$ 0,015/post e melhorando o alcance orgânico).
    """
    copy = oportunidade.get("copy_venda", {})
    titulo_raw = (copy.get("titulo") or oportunidade.get("nome_produto") or "Super Oferta!").strip()
    titulo = (titulo_raw[:85] + "...") if len(titulo_raw) > 88 else titulo_raw

    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)
    url_afiliado = (oportunidade.get("url_afiliado") or "").strip()
    loja = oportunidade.get("loja") or ("Mercado Livre" if "mercadolivre" in url_afiliado.lower() else "Magalu")
    badge = "🟡 [MERCADO LIVRE]" if "mercado" in loja.lower() else "🔵 [MAGALU]"

    linhas = [f"{badge}"]
    if oportunidade.get("menor_preco_historico"):
        media_ant = float(oportunidade.get("preco_medio_historico") or 0.0)
        if media_ant > preco_atual:
            linhas.append(f"📉 MENOR PREÇO REGISTRADO! (Média anterior: R$ {media_ant:.2f})")
        else:
            linhas.append("📉 MENOR PREÇO REGISTRADO!")
    linhas.extend([f"🔥 {titulo}", ""])
    if preco_antigo and float(preco_antigo) > preco_atual:
        linhas.append(f"❌ De: R$ {float(preco_antigo):.2f}")
    if desconto >= 5:
        linhas.append(f"✅ Por: R$ {preco_atual:.2f} ({desconto:.0f}% OFF!)")
    else:
        linhas.append(f"✅ Por: R$ {preco_atual:.2f}")

    linhas.extend([
        "",
        "📲 Link da oferta no nosso Telegram: @promosgeektech (link na bio!)",
        "#Promocao #Oferta #Tech #Gamer"
    ])
    return "\n".join(linhas)


def disparar_x_twitter(oportunidades_dict, df_todos_produtos=None, max_posts=2, intervalo_segundos=8):
    """
    Publica as melhores ofertas da rodada no X (Twitter) em MODO ECONÔMICO:
    foto JPEG + oferta sem URLs no texto (~US$ 0,015/post no Pay-Per-Use).
    Por padrão posta as Top 2 ofertas por execução (6/dia nas 3 rodadas).
    """
    if not TWEEPY_DISPONIVEL:
        logging.warning("Biblioteca 'tweepy' não instalada. Pulando publicação no X (Twitter).")
        return

    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.warning("Credenciais do X ausentes (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET). Pulando envio para o X.")
        return

    oportunidades = oportunidades_dict.get("oportunidades", [])
    if not oportunidades:
        logging.info("Nenhuma oportunidade para publicar no X.")
        return

    try:
        max_posts = int(os.getenv("X_MAX_POSTS", str(max_posts)))
    except ValueError:
        max_posts = 2

    # Indexa imagem_url e preco_antigo do catálogo completo
    mapa_por_sku, mapa_por_url, mapa_por_nome = {}, {}, {}
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        for _, row in df_todos_produtos.iterrows():
            info = {
                "imagem_url": row.get("imagem_url"),
                "preco_antigo": row.get("preco_antigo"),
            }
            sku = str(row.get("sku", ""))
            url_af = str(row.get("url_afiliado", "") or "")
            nome_norm = str(row.get("nome_produto", "") or "").strip().lower()[:40]
            if sku:
                mapa_por_sku[sku] = info
            if url_af:
                mapa_por_url[url_af] = info
            if nome_norm:
                mapa_por_nome[nome_norm] = info

    # Seleciona as Top N ofertas mais chamativas (priorizando Quedas Reais do Radar + desconto + lucro)
    selecionadas = sorted(
        oportunidades,
        key=lambda op: (
            (100.0 if op.get("menor_preco_historico") else 0.0) +
            float(op.get("queda_real_percent", 0.0) or 0.0) * 2.0 +
            float(op.get("percentual_desconto", 0.0) or 0.0) * 0.6 +
            float(op.get("lucro_estimado_reais", 0.0) or 0.0) * 0.4
        ),
        reverse=True
    )[:max_posts]

    try:
        # API v1.1 usada para upload de mídia (foto)
        auth_v1 = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
        api_v1 = tweepy.API(auth_v1)

        # API v2 usada para criação dos tweets
        client_v2 = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
    except Exception as e:
        logging.error(f"Erro ao autenticar na API do X (Twitter): {e}")
        return

    logging.info(f"🐦 Iniciando publicação das Top {len(selecionadas)} ofertas no X (Twitter)...")
    sucessos = 0

    for i, op in enumerate(selecionadas):
        sku = str(op.get("sku_selecionado", ""))
        url_op = str(op.get("url_afiliado", "") or "")
        nome_op = str(op.get("nome_produto", "") or "").strip().lower()[:40]
        extra = mapa_por_sku.get(sku) or mapa_por_url.get(url_op) or mapa_por_nome.get(nome_op) or {}

        imagem_url = op.get("imagem_url") or extra.get("imagem_url")
        preco_antigo = op.get("preco_antigo") or extra.get("preco_antigo")
        texto_tweet = formatar_texto_tweet(op, preco_antigo=preco_antigo)

        media_ids = None
        if imagem_url:
            img_bytes = baixar_imagem_jpeg(imagem_url)
            if img_bytes:
                try:
                    media = api_v1.media_upload(filename="produto.jpg", file=BytesIO(img_bytes))
                    media_ids = [media.media_id]
                except Exception as media_err:
                    logging.warning(f"Falha no upload de imagem para o X (postando sem foto): {media_err}")

        try:
            client_v2.create_tweet(text=texto_tweet, media_ids=media_ids)
            sucessos += 1
            logging.info(f"Tweet {sucessos}/{len(selecionadas)} publicado no X com sucesso!")
        except tweepy.TooManyRequests:
            logging.warning("Limite de requisições da API do X (HTTP 429) atingido. Encerrando envios no X nesta rodada.")
            break
        except Exception as tweet_err:
            logging.error(f"Erro ao publicar tweet no X: {tweet_err}")

        if i < len(selecionadas) - 1:
            time.sleep(intervalo_segundos)

    logging.info(f"🐦 Finalizado no X: {sucessos}/{len(selecionadas)} tweets publicados!")
    return sucessos


# --- 3.4.5. Publicação Automática no Threads (Meta) ---

def formatar_texto_threads(oportunidade, preco_antigo=None):
    """
    Formata a oferta para o Threads (limite de 500 caracteres),
    incluindo copy persuasiva, preço De/Por, desconto, link de afiliado direto
    (zero taxa de link no Threads!) e chamada para o canal do Telegram.
    """
    copy = oportunidade.get("copy_venda", {})
    titulo = (copy.get("titulo") or oportunidade.get("nome_produto") or "Super Oferta!").strip()
    corpo = (copy.get("corpo") or "").strip()
    url_afiliado = (oportunidade.get("url_afiliado") or "").strip()
    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)
    loja = oportunidade.get("loja") or ("Mercado Livre" if "mercadolivre" in url_afiliado.lower() else "Magalu")
    badge = "🟡 [MERCADO LIVRE]" if "mercado" in loja.lower() else "🔵 [MAGALU]"

    linhas = [f"{badge}"]
    if oportunidade.get("menor_preco_historico"):
        media_ant = float(oportunidade.get("preco_medio_historico") or 0.0)
        if media_ant > preco_atual:
            linhas.append(f"📉 MENOR PREÇO REGISTRADO! (Média anterior: R$ {media_ant:.2f})")
        else:
            linhas.append("📉 MENOR PREÇO REGISTRADO!")
    linhas.extend([f"🔥 {titulo}", ""])
    if corpo:
        linhas.append(corpo[:140])
        linhas.append("")

    if preco_antigo and float(preco_antigo) > preco_atual:
        linhas.append(f"❌ De: R$ {float(preco_antigo):.2f}")
    if desconto >= 5:
        linhas.append(f"✅ Por: R$ {preco_atual:.2f} ({desconto:.0f}% OFF!)")
    else:
        linhas.append(f"✅ Por: R$ {preco_atual:.2f}")

    if url_afiliado:
        linhas.extend(["", f"🛒 Compre aqui: {url_afiliado}"])

    linhas.extend(["", "📢 Mais ofertas no Telegram: @promosgeektech"])
    texto = "\n".join(linhas)
    return texto[:495]


def disparar_threads(oportunidades_dict, df_todos_produtos=None, max_posts=5, intervalo_segundos=6):
    """
    Publica as melhores ofertas da rodada no Threads via API oficial da Meta (100% gratuita).
    Descobre o THREADS_USER_ID automaticamente via /me usando apenas THREADS_ACCESS_TOKEN.
    Tenta publicar com foto (JPEG/PNG) e faz fallback automático para TEXT + link_attachment.
    """
    access_token = os.getenv("THREADS_ACCESS_TOKEN")
    if not access_token:
        logging.warning("Credencial THREADS_ACCESS_TOKEN ausente. Pulando publicação no Threads.")
        return

    oportunidades = oportunidades_dict.get("oportunidades", [])
    if not oportunidades:
        logging.info("Nenhuma oportunidade para publicar no Threads.")
        return

    try:
        max_posts = int(os.getenv("THREADS_MAX_POSTS", str(max_posts)))
    except ValueError:
        max_posts = 5

    # Descobre o USER_ID automaticamente pelo endpoint /me caso não esteja no ambiente
    user_id = os.getenv("THREADS_USER_ID")
    if not user_id:
        try:
            me_resp = requests.get(
                "https://graph.threads.net/v1.0/me",
                params={"fields": "id,username", "access_token": access_token},
                timeout=12
            )
            if me_resp.status_code == 200:
                me_data = me_resp.json()
                user_id = me_data.get("id")
                logging.info(f"🧵 Threads autenticado como @{me_data.get('username', 'desconhecido')} (ID: {user_id})")
            else:
                logging.error(f"Erro ao autenticar no Threads (/me): {me_resp.status_code} - {me_resp.text}")
                return
        except Exception as e:
            logging.error(f"Exceção ao consultar /me do Threads: {e}")
            return

    # Indexa imagem_url e preco_antigo do catálogo completo
    mapa_por_sku, mapa_por_url, mapa_por_nome = {}, {}, {}
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        for _, row in df_todos_produtos.iterrows():
            info = {
                "imagem_url": row.get("imagem_url"),
                "preco_antigo": row.get("preco_antigo"),
            }
            sku = str(row.get("sku", ""))
            url_af = str(row.get("url_afiliado", "") or "")
            nome_norm = str(row.get("nome_produto", "") or "").strip().lower()[:40]
            if sku:
                mapa_por_sku[sku] = info
            if url_af:
                mapa_por_url[url_af] = info
            if nome_norm:
                mapa_por_nome[nome_norm] = info

    # Seleciona as Top N ofertas (priorizando Quedas Reais do Radar + desconto + lucro estimado)
    selecionadas = sorted(
        oportunidades,
        key=lambda op: (
            (100.0 if op.get("menor_preco_historico") else 0.0) +
            float(op.get("queda_real_percent", 0.0) or 0.0) * 2.0 +
            float(op.get("percentual_desconto", 0.0) or 0.0) * 0.6 +
            float(op.get("lucro_estimado_reais", 0.0) or 0.0) * 0.4
        ),
        reverse=True
    )[:max_posts]

    logging.info(f"🧵 Iniciando publicação das Top {len(selecionadas)} ofertas no Threads...")
    sucessos = 0

    for i, op in enumerate(selecionadas):
        sku = str(op.get("sku_selecionado", ""))
        url_op = str(op.get("url_afiliado", "") or "")
        nome_op = str(op.get("nome_produto", "") or "").strip().lower()[:40]
        extra = mapa_por_sku.get(sku) or mapa_por_url.get(url_op) or mapa_por_nome.get(nome_op) or {}

        imagem_url = op.get("imagem_url") or extra.get("imagem_url")
        preco_antigo = op.get("preco_antigo") or extra.get("preco_antigo")
        texto_post = formatar_texto_threads(op, preco_antigo=preco_antigo)

        creation_id = None
        usou_imagem = False

        # Passo 1A: Tenta criar container de IMAGEM se a URL for JPEG/PNG pública
        if imagem_url and any(imagem_url.lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
            try:
                resp_img = requests.post(
                    f"https://graph.threads.net/v1.0/{user_id}/threads",
                    data={
                        "media_type": "IMAGE",
                        "image_url": imagem_url,
                        "text": texto_post,
                        "access_token": access_token,
                    },
                    timeout=15
                )
                if resp_img.status_code == 200 and resp_img.json().get("id"):
                    creation_id = resp_img.json()["id"]
                    usou_imagem = True
                else:
                    logging.warning(f"Threads container IMAGE falhou ({resp_img.status_code}), usando fallback TEXT: {resp_img.text}")
            except Exception as e:
                logging.warning(f"Erro ao criar container IMAGE no Threads: {e}")

        # Passo 1B (Fallback): Cria container de TEXTO com link_attachment
        if not creation_id:
            try:
                payload_txt = {
                    "media_type": "TEXT",
                    "text": texto_post,
                    "access_token": access_token,
                }
                if url_op:
                    payload_txt["link_attachment"] = url_op
                resp_txt = requests.post(
                    f"https://graph.threads.net/v1.0/{user_id}/threads",
                    data=payload_txt,
                    timeout=15
                )
                if resp_txt.status_code == 200 and resp_txt.json().get("id"):
                    creation_id = resp_txt.json()["id"]
                else:
                    logging.error(f"Erro ao criar container TEXT no Threads ({resp_txt.status_code}): {resp_txt.text}")
                    continue
            except Exception as e:
                logging.error(f"Exceção ao criar container TEXT no Threads: {e}")
                continue

        # Aguarda a Meta processar a mídia antes de publicar
        time.sleep(5 if usou_imagem else 2)

        # Passo 2: Publica o container
        try:
            pub_resp = requests.post(
                f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
                data={
                    "creation_id": creation_id,
                    "access_token": access_token,
                },
                timeout=15
            )
            if pub_resp.status_code == 200:
                sucessos += 1
                tipo = "foto" if usou_imagem else "texto+link"
                logging.info(f"Threads {sucessos}/{len(selecionadas)} publicado ({tipo}) com sucesso!")
            else:
                logging.error(f"Erro ao publicar no Threads ({pub_resp.status_code}): {pub_resp.text}")
        except Exception as e:
            logging.error(f"Exceção ao publicar no Threads: {e}")

        if i < len(selecionadas) - 1:
            time.sleep(intervalo_segundos)

    logging.info(f"🧵 Finalizado no Threads: {sucessos}/{len(selecionadas)} posts publicados!")
    return sucessos


def _bonus_nicho_gamestore(op):
    """
    Calcula bônus/penalidade de aderência à marca Gamestore (Games, Hardware Gamer & Áudio)
    para garantir que Reels, Stories e Feed da Página nunca desperdicem destaque com itens
    fora do nicho (ex: fechadura, cadeado, vitrola, eletrodomésticos).
    """
    copy = op.get("copy_venda", {})
    texto = " ".join([
        str(op.get("nome_produto", "") or ""),
        str(op.get("categoria", "") or ""),
        str(copy.get("titulo", "") or ""),
    ]).lower()

    termos_fora_nicho = [
        "fechadura", "cadeado", "vitrola", "camera wi-fi", "câmera wi-fi",
        "lampada", "lâmpada", "tomada", "interruptor", "geladeira",
        "fritadeira", "panela", "aspirador", "cafeteira", "ventilador", "chaleira"
    ]
    if any(t in texto for t in termos_fora_nicho):
        return -150.0

    termos_gamer_forte = [
        "ps5", "ps4", "playstation", "xbox", "nintendo", "switch", "gamer",
        "headset", "controle", "joystick", "dualsense", "ssd", "nvme",
        "mouse", "teclado", "mecanico", "mecânico", "monitor", "rtx", "gtx",
        "placa de video", "placa de vídeo", "console", "jogo", "gta", "fifa",
        "ea fc", "call of duty", "dark souls", "halo", "red dead", "hyperx",
        "logitech", "razer", "corsair", "redragon", "fifine", "havit",
        "jbl", "fone", "bluetooth", "tws", "notebook", "gabinete", "ram"
    ]
    if any(t in texto for t in termos_gamer_forte):
        return 180.0

    cat = str(op.get("categoria", "") or "").lower()
    if any(c in cat for c in ("game", "informática", "informatica", "áudio", "audio", "tech")):
        return 90.0

    return 0.0


# --- 3.4.6. Publicação Automática na Página do Facebook (Foto Limpa + Link no 1º Comentário) ---

def formatar_texto_facebook(oportunidade, preco_antigo=None):
    """
    Formata a legenda da oferta para Página do Facebook SEM link externo no post principal
    (estratégia anti-restrição de alcance da Meta; o link vai automaticamente no 1º comentário).
    """
    copy = oportunidade.get("copy_venda", {})
    titulo = (copy.get("titulo") or oportunidade.get("nome_produto") or "Super Oferta!").strip()
    corpo = (copy.get("corpo") or "").strip()
    cta = (copy.get("cta") or "Aproveite antes que o preço suba!").strip()
    url_afiliado = (oportunidade.get("url_afiliado") or "").strip()
    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)
    loja = oportunidade.get("loja") or ("Mercado Livre" if "mercadolivre" in url_afiliado.lower() else "Magalu")
    badge = "🟡 [MERCADO LIVRE]" if "mercado" in loja.lower() else "🔵 [MAGALU]"

    linhas = [f"{badge}"]
    if oportunidade.get("menor_preco_historico"):
        media_ant = float(oportunidade.get("preco_medio_historico") or 0.0)
        if media_ant > preco_atual:
            linhas.append(f"📉 MENOR PREÇO REGISTRADO! (Média anterior: R$ {media_ant:.2f})")
        else:
            linhas.append("📉 MENOR PREÇO REGISTRADO!")
    linhas.extend([f"🔥 {titulo}", ""])
    if corpo:
        linhas.extend([corpo, ""])

    if preco_antigo and float(preco_antigo) > preco_atual:
        linhas.append(f"❌ De: R$ {float(preco_antigo):.2f}")
    if desconto >= 5:
        linhas.append(f"✅ Por apenas: R$ {preco_atual:.2f} ({desconto:.0f}% OFF!)")
    else:
        linhas.append(f"✅ Por apenas: R$ {preco_atual:.2f}")

    linhas.extend([
        "",
        f"⚡ {cta}",
        "👇 Link direto da oferta no 1º comentário!",
        "📢 Mais promoções diárias no Telegram: @promosgeektech",
        "",
        "#Promocao #Oferta #Desconto #Tech #Gamer"
    ])
    return "\n".join(linhas)


def disparar_facebook_page(oportunidades_dict, df_todos_produtos=None, max_posts=5, intervalo_segundos=6):
    """
    Publica as melhores ofertas na Página do Facebook via Meta Graph API (100% gratuito):
      1. Sobe foto JPEG real (via Pillow, funciona para ML e Magalu) com legenda limpa (SEM link).
      2. Publica o link de afiliado automaticamente no 1º comentário para maximizar alcance orgânico.
    Descobre o PAGE_ID automaticamente via /me usando apenas FACEBOOK_PAGE_TOKEN.
    """
    page_token = os.getenv("FACEBOOK_PAGE_TOKEN")
    if not page_token:
        logging.warning("Credencial FACEBOOK_PAGE_TOKEN ausente. Pulando publicação na Página do Facebook.")
        return 0

    oportunidades = oportunidades_dict.get("oportunidades", [])
    if not oportunidades:
        logging.info("Nenhuma oportunidade para publicar no Facebook.")
        return 0

    try:
        max_posts = int(os.getenv("FACEBOOK_MAX_POSTS", str(max_posts)))
    except ValueError:
        max_posts = 5

    # Descobre automaticamente o PAGE_ID e garante que estamos usando um Token de Página
    # (Se o secret for um Token de Usuário com pages_show_list, troca automaticamente via /me/accounts)
    page_id = os.getenv("FACEBOOK_PAGE_ID")
    try:
        acc_resp = requests.get(
            "https://graph.facebook.com/v21.0/me/accounts",
            params={"fields": "id,name,access_token", "access_token": page_token},
            timeout=12
        )
        if acc_resp.status_code == 200:
            paginas = acc_resp.json().get("data", [])
            if paginas:
                escolhida = next((p for p in paginas if page_id and str(p.get("id")) == str(page_id)), paginas[0])
                page_id = escolhida.get("id")
                if escolhida.get("access_token"):
                    page_token = escolhida["access_token"]
                logging.info(f"📘 Token de Usuário convertido automaticamente para a Página '{escolhida.get('name', 'desconhecida')}' (ID: {page_id})")
    except Exception as e:
        logging.warning(f"Aviso ao verificar /me/accounts do Facebook: {e}")

    if not page_id:
        try:
            me_resp = requests.get(
                "https://graph.facebook.com/v21.0/me",
                params={"fields": "id,name", "access_token": page_token},
                timeout=12
            )
            if me_resp.status_code == 200:
                me_data = me_resp.json()
                page_id = me_data.get("id")
                logging.info(f"📘 Facebook autenticado na Página '{me_data.get('name', 'desconhecida')}' (ID: {page_id})")
            else:
                logging.error(f"Erro ao autenticar no Facebook (/me): {me_resp.status_code} - {me_resp.text}")
                return 0
        except Exception as e:
            logging.error(f"Exceção ao consultar /me do Facebook: {e}")
            return 0

    # Indexa imagem_url e preco_antigo do catálogo completo
    mapa_por_sku, mapa_por_url, mapa_por_nome = {}, {}, {}
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        for _, row in df_todos_produtos.iterrows():
            info = {
                "imagem_url": row.get("imagem_url"),
                "preco_antigo": row.get("preco_antigo"),
            }
            sku = str(row.get("sku", ""))
            url_af = str(row.get("url_afiliado", "") or "")
            nome_norm = str(row.get("nome_produto", "") or "").strip().lower()[:40]
            if sku:
                mapa_por_sku[sku] = info
            if url_af:
                mapa_por_url[url_af] = info
            if nome_norm:
                mapa_por_nome[nome_norm] = info

    # Seleciona as Top N ofertas (Nicho Gamestore + Quedas Reais do Radar + desconto + lucro estimado)
    selecionadas = sorted(
        oportunidades,
        key=lambda op: (
            _bonus_nicho_gamestore(op) +
            (100.0 if op.get("menor_preco_historico") else 0.0) +
            float(op.get("queda_real_percent", 0.0) or 0.0) * 2.0 +
            float(op.get("percentual_desconto", 0.0) or 0.0) * 0.6 +
            float(op.get("lucro_estimado_reais", 0.0) or 0.0) * 0.4
        ),
        reverse=True
    )[:max_posts]

    logging.info(f"📘 Iniciando publicação das Top {len(selecionadas)} ofertas na Página do Facebook...")
    sucessos = 0

    for i, op in enumerate(selecionadas):
        sku = str(op.get("sku_selecionado", ""))
        url_op = str(op.get("url_afiliado", "") or "").strip()
        nome_op = str(op.get("nome_produto", "") or "").strip().lower()[:40]
        extra = mapa_por_sku.get(sku) or mapa_por_url.get(url_op) or mapa_por_nome.get(nome_op) or {}

        imagem_url = op.get("imagem_url") or extra.get("imagem_url")
        preco_antigo = op.get("preco_antigo") or extra.get("preco_antigo")
        legenda = formatar_texto_facebook(op, preco_antigo=preco_antigo)

        post_id = None

        # Passo 1A: Publica com foto JPEG (upload multipart direto — funciona até para .webp do ML)
        if imagem_url:
            img_bytes = baixar_imagem_jpeg(imagem_url)
            if img_bytes:
                try:
                    resp_photo = requests.post(
                        f"https://graph.facebook.com/v21.0/{page_id}/photos",
                        data={
                            "caption": legenda,
                            "published": "true",
                            "access_token": page_token,
                        },
                        files={"source": ("produto.jpg", img_bytes, "image/jpeg")},
                        timeout=20
                    )
                    if resp_photo.status_code == 200:
                        data_p = resp_photo.json()
                        post_id = data_p.get("post_id") or data_p.get("id")
                    else:
                        logging.warning(f"Facebook /photos falhou ({resp_photo.status_code}), tentando /feed: {resp_photo.text}")
                except Exception as e:
                    logging.warning(f"Erro ao subir foto no Facebook: {e}")

        # Passo 1B (Fallback): Publica texto no /feed caso a foto falhe
        if not post_id:
            try:
                resp_feed = requests.post(
                    f"https://graph.facebook.com/v21.0/{page_id}/feed",
                    data={
                        "message": legenda,
                        "access_token": page_token,
                    },
                    timeout=15
                )
                if resp_feed.status_code == 200:
                    post_id = resp_feed.json().get("id")
                else:
                    logging.error(f"Erro ao publicar no /feed do Facebook ({resp_feed.status_code}): {resp_feed.text}")
                    continue
            except Exception as e:
                logging.error(f"Exceção ao publicar no /feed do Facebook: {e}")
                continue

        sucessos += 1
        logging.info(f"Facebook {sucessos}/{len(selecionadas)} publicado (post_id: {post_id})!")

        # Passo 2: Publica o link direto de afiliado no 1º comentário (mantém alcance orgânico alto)
        if post_id and url_op:
            time.sleep(2)
            try:
                resp_comm = requests.post(
                    f"https://graph.facebook.com/v21.0/{post_id}/comments",
                    data={
                        "message": f"🛒 Garanta a oferta aqui: {url_op}",
                        "access_token": page_token,
                    },
                    timeout=12
                )
                if resp_comm.status_code == 200:
                    logging.info(f"💬 1º comentário com link publicado no post {post_id}!")
                else:
                    logging.warning(f"Não foi possível comentar link no Facebook ({resp_comm.status_code}): {resp_comm.text}")
            except Exception as e:
                logging.warning(f"Exceção ao comentar link no Facebook: {e}")

        if i < len(selecionadas) - 1:
            time.sleep(intervalo_segundos)

    logging.info(f"📘 Finalizado no Facebook: {sucessos}/{len(selecionadas)} posts publicados!")
    return sucessos


def disparar_facebook_reels_stories(oportunidades_dict, df_todos_produtos=None, max_reels=1, max_stories=2):
    """
    Gera criativos verticais 9:16 (1080x1920) com Pillow + ffmpeg e publica automaticamente
    como Facebook Reels (MP4 animado + link no 1º comentário) e Facebook Stories (card HD)
    na Página usando o mesmo FACEBOOK_PAGE_TOKEN (100% gratuito).
    """
    page_token = os.getenv("FACEBOOK_PAGE_TOKEN")
    if not page_token:
        return 0, 0

    oportunidades = oportunidades_dict.get("oportunidades", [])
    if not oportunidades:
        return 0, 0

    try:
        from media_generator import (
            gerar_card_vertical_9x16,
            gerar_locucao_ptbr,
            gerar_video_reel_hyperframes,
            gerar_video_reel_mp4,
            OUTPUT_DIR,
        )
    except Exception as imp_err:
        logging.warning(f"Módulo media_generator indisponível: {imp_err}")
        return 0, 0

    # Autentica na Página (mesma lógica do feed: converte User Token -> Page Token se necessário)
    page_id = os.getenv("FACEBOOK_PAGE_ID")
    try:
        acc_resp = requests.get(
            "https://graph.facebook.com/v21.0/me/accounts",
            params={"fields": "id,name,access_token", "access_token": page_token},
            timeout=12
        )
        if acc_resp.status_code == 200:
            paginas = acc_resp.json().get("data", [])
            if paginas:
                escolhida = next((p for p in paginas if page_id and str(p.get("id")) == str(page_id)), paginas[0])
                page_id = escolhida.get("id")
                if escolhida.get("access_token"):
                    page_token = escolhida["access_token"]
    except Exception:
        pass

    if not page_id:
        try:
            me_resp = requests.get(
                "https://graph.facebook.com/v21.0/me",
                params={"fields": "id,name", "access_token": page_token},
                timeout=12
            )
            if me_resp.status_code == 200:
                page_id = me_resp.json().get("id")
        except Exception:
            return 0, 0

    if not page_id:
        return 0, 0

    # Indexa imagens e preços antigos
    mapa_por_sku, mapa_por_url, mapa_por_nome = {}, {}, {}
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        for _, row in df_todos_produtos.iterrows():
            info = {"imagem_url": row.get("imagem_url"), "preco_antigo": row.get("preco_antigo")}
            sku = str(row.get("sku", ""))
            url_af = str(row.get("url_afiliado", "") or "")
            nome_norm = str(row.get("nome_produto", "") or "").strip().lower()[:40]
            if sku:
                mapa_por_sku[sku] = info
            if url_af:
                mapa_por_url[url_af] = info
            if nome_norm:
                mapa_por_nome[nome_norm] = info

    candidatas_ordenadas = sorted(
        oportunidades,
        key=lambda op: (
            _bonus_nicho_gamestore(op) +
            (100.0 if op.get("menor_preco_historico") else 0.0) +
            float(op.get("queda_real_percent", 0.0) or 0.0) * 2.0 +
            float(op.get("percentual_desconto", 0.0) or 0.0) * 0.6 +
            float(op.get("lucro_estimado_reais", 0.0) or 0.0) * 0.4
        ),
        reverse=True
    )

    # Pré-seleciona ofertas com foto válida baixada (nunca publica Reel/Story com caixa branca vazia)
    top_ofertas_com_foto = []
    limite_necessario = max(max_reels, max_stories)
    for op in candidatas_ordenadas:
        sku = str(op.get("sku_selecionado", ""))
        url_op = str(op.get("url_afiliado", "") or "").strip()
        nome_op = str(op.get("nome_produto", "") or "").strip().lower()[:40]
        extra = mapa_por_sku.get(sku) or mapa_por_url.get(url_op) or mapa_por_nome.get(nome_op) or {}

        imagem_url = op.get("imagem_url") or extra.get("imagem_url")
        preco_antigo = op.get("preco_antigo") or extra.get("preco_antigo")
        img_bytes = baixar_imagem_jpeg(imagem_url) if imagem_url else None
        if not img_bytes:
            logging.warning(f"Pulando oferta sem foto válida para Reel/Story: {op.get('nome_produto', '')[:50]}")
            continue
        top_ofertas_com_foto.append((op, img_bytes, preco_antigo, url_op))
        if len(top_ofertas_com_foto) >= limite_necessario:
            break

    reels_ok = 0
    stories_ok = 0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- 1. FACEBOOK REELS (MP4 9:16 animado + link no 1º comentário) ---
    for idx, (op, img_bytes, preco_antigo, url_op) in enumerate(top_ofertas_com_foto[:max_reels], start=1):

        voz_path = gerar_locucao_ptbr(
            op, preco_antigo=preco_antigo,
            arquivo_saida=os.path.join(OUTPUT_DIR, f"reel_voz_{idx}.mp3")
        )
        # Tenta primeiro o Reel animado em motion graphics (HyperFrames); faz fallback para Pillow + ffmpeg
        mp4_alvo = os.path.join(OUTPUT_DIR, f"reel_oferta_{idx}.mp4")
        mp4_path = gerar_video_reel_hyperframes(
            op,
            img_bytes=img_bytes,
            preco_antigo=preco_antigo,
            audio_path=voz_path,
            arquivo_saida=mp4_alvo,
        )
        if not mp4_path:
            card_path = gerar_card_vertical_9x16(
                op, img_bytes=img_bytes, preco_antigo=preco_antigo, modo="reel",
                arquivo_saida=os.path.join(OUTPUT_DIR, f"reel_card_{idx}.jpg")
            )
            mp4_path = gerar_video_reel_mp4(
                card_path,
                arquivo_saida=mp4_alvo,
                duracao_segundos=9,
                audio_path=voz_path
            )
        if not mp4_path or not os.path.exists(mp4_path):
            continue

        try:
            # Fase 1: Start
            r_start = requests.post(
                f"https://graph.facebook.com/v21.0/{page_id}/video_reels",
                data={"upload_phase": "start", "access_token": page_token},
                timeout=15
            )
            if r_start.status_code != 200:
                logging.warning(f"Facebook Reels start falhou ({r_start.status_code}): {r_start.text}")
                continue
            video_id = r_start.json().get("video_id")
            upload_url = r_start.json().get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{video_id}"

            # Fase 2: Upload binário MP4
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
                timeout=60
            )
            if r_up.status_code != 200:
                logging.warning(f"Facebook Reels upload falhou ({r_up.status_code}): {r_up.text}")
                continue

            # Fase 3: Finish & Publish
            legenda_reel = formatar_texto_facebook(op, preco_antigo=preco_antigo)
            r_fin = requests.post(
                f"https://graph.facebook.com/v21.0/{page_id}/video_reels",
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": legenda_reel,
                    "access_token": page_token,
                },
                timeout=25
            )
            if r_fin.status_code == 200:
                reels_ok += 1
                logging.info(f"🎬 Facebook Reel {reels_ok}/{max_reels} publicado com sucesso (video_id: {video_id})!")
                if video_id and url_op:
                    time.sleep(4)
                    try:
                        requests.post(
                            f"https://graph.facebook.com/v21.0/{video_id}/comments",
                            data={"message": f"🛒 Garanta a oferta aqui: {url_op}", "access_token": page_token},
                            timeout=12
                        )
                    except Exception:
                        pass
            else:
                logging.warning(f"Facebook Reels finish falhou ({r_fin.status_code}): {r_fin.text}")
        except Exception as e:
            logging.warning(f"Exceção ao publicar Facebook Reel: {e}")

    # --- 2. FACEBOOK STORIES (Cards 9:16 HD) ---
    for idx, (op, img_bytes, preco_antigo, url_op) in enumerate(top_ofertas_com_foto[:max_stories], start=1):

        story_path = gerar_card_vertical_9x16(
            op, img_bytes=img_bytes, preco_antigo=preco_antigo, modo="story",
            arquivo_saida=os.path.join(OUTPUT_DIR, f"story_oferta_{idx}.jpg")
        )
        if not story_path or not os.path.exists(story_path):
            continue

        try:
            with open(story_path, "rb") as f_st:
                st_bytes = f_st.read()
            # Passo 1: Upload como foto não publicada
            r_ph = requests.post(
                f"https://graph.facebook.com/v21.0/{page_id}/photos",
                data={"published": "false", "access_token": page_token},
                files={"source": (f"story_{idx}.jpg", st_bytes, "image/jpeg")},
                timeout=20
            )
            if r_ph.status_code != 200 or not r_ph.json().get("id"):
                logging.warning(f"Facebook Story upload foto falhou ({r_ph.status_code}): {r_ph.text}")
                continue
            photo_id = r_ph.json()["id"]

            # Passo 2: Publica como Story da Página
            r_st = requests.post(
                f"https://graph.facebook.com/v21.0/{page_id}/photo_stories",
                data={"photo_id": photo_id, "access_token": page_token},
                timeout=15
            )
            if r_st.status_code == 200:
                stories_ok += 1
                logging.info(f"📱 Facebook Story {stories_ok}/{max_stories} publicado com sucesso!")
            else:
                logging.warning(f"Facebook Story falhou ({r_st.status_code}): {r_st.text}")
        except Exception as e:
            logging.warning(f"Exceção ao publicar Facebook Story: {e}")

        time.sleep(3)

    logging.info(f"🎬📱 Finalizado Meta Vertical: {reels_ok}/{max_reels} Reels e {stories_ok}/{max_stories} Stories publicados!")
    return reels_ok, stories_ok


# --- 3.5. Controle de Histórico Anti-Repetição (72 horas via SQLite) ---


def carregar_historico_postados(horas_validade=72, db_path=storage_db.DEFAULT_DB_PATH, conn=None):
    """Carrega SKUs postados recentemente direto do SQLite dentro da janela de horas_validade."""
    fechar_conn = conn is None
    if conn is None:
        conn = storage_db.conectar_db(db_path)
        storage_db.inicializar_db(conn)
    try:
        ativo = storage_db.carregar_skus_postados_recentes(conn, horas_validade=horas_validade)
        logging.info(f"Histórico anti-repetição (SQLite) carregado: {len(ativo)} ofertas bloqueadas nas últimas {horas_validade}h.")
        return ativo
    except Exception as e:
        logging.warning(f"Não foi possível carregar histórico anti-repetição do SQLite: {e}")
        return {}
    finally:
        if fechar_conn and conn is not None:
            conn.close()


def salvar_historico_postados(
    novos_skus,
    df_todos_produtos=None,
    db_path=storage_db.DEFAULT_DB_PATH,
    conn=None,
    canal_resumo="telegram",
):
    """Registra os SKUs recém-postados na tabela historico_postados do SQLite."""
    if not novos_skus:
        return 0

    mapa_info = {}
    for row in _converter_candidatas_para_lista(df_todos_produtos):
        sku_row = str(row.get("sku", "") or "").strip()
        if sku_row:
            mapa_info[sku_row] = {
                "loja": row.get("loja"),
                "preco": row.get("preco_atual"),
            }

    agora_iso = datetime.now().isoformat()
    itens = []
    for sku in novos_skus:
        sku_str = str(sku or "").strip()
        if not sku_str:
            continue
        info = mapa_info.get(sku_str, {})
        itens.append({
            "sku": sku_str,
            "loja": info.get("loja") or storage_db.inferir_loja_por_sku(sku_str),
            "preco_postado": info.get("preco"),
            "canal_resumo": canal_resumo,
            "postado_em": agora_iso,
        })

    fechar_conn = conn is None
    if conn is None:
        conn = storage_db.conectar_db(db_path)
        storage_db.inicializar_db(conn)
    try:
        gravados = storage_db.registrar_postagens_lote(conn, itens)
        logging.info(f"Histórico anti-repetição (SQLite) atualizado: {gravados} ofertas registradas.")
        return gravados
    except Exception as e:
        logging.warning(f"Erro ao salvar histórico anti-repetição no SQLite: {e}")
        return 0
    finally:
        if fechar_conn and conn is not None:
            conn.close()


def aplicar_filtro_anti_repeticao_72h(produtos, historico_postados, minimo_ineditos=25):
    """
    Remove produtos já postados nas últimas 72h apenas se restarem >= minimo_ineditos itens;
    caso contrário, preserva o catálogo completo com rotação por jitter.
    """
    if not historico_postados:
        return produtos

    bloqueados = set(str(k) for k in historico_postados.keys())
    if hasattr(produtos, "empty"):
        if produtos.empty:
            return produtos
        total_bruto = len(produtos)
        df_ineditos = produtos[~produtos["sku"].astype(str).isin(bloqueados)]
        if len(df_ineditos) >= int(minimo_ineditos):
            logging.info(
                f"Filtro anti-repetição aplicado: {total_bruto - len(df_ineditos)} ofertas recentes ignoradas. "
                f"Restaram {len(df_ineditos)} inéditas!"
            )
            return df_ineditos.copy()
        logging.info(
            f"Poucos produtos inéditos nesta rodada ({len(df_ineditos)} < {minimo_ineditos}); "
            "mantendo catálogo completo com rotação por jitter."
        )
        return produtos

    lista = list(produtos or [])
    ineditos = [p for p in lista if str(p.get("sku", "")) not in bloqueados]
    if len(ineditos) >= int(minimo_ineditos):
        logging.info(
            f"Filtro anti-repetição aplicado: {len(lista) - len(ineditos)} ofertas recentes ignoradas. "
            f"Restaram {len(ineditos)} inéditas!"
        )
        return ineditos
    logging.info(
        f"Poucos produtos inéditos nesta rodada ({len(ineditos)} < {minimo_ineditos}); "
        "mantendo catálogo completo com rotação por jitter."
    )
    return lista


def calcular_score_qualidade_item(
    menor_preco_historico,
    queda_real_percent,
    percentual_desconto,
    lucro_estimado_reais,
    preco_atual,
    jitter_val=0.0,
):
    """Calcula score composto ponderando Radar 180d + Desconto + Lucro em R$ + Sweet Spot."""
    try:
        preco_f = float(preco_atual or 0.0)
    except (TypeError, ValueError):
        preco_f = 0.0
    sweet = 25.0 if 35.0 <= preco_f <= 500.0 else 0.0
    return (
        (int(bool(menor_preco_historico)) * 45.0)
        + (min(float(queda_real_percent or 0.0), 40.0) * 1.5)
        + (float(percentual_desconto or 0.0) * 0.35)
        + (min(float(lucro_estimado_reais or 0.0), 80.0) * 0.40)
        + sweet
        + float(jitter_val or 0.0)
    )


# --- 3.6. Radar de Queda Real de Preço (Histórico 180 dias via SQLite + Regra Anti-"Metade do Dobro") ---


def enriquecer_e_atualizar_historico_precos(
    produtos,
    conn=None,
    db_path=storage_db.DEFAULT_DB_PATH,
    dias=180,
    data_coleta=None,
):
    """
    Modo Híbrido 180d via SQLite:
      1) Consulta min_180d, mediana_180d e dias_observados ANTES de gravar a rodada atual
         (nunca compara o SKU com o próprio preço da rodada).
      2) Usa mediana_180d em preco_medio_historico e queda_real_percent (proteção contra picos artificiais).
      3) Só ativa menor_preco_historico=True quando dias_observados >= 5 E preco_atual < min_180d.
      4) Grava os preços da rodada em lote no SQLite após concluir todas as leituras.
    """
    hoje = str(data_coleta or datetime.now().strftime("%Y-%m-%d"))[:10]
    agora_iso = datetime.now().isoformat()

    is_df = hasattr(produtos, "iterrows")
    if is_df and produtos.empty:
        produtos["queda_real_percent"] = []
        produtos["menor_preco_historico"] = []
        produtos["preco_medio_historico"] = []
        return produtos

    linhas = _converter_candidatas_para_lista(produtos) if is_df else list(produtos or [])
    if not linhas:
        return produtos

    fechar_conn = conn is None
    if conn is None:
        conn = storage_db.conectar_db(db_path)
        storage_db.inicializar_db(conn)

    quedas_reais = []
    minimas_hist = []
    medias_hist = []
    registros_para_gravar = []

    qtd_minimas = 0
    qtd_quedas = 0

    try:
        # FASE A: Leitura integral do histórico anterior ANTES de escrever qualquer preço da rodada
        for row in linhas:
            sku = str(row.get("sku", "") or "").strip()
            loja = str(row.get("loja") or storage_db.inferir_loja_por_sku(sku)).strip()
            try:
                preco = round(float(row.get("preco_atual", 0.0) or 0.0), 2)
            except (TypeError, ValueError):
                preco = 0.0

            queda_pct = 0.0
            is_minima = False
            mediana_ref = 0.0

            if sku and preco > 0:
                stats = storage_db.obter_estatisticas_sku(
                    conn,
                    sku=sku,
                    loja=loja,
                    dias=dias,
                    data_referencia=hoje,
                    excluir_data=hoje,
                )
                dias_obs = int(stats.get("dias_observados", 0) or 0)
                min_180d = stats.get("min_180d")
                mediana_180d = stats.get("mediana_180d")

                if mediana_180d is not None and float(mediana_180d) > 0:
                    mediana_ref = round(float(mediana_180d), 2)
                    if mediana_ref > preco:
                        queda_pct = round(((mediana_ref - preco) / mediana_ref) * 100.0, 1)

                # Trava anti-"metade do dobro" + warm-up: exige >= 5 dias anteriores e estar estritamente abaixo da mínima
                if dias_obs >= 5 and min_180d is not None and preco < float(min_180d):
                    is_minima = True
                    qtd_minimas += 1

                if queda_pct >= 5.0:
                    qtd_quedas += 1

                registros_para_gravar.append({
                    "sku": sku,
                    "loja": loja,
                    "preco": preco,
                    "data_coleta": hoje,
                    "titulo": str(row.get("nome_produto", "") or "").strip(),
                    "categoria": str(row.get("categoria", "") or "").strip(),
                    "atualizado_em": agora_iso,
                })

            quedas_reais.append(queda_pct)
            minimas_hist.append(is_minima)
            medias_hist.append(mediana_ref)

        # FASE B: Gravação em lote somente depois de todas as consultas de comparação
        gravados = storage_db.registrar_precos_lote(conn, registros_para_gravar)
        logging.info(
            f"📉 Radar de Preços 180d (SQLite) atualizado ({gravados} preços gravados hoje). "
            f"Nesta rodada: {qtd_minimas} mínimas históricas (warm-up >=5d) e {qtd_quedas} quedas >=5% vs mediana!"
        )
    finally:
        if fechar_conn and conn is not None:
            conn.close()

    if is_df:
        produtos = produtos.copy()
        produtos["queda_real_percent"] = quedas_reais
        produtos["menor_preco_historico"] = minimas_hist
        produtos["preco_medio_historico"] = medias_hist
        return produtos

    for row, q, m, med in zip(linhas, quedas_reais, minimas_hist, medias_hist):
        row["queda_real_percent"] = q
        row["menor_preco_historico"] = m
        row["preco_medio_historico"] = med
    return linhas


def enriquecer_oportunidades_com_radar(oportunidades_dict, df_produtos):
    """Propaga sinais do Radar 180d e re-hidrata url_afiliado/imagem_url pelo SKU."""
    if not oportunidades_dict or "oportunidades" not in oportunidades_dict:
        return oportunidades_dict

    lista_produtos = _converter_candidatas_para_lista(df_produtos)
    if not lista_produtos:
        return oportunidades_dict

    mapa_sku, mapa_url, mapa_nome = {}, {}, {}
    for row in lista_produtos:
        info = {
            "menor_preco_historico": bool(row.get("menor_preco_historico", False)),
            "queda_real_percent": float(row.get("queda_real_percent", 0.0) or 0.0),
            "preco_medio_historico": float(row.get("preco_medio_historico", 0.0) or 0.0),
            "url_afiliado": row.get("url_afiliado"),
            "imagem_url": row.get("imagem_url"),
            "preco_antigo": row.get("preco_antigo"),
            "categoria": row.get("categoria"),
            "loja": row.get("loja"),
            "comissao_percent": row.get("comissao_percent"),
            "lucro_estimado_reais": row.get("lucro_estimado_reais"),
        }
        sku = str(row.get("sku", ""))
        url_af = str(row.get("url_afiliado", "") or "")
        nome_norm = str(row.get("nome_produto", "") or "").strip().lower()[:40]
        if sku:
            mapa_sku[sku] = info
        if url_af:
            mapa_url[url_af] = info
        if nome_norm:
            mapa_nome[nome_norm] = info

    for op in oportunidades_dict.get("oportunidades", []):
        sku = str(op.get("sku_selecionado", ""))
        url_op = str(op.get("url_afiliado", "") or "")
        nome_op = str(op.get("nome_produto", "") or "").strip().lower()[:40]
        extra = mapa_sku.get(sku) or mapa_url.get(url_op) or mapa_nome.get(nome_op)
        if extra:
            op["menor_preco_historico"] = extra["menor_preco_historico"]
            op["queda_real_percent"] = extra["queda_real_percent"]
            op["preco_medio_historico"] = extra["preco_medio_historico"]
            for campo in (
                "url_afiliado",
                "imagem_url",
                "preco_antigo",
                "categoria",
                "loja",
                "comissao_percent",
                "lucro_estimado_reais",
            ):
                if not op.get(campo) and extra.get(campo) is not None:
                    op[campo] = extra[campo]

    return oportunidades_dict


# --- 4. O Maestro da Orquestra (Bloco Principal Modificado) ---

if __name__ == "__main__":
    import argparse

    cli_parser = argparse.ArgumentParser(add_help=False)
    cli_parser.add_argument("--run-editorial", action="store_true", help="Força execução do bloco editorial RSS")
    args_cli, _ = cli_parser.parse_known_args()

    configurar_gemini(obrigatorio=True)

    conn_db = storage_db.conectar_db()
    try:
        storage_db.inicializar_db(conn_db)
        if (
            storage_db.contar_linhas_precos(storage_db.DEFAULT_DB_PATH) == 0
            and (os.path.exists("historico_precos.json") or os.path.exists("historico_postados.json"))
        ):
            storage_db.migrar_jsons_legados(conn_db)

        # Carrega histórico das últimas 72h (anti-repetição) direto do SQLite
        historico_postados = carregar_historico_postados(horas_validade=72, conn=conn_db)

        POOL_MAGALU = [
            "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
            "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
            "https://www.magazinevoce.com.br/magazinedealz/casa-inteligente/l/ci/",
            "https://www.magazinevoce.com.br/magazinedealz/celulares-e-smartphones/l/te/",
            "https://www.magazinevoce.com.br/magazinedealz/audio/l/ea/",
        ]
        # Sorteia 3 categorias da Magalu por execução para variar o catálogo
        URLS_BASE_MAGALU = random.sample(POOL_MAGALU, k=3)

        URL_ML_SOCIAL = (
            "https://www.mercadolivre.com.br/social/rafaelmelo825"
            "?matt_word=rafaelmelo825&matt_tool=61727000&forceInApp=true"
            "&ref=BNMjcwPk80fK3V%2FaZkPyOPSUZvCKY1lXkz7gVn1Lk0heRiFWKmz5M4HRd6c6Lzr"
            "%2FuAj586dkXZ2W8cbQV1wKa2LpVSemU7GsCrR5Mv0Ou4hXSI4eC47TaGOR2DuPSqEh81"
            "ti8ZXhLB0DAdcCStEU8%2B3IwqjwS6GC2byelKta%2BPLZ9yC8%2FTUySd5A%2ByhIJJQo"
            "9Gt9NvwD9Dle76xPtnsfM9P9NL%2Fj%2BQiaJVXOUEol2buRlVN5bpKt092dM8jij639Z3JOHg%3D%3D"
        )

        # Pool diversificado de buscas e subcategorias no Mercado Livre (rotação a cada disparo)
        POOL_ML = [
            ("https://lista.mercadolivre.com.br/games", "Games"),
            ("https://lista.mercadolivre.com.br/controle-sem-fio-gamer", "Games"),
            ("https://lista.mercadolivre.com.br/headset-gamer", "Games"),
            ("https://lista.mercadolivre.com.br/jogos-ps5-xbox-nintendo", "Games"),
            ("https://lista.mercadolivre.com.br/informatica", "Informática"),
            ("https://lista.mercadolivre.com.br/ssd-nvme", "Informática"),
            ("https://lista.mercadolivre.com.br/mouse-gamer", "Informática"),
            ("https://lista.mercadolivre.com.br/teclado-mecanico", "Informática"),
            ("https://lista.mercadolivre.com.br/monitor-gamer", "Informática"),
            ("https://lista.mercadolivre.com.br/celulares-telefones", "Celulares"),
            ("https://lista.mercadolivre.com.br/smartwatch", "Celulares"),
            ("https://lista.mercadolivre.com.br/eletronicos-audio-video", "Áudio & Geek"),
            ("https://lista.mercadolivre.com.br/fone-bluetooth-tws", "Áudio & Geek"),
            ("https://lista.mercadolivre.com.br/caixa-de-som-bluetooth", "Áudio & Geek"),
            ("https://lista.mercadolivre.com.br/casa-inteligente", "Casa Inteligente"),
            ("https://lista.mercadolivre.com.br/alexa-echo-dot", "Casa Inteligente"),
            ("https://lista.mercadolivre.com.br/fita-led-rgb-wifi", "Casa Inteligente"),
        ]
        # Sorteia 7 frentes diferentes do ML a cada execução para minerar novidades sempre
        CATEGORIAS_ML = random.sample(POOL_ML, k=7)

        all_dfs = []  
        logging.info("🚀 Iniciando motor Multi-Plataforma: Magalu + Mercado Livre...")

        # --- 1. RASPAGEM DA MAGAZINE LUIZA ---
        logging.info("--- Vasculhando vitrines da Magazine Luiza ---")
        for url_base in URLS_BASE_MAGALU:
            logging.info(f"Vasculhando vitrine Magalu: {url_base}")
            pagina_inicial = random.choice([1, 1, 2, 3])
            for pagina in range(pagina_inicial, pagina_inicial + 4):
                url_paginada = f"{url_base}?page={pagina}"
                logging.info(f"Magalu: Buscando página {pagina}...")

                df_pagina, _ = extrair_dados_magalu_live(url_paginada)

                if df_pagina is None or df_pagina.empty:
                    logging.info(f"Magalu: Fim dos produtos após a página {pagina-1}.")
                    break

                all_dfs.append(df_pagina)
                time.sleep(2)

        # --- 2. RASPAGEM DO MERCADO LIVRE ---
        logging.info("--- Vasculhando vitrine e ofertas do Mercado Livre ---")

        # 2.1 Vitrine Social Oficial do Rafael (Games, Mais Vendidos e Super Ofertas)
        try:
            logging.info("Mercado Livre: Extraindo produtos da Vitrine Social Oficial...")
            df_ml_social = extrair_dados_mercadolivre_live(URL_ML_SOCIAL, categoria_padrao="Games & Tech")
            if df_ml_social is not None and not df_ml_social.empty:
                logging.info(f"Mercado Livre: {len(df_ml_social)} produtos capturados da sua vitrine social!")
                all_dfs.append(df_ml_social)
        except Exception as e:
            logging.warning(f"Erro ao raspar vitrine social do ML: {e}")

        # 2.2 Categorias e Subnichos sorteados nesta rodada (alternando página 1 e página 2)
        for url_ml, cat_nome in CATEGORIAS_ML:
            try:
                url_alvo = f"{url_ml}_Desde_49" if random.random() < 0.4 else url_ml
                logging.info(f"Mercado Livre: Buscando {cat_nome} ({url_alvo})...")
                df_ml_cat = extrair_dados_mercadolivre_live(url_alvo, categoria_padrao=cat_nome)
                if df_ml_cat is None or df_ml_cat.empty:
                    if url_alvo != url_ml:
                        df_ml_cat = extrair_dados_mercadolivre_live(url_ml, categoria_padrao=cat_nome)
                if df_ml_cat is not None and not df_ml_cat.empty:
                    logging.info(f"Mercado Livre [{cat_nome}]: {len(df_ml_cat)} produtos encontrados.")
                    all_dfs.append(df_ml_cat)
                time.sleep(2)
            except Exception as e:
                logging.warning(f"Erro ao buscar categoria {cat_nome} do ML: {e}")

        if not all_dfs:
            logging.error("Nenhum produto extraído de nenhuma das plataformas. Verifique as conexões.")
            sys.exit(0)

        # Junta todas as tabelas e remove duplicatas por SKU
        df_produtos = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=["sku"])

        # Atualiza o Radar de Queda Real de Preço (180d via SQLite) ANTES do filtro de 72h
        df_produtos = enriquecer_e_atualizar_historico_precos(df_produtos, conn=conn_db, dias=180)

        # Filtra fora produtos já postados nas últimas 72h (fallback se < 25 inéditos)
        df_produtos = aplicar_filtro_anti_repeticao_72h(
            df_produtos, historico_postados, minimo_ineditos=25
        )

        logging.info(f"SUCESSO TOTAL! {len(df_produtos)} itens elegíveis de Magalu e Mercado Livre!")

        # Prepara o Score ponderando Queda Real (Radar 180d) + Desconto + Lucro em R$ + Sweet Spot + Jitter
        jitter = [random.uniform(0, 8) for _ in range(len(df_produtos))]
        df_produtos["score_qualidade"] = (
            (df_produtos["menor_preco_historico"].astype(int) * 45) +
            (df_produtos["queda_real_percent"].clip(upper=40) * 1.5) +
            (df_produtos["percentual_desconto"] * 0.35) +
            (df_produtos["lucro_estimado_reais"].clip(upper=80) * 0.40) +
            (df_produtos["preco_atual"].between(35, 500) * 25) +
            jitter
        )

        # Prepara o catálogo balanceado para a IA: Top Mercado Livre + Top Magalu
        df_ml = df_produtos[df_produtos["loja"] == "Mercado Livre"].sort_values(by="score_qualidade", ascending=False).head(80)
        df_magalu = df_produtos[df_produtos["loja"] == "Magalu"].sort_values(by="score_qualidade", ascending=False).head(40)

        if not df_ml.empty and not df_magalu.empty:
            df_ordenado_para_ia = pd.concat([df_ml, df_magalu], ignore_index=True)
        else:
            df_ordenado_para_ia = df_produtos.sort_values(by="score_qualidade", ascending=False).head(120)

        logging.info(f"Enviando {len(df_ordenado_para_ia)} candidatos inéditos para a IA escolher as 20 melhores (15 ML + 5 Magalu)...")
        json_input_data = gerar_json_para_ia(df_ordenado_para_ia.drop(columns=["score_qualidade"]))

        logging.info("\n=== CHAMANDO ALPHA-PROFIT (GEMINI) ===")
        json_final_output = gemini_fx(json_input_data)

        # Parsing blindado da resposta do Gemini com fallback determinístico caso falhe
        oportunidades_dict = parsear_resposta_gemini(
            json_final_output,
            candidatas_fallback=df_ordenado_para_ia,
            qtd_ml=15,
            qtd_magalu=5,
        )
        oportunidades_dict = enriquecer_oportunidades_com_radar(oportunidades_dict, df_produtos)

        # O envio de e-mail agora é garantido, independentemente da IA funcionar ou não.
        enviar_email_oportunidades(
            email_disparo=os.getenv("EMAIL_USER"),
            senha=os.getenv("EMAIL_PASSWORD"),
            email_destinatario="rsouza.melo18@gmail.com",
            oportunidades_dict=oportunidades_dict,
            df_todos_produtos=df_produtos 
        )

        # 🚀 DISPARO AUTOMÁTICO NO TELEGRAM (Canal de Ofertas / Grupo VIP)
        skus_postados = disparar_canal_telegram(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            oportunidades_dict=oportunidades_dict,
            df_todos_produtos=df_produtos,
            intervalo_segundos=3
        )

        # 🐦 DISPARO AUTOMÁTICO NO X (Twitter) — Modo Econômico (Top 2 sem URL = ~US$ 0,015/post)
        posts_x = disparar_x_twitter(
            oportunidades_dict=oportunidades_dict,
            df_todos_produtos=df_produtos,
            max_posts=2,
            intervalo_segundos=8
        ) or 0

        # 🧵 DISPARO AUTOMÁTICO NO THREADS (Meta) — 100% Gratuito (Top 5 com link direto + foto/preview)
        posts_threads = disparar_threads(
            oportunidades_dict=oportunidades_dict,
            df_todos_produtos=df_produtos,
            max_posts=5,
            intervalo_segundos=6
        ) or 0

        # 📘 DISPARO AUTOMÁTICO NA PÁGINA DO FACEBOOK — 100% Gratuito (Top 5 foto limpa + link no 1º comentário)
        posts_facebook = disparar_facebook_page(
            oportunidades_dict=oportunidades_dict,
            df_todos_produtos=df_produtos,
            max_posts=5,
            intervalo_segundos=6
        ) or 0

        # 🎬📱 DISPARO AUTOMÁTICO DE REELS (1 MP4) + STORIES (2 Cards 9:16) NA PÁGINA DO FACEBOOK
        reels_fb, stories_fb = disparar_facebook_reels_stories(
            oportunidades_dict=oportunidades_dict,
            df_todos_produtos=df_produtos,
            max_reels=1,
            max_stories=2
        )

        # Atualiza o histórico de 72h no SQLite para que os próximos disparos tragam novidades
        if skus_postados:
            canais_usados = ["telegram"]
            if posts_x:
                canais_usados.append("x")
            if posts_threads:
                canais_usados.append("threads")
            if posts_facebook:
                canais_usados.append("facebook")
            salvar_historico_postados(
                skus_postados,
                df_todos_produtos=df_produtos,
                conn=conn_db,
                canal_resumo=",".join(canais_usados),
            )

        # 📰 BLOCO EDITORIAL RSS (100% isolado — falha aqui nunca impacta ofertas nem SQLite)
        try:
            import rss_editorial
            res_editorial = rss_editorial.executar_bloco_editorial(
                conn=conn_db,
                oportunidades_dict=oportunidades_dict,
                forcar_execucao=args_cli.run_editorial,
            )
            logging.info(f"📰 Bloco Editorial RSS finalizado: {res_editorial}")
        except Exception as ed_err:
            logging.warning(f"Falha isolada no bloco editorial RSS (ofertas preservadas): {ed_err}")

        # 📊 TELEMETRIA & DASHBOARD HTML DE ACOMPANHAMENTO (Automático + Painel de Vendas Reais)
        try:
            from dashboard_generator import (
                obter_membros_telegram,
                obter_metricas_facebook_page,
                registrar_metricas_execucao,
                gerar_dashboard_html,
            )
            membros_tg = obter_membros_telegram(
                os.getenv("TELEGRAM_BOT_TOKEN"),
                os.getenv("TELEGRAM_CHAT_ID"),
            )
            fb_insights = obter_metricas_facebook_page(
                os.getenv("FACEBOOK_PAGE_TOKEN"),
                os.getenv("FACEBOOK_PAGE_ID"),
            )
            qtd_ml = int((df_produtos["loja"] == "Mercado Livre").sum()) if "loja" in df_produtos.columns else 0
            qtd_magalu = int((df_produtos["loja"] == "Magalu").sum()) if "loja" in df_produtos.columns else 0
            hist_metricas = registrar_metricas_execucao(
                raspados_ml=qtd_ml,
                raspados_magalu=qtd_magalu,
                postados_telegram=len(skus_postados),
                postados_threads=posts_threads,
                postados_facebook=posts_facebook,
                postados_x=posts_x,
                membros_telegram=membros_tg,
                fb_insights=fb_insights,
                oportunidades_dict=oportunidades_dict,
            )
            gerar_dashboard_html(hist_metricas)
        except Exception as dash_err:
            logging.warning(f"Falha ao atualizar dashboard de acompanhamento: {dash_err}")
    finally:
        conn_db.close()

    logging.info("Processo totalmente concluído! Confira seu e-mail, Telegram, X, Threads, Facebook e o Dashboard HTML.")
