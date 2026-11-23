import asyncio
import html
import json
import logging
import math
import os
import re
import shutil
import subprocess
import textwrap
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

try:
    import edge_tts
    EDGE_TTS_OK = True
except ImportError:
    EDGE_TTS_OK = False

OUTPUT_DIR = "media_output"
WIDTH = 1080
HEIGHT = 1920
VOZ_PADRAO_REEL = "pt-BR-ThalitaMultilingualNeural"


def _carregar_fonte(tamanho, bold=True):
    """Carrega fonte TrueType disponível no Linux (GitHub Actions) ou Windows."""
    candidatos = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
    )
    for path in candidatos:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, tamanho)
            except Exception:
                continue
    return ImageFont.load_default()


def _desenhar_gradiente_vertical(largura, altura, cor_topo, cor_base):
    """Cria um fundo vertical suave com gradiente escuro moderno."""
    img = Image.new("RGB", (largura, altura), cor_topo)
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = cor_topo
    r2, g2, b2 = cor_base
    for y in range(altura):
        ratio = y / max(altura - 1, 1)
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (largura, y)], fill=(r, g, b))
    return img


def _centralizar_texto(draw, y, texto, fonte, cor, largura=WIDTH):
    bbox = draw.textbbox((0, 0), texto, font=fonte)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (largura - tw) // 2
    draw.text((x, y), texto, font=fonte, fill=cor)
    return x, y, tw, th


def gerar_card_vertical_9x16(
    oportunidade,
    img_bytes=None,
    preco_antigo=None,
    modo="reel",
    arquivo_saida=None,
):
    """
    Gera um criativo vertical 9:16 (1080x1920) de alto impacto para Reels/Stories:
      - Zona segura para UI da Meta (topo/rodapé)
      - Selo da loja (Mercado Livre / Magalu) + Tag de desconto (% OFF)
      - Foto do produto centralizada em moldura branca limpa
      - Título legível + Preço De/Por em destaque
      - Barra de CTA para o 1º comentário / Telegram (@promosgeektech)
    """
    if not PILLOW_OK:
        logging.warning("Pillow não disponível para gerar card vertical.")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, f"card_{modo}.jpg")

    copy = oportunidade.get("copy_venda", {})
    titulo = (copy.get("titulo") or oportunidade.get("nome_produto") or "Super Oferta!").strip()
    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)
    url_af = str(oportunidade.get("url_afiliado", "") or "")
    loja = oportunidade.get("loja") or ("Mercado Livre" if "mercadolivre" in url_af.lower() else "Magalu")
    is_ml = "mercado" in loja.lower()

    # 1. Fundo gradiente escuro (estilo vitrine Tech/Gamer)
    canvas = _desenhar_gradiente_vertical(WIDTH, HEIGHT, (11, 16, 36), (22, 34, 68))
    draw = ImageDraw.Draw(canvas)

    # Faixa sutil de brilho no topo
    cor_destaque = (255, 230, 0) if is_ml else (0, 134, 255)
    draw.rectangle([0, 0, WIDTH, 14], fill=cor_destaque)

    # 2. Selo da Loja + Selo de Desconto (abaixo da zona segura do topo: y=155)
    f_badge = _carregar_fonte(34, bold=True)
    f_disc = _carregar_fonte(38, bold=True)

    texto_loja = "MERCADO LIVRE" if is_ml else "MAGALU OFICIAL"
    cor_texto_loja = (15, 23, 42) if is_ml else (255, 255, 255)

    # Pill da loja (esquerda)
    bbox_l = draw.textbbox((0, 0), texto_loja, font=f_badge)
    w_loja = (bbox_l[2] - bbox_l[0]) + 56
    h_pill = 68
    y_pill = 165

    if desconto >= 5:
        texto_disc = f"-{desconto:.0f}% OFF"
        bbox_d = draw.textbbox((0, 0), texto_disc, font=f_disc)
        w_disc = (bbox_d[2] - bbox_d[0]) + 56
        gap = 24
        x_start = (WIDTH - (w_loja + gap + w_disc)) // 2

        draw.rounded_rectangle([x_start, y_pill, x_start + w_loja, y_pill + h_pill], radius=34, fill=cor_destaque)
        draw.text((x_start + 28, y_pill + 15), texto_loja, font=f_badge, fill=cor_texto_loja)

        x_disc = x_start + w_loja + gap
        draw.rounded_rectangle([x_disc, y_pill, x_disc + w_disc, y_pill + h_pill], radius=34, fill=(239, 68, 68))
        draw.text((x_disc + 28, y_pill + 13), texto_disc, font=f_disc, fill=(255, 255, 255))
    else:
        x_start = (WIDTH - w_loja) // 2
        draw.rounded_rectangle([x_start, y_pill, x_start + w_loja, y_pill + h_pill], radius=34, fill=cor_destaque)
        draw.text((x_start + 28, y_pill + 15), texto_loja, font=f_badge, fill=cor_texto_loja)

    # 3. Moldura branca central para foto do produto
    box_w, box_h = 840, 740
    box_x = (WIDTH - box_w) // 2
    box_y = 275

    # Sombra suave
    draw.rounded_rectangle([box_x + 10, box_y + 14, box_x + box_w + 10, box_y + box_h + 14], radius=42, fill=(6, 10, 24))
    draw.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h], radius=42, fill=(255, 255, 255))

    if img_bytes:
        try:
            prod = Image.open(BytesIO(img_bytes))
            if prod.mode in ("RGBA", "LA", "P"):
                fundo = Image.new("RGB", prod.size, (255, 255, 255))
                if prod.mode == "P":
                    prod = prod.convert("RGBA")
                fundo.paste(prod, mask=prod.split()[-1] if prod.mode == "RGBA" else None)
                prod = fundo
            else:
                prod = prod.convert("RGB")
            prod = ImageOps.contain(prod, (box_w - 80, box_h - 80), Image.Resampling.LANCZOS)
            px = box_x + (box_w - prod.width) // 2
            py = box_y + (box_h - prod.height) // 2
            canvas.paste(prod, (px, py))
        except Exception as e:
            logging.warning(f"Falha ao colar foto do produto no card 9:16: {e}")

    # 4. Título do Produto (até 3 linhas)
    f_title = _carregar_fonte(46, bold=True)
    linhas_titulo = textwrap.wrap(titulo, width=28)[:3]
    y_curr = box_y + box_h + 52
    for linha in linhas_titulo:
        _, _, _, th = _centralizar_texto(draw, y_curr, linha, f_title, (248, 250, 252))
        y_curr += th + 16

    # 5. Bloco de Preços (De -> Por)
    y_curr += 22
    if preco_antigo and float(preco_antigo) > preco_atual:
        f_old = _carregar_fonte(40, bold=False)
        txt_old = f"De R$ {float(preco_antigo):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        ox, oy, ow, oh = _centralizar_texto(draw, y_curr, txt_old, f_old, (148, 163, 184))
        draw.line([(ox - 8, oy + oh // 2 + 2), (ox + ow + 8, oy + oh // 2 + 2)], fill=(239, 68, 68), width=4)
        y_curr += oh + 20

    f_price = _carregar_fonte(92, bold=True)
    txt_price = f"R$ {preco_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    _, _, _, ph = _centralizar_texto(draw, y_curr, txt_price, f_price, (16, 185, 129))
    y_curr += ph + 38

    # 6. Botão CTA (acima da zona segura inferior do Reels/Stories)
    f_cta = _carregar_fonte(34, bold=True)
    cta_txt = "LINK NO 1º COMENTÁRIO!" if modo == "reel" else "PEGUE NO TELEGRAM: @PROMOSGEEKTECH"
    cta_w, cta_h = 840, 86
    cta_x = (WIDTH - cta_w) // 2
    cta_y = min(max(y_curr + 10, 1490), 1560)

    draw.rounded_rectangle([cta_x, cta_y, cta_x + cta_w, cta_y + cta_h], radius=43, fill=(37, 99, 235))
    _centralizar_texto(draw, cta_y + 22, cta_txt, f_cta, (255, 255, 255))

    # Rodapé da marca
    f_brand = _carregar_fonte(28, bold=False)
    _centralizar_texto(draw, cta_y + cta_h + 26, "GAMESTORE  •  @promosgeektech", f_brand, (148, 163, 184))

    canvas.save(arquivo_saida, format="JPEG", quality=92)
    logging.info(f"🎨 Card vertical 9:16 gerado: {arquivo_saida}")
    return arquivo_saida


def _formatar_preco_falado(valor):
    """Formata um float para leitura natural em português (ex: 199.90 -> '199 reais e 90 centavos')."""
    reais = int(valor)
    centavos = int(round((valor - reais) * 100))
    if centavos == 0:
        return f"{reais} reais"
    return f"{reais} reais e {centavos} centavos"


def gerar_locucao_ptbr(
    oportunidade,
    preco_antigo=None,
    arquivo_saida=None,
    voice=VOZ_PADRAO_REEL,
    rate="+10%",
):
    """
    Gera locução neural em PT-BR (gratuita via edge-tts, voz ThalitaMultilingualNeural)
    para narrar o achado no Reel com pronúncia natural de termos gamer/tech.
    """
    if not EDGE_TTS_OK:
        logging.warning("Biblioteca 'edge-tts' não instalada. Reel será gerado sem locução.")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "reel_voz.mp3")

    copy = oportunidade.get("copy_venda", {})
    nome_raw = (oportunidade.get("nome_produto") or copy.get("titulo") or "esse produto").strip()
    # Limpa símbolos/emojis e limita a ~65 chars para uma fala ágil e envolvente
    nome_limpo = re.sub(r"[^\w\sÀ-ÿ\-\+\.]", " ", nome_raw)
    nome_limpo = re.sub(r"\s+", " ", nome_limpo).strip()
    if len(nome_limpo) > 65:
        nome_limpo = nome_limpo[:65].rsplit(" ", 1)[0]

    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)

    abertura = "Menor preço registrado!" if oportunidade.get("menor_preco_historico") else "Alerta de oferta!"
    partes = [f"{abertura} {nome_limpo}"]
    if preco_antigo and float(preco_antigo) > preco_atual:
        partes.append(f"caiu de {int(round(float(preco_antigo)))} reais por apenas {_formatar_preco_falado(preco_atual)}!")
    else:
        partes.append(f"por apenas {_formatar_preco_falado(preco_atual)}!")

    if desconto >= 10:
        partes.append(f"São {int(round(desconto))} por cento de desconto!")

    partes.append("Link no primeiro comentário!")
    texto_fala = " ".join(partes)

    try:
        async def _run():
            comm = edge_tts.Communicate(texto_fala, voice=voice, rate=rate)
            await comm.save(arquivo_saida)

        asyncio.run(_run())
        if os.path.exists(arquivo_saida) and os.path.getsize(arquivo_saida) > 1000:
            logging.info(f"🎙️ Locução PT-BR ({voice}) gerada: {arquivo_saida}")
            return arquivo_saida
    except Exception as e:
        logging.warning(f"Falha ao gerar locução edge-tts (seguindo sem voz): {e}")

    return None


def _obter_duracao_audio(audio_path):
    """Obtém a duração exata do áudio em segundos via ffprobe para nunca cortar a locução."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin or not audio_path or not os.path.exists(audio_path):
        return None
    try:
        res = subprocess.run(
            [
                ffprobe_bin,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception:
        pass
    return None


def gerar_video_reel_mp4(imagem_card_path, arquivo_saida=None, duracao_segundos=9, audio_path=None):
    """
    Converte o card vertical 1080x1920 em um vídeo MP4 pronto para Reels/Shorts/TikTok
    usando ffmpeg (zoom suave + fade-in + locução PT-BR da Thalita ou faixa AAC silenciosa).
    Ajusta automaticamente a duração do vídeo para o tempo exato da locução + 0,8s.
    """
    if not imagem_card_path or not os.path.exists(imagem_card_path):
        return None

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logging.warning("ffmpeg não encontrado no ambiente. Pulando geração do vídeo MP4.")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "reel_oferta.mp4")

    tem_audio_real = bool(audio_path and os.path.exists(audio_path))
    if tem_audio_real:
        dur_audio = _obter_duracao_audio(audio_path)
        if dur_audio:
            duracao_segundos = max(8, min(20, int(math.ceil(dur_audio + 0.8))))

    fps = 30
    total_frames = duracao_segundos * fps
    # Zoom suave de 1.00x até ~1.08x centralizado + fade in de 0.4s
    vf = (
        f"scale=1080:1920,"
        f"zoompan=z='min(zoom+0.00028,1.08)':d={total_frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
        f"fade=t=in:st=0:d=0.4,format=yuv420p"
    )

    if tem_audio_real:
        audio_inputs = ["-i", audio_path]
    else:
        audio_inputs = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]

    cmd = [
        ffmpeg_bin,
        "-y",
        "-loop", "1",
        "-i", imagem_card_path,
        *audio_inputs,
        "-vf", vf,
        "-t", str(duracao_segundos),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        arquivo_saida,
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and os.path.exists(arquivo_saida):
            tamanho_kb = os.path.getsize(arquivo_saida) // 1024
            modo_som = "com locução PT-BR" if tem_audio_real else "sem locução"
            logging.info(f"🎬 Vídeo Reel MP4 gerado ({duracao_segundos}s, {tamanho_kb} KB, {modo_som}): {arquivo_saida}")
            return arquivo_saida
        logging.error(f"ffmpeg falhou ao gerar Reel: {res.stderr[-400:]}")
    except Exception as e:
        logging.error(f"Exceção ao executar ffmpeg: {e}")

    return None


def gerar_video_reel_hyperframes(
    oportunidade,
    img_bytes=None,
    preco_antigo=None,
    audio_path=None,
    arquivo_saida=None,
):
    """
    Gera um Reel MP4 1080x1920 com motion graphics GSAP determinísticos via HeyGen HyperFrames
    (100% gratuito/open-source) sincronizado com a locução PT-BR da Thalita.
    Retorna None caso o HyperFrames não esteja disponível para acionar fallback Pillow+ffmpeg.
    """
    hf_bin = shutil.which("hyperframes") or shutil.which("hyperframes.cmd")
    npx_bin = shutil.which("npx") or shutil.which("npx.cmd")
    if not hf_bin and not npx_bin:
        logging.warning("HyperFrames/npx não encontrado. Usando fallback Pillow + ffmpeg.")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "reel_oferta.mp4")
    arquivo_saida_abs = os.path.abspath(arquivo_saida)

    job_dir = os.path.abspath(os.path.join(OUTPUT_DIR, "hf_job"))
    assets_dir = os.path.join(job_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # 1. Prepara imagem do produto em assets/produto.jpg
    prod_img_path = os.path.join(assets_dir, "produto.jpg")
    tem_imagem = False
    if img_bytes:
        try:
            with open(prod_img_path, "wb") as f_img:
                f_img.write(img_bytes)
            tem_imagem = True
        except Exception as e:
            logging.warning(f"Erro ao gravar produto.jpg para HyperFrames: {e}")

    # 2. Prepara áudio da Thalita em assets/voz.mp3 e calcula duração exata
    tem_audio = False
    duracao_audio = 0.0
    duracao_total = 10.0
    if audio_path and os.path.exists(audio_path):
        try:
            shutil.copy2(audio_path, os.path.join(assets_dir, "voz.mp3"))
            dur_probe = _obter_duracao_audio(audio_path)
            duracao_audio = round(dur_probe, 2) if dur_probe else 10.0
            duracao_total = round(max(9.0, min(22.0, duracao_audio + 0.8)), 2)
            tem_audio = True
        except Exception as e:
            logging.warning(f"Erro ao preparar áudio para HyperFrames: {e}")

    # 3. Dados dinâmicos da oferta
    copy = oportunidade.get("copy_venda", {})
    titulo_raw = (copy.get("titulo") or oportunidade.get("nome_produto") or "Super Oferta!").strip()
    if len(titulo_raw) > 78:
        titulo_raw = titulo_raw[:75].rsplit(" ", 1)[0] + "..."
    titulo_html = html.escape(titulo_raw)

    preco_atual = float(oportunidade.get("preco_atual", 0.0) or 0.0)
    desconto = float(oportunidade.get("percentual_desconto", 0.0) or 0.0)
    url_af = str(oportunidade.get("url_afiliado", "") or "")
    loja = oportunidade.get("loja") or ("Mercado Livre" if "mercadolivre" in url_af.lower() else "Magalu")
    is_ml = "mercado" in loja.lower()

    store_label = "MERCADO LIVRE" if is_ml else "MAGALU OFICIAL"
    store_bg = "#ffe600" if is_ml else "#0086ff"
    store_fg = "#0f172a" if is_ml else "#ffffff"
    top_gradient = (
        "linear-gradient(90deg, #ffe600, #ff6b00, #ef4444)"
        if is_ml
        else "linear-gradient(90deg, #0086ff, #38bdf8, #10b981)"
    )

    preco_novo_str = f"R$ {preco_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    bloco_preco_antigo = ""
    if preco_antigo and float(preco_antigo) > preco_atual:
        preco_antigo_str = f"De R$ {float(preco_antigo):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        bloco_preco_antigo = f"""
          <div id="old-price-wrap">
            {preco_antigo_str}
            <div id="strike-line"></div>
          </div>"""

    badge_off_html = (
        f'<div id="badge-off" class="pill">-{desconto:.0f}% OFF</div>'
        if desconto >= 5
        else ""
    )
    img_html = '<img id="product-img" src="./assets/produto.jpg" alt="Produto" />' if tem_imagem else ""
    audio_html = (
        f'<audio src="./assets/voz.mp3" data-start="0.2" data-duration="{duracao_audio}" data-track-index="1"></audio>'
        if tem_audio
        else ""
    )

    # 4. Escreve hyperframes.json e index.html (template validado 1080x1920 sem sobreposição)
    with open(os.path.join(job_dir, "hyperframes.json"), "w", encoding="utf-8") as f_cfg:
        json.dump(
            {
                "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
                "media": {"autoProxy": True},
            },
            f_cfg,
            indent=2,
        )

    header_alert_txt = (
        "📉 MENOR PREÇO REGISTRADO!"
        if oportunidade.get("menor_preco_historico")
        else "⚡ ALERTA DE OFERTA"
    )
    index_html = f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        width: 1080px; height: 1920px; overflow: hidden;
        background: #070b18;
        font-family: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
      }}
      #root {{
        position: relative; width: 1080px; height: 1920px; overflow: hidden;
        background: radial-gradient(circle at 50% 34%, #1b2c5c 0%, #121c3a 45%, #070b18 100%);
      }}
      #bg-glow {{
        position: absolute; width: 900px; height: 900px; top: 220px; left: 90px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(37, 99, 235, 0.35) 0%, rgba(239, 68, 68, 0.14) 45%, transparent 70%);
        filter: blur(40px); pointer-events: none;
      }}
      #top-bar {{
        position: absolute; top: 0; left: 0; width: 1080px; height: 16px;
        background: {top_gradient};
      }}
      #stage {{
        position: absolute; inset: 0; width: 1080px; height: 1920px;
        display: flex; flex-direction: column; align-items: center; z-index: 2;
      }}
      #header-alert {{
        margin-top: 155px; font-size: 32px; font-weight: 800;
        letter-spacing: 0.12em; color: #ffe600; text-transform: uppercase;
      }}
      #badges-row {{
        margin-top: 22px; display: flex; align-items: center; gap: 20px;
      }}
      .pill {{
        padding: 16px 34px; border-radius: 999px; font-size: 34px; font-weight: 900;
        letter-spacing: 0.02em; box-shadow: 0 12px 30px rgba(0, 0, 0, 0.35);
      }}
      #badge-store {{ background: {store_bg}; color: {store_fg}; }}
      #badge-off {{ background: linear-gradient(135deg, #ef4444, #dc2626); color: #ffffff; }}
      #product-card {{
        margin-top: 38px; width: 840px; height: 700px; background: #ffffff;
        border-radius: 44px; padding: 36px;
        box-shadow: 0 30px 70px rgba(0, 0, 0, 0.55), 0 0 0 3px rgba(255, 255, 255, 0.12);
        display: flex; align-items: center; justify-content: center;
      }}
      #product-img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
      #title {{
        margin-top: 44px; width: 880px; text-align: center; color: #f8fafc;
        font-size: 48px; font-weight: 800; line-height: 1.18;
      }}
      #price-box {{
        margin-top: 28px; display: flex; flex-direction: column; align-items: center;
      }}
      #old-price-wrap {{
        position: relative; display: inline-block;
        font-size: 44px; font-weight: 600; color: #94a3b8;
      }}
      #strike-line {{
        position: absolute; left: -12px; right: -12px; top: 52%; height: 6px;
        background: #ef4444; border-radius: 4px;
        transform-origin: left center; transform: scaleX(0);
      }}
      #new-price {{
        margin-top: 8px; font-size: 108px; font-weight: 900; color: #10b981;
        letter-spacing: -0.03em; text-shadow: 0 0 40px rgba(16, 185, 129, 0.45);
      }}
      #cta-wrap {{
        margin-top: 36px; position: relative; width: 840px; height: 96px;
        border-radius: 999px; background: linear-gradient(135deg, #2563eb, #1d4ed8);
        box-shadow: 0 18px 45px rgba(37, 99, 235, 0.5);
        display: flex; align-items: center; justify-content: center; overflow: hidden;
      }}
      #cta-text {{ color: #ffffff; font-size: 36px; font-weight: 900; letter-spacing: 0.03em; }}
      #cta-shine {{
        position: absolute; top: 0; left: -240px; width: 180px; height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.45), transparent);
        transform: skewX(-22deg);
      }}
      #brand {{
        margin-top: 26px; font-size: 28px; font-weight: 600;
        color: #94a3b8; letter-spacing: 0.08em;
      }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{duracao_total}" data-width="1080" data-height="1920">
      <div id="top-bar"></div>
      <div id="bg-glow"></div>
      <div id="stage" class="clip" data-start="0" data-duration="{duracao_total}" data-track-index="0">
        <div id="header-alert">{header_alert_txt}</div>
        <div id="badges-row">
          <div id="badge-store" class="pill">{store_label}</div>
          {badge_off_html}
        </div>
        <div id="product-card">{img_html}</div>
        <h1 id="title">{titulo_html}</h1>
        <div id="price-box">
          {bloco_preco_antigo}
          <div id="new-price">{preco_novo_str}</div>
        </div>
        <div id="cta-wrap">
          <span id="cta-text">👇 LINK NO 1º COMENTÁRIO!</span>
          <div id="cta-shine"></div>
        </div>
        <div id="brand">GAMESTORE • @PROMOSGEEKTECH</div>
      </div>
      {audio_html}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#header-alert", {{ opacity: 0, y: -35 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }}, 0.0);
      tl.fromTo("#badge-store", {{ opacity: 0, x: -60, scale: 0.85 }}, {{ opacity: 1, x: 0, scale: 1, duration: 0.5, ease: "back.out(1.6)" }}, 0.15);
      if (document.querySelector("#badge-off")) {{
        tl.fromTo("#badge-off", {{ opacity: 0, scale: 1.7, rotate: -10 }}, {{ opacity: 1, scale: 1, rotate: 0, duration: 0.55, ease: "back.out(1.8)" }}, 0.35);
        tl.to("#badge-off", {{ scale: 1.08, duration: 0.45, yoyo: true, repeat: 9, ease: "sine.inOut" }}, 4.5);
      }}
      tl.fromTo("#product-card", {{ opacity: 0, y: 80, scale: 0.86 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.7, ease: "power3.out" }}, 0.5);
      if (document.querySelector("#product-img")) {{
        tl.fromTo("#product-img", {{ scale: 0.92 }}, {{ scale: 1.06, duration: {max(duracao_total - 0.8, 5.0)}, ease: "none" }}, 0.8);
      }}
      tl.fromTo("#title", {{ opacity: 0, y: 35 }}, {{ opacity: 1, y: 0, duration: 0.55, ease: "power3.out" }}, 1.2);
      if (document.querySelector("#old-price-wrap")) {{
        tl.fromTo("#old-price-wrap", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }}, 2.4);
        tl.to("#strike-line", {{ scaleX: 1, duration: 0.45, ease: "power3.inOut" }}, 3.0);
      }}
      tl.fromTo("#new-price", {{ opacity: 0, scale: 0.55 }}, {{ opacity: 1, scale: 1, duration: 0.65, ease: "back.out(1.8)" }}, 3.5);
      tl.to("#bg-glow", {{ scale: 1.18, opacity: 0.9, duration: 3.5, yoyo: true, repeat: 3, ease: "sine.inOut" }}, 0.5);
      tl.fromTo("#cta-wrap", {{ opacity: 0, y: 55, scale: 0.9 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.6, ease: "back.out(1.5)" }}, 4.6);
      tl.fromTo("#brand", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5 }}, 5.1);
      tl.fromTo("#cta-shine", {{ left: "-240px" }}, {{ left: "960px", duration: 0.9, ease: "power2.inOut" }}, 5.8);
      tl.fromTo("#cta-shine", {{ left: "-240px" }}, {{ left: "960px", duration: 0.9, ease: "power2.inOut" }}, 8.6);
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>"""

    with open(os.path.join(job_dir, "index.html"), "w", encoding="utf-8") as f_html:
        f_html.write(index_html)

    cmd = (
        [hf_bin, "render", "--output", arquivo_saida_abs]
        if hf_bin
        else [npx_bin, "--yes", "hyperframes", "render", "--output", arquivo_saida_abs]
    )

    try:
        logging.info(f"⚡ Renderizando Reel animado via HyperFrames ({duracao_total}s)...")
        res = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True, timeout=240)
        if res.returncode == 0 and os.path.exists(arquivo_saida_abs) and os.path.getsize(arquivo_saida_abs) > 50000:
            tamanho_kb = os.path.getsize(arquivo_saida_abs) // 1024
            logging.info(f"🎬 Reel HyperFrames gerado com sucesso ({duracao_total}s, {tamanho_kb} KB): {arquivo_saida_abs}")
            return arquivo_saida_abs
        logging.warning(f"HyperFrames retornou código {res.returncode}. Acionando fallback Pillow+ffmpeg.")
    except Exception as e:
        logging.warning(f"Exceção no HyperFrames (acionando fallback Pillow+ffmpeg): {e}")

    return None
