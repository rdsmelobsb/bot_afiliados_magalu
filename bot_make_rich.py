import pandas as pd
import json
import requests
from bs4 import BeautifulSoup
import sys
import time
import logging
import os
import google.generativeai as genai
import smtplib  # Importado para o e-mail
from email.message import EmailMessage  # Importado para o e-mail

# --- 1. Configuração do Logging e API ---

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logging.error("A variável de ambiente 'GOOGLE_API_KEY' não foi definida.")
        logging.error("Defina-a antes de rodar: export GOOGLE_API_KEY='SUA_CHAVE'")
        sys.exit(1)  # Encerra o script se a chave não estiver presente
    genai.configure(api_key=api_key)
    logging.info("API do Gemini configurada com sucesso.")
except Exception as e:
    logging.error(f"Erro ao configurar a API do Gemini: {e}")
    sys.exit(1)


# --- 2. Diretriz de Sistema (Prompt da IA) ---

ALPHA_PROFIT_SYSTEM_PROMPT = """
## DIRETRIZ DE SISTEMA: PROJETO "ALPHA-PROFIT"

**1. IDENTIDADE (ROLE):**
Você é o "Alpha-Profit", um C-Level AI Strategist especializado em e-commerce de afiliados (Nicho: Games, Geek, Tech) com um único KPI: maximizar a Receita Bruta de Afiliados. Sua meta de curto prazo é gerar R$ 10.000.

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

* **Filtro 1: Aderência ao Ticket (Peso 40%)**: Selecione produtos onde `preco_atual` esteja na faixa de R$ 35,00 a R$ 500,00. Este é o nosso "Sweet Spot" de R$ 350.
* **Filtro 2: Percepção de Valor (Peso 35%)**: Priorize produtos com o MAIOR `percentual_desconto`. A escassez e a oportunidade (promoções) são os maiores gatilhos para o público "mar aberto".
* **Filtro 3: Potencial de Lucro (Peso 25%)**: Se `comissao_percent` estiver disponível, use-o como um desempate de alta prioridade. Maximize nosso R$ (Receita = preco_atual * comissao_percent).
* **Filtro 4: Relevância (Qualificador)**: O produto deve ser Banal? NÃO. Deve ter apelo imediato para o nicho (Games, Geek, Tech). Um mouse gamer obscuro em promoção é MELHOR que um fone de ouvido genérico.

**5. DIRETRIZ DE SAÍDA (OUTPUT):**
Sua resposta deve ser um JSON ESTRITO, sem texto introdutório ou final. O JSON deve conter uma chave principal "oportunidades" que é um array de 10 objetos.

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
    },
    {
      "sku_selecionado": "SKU_DO_PRODUTO_2",
      "nome_produto": "Nome do Produto 2",
      "preco_atual": 55.00,
      "percentual_desconto": 25,
      "url_afiliado": "URL_AFILIADO_AQUI_2",
      "razao_selecao": "...",
      "copy_venda": {
        "titulo": "...",
        "corpo": "...",
        "cta": "..."
      }
    },
    // ... (mais 8 oportunidades seguindo o mesmo padrão)
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
    extrai os dados dos produtos E a informação de paginas,
    cria um DataFrame e o retorna junto com o total de páginas.

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
        logging.warning(
            "Erro: Não foi possível encontrar a tag <script id='__NEXT_DATA__'>."
        )
        return None, 1

    try:
        json_data = json.loads(next_data_script.string)
    except json.JSONDecodeError as e:
        logging.warning(f"Erro ao decodificar o JSON: {e}")
        return None, 1

    try:
        search_data = json_data["props"]["pageProps"]["data"]["search"]
        product_list = search_data["products"]

        pagination_data = search_data.get("pagination", {})
        total_pages = pagination_data.get("pages", 1)
        current_page = pagination_data.get("page", 1)

    except KeyError:
        logging.warning(
            "Erro: A estrutura do JSON mudou. Não foi possível encontrar 'search' ou 'products'"
        )
        logging.warning("['props']['pageProps']['data']['search']['products']")
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
                "comissao_percent": None,  # (Ainda não disponível publicamente)
                "url_afiliado": base_url + product.get("url")
                if product.get("url")
                else None,
            }

            if (
                product_data["sku"]
                and product_data["nome_produto"]
                and product_data["preco_atual"]
            ):
                processed_products.append(product_data)

        except (ValueError, TypeError, AttributeError) as e:
            logging.warning(
                f"Erro ao processar o produto SKU {product.get('id')}: {e}. Pulando."
            )
            continue

    if not processed_products:
        logging.info(
            f"Nenhum produto foi processado com sucesso na página {current_page}."
        )
        return pd.DataFrame(), total_pages

    df = pd.DataFrame(processed_products)
    columns_order = [
        "sku",
        "nome_produto",
        "preco_atual",
        "preco_antigo",
        "percentual_desconto",
        "categoria",
        "comissao_percent",
        "url_afiliado",
    ]
    df = df.reindex(columns=columns_order)

    return df, total_pages


def gerar_json_para_ia(df):
    """
    Converte o DataFrame final para a string JSON que o "Alpha-Profit" espera.
    """
    if df is None or df.empty:
        logging.warning("DataFrame está vazio. Nenhum JSON gerado.")
        return None

    json_input_para_ia = df.to_json(orient="records", force_ascii=False, indent=2)
    return json_input_para_ia


# --- 4. Funções da IA (Gemini) ---


def gemini_fx(prompt):
    """
    Tenta gerar conteúdo usando uma lista de modelos Gemini em fallback.
    """
    result = None

    modelos_a_tentar = ["gemini-3-pro-preview"]

    for modelo_nome in modelos_a_tentar:
        try:
            logging.info(f"Tentando usar o modelo: {modelo_nome}")
            model = genai.GenerativeModel(modelo_nome)
            result = model.generate_content(
                prompt,
                safety_settings={
                    "HARASSMENT": "block_none",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "block_none",
                    "HARM_CATEGORY_HATE_SPEECH": "block_none",
                    "HARM_CATEGORY_DANGEROUS_CONTENT": "block_none",
                },
            )
            logging.info(f"Sucesso com o modelo: {modelo_nome}")
            return result.text

        except Exception as e:
            logging.warning(f"Modelo {modelo_nome} falhou: {e}")
            continue

    # Se todos os modelos falharem
    logging.error("Todos os modelos Gemini falharam")
    if result and hasattr(result, "prompt_feedback"):
        return f'{{"erro": "A análise da IA falhou", "motivo": "{result.prompt_feedback}"}}'
    return (
        f'{{"erro": "A análise da IA não pôde ser gerada. Todos os modelos falharam."}}'
    )


def extrair_json_da_resposta(texto_ia):
    """
    Limpa a resposta da IA, extraindo apenas o bloco JSON.
    """
    try:
        # Tenta encontrar o JSON delimitado
        if "```json" in texto_ia:
            inicio = texto_ia.find("```json") + 7  # Pula o ```json
            fim = texto_ia.rfind("```")
            json_str = texto_ia[inicio:fim].strip()
        else:
            # Se não, pega o primeiro '{' e o último '}'
            inicio = texto_ia.index("{")
            fim = texto_ia.rindex("}") + 1
            json_str = texto_ia[inicio:fim]

        # Valida se é um JSON
        json_validado = json.loads(json_str)
        # Retorna o JSON "bonito" (pretty-print)
        return json.dumps(json_validado, indent=2, ensure_ascii=False)

    except (ValueError, json.JSONDecodeError) as e:
        logging.error(f"Não foi possível extrair um JSON válido da resposta da IA: {e}")
        logging.error(f"Resposta recebida: {texto_ia}")
        return f'{{"erro": "A resposta da IA não era um JSON válido.", "resposta_recebida": "{texto_ia}"}}'


# --- 5. Classe de E-mail ---


class MandaEmail:
    def __init__(self, email_disparo, senha, host="smtp.gmail.com", porta=587):
        if not email_disparo or not senha:
            raise ValueError(
                "EMAIL_DISPARO e EMAIL_SENHA devem ser definidos nas variáveis de ambiente."
            )

        self.email_disparo = email_disparo
        self.senha = senha
        self.host = host
        self.porta = porta
        self.assinatura_html = """
<br><br>
<div style="border-top: 1px solid #ddd; padding-top: 20px;">
  <p style="font-style: italic; color: #555;">Alpha-Profit AI Bot</p>
  <img src="https://ci3.googleusercontent.com/meips/ADKq_NZNnO1Uv8e0QiAHUG--ckV2LDa1U2j3GOLJs8Z-yXbEGFVoEXuTza7ZsxBT3ViSHgUgX8yrpTHkrTnujVq5Kp94rWhDRryaeSIYQJv4ooOR4a8fSp8SAAw=s0-d-e1-ft#https://novasb.com.br/wp-content/uploads/assinatura/RAFAELMELO.png" alt="assinatura" style="width: 150px; height: auto;">
</div>
"""

    def _formatar_oportunidades_html(self, oportunidades_dict):
        """Helper para transformar o JSON de oportunidades em HTML."""
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
            return "<p>Erro ao formatar o corpo do e-mail.</p>"

    def enviar_email_oportunidades(self, oportunidades_dict, email_destinatario):
        ASSUNTO = f'Alpha-Profit: 10 Oportunidades de Ouro Detectadas! ({time.strftime("%d/%m/%Y")})'

        msg = EmailMessage()
        msg["Subject"] = ASSUNTO
        msg["From"] = self.email_disparo
        msg["To"] = email_destinatario

        # Gera o corpo HTML a partir do dicionário de oportunidades
        oportunidades_html = self._formatar_oportunidades_html(oportunidades_dict)

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
        <p>Olá,</p>
        <p>O "Alpha-Profit" AI Bot completou a varredura e análise. Foram identificadas as <strong>10 oportunidades de ouro</strong> com maior potencial de conversão com base em suas diretrizes:</p>

        {oportunidades_html}

        <p>Abs,</p>
        {self.assinatura_html}
    </div>
</body>
</html>
"""
        msg.set_content(mensagem_html, subtype="html")

        try:
            with smtplib.SMTP(self.host, self.porta) as server:
                server.starttls()
                server.login(self.email_disparo, self.senha)
                server.send_message(msg)
                logging.info(
                    f"Email de oportunidades enviado com sucesso para {email_destinatario}!"
                )
        except smtplib.SMTPException as e:
            logging.error(f"Falha ao enviar e-mail: {e}")
        except Exception as e:
            logging.error(f"Erro inesperado no envio de e-mail: {e}")


# --- 6. Execução Principal (Scraper + IA + E-mail) ---

if __name__ == "__main__":

    # --- ETAPA 1: SCRAPING ---
    # Lista de URLs base para raspar (Nicho: Games, Geek, Tech)
    URLS_BASE = [
        "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
        "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
        "https://www.magazinevoce.com.br/magazinedealz/casa-inteligente/l/ci/",
    ]

    all_dfs = []  # Lista para acumular DataFrames de TODAS as categorias e páginas

    logging.info(f"Iniciando scraping para {len(URLS_BASE)} categoria(s)...")

    # Loop principal para iterar sobre cada URL base
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
                logging.info(
                    f"Total de páginas detectado para esta categoria: {total_pages}"
                )

            if df_pagina is not None and not df_pagina.empty:
                logging.info(
                    f"Sucesso: {len(df_pagina)} produtos adicionados da página {page_to_scrape}."
                )
                all_dfs.append(df_pagina)  # Adiciona o df da página à lista total
            else:
                logging.warning(
                    f"Não foi possível extrair dados da página {page_to_scrape} ou a página estava vazia."
                )

            page_to_scrape += 1
            time.sleep(1)  # Pausa de 1 segundo (boa prática)

    if not all_dfs:
        logging.error(
            "Nenhum produto foi extraído de nenhuma página/categoria. Encerrando."
        )
        sys.exit(0)

    # --- ETAPA 2: PROCESSAMENTO E GERAÇÃO DE INSUMO ---

    # Concatena TODOS os DataFrames (de todas as páginas e categorias) em um só
    df_produtos = pd.concat(all_dfs, ignore_index=True)

    logging.info(
        f"\n[SUCESSO] Total de produtos extraídos de {len(URLS_BASE)} categoria(s): {len(df_produtos)}"
    )

    df_produtos.to_csv("produtos_extraidos.csv", index=False, encoding="utf-8-sig")
    logging.info("DataFrame completo salvo em 'produtos_extraidos.csv'")

    # --- Filtro Estratégico (Top 50 do TOTAL) ---

    logging.info(
        f"Aplicando filtro estratégico para selecionar os 50 melhores produtos para a IA..."
    )

    # 1. Cria uma coluna de prioridade para o "Sweet Spot" (R$ 35-500)
    df_produtos["prioridade_sweet_spot"] = df_produtos["preco_atual"].between(35, 500)

    # 2. Ordena pela prioridade (True vem antes de False) e depois pelo maior desconto
    df_ordenado_para_ia = df_produtos.sort_values(
        by=["prioridade_sweet_spot", "percentual_desconto"], ascending=[False, False]
    )

    # 3. Seleciona os 50 melhores (ou menos, se o total for menor)
    df_para_ia = df_ordenado_para_ia.head(50)

    logging.info(f"Total de produtos após filtro para IA: {len(df_para_ia)}")

    # Remove a coluna auxiliar antes de enviar para a IA
    df_para_ia = df_para_ia.drop(columns=["prioridade_sweet_spot"])

    # Passa o DataFrame filtrado e ordenado para a função de geração de JSON
    json_input_data = gerar_json_para_ia(df_para_ia)

    if not json_input_data:
        logging.error("Falha ao gerar o JSON de insumo para a IA. Encerrando.")
        sys.exit(0)

    with open("insumo_ia.json", "w", encoding="utf-8") as f:
        f.write(json_input_data)
    logging.info("Insumo JSON (top 50) salvo em 'insumo_ia.json'")

    # --- ETAPA 3: CHAMADA DA IA (ALPHA-PROFIT) ---

    final_prompt = f"""
    {ALPHA_PROFIT_SYSTEM_PROMPT}

    ---
    [INPUT_DATA]
    ---
    {json_input_data}
    """

    logging.info("\n" + "=" * 25 + " CHAMANDO ALPHA-PROFIT (GEMINI) " + "=" * 25)
    logging.info(
        "Analisando dados (Top 50) para encontrar as 10 'Oportunidades de Ouro'..."
    )

    api_response = gemini_fx(final_prompt)

    logging.info("Resposta da IA recebida. Limpando e formatando...")
    json_final_output = extrair_json_da_resposta(api_response)

    # --- ETAPA 4: RESULTADO FINAL E ARQUIVOS ---

    print("\n" + "=" * 25 + " RESPOSTA FINAL (JSON) " + "=" * 25)
    print(json_final_output)

    try:
        with open("oportunidades_alpha_profit.json", "w", encoding="utf-8") as f:
            f.write(json_final_output)
        logging.info(
            "\n[SUCESSO] Oportunidades salvas em 'oportunidades_alpha_profit.json'"
        )
    except Exception as e:
        logging.error(f"\nErro ao salvar arquivo JSON final: {e}")

    # --- ETAPA 5: ENVIO DE E-MAIL (NOVA) ---

    logging.info("\n" + "=" * 25 + " ENVIANDO E-MAIL " + "=" * 25)

    # Carrega as credenciais de e-mail do ambiente
    EMAIL_DISPARO = os.getenv("EMAIL_USER")
    EMAIL_SENHA = os.getenv("EMAIL_PASSWORD")
    EMAIL_DESTINATARIO = (
        "rafael.melo@novagencia.com"  # <--- Defina o e-mail de destino aqui
    )

    if EMAIL_DISPARO and EMAIL_SENHA:
        try:
            # Carrega o dicionário Python a partir do JSON final
            oportunidades_dict = json.loads(json_final_output)

            # Verifica se a IA retornou um erro
            if "erro" in oportunidades_dict:
                logging.error(
                    f"A IA retornou um erro, e-mail não será enviado. Erro: {oportunidades_dict['erro']}"
                )
            else:
                # Instancia e envia o e-mail
                mailer = MandaEmail(email_disparo=EMAIL_DISPARO, senha=EMAIL_SENHA)
                mailer.enviar_email_oportunidades(
                    oportunidades_dict=oportunidades_dict,
                    email_destinatario=EMAIL_DESTINATARIO,
                )
        except json.JSONDecodeError:
            logging.error(
                "Não foi possível decodificar o JSON final para enviar o e-mail."
            )
        except Exception as e:
            logging.error(f"Falha ao instanciar ou enviar e-mail: {e}")
    else:
        logging.warning("Variáveis 'EMAIL_DISPARO' e 'EMAIL_SENHA' não definidas.")

        logging.warning("O e-mail de alerta NÃO será enviado.")

