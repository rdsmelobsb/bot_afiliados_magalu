import asyncio
import html
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import textwrap
import unicodedata
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

try:
    import edge_tts
    EDGE_TTS_OK = True
except ImportError:
    EDGE_TTS_OK = False

OUTPUT_DIR = "media_output"
ASSETS_BACKGROUNDS_DIR = os.path.join("assets", "backgrounds")
ASSETS_OUTROS_DIR = os.path.join("assets", "outros")
WIDTH = 1080
HEIGHT = 1920
VOZ_PADRAO_REEL = "pt-BR-ThalitaMultilingualNeural"


def _env_bool_media(nome, default=True):
    val = os.getenv(nome)
    if val is None or str(val).strip() == "":
        return bool(default)
    return str(val).strip().lower() in ("1", "true", "sim", "yes", "on")


def _obter_caminho_fonte_ffmpeg():
    """Retorna o caminho TrueType existente para filtros drawtext do FFmpeg."""
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ):
        if os.path.exists(path):
            return path
    return None


def selecionar_broll_fundo(backgrounds_dir=None):
    """Seleciona aleatoriamente um B-Roll .mp4 válido em assets/backgrounds/, ou None se vazio/desabilitado."""
    if not _env_bool_media("REEL_BROLL_ENABLED", default=True):
        return None
    alvo_dir = backgrounds_dir or ASSETS_BACKGROUNDS_DIR
    if not os.path.isdir(alvo_dir):
        return None
    candidatos = [
        os.path.join(alvo_dir, nome)
        for nome in sorted(os.listdir(alvo_dir))
        if nome.lower().endswith(".mp4")
        and os.path.isfile(os.path.join(alvo_dir, nome))
        and os.path.getsize(os.path.join(alvo_dir, nome)) > 0
    ]
    if not candidatos:
        return None
    return random.choice(candidatos)


def selecionar_outro_gamestore(outros_dir=None):
    """Retorna assets/outros/outro_gamestore.mp4 (ou 1º .mp4 válido), ou None se vazio/desabilitado."""
    if not _env_bool_media("REEL_OUTRO_ENABLED", default=True):
        return None
    alvo_dir = outros_dir or ASSETS_OUTROS_DIR
    if not os.path.isdir(alvo_dir):
        return None
    arquivos = [
        nome
        for nome in sorted(os.listdir(alvo_dir))
        if nome.lower().endswith(".mp4")
        and os.path.isfile(os.path.join(alvo_dir, nome))
        and os.path.getsize(os.path.join(alvo_dir, nome)) > 0
    ]
    if not arquivos:
        return None
    preferido = next((n for n in arquivos if n.lower() == "outro_gamestore.mp4"), None)
    return os.path.join(alvo_dir, preferido or arquivos[0])


def _video_tem_audio(video_path):
    """Verifica via ffprobe se o vídeo possui ao menos uma faixa de áudio."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin or not video_path or not os.path.exists(video_path):
        return False
    try:
        res = subprocess.run(
            [
                ffprobe_bin,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return res.returncode == 0 and "audio" in (res.stdout or "").lower()
    except Exception:
        return False


def preparar_broll_fundo_mp4(broll_path, duracao_segundos, arquivo_saida):
    """
    Normaliza um B-Roll do Google Flow em loop contínuo cortado na duração exata:
    1080x1920, 30fps, yuv420p, com scrim escuro (black@0.60) para legibilidade máxima.
    """
    if not broll_path or not os.path.exists(broll_path):
        return None
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return None

    os.makedirs(os.path.dirname(os.path.abspath(arquivo_saida)), exist_ok=True)
    dur_str = f"{max(1.0, float(duracao_segundos)):.2f}"
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,fps=30,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.60:t=fill,"
        "format=yuv420p"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-stream_loop", "-1",
        "-i", broll_path,
        "-t", dur_str,
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-movflags", "+faststart",
        arquivo_saida,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and os.path.exists(arquivo_saida) and os.path.getsize(arquivo_saida) > 10000:
            logging.info(f"🎞️ B-Roll de fundo normalizado ({dur_str}s): {os.path.basename(broll_path)}")
            return arquivo_saida
        logging.warning(f"Falha ao normalizar B-Roll ({res.returncode}): {(res.stderr or '')[-300:]}")
    except Exception as exc:
        logging.warning(f"Exceção ao preparar B-Roll de fundo: {exc}")
    return None


def anexar_outro_gamestore(
    reel_path,
    outro_path=None,
    arquivo_saida=None,
    cta_texto="SIGA @PROMOSGEEKTECH • LINK NA BIO",
):
    """
    Concatena a vinheta Outro de ~2s da Gamestore ao final do Reel com normalização obrigatória
    (1080x1920, 30fps, yuv420p, AAC 44100Hz estéreo), injetando anullsrc se algum clipe não tiver áudio
    e adicionando o CTA discreto na Safe Zone acima dos últimos 540px.
    """
    if not reel_path or not os.path.exists(reel_path):
        return reel_path

    outro_alvo = outro_path if outro_path is not None else selecionar_outro_gamestore()
    if not outro_alvo or not os.path.exists(outro_alvo):
        return reel_path

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logging.warning("ffmpeg indisponível para anexar Outro Gamestore. Mantendo Reel original.")
        return reel_path

    reel_tem_audio = _video_tem_audio(reel_path)
    outro_tem_audio = _video_tem_audio(outro_alvo)
    dur_reel = _obter_duracao_audio(reel_path) or 10.0
    dur_outro = _obter_duracao_audio(outro_alvo) or 2.0

    inputs = ["-i", reel_path, "-i", outro_alvo]
    next_idx = 2

    if reel_tem_audio:
        a0_expr = "[0:a]aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a0]"
    else:
        inputs.extend(["-f", "lavfi", "-t", f"{dur_reel:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
        a0_expr = f"[{next_idx}:a]atrim=duration={dur_reel:.2f},aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a0]"
        next_idx += 1

    if outro_tem_audio:
        a1_expr = "[1:a]aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a1]"
    else:
        inputs.extend(["-f", "lavfi", "-t", f"{dur_outro:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
        a1_expr = f"[{next_idx}:a]atrim=duration={dur_outro:.2f},aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a1]"
        next_idx += 1

    drawtext_cta = ""
    cta_limpo = re.sub(r"[:'\";\\]", " ", str(cta_texto or "")).strip()
    if cta_limpo:
        font_path = _obter_caminho_fonte_ffmpeg()
        font_opt = ""
        if font_path:
            font_esc = font_path.replace("\\", "/").replace(":", "\\:")
            font_opt = f"fontfile='{font_esc}':"
        # Posicionado em y=1290 (mantém os últimos ~540px / 28% da base livres — Safe Zone Reels)
        drawtext_cta = (
            f",drawtext={font_opt}text='{cta_limpo}':"
            "fontcolor=#F5F7FA:fontsize=30:x=(w-text_w)/2:y=1290:"
            "box=1:boxcolor=0x0A0B0E@0.72:boxborderw=18"
        )

    filter_complex = ";".join([
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=#0A0B0E,fps=30,setsar=1,format=yuv420p[v0]",
        f"[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,fps=30,setsar=1{drawtext_cta},format=yuv420p[v1]",
        a0_expr,
        a1_expr,
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]",
    ])

    destino = arquivo_saida or reel_path
    destino_tmp = f"{destino}.outro_tmp.mp4"
    cmd = [
        ffmpeg_bin,
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        destino_tmp,
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode == 0 and os.path.exists(destino_tmp) and os.path.getsize(destino_tmp) > 10000:
            os.replace(destino_tmp, destino)
            logging.info(f"⚡ Vinheta Outro Gamestore anexada ao Reel: {destino}")
            return destino
        logging.warning(f"FFmpeg concat Outro falhou ({res.returncode}): {(res.stderr or '')[-400:]}")
    except Exception as exc:
        logging.warning(f"Exceção ao anexar Outro Gamestore: {exc}")
    finally:
        if os.path.exists(destino_tmp):
            try:
                os.remove(destino_tmp)
            except Exception:
                pass

    return reel_path


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
    Gera um criativo vertical 9:16 (1080x1920) com estética Impeccable Tech Editorial:
      - Zona segura calibrada para UI do Facebook Stories/Reels (topo >= 225px, rodapé >= 210px)
      - Fundo obsidian (#0A0B0E) com micro-grade arquitetônica e faixa de acento
      - Cabeçalho GAMESTORE // RADAR + tag MENOR PREÇO 30D / OFERTA VERIFICADA
      - Palco branco de estúdio com foto do produto + carimbo -XX% OFF e selo da loja integrados
      - Painel de preço (#13161D) com De/Por + tag ECONOMIZE R$ ...
      - Barra de CTA branca de alto contraste sem estouro de texto
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
    is_min_hist = bool(oportunidade.get("menor_preco_historico"))

    # Paleta Impeccable Tech Editorial
    cor_bg = (10, 11, 14)          # #0A0B0E
    cor_grid = (20, 22, 28)        # micro-grade sutil
    cor_surface = (19, 22, 29)     # #13161D
    cor_border = (42, 46, 58)      # hairline
    cor_text = (245, 247, 250)     # #F5F7FA
    cor_muted = (154, 163, 178)    # #9AA3B2
    cor_accent = (217, 255, 0) if is_ml else (56, 189, 248)  # Volt Lime (ML) / Cyan (Magalu)
    cor_danger = (255, 59, 48)     # #FF3B30
    cor_store_bg = (255, 230, 0) if is_ml else (0, 134, 255)
    cor_store_fg = (10, 11, 14) if is_ml else (255, 255, 255)

    # 1. Fundo obsidian + micro-grade arquitetônica + faixa superior de acento
    canvas = Image.new("RGB", (WIDTH, HEIGHT), cor_bg)
    draw = ImageDraw.Draw(canvas)
    for gx in range(0, WIDTH, 54):
        draw.line([(gx, 0), (gx, HEIGHT)], fill=cor_grid, width=1)
    for gy in range(0, HEIGHT, 54):
        draw.line([(0, gy), (WIDTH, gy)], fill=cor_grid, width=1)
    draw.rectangle([0, 0, WIDTH, 10], fill=cor_accent)

    pad_x = 76
    inner_w = WIDTH - (pad_x * 2)  # 928px

    # 2. Masthead editorial abaixo da zona segura do Facebook Stories (y=225)
    y_head = 225
    f_brand = _carregar_fonte(34, bold=True)
    f_tag = _carregar_fonte(24, bold=True)
    draw.rounded_rectangle([pad_x, y_head + 10, pad_x + 14, y_head + 24], radius=3, fill=cor_accent)
    draw.text((pad_x + 28, y_head), "GAMESTORE // RADAR", font=f_brand, fill=cor_text)

    tag_txt = "MENOR PREÇO 180D" if is_min_hist else "OFERTA VERIFICADA"
    tb = draw.textbbox((0, 0), tag_txt, font=f_tag)
    tw_tag = (tb[2] - tb[0]) + 36
    th_tag = 48
    tx_tag = WIDTH - pad_x - tw_tag
    draw.rounded_rectangle(
        [tx_tag, y_head - 4, WIDTH - pad_x, y_head - 4 + th_tag],
        radius=8, fill=cor_surface, outline=cor_border, width=2,
    )
    draw.text((tx_tag + 18, y_head + 6), tag_txt, font=f_tag, fill=cor_accent)
    draw.line([(pad_x, y_head + 60), (WIDTH - pad_x, y_head + 60)], fill=cor_border, width=2)

    # 3. Palco branco de estúdio para foto do produto + selos integrados
    box_x = pad_x
    box_y = y_head + 86  # 311px
    box_w = inner_w      # 928px
    box_h = 660

    draw.rounded_rectangle([box_x + 8, box_y + 12, box_x + box_w + 8, box_y + box_h + 12], radius=28, fill=(4, 5, 8))
    draw.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h], radius=28, fill=(255, 255, 255))

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
            prod = ImageOps.contain(prod, (box_w - 110, box_h - 110), Image.Resampling.LANCZOS)
            px = box_x + (box_w - prod.width) // 2
            py = box_y + (box_h - prod.height) // 2
            canvas.paste(prod, (px, py))
        except Exception as e:
            logging.warning(f"Falha ao colar foto do produto no card 9:16: {e}")

    # Selo da loja integrado (canto inferior esquerdo do palco)
    f_store = _carregar_fonte(28, bold=True)
    texto_loja = "MERCADO LIVRE" if is_ml else "MAGALU OFICIAL"
    sb = draw.textbbox((0, 0), texto_loja, font=f_store)
    sw = (sb[2] - sb[0]) + 42
    sh = 54
    sx = box_x + 26
    sy = box_y + box_h - sh - 26
    draw.rounded_rectangle([sx, sy, sx + sw, sy + sh], radius=10, fill=cor_store_bg)
    draw.text((sx + 21, sy + 11), texto_loja, font=f_store, fill=cor_store_fg)

    # Carimbo de desconto integrado (canto superior direito do palco)
    if desconto >= 5:
        f_disc = _carregar_fonte(46, bold=True)
        texto_disc = f"-{desconto:.0f}% OFF"
        db = draw.textbbox((0, 0), texto_disc, font=f_disc)
        dw = (db[2] - db[0]) + 46
        dh = 74
        dx = box_x + box_w - dw - 26
        dy = box_y + 26
        draw.rounded_rectangle([dx, dy, dx + dw, dy + dh], radius=14, fill=cor_danger)
        draw.text((dx + 23, dy + 11), texto_disc, font=f_disc, fill=(255, 255, 255))

    # 4. Título do Produto (alinhado à esquerda, até 2 linhas limpas)
    f_title = _carregar_fonte(44, bold=True)
    linhas_titulo = textwrap.wrap(titulo, width=32)[:2]
    y_curr = box_y + box_h + 36
    for linha in linhas_titulo:
        draw.text((pad_x, y_curr), linha, font=f_title, fill=cor_text)
        tb_l = draw.textbbox((0, 0), linha, font=f_title)
        y_curr += (tb_l[3] - tb_l[1]) + 14

    # 5. Painel de Preço (#13161D) + Economia Real em Reais
    panel_y = y_curr + 22
    panel_h = 228
    draw.rounded_rectangle(
        [pad_x, panel_y, WIDTH - pad_x, panel_y + panel_h],
        radius=24, fill=cor_surface, outline=cor_border, width=2,
    )

    inner_px = pad_x + 34
    if preco_antigo and float(preco_antigo) > preco_atual:
        preco_antigo_f = float(preco_antigo)
        economia_f = preco_antigo_f - preco_atual
        f_old = _carregar_fonte(36, bold=True)
        txt_old = f"DE R$ {preco_antigo_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        ob = draw.textbbox((0, 0), txt_old, font=f_old)
        ow, oh = ob[2] - ob[0], ob[3] - ob[1]
        oy = panel_y + 28
        draw.text((inner_px, oy), txt_old, font=f_old, fill=cor_muted)
        draw.line([(inner_px - 6, oy + oh // 2 + 4), (inner_px + ow + 6, oy + oh // 2 + 4)], fill=cor_danger, width=5)

        # Pill ECONOMIZE R$ ... alinhada à direita dentro do painel
        f_sav = _carregar_fonte(24, bold=True)
        txt_sav = f"ECONOMIZE R$ {economia_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        eb = draw.textbbox((0, 0), txt_sav, font=f_sav)
        ew = (eb[2] - eb[0]) + 32
        eh = 44
        ex = WIDTH - pad_x - 34 - ew
        ey = panel_y + 24
        draw.rounded_rectangle([ex, ey, ex + ew, ey + eh], radius=8, fill=(24, 34, 24) if is_ml else (16, 36, 52), outline=cor_accent, width=2)
        draw.text((ex + 16, ey + 8), txt_sav, font=f_sav, fill=cor_accent)

    f_price = _carregar_fonte(102, bold=True)
    txt_price = f"R$ {preco_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    draw.text((inner_px, panel_y + 88), txt_price, font=f_price, fill=cor_accent)

    # 6. Botão CTA branco de alto contraste (com ajuste de fonte para nunca estourar a borda)
    cta_txt = "LINK NO 1º COMENTÁRIO" if modo == "reel" else "TELEGRAM: @PROMOSGEEKTECH"
    cta_y = panel_y + panel_h + 30
    cta_h = 98
    draw.rounded_rectangle([pad_x, cta_y, WIDTH - pad_x, cta_y + cta_h], radius=20, fill=(255, 255, 255))
    f_cta = _carregar_fonte(38, bold=True)
    _centralizar_texto(draw, cta_y + 26, cta_txt, f_cta, (10, 11, 14))

    # Rodapé editorial
    f_foot = _carregar_fonte(24, bold=True)
    y_foot = cta_y + cta_h + 24
    draw.text((pad_x, y_foot), "@PROMOSGEEKTECH", font=f_foot, fill=cor_muted)
    fb_r = draw.textbbox((0, 0), "ESTOQUE LIMITADO", font=f_foot)
    draw.text((WIDTH - pad_x - (fb_r[2] - fb_r[0]), y_foot), "ESTOQUE LIMITADO", font=f_foot, fill=cor_muted)

    canvas.save(arquivo_saida, format="JPEG", quality=93)
    logging.info(f"🎨 Card vertical 9:16 (Impeccable) gerado: {arquivo_saida}")
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


def gerar_video_reel_mp4(
    imagem_card_path,
    arquivo_saida=None,
    duracao_segundos=9,
    audio_path=None,
    usar_broll=True,
    aplicar_outro=True,
):
    """
    Converte o card vertical 1080x1920 em um vídeo MP4 pronto para Reels/Shorts/TikTok
    usando ffmpeg (suporte a B-Roll em loop + zoom suave + fade-in + locução da Thalita + Outro 2s).
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
            duracao_segundos = max(8, min(26, int(math.ceil(dur_audio + 0.8))))

    fps = 30
    total_frames = duracao_segundos * fps
    broll_path = selecionar_broll_fundo() if usar_broll else None
    is_png_alpha = str(imagem_card_path).lower().endswith(".png")

    if tem_audio_real:
        audio_inputs = ["-i", audio_path]
        audio_idx = 2 if (broll_path and is_png_alpha) else 1
    else:
        audio_inputs = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        audio_idx = 2 if (broll_path and is_png_alpha) else 1

    if broll_path and is_png_alpha:
        filter_complex = (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,fps={fps},"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.60:t=fill[bg];"
            f"[1:v]scale=1080:1920,fade=t=in:st=0:d=0.4[fg];"
            f"[bg][fg]overlay=0:0:shortest=1,format=yuv420p[v]"
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-stream_loop", "-1",
            "-i", broll_path,
            "-loop", "1",
            "-i", imagem_card_path,
            *audio_inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", f"{audio_idx}:a",
            "-t", str(duracao_segundos),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            arquivo_saida,
        ]
    else:
        # Zoom suave de 1.00x até ~1.08x centralizado + fade in de 0.4s (suporta 9:16 1080x1920)
        vf = (
            f"scale=1080:1920,"
            f"zoompan=z='min(zoom+0.00028,1.08)':d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
            f"fade=t=in:st=0:d=0.4,format=yuv420p"
        )
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
            if aplicar_outro:
                return anexar_outro_gamestore(arquivo_saida)
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
    header_alert_txt = "MENOR PREÇO 180D" if is_min_hist else "OFERTA VERIFICADA"
    broll_selecionado = selecionar_broll_fundo()
    broll_pronto = None
    if broll_selecionado:
        broll_pronto = preparar_broll_fundo_mp4(
            broll_selecionado,
            duracao_total,
            os.path.join(assets_dir, "broll_bg.mp4"),
        )
    broll_html = (
        f'<video id="broll-bg" src="./assets/broll_bg.mp4" muted playsinline '
        f'data-start="0" data-duration="{duracao_total}" data-track-index="0"></video>'
        '<div id="broll-scrim"></div>'
        if broll_pronto
        else ""
    )
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
      #broll-bg {{
        position: absolute; inset: 0; width: 1080px; height: 1920px;
        object-fit: cover; z-index: 0;
      }}
      #broll-scrim {{
        position: absolute; inset: 0; pointer-events: none; z-index: 1;
        background: radial-gradient(ellipse 90% 80% at 50% 45%, rgba(10, 11, 14, 0.55) 0%, rgba(10, 11, 14, 0.78) 100%);
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
      {broll_html}
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
            return anexar_outro_gamestore(arquivo_saida_abs)
        err_tail = (res.stderr or res.stdout or "").strip()[-400:]
        logging.warning(f"HyperFrames retornou código {res.returncode} ({err_tail}). Acionando fallback Pillow+ffmpeg.")
    except Exception as e:
        logging.warning(f"Exceção no HyperFrames (acionando fallback Pillow+ffmpeg): {e}")

    return None


# --- FÁBRICA EDITORIAL TECH/GAMER (Card 4:5 + Reel 9:16 HyperFrames com Thalita) ---


def _paleta_categoria_editorial(tag_categoria):
    """Retorna paleta neon calibrada para contraste sobre scrim obsidian."""
    cat = str(tag_categoria or "TECH").strip().upper()
    if any(k in cat for k in ("HARD", "GPU", "CPU", "PC", "SSD")):
        return (217, 255, 0), "#D9FF00", "HARDWARE"
    if any(k in cat for k in ("GAME", "JOGO", "CONSOLE", "PS5", "XBOX", "SWITCH")):
        return (0, 240, 255), "#00F0FF", "GAMES"
    if any(k in cat for k in ("TECH", "CEL", "MOBILE", "AI", "IA")):
        return (250, 204, 21), "#FACC15", "TECH"
    return (56, 189, 248), "#38BDF8", (cat[:16] or "TECH")


def _norm_palavra(txt):
    bruto = unicodedata.normalize("NFKD", str(txt or "").lower())
    sem_acentos = "".join(ch for ch in bruto if not unicodedata.combining(ch))
    return re.sub(r"[^\w]", "", sem_acentos)


def _aplicar_destaque_html(headline, destaque):
    """Destaca palavras de destaque_card dentro da headline HTML sem quebrar acentos."""
    hl_str = str(headline or "").strip()
    tokens_dest = {_norm_palavra(p) for p in str(destaque or "").split() if _norm_palavra(p)}
    if not tokens_dest:
        return html.escape(hl_str)

    partes = []
    for palavra in hl_str.split():
        esc = html.escape(palavra)
        if _norm_palavra(palavra) in tokens_dest:
            partes.append(f'<span class="hl-accent">{esc}</span>')
        else:
            partes.append(esc)
    return " ".join(partes)


def gerar_locucao_texto_ptbr(
    texto_fala,
    arquivo_saida=None,
    voice=VOZ_PADRAO_REEL,
    rate="+8%",
):
    """Gera locução neural PT-BR via edge-tts (Thalita) a partir de roteiro pronto."""
    if not EDGE_TTS_OK:
        logging.warning("Biblioteca 'edge-tts' não instalada. Reel editorial será gerado sem voz.")
        return None

    fala_limpa = re.sub(r"https?://\S+", "", str(texto_fala or ""))
    fala_limpa = re.sub(r"\s+", " ", fala_limpa).strip()
    if not fala_limpa:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "reel_editorial_voz.mp3")

    try:
        async def _run():
            comm = edge_tts.Communicate(fala_limpa, voice=voice, rate=rate)
            await comm.save(arquivo_saida)

        asyncio.run(_run())
        if os.path.exists(arquivo_saida) and os.path.getsize(arquivo_saida) > 1000:
            logging.info(f"🎙️ Locução editorial PT-BR ({voice}) gerada: {arquivo_saida}")
            return arquivo_saida
    except Exception as exc:
        logging.warning(f"Falha ao gerar locução editorial edge-tts: {exc}")

    return None


def gerar_card_editorial_rss(
    headline_card,
    destaque_card="",
    tag_categoria="TECH",
    fonte="Redação",
    img_bytes=None,
    arquivo_saida=None,
    tamanho=(1080, 1350),
    modo="feed",
):
    """
    Gera card editorial (4:5 Feed 1080x1350, 9:16 Story 1080x1920 ou 9:16 Reel fallback):
      - Foto real da notícia com smart-crop (ou fundo obsidian com grade e glow quando sem foto)
      - Scrim cinematográfico escuro calibrado para safe zones e contraste WCAG na tipografia
      - Pill de categoria neon no topo + headline bold com palavras em destaque neon
      - Barra de rodapé limpa: GAMESTORE / GIRO GAMESTORE  •  VIA [FONTE]
    """
    if not PILLOW_OK:
        logging.warning("Pillow não disponível para gerar card editorial.")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "card_editorial_rss.jpg")

    w, h = int(tamanho[0]), int(tamanho[1])
    modo_norm = str(modo or "feed").strip().lower()
    if modo_norm == "feed" and h >= 1700:
        modo_norm = "story"

    cor_accent, _, cat_label = _paleta_categoria_editorial(tag_categoria)
    cor_bg = (10, 11, 14)
    cor_text = (245, 247, 250)
    cor_muted = (165, 174, 190)

    # 1. Fundo: foto real com crop inteligente ou obsidian tech editorial
    canvas = None
    if img_bytes:
        try:
            foto = Image.open(BytesIO(img_bytes))
            if foto.mode in ("RGBA", "LA", "P"):
                fundo = Image.new("RGB", foto.size, cor_bg)
                if foto.mode == "P":
                    foto = foto.convert("RGBA")
                fundo.paste(foto, mask=foto.split()[-1] if foto.mode == "RGBA" else None)
                foto = fundo
            else:
                foto = foto.convert("RGB")
            foto = ImageOps.fit(foto, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
            foto = ImageEnhance.Contrast(foto).enhance(1.06)
            canvas = foto
        except Exception as exc:
            logging.warning(f"Falha ao processar foto da notícia no card editorial (usando fallback dark): {exc}")
            canvas = None

    if canvas is None:
        canvas = Image.new("RGB", (w, h), cor_bg)
        draw_bg = ImageDraw.Draw(canvas)
        for gx in range(0, w, 54):
            draw_bg.line([(gx, 0), (gx, h)], fill=(20, 23, 30), width=1)
        for gy in range(0, h, 54):
            draw_bg.line([(0, gy), (w, gy)], fill=(20, 23, 30), width=1)
        # Glow sutil no topo direito com a cor da categoria
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dg = ImageDraw.Draw(glow)
        for rad, alp in ((520, 22), (380, 28), (240, 34)):
            dg.ellipse([w - rad - 40, -rad // 2, w + rad // 2, rad + 120], fill=(*cor_accent, alp))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), glow).convert("RGB")

    # 2. Scrim cinematográfico vertical + Safe Zones por formato
    if modo_norm == "reel":
        pad_left, pad_right = 72, 164
        y_top = 224
        footer_bottom_margin = 544
        bot_start_frac, bot_solid_frac = 0.26, 0.56
    elif modo_norm == "story":
        pad_left, pad_right = 72, 72
        y_top = 224
        footer_bottom_margin = 310
        bot_start_frac, bot_solid_frac = 0.30, 0.66
    else:
        pad_left, pad_right = 72, 72
        y_top = 58
        footer_bottom_margin = 72
        bot_start_frac, bot_solid_frac = 0.30, 0.72

    scrim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    top_end = int(h * 0.22)
    bot_start = int(h * bot_start_frac)
    bot_solid = int(h * bot_solid_frac)

    for y in range(h):
        alpha = 0
        if y < top_end:
            ratio = 1.0 - (y / max(top_end, 1))
            alpha = int(180 * ratio)
        if y >= bot_start:
            if y >= bot_solid:
                alpha = max(alpha, 246)
            else:
                ratio = (y - bot_start) / max(bot_solid - bot_start, 1)
                alpha = max(alpha, int(246 * (ratio ** 1.35)))
        if alpha > 0:
            scrim_draw.line([(0, y), (w, y)], fill=(10, 11, 14, alpha))

    canvas = Image.alpha_composite(canvas.convert("RGBA"), scrim).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    # Faixa superior de acento
    draw.rectangle([0, 0, w, 9], fill=cor_accent)

    max_txt_w = max(320, w - pad_left - pad_right)

    # 3. Pill de categoria no topo + selo discreto
    f_pill = _carregar_fonte(26, bold=True)
    pill_txt = cat_label
    pb = draw.textbbox((0, 0), pill_txt, font=f_pill)
    pill_w = (pb[2] - pb[0]) + 62
    pill_h = 52
    draw.rounded_rectangle(
        [pad_left, y_top, pad_left + pill_w, y_top + pill_h],
        radius=12,
        fill=(15, 18, 25),
        outline=cor_accent,
        width=2,
    )
    draw.rounded_rectangle(
        [pad_left + 18, y_top + 17, pad_left + 34, y_top + 33],
        radius=4,
        fill=cor_accent,
    )
    draw.text((pad_left + 44, y_top + 11), pill_txt, font=f_pill, fill=cor_text)

    f_giro = _carregar_fonte(24, bold=True)
    top_right_txt = "@PROMOSGEEKTECH" if modo_norm == "story" else "GIRO GAMESTORE"
    gb = draw.textbbox((0, 0), top_right_txt, font=f_giro)
    draw.text((w - pad_right - (gb[2] - gb[0]), y_top + 13), top_right_txt, font=f_giro, fill=cor_muted)

    # 4. Headline editorial com auto-ajuste de fonte + destaque neon inline
    headline_limpa = re.sub(r"\s+", " ", str(headline_card or "Novidade Tech & Gamer")).strip()
    tokens_dest = {_norm_palavra(p) for p in str(destaque_card or "").split() if _norm_palavra(p)}

    font_hl = _carregar_fonte(60, bold=True)
    linhas_hl = [headline_limpa]
    line_step = 72
    tamanhos_candidatos = (58, 52, 46, 42) if modo_norm == "reel" else (68, 62, 56, 50, 44)
    for tam_fonte in tamanhos_candidatos:
        cand_font = _carregar_fonte(tam_fonte, bold=True)
        # Calcula largura aproximada e envolve palavra a palavra com precisão em px
        palavras = headline_limpa.split()
        linhas_tmp = []
        atual = ""
        for pal in palavras:
            teste = f"{atual} {pal}".strip()
            tb = draw.textbbox((0, 0), teste, font=cand_font)
            if (tb[2] - tb[0]) <= max_txt_w or not atual:
                atual = teste
            else:
                linhas_tmp.append(atual)
                atual = pal
        if atual:
            linhas_tmp.append(atual)
        if len(linhas_tmp) <= 4:
            font_hl = cand_font
            linhas_hl = linhas_tmp
            line_step = int(tam_fonte * 1.18)
            break
    else:
        font_hl = _carregar_fonte(42 if modo_norm == "reel" else 44, bold=True)
        linhas_hl = textwrap.wrap(headline_limpa, width=22 if modo_norm == "reel" else 26)[:4]
        line_step = 50 if modo_norm == "reel" else 54

    # Posicionamento acima do rodapé respeitando a safe zone do modo
    y_footer_txt = h - footer_bottom_margin
    y_divider = y_footer_txt - 28
    hl_block_h = len(linhas_hl) * line_step
    y_accent_bar = y_divider - hl_block_h - 36
    y_hl_start = y_accent_bar + 22

    # Barra de acento curta antes da manchete
    draw.rounded_rectangle([pad_left, y_accent_bar, pad_left + 92, y_accent_bar + 7], radius=4, fill=cor_accent)

    # Renderização palavra por palavra com sombra leve + cor neon nas palavras-chave
    for idx_l, linha in enumerate(linhas_hl):
        y_line = y_hl_start + (idx_l * line_step)
        x_cursor = pad_left
        palavras_linha = linha.split()
        for p_idx, pal in enumerate(palavras_linha):
            is_hi = _norm_palavra(pal) in tokens_dest
            cor_pal = cor_accent if is_hi else cor_text
            sufixo = " " if p_idx < len(palavras_linha) - 1 else ""
            trecho = pal + sufixo
            draw.text((x_cursor + 2, y_line + 3), trecho, font=font_hl, fill=(0, 0, 0))
            draw.text((x_cursor, y_line), trecho, font=font_hl, fill=cor_pal)
            pb_w = draw.textbbox((0, 0), trecho, font=font_hl)
            x_cursor += pb_w[2] - pb_w[0]

    # 5. Barra de rodapé limpa
    draw.line([(pad_left, y_divider), (w - pad_right, y_divider)], fill=(48, 54, 68), width=2)
    f_foot = _carregar_fonte(24 if modo_norm == "reel" else 26, bold=True)
    fonte_upper = str(fonte or "REDAÇÃO").strip().upper()

    if modo_norm == "story":
        foot_story = f"GIRO GAMESTORE  •  VIA {fonte_upper}"
        draw.text((pad_left, y_footer_txt), foot_story, font=f_foot, fill=cor_muted)
    elif modo_norm == "reel":
        foot_reel = f"GAMESTORE  •  VIA {fonte_upper}"
        draw.text((pad_left, y_footer_txt), foot_reel, font=f_foot, fill=cor_text)
    else:
        foot_left = f"GAMESTORE  •  VIA {fonte_upper}"
        draw.text((pad_left, y_footer_txt), foot_left, font=f_foot, fill=cor_text)

        foot_right = "@PROMOSGEEKTECH"
        frb = draw.textbbox((0, 0), foot_right, font=f_foot)
        draw.text((w - pad_right - (frb[2] - frb[0]), y_footer_txt), foot_right, font=f_foot, fill=cor_accent)

    canvas.save(arquivo_saida, format="JPEG", quality=93)
    logging.info(f"🎨 Card editorial {w}x{h} ({modo_norm}) gerado: {arquivo_saida}")
    return arquivo_saida


def gerar_story_editorial_rss(
    headline_card,
    destaque_card="",
    tag_categoria="TECH",
    fonte="Redação",
    img_bytes=None,
    arquivo_saida=None,
):
    """Gera Story editorial estático 9:16 (1080x1920, sem narração) em media_output/story_editorial.jpg."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "story_editorial.jpg")
    return gerar_card_editorial_rss(
        headline_card=headline_card,
        destaque_card=destaque_card,
        tag_categoria=tag_categoria,
        fonte=fonte,
        img_bytes=img_bytes,
        arquivo_saida=arquivo_saida,
        tamanho=(1080, 1920),
        modo="story",
    )


def gerar_reel_editorial_rss(
    headline_card,
    destaque_card="",
    tag_categoria="TECH",
    fonte="Redação",
    roteiro_reel="",
    img_bytes=None,
    arquivo_saida=None,
):
    """
    Gera Reel Editorial 9:16 (1080x1920) via HeyGen HyperFrames + locução da Thalita (edge-tts),
    com fallback automático para Card 9:16 Pillow + ffmpeg.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not arquivo_saida:
        arquivo_saida = os.path.join(OUTPUT_DIR, "reel_editorial_rss.mp4")
    arquivo_saida_abs = os.path.abspath(arquivo_saida)

    voz_path = gerar_locucao_texto_ptbr(
        roteiro_reel or headline_card,
        arquivo_saida=os.path.join(OUTPUT_DIR, "reel_editorial_voz.mp3"),
    )

    duracao_audio = 0.0
    duracao_total = 12.0
    tem_audio = False
    if voz_path and os.path.exists(voz_path):
        dur_probe = _obter_duracao_audio(voz_path)
        duracao_audio = round(dur_probe, 2) if dur_probe else 12.0
        duracao_total = round(max(10.0, min(26.0, duracao_audio + 0.8)), 2)
        tem_audio = True

    hf_bin = shutil.which("hyperframes") or shutil.which("hyperframes.cmd")
    npx_bin = shutil.which("npx") or shutil.which("npx.cmd")

    if hf_bin or npx_bin:
        job_dir = os.path.abspath(os.path.join(OUTPUT_DIR, "hf_editorial_job"))
        assets_dir = os.path.join(job_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        tem_img = False
        if img_bytes:
            try:
                with open(os.path.join(assets_dir, "noticia.jpg"), "wb") as f_img:
                    f_img.write(img_bytes)
                tem_img = True
            except Exception as exc:
                logging.warning(f"Erro ao gravar noticia.jpg para Reel editorial: {exc}")

        if tem_audio:
            shutil.copy2(voz_path, os.path.join(assets_dir, "voz_editorial.mp3"))

        _, accent_hex, cat_label = _paleta_categoria_editorial(tag_categoria)
        headline_markup = _aplicar_destaque_html(headline_card, destaque_card)
        fonte_esc = html.escape(str(fonte or "REDAÇÃO").strip().upper())

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

        bg_img_html = '<img id="hero-img" src="./assets/noticia.jpg" alt="Notícia" />' if tem_img else ""
        audio_html = (
            f'<audio src="./assets/voz_editorial.mp3" data-start="0.2" data-duration="{duracao_audio}" data-track-index="1"></audio>'
            if tem_audio
            else ""
        )

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
        --text: #F5F7FA;
        --muted: #A5AEBE;
        --accent: {accent_hex};
      }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        width: 1080px; height: 1920px; overflow: hidden;
        background: var(--bg);
        font-family: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, sans-serif;
        color: var(--text);
      }}
      #root {{
        position: relative; width: 1080px; height: 1920px; overflow: hidden;
        background: var(--bg);
      }}
      #bg-grid {{
        position: absolute; inset: 0;
        background-image:
          linear-gradient(to right, rgba(255,255,255,0.035) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(255,255,255,0.035) 1px, transparent 1px);
        background-size: 54px 54px;
      }}
      #hero-img {{
        position: absolute; inset: 0; width: 1080px; height: 1920px;
        object-fit: cover; object-position: 50% 35%;
        transform-origin: center center;
      }}
      #scrim {{
        position: absolute; inset: 0;
        background: linear-gradient(
          180deg,
          rgba(10,11,14,0.78) 0%,
          rgba(10,11,14,0.20) 20%,
          rgba(10,11,14,0.34) 34%,
          rgba(10,11,14,0.88) 54%,
          rgba(10,11,14,0.96) 72%,
          rgba(10,11,14,0.99) 100%
        );
      }}
      #top-stripe {{
        position: absolute; top: 0; left: 0; width: 1080px; height: 10px;
        background: var(--accent); z-index: 6;
      }}
      /* Invariante HyperFrames: class="clip" apenas no container raiz #stage + Safe Zone Reels */
      #stage {{
        position: absolute; inset: 0; width: 1080px; height: 1920px;
        display: flex; flex-direction: column; justify-content: space-between;
        padding: 224px 164px 540px 72px; z-index: 4;
      }}
      #masthead {{
        display: flex; align-items: center; justify-content: space-between; gap: 16px;
      }}
      #cat-pill {{
        display: inline-flex; align-items: center; gap: 12px;
        padding: 10px 22px; border-radius: 12px;
        background: rgba(15, 18, 25, 0.90);
        border: 2px solid var(--accent);
        font-family: "Barlow Condensed", sans-serif;
        font-size: 28px; font-weight: 900; letter-spacing: 0.08em;
      }}
      #cat-dot {{ width: 12px; height: 12px; border-radius: 4px; background: var(--accent); }}
      #brand-tag {{
        font-family: "Barlow Condensed", sans-serif;
        font-size: 26px; font-weight: 800; letter-spacing: 0.08em;
        color: var(--muted);
      }}
      #bottom-block {{
        display: flex; flex-direction: column; gap: 22px;
      }}
      #accent-rule {{
        width: 100px; height: 8px; border-radius: 4px;
        background: var(--accent); transform-origin: left center;
      }}
      #headline {{
        font-size: 58px; font-weight: 800; line-height: 1.14;
        letter-spacing: -0.025em;
        text-shadow: 0 4px 20px rgba(0, 0, 0, 0.72);
      }}
      .hl-accent {{ color: var(--accent); }}
      #progress-track {{
        width: 100%; height: 6px; border-radius: 999px;
        background: rgba(255, 255, 255, 0.14); overflow: hidden;
      }}
      #progress-bar {{
        width: 100%; height: 100%; background: var(--accent);
        transform-origin: left center; transform: scaleX(0);
      }}
      #footer-bar {{
        display: flex; justify-content: space-between; align-items: center;
        gap: 12px; flex-wrap: wrap;
        font-family: "Barlow Condensed", sans-serif;
        font-size: 26px; font-weight: 800; letter-spacing: 0.05em;
      }}
      #footer-handle {{ color: var(--accent); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="editorial" data-start="0" data-duration="{duracao_total}" data-width="1080" data-height="1920">
      <div id="top-stripe"></div>
      <div id="bg-grid"></div>
      {bg_img_html}
      <div id="scrim"></div>
      <div id="stage" class="clip" data-start="0" data-duration="{duracao_total}" data-track-index="0">
        <header id="masthead">
          <div id="cat-pill"><span id="cat-dot"></span><span>{cat_label}</span></div>
          <span id="brand-tag">GIRO GAMESTORE</span>
        </header>
        <section id="bottom-block">
          <div id="accent-rule"></div>
          <h1 id="headline">{headline_markup}</h1>
          <div id="progress-track"><div id="progress-bar"></div></div>
          <footer id="footer-bar">
            <span>GAMESTORE  •  VIA {fonte_esc}</span>
            <span id="footer-handle">@PROMOSGEEKTECH</span>
          </footer>
        </section>
      </div>
      {audio_html}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      if (document.querySelector("#hero-img")) {{
        tl.fromTo("#hero-img", {{ scale: 1.0 }}, {{ scale: 1.12, duration: {duracao_total}, ease: "none" }}, 0.0);
      }}
      tl.fromTo("#masthead", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }}, 0.0);
      tl.fromTo("#accent-rule", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.45, ease: "power3.out" }}, 0.25);
      tl.fromTo("#headline", {{ opacity: 0, y: 28 }}, {{ opacity: 1, y: 0, duration: 0.60, ease: "power3.out" }}, 0.35);
      tl.fromTo("#footer-bar", {{ opacity: 0, y: 12 }}, {{ opacity: 1, y: 0, duration: 0.40, ease: "power2.out" }}, 0.65);
      tl.to("#progress-bar", {{ scaleX: 1, duration: {max(duracao_total - 0.5, 4.0)}, ease: "none" }}, 0.4);
      window.__timelines["editorial"] = tl;
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
            logging.info(f"⚡ Renderizando Reel editorial via HyperFrames ({duracao_total}s)...")
            res = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True, timeout=240)
            if res.returncode == 0 and os.path.exists(arquivo_saida_abs) and os.path.getsize(arquivo_saida_abs) > 50000:
                tamanho_kb = os.path.getsize(arquivo_saida_abs) // 1024
                logging.info(f"🎬 Reel Editorial HyperFrames gerado ({duracao_total}s, {tamanho_kb} KB): {arquivo_saida_abs}")
                return anexar_outro_gamestore(arquivo_saida_abs)
            err_tail = (res.stderr or res.stdout or "").strip()[-400:]
            logging.warning(f"HyperFrames editorial falhou ({res.returncode}: {err_tail}). Usando fallback Pillow+ffmpeg.")
        except Exception as exc:
            logging.warning(f"Exceção HyperFrames editorial (fallback Pillow+ffmpeg): {exc}")

    # Fallback Pillow + ffmpeg (Card 9:16 com Safe Zone Reels + áudio da Thalita)
    card_9x16 = gerar_card_editorial_rss(
        headline_card=headline_card,
        destaque_card=destaque_card,
        tag_categoria=tag_categoria,
        fonte=fonte,
        img_bytes=img_bytes,
        arquivo_saida=os.path.join(OUTPUT_DIR, "reel_editorial_card_fallback.jpg"),
        tamanho=(1080, 1920),
        modo="reel",
    )
    if not card_9x16:
        return None
    return gerar_video_reel_mp4(
        card_9x16,
        arquivo_saida=arquivo_saida_abs,
        duracao_segundos=int(math.ceil(duracao_total)),
        audio_path=voz_path,
        usar_broll=False,
        aplicar_outro=True,
    )
