import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import magalu_scrapper  # noqa: E402
import storage_db  # noqa: E402


class TestRadar180dEParserGemini(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "radar_test.db")
        self.conn = storage_db.conectar_db(self.db_path)
        storage_db.inicializar_db(self.conn)

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.tmp_dir.cleanup()

    def test_radar_bloqueia_selo_com_menos_de_5_dias(self):
        # 4 dias observados a R$ 300,00 -> warm-up insuficiente (< 5 dias)
        for dia in ("2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24"):
            storage_db.registrar_preco_dia(self.conn, "ML_WARMUP", "Mercado Livre", 300.0, data_coleta=dia)
        self.conn.commit()

        produtos = [
            {
                "sku": "ML_WARMUP",
                "loja": "Mercado Livre",
                "nome_produto": "Mouse Teste",
                "categoria": "Games",
                "preco_atual": 199.90,
            }
        ]
        res = magalu_scrapper.enriquecer_e_atualizar_historico_precos(
            produtos, conn=self.conn, dias=180, data_coleta="2026-11-25"
        )
        self.assertFalse(res[0]["menor_preco_historico"])
        self.assertEqual(res[0]["preco_medio_historico"], 300.0)
        self.assertEqual(res[0]["queda_real_percent"], 33.4)

    def test_radar_ativa_selo_e_bonus_com_5_ou_mais_dias(self):
        # 5 dias observados a R$ 300,00
        for dia in ("2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24"):
            storage_db.registrar_preco_dia(self.conn, "ML_MINIMA", "Mercado Livre", 300.0, data_coleta=dia)
            storage_db.registrar_preco_dia(self.conn, "ML_IGUAL", "Mercado Livre", 300.0, data_coleta=dia)
        self.conn.commit()

        produtos = [
            {
                "sku": "ML_MINIMA",
                "loja": "Mercado Livre",
                "nome_produto": "Headset Pro",
                "categoria": "Games",
                "preco_atual": 240.00,  # estritamente menor que min_180d (300)
                "percentual_desconto": 20.0,
                "lucro_estimado_reais": 15.0,
            },
            {
                "sku": "ML_IGUAL",
                "loja": "Mercado Livre",
                "nome_produto": "Headset Igual",
                "categoria": "Games",
                "preco_atual": 300.00,  # igual ao min_180d -> nao dispara selo
                "percentual_desconto": 20.0,
                "lucro_estimado_reais": 15.0,
            },
        ]
        res = magalu_scrapper.enriquecer_e_atualizar_historico_precos(
            produtos, conn=self.conn, dias=180, data_coleta="2026-11-25"
        )
        self.assertTrue(res[0]["menor_preco_historico"])
        self.assertEqual(res[0]["queda_real_percent"], 20.0)
        self.assertEqual(res[0]["preco_medio_historico"], 300.0)

        self.assertFalse(res[1]["menor_preco_historico"])

        score_com_selo = magalu_scrapper.calcular_score_qualidade_item(
            res[0]["menor_preco_historico"],
            res[0]["queda_real_percent"],
            res[0]["percentual_desconto"],
            res[0]["lucro_estimado_reais"],
            res[0]["preco_atual"],
        )
        score_sem_selo = magalu_scrapper.calcular_score_qualidade_item(
            res[1]["menor_preco_historico"],
            res[1]["queda_real_percent"],
            res[1]["percentual_desconto"],
            res[1]["lucro_estimado_reais"],
            res[1]["preco_atual"],
        )
        # Bônus de +45 da mínima histórica + bônus de queda real (20 * 1.5 = +30)
        self.assertEqual(score_com_selo - score_sem_selo, 75.0)

    def test_radar_mediana_amortece_pico_artificial_metade_do_dobro(self):
        # 4 dias a R$ 200 e 1 dia com pico falso a R$ 900 -> média seria 340, mediana é 200
        amostras = [
            ("2026-11-20", 200.0),
            ("2026-11-21", 200.0),
            ("2026-11-22", 200.0),
            ("2026-11-23", 200.0),
            ("2026-11-24", 900.0),
        ]
        for dia, preco in amostras:
            storage_db.registrar_preco_dia(self.conn, "MAGALU_PICO", "Magalu", preco, data_coleta=dia)
        self.conn.commit()

        produtos = [
            {
                "sku": "MAGALU_PICO",
                "loja": "Magalu",
                "nome_produto": "Monitor Fake",
                "categoria": "Informática",
                "preco_atual": 210.0,
            }
        ]
        res = magalu_scrapper.enriquecer_e_atualizar_historico_precos(
            produtos, conn=self.conn, dias=180, data_coleta="2026-11-25"
        )
        self.assertEqual(res[0]["preco_medio_historico"], 200.0)
        self.assertEqual(res[0]["queda_real_percent"], 0.0)
        self.assertFalse(res[0]["menor_preco_historico"])

    def test_radar_ordem_leitura_antes_de_escrita_e_rerun_mesmo_dia(self):
        for dia in ("2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24"):
            storage_db.registrar_preco_dia(self.conn, "ML_ORDEM", "Mercado Livre", 300.0, data_coleta=dia)
        self.conn.commit()

        # 1ª rodada do dia: lê 300.0 antes de gravar 250.0 -> marca mínima real e grava 250.0
        r1 = magalu_scrapper.enriquecer_e_atualizar_historico_precos(
            [{"sku": "ML_ORDEM", "loja": "Mercado Livre", "preco_atual": 250.0, "nome_produto": "SSD"}],
            conn=self.conn,
            dias=180,
            data_coleta="2026-11-25",
        )
        self.assertTrue(r1[0]["menor_preco_historico"])
        row_hoje = self.conn.execute(
            "SELECT preco_min_dia, preco_ultimo FROM historico_precos WHERE sku='ML_ORDEM' AND data_coleta='2026-11-25'"
        ).fetchone()
        self.assertEqual(row_hoje["preco_min_dia"], 250.0)

        # 2ª rodada no mesmo dia (ex: 15h BRT) a R$ 240: ainda exclui '2026-11-25' da comparação
        r2 = magalu_scrapper.enriquecer_e_atualizar_historico_precos(
            [{"sku": "ML_ORDEM", "loja": "Mercado Livre", "preco_atual": 240.0, "nome_produto": "SSD"}],
            conn=self.conn,
            dias=180,
            data_coleta="2026-11-25",
        )
        self.assertTrue(r2[0]["menor_preco_historico"])
        row_hoje_2 = self.conn.execute(
            "SELECT preco_min_dia, preco_ultimo FROM historico_precos WHERE sku='ML_ORDEM' AND data_coleta='2026-11-25'"
        ).fetchone()
        self.assertEqual(row_hoje_2["preco_min_dia"], 240.0)
        self.assertEqual(row_hoje_2["preco_ultimo"], 240.0)

    def test_anti_repeticao_72h_fallback_e_persistencia_sqlite(self):
        # Grava 10 SKUs postados recentemente no SQLite
        skus_postados = [f"ML_ITEM_{i}" for i in range(10)]
        catalogo_30 = [
            {"sku": f"ML_ITEM_{i}", "loja": "Mercado Livre", "preco_atual": 100.0 + i}
            for i in range(30)
        ]
        magalu_scrapper.salvar_historico_postados(
            skus_postados,
            df_todos_produtos=catalogo_30,
            conn=self.conn,
            canal_resumo="telegram,facebook",
        )

        ativos = magalu_scrapper.carregar_historico_postados(horas_validade=72, conn=self.conn)
        self.assertEqual(len(ativos), 10)

        # Com 30 produtos e 10 bloqueados -> sobram 20 (< 25) -> fallback mantém todos os 30
        filtrado_30 = magalu_scrapper.aplicar_filtro_anti_repeticao_72h(catalogo_30, ativos, minimo_ineditos=25)
        self.assertEqual(len(filtrado_30), 30)

        # Com 40 produtos e 10 bloqueados -> sobram 30 (>= 25) -> filtra para 30 inéditos
        catalogo_40 = [
            {"sku": f"ML_ITEM_{i}", "loja": "Mercado Livre", "preco_atual": 100.0 + i}
            for i in range(40)
        ]
        filtrado_40 = magalu_scrapper.aplicar_filtro_anti_repeticao_72h(catalogo_40, ativos, minimo_ineditos=25)
        self.assertEqual(len(filtrado_40), 30)
        self.assertTrue(all(item["sku"] not in ativos for item in filtrado_40))

    def test_parser_gemini_bem_formado_e_variacoes(self):
        item_ok = {
            "sku_selecionado": "ML_MLB101",
            "nome_produto": "Controle Sem Fio",
            "loja": "Mercado Livre",
            "preco_atual": 199.9,
            "percentual_desconto": 25,
            "url_afiliado": "https://mercadolivre.com.br/p/MLB101",
            "copy_venda": {"titulo": "Controle Pro", "corpo": "Super oferta", "cta": "Compre"},
        }

        # 1. JSON padrão
        res1 = magalu_scrapper.parsear_resposta_gemini(json.dumps({"oportunidades": [item_ok]}))
        self.assertEqual(res1["_origem"], "gemini")
        self.assertEqual(len(res1["oportunidades"]), 1)

        # 2. Markdown code fence
        fenced = f"```json\n{json.dumps({'oportunidades': [item_ok]})}\n```"
        res2 = magalu_scrapper.parsear_resposta_gemini(fenced)
        self.assertEqual(res2["_origem"], "gemini")
        self.assertEqual(res2["oportunidades"][0]["sku_selecionado"], "ML_MLB101")

        # 3. Array direto no topo ou chave alternativa ("ofertas")
        res3 = magalu_scrapper.parsear_resposta_gemini(json.dumps([item_ok]))
        self.assertEqual(res3["_origem"], "gemini")
        self.assertEqual(len(res3["oportunidades"]), 1)

        res4 = magalu_scrapper.parsear_resposta_gemini(json.dumps({"ofertas": [item_ok]}))
        self.assertEqual(res4["_origem"], "gemini")
        self.assertEqual(len(res4["oportunidades"]), 1)

    def test_parser_gemini_truncado_e_mal_formado_com_fallback(self):
        candidatas = [
            {
                "sku": f"ML_{i}",
                "nome_produto": f"Produto ML {i}",
                "loja": "Mercado Livre",
                "categoria": "Games",
                "preco_atual": 120.0 + i,
                "preco_antigo": 200.0,
                "percentual_desconto": 35.0,
                "comissao_percent": 6.5,
                "lucro_estimado_reais": 8.0,
                "url_afiliado": f"https://ml.test/{i}",
                "imagem_url": f"https://img.test/{i}.jpg",
                "menor_preco_historico": (i == 0),
                "queda_real_percent": 15.0,
                "preco_medio_historico": 150.0,
                "score_qualidade": 100.0 - i,
            }
            for i in range(18)
        ] + [
            {
                "sku": f"MAGALU_{j}",
                "nome_produto": f"Produto Magalu {j}",
                "loja": "Magalu",
                "categoria": "Informática",
                "preco_atual": 220.0 + j,
                "preco_antigo": 320.0,
                "percentual_desconto": 30.0,
                "comissao_percent": 4.0,
                "lucro_estimado_reais": 9.0,
                "url_afiliado": f"https://magalu.test/{j}",
                "imagem_url": f"https://img.test/m{j}.jpg",
                "menor_preco_historico": False,
                "queda_real_percent": 5.0,
                "preco_medio_historico": 240.0,
                "score_qualidade": 90.0 - j,
            }
            for j in range(6)
        ]

        # 1. JSON truncado no 3º item -> resgata os 2 itens íntegros
        truncado = (
            '{"oportunidades": ['
            '{"sku_selecionado": "ML_0", "nome_produto": "Prod 0", "preco_atual": 120},'
            '{"sku_selecionado": "ML_1", "nome_produto": "Prod 1", "preco_atual": 121},'
            '{"sku_selecionado": "ML_2", "nome_produto": "Cortado no mei'
        )
        with self.assertLogs(level="WARNING"):
            res_parc = magalu_scrapper.parsear_resposta_gemini(truncado, candidatas_fallback=candidatas)
        self.assertEqual(res_parc["_origem"], "gemini_parcial")
        self.assertEqual(len(res_parc["oportunidades"]), 2)

        # 2. Resposta totalmente mal-formada / {"erro": ...} / lista vazia -> ativa fallback 15 ML + 5 Magalu
        for resposta_ruim in (
            "Aqui vai sua seleção: erro inesperado sem json",
            '{"erro": "A análise da IA falhou", "motivo": "timeout"}',
            '{"oportunidades": []}',
            "",
        ):
            with self.assertLogs(level="WARNING") as cm:
                res_fb = magalu_scrapper.parsear_resposta_gemini(
                    resposta_ruim, candidatas_fallback=candidatas, qtd_ml=15, qtd_magalu=5
                )
            self.assertEqual(res_fb["_origem"], "fallback_deterministico")
            self.assertEqual(len(res_fb["oportunidades"]), 20)
            qtd_ml = sum(1 for x in res_fb["oportunidades"] if x["loja"] == "Mercado Livre")
            qtd_mg = sum(1 for x in res_fb["oportunidades"] if x["loja"] == "Magalu")
            self.assertEqual(qtd_ml, 15)
            self.assertEqual(qtd_mg, 5)
            self.assertTrue(any("Parser Gemini sem oportunidades válidas" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
