import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage_db  # noqa: E402


class TestStorageDB(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "alpha_profit_test.db")
        self.conn = storage_db.conectar_db(self.db_path)
        storage_db.inicializar_db(self.conn)

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.tmp_dir.cleanup()

    def test_journal_mode_delete_e_tabelas_obrigatorias(self):
        jm = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(jm).lower(), "delete")

        tabelas = {
            r["name"]
            for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for esperada in storage_db.TABELAS_OBRIGATORIAS:
            self.assertIn(esperada, tabelas)

    def test_upsert_mantem_menor_preco_do_dia(self):
        hoje = "2026-11-25"
        storage_db.registrar_preco_dia(
            self.conn,
            sku="ML_MLB123",
            loja="Mercado Livre",
            preco=250.00,
            data_coleta=hoje,
            titulo="Mouse Gamer",
            categoria="Games",
        )
        # Preço cai no mesmo dia -> min passa a ser 199.90 e ultimo 199.90
        storage_db.registrar_preco_dia(
            self.conn,
            sku="ML_MLB123",
            loja="Mercado Livre",
            preco=199.90,
            data_coleta=hoje,
        )
        # Preço sobe depois no mesmo dia -> ultimo vira 279.00, mas min do dia continua 199.90
        storage_db.registrar_preco_dia(
            self.conn,
            sku="ML_MLB123",
            loja="Mercado Livre",
            preco=279.00,
            data_coleta=hoje,
        )
        self.conn.commit()

        row = self.conn.execute(
            "SELECT preco_min_dia, preco_ultimo, titulo FROM historico_precos WHERE sku='ML_MLB123'"
        ).fetchone()
        self.assertEqual(row["preco_min_dia"], 199.90)
        self.assertEqual(row["preco_ultimo"], 279.00)
        self.assertEqual(row["titulo"], "Mouse Gamer")

    def test_migracao_jsons_legados_idempotente(self):
        precos_json = os.path.join(self.tmp_dir.name, "historico_precos.json")
        postados_json = os.path.join(self.tmp_dir.name, "historico_postados.json")

        hoje = datetime.now().strftime("%Y-%m-%d")
        ts_recente = (datetime.now() - timedelta(hours=5)).isoformat()
        ts_antigo = (datetime.now() - timedelta(hours=100)).isoformat()

        with open(precos_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ML_MLB999": {"min": 149.0, "avg": 170.0, "count": 4, "last": 165.0, "updated": hoje},
                    "MAGALU_555": {"min": 89.9, "avg": 99.9, "count": 2, "last": 89.9, "updated": hoje},
                },
                f,
            )

        with open(postados_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ML_MLB999": ts_recente,
                    "MAGALU_555": ts_antigo,
                },
                f,
            )

        r1 = storage_db.migrar_jsons_legados(self.conn, precos_json, postados_json)
        self.assertEqual(r1["precos_migrados"], 2)
        self.assertEqual(r1["postados_migrados"], 2)

        # Segunda execução deve ser 100% idempotente
        r2 = storage_db.migrar_jsons_legados(self.conn, precos_json, postados_json)
        self.assertEqual(r2["precos_migrados"], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM historico_precos").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM historico_postados").fetchone()[0], 2)

        row_ml = self.conn.execute("SELECT loja, preco_min_dia, preco_ultimo FROM historico_precos WHERE sku='ML_MLB999'").fetchone()
        self.assertEqual(row_ml["loja"], "Mercado Livre")
        self.assertEqual(row_ml["preco_min_dia"], 149.0)
        self.assertEqual(row_ml["preco_ultimo"], 165.0)

        recentes = storage_db.carregar_skus_postados_recentes(self.conn, horas_validade=72)
        self.assertIn("ML_MLB999", recentes)
        self.assertNotIn("MAGALU_555", recentes)

    def test_obter_estatisticas_sku_180d_com_mediana_e_pico_artificial(self):
        ref = "2026-11-25"
        # 5 dias anteriores: 4 dias a R$ 200 e 1 dia inflado a R$ 800 ("metade do dobro")
        amostras = [
            ("2026-11-20", 200.0),
            ("2026-11-21", 200.0),
            ("2026-11-22", 200.0),
            ("2026-11-23", 200.0),
            ("2026-11-24", 800.0),
        ]
        for dt, val in amostras:
            storage_db.registrar_preco_dia(self.conn, "ML_TEST", "Mercado Livre", val, data_coleta=dt)
        self.conn.commit()

        stats = storage_db.obter_estatisticas_sku(self.conn, "ML_TEST", "Mercado Livre", dias=180, data_referencia=ref)
        self.assertEqual(stats["dias_observados"], 5)
        self.assertEqual(stats["min_180d"], 200.0)
        self.assertEqual(stats["mediana_180d"], 200.0)  # Mediana resiste ao pico de 800!
        self.assertEqual(stats["media_180d"], 320.0)

    def test_limpeza_180_dias_e_validacao_integridade_sem_falso_positivo(self):
        # Insere 10 registros antigos (> 180 dias) e 2 recentes
        for i in range(10):
            storage_db.registrar_preco_dia(
                self.conn, f"ML_OLD_{i}", "Mercado Livre", 100.0, data_coleta="2026-01-01"
            )
        storage_db.registrar_preco_dia(
            self.conn, "ML_NEW_1", "Mercado Livre", 150.0, data_coleta="2026-11-20"
        )
        storage_db.registrar_preco_dia(
            self.conn, "ML_NEW_2", "Mercado Livre", 180.0, data_coleta="2026-11-25"
        )
        self.conn.commit()
        self.conn.close()

        baseline = storage_db.contar_linhas_precos(self.db_path)
        self.assertEqual(baseline, 12)

        # Limpeza apaga 10 de 12 linhas (queda de 83% > 15%), mas é legítima pelo expurgo de 180d!
        conn = storage_db.conectar_db(self.db_path)
        res = storage_db.limpar_historico_antigo(conn, dias=180, executar_vacuum=True, data_referencia="2026-11-25")
        conn.close()

        self.assertEqual(res["precos_removidos"], 10)
        self.assertEqual(storage_db.contar_linhas_precos(self.db_path), 2)

        ok, detalhes = storage_db.validar_integridade_db(self.db_path, baseline_linhas=baseline)
        self.assertTrue(ok, msg=f"Esperava aprovação após limpeza legítima, veio: {detalhes}")
        self.assertEqual(detalhes["removidos_justificados"], 10)

    def test_guarda_integridade_reprova_queda_anomala_e_corrupcao(self):
        for i in range(10):
            storage_db.registrar_preco_dia(
                self.conn, f"ML_A_{i}", "Mercado Livre", 120.0, data_coleta="2026-11-24"
            )
        self.conn.commit()
        self.conn.close()

        # Queda abrupta para baseline=20 (50% de perda injustificada > 15%)
        ok, detalhes = storage_db.validar_integridade_db(self.db_path, baseline_linhas=20)
        self.assertFalse(ok)
        self.assertIn("queda_anomala_linhas", detalhes["motivo"])

        # Arquivo corrompido
        corrupt_path = os.path.join(self.tmp_dir.name, "corrupt.db")
        with open(corrupt_path, "wb") as f:
            f.write(b"nao e um banco sqlite valido" * 20)
        ok_c, det_c = storage_db.validar_integridade_db(corrupt_path, baseline_linhas=1)
        self.assertFalse(ok_c)

    def test_deduplicacao_pautas_rss_7_dias(self):
        url = "https://adrenaline.com.br/noticias/placa-video-cai-preco"
        self.assertFalse(storage_db.pauta_ja_publicada(self.conn, url, storage_db.normalizar_tema("Placa de vídeo cai de preço")))
        storage_db.registrar_pauta_rss(
            self.conn,
            url=url,
            fonte="Adrenaline",
            titulo="Placa de vídeo cai de preço no Brasil!",
            canais_postados="threads,x,facebook",
        )
        # Mesma URL -> bloqueia
        self.assertTrue(storage_db.pauta_ja_publicada(self.conn, url))
        # URL diferente mas mesmo tema normalizado -> bloqueia
        self.assertTrue(
            storage_db.pauta_ja_publicada(
                self.conn,
                "https://tecnoblog.net/noticias/outro-link",
                storage_db.normalizar_tema("Placa de vídeo cai de preço no Brasil"),
            )
        )

    def test_cli_fluxo_completo(self):
        cli_db = os.path.join(self.tmp_dir.name, "cli.db")
        script = str(Path(__file__).resolve().parent.parent / "storage_db.py")

        r_init = subprocess.run(
            [sys.executable, script, "--db", cli_db, "--init", "--baseline"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(r_init.stdout.strip(), "0")

        r_val = subprocess.run(
            [sys.executable, script, "--db", cli_db, "--validate", "--baseline-count", "0"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(r_val.stdout)
        self.assertEqual(payload["integrity_check"], "ok")
        self.assertEqual(payload["journal_mode"], "delete")


if __name__ == "__main__":
    unittest.main()
