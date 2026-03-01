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


# --- 2. Diretriz de Sistema (Prompt da IA) ---

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
* `comissao_percent`: (Opcional, mas VITAL) O percentual de comissão do afiliado.
* `url_afiliado`: O link de compra.

**4. PROCESSO DE DECISÃO ESTRATÉGICA (THOUGHT_PROCESS):**
Seu objetivo é identificar as 10 (DEZ) "Oportunidades de Ouro". Você deve priorizar com base nesta hierarquia de decisão:

* **Filtro 1: Aderência ao Ticket (Peso 40%)**: Selecione produtos onde `preco_atual` esteja na faixa de R$ 35,00 a R$ 500,00. Este é o nosso "Sweet Spot" de R$ 500.
* **Filtro 2: Percepção de Valor (Peso 35%)**: Priorize produtos com o MAIOR `percentual_desconto`. A escassez e a oportunidade (promoções) são os maiores gatilhos para o público "mar aberto".
* **Filtro 3: Potencial de Lucro (Peso 25%)**: Se `comissao_percent` estiver disponível, use-o como um desempate de alta prioridade. Maximize nosso R$ (Receita = preco_atual * comissao_percent).
* **Filtro 4: Relevância (Qualificador)**: O produto deve ser Banal? NÃO. Deve ter apelo imediato para o nicho (Games, Geek, Tech). Um mouse gamer obscuro em promoção é MELHOR que um fone de ouvido genérico.

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
      "url_afiliado": "URL_AFILIADO_AQUI",
      "razao_selecao": "Justificativa breve e lógica (Ex: 'Alto desconto + Sweet Spot de preço para hardware geek').",
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


# --- 3. Funções do Scraper ---

def extrair_dados_magalu_live(url):
    """
    Conecta-se à URL do Magazine Você, baixa o HTML ao vivo,
    extrai os dados dos produtos e a informação de páginas.
    Retorna: (DataFrame, int) ou (None, 1) em caso de falha.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text
    except requests.exceptions.HTTPError as http_err:
        logging.warning(f"Erro HTTP ao tentar acessar a URL: {http_err}")
        return None, 1
    except requests.exceptions.ConnectionError as conn_err:
        logging.warning(f"Erro de conexão: {conn_err}")
        return None, 1
    except requests.exceptions.Timeout:
        logging.warning("Erro: A conexão demorou demais (Timeout).")
        return None, 1
    except requests.exceptions.RequestException as e:
        logging.warning(f"Erro inesperado ao buscar a URL: {e}")
        return None, 1

    soup = BeautifulSoup(html_content, "html.parser")
    next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})

    if not next_data_script:
        logging.warning("Erro: Não foi possível encontrar a tag <script id='__NEXT_DATA__'>.")
        return None, 1

    try:
        json_data = json.loads(next_data_script.string)
    except json.JSONDecodeError as e:
        logging.warning(f"Erro ao decodificar o JSON da página: {e}")
        return None, 1

    try:
        search_data = json_data["props"]["pageProps"]["data"]["search"]
        product_list = search_data["products"]
        pagination_data = search_data.get("pagination", {})
        total_pages = pagination_data.get("pages", 1)
        current_page = pagination_data.get("page", 1)
    except KeyError:
        logging.warning("Erro: A estrutura do JSON da Magalu mudou. Não achei 'search' ou 'products'.")
        return None, 1

    processed_products = []
    base_url = "https://www.magazinevoce.com.br"

    for product in product_list:
        try:
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

            product_data = {
                "sku": product.get("id"),
                "nome_produto": product.get("title"),
                "preco_atual": preco_atual,
                "preco_antigo": preco_antigo,
                "percentual_desconto": percentual_desconto,
                "categoria": product.get("category", {}).get("name"),
                "comissao_percent": None,  
                "url_afiliado": base_url + product.get("url") if product.get("url") else None,
            }

            if product_data["sku"] and product_data["nome_produto"] and product_data["preco_atual"]:
                processed_products.append(product_data)

        except (ValueError, TypeError, AttributeError) as e:
            logging.warning(f"Erro ao processar o produto SKU {product.get('id')}: {e}. Pulando esse, véi.")
            continue

    if not processed_products:
        logging.info(f"Nenhum produto foi processado com sucesso na página {current_page}.")
        return pd.DataFrame(), total_pages

    df = pd.DataFrame(processed_products)
    columns_order = [
        "sku", "nome_produto", "preco_atual", "preco_antigo",
        "percentual_desconto", "categoria", "comissao_percent", "url_afiliado"
    ]
    df = df.reindex(columns=columns_order)

    return df, total_pages


def gerar_json_para_ia(df):
    """
    Converte o DataFrame final para a string JSON esperada pela IA.
    """
    if df is None or df.empty:
        logging.warning("DataFrame tá vazio, parceiro. Nenhum JSON gerado.")
        return None

    json_input_para_ia = df.to_json(orient="records", force_ascii=False, indent=2)
    return json_input_para_ia


# --- 4. Funções da IA (Gemini Otimizado) ---

def gemini_fx(dados_json):
    """
    Gera conteúdo usando a IA do Gemini usando System Instructions e Modo JSON.
    """
    try:
        logging.info("Iniciando a análise braba com o modelo Gemini...")
        
        # Modelo atualizado pro Flash (super rápido e de boa com os limites gratuitos)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash", 
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
                "HARASSMENT": "block_none",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "block_none",
                "HARM_CATEGORY_HATE_SPEECH": "block_none",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "block_none",
            },
        )
        
        logging.info("Análise concluída com sucesso! Tá na mão.")
        return result.text 

    except Exception as e:
        logging.error(f"Putz, a IA falhou: {e}")
        # Simplifiquei a resposta de erro pra garantir que seja um JSON limpo
        return f'{{"erro": "A análise da IA falhou", "motivo": "Erro interno na chamada do modelo."}}'


# --- 5. Funções de E-mail (Procedural) ---

def formatar_oportunidades_html(oportunidades_dict):
    """
    Transforma o dicionário de oportunidades naquele HTML bonitão pro e-mail.
    """
    html_out = ""
    try:
        for i, op in enumerate(oportunidades_dict.get("oportunidades", [])):
            copy = op.get("copy_venda", {})
            html_out += f"""
            <div class="opportunity-card" style="border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; padding: 16px; background-color: #f9f9f9;">
                <h3 style="color: #0086ff; margin-top: 0;">Oportunidade {i+1}: {op.get('nome_produto', 'N/A')}</h3>
                
                <p><strong>Preço Atual:</strong> <span style="color: #008000; font-weight: bold;">R$ {op.get('preco_atual', 0.0):.2f}</span></p>
                <p><strong>Desconto:</strong> <span style="color: #c00; font-weight: bold;">{op.get('percentual_desconto', 0.0)}% OFF</span></p>
                <p><strong>Razão da Seleção:</strong> <em style="color: #333;">"{op.get('razao_selecao', 'N/A')}"</em></p>
                
                <div class="copy-box" style="background-color: #fff; border: 1px dashed #ccc; padding: 12px; margin-top: 15px; border-radius: 4px;">
                    <h4 style="margin: 0 0 5px 0;">Copy para Venda:</h4>
                    <p style="margin: 2px 0;"><strong>Título:</strong> {copy.get('titulo', 'N/A')}</p>
                    <p style="margin: 2px 0;"><strong>Corpo:</strong> {copy.get('corpo', 'N/A')}</p>
                    <p style="margin: 2px 0;"><strong>CTA:</strong> {copy.get('cta', 'N/A')}</p>
                </div>
                
                <a href="{op.get('url_afiliado', '#')}" target="_blank" style="display: inline-block; background-color: #0086ff; color: #ffffff; padding: 10px 15px; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 15px;">
                    Ver Oferta (Link de Afiliado)
                </a>
            </div>
            """
        return html_out
    except Exception as e:
        logging.error(f"Erro ao formatar HTML das oportunidades: {e}")
        return "<p>Deu um errinho ao formatar o corpo do e-mail, véi.</p>"


def enviar_email_oportunidades(email_disparo, senha, email_destinatario, oportunidades_dict, host="smtp.gmail.com", porta=587):
    """
    Monta e envia o e-mail com as oportunidades identificadas pela IA.
    """
    if not email_disparo or not senha:
        logging.error("Credenciais de e-mail não fornecidas. Faltou o login e senha aí.")
        return

    assinatura_html = """
    <br><br>
    <div style="border-top: 1px solid #ddd; padding-top: 20px;">
      <p style="font-style: italic; color: #555;">Alpha-Profit AI Bot</p>
      <img src="https://ssl.gstatic.com/ui/v1/icons/mail/rfr/logo_gmail_lockup_default_1x_r5.png" alt="assinatura" style="width: 100px; height: auto;">
    </div>
    """

    assunto = f'Alpha-Profit: 10 Oportunidades de Ouro Detectadas! ({time.strftime("%d/%m/%Y")})'

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = email_disparo
    msg["To"] = email_destinatario

    oportunidades_html = formatar_oportunidades_html(oportunidades_dict)

    mensagem_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
            .container {{ width: 90%; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; }}
        </style>
    </head>
    <body>
        <div class="container">
            <p>Fala, líder,</p>
            <p>O "Alpha-Profit" AI Bot completou a varredura. Foram identificadas as <strong>10 oportunidades de ouro</strong> com maior potencial de conversão:</p>

            {oportunidades_html}

            <p>Bora vender!</p>
            {assinatura_html}
        </div>
    </body>
    </html>
    """
    msg.set_content(mensagem_html, subtype="html")

    try:
        with smtplib.SMTP(host, porta) as server:
            server.starttls()
            server.login(email_disparo, senha)
            server.send_message(msg)
            logging.info(f"Email enviado com sucesso para {email_destinatario}! Tá lá.")
    except smtplib.SMTPException as e:
        logging.error(f"Falha ao enviar e-mail (SMTP): {e}")
    except Exception as e:
        logging.error(f"Erro inesperado no envio de e-mail: {e}")


# --- 6. Execução Principal (Scraper + IA + E-mail) ---

if __name__ == "__main__":

    # --- ETAPA 1: SCRAPING ---
    URLS_BASE = [
        "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
        "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
        "https://www.magazinevoce.com.br/magazinedealz/casa-inteligente/l/ci/",
        "https://www.magazinevoce.com.br/magazinedealz/busca/lp/",
    ]

    all_dfs = []  
    logging.info(f"Iniciando scraping para {len(URLS_BASE)} categoria(s)... Bora lá!")

    for url_base in URLS_BASE:
        logging.info(f"\n[INICIANDO CATEGORIA]: {url_base}")
        total_pages = 1
        page_to_scrape = 1

        while page_to_scrape <= total_pages:
            if page_to_scrape == 1:
                current_url = url_base
            else:
                if "?" in url_base:
                    current_url = f"{url_base}&page={page_to_scrape}"
                else:
                    current_url = f"{url_base}?page={page_to_scrape}"

            logging.info(f"--- Raspando Página {page_to_scrape} de {total_pages} ---")

            df_pagina, paginas_detectadas = extrair_dados_magalu_live(current_url)

            if page_to_scrape == 1 and paginas_detectadas > 1:
                total_pages = paginas_detectadas
                logging.info(f"Total de páginas detectado pra essa categoria: {total_pages}")

            if df_pagina is not None and not df_pagina.empty:
                logging.info(f"Show: {len(df_pagina)} produtos adicionados da página {page_to_scrape}.")
                all_dfs.append(df_pagina) 
            else:
                logging.warning(f"Não rolou extrair dados da página {page_to_scrape} ou a página tava vazia.")

            page_to_scrape += 1
            time.sleep(1) 

    if not all_dfs:
        logging.error("Nenhum produto extraído, véi. O script vai parar por aqui.")
        sys.exit(0)

    # --- ETAPA 2: PROCESSAMENTO E GERAÇÃO DE INSUMO ---
    df_produtos = pd.concat(all_dfs, ignore_index=True)

    logging.info(f"\n[SUCESSO] Total de produtos extraídos: {len(df_produtos)}")

    df_produtos.to_csv("produtos_extraidos.csv", index=False, encoding="utf-8-sig")
    logging.info("Tudo salvo em 'produtos_extraidos.csv'")

    logging.info("Aplicando filtro estratégico pra mandar uma lista farta pra IA analisar...")

    df_produtos["prioridade_sweet_spot"] = df_produtos["preco_atual"].between(35, 500)
    df_ordenado_para_ia = df_produtos.sort_values(
        by=["prioridade_sweet_spot", "percentual_desconto"], ascending=[False, False]
    )
    
    # A MÁGICA TÁ AQUI, VÉI! Reduzi de 250 pra 80.
    # A IA não vai mais precisar pensar até o cérebro derreter e estourar o tempo.
    df_para_ia = df_ordenado_para_ia.head(80)

    logging.info(f"Total de produtos que vão pra IA analisar: {len(df_para_ia)}")

    df_para_ia = df_para_ia.drop(columns=["prioridade_sweet_spot"])
    json_input_data = gerar_json_para_ia(df_para_ia)

    if not json_input_data:
        logging.error("Falha ao gerar o JSON pra IA. Encerrando.")
        sys.exit(0)

    with open("insumo_ia.json", "w", encoding="utf-8") as f:
        f.write(json_input_data)
    logging.info("Insumo JSON salvo em 'insumo_ia.json'")

    # --- ETAPA 3: CHAMADA DA IA (ALPHA-PROFIT OTIMIZADO) ---
    logging.info("\n" + "=" * 25 + " CHAMANDO ALPHA-PROFIT (GEMINI) " + "=" * 25)
    logging.info("Analisando os dados pra pescar as 10 'Oportunidades de Ouro'...")

    json_final_output = gemini_fx(json_input_data)

    # --- ETAPA 4: RESULTADO FINAL E ARQUIVOS ---
    print("\n" + "=" * 25 + " RESPOSTA FINAL (JSON) " + "=" * 25)
    print(json_final_output)

    try:
        with open("oportunidades_alpha_profit.json", "w", encoding="utf-8") as f:
            f.write(json_final_output)
        logging.info("\n[SUCESSO] Oportunidades salvas em 'oportunidades_alpha_profit.json'")
    except Exception as e:
        logging.error(f"\nDeu erro ao tentar salvar o arquivo JSON final: {e}")

    # --- ETAPA 5: ENVIO DE E-MAIL ---
    logging.info("\n" + "=" * 25 + " ENVIANDO E-MAIL " + "=" * 25)

    EMAIL_DISPARO = os.getenv("EMAIL_USER")
    EMAIL_SENHA = os.getenv("EMAIL_PASSWORD")
    EMAIL_DESTINATARIO = "rafael.melo@novagencia.com"

    if EMAIL_DISPARO and EMAIL_SENHA:
        try:
            oportunidades_dict = json.loads(json_final_output)
            
            if "erro" in oportunidades_dict:
                 logging.error(f"A IA retornou um erro interno: {oportunidades_dict['motivo']}")
            else:
                enviar_email_oportunidades(
                    email_disparo=EMAIL_DISPARO,
                    senha=EMAIL_SENHA,
                    email_destinatario=EMAIL_DESTINATARIO,
                    oportunidades_dict=oportunidades_dict
                )
        except json.JSONDecodeError as e:
            logging.error(f"Não rolou decodificar o JSON final pro e-mail. Motivo: {e}")
            logging.error(f"Conteúdo que falhou: {json_final_output}")
        except Exception as e:
            logging.error(f"Falha geral ao enviar e-mail: {e}")
    else:
        logging.warning("Variáveis 'EMAIL_USER' e 'EMAIL_PASSWORD' não definidas. O e-mail não vai rolar.")
