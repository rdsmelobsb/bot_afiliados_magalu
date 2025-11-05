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
        logging.error("A variável de ambiente 'GEMINI_API_KEY' não foi definida.")
        logging.error("Defina-a antes de rodar: export GEMINI_API_KEY='SUA_CHAVE'")
        sys.exit(1)  # Encerra o script se a chave não estiver presente
    genai.configure(api_key=api_key)
    logging.info("API do Gemini configurada com sucesso.")
except Exception as e:
    logging.error(f"Erro ao configurar a API do Gemini: {e}")
    sys.exit(1)


# --- 2. Diretriz de Sistema (Prompt da IA) ---

# --- REATORAÇÃO: Atualizado para 30 produtos ---
ALPHA_PROFIT_SYSTEM_PROMPT = """
## DIRETRIZ DE SISTEMA: PROJETO "ALPHA-PROFIT"

**1. IDENTIDADE (ROLE):**
Você é o "Alpha-Profit", um C-Level AI Strategist especializado em e-commerce de afiliados (Nicho: Games, Geek, Tech) com um único KPI: maximizar a Receita Bruta de Afiliados. Sua meta de curto prazo é gerar R$ 10.000.

**2. CONTEXTO OPERACIONAL (CONTEXT):**
Analisamos um catálogo de produtos de afiliados em tempo real. O público-alvo é "mar aberto" (amplo), +18. O "Ponto Doce" (Sweet Spot) de conversão por impulso é um Ticket Médio de R$ 50,00.

**3. DIRETRIZ DE ENTRADA (INPUT):**
Eu fornecerei um [INPUT_DATA], que é uma string JSON representando um DataFrame. **IMPORTANTE: Esta lista já foi pré-filtrada por mim (Python) para conter apenas os ~100 melhores candidatos** (com base no 'Sweet Spot' de R$ 35-R$ 60 e ordenados pelo maior desconto).

* `sku`: Identificador único.
* `nome_produto`: Nome do produto.
* `preco_atual`: Preço de venda atual (em R$).
* `preco_antigo`: Preço original (para cálculo de desconto).
* `percentual_desconto`: (preco_antigo - preco_atual) / preco_antigo.
* `categoria`: (Ex: 'Games', 'Hardware', 'Colecionáveis', 'Tecnologia').
* `comissao_percent`: (Opcional) O percentual de comissão do afiliado.
* `url_afiliado`: O link de compra.

**4. PROCESSO DE DECISÃO ESTRATÉGICA (THOUGHT_PROCESS):**
Seu objetivo é identificar as **30 (TRINTA)** "Oportunidades de Ouro" desta lista de candidatos. Você deve priorizar com base nesta hierarquia de decisão:

* **Filtro 1 e 2 (Já feitos por mim):** Os produtos já estão no "Sweet Spot" (R$ 35-R$ 60) e ordenados por desconto.
* **Filtro 3: Relevância (Seu Foco Principal):** Sua tarefa é aplicar o filtro qualitativo. O produto deve ter apelo imediato para o nicho (Games, Geek, Tech). Um mouse gamer obscuro em promoção é MELHOR que um fone de ouvido genérico ou um cabo USB comum. **Seja crítico e selecione apenas os mais relevantes para o nicho.**
* **Filtro 4: Potencial de Lucro (Desempate):** Se `comissao_percent` estiver disponível, use-o como um desempate.

**5. DIRETRIZ DE SAÍDA (OUTPUT):**
Sua resposta deve ser um JSON ESTRITO, sem texto introdutório ou final. O JSON deve conter uma chave principal "oportunidades" que é um array de **30 objetos**.

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
    // ... (Mais 28 objetos aqui, totalizando 30)
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

    # Garante que o JSON não tenha NaNs que quebram o parser
    df = df.fillna(value=pd.NA).where(pd.notna(df), None)

    json_input_para_ia = df.to_json(orient="records", force_ascii=False, indent=2)
    return json_input_para_ia


# --- 4. Funções da IA (Gemini) ---

MODELOS_DISPONIVEIS = [
     "gemini-2.5-pro", # Mantido como fallback se o 2.5 não existir no seu billing
]


def gemini_fx(prompt):
    """
    Tenta gerar conteúdo usando uma lista de modelos Gemini em fallback.
    """
    result = None

    for modelo_nome in MODELOS_DISPONIVEIS:
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
                "EMAIL_USER e EMAIL_PASSWORD devem ser definidos nas variáveis de ambiente."
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
            # Loop funciona para 3, 30, ou N oportunidades
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

        # --- REATORAÇÃO: Contagem dinâmica ---
        lista_oportunidades = oportunidades_dict.get("oportunidades", [])
        num_ops = len(lista_oportunidades)

        ASSUNTO = f'Alpha-Profit: Top {num_ops} Oportunidades Detectadas! ({time.strftime("%d/%m/%Y")})'

        msg = EmailMessage()
        msg["Subject"] = ASSUNTO
        msg["From"] = self.email_disparo
        msg["To"] = email_destinatario

        # Gera o corpo HTML a partir do dicionário de oportunidades
        oportunidades_html = self._formatar_oportunidades_html(oportunidades_dict)

        # --- REATORAÇÃO: Texto dinâmico ---
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
        <p>O "Alpha-Profit" AI Bot completou a varredura e análise. Foram identificadas as <strong>{num_ops} oportunidades de ouro</strong> com maior potencial de conversão com base em suas diretrizes:</p>

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

    # --- Constantes para configuração ---
    ARQUIVO_CSV_PRODUTOS = "produtos_extraidos_COMPLETO.csv"
    ARQUIVO_JSON_INSUMO = "insumo_ia_CANDIDATOS.json"
    ARQUIVO_JSON_RESULTADO = "oportunidades_alpha_profit_FINAL.json"

    # --- REATORAÇÃO: Constantes para pré-filtragem ---
    PRECO_MIN_SWEETSPOT = 35.0
    PRECO_MAX_SWEETSPOT = 60.0
    N_CANDIDATOS_PARA_IA = 100  # Enviamos os 100 melhores para a IA escolher 30

    URLS_PARA_RASPAR = [
        "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
        "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
        "https://www.magazinevoce.com.br/magazinedealz/informatica-acessorios/l/inca/",
        "https://www.magazinevoce.com.br/magazinedealz/pc-gamer/l/pcga/",
    ]

    all_dfs = []

    # --- ETAPA 1: SCRAPING (Modificado para múltiplas URLs) ---

    for url_base in URLS_PARA_RASPAR:
        logging.info("=" * 30)
        logging.info(f"Iniciando scraping da URL base: {url_base}")
        logging.info("=" * 30)

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
                logging.info(f"Total de páginas detectado para esta URL: {total_pages}")

            if df_pagina is not None and not df_pagina.empty:
                logging.info(
                    f"Sucesso: {len(df_pagina)} produtos adicionados da página {page_to_scrape}."
                )
                all_dfs.append(df_pagina)
            else:
                logging.warning(
                    f"Não foi possível extrair dados da página {page_to_scrape} ou a página estava vazia."
                )

            page_to_scrape += 1
            time.sleep(1)  # Pausa de 1 segundo (boa prática)

    if not all_dfs:
        logging.error("Nenhum produto foi extraído de nenhuma página. Encerrando.")
        sys.exit(0)

    # --- ETAPA 2: PROCESSAMENTO, PRÉ-FILTRAGEM E GERAÇÃO DE INSUMO ---

    df_produtos = pd.concat(all_dfs, ignore_index=True)
    # Remove duplicados pelo SKU, mantendo o que apareceu primeiro
    df_produtos = df_produtos.drop_duplicates(subset=["sku"], keep="first")

    logging.info(
        f"\n[SUCESSO] Total de produtos extraídos (sem duplicados): {len(df_produtos)}"
    )

    # Salva o CSV *antes* de filtrar, para ter o backup completo
    df_produtos.to_csv(ARQUIVO_CSV_PRODUTOS, index=False, encoding="utf-8-sig")
    logging.info(
        f"DataFrame completo (antes da filtragem) salvo em '{ARQUIVO_CSV_PRODUTOS}'"
    )

    # --- REATORAÇÃO: LÓGICA DE PRÉ-FILTRAGEM INTELIGENTE ---

    # 1. Aplicar Filtro 1 (Sweet Spot de Preço)
    df_filtrado = df_produtos[
        df_produtos["preco_atual"].between(PRECO_MIN_SWEETSPOT, PRECO_MAX_SWEETSPOT)
    ].copy()
    logging.info(
        f"Produtos após Filtro 1 (Preço R${PRECO_MIN_SWEETSPOT}-R${PRECO_MAX_SWEETSPOT}): {len(df_filtrado)}"
    )

    # 2. Aplicar Filtro 2 (Maior Desconto)
    # Produtos com desconto 0 são filtrados aqui
    df_filtrado = df_filtrado[df_filtrado["percentual_desconto"] > 0]
    df_filtrado = df_filtrado.sort_values(by="percentual_desconto", ascending=False)
    logging.info(f"Produtos com desconto > 0: {len(df_filtrado)}")

    # 3. Criar a lista de candidatos (Top N)
    df_candidatos = df_filtrado.head(N_CANDIDATOS_PARA_IA)
    logging.info(
        f"Top {len(df_candidatos)} candidatos selecionados (por desconto) para análise da IA."
    )

    if df_candidatos.empty:
        logging.error(
            f"Nenhum produto encontrado no 'Sweet Spot' e com desconto. Encerrando."
        )
        sys.exit(0)

    # 4. Gerar o JSON de insumo APENAS com os candidatos
    json_input_data = gerar_json_para_ia(df_candidatos)

    if not json_input_data:
        logging.error("Falha ao gerar o JSON de insumo para a IA. Encerrando.")
        sys.exit(0)

    # Salva o JSON que será enviado para a IA
    with open(ARQUIVO_JSON_INSUMO, "w", encoding="utf-8") as f:
        f.write(json_input_data)
    logging.info(f"Insumo JSON (apenas candidatos) salvo em '{ARQUIVO_JSON_INSUMO}'")

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
        f"Analisando {len(df_candidatos)} candidatos para encontrar as 30 'Oportunidades de Ouro'..."
    )

    api_response = gemini_fx(final_prompt)

    logging.info("Resposta da IA recebida. Limpando e formatando...")
    json_final_output = extrair_json_da_resposta(api_response)

    # --- ETAPA 4: RESULTADO FINAL E ARQUIVOS ---

    print("\n" + "=" * 25 + " RESPOSTA FINAL (JSON) " + "=" * 25)
    print(json_final_output)

    try:
        # Salva o resultado final da IA
        with open(ARQUIVO_JSON_RESULTADO, "w", encoding="utf-8") as f:
            f.write(json_final_output)
        logging.info(f"\n[SUCESSO] Oportunidades salvas em '{ARQUIVO_JSON_RESULTADO}'")
    except Exception as e:
        logging.error(f"\nErro ao salvar arquivo JSON final: {e}")

    # --- ETAPA 5: ENVIO DE E-MAIL ---

    logging.info("\n" + "=" * 25 + " ENVIANDO E-MAIL " + "=" * 25)

    EMAIL_DISPARO = os.getenv("EMAIL_USER")
    EMAIL_SENHA = os.getenv("EMAIL_PASSWORD")
    EMAIL_DESTINATARIO = os.getenv("EMAIL_DESTINATARIO", "rafael.melo@novagencia.com")

    try:
        mailer = MandaEmail(email_disparo=EMAIL_DISPARO, senha=EMAIL_SENHA)

        # Carrega o dicionário Python a partir do JSON final
        oportunidades_dict = json.loads(json_final_output)

        if "erro" in oportunidades_dict:
            logging.error(
                f"A IA retornou um erro, e-mail não será enviado. Erro: {oportunidades_dict['erro']}"
            )
        else:
            mailer.enviar_email_oportunidades(
                oportunidades_dict=oportunidades_dict,
                email_destinatario=EMAIL_DESTINATARIO,
            )

    except (ValueError, json.JSONDecodeError) as e:
        logging.error(f"Falha ao preparar ou enviar e-mail: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado no envio de e-mail: {e}")

    if not EMAIL_DISPARO or not EMAIL_SENHA:
        logging.warning("Variáveis 'EMAIL_USER' e 'EMAIL_PASSWORD' não definidas.")
        logging.warning("O e-mail de alerta NÃO foi enviado.")

