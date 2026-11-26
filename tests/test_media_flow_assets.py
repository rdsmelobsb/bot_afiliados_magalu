from io import BytesIO
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_generator  # noqa: E402


class TestMediaFlowAssets(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.bg_dir = os.path.join(self.tmp_dir.name, "backgrounds")
        self.outro_dir = os.path.join(self.tmp_dir.name, "outros")
        os.makedirs(self.bg_dir, exist_ok=True)
        os.makedirs(self.outro_dir, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _criar_jpeg_bytes(self, size=(400, 400)):
        im = Image.new("RGB", size, (25, 140, 210))
        buf = BytesIO()
        im.save(buf, format="JPEG")
        return buf.getvalue()

    def test_pastas_vazias_e_feature_flags_desligadas_fazem_fallback_limpo(self):
        # 1. Apenas .gitkeep nas pastas -> retorna None sem erros
        with open(os.path.join(self.bg_dir, ".gitkeep"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(self.outro_dir, ".gitkeep"), "w", encoding="utf-8") as f:
            f.write("")

        self.assertIsNone(media_generator.selecionar_broll_fundo(self.bg_dir))
        self.assertIsNone(media_generator.selecionar_outro_gamestore(self.outro_dir))

        reel_in = os.path.join(self.tmp_dir.name, "reel_sem_outro.mp4")
        with open(reel_in, "wb") as f_mp4:
            f_mp4.write(b"0" * 60000)

        with patch.object(media_generator, "ASSETS_OUTROS_DIR", self.outro_dir):
            with patch.object(media_generator.subprocess, "run", side_effect=AssertionError("Não deveria chamar FFmpeg")):
                res = media_generator.anexar_outro_gamestore(reel_in)
        self.assertEqual(res, reel_in)

        # 2. Com .mp4 presente mas flags desligadas -> também ignora
        with open(os.path.join(self.bg_dir, "bg_cyber_01.mp4"), "wb") as f:
            f.write(b"1" * 1024)
        with open(os.path.join(self.outro_dir, "outro_gamestore.mp4"), "wb") as f:
            f.write(b"1" * 1024)

        with patch.dict(os.environ, {"REEL_BROLL_ENABLED": "false", "REEL_OUTRO_ENABLED": "false"}, clear=False):
            self.assertIsNone(media_generator.selecionar_broll_fundo(self.bg_dir))
            self.assertIsNone(media_generator.selecionar_outro_gamestore(self.outro_dir))

        # 3. HyperFrames com pastas vazias não injeta <video id="broll-bg">
        op = {
            "nome_produto": "Headset Gamer Sem Fio",
            "loja": "Magalu",
            "preco_atual": 299.90,
            "percentual_desconto": 25.0,
            "menor_preco_historico": True,
            "url_afiliado": "https://magalu.test/headset",
        }
        mp4_out = os.path.join(self.tmp_dir.name, "reel_vazio.mp4")

        def fake_hf_run(cmd, cwd=None, capture_output=True, text=True, timeout=240):
            with open(mp4_out, "wb") as f_out:
                f_out.write(b"0" * 60000)

            class Res:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return Res()

        empty_bg = os.path.join(self.tmp_dir.name, "empty_bg")
        empty_outro = os.path.join(self.tmp_dir.name, "empty_outro")
        os.makedirs(empty_bg, exist_ok=True)
        os.makedirs(empty_outro, exist_ok=True)

        with patch.object(media_generator, "OUTPUT_DIR", self.tmp_dir.name):
            with patch.object(media_generator, "ASSETS_BACKGROUNDS_DIR", empty_bg):
                with patch.object(media_generator, "ASSETS_OUTROS_DIR", empty_outro):
                    with patch.dict(os.environ, {"REEL_BROLL_ENABLED": "true", "REEL_OUTRO_ENABLED": "true"}, clear=False):
                        with patch.object(media_generator.shutil, "which", side_effect=lambda b: "hyperframes" if "hyperframes" in b else None):
                            with patch.object(media_generator.subprocess, "run", side_effect=fake_hf_run):
                                res_hf = media_generator.gerar_video_reel_hyperframes(
                                    op, img_bytes=self._criar_jpeg_bytes(), arquivo_saida=mp4_out
                                )

        self.assertEqual(res_hf, mp4_out)
        with open(os.path.join(self.tmp_dir.name, "hf_job", "index.html"), "r", encoding="utf-8") as f_html:
            html_txt = f_html.read()
        self.assertNotIn('id="broll-bg"', html_txt)
        self.assertIn("MENOR PREÇO 180D", html_txt)

    def test_descoberta_broll_outro_e_flags_ffmpeg_scrim_concat(self):
        bg_file = os.path.join(self.bg_dir, "bg_cyber_01.mp4")
        outro_pref = os.path.join(self.outro_dir, "outro_gamestore.mp4")
        outro_sec = os.path.join(self.outro_dir, "aaa_outro_extra.mp4")
        for p in (bg_file, outro_pref, outro_sec):
            with open(p, "wb") as f:
                f.write(b"mp4data" * 500)

        with patch.dict(os.environ, {"REEL_BROLL_ENABLED": "true", "REEL_OUTRO_ENABLED": "true"}, clear=False):
            self.assertEqual(media_generator.selecionar_broll_fundo(self.bg_dir), bg_file)
            # Prioriza outro_gamestore.mp4 mesmo havendo aaa_outro_extra.mp4 antes na ordem alfabética
            self.assertEqual(media_generator.selecionar_outro_gamestore(self.outro_dir), outro_pref)

        # 1. preparar_broll_fundo_mp4 valida loop, 1080x1920, 30fps, scrim 0.60 e -an
        broll_norm = os.path.join(self.tmp_dir.name, "broll_norm.mp4")
        cmds_broll = []

        def fake_ffmpeg_broll(cmd, capture_output=True, text=True, timeout=120):
            cmds_broll.append(cmd)
            with open(cmd[-1], "wb") as f_out:
                f_out.write(b"0" * 20000)

            class Res:
                returncode = 0
                stderr = ""

            return Res()

        with patch.object(media_generator.shutil, "which", return_value="ffmpeg"):
            with patch.object(media_generator.subprocess, "run", side_effect=fake_ffmpeg_broll):
                out_b = media_generator.preparar_broll_fundo_mp4(bg_file, 11.5, broll_norm)

        self.assertEqual(out_b, broll_norm)
        cmd_b = " ".join(cmds_broll[0])
        self.assertIn("-stream_loop -1", cmd_b)
        self.assertIn("-t 11.50", cmd_b)
        self.assertIn("scale=1080:1920", cmd_b)
        self.assertIn("crop=1080:1920", cmd_b)
        self.assertIn("fps=30", cmd_b)
        self.assertIn("black@0.60", cmd_b)
        self.assertIn("yuv420p", cmd_b)
        self.assertIn("-an", cmd_b)

        # 2. anexar_outro_gamestore com áudio ausente no Outro -> injeta anullsrc + concat + drawtext CTA
        reel_in = os.path.join(self.tmp_dir.name, "reel_principal.mp4")
        with open(reel_in, "wb") as f:
            f.write(b"reel" * 5000)

        cmds_concat = []

        def fake_ffmpeg_concat(cmd, capture_output=True, text=True, timeout=180):
            cmds_concat.append(cmd)
            with open(cmd[-1], "wb") as f_out:
                f_out.write(b"concat" * 5000)

            class Res:
                returncode = 0
                stderr = ""

            return Res()

        with patch.object(media_generator.shutil, "which", return_value="ffmpeg"):
            with patch.object(media_generator, "_video_tem_audio", side_effect=[True, False]):
                with patch.object(media_generator, "_obter_duracao_audio", side_effect=[10.0, 2.0]):
                    with patch.object(media_generator.subprocess, "run", side_effect=fake_ffmpeg_concat):
                        res_sem_audio = media_generator.anexar_outro_gamestore(reel_in, outro_path=outro_pref)

        self.assertEqual(res_sem_audio, reel_in)
        cmd_c1 = " ".join(cmds_concat[0])
        self.assertIn("anullsrc=channel_layout=stereo:sample_rate=44100", cmd_c1)
        self.assertIn("concat=n=2:v=1:a=1[vout][aout]", cmd_c1)
        self.assertIn("y=1290", cmd_c1)
        self.assertIn("SIGA @PROMOSGEEKTECH", cmd_c1)

        # 3. anexar_outro_gamestore com áudio presente em ambos -> NÃO injeta anullsrc
        cmds_concat.clear()
        with patch.object(media_generator.shutil, "which", return_value="ffmpeg"):
            with patch.object(media_generator, "_video_tem_audio", side_effect=[True, True]):
                with patch.object(media_generator, "_obter_duracao_audio", side_effect=[10.0, 2.0]):
                    with patch.object(media_generator.subprocess, "run", side_effect=fake_ffmpeg_concat):
                        res_com_audio = media_generator.anexar_outro_gamestore(reel_in, outro_path=outro_pref)

        self.assertEqual(res_com_audio, reel_in)
        cmd_c2 = " ".join(cmds_concat[0])
        self.assertNotIn("anullsrc", cmd_c2)
        self.assertIn("concat=n=2:v=1:a=1[vout][aout]", cmd_c2)

    def test_hyperframes_oferta_com_broll_outro_e_workflow_flags(self):
        bg_file = os.path.join(self.bg_dir, "bg_cyber_01.mp4")
        outro_file = os.path.join(self.outro_dir, "outro_gamestore.mp4")
        for p in (bg_file, outro_file):
            with open(p, "wb") as f:
                f.write(b"mp4data" * 500)

        op = {
            "nome_produto": "SSD NVMe 1TB",
            "loja": "Mercado Livre",
            "preco_atual": 349.90,
            "percentual_desconto": 30.0,
            "menor_preco_historico": False,
            "url_afiliado": "https://mercadolivre.com.br/p/MLB1",
        }
        mp4_out = os.path.join(self.tmp_dir.name, "reel_com_broll.mp4")
        chamadas_outro = []

        def fake_hf_run(cmd, cwd=None, capture_output=True, text=True, timeout=240):
            with open(mp4_out, "wb") as f_out:
                f_out.write(b"0" * 60000)

            class Res:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return Res()

        def _fake_prep(src, dur, dst):
            Path(dst).write_bytes(b"broll")
            return dst

        with patch.object(media_generator, "OUTPUT_DIR", self.tmp_dir.name):
            with patch.object(media_generator, "ASSETS_BACKGROUNDS_DIR", self.bg_dir):
                with patch.object(media_generator, "ASSETS_OUTROS_DIR", self.outro_dir):
                    with patch.object(media_generator, "preparar_broll_fundo_mp4", side_effect=_fake_prep):
                        with patch.object(
                            media_generator,
                            "anexar_outro_gamestore",
                            side_effect=lambda p: chamadas_outro.append(p) or p,
                        ):
                            with patch.object(
                                media_generator.shutil,
                                "which",
                                side_effect=lambda b: "hyperframes" if "hyperframes" in b else None,
                            ):
                                with patch.object(media_generator.subprocess, "run", side_effect=fake_hf_run):
                                    res_hf = media_generator.gerar_video_reel_hyperframes(
                                        op, img_bytes=self._criar_jpeg_bytes(), arquivo_saida=mp4_out
                                    )

                                    mp4_ed = os.path.join(self.tmp_dir.name, "reel_editorial_outro.mp4")

                                    def fake_hf_ed(cmd, cwd=None, capture_output=True, text=True, timeout=240):
                                        Path(mp4_ed).write_bytes(b"0" * 60000)

                                        class ResEd:
                                            returncode = 0
                                            stdout = "ok"
                                            stderr = ""

                                        return ResEd()

                                    with patch.object(media_generator.subprocess, "run", side_effect=fake_hf_ed):
                                        with patch.object(media_generator, "gerar_locucao_texto_ptbr", return_value=None):
                                            res_ed = media_generator.gerar_reel_editorial_rss(
                                                headline_card="RTX 5070 entra em queda real no Brasil",
                                                destaque_card="RTX 5070",
                                                tag_categoria="HARDWARE",
                                                fonte="Adrenaline",
                                                roteiro_reel="Placa de vídeo cai de preço nesta semana.",
                                                img_bytes=self._criar_jpeg_bytes(),
                                                arquivo_saida=mp4_ed,
                                            )

        self.assertEqual(res_hf, mp4_out)
        self.assertEqual(res_ed, mp4_ed)
        self.assertEqual(chamadas_outro, [mp4_out, mp4_ed])
        with open(os.path.join(self.tmp_dir.name, "hf_job", "index.html"), "r", encoding="utf-8") as f_html:
            html_txt = f_html.read()
        self.assertIn('id="broll-bg"', html_txt)
        self.assertIn("./assets/broll_bg.mp4", html_txt)

        # Verifica env vars no workflow e arquivos .gitkeep/.md em assets/
        root_dir = Path(__file__).resolve().parent.parent
        wf_txt = (root_dir / ".github" / "workflows" / "alpha-profit-bot.yml").read_text(encoding="utf-8")
        self.assertIn("REEL_BROLL_ENABLED: 'true'", wf_txt)
        self.assertIn("REEL_OUTRO_ENABLED: 'true'", wf_txt)
        self.assertTrue((root_dir / "assets" / "backgrounds" / ".gitkeep").exists())
        self.assertTrue((root_dir / "assets" / "outros" / ".gitkeep").exists())
        self.assertTrue((root_dir / "assets" / "PROMPTS_GOOGLE_FLOW.md").exists())


if __name__ == "__main__":
    unittest.main()
