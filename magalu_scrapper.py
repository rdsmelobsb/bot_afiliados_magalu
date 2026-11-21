import pandas as pd
import json
import requests
from bs4 import BeautifulSoup
import sys
import time
import logging
import os
import google.generativeai as genai
import smtplib
from email.message import EmailMessage
import csv 
from urllib.parse import urlparse, parse_qs 
import re 
import random
from datetime import datetime, timedelta
from io import BytesIO

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

try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logging.error("Opa! Defina a chave antes de rodar: export GEMINI_API_KEY='SUA_CHAVE'")
        sys.exit(1)  
    genai.configure(api_key=api_key)
    logging.info("API do Gemini configurada com sucesso. Tudo nos conformes!")
except Exception as e:
    logging.error(f"Deu ruim ao configurar a API do Gemini: {e}")
    sys.exit(1)


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
* `url_afiliado`: O link de compra.

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
Sua resposta deve ser um JSON ESTRITO. O JSON deve conter uma chave principal "oportunidades" que é um array de EXATAMENTE 20 objetos (15 do Mercado Livre e 5 da Magalu). Intercale as ofertas para manter uma experiência dinâmica no canal!

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
      "url_afiliado": "URL_AFILIADO_AQUI",
      "razao_selecao": "Justificativa breve e lógica (Ex: 'Alto desconto + comissão atrativa no sweet spot de hardware').",
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

    # Melhora resolução de miniaturas para alta qualidade (800x600)
    if img_url:
        img_url = img_url.replace("/186x140/", "/800x600/").replace("/280x210/", "/800x600/")

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
    return df.to_json(orient="records", force_ascii=False, indent=2)


def gemini_fx(dados_json):
    try:
        logging.info("Iniciando a análise braba com o modelo Gemini...")
        model = genai.GenerativeModel(
            model_name="gemini-4-hydrogen",
            system_instruction=ALPHA_PROFIT_SYSTEM_PROMPT,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.65
            }
        )
        prompt_usuario = f"Analise o catálogo abaixo e retorne EXATAMENTE 20 Oportunidades de Ouro (15 do Mercado Livre e 5 da Magalu), priorizando variedade de produtos e categorias, seguindo as regras do sistema:\n\n{dados_json}"
        result = model.generate_content(
            prompt_usuario,
            safety_settings={
                "HARASSMENT": "block_none", "HARM_CATEGORY_SEXUALLY_EXPLICIT": "block_none",
                "HARM_CATEGORY_HATE_SPEECH": "block_none", "HARM_CATEGORY_DANGEROUS_CONTENT": "block_none",
            },
        )
        logging.info("Análise concluída com sucesso!")
        return result.text 
    except Exception as e:
        logging.error(f"Putz, a IA falhou: {e}")
        return f'{{"erro": "A análise da IA falhou", "motivo": "{e}"}}'


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
    texto_caption = f"{badge}\n🔥 <b>{titulo}</b>\n\n"
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

    linhas = [f"{badge}", f"🔥 {titulo}", ""]
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

    # Seleciona as Top N ofertas mais chamativas (maior desconto + maior lucro estimado)
    selecionadas = sorted(
        oportunidades,
        key=lambda op: (
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

    linhas = [f"{badge}", f"🔥 {titulo}", ""]
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

    # Seleciona as Top N ofertas (priorizando desconto + lucro estimado)
    selecionadas = sorted(
        oportunidades,
        key=lambda op: (
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

    linhas = [f"{badge}", f"🔥 {titulo}", ""]
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

    # Seleciona as Top N ofertas (desconto + lucro estimado)
    selecionadas = sorted(
        oportunidades,
        key=lambda op: (
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


# --- 3.5. Controle de Histórico Anti-Repetição (72 horas) ---

HISTORICO_ARQUIVO = "historico_postados.json"


def carregar_historico_postados(horas_validade=72):
    """Carrega SKUs postados recentemente e expira automaticamente os mais antigos que horas_validade."""
    if not os.path.exists(HISTORICO_ARQUIVO):
        return {}
    try:
        with open(HISTORICO_ARQUIVO, "r", encoding="utf-8") as f:
            dados = json.load(f)
        limite = datetime.now() - timedelta(hours=horas_validade)
        ativo = {}
        for sku, ts_str in dados.items():
            try:
                if datetime.fromisoformat(ts_str) > limite:
                    ativo[sku] = ts_str
            except Exception:
                continue
        logging.info(f"Histórico anti-repetição carregado: {len(ativo)} ofertas bloqueadas nas últimas {horas_validade}h.")
        return ativo
    except Exception as e:
        logging.warning(f"Não foi possível ler {HISTORICO_ARQUIVO}: {e}")
        return {}


def salvar_historico_postados(historico_atual, novos_skus):
    """Adiciona os SKUs recém-postados ao histórico local (persistido via cache no GitHub Actions)."""
    agora = datetime.now().isoformat()
    for sku in novos_skus:
        if sku:
            historico_atual[str(sku)] = agora
    try:
        with open(HISTORICO_ARQUIVO, "w", encoding="utf-8") as f:
            json.dump(historico_atual, f, ensure_ascii=False, indent=2)
        logging.info(f"Histórico atualizado: {len(novos_skus)} novas ofertas registradas ({len(historico_atual)} no total).")
    except Exception as e:
        logging.warning(f"Erro ao salvar {HISTORICO_ARQUIVO}: {e}")


# --- 4. O Maestro da Orquestra (Bloco Principal Modificado) ---

if __name__ == "__main__":

    # Carrega histórico das últimas 72h para não repetir as mesmas ofertas
    historico_postados = carregar_historico_postados(horas_validade=72)

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
        # Começa em página 1 ou sorteia uma janela de páginas (ex: 1..4 ou 2..5) para variar
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
            # 40% das vezes mergulha na página 2 (_Desde_49) para encontrar achados menos óbvios
            url_alvo = f"{url_ml}_Desde_49" if random.random() < 0.4 else url_ml
            logging.info(f"Mercado Livre: Buscando {cat_nome} ({url_alvo})...")
            df_ml_cat = extrair_dados_mercadolivre_live(url_alvo, categoria_padrao=cat_nome)
            if df_ml_cat is None or df_ml_cat.empty:
                # Fallback para página 1 se página 2 vier vazia
                if url_alvo != url_ml:
                    df_ml_cat = extrair_dados_mercadolivre_live(url_ml, categoria_padrao=cat_nome)
            if df_ml_cat is not None and not df_ml_cat.empty:
                logging.info(f"Mercado Livre [{cat_nome}]: {len(df_ml_cat)} produtos encontrados.")
                all_dfs.append(df_ml_cat)
            time.sleep(2)
        except Exception as e:
            logging.warning(f"Erro ao buscar categoria {cat_nome} do ML: {e}")

    # Verifica se pegou produtos no total
    if not all_dfs:
        logging.error("Nenhum produto extraído de nenhuma das plataformas. Verifique as conexões.")
        sys.exit(0)

    # Junta todas as tabelas e remove duplicatas por SKU
    df_produtos = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=["sku"])
    total_bruto = len(df_produtos)

    # Filtra fora produtos já postados nas últimas 72h (Anti-Repetição)
    if historico_postados:
        df_ineditos = df_produtos[~df_produtos["sku"].astype(str).isin(historico_postados.keys())]
        if len(df_ineditos) >= 25:
            logging.info(f"Filtro anti-repetição aplicado: {total_bruto - len(df_ineditos)} ofertas recentes ignoradas. Restaram {len(df_ineditos)} inéditas!")
            df_produtos = df_ineditos.copy()
        else:
            logging.info("Poucos produtos inéditos nesta rodada; mantendo catálogo completo com rotação por jitter.")

    logging.info(f"SUCESSO TOTAL! {len(df_produtos)} itens elegíveis de Magalu e Mercado Livre!")
    
    # Prepara o Score ponderando Desconto + Lucro em R$ + Sweet Spot + Jitter de diversidade
    jitter = [random.uniform(0, 8) for _ in range(len(df_produtos))]
    df_produtos["score_qualidade"] = (
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

    # Tentamos ler a resposta da IA. Se der erro, 'oportunidades_dict' fica vazio.
    try:
        oportunidades_dict = json.loads(json_final_output)
    except Exception as e:
        logging.warning(f"Erro ao interpretar JSON da IA. Ativando Contingência. Erro: {e}")
        oportunidades_dict = {}

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

    # Atualiza o histórico de 72h para que os próximos disparos tragam novidades
    if skus_postados:
        salvar_historico_postados(historico_postados, skus_postados)

    # 📊 TELEMETRIA & DASHBOARD HTML DE ACOMPANHAMENTO (Automático + Painel de Vendas Reais)
    try:
        from dashboard_generator import (
            obter_membros_telegram,
            registrar_metricas_execucao,
            gerar_dashboard_html,
        )
        membros_tg = obter_membros_telegram(
            os.getenv("TELEGRAM_BOT_TOKEN"),
            os.getenv("TELEGRAM_CHAT_ID"),
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
            oportunidades_dict=oportunidades_dict,
        )
        gerar_dashboard_html(hist_metricas)
    except Exception as dash_err:
        logging.warning(f"Falha ao atualizar dashboard de acompanhamento: {dash_err}")
    
    logging.info("Processo totalmente concluído! Confira seu e-mail, Telegram, X, Threads, Facebook e o Dashboard HTML.")
