import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    def test_filtro_janela_24h_e_coleta_com_fallback_feed(self):
        agora_utc = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>RTX 5060 aparece mais barata no varejo</title>
            <link>https://adrenaline.com.br/noticias/rtx-5060-preco</link>
            <description><![CDATA[<p>Modelo de entrada cai de preço nesta semana.</p>]]></description>
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
        self.assertEqual(noticias[0]["resumo"], "Modelo de entrada cai de preço nesta semana.")

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
            canais_postados="x,threads,facebook",
            publicado_em=(agora - timedelta(days=2)).isoformat(),
        )
        storage_db.registrar_pauta_rss(
            self.conn,
            url="https://tecnoblog.net/noticias/pauta-expirada-10-dias",
            fonte="Tecnoblog",
            titulo="Mouse gamer antigo volta ao estoque",
            canais_postados="x",
            publicado_em=(agora - timedelta(days=10)).isoformat(),
        )

        candidatos = [
            # Mesma URL -> bloqueada
            {
                "fonte": "Adrenaline",
                "titulo": "NVIDIA libera DLSS 4 para novos jogos de PC",
                "url": "https://www.adrenaline.com.br/noticias/nvidia-dlss-4-chega-jogos",
                "tema_normalizado": storage_db.normalizar_tema("NVIDIA libera DLSS 4 para novos jogos de PC"),
            },
            # Portal diferente, mesmo assunto nos últimos 7d -> bloqueada por similaridade
            {
                "fonte": "Tecnoblog",
                "titulo": "DLSS 4 da NVIDIA chega a novos jogos de PC nesta semana",
                "url": "https://tecnoblog.net/noticias/dlss-4-nvidia-novos-jogos",
                "tema_normalizado": storage_db.normalizar_tema("DLSS 4 da NVIDIA chega a novos jogos de PC nesta semana"),
            },
            # Tema de 10 dias atrás -> já expirou da janela de 7d -> elegível
            {
                "fonte": "Voxel",
                "titulo": "Mouse gamer antigo volta ao estoque",
                "url": "https://voxel.example.com/mouse-volta",
                "tema_normalizado": storage_db.normalizar_tema("Mouse gamer antigo volta ao estoque"),
            },
            # Inédita real -> elegível
            {
                "fonte": "Canaltech",
                "titulo": "SSD NVMe PCIe 4.0 fica mais barato com queda do dólar",
                "url": "https://canaltech.com.br/hardware/ssd-nvme-cai",
                "tema_normalizado": storage_db.normalizar_tema("SSD NVMe PCIe 4.0 fica mais barato com queda do dólar"),
            },
        ]

        restantes = rss_editorial.filtrar_pautas_ineditas(self.conn, candidatos, dias=7, agora=agora)
        urls_restantes = [x["url"] for x in restantes]
        self.assertEqual(
            urls_restantes,
            [
                "https://voxel.example.com/mouse-volta",
                "https://canaltech.com.br/hardware/ssd-nvme-cai",
            ],
        )

    def test_parser_editorial_zero_urls_no_x_e_match_condicional(self):
        candidatos = [
            {
                "fonte": "Canaltech",
                "titulo": "SSD NVMe 1TB entra na mira de quem quer acelerar o PC",
                "resumo": "Preços de SSDs seguem competitivos neste trimestre.",
                "url": "https://canaltech.com.br/ssd-nvme-1tb",
            }
        ]
        ofertas = [
            {
                "sku_selecionado": "ML_SSD_1TB",
                "nome_produto": "SSD Kingston NV2 1TB NVMe",
                "url_afiliado": "https://mercadolivre.com.br/ssd?matt_tool=61727000&matt_word=rafaelmelo825",
            }
        ]

        # Caso A: X vem contaminado com URL, t.me e domínio + falta "Via Canaltech" + match real de oferta
        raw_com_urls = json.dumps({
            "url_escolhida": "https://canaltech.com.br/ssd-nvme-1tb",
            "fonte": "Canaltech",
            "titulo_original": "SSD NVMe 1TB entra na mira de quem quer acelerar o PC",
            "tem_match_oferta": True,
            "sku_oferta_relacionada": "ML_SSD_1TB",
            "texto_x": "Vale trocar HD por SSD NVMe? Veja em https://canaltech.com.br/abc ou t.me/promosgeektech e canaltech.com.br! @promosgeektech",
            "texto_threads": "Ainda usando HD no PC em 2026? SSD NVMe 1TB muda seu setup. O que você usa aí?",
            "texto_facebook": "Ainda sofre com boot lento? Confira o link https://evil.com no post! Qual SSD você usa?",
            "texto_telegram": "Resumo SSD NVMe 1TB.",
        })
        pauta_a = rss_editorial.parsear_resposta_editorial(raw_com_urls, candidatos, ofertas_rodada=ofertas)
        self.assertIsNotNone(pauta_a)
        self.assertNotIn("http", pauta_a["texto_x"].lower())
        self.assertNotIn("t.me", pauta_a["texto_x"].lower())
        self.assertNotIn(".com", pauta_a["texto_x"].lower())
        self.assertNotIn("http", pauta_a["texto_facebook"].lower())
        self.assertIn("Via Canaltech", pauta_a["texto_threads"])
        self.assertIn("Via Canaltech", pauta_a["texto_facebook"])
        self.assertTrue(pauta_a["tem_match_oferta"])
        self.assertEqual(pauta_a["url_oferta_comentario"], ofertas[0]["url_afiliado"])

        # Caso B: tem_match_oferta=False ou SKU alucinado -> url_oferta_comentario precisa ser None
        raw_sem_match = json.dumps({
            "url_escolhida": "https://canaltech.com.br/ssd-nvme-1tb",
            "fonte": "Canaltech",
            "titulo_original": "SSD NVMe 1TB entra na mira de quem quer acelerar o PC",
            "tem_match_oferta": True,
            "sku_oferta_relacionada": "SKU_INEXISTENTE",
            "texto_x": "Qual upgrade deu mais diferença no seu setup?",
            "texto_threads": "Upgrade de SSD vale a pena. Via Canaltech",
            "texto_facebook": "Qual foi o melhor upgrade do seu PC? Via Canaltech",
            "texto_telegram": "Pauta pura Via Canaltech",
        })
        pauta_b = rss_editorial.parsear_resposta_editorial(raw_sem_match, candidatos, ofertas_rodada=ofertas)
        self.assertFalse(pauta_b["tem_match_oferta"])
        self.assertIsNone(pauta_b["url_oferta_comentario"])

    def test_isolamento_de_falhas_e_flag_telegram(self):
        agora_utc = datetime(2026, 11, 25, 18, 0, 0, tzinfo=timezone.utc)  # 15h BRT

        # 1. Falha no RSS/IA não propaga exceção
        def fetcher_explode(url, timeout=10):
            raise RuntimeError("boom rede")

        res_err = rss_editorial.executar_bloco_editorial(
            conn=self.conn,
            oportunidades_dict={"oportunidades": []},
            forcar_execucao=False,
            agora=agora_utc,
            fetcher=fetcher_explode,
        )
        self.assertFalse(res_err["executado"])

        # 2. Fluxo completo com EDITORIAL_TELEGRAM_ENABLED=false não posta no Telegram e grava no SQLite
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>PlayStation lança atualização focada em bateria do DualSense</title>
          <link>https://www.adrenaline.com.br/games/dualsense-bateria-update</link>
          <description>Atualização melhora gerenciamento de energia do controle.</description>
          <pubDate>{(agora_utc - timedelta(hours=2)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        </item></channel></rss>"""

        chamadas = {"x": 0, "threads": 0, "facebook": 0, "telegram": 0}

        def fake_ia(cands, ofertas):
            return json.dumps({
                "url_escolhida": cands[0]["url"],
                "fonte": "Adrenaline",
                "titulo_original": cands[0]["titulo"],
                "tem_match_oferta": False,
                "sku_oferta_relacionada": "",
                "texto_x": "DualSense ganhou update focado em bateria! Quanto tempo dura o seu controle?",
                "texto_threads": "Update do DualSense foca em autonomia de bateria. Via Adrenaline. Você joga no cabo ou sem fio?",
                "texto_facebook": "Bateria do controle faz diferença na jogatina! Via Adrenaline. Quantas horas dura o seu?",
                "texto_telegram": "Update DualSense Via Adrenaline",
            })

        pubs = {
            "x": lambda txt: chamadas.__setitem__("x", chamadas["x"] + 1) or True,
            "threads": lambda txt: chamadas.__setitem__("threads", chamadas["threads"] + 1) or True,
            "facebook": lambda txt, url_oferta_comentario=None: chamadas.__setitem__("facebook", chamadas["facebook"] + 1) or True,
            "telegram": lambda txt, url_oferta=None: chamadas.__setitem__("telegram", chamadas["telegram"] + 1) or True,
        }

        with patch.dict(
            os.environ,
            {"EDITORIAL_ENABLED": "true", "EDITORIAL_TELEGRAM_ENABLED": "false"},
            clear=False,
        ):
            res_ok = rss_editorial.executar_bloco_editorial(
                conn=self.conn,
                oportunidades_dict={"oportunidades": []},
                forcar_execucao=False,
                agora=agora_utc,
                fetcher=lambda u, timeout=10: xml_ok.encode("utf-8"),
                gerador_ia=fake_ia,
                publicadores=pubs,
            )

        self.assertTrue(res_ok["executado"])
        self.assertEqual(chamadas, {"x": 1, "threads": 1, "facebook": 1, "telegram": 0})
        self.assertEqual(res_ok["canais"], ["x", "threads", "facebook"])
        self.assertTrue(
            storage_db.pauta_ja_publicada(self.conn, "https://www.adrenaline.com.br/games/dualsense-bateria-update")
        )
        # Reexecução no mesmo dia BRT sem --run-editorial não duplica
        res_dup = rss_editorial.executar_bloco_editorial(
            conn=self.conn,
            oportunidades_dict={"oportunidades": []},
            forcar_execucao=False,
            agora=agora_utc,
        )
        self.assertEqual(res_dup["motivo"], "ja_publicado_hoje")

    def test_execucao_editorial_pura_com_zero_ofertas_falha_scraping(self):
        agora_utc = datetime(2026, 11, 25, 22, 30, 0, tzinfo=timezone.utc)  # Fora das 15h BRT, usa forcar_execucao=True
        xml_ok = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>AMD anuncia corte de preço em processadores Ryzen AM5</title>
          <link>https://tecnoblog.net/noticias/amd-corte-ryzen-am5</link>
          <description>Redução busca aquecer upgrades de setup nesta temporada.</description>
          <pubDate>{(agora_utc - timedelta(hours=1)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        </item></channel></rss>"""

        fb_captura = {}

        def fake_ia(cands, ofertas):
            self.assertEqual(ofertas, [])
            return json.dumps({
                "url_escolhida": cands[0]["url"],
                "fonte": "Tecnoblog",
                "titulo_original": cands[0]["titulo"],
                "tem_match_oferta": True,
                "sku_oferta_relacionada": "ML_RYZEN_FAKE",
                "texto_x": "Processadores AM5 ficando mais acessíveis! Vai fazer upgrade?",
                "texto_threads": "Corte nos Ryzen AM5 muda a conta do upgrade. Via Tecnoblog. Vale esperar?",
                "texto_facebook": "AM5 ficando competitivo frente ao AM4! Via Tecnoblog. Qual plataforma você escolheria hoje?",
                "texto_telegram": "Ryzen AM5 Via Tecnoblog",
            })

        def fake_fb(txt, url_oferta_comentario=None):
            fb_captura["txt"] = txt
            fb_captura["url_comentario"] = url_oferta_comentario
            return True

        res = rss_editorial.executar_bloco_editorial(
            conn=self.conn,
            ofertas_selecionadas=[],
            forcar_execucao=True,
            agora=agora_utc,
            fetcher=lambda u, timeout=10: xml_ok.encode("utf-8"),
            gerador_ia=fake_ia,
            publicadores={
                "x": lambda txt: True,
                "threads": lambda txt: True,
                "facebook": fake_fb,
            },
        )
        self.assertTrue(res["executado"])
        self.assertFalse(res["tem_match_oferta"])
        self.assertIsNone(fb_captura["url_comentario"])
        self.assertEqual(res["canais"], ["x", "threads", "facebook"])

    def test_diagnostico_bloqueio_waf_http(self):
        import magalu_scrapper

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


if __name__ == "__main__":
    unittest.main()
