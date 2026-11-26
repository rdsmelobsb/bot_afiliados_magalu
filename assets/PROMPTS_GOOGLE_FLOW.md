# 🎬 Guia de Ativos Google Flow (`assets/`) — Gamestore

Este diretório armazena os vídeos base gerados manualmente no **Google Flow** (custo **R\$ 0** de API) para dar acabamento cinematográfico aos Reels automáticos do **Alpha-Profit**.

---

## 📁 Onde Salvar os Arquivos

| Pasta | Arquivos Esperados | Padrão Técnico Recomendado |
| :--- | :--- | :--- |
| `assets/backgrounds/` | `bg_cyber_01.mp4`, `bg_cyber_02.mp4`, `bg_cyber_03.mp4` (quantos quiser) | Vertical **9:16** (`1080×1920`), **5–8s**, **30fps**, **< 8 MB** cada (pode ser sem áudio) |
| `assets/outros/` | `outro_gamestore.mp4` (prioritário, ou qualquer `.mp4`) | Vertical **9:16** (`1080×1920`), **~2s**, **30fps**, **< 5 MB**, Safe Zone base 28% livre |

> **Observação:** Se as pastas estiverem vazias (apenas `.gitkeep`), o `media_generator.py` mantém o funcionamento padrão em fundo *Obsidian Tech* sem gerar nenhum erro.

### Dica rápida de compressão (< 8 MB) caso o arquivo venha pesado do Flow
```bash
ffmpeg -y -i entrada.mp4 -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p" -c:v libx264 -crf 24 -preset slow -an -movflags +faststart bg_cyber_01.mp4
```

---

## 🎥 3 Prompts para B-Rolls de Fundo (9:16, 5–8s, Estética Cyber-Hardware)

Use estes prompts no **Google Flow** (formato **9:16 Portrait**) — todos mantêm o **centro escuro e com baixo ruído visual** para que o card do produto, selo de desconto 180d e preços tenham leitura absoluta após o scrim de 60%:

### 1. `bg_cyber_01.mp4` — Placa-Mãe & Circuitos Obsidian Neon
```text
Vertical 9:16 cinematic macro background loop of a dark matte black matte-carbon gaming motherboard and GPU heatsink inside an obsidian studio, subtle slow camera dolly forward, delicate glowing cyan (#00F0FF) and emerald green (#10B981) PCB circuit traces pulsing softly along the top and outer edges, deep dark shadow across the center area with low visual noise, shallow depth of field, moody studio rim lighting, clean high-contrast background for UI overlay, no text, no logos, seamless loop feel.
```

### 2. `bg_cyber_02.mp4` — Túnel Geométrico Gamer Minimalista
```text
Vertical 9:16 sleek dark futuristic cyber-tech studio background, minimal dark obsidian metallic architectural ribs receding slowly in perspective, faint cyan and emerald neon light strips framing only the left and right borders, center frame intentionally dark, matte, and clean with soft atmospheric mist, ultra smooth slow camera drift, zero clutter, no text, no people, designed for overlay typography.
```

### 3. `bg_cyber_03.mp4` — Setup Periféricos Bokeh Escuro
```text
Vertical 9:16 abstract out-of-focus dark gaming desk bokeh background at night, subtle blurred mechanical keyboard edges and soft cyan-to-emerald RGB ambient light gradient along the upper corners, smooth slow pan movement, clean deep-black center zone with minimal contrast distraction, ultra sharp 30fps, no text, no watermarks.
```

---

## ⚡ 1 Prompt para Vinheta Outro/CTA 2s (`Ingredients` com a Logo Gamestore)

No **Google Flow**, selecione o modo **Ingredients** (ou *Image-to-Video*), faça upload da **nova logo circular cyber-tech da Gamestore** como referência e gere um clipe curto (~2s, 9:16):

### `outro_gamestore.mp4` — Vinheta Outro Gamestore (Safe Zone Reels)
```text
Using the circular cyber-tech Gamestore logo from Ingredients as the exact centerpiece: vertical 9:16 dark obsidian background (#0A0B0E), fast 2-second high-impact reveal animation where glowing cyan and emerald neon circuit pulses converge around the circular logo positioned in the upper-middle third of the frame, clean crisp dark area below the logo, keeping the bottom 30 percent of the screen completely empty and uncluttered for Reels safe zone and overlaid CTA text, zero distortion on the logo text, sleek commercial motion graphics, no extra random words.
```

> O `media_generator.py` injeta automaticamente faixa de áudio silenciosa AAC `44100Hz` se o vídeo vier mudo do Flow, normaliza para `1080×1920 @ 30fps` e adiciona o CTA discreto **`SIGA @PROMOSGEEKTECH • LINK NA BIO`** acima dos últimos `540px` da tela (fora da área coberta pela UI do Facebook/Instagram Reels).
