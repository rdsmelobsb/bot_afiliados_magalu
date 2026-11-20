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
* `categoria`: (Ex: 'Games', 'Hardware', 'Colecionáveis', 'Tecnologia').
* `seller_id`: Identificador do vendedor ('magazineluiza' para 1P direto ou nome da loja parceira para 3P).
* `comissao_percent`: O percentual de comissão do afiliado (ex: 5.0 para 5%).
* `lucro_estimado_reais`: O valor líquido estimado em R$ de comissão por venda (preco_atual * comissao_percent / 100).
* `url_afiliado`: O link de compra.

**4. PROCESSO DE DECISÃO ESTRATÉGICA (THOUGHT_PROCESS):**
Seu objetivo é identificar as 10 (DEZ) "Oportunidades de Ouro". Você deve priorizar com base nesta hierarquia de decisão:

* **Filtro 1: Aderência ao Ticket (Peso 35%)**: Selecione produtos onde `preco_atual` esteja na faixa de R$ 35,00 a R$ 500,00 (Sweet Spot de impulso).
* **Filtro 2: Percepção de Valor (Peso 35%)**: Priorize produtos com o MAIOR `percentual_desconto`. A escassez e o desconto forte são os maiores gatilhos.
* **Filtro 3: Potencial de Lucro Líquido (Peso 30%)**: Maximize a receita real do afiliado em R$ (`lucro_estimado_reais`). Um produto com bom desconto e comissão de R$ 25 é muito melhor que um que paga R$ 1.
* **Filtro 4: Relevância (Qualificador)**: O produto deve ter apelo imediato para o nicho (Games, Geek, Tech, Smart House).

**5. DIRETRIZ DE SAÍDA (OUTPUT):**
Sua resposta deve ser um JSON ESTRITO. O JSON deve conter uma chave principal "oportunidades" que é um array de 10 objetos.

**Cumpra este formato EXATAMENTE:**
{
  "oportunidades": [
    {
      "sku_selecionado": "SKU_DO_PRODUTO_1",
      "nome_produto": "Nome do Produto 1",
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
                "sku": product.get("id"),
                "nome_produto": nome,
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
                "temperature": 0.3
            }
        )
        prompt_usuario = f"Analise o catálogo abaixo e retorne as 10 Oportunidades de Ouro seguindo as regras do sistema:\n\n{dados_json}"
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

            html_out += f"""
            <div style="border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; padding: 16px; background-color: #f9f9f9;">
                <h3 style="color: #0086ff; margin-top: 0;">Oportunidade {i+1}: {op.get('nome_produto', 'N/A')}</h3>
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
        msg["Subject"] = f'Alpha-Profit: 10 Oportunidades! ({time.strftime("%d/%m/%Y")})'
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

    # Monta a legenda formatada com HTML suportado pelo Telegram
    texto_caption = f"🔥 <b>{titulo}</b>\n\n"
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
                [{"text": "🛒 GARANTIR OFERTA NO MAGALU", "url": url_afiliado}]
            ]
        }

    # Tentativa 1: Enviar com a Foto do produto em alta resolução
    if imagem_url:
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
                logging.info(f"Oportunidade postada com foto no Telegram: {titulo[:35]}...")
                return True
            else:
                logging.warning(f"Telegram retornou status {resp.status_code} na foto: {resp.text}. Tentando em texto...")
        except Exception as e:
            logging.warning(f"Erro ao postar foto no Telegram: {e}. Tentando apenas texto...")

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
    Percorre a lista de 10 oportunidades e dispara uma a uma no canal do Telegram,
    com um espaçamento de segurança para evitar rate limits.
    """
    if not bot_token or not chat_id:
        logging.warning("Credenciais do Telegram ausentes (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID). Pulando envio para o canal.")
        return

    oportunidades = oportunidades_dict.get("oportunidades", [])
    if not oportunidades:
        logging.info("Nenhuma oportunidade para enviar ao Telegram.")
        return

    # Indexa imagem_url e preco_antigo por SKU
    mapa_produtos = {}
    if df_todos_produtos is not None and not df_todos_produtos.empty:
        for _, row in df_todos_produtos.iterrows():
            sku = str(row.get("sku", ""))
            mapa_produtos[sku] = {
                "imagem_url": row.get("imagem_url"),
                "preco_antigo": row.get("preco_antigo")
            }

    logging.info(f"🚀 Iniciando postagem de {len(oportunidades)} ofertas no Canal do Telegram...")
    sucessos = 0

    for i, op in enumerate(oportunidades):
        sku = str(op.get("sku_selecionado", ""))
        extra = mapa_produtos.get(sku, {})
        imagem_url = op.get("imagem_url") or extra.get("imagem_url")
        preco_antigo = op.get("preco_antigo") or extra.get("preco_antigo")

        if enviar_oportunidade_telegram(bot_token, chat_id, op, imagem_url=imagem_url, preco_antigo=preco_antigo):
            sucessos += 1

        if i < len(oportunidades) - 1:
            time.sleep(intervalo_segundos)

    logging.info(f"🎉 Finalizado: {sucessos}/{len(oportunidades)} ofertas publicadas no Telegram com sucesso!")


# --- 4. O Maestro da Orquestra (Bloco Principal Modificado) ---

if __name__ == "__main__":

    URLS_BASE = [
        "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
        "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
        "https://www.magazinevoce.com.br/magazinedealz/casa-inteligente/l/ci/",
    ]

    all_dfs = []  
    logging.info("Iniciando raspagem infinita! Rumo ao fim do catálogo...")

    # NOVA LÓGICA DE PAGINAÇÃO: INFINITA (While True)
    for url_base in URLS_BASE:
        logging.info(f"--- Vasculhando a vitrine: {url_base} ---")
        pagina = 1
        
        while True:
            # A url_paginada ganha o ?page=X (na primeira página pode ter, não afeta a loja)
            url_paginada = f"{url_base}?page={pagina}"
            logging.info(f"Buscando página {pagina}...")
            
            df_pagina, _ = extrair_dados_magalu_live(url_paginada)
            
            # Condição de parada (Break): Se o df vier vazio, é porque acabaram os produtos
            if df_pagina is None or df_pagina.empty:
                logging.info(f"Fim da linha! Não há mais produtos após a página {pagina-1}.")
                break # Pula para a próxima categoria
                
            all_dfs.append(df_pagina)
            
            pagina += 1
            # Pausa estratégica para a loja não bloquear a gente
            time.sleep(2)

    # Verifica se pegou alguma coisa no total
    if not all_dfs:
        logging.error("Nenhum produto extraído. Verifique as URLs ou bloqueios.")
        sys.exit(0)

    # Junta todas as tabelas raspadas em uma só super tabela
    df_produtos = pd.concat(all_dfs, ignore_index=True)
    logging.info(f"SUCESSO TOTAL! {len(df_produtos)} itens raspados de todas as categorias!")
    
    # Prepara o Top 100 ponderando Desconto + Lucro em R$ no bolso + Sweet Spot
    df_produtos["score_qualidade"] = (
        (df_produtos["percentual_desconto"] * 0.35) +
        (df_produtos["lucro_estimado_reais"].clip(upper=80) * 0.40) +
        (df_produtos["preco_atual"].between(35, 500) * 25)
    )
    
    df_ordenado_para_ia = df_produtos.sort_values(by="score_qualidade", ascending=False).head(100)
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
    disparar_canal_telegram(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        oportunidades_dict=oportunidades_dict,
        df_todos_produtos=df_produtos,
        intervalo_segundos=3
    )
    
    logging.info("Processo totalmente concluído! Pode ir ver seu e-mail e seu canal do Telegram.")
