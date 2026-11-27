import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import magalu_scrapper  # noqa: E402


class TestMLResiliencia(unittest.TestCase):
    def test_circuit_breaker_lista_aborta_na_primeira_e_segue_para_www(self):
        urls_chamadas = []

        def fake_extrator(url, categoria_padrao="Geral", retornar_diagnostico=True, exigir_nicho_forte=False):
            urls_chamadas.append(url)
            if "lista.mercadolivre.com.br" in url:
                return [], {"status_code": 200, "suspeita_waf": True, "indicio": "account-verification"}
            if "/social/" in url:
                if "page=2" in url:
                    return [], {"status_code": 200, "suspeita_waf": False}
                return [
                    {"sku": "ML_MLB1001", "nome_produto": "Headset Gamer Sem Fio", "loja": "Mercado Livre", "preco_atual": 250.0}
                ], {"status_code": 200, "suspeita_waf": False}
            if "/ofertas" in url:
                return [
                    {"sku": "ML_MLB2001", "nome_produto": "Monitor Gamer LG 24", "loja": "Mercado Livre", "preco_atual": 799.0}
                ], {"status_code": 200, "suspeita_waf": False}
            return [
                {"sku": f"ML_MLB_{categoria_padrao}", "nome_produto": f"Item {categoria_padrao}", "loja": "Mercado Livre", "preco_atual": 199.0}
            ], {"status_code": 200, "suspeita_waf": False}

        categorias_lista = [
            ("https://lista.mercadolivre.com.br/games", "Games"),
            ("https://lista.mercadolivre.com.br/ssd-nvme", "Informática"),
            ("https://lista.mercadolivre.com.br/mouse-gamer", "Informática"),
            ("https://lista.mercadolivre.com.br/celulares-telefones", "Celulares"),
            ("https://lista.mercadolivre.com.br/headset-gamer", "Games"),
        ]

        with self.assertLogs(level="WARNING") as cm:
            itens, stats = magalu_scrapper.coletar_catalogo_mercadolivre(
                rotas_www=magalu_scrapper.ROTAS_CATALOGO_ML_WWW,
                categorias_lista=categorias_lista,
                max_paginas_social=3,
                extrator_fn=fake_extrator,
                pausa_segundos=0,
            )

        self.assertTrue(stats["circuit_breaker_ativado"])
        self.assertEqual(stats["chamadas_lista"], 1)
        chamadas_lista_reais = [u for u in urls_chamadas if "lista.mercadolivre.com.br" in u]
        self.assertEqual(len(chamadas_lista_reais), 1)
        self.assertEqual(stats["social"], 1)
        self.assertEqual(stats["www_catalogo"], len(magalu_scrapper.ROTAS_CATALOGO_ML_WWW))
        self.assertEqual(len(itens), 1 + len(magalu_scrapper.ROTAS_CATALOGO_ML_WWW))
        self.assertEqual(sum(1 for msg in cm.output if "Circuit Breaker ML ativado" in msg), 1)

    def test_paginacao_vitrine_social_para_quando_repetida_ou_vazia(self):
        chamadas = []

        def fake_social(url, categoria_padrao="Geral", retornar_diagnostico=True, exigir_nicho_forte=False):
            chamadas.append(url)
            if "page=3" in url:
                # Página 3 repete item já visto na página 1 -> deve parar sem duplicar
                return [{"sku": "ML_MLB111", "nome_produto": "Controle Xbox", "loja": "Mercado Livre"}], {"suspeita_waf": False}
            if "page=2" in url:
                return [{"sku": "ML_MLB222", "nome_produto": "SSD NVMe 1TB", "loja": "Mercado Livre"}], {"suspeita_waf": False}
            return [{"sku": "ML_MLB111", "nome_produto": "Controle Xbox", "loja": "Mercado Livre"}], {"suspeita_waf": False}

        itens = magalu_scrapper.coletar_vitrine_social_ml(
            max_paginas=4,
            extrator_fn=fake_social,
            pausa_segundos=0,
        )
        self.assertEqual(len(chamadas), 3)
        self.assertIn("page=2", chamadas[1])
        self.assertIn("matt_tool=61727000", chamadas[1])
        self.assertIn("matt_word=rafaelmelo825", chamadas[1])
        self.assertEqual([x["sku"] for x in itens], ["ML_MLB111", "ML_MLB222"])

        # Página 2 vazia também encerra na página 2
        chamadas_vazia = []

        def fake_social_vazia(url, categoria_padrao="Geral", retornar_diagnostico=True, exigir_nicho_forte=False):
            chamadas_vazia.append(url)
            if "page=2" in url:
                return [], {"suspeita_waf": False}
            return [{"sku": "ML_MLB111", "nome_produto": "Controle Xbox", "loja": "Mercado Livre"}], {"suspeita_waf": False}

        itens_v = magalu_scrapper.coletar_vitrine_social_ml(max_paginas=3, extrator_fn=fake_social_vazia, pausa_segundos=0)
        self.assertEqual(len(chamadas_vazia), 2)
        self.assertEqual(len(itens_v), 1)

    def test_parser_ofertas_mais_vendidos_filtro_nicho_e_tags_afiliado(self):
        html_ofertas = """
        <html><body>
          <div class="promotion-item">
            <a href="/p/MLB12345678?foo=1#anchor" class="promotion-item__link">
              <img class="promotion-item__img" src="data:image/gif;base64,AAA" data-src="https://http2.mlstatic.com/D_NQ_NP_ssd.webp" />
              <p class="promotion-item__title">SSD Kingston NV2 1TB NVMe PCIe 4.0</p>
            </a>
            <s class="promotion-item__oldprice">R$ 599,90</s>
            <div class="promotion-item__price">
              <span class="andes-money-amount__fraction">389</span>
              <span class="andes-money-amount__cents">90</span>
            </div>
            <span class="promotion-item__discount">35% OFF</span>
          </div>
          <div class="promotion-item">
            <a href="https://www.mercadolivre.com.br/p/MLB99900011" class="promotion-item__link">
              <img data-src="https://http2.mlstatic.com/D_NQ_NP_fralda.webp" />
              <p class="promotion-item__title">Fralda Pampers Confort Sec XXG 100 Unidades</p>
            </a>
            <div class="promotion-item__price">
              <span class="andes-money-amount__fraction">129</span>
            </div>
          </div>
          <div class="promotion-item">
            <a href="https://produto.mercadolivre.com.br/MLB-555666777-lixeira" class="promotion-item__link">
              <p class="promotion-item__title">Lixeira Sensor Automatica Banheiro 12L</p>
            </a>
            <div class="promotion-item__price">
              <span class="andes-money-amount__fraction">99</span>
            </div>
          </div>
        </body></html>
        """

        html_mais_vendidos = """
        <html><body>
          <div class="poly-card">
            <img class="poly-component__picture" src="data:image/png;base64,BBB" data-src="https://http2.mlstatic.com/D_NQ_NP_dualsense.webp" />
            <a class="poly-component__title" href="https://www.mercadolivre.com.br/controle-dualsense/p/MLB22233344">Controle DualSense Sem Fio PS5 Branco</a>
            <s class="poly-price__previous">R$ 499,00</s>
            <div class="poly-price__current">
              <span class="andes-money-amount__fraction">379</span>
              <span class="andes-money-amount__cents">00</span>
            </div>
          </div>
        </body></html>
        """

        class FakeResp:
            def __init__(self, html_txt):
                self.status_code = 200
                self.text = html_txt

        def fake_get(url, headers=None, timeout=15):
            if "/ofertas" in url:
                return FakeResp(html_ofertas)
            return FakeResp(html_mais_vendidos)

        with patch.object(magalu_scrapper.requests, "get", side_effect=fake_get):
            res_of, diag_of = magalu_scrapper.extrair_dados_mercadolivre_live(
                "https://www.mercadolivre.com.br/ofertas",
                categoria_padrao="Ofertas do Dia",
                retornar_diagnostico=True,
                exigir_nicho_forte=True,
            )
            res_mv, diag_mv = magalu_scrapper.extrair_dados_mercadolivre_live(
                "https://www.mercadolivre.com.br/mais-vendidos/MLB1144",
                categoria_padrao="Games",
                retornar_diagnostico=True,
                exigir_nicho_forte=False,
            )

        itens_of = magalu_scrapper._converter_candidatas_para_lista(res_of)
        itens_mv = magalu_scrapper._converter_candidatas_para_lista(res_mv)

        self.assertFalse(diag_of["suspeita_waf"])
        self.assertFalse(diag_mv["suspeita_waf"])
        self.assertEqual(len(itens_of), 1)
        self.assertEqual(itens_of[0]["sku"], "ML_MLB12345678")
        self.assertEqual(itens_of[0]["preco_atual"], 389.90)
        self.assertEqual(itens_of[0]["preco_antigo"], 599.90)
        self.assertEqual(itens_of[0]["percentual_desconto"], 35.0)
        self.assertEqual(itens_of[0]["imagem_url"], "https://http2.mlstatic.com/D_NQ_NP_ssd.webp")
        self.assertIn("matt_tool=61727000", itens_of[0]["url_afiliado"])
        self.assertIn("matt_word=rafaelmelo825", itens_of[0]["url_afiliado"])
        self.assertTrue(itens_of[0]["url_afiliado"].startswith("https://www.mercadolivre.com.br/p/MLB12345678"))

        self.assertEqual(len(itens_mv), 1)
        self.assertEqual(itens_mv[0]["sku"], "ML_MLB22233344")
        self.assertEqual(itens_mv[0]["preco_atual"], 379.0)
        self.assertEqual(itens_mv[0]["preco_antigo"], 499.0)
        self.assertEqual(itens_mv[0]["imagem_url"], "https://http2.mlstatic.com/D_NQ_NP_dualsense.webp")
        self.assertIn("matt_tool=61727000", itens_mv[0]["url_afiliado"])
        self.assertIn("matt_word=rafaelmelo825", itens_mv[0]["url_afiliado"])


if __name__ == "__main__":
    unittest.main()
