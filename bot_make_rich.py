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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logging.error("Opa! Defina a chave: export GEMINI_API_KEY='SUA_CHAVE'")
        sys.exit(1)  
    genai.configure(api_key=api_key)
    logging.info("API configurada. Sistema Alpha-Profit pronto para decolagem.")
except Exception as e:
    logging.error(f"Erro na configuração: {e}")
    sys.exit(1)

# --- 2. Diretriz de Sistema (Prompt Atualizado com Filtro de Verossimilhança) ---
ALPHA_PROFIT_SYSTEM_PROMPT = """
## DIRETRIZ DE SISTEMA: PROJETO "ALPHA-PROFIT" v2.0

**1. IDENTIDADE:**
Você é um C-Level AI Strategist. Seu KPI é lucro bruto. Você é CÉTICO e analítico.

**2. FILTRO DE VEROSSIMILHANÇA (ANTI-FRAUDE):**
- Descarte produtos com descontos acima de 80% em eletrônicos de marca (Samsung, Apple, LG, etc); são provavelmente erros de base.
- Priorize MARCAS RECONHECIDAS (Ex: Logitech, JBL, Kingston, Sony). Um desconto de 15% em marca líder vale mais que 70% em produto genérico.
- Descarte "miudezas": cabos, adaptadores e suportes, a menos que sejam de marcas premium.

**3. PROCESSO DE DECISÃO:**
Identifique as 10 "Oportunidades de Ouro" cruzando:
* **Utilidade Técnica (Peso 50%):** O produto resolve uma dor real (Ex: fim do drift, upgrade de velocidade)?
* **Aderência ao Preço (Peso 30%):** Faixa ideal R$ 50,00 a R$ 450,00.
* **Escassez Real (Peso 20%):** Descontos de 20% a 50% são os mais confiáveis e convertem melhor que "ofertas impossíveis".

**4. FORMATO DE SAÍDA:** (JSON Estrito conforme modelo anterior)
"""

# --- 3. Funções do Scraper (Com Filtro de Termos Banidos) ---

def extrair_dados_magalu_live(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."}
    
    # 🟢 LISTA DE TERMOS QUE POLUEM SEU CATALOGO
    termos_banidos = ['cabo', 'pelicula', 'capinha', 'adaptador', 'suporte', 'conector', 'carregador tipo c', 'capa para']

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not next_data_script: return None, 1
        
        json_data = json.loads(next_data_script.string)
        search_data = json_data["props"]["pageProps"]["data"]["search"]
        product_list = search_data["products"]
        total_pages = search_data.get("pagination", {}).get("pages", 1)
        
        processed_products = []
        for product in product_list:
            titulo = product.get("title", "").lower()
            
            # 🟢 FILTRO ATIVO: Pula se o título contiver lixo
            if any(termo in titulo for termo in termos_banidos):
                continue

            price_data = product.get("price", {})
            preco_antigo = float(price_data.get("price") or 0)
            preco_atual = float(price_data.get("fullPrice") or 0)

            if preco_antigo > preco_atual > 0:
                desconto = round(((preco_antigo - preco_atual) / preco_antigo) * 100, 2)
                
                # 🟢 FILTRO DE SANIDADE: Ignora descontos impossíveis em tecnologia
                if desconto > 85: continue 

                processed_products.append({
                    "sku": product.get("id"),
                    "nome_produto": product.get("title"),
                    "preco_atual": preco_atual,
                    "preco_antigo": preco_antigo,
                    "percentual_desconto": desconto,
                    "categoria": product.get("category", {}).get("name"),
                    "url_afiliado": "https://www.magazinevoce.com.br" + product.get("url", "")
                })
        
        return pd.DataFrame(processed_products), total_pages
    except Exception as e:
        logging.warning(f"Falha na extração: {e}")
        return None, 1

# --- 4. Execução Principal com Ordenação Inteligente ---

if __name__ == "__main__":
    URLS_BASE = [
        "https://www.magazinevoce.com.br/magazinedealz/informatica/l/in/",
        "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/",
        "https://www.magazinevoce.com.br/magazinedealz/casa-inteligente/l/ci/",
    ]

    all_dfs = []
    for url in URLS_BASE:
        df_pg, _ = extrair_dados_magalu_live(url)
        if df_pg is not None: all_dfs.append(df_pg)

    if not all_dfs: sys.exit("Nenhum dado extraído.")

    df_final = pd.concat(all_dfs, ignore_index=True)

    # 🟢 NOVO: SCORE DE OPORTUNIDADE (BI LOGIC)
    # Valorizamos desconto (60%) e proximidade do Sweet Spot R$ 200 (40%)
    df_final["score"] = (df_final["percentual_desconto"] * 0.6) + \
                        (df_final["preco_atual"].between(50, 450) * 40)

    # Pegamos os 120 melhores para a IA escolher 10
    df_para_ia = df_final.sort_values(by="score", ascending=False).head(120)
    
    # 🟢 ATUALIZAÇÃO DO MODELO: gemini-2.0-flash (estável e rápido)
    # (Resto do código de chamada da IA e envio de e-mail segue igual)
    logging.info(f"Enviando {len(df_para_ia)} candidatos filtrados para análise do Alpha-Profit.")
