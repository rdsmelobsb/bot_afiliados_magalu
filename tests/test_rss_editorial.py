from io import BytesIO
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import magalu_scrapper  # noqa: E402
import media_generator  # noqa: E402
import rss_editorial  # noqa: E402
import storage_db  # noqa: E402


class TestRSSEditorial(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "editorial_test.db")
        self.conn = storage_db.conectar_db(self.db_path)
        storage_db.inicializar_db(self.conn)

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.tmp_dir.cleanup()

    def _criar_jpeg_memoria(self, cor=(30, 110, 220), size=(640, 360)):
        im = Image.new("RGB", size, cor)
        buf = BytesIO()
        im.save(buf, format="JPEG")
        return buf.getvalue()

    def test_x_e_threads_rigorosamente_desativados_por_padrao(self):
        ops_dummy = {
            "oportunidades": [
                {
                    "sku_selecionado": "ML_TEST1",
                    "nome_produto": "Mouse Gamer",
                    "loja": "Mercado Livre",
                    "preco_atual": 120.0,
                    "percentual_desconto": 20.0,
                    "lucro_estimado_reais": 8.0,
                    "url_afiliado": "https://mercadolivre.com.br/p/MLB1",
                }
            ]
        }
        creds = {
            "X_API_KEY": "fake_key",
            "X_API_SECRET": "fake_sec",
            "X_ACCESS_TOKEN": "fake_tok",
            "X_ACCESS_TOKEN_SECRET": "fake_tok_sec",
            "THREADS_ACCESS_TOKEN": "fake_threads",
            "X_ENABLED": "false",
            "THREADS_ENABLED": "false",
        }
        with patch.dict(os.environ, creds, clear=False):
            with patch.object(magalu_scrapper.requests, "get", side_effect=AssertionError("Não deveria chamar HTTP")):
                self.assertEqual(magalu_scrapper.disparar_x_twitter(ops_dummy), 0)
                self.assertEqual(magalu_scrapper.disparar_threads(ops_dummy), 0)
                self.assertFalse(rss_editorial.publicar_editorial_x("Texto teste"))
                self.assertFalse(rss_editorial.publicar_editorial_threads("Texto teste"))

    def test_filtro_janela_24h_e_coleta_com_fallback_feed(self):
        agora_utc = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
          <item>
            <title>RTX 5060 aparece mais barata no varejo</title>
            <link>https://adrenaline.com.br/noticias/rtx-5060-preco</link>
            <description><![CDATA[<p>Modelo de entrada cai de preço nesta semana.</p>]]></description>
            <media:content url="https://adrenaline.com.br/img/rtx5060.jpg" medium="image" />
            <pubDate>{(agora_utc - timedelta(hours=3)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
          </item>
          <item>
            <title>Notícia antiga de 3 dias atrás</title>
            <link>https://adrenaline.com.br/noticias/antiga</link>
            <description>Antiga</description>
            <pubDate>{(agora_utc - timedelta(hours=72)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
          </item>
        </channel></rss>"""

        def fake_fetcher(url, timeout=10):
            if "falha" in url:
                raise TimeoutError("feed fora do ar")
            return xml_ok.encode("utf-8")

        feeds = [
            ("PortalQueFalhou", "https://falha.example.com/rss"),
            ("Adrenaline", "https://adrenaline.com.br/feed/"),
        ]
        noticias = rss_editorial.coletar_noticias_rss(
            feeds=feeds, horas=24, agora_utc=agora_utc, fetcher=fake_fetcher
        )
        self.assertEqual(len(noticias), 1)
        self.assertEqual(noticias[0]["fonte"], "Adrenaline")
        self.assertEqual(noticias[0]["imagem_url"], "https://adrenaline.com.br/img/rtx5060.jpg")
        self.assertEqual(noticias[0]["resumo"], "Modelo de entrada cai de preço nesta semana.")

    def test_extrair_og_image_e_gerar_card_4x5_com_e_sem_foto(self):
        # 1. Extração via og:image quando RSS vem sem foto
        class FakeResp:
            status_code = 200
            text = '<html><head><meta property="og:image" content="https://cdn.site.com/foto-noticia.jpg" /></head></html>'

        with patch.object(rss_editorial.requests, "get", return_value=FakeResp()):
            og_url = rss_editorial.extrair_og_image_pagina("https://site.com/materia")
        self.assertEqual(og_url, "https://cdn.site.com/foto-noticia.jpg")

        # 2. Geração de Card 4:5 (1080x1350) com foto real
        card_com_foto = os.path.join(self.tmp_dir.name, "card_foto.jpg")
        out_1 = media_generator.gerar_card_editorial_rss(
            headline_card="Intel ARC B580 pressiona placas de entrada no Brasil",
            destaque_card="Intel ARC",
            tag_categoria="HARDWARE",
            fonte="Adrenaline",
            img_bytes=self._criar_jpeg_memoria(),
            arquivo_saida=card_com_foto,
        )
        self.assertEqual(out_1, card_com_foto)
        with Image.open(card_com_foto) as im1:
            self.assertEqual(im1.size, (1080, 1350))

        # 3. Geração de Card 4:5 sem foto (fallback dark estilizado, nunca texto puro)
        card_sem_foto = os.path.join(self.tmp_dir.name, "card_dark.jpg")
        out_2 = media_generator.gerar_card_editorial_rss(
            headline_card="PS5 recebe melhoria de autonomia para o DualSense",
            destaque_card="PS5 DualSense",
            tag_categoria="GAMES",
            fonte="Voxel",
            img_bytes=None,
            arquivo_saida=card_sem_foto,
        )
        self.assertEqual(out_2, card_sem_foto)
        with Image.open(card_sem_foto) as im2:
            self.assertEqual(im2.size, (1080, 1350))

    def test_limite_30_candidatos_balanceados_entre_feeds(self):
        candidatos = []
        for idx, fonte in enumerate(("Adrenaline", "Tecnoblog", "Canaltech", "Voxel")):
            for n in range(15):  # 60 candidatos totais
                candidatos.append({
                    "fonte": fonte,
                    "titulo": f"{fonte} noticia {n}",
                    "url": f"https://{fonte.lower()}.test/{n}",
                    "publicado_em": f"2026-11-25T{23 - n:02d}:0{idx}:00+00:00",
                })
        sel = rss_editorial.selecionar_candidatos_balanceados(candidatos, limite=30)
        self.assertEqual(len(sel), 30)
        por_fonte = {}
        for s in sel:
            por_fonte[s["fonte"]] = por_fonte.get(s["fonte"], 0) + 1
        # 30 dividido entre 4 fontes -> 8, 8, 7, 7
        self.assertEqual(sorted(por_fonte.values()), [7, 7, 8, 8])

    def test_janela_15h_brt_flag_cli_e_feature_flag(self):
        tz_brt = timezone(timedelta(hours=-3))
        dt_10h = datetime(2026, 11, 25, 10, 0, tzinfo=tz_brt)
        dt_15h = datetime(2026, 11, 25, 15, 5, tzinfo=tz_brt)
        dt_20h = datetime(2026, 11, 25, 20, 0, tzinfo=tz_brt)

        with patch.dict(os.environ, {"EDITORIAL_ENABLED": "true"}, clear=False):
            self.assertEqual(rss_editorial.deve_executar_editorial(False, dt_10h)[0], False)
            self.assertEqual(rss_editorial.deve_executar_editorial(False, dt_15h), (True, "janela_15h_brt"))
            self.assertEqual(rss_editorial.deve_executar_editorial(False, dt_20h)[0], False)
            self.assertEqual(rss_editorial.deve_executar_editorial(True, dt_20h), (True, "flag_cli_run_editorial"))

        with patch.dict(os.environ, {"EDITORIAL_ENABLED": "false"}, clear=False):
            self.assertEqual(rss_editorial.deve_executar_editorial(True, dt_15h), (False, "editorial_desabilitado_env"))

    def test_deduplicacao_7_dias_url_e_tema_portais_diferentes(self):
        agora = datetime(2026, 11, 25, 15, 0)
        storage_db.registrar_pauta_rss(
            self.conn,
            url="https://www.adrenaline.com.br/noticias/nvidia-dlss-4-chega-jogos",
            fonte="Adrenaline",
            titulo="NVIDIA libera DLSS 4 para novos jogos de PC",
            canais_postados="facebook,telegram",
            publicado_em=(agora - timedelta(days=2)).isoformat(),
        )
        storage_db.registrar_pauta_rss(
            self.conn,
            url="https://tecnoblog.net/noticias/pauta-expirada-10-dias",
            fonte="Tecnoblog",
            titulo="Mouse gamer antigo volta ao estoque",
            canais_postados="facebook",
            publicado_em=(agora - timedelta(days=10)).isoformat(),
        )

        candidatos = [
            {
                "fonte": "Adrenaline",
                "titulo": "NVIDIA libera DLSS 4 para novos jogos de PC",
                "url": "https://www.adrenaline.com.br/noticias/nvidia-dlss-4-chega-jogos",
                "tema_normalizado": storage_db.normalizar_tema("NVIDIA libera DLSS 4 para novos jogos de PC"),
            },
            {
                "fonte": "Tecnoblog",
                "titulo": "DLSS 4 da NVIDIA chega a novos jogos de PC nesta semana",
                "url": "https://tecnoblog.net/noticias/dlss-4-nvidia-novos-jogos",
                "tema_normalizado": storage_db.normalizar_tema("DLSS 4 da NVIDIA chega a novos jogos de PC nesta semana"),
            },
            {
                "fonte": "Voxel",
                "titulo": "Mouse gamer antigo volta ao estoque",
                "url": "https://voxel.example.com/mouse-volta",
                "tema_normalizado": storage_db.normalizar_tema("Mouse gamer antigo volta ao estoque"),
            },
            {
                "fonte": "Canaltech",
                "titulo": "SSD NVMe PCIe 4.0 fica mais barato com queda do dólar",
                "url": "https://canaltech.com.br/hardware/ssd-nvme-cai",
                "tema_normalizado": storage_db.normalizar_tema("SSD NVMe PCIe 4.0 fica mais barato com queda do dólar"),
            },
        ]

        restantes = rss_editorial.filtrar_pautas_ineditas(self.conn, candidatos, dias=7, agora=agora)
        self.assertEqual(
            [x["url"] for x in restantes],
            [
                "https://voxel.example.com/mouse-volta",
                "https://canaltech.com.br/hardware/ssd-nvme-cai",
            ],
        )

    def test_schema_editorial_humanizer_e_match_condicional(self):
        # Valida bans do humanizer presentes no system prompt
        for termo_banido in ("Pensando em", "Você sabia", "amadurecimento", "segmento mainstream", "Deixe sua opinião nos comentários"):
            self.assertIn(termo_banido, rss_editorial.EDITORIAL_SYSTEM_PROMPT)

        candidatos = [
            {
                "fonte": "Canaltech",
                "titulo": "SSD NVMe 1TB entra na mira de quem quer acelerar o PC",
                "resumo": "Preços de SSDs seguem competitivos neste trimestre.",
                "url": "https://canaltech.com.br/ssd-nvme-1tb",
                "imagem_url": "https://canaltech.com.br/img/ssd.jpg",
            }
        ]
        ofertas = [
            {
                "sku_selecionado": "ML_SSD_1TB",
                "nome_produto": "SSD Kingston NV2 1TB NVMe",
                "url_afiliado": "https://mercadolivre.com.br/ssd?matt_tool=61727000&matt_word=rafaelmelo825",
            }
        ]

        raw_ok = json.dumps({
            "url_escolhida": "https://canaltech.com.br/ssd-nvme-1tb",
            "fonte": "Canaltech",
            "titulo_original": "SSD NVMe 1TB entra na mira de quem quer acelerar o PC",
            "tag_categoria": "hardware",
            "headline_card": "SSD NVMe 1TB derruba custo de upgrade no PC gamer com folga extra",
            "destaque_card": "SSD NVMe",
            "roteiro_reel": "Se o seu computador ainda sofre com tela travando na inicializacao, o SSD NVMe virou o upgrade mais barato pra ganhar folego sem trocar placa-mae.",
            "tem_match_oferta": True,
            "sku_oferta_relacionada": "ML_SSD_1TB",
            "texto_facebook": "SSD NVMe de 1TB está custando quase o mesmo que modelos básicos de entrada.\n\nTrocar um HD ou SATA antigo aqui corta o carregamento de jogos pela metade.\n\nVocê vai de 1TB logo de cara ou prefere economizar pegando 500GB?\n\nConfira https://evil.com",
            "texto_telegram": "SSD NVMe de 1TB caiu de preço e virou o melhor custo-benefício pra dar gás no PC sem gastar em GPU.\n\nVocê já aposentou o HD de vez ou ainda usa como secundário?",
        })

        pauta = rss_editorial.parsear_resposta_editorial(raw_ok, candidatos, ofertas_rodada=ofertas)
        self.assertIsNotNone(pauta)
        self.assertLessEqual(len(pauta["headline_card"].split()), 9)
        self.assertEqual(pauta["tag_categoria"], "HARDWARE")
        self.assertEqual(pauta["destaque_card"], "SSD NVMe")
        self.assertIn("SSD NVMe", pauta["roteiro_reel"])
        self.assertNotIn("http", pauta["texto_facebook"].lower())
        self.assertIn("📰 Fonte: Canaltech", pauta["texto_facebook"])
        self.assertIn("📰 Fonte: Canaltech", pauta["texto_telegram"])
        self.assertTrue(pauta["tem_match_oferta"])
        self.assertEqual(pauta["url_oferta_comentario"], ofertas[0]["url_afiliado"])

    def test_isolamento_de_falhas_reel_e_canais_fb_tg(self):
        agora_utc = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)  # 15h BRT

        # 1. Falha no RSS não propaga
        res_err = rss_editorial.executar_bloco_editorial(
            conn=self.conn,
            ofertas_selecionadas=[],
            forcar_execucao=False,
            agora=agora_utc,
            fetcher=lambda u, timeout=10: (_ for _ in ()).throw(RuntimeError("boom rede")),
        )
        self.assertFalse(res_err["executado"])

        # 2. Fluxo completo com erro simulado no Reel: Card 4:5 ainda publica em FB + TG e X/Threads ficam desligados
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>PlayStation lança atualização focada em bateria do DualSense</title>
          <link>https://www.adrenaline.com.br/games/dualsense-bateria-update</link>
          <description>Atualização melhora gerenciamento de energia do controle.</description>
          <pubDate>{(agora_utc - timedelta(hours=2)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        </item></channel></rss>"""

        chamadas = {"facebook": 0, "telegram": 0, "x": 0, "threads": 0}
        card_tmp = os.path.join(self.tmp_dir.name, "card_editorial_test.jpg")

        def fake_ia(cands, ofertas):
            return json.dumps({
                "url_escolhida": cands[0]["url"],
                "fonte": "Adrenaline",
                "titulo_original": cands[0]["titulo"],
                "tag_categoria": "GAMES",
                "headline_card": "Update do DualSense melhora bateria no PS5",
                "destaque_card": "DualSense",
                "roteiro_reel": "A Sony soltou atualização nova pro DualSense focada em segurar mais horas fora do cabo.",
                "tem_match_oferta": False,
                "sku_oferta_relacionada": "",
                "texto_facebook": "A Sony liberou update para melhorar o gasto de bateria do DualSense.\n\nQuem joga sessões longas sem fio costuma sofrer bastante com a carga.\n\nVocê joga no cabo ou prefere manter dois controles carregados?",
                "texto_telegram": "Sony soltou atualização focada em autonomia para o DualSense.\n\nQuantas horas o seu controle aguenta antes de pedir cabo?",
            })

        pubs = {
            "facebook": lambda txt, card_path=None, url_oferta_comentario=None: (
                chamadas.__setitem__("facebook", chamadas["facebook"] + 1) or bool(card_path and os.path.exists(card_path))
            ),
            "telegram": lambda txt, card_path=None, url_oferta=None: (
                chamadas.__setitem__("telegram", chamadas["telegram"] + 1) or bool(card_path and os.path.exists(card_path))
            ),
            "x": lambda txt: chamadas.__setitem__("x", chamadas["x"] + 1) or True,
            "threads": lambda txt: chamadas.__setitem__("threads", chamadas["threads"] + 1) or True,
            "gerar_reel": lambda pauta, img: (_ for _ in ()).throw(RuntimeError("falha simulada no HyperFrames")),
        }

        with patch.dict(
            os.environ,
            {
                "EDITORIAL_ENABLED": "true",
                "EDITORIAL_TELEGRAM_ENABLED": "true",
                "EDITORIAL_REEL_ENABLED": "true",
                "X_ENABLED": "false",
                "THREADS_ENABLED": "false",
            },
            clear=False,
        ):
            with patch.object(media_generator, "OUTPUT_DIR", self.tmp_dir.name):
                res_ok = rss_editorial.executar_bloco_editorial(
                    conn=self.conn,
                    ofertas_selecionadas=[],
                    forcar_execucao=False,
                    agora=agora_utc,
                    fetcher=lambda u, timeout=10: xml_ok.encode("utf-8"),
                    gerador_ia=fake_ia,
                    publicadores=pubs,
                )

        self.assertTrue(res_ok["executado"])
        self.assertIsNotNone(res_ok["card_path"])
        self.assertTrue(os.path.exists(res_ok["card_path"]))
        self.assertEqual(chamadas, {"facebook": 1, "telegram": 1, "x": 0, "threads": 0})
        self.assertEqual(res_ok["canais"], ["facebook", "telegram"])
        self.assertTrue(
            storage_db.pauta_ja_publicada(self.conn, "https://www.adrenaline.com.br/games/dualsense-bateria-update")
        )

    def test_diagnostico_bloqueio_waf_http(self):
        with self.assertLogs(level="ERROR") as cm:
            diag_waf = magalu_scrapper._diagnosticar_bloqueio_http(
                "Mercado Livre",
                "https://lista.mercadolivre.com.br/games",
                403,
                "<html><title>Access Denied</title><body>Please solve captcha</body></html>",
                motivo_extra="http_nao_200",
            )
        self.assertTrue(diag_waf["suspeita_waf"])
        self.assertEqual(diag_waf["status_code"], 403)
        self.assertIn("status_code=403", cm.output[0])

        with self.assertLogs(level="WARNING"):
            diag_ok = magalu_scrapper._diagnosticar_bloqueio_http(
                "Magalu",
                "https://www.magazinevoce.com.br/magazinedealz/games/l/ga/?page=5",
                200,
                "<html><title>Magalu Games</title><body>Sem mais itens</body></html>",
                motivo_extra="sem_next_data",
            )
        self.assertFalse(diag_ok["suspeita_waf"])

    def test_selecao_por_noticia_id_e_unwrap_lista_com_fences(self):
        candidatos = [
            {
                "id": 1,
                "fonte": "Adrenaline",
                "titulo": "Primeira noticia de teste",
                "url": "https://adrenaline.com.br/noticia-1",
                "imagem_url": "https://adrenaline.com.br/img-1.jpg",
            },
            {
                "id": 2,
                "fonte": "Tecnoblog",
                "titulo": "Ryzen 7 9800X3D recebe ajuste oficial de preco no Brasil",
                "url": "https://tecnoblog.net/noticias/ryzen-9800x3d-preco/",
                "imagem_url": "https://tecnoblog.net/img/ryzen.jpg",
            },
        ]
        # Sem url_escolhida, embrulhado em markdown fence + array JSON de 1 elemento
        raw = (
            "```json\n"
            + json.dumps([
                {
                    "noticia_id": "2",
                    "tag_categoria": "hardware",
                    "headline_card": "Ryzen 7 9800X3D fica mais competitivo no Brasil",
                    "destaque_card": "9800X3D",
                    "roteiro_reel": "O Ryzen 9800X3D ganhou novo ajuste de preço nas lojas brasileiras nesta semana.",
                    "texto_facebook": "O Ryzen 7 9800X3D começou a aparecer com preço ajustado no varejo.\n\nPara quem monta PC focado em alto FPS, o chip continua referência.\n\nVocê esperaria mais ou já fecharia upgrade agora?",
                }
            ])
            + "\n```"
        )
        pauta = rss_editorial.parsear_resposta_editorial(raw, candidatos)
        self.assertIsNotNone(pauta)
        self.assertEqual(pauta["noticia_id"], 2)
        self.assertEqual(pauta["url_escolhida"], "https://tecnoblog.net/noticias/ryzen-9800x3d-preco/")
        self.assertEqual(pauta["fonte"], "Tecnoblog")
        self.assertEqual(pauta["imagem_url"], "https://tecnoblog.net/img/ryzen.jpg")
        self.assertIn("📰 Fonte: Tecnoblog", pauta["texto_telegram"])

    def test_fallbacks_por_campo_sem_descartar_pauta_e_pula_so_reel(self):
        agora_utc = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Controle Xbox ganha nova edicao especial com gatilhos texturizados no Brasil</title>
          <link>https://www.adrenaline.com.br/games/controle-xbox-edicao-especial</link>
          <description>Novo modelo chega às lojas neste mês.</description>
          <pubDate>{(agora_utc - timedelta(hours=1)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        </item></channel></rss>"""

        # JSON sem texto_telegram, sem headline_card, com destaque_card incompatível e sem roteiro_reel
        def fake_ia(cands, ofertas):
            return json.dumps({
                "noticia_id": cands[0]["id"],
                "destaque_card": "PalavraInexistenteNaManchete",
                "texto_facebook": "A Microsoft colocou nas lojas uma nova edição especial do controle de Xbox.\n\nOs gatilhos texturizados ajudam bastante em jogos de corrida e FPS.\n\nVocê prefere controle padrão ou edição especial?",
            })

        chamadas = {"facebook": 0, "telegram": 0, "gerar_reel": 0, "facebook_reel": 0}
        pubs = {
            "facebook": lambda txt, card_path=None, url_oferta_comentario=None: (
                chamadas.__setitem__("facebook", chamadas["facebook"] + 1)
                or bool(card_path and os.path.exists(card_path) and "📰 Fonte: Adrenaline" in txt)
            ),
            "telegram": lambda txt, card_path=None, url_oferta=None: (
                chamadas.__setitem__("telegram", chamadas["telegram"] + 1)
                or bool(card_path and os.path.exists(card_path) and "Microsoft colocou nas lojas" in txt)
            ),
            "gerar_reel": lambda pauta, img: chamadas.__setitem__("gerar_reel", chamadas["gerar_reel"] + 1) or None,
            "facebook_reel": lambda *a, **kw: chamadas.__setitem__("facebook_reel", chamadas["facebook_reel"] + 1) or True,
        }

        with patch.dict(
            os.environ,
            {
                "EDITORIAL_ENABLED": "true",
                "EDITORIAL_TELEGRAM_ENABLED": "true",
                "EDITORIAL_REEL_ENABLED": "true",
                "X_ENABLED": "false",
                "THREADS_ENABLED": "false",
            },
            clear=False,
        ):
            with patch.object(media_generator, "OUTPUT_DIR", self.tmp_dir.name):
                res = rss_editorial.executar_bloco_editorial(
                    conn=self.conn,
                    ofertas_selecionadas=[],
                    forcar_execucao=False,
                    agora=agora_utc,
                    fetcher=lambda u, timeout=10: xml_ok.encode("utf-8"),
                    gerador_ia=fake_ia,
                    publicadores=pubs,
                )

        self.assertTrue(res["executado"])
        self.assertLessEqual(len(res["headline_card"].split()), 9)
        self.assertEqual(chamadas, {"facebook": 1, "telegram": 1, "gerar_reel": 0, "facebook_reel": 0})
        self.assertEqual(res["canais"], ["facebook", "telegram"])

    def test_retry_automatico_json_malformado_recupera_na_segunda_tentativa(self):
        agora_utc = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Monitor OLED 240Hz cai de preco em promocao relampago</title>
          <link>https://tecnoblog.net/noticias/monitor-oled-240hz-cai</link>
          <description>Painéis OLED começam a ficar mais acessíveis.</description>
          <pubDate>{(agora_utc - timedelta(hours=2)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        </item></channel></rss>"""

        tentativas = {"n": 0}

        def fake_ia_retry(cands, ofertas):
            tentativas["n"] += 1
            if tentativas["n"] == 1:
                return ('{"noticia_id": 1, "texto_facebook": "cortado...', "STOP")
            return (
                json.dumps({
                    "noticia_id": cands[0]["id"],
                    "tag_categoria": "HARDWARE",
                    "headline_card": "Monitor OLED 240Hz fica mais barato",
                    "destaque_card": "OLED 240Hz",
                    "roteiro_reel": "",
                    "texto_facebook": "Painel OLED de 240Hz caiu de preço nesta semana e acirrou a briga com IPS rápido.\n\nQuem joga competitivo sente na hora o tempo de resposta quase instantâneo.\n\nVocê encara OLED no desktop ou prefere IPS sem medo de burn-in?",
                }),
                "STOP",
            )

        pubs = {
            "facebook": lambda txt, card_path=None, url_oferta_comentario=None: True,
            "telegram": lambda txt, card_path=None, url_oferta=None: True,
        }
        with patch.dict(
            os.environ,
            {
                "EDITORIAL_ENABLED": "true",
                "EDITORIAL_TELEGRAM_ENABLED": "true",
                "EDITORIAL_REEL_ENABLED": "false",
            },
            clear=False,
        ):
            with patch.object(media_generator, "OUTPUT_DIR", self.tmp_dir.name):
                res = rss_editorial.executar_bloco_editorial(
                    conn=self.conn,
                    ofertas_selecionadas=[],
                    forcar_execucao=False,
                    agora=agora_utc,
                    fetcher=lambda u, timeout=10: xml_ok.encode("utf-8"),
                    gerador_ia=fake_ia_retry,
                    publicadores=pubs,
                )

        self.assertEqual(tentativas["n"], 2)
        self.assertTrue(res["executado"])
        self.assertEqual(res["canais"], ["facebook", "telegram"])

    def test_logs_diagnosticos_parser_e_extracao_finish_reason(self):
        class FakePart:
            def __init__(self, text):
                self.text = text

        class FakeContent:
            def __init__(self, parts):
                self.parts = parts

        class FakeCand:
            def __init__(self, finish_reason, parts):
                self.finish_reason = finish_reason
                self.content = FakeContent(parts)

        class FakeResp:
            def __init__(self):
                self.candidates = [FakeCand("MAX_TOKENS", [FakePart('{"noticia_id": 1'), FakePart(', "x": 2')])]

        txt, fr = rss_editorial._extrair_texto_resposta_gemini_editorial(FakeResp())
        self.assertEqual(fr, "MAX_TOKENS")
        self.assertEqual(txt, '{"noticia_id": 1, "x": 2')

        candidatos = [{"id": 1, "fonte": "Voxel", "titulo": "Noticia 1", "url": "https://voxel.test/1"}]

        with self.assertLogs(level="WARNING") as cm_json:
            res_json = rss_editorial.parsear_resposta_editorial(
                '{"noticia_id": 1, "texto_facebook": "incompleto...',
                candidatos,
                finish_reason="MAX_TOKENS",
            )
        self.assertIsNone(res_json)
        self.assertIn("json_invalido", cm_json.output[0])
        self.assertIn("finish_reason=MAX_TOKENS", cm_json.output[0])
        self.assertIn("inicio=", cm_json.output[0])
        self.assertIn("fim=", cm_json.output[0])

        with self.assertLogs(level="WARNING") as cm_id:
            res_id = rss_editorial.parsear_resposta_editorial(
                json.dumps({"noticia_id": 99, "texto_facebook": "Texto qualquer"}),
                candidatos,
                finish_reason="STOP",
            )
        self.assertIsNone(res_id)
        self.assertIn("noticia_nao_encontrada", cm_id.output[0])
        self.assertIn("noticia_id=99", cm_id.output[0])


if __name__ == "__main__":
    unittest.main()
