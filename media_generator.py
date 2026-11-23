import logging
import os
import shutil
import subprocess
import textwrap
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

OUTPUT_DIR = "media_output"
WIDTH = 1080
HEIGHT = 1920


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


def gerar_video_reel_mp4(imagem_card_path, arquivo_saida=None, duracao_segundos=8):
    """
    Converte o card vertical 1080x1920 em um vídeo MP4 pronto para Reels/Shorts/TikTok
    usando ffmpeg (efeito de zoom suave + fade-in + faixa AAC silenciosa para 100% de compatibilidade Meta).
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

    fps = 30
    total_frames = duracao_segundos * fps
    # Zoom suave de 1.00x até ~1.08x centralizado + fade in de 0.4s
    vf = (
        f"scale=1080:1920,"
        f"zoompan=z='min(zoom+0.00035,1.08)':d={total_frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
        f"fade=t=in:st=0:d=0.4,format=yuv420p"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-loop", "1",
        "-i", imagem_card_path,
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf,
        "-t", str(duracao_segundos),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        arquivo_saida,
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if res.returncode == 0 and os.path.exists(arquivo_saida):
            tamanho_kb = os.path.getsize(arquivo_saida) // 1024
            logging.info(f"🎬 Vídeo Reel MP4 gerado ({tamanho_kb} KB): {arquivo_saida}")
            return arquivo_saida
        logging.error(f"ffmpeg falhou ao gerar Reel: {res.stderr[-400:]}")
    except Exception as e:
        logging.error(f"Exceção ao executar ffmpeg: {e}")

    return None
