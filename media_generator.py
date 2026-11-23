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
    store_bg = "#FFE600" if is_ml else "#0086FF"
    store_fg = "#0A0B0E" if is_ml else "#FFFFFF"
    accent_color = "#D9FF00" if is_ml else "#38BDF8"

    preco_novo_str = f"R$ {preco_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    bloco_preco_antigo = ""
    bloco_economia = ""
    if preco_antigo and float(preco_antigo) > preco_atual:
        preco_antigo_f = float(preco_antigo)
        economia_f = preco_antigo_f - preco_atual
        preco_antigo_str = f"DE R$ {preco_antigo_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        economia_str = f"ECONOMIZE R$ {economia_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        bloco_preco_antigo = f"""
          <div id="old-price-wrap">
            <span>{preco_antigo_str}</span>
            <div id="strike-line"></div>
          </div>"""
        bloco_economia = f'<div id="savings-pill">{economia_str}</div>'

    badge_off_html = (
        f'<div id="badge-off"><span class="off-num">-{desconto:.0f}%</span><span class="off-lbl">OFF</span></div>'
        if desconto >= 5
        else ""
    )
    img_html = '<img id="product-img" src="./assets/produto.jpg" alt="Produto" />' if tem_imagem else ""
    audio_html = (
        f'<audio src="./assets/voz.mp3" data-start="0.2" data-duration="{duracao_audio}" data-track-index="1"></audio>'
        if tem_audio
        else ""
    )

    # 4. Escreve hyperframes.json e index.html (template Impeccable 1080x1920 sem sobreposição)
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

    is_min_hist = bool(oportunidade.get("menor_preco_historico"))
    header_alert_txt = "MENOR PREÇO 30D" if is_min_hist else "OFERTA VERIFICADA"
    header_icon_svg = (
        '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"></polyline><polyline points="17 18 23 18 23 12"></polyline></svg>'
        if is_min_hist
        else '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>'
    )
    cta_icon_svg = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline></svg>'

    index_html = f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800;900&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      :root {{
        --bg: #0A0B0E;
        --surface: #13161D;
        --border: rgba(255, 255, 255, 0.10);
        --text: #F5F7FA;
        --muted: #9AA3B2;
        --accent: {accent_color};
        --danger: #FF3B30;
        --store-bg: {store_bg};
        --store-fg: {store_fg};
      }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        width: 1080px; height: 1920px; overflow: hidden;
        background: var(--bg);
        font-family: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: var(--text);
        -webkit-font-smoothing: antialiased;
      }}
      #root {{
        position: relative; width: 1080px; height: 1920px; overflow: hidden;
        background: var(--bg);
      }}
      /* Micro-grade arquitetônica sutil (estética Tech Editorial) */
      #bg-grid {{
        position: absolute; inset: 0; pointer-events: none;
        background-image:
          linear-gradient(to right, rgba(255, 255, 255, 0.035) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
        background-size: 54px 54px;
        mask-image: radial-gradient(ellipse 85% 75% at 50% 42%, #000 35%, transparent 100%);
      }}
      /* Faixa superior limpa da marca */
      #top-accent {{
        position: absolute; top: 0; left: 0; width: 1080px; height: 10px;
        background: var(--accent); z-index: 5;
      }}
      /* Invariante HyperFrames: class="clip" apenas no container raiz #stage */
      #stage {{
        position: absolute; inset: 0; width: 1080px; height: 1920px;
        display: flex; flex-direction: column; align-items: center;
        padding: 152px 76px 210px 76px;
        z-index: 2;
      }}
      /* 1. Cabeçalho editorial (Masthead) */
      #masthead {{
        width: 100%;
        display: flex; align-items: center; justify-content: space-between;
        padding-bottom: 22px;
        border-bottom: 1px solid var(--border);
      }}
      #brand-lockup {{
        display: flex; align-items: center; gap: 14px;
      }}
      #brand-dot {{
        width: 14px; height: 14px; border-radius: 3px;
        background: var(--accent);
      }}
      #brand-name {{
        font-family: "Barlow Condensed", sans-serif;
        font-size: 36px; font-weight: 900; letter-spacing: 0.08em;
        color: var(--text); text-transform: uppercase;
      }}
      #status-tag {{
        display: inline-flex; align-items: center; gap: 10px;
        padding: 10px 22px; border-radius: 8px;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid var(--border);
        color: var(--accent);
        font-size: 24px; font-weight: 800; letter-spacing: 0.06em;
        text-transform: uppercase;
      }}
      /* 2. Palco de estúdio do produto (com selos integrados) */
      #product-stage {{
        position: relative;
        margin-top: 34px;
        width: 100%; height: 690px;
        background: #FFFFFF;
        border-radius: 28px;
        padding: 52px;
        display: flex; align-items: center; justify-content: center;
        overflow: hidden;
        box-shadow: 0 32px 64px rgba(0, 0, 0, 0.55);
      }}
      #product-img {{
        max-width: 92%; max-height: 92%; object-fit: contain;
        transform-origin: center center;
      }}
      /* Selo da loja integrado ao palco (canto inferior esquerdo) */
      #badge-store {{
        position: absolute; left: 28px; bottom: 28px;
        padding: 12px 24px; border-radius: 10px;
        background: var(--store-bg); color: var(--store-fg);
        font-family: "Barlow Condensed", sans-serif;
        font-size: 32px; font-weight: 900; letter-spacing: 0.05em;
        text-transform: uppercase;
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
      }}
      /* Carimbo editorial de desconto (canto superior direito) */
      #badge-off {{
        position: absolute; right: 28px; top: 28px;
        background: var(--danger); color: #FFFFFF;
        padding: 14px 26px; border-radius: 14px;
        display: flex; align-items: baseline; gap: 8px;
        box-shadow: 0 14px 30px rgba(255, 59, 48, 0.35);
      }}
      .off-num {{
        font-family: "Barlow Condensed", sans-serif;
        font-size: 62px; font-weight: 900; line-height: 0.92;
        font-variant-numeric: tabular-nums;
      }}
      .off-lbl {{
        font-family: "Barlow Condensed", sans-serif;
        font-size: 30px; font-weight: 800; letter-spacing: 0.04em;
      }}
      /* 3. Título do produto (tipografia limpa, sem competir com o preço) */
      #title {{
        margin-top: 38px; width: 100%;
        text-align: left; color: var(--text);
        font-size: 46px; font-weight: 800; line-height: 1.18;
        letter-spacing: -0.025em;
        display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        overflow: hidden;
      }}
      /* 4. Momento Focal: Bloco de Preço + Economia Real */
      #price-panel {{
        margin-top: 30px; width: 100%;
        padding: 30px 36px; border-radius: 24px;
        background: var(--surface);
        border: 1px solid var(--border);
        display: flex; flex-direction: column; gap: 8px;
      }}
      #price-top-row {{
        display: flex; align-items: center; justify-content: space-between;
        min-height: 44px;
      }}
      #old-price-wrap {{
        position: relative; display: inline-block;
        font-family: "Barlow Condensed", sans-serif;
        font-size: 42px; font-weight: 700; letter-spacing: 0.02em;
        color: var(--muted); font-variant-numeric: tabular-nums;
      }}
      #strike-line {{
        position: absolute; left: -8px; right: -8px; top: 50%; height: 5px;
        background: var(--danger); border-radius: 2px;
        transform-origin: left center; transform: scaleX(0);
      }}
      #savings-pill {{
        padding: 8px 18px; border-radius: 8px;
        background: rgba(217, 255, 0, 0.12);
        border: 1px solid rgba(217, 255, 0, 0.35);
        color: var(--accent);
        font-size: 24px; font-weight: 800; letter-spacing: 0.03em;
        font-variant-numeric: tabular-nums;
      }}
      #new-price {{
        font-family: "Barlow Condensed", sans-serif;
        font-size: 138px; font-weight: 900; line-height: 0.96;
        letter-spacing: -0.02em;
        color: var(--accent);
        font-variant-numeric: tabular-nums;
      }}
      /* 5. Barra de Ação (CTA) de alto contraste */
      #cta-wrap {{
        margin-top: 32px; position: relative; width: 100%; height: 104px;
        border-radius: 20px; background: #FFFFFF; color: #0A0B0E;
        display: flex; align-items: center; justify-content: center; gap: 16px;
        overflow: hidden;
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
      }}
      #cta-text {{
        font-family: "Barlow Condensed", sans-serif;
        font-size: 44px; font-weight: 900; letter-spacing: 0.04em;
        text-transform: uppercase;
      }}
      #cta-icon {{
        display: flex; align-items: center; justify-content: center;
      }}
      #cta-shine {{
        position: absolute; top: 0; left: -260px; width: 180px; height: 100%;
        background: linear-gradient(90deg, transparent, rgba(10, 11, 14, 0.14), transparent);
        transform: skewX(-22deg);
      }}
      #cta-progress-track {{
        position: absolute; left: 0; bottom: 0; width: 100%; height: 7px;
        background: rgba(10, 11, 14, 0.12);
      }}
      #cta-progress-bar {{
        width: 100%; height: 100%; background: var(--danger);
        transform-origin: left center; transform: scaleX(0);
      }}
      #footer-handle {{
        margin-top: 22px; width: 100%;
        display: flex; justify-content: space-between; align-items: center;
        font-size: 24px; font-weight: 700; color: var(--muted);
        letter-spacing: 0.05em;
      }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{duracao_total}" data-width="1080" data-height="1920">
      <div id="top-accent"></div>
      <div id="bg-grid"></div>
      <div id="stage" class="clip" data-start="0" data-duration="{duracao_total}" data-track-index="0">
        <header id="masthead">
          <div id="brand-lockup">
            <div id="brand-dot"></div>
            <span id="brand-name">GAMESTORE // RADAR</span>
          </div>
          <div id="status-tag">{header_icon_svg}<span>{header_alert_txt}</span></div>
        </header>

        <section id="product-stage">
          {img_html}
          <div id="badge-store">{store_label}</div>
          {badge_off_html}
        </section>

        <h1 id="title">{titulo_html}</h1>

        <section id="price-panel">
          <div id="price-top-row">
            {bloco_preco_antigo}
            {bloco_economia}
          </div>
          <div id="new-price">{preco_novo_str}</div>
        </section>

        <div id="cta-wrap">
          <span id="cta-icon">{cta_icon_svg}</span>
          <span id="cta-text">LINK NO 1º COMENTÁRIO</span>
          <div id="cta-shine"></div>
          <div id="cta-progress-track"><div id="cta-progress-bar"></div></div>
        </div>

        <footer id="footer-handle">
          <span>@PROMOSGEEKTECH</span>
          <span>ESTOQUE LIMITADO</span>
        </footer>
      </div>
      {audio_html}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      /* 0.0s - 0.6s: Hook imediato (palco do produto via clip-path + masthead) */
      tl.fromTo("#masthead", {{ opacity: 0, y: -18 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "power3.out" }}, 0.0);
      tl.fromTo(
        "#product-stage",
        {{ clipPath: "inset(8% 0% 8% 0% round 28px)", opacity: 0, y: 24 }},
        {{ clipPath: "inset(0% 0% 0% 0% round 28px)", opacity: 1, y: 0, duration: 0.55, ease: "power4.out" }},
        0.05
      );
      if (document.querySelector("#product-img")) {{
        tl.fromTo("#product-img", {{ scale: 0.94 }}, {{ scale: 1.06, duration: {max(duracao_total - 0.3, 5.0)}, ease: "none" }}, 0.25);
      }}
      tl.fromTo("#badge-store", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "power3.out" }}, 0.35);
      if (document.querySelector("#badge-off")) {{
        tl.fromTo("#badge-off", {{ opacity: 0, scale: 1.25 }}, {{ opacity: 1, scale: 1, duration: 0.4, ease: "power4.out" }}, 0.4);
      }}

      /* 0.55s: Título entra limpo e legível */
      tl.fromTo("#title", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.42, ease: "power3.out" }}, 0.55);

      /* 0.95s - 1.85s: Momento Focal (Queda de Preço antes dos 2s de retenção!) */
      tl.fromTo("#price-panel", {{ opacity: 0, y: 24 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }}, 0.9);
      if (document.querySelector("#old-price-wrap")) {{
        tl.to("#strike-line", {{ scaleX: 1, duration: 0.38, ease: "power3.inOut" }}, 1.25);
      }}
      tl.fromTo("#new-price", {{ opacity: 0, y: 18 }}, {{ opacity: 1, y: 0, duration: 0.48, ease: "power4.out" }}, 1.38);
      if (document.querySelector("#savings-pill")) {{
        tl.fromTo("#savings-pill", {{ opacity: 0, x: 16 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }}, 1.65);
      }}

      /* 2.0s+: CTA + barra de progresso sincronizada com a locução */
      tl.fromTo("#cta-wrap", {{ opacity: 0, y: 22 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }}, 2.0);
      tl.fromTo("#footer-handle", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.35 }}, 2.25);
      tl.to("#cta-progress-bar", {{ scaleX: 1, duration: {max(duracao_total - 2.1, 4.0)}, ease: "none" }}, 2.1);
      tl.fromTo("#cta-icon", {{ y: -4 }}, {{ y: 5, duration: 0.55, yoyo: true, repeat: 9, ease: "sine.inOut" }}, 2.5);
      tl.fromTo("#cta-shine", {{ left: "-260px" }}, {{ left: "1020px", duration: 0.85, ease: "power2.inOut" }}, 3.2);
      tl.fromTo("#cta-shine", {{ left: "-260px" }}, {{ left: "1020px", duration: 0.85, ease: "power2.inOut" }}, 6.4);

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
