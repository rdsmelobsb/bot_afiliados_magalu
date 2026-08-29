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

# --- 3. Funções de Scraping e Processamento ---

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

            product_data = {
                "sku": product.get("id"),
                "nome_produto": nome,
                "preco_atual": preco_atual,
                "preco_antigo": preco_antigo,
                "percentual_desconto": percentual_desconto,
                "categoria": product.get("category", {}).get("name"),
                "comissao_percent": None,  
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
            html_out += f"""
            <div style="border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; padding: 16px; background-color: #f9f9f9;">
                <h3 style="color: #0086ff; margin-top: 0;">Oportunidade {i+1}: {op.get('nome_produto', 'N/A')}</h3>
                <p><strong>Preço:</strong> R$ {op.get('preco_atual', 0.0):.2f} | <strong>Desconto:</strong> <span style="color: #c00;">{op.get('percentual_desconto', 0.0)}% OFF</span></p>
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
    msg["Subject"] = f'Alpha-Profit: 10 Oportunidades! ({time.strftime("%d/%m/%Y")})'
    msg["From"] = email_disparo
    msg["To"] = email_destinatario

    oportunidades_html = formatar_oportunidades_html(oportunidades_dict)
    mensagem_html = f"<html><body><h2>Alpha-Profit AI Bot</h2>{oportunidades_html}</body></html>"
    msg.set_content(mensagem_html, subtype="html")

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
            logging.info("Email enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro no envio de e-mail: {e}")


# --- 4. O Maestro da Orquestra (Bloco Principal Modificado) ---

if __name__ == "__main__":

    URLS_BASE = [
        "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
        "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
        "https://www.magazinevoce.com.br/magazinedealz/casa-inteligente/l/ci/",
    ]

    all_dfs = []  
    logging.info("Iniciando scraping turbinado (agora lendo múltiplas páginas)...")

    # NOVA LÓGICA DE PAGINAÇÃO:
    for url_base in URLS_BASE:
        logging.info(f"Vasculhando a vitrine principal: {url_base}")
        
        # 1. Busca a primeira página e descobre o total de páginas existentes
        df_pagina, total_pages = extrair_dados_magalu_live(url_base)
        
        if df_pagina is not None and not df_pagina.empty:
            all_dfs.append(df_pagina) 

        # 2. Se houver mais de uma página, vamos visitá-las!
        if total_pages > 1:
            # Dica: Limitamos a no máximo 5 páginas por categoria para evitar bloqueios 
            # da loja e para o programa não demorar uma eternidade.
            limite_paginas = min(total_pages, 5) 
            
            # Cria o laço da página 2 até o limite estabelecido
            for pagina in range(2, limite_paginas + 1):
                # Adiciona o "?page=X" na URL, que é o padrão de paginação de e-commerces
                url_paginada = f"{url_base}?page={pagina}"
                logging.info(f"Buscando página {pagina} de {limite_paginas}...")
                
                df_extra, _ = extrair_dados_magalu_live(url_paginada)
                
                if df_extra is not None and not df_extra.empty:
                    all_dfs.append(df_extra)
                
                # Pausa estratégica de 2 segundos. Sem isso, a loja bloqueia nosso robô!
                time.sleep(2)

    # Verifica se pegou alguma coisa
    if not all_dfs:
        logging.error("Nenhum produto extraído.")
        sys.exit(0)

    # Junta todas as tabelas raspadas em uma só super tabela
    df_produtos = pd.concat(all_dfs, ignore_index=True)
    logging.info(f"Total de produtos raspados após paginação: {len(df_produtos)} itens!")
    
    # Prepara o Top 100 para a Inteligência Artificial não se perder com excesso de dados
    df_produtos["score_qualidade"] = (df_produtos["percentual_desconto"] * 0.6) + \
                                     (df_produtos["preco_atual"].between(35, 500) * 40)
    
    df_ordenado_para_ia = df_produtos.sort_values(by="score_qualidade", ascending=False).head(100)
    
    json_input_data = gerar_json_para_ia(df_ordenado_para_ia.drop(columns=["score_qualidade"]))

    logging.info("\n=== CHAMANDO ALPHA-PROFIT (GEMINI) ===")
    json_final_output = gemini_fx(json_input_data)

    try:
        oportunidades_dict = json.loads(json_final_output)
        if "oportunidades" in oportunidades_dict:
            enviar_email_oportunidades(
                email_disparo=os.getenv("EMAIL_USER"),
                senha=os.getenv("EMAIL_PASSWORD"),
                email_destinatario="rsouza.melo18@gmail.com",
                oportunidades_dict=oportunidades_dict,
                df_todos_produtos=df_produtos # Aqui vai a nossa super tabela completa pro CSV!
            )
    except Exception as e:
        logging.error(f"Erro no processamento final: {e}")
