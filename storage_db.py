import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import statistics
import sys
import unicodedata
from datetime import datetime, timedelta

DEFAULT_DB_PATH = "alpha_profit.db"
TABELAS_OBRIGATORIAS = (
    "historico_precos",
    "historico_postados",
    "pautas_rss",
    "metadados_sync",
)


def conectar_db(db_path=DEFAULT_DB_PATH):
    """Abre conexão SQLite em modo DELETE (sem WAL) para compactação segura em arquivo único."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=FULL;")
    return conn


def inicializar_db(conn):
    """Cria as tabelas e índices principais de forma idempotente."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS historico_precos (
            sku TEXT NOT NULL,
            loja TEXT NOT NULL,
            data_coleta TEXT NOT NULL,
            preco_min_dia REAL NOT NULL,
            preco_ultimo REAL NOT NULL,
            titulo TEXT NOT NULL DEFAULT '',
            categoria TEXT NOT NULL DEFAULT '',
            atualizado_em TEXT NOT NULL,
            PRIMARY KEY (sku, loja, data_coleta)
        );

        CREATE INDEX IF NOT EXISTS idx_historico_precos_lookup
            ON historico_precos (sku, loja, data_coleta);

        CREATE INDEX IF NOT EXISTS idx_historico_precos_data
            ON historico_precos (data_coleta);

        CREATE TABLE IF NOT EXISTS historico_postados (
            sku TEXT NOT NULL,
            loja TEXT NOT NULL,
            postado_em TEXT NOT NULL,
            preco_postado REAL,
            canal_resumo TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (sku, loja, postado_em)
        );

        CREATE INDEX IF NOT EXISTS idx_historico_postados_ts
            ON historico_postados (postado_em);

        CREATE INDEX IF NOT EXISTS idx_historico_postados_sku
            ON historico_postados (sku, postado_em);

        CREATE TABLE IF NOT EXISTS pautas_rss (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            fonte TEXT NOT NULL,
            titulo TEXT NOT NULL,
            tema_normalizado TEXT NOT NULL,
            publicado_em TEXT NOT NULL,
            canais_postados TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_pautas_rss_pub
            ON pautas_rss (publicado_em);

        CREATE INDEX IF NOT EXISTS idx_pautas_rss_tema
            ON pautas_rss (tema_normalizado);

        CREATE TABLE IF NOT EXISTS metadados_sync (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );
        """
    )
    conn.commit()


def inferir_loja_por_sku(sku):
    """Infere o nome padronizado da loja a partir do prefixo do SKU legado."""
    sku_norm = str(sku or "").strip().upper()
    if sku_norm.startswith("ML_"):
        return "Mercado Livre"
    if sku_norm.startswith("MAGALU_"):
        return "Magalu"
    return "Desconhecida"


def definir_metadado(conn, chave, valor, atualizado_em=None):
    ts = atualizado_em or datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO metadados_sync (chave, valor, atualizado_em)
        VALUES (?, ?, ?)
        ON CONFLICT(chave) DO UPDATE SET
            valor = excluded.valor,
            atualizado_em = excluded.atualizado_em
        """,
        (str(chave), str(valor), ts),
    )


def obter_metadado(conn, chave, padrao=None):
    row = conn.execute(
        "SELECT valor, atualizado_em FROM metadados_sync WHERE chave = ?",
        (str(chave),),
    ).fetchone()
    if not row:
        return padrao, None
    return row["valor"], row["atualizado_em"]


def registrar_preco_dia(
    conn,
    sku,
    loja,
    preco,
    data_coleta=None,
    titulo="",
    categoria="",
    atualizado_em=None,
    preco_min_inicial=None,
):
    """
    Faz upsert diário do preço mantendo sempre o menor valor registrado no dia
    (MIN(preco_min_dia, excluded.preco_min_dia)) e atualizando o último preço observado.
    """
    sku_limpo = str(sku or "").strip()
    loja_limpa = str(loja or "").strip() or inferir_loja_por_sku(sku_limpo)
    try:
        preco_val = round(float(preco), 2)
    except (TypeError, ValueError):
        return False

    if not sku_limpo or preco_val <= 0:
        return False

    preco_min_val = preco_val
    if preco_min_inicial is not None:
        try:
            min_cand = round(float(preco_min_inicial), 2)
            if min_cand > 0:
                preco_min_val = min(preco_val, min_cand)
        except (TypeError, ValueError):
            pass

    data_str = str(data_coleta or datetime.now().strftime("%Y-%m-%d"))[:10]
    ts_str = str(atualizado_em or datetime.now().isoformat())

    conn.execute(
        """
        INSERT INTO historico_precos (
            sku, loja, data_coleta, preco_min_dia, preco_ultimo,
            titulo, categoria, atualizado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku, loja, data_coleta) DO UPDATE SET
            preco_min_dia = MIN(historico_precos.preco_min_dia, excluded.preco_min_dia),
            preco_ultimo = excluded.preco_ultimo,
            titulo = CASE
                WHEN excluded.titulo != '' THEN excluded.titulo
                ELSE historico_precos.titulo
            END,
            categoria = CASE
                WHEN excluded.categoria != '' THEN excluded.categoria
                ELSE historico_precos.categoria
            END,
            atualizado_em = excluded.atualizado_em
        """,
        (
            sku_limpo,
            loja_limpa,
            data_str,
            preco_min_val,
            preco_val,
            str(titulo or "").strip(),
            str(categoria or "").strip(),
            ts_str,
        ),
    )
    return True


def registrar_precos_lote(conn, registros):
    """Executa upsert em lote na tabela historico_precos dentro de uma transação."""
    inseridos = 0
    for reg in registros:
        ok = registrar_preco_dia(
            conn,
            sku=reg.get("sku"),
            loja=reg.get("loja"),
            preco=reg.get("preco"),
            data_coleta=reg.get("data_coleta"),
            titulo=reg.get("titulo", ""),
            categoria=reg.get("categoria", ""),
            atualizado_em=reg.get("atualizado_em"),
            preco_min_inicial=reg.get("preco_min_inicial"),
        )
        if ok:
            inseridos += 1
    conn.commit()
    return inseridos


def obter_estatisticas_sku(
    conn,
    sku,
    loja,
    dias=180,
    data_referencia=None,
    excluir_data=None,
):
    """
    Calcula min_180d, mediana_180d, media_180d e dias_observados para um (sku, loja).
    """
    ref_dt = (
        datetime.strptime(str(data_referencia)[:10], "%Y-%m-%d")
        if data_referencia
        else datetime.now()
    )
    ref_str = ref_dt.strftime("%Y-%m-%d")
    limite_str = (ref_dt - timedelta(days=int(dias))).strftime("%Y-%m-%d")

    params = [str(sku).strip(), str(loja).strip(), limite_str, ref_str]
    sql = """
        SELECT preco_min_dia
        FROM historico_precos
        WHERE sku = ? AND loja = ? AND data_coleta >= ? AND data_coleta <= ?
    """
    if excluir_data:
        sql += " AND data_coleta != ?"
        params.append(str(excluir_data)[:10])

    rows = conn.execute(sql, params).fetchall()
    valores = [float(r["preco_min_dia"]) for r in rows if r["preco_min_dia"] and float(r["preco_min_dia"]) > 0]

    if not valores:
        return {
            "min_180d": None,
            "mediana_180d": None,
            "media_180d": None,
            "dias_observados": 0,
        }

    return {
        "min_180d": round(min(valores), 2),
        "mediana_180d": round(float(statistics.median(valores)), 2),
        "media_180d": round(float(statistics.mean(valores)), 2),
        "dias_observados": len(valores),
    }


def registrar_postagem(conn, sku, loja=None, preco_postado=None, canal_resumo="", postado_em=None):
    """Registra uma publicação na trava anti-repetição de 72h de forma idempotente."""
    sku_limpo = str(sku or "").strip()
    if not sku_limpo:
        return False
    loja_limpa = str(loja or "").strip() or inferir_loja_por_sku(sku_limpo)
    ts_str = str(postado_em or datetime.now().isoformat())
    preco_val = None
    if preco_postado is not None:
        try:
            preco_val = round(float(preco_postado), 2)
        except (TypeError, ValueError):
            preco_val = None

    conn.execute(
        """
        INSERT OR IGNORE INTO historico_postados (
            sku, loja, postado_em, preco_postado, canal_resumo
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (sku_limpo, loja_limpa, ts_str, preco_val, str(canal_resumo or "").strip()),
    )
    return True


def registrar_postagens_lote(conn, itens):
    """Registra múltiplas postagens em uma única transação."""
    count = 0
    for item in itens:
        if registrar_postagem(
            conn,
            sku=item.get("sku"),
            loja=item.get("loja"),
            preco_postado=item.get("preco_postado"),
            canal_resumo=item.get("canal_resumo", ""),
            postado_em=item.get("postado_em"),
        ):
            count += 1
    conn.commit()
    return count


def carregar_skus_postados_recentes(conn, horas_validade=72, agora=None):
    """Retorna {sku: ultimo_timestamp_iso} para itens postados dentro da janela de horas_validade."""
    ref_dt = agora if isinstance(agora, datetime) else datetime.now()
    limite = ref_dt - timedelta(hours=int(horas_validade))
    rows = conn.execute(
        "SELECT sku, postado_em FROM historico_postados ORDER BY postado_em DESC"
    ).fetchall()

    recentes = {}
    for row in rows:
        sku = str(row["sku"])
        ts_str = str(row["postado_em"])
        try:
            ts_dt = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts_dt > limite:
            if sku not in recentes or ts_str > recentes[sku]:
                recentes[sku] = ts_str
    return recentes


def normalizar_tema(texto):
    """Normaliza título/tema RSS (sem acentos, lowercase, alfanumérico) para deduplicação."""
    bruto = unicodedata.normalize("NFKD", str(texto or "").lower())
    sem_acentos = "".join(ch for ch in bruto if not unicodedata.combining(ch))
    palavras = re.findall(r"[a-z0-9]+", sem_acentos)
    return " ".join(palavras[:16])


def gerar_url_hash(url):
    """Gera hash SHA-256 determinístico da URL normalizada."""
    url_limpa = str(url or "").strip().split("#")[0].rstrip("/")
    return hashlib.sha256(url_limpa.encode("utf-8")).hexdigest()


def pauta_ja_publicada(conn, url, tema_normalizado=None, dias=7, agora=None):
    """Verifica se uma pauta com a mesma URL ou mesmo tema normalizado foi usada nos últimos N dias."""
    ref_dt = agora if isinstance(agora, datetime) else datetime.now()
    limite_iso = (ref_dt - timedelta(days=int(dias))).isoformat()
    u_hash = gerar_url_hash(url)
    tema = tema_normalizado or normalizar_tema(url)

    row = conn.execute(
        """
        SELECT id FROM pautas_rss
        WHERE publicado_em >= ?
          AND (url_hash = ? OR (tema_normalizado != '' AND tema_normalizado = ?))
        LIMIT 1
        """,
        (limite_iso, u_hash, tema),
    ).fetchone()
    return row is not None


def registrar_pauta_rss(
    conn,
    url,
    fonte,
    titulo,
    tema_normalizado=None,
    canais_postados="",
    publicado_em=None,
):
    """Persiste pauta editorial publicada para evitar repetição por 7 dias."""
    u_hash = gerar_url_hash(url)
    tema = tema_normalizado or normalizar_tema(titulo)
    pub_iso = str(publicado_em or datetime.now().isoformat())
    conn.execute(
        """
        INSERT OR IGNORE INTO pautas_rss (
            url_hash, url, fonte, titulo, tema_normalizado, publicado_em, canais_postados
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (u_hash, str(url).strip(), str(fonte).strip(), str(titulo).strip(), tema, pub_iso, str(canais_postados).strip()),
    )
    conn.commit()
    return u_hash


def migrar_jsons_legados(
    conn,
    precos_path="historico_precos.json",
    postados_path="historico_postados.json",
):
    """
    Importa historico_precos.json e historico_postados.json de forma idempotente.
    Segura para rodar repetidas vezes sem duplicar registros.
    """
    precos_migrados = 0
    postados_migrados = 0
    hoje = datetime.now().strftime("%Y-%m-%d")

    if precos_path and os.path.exists(precos_path):
        try:
            with open(precos_path, "r", encoding="utf-8") as f:
                dados_precos = json.load(f)
            if isinstance(dados_precos, dict):
                for sku, info in dados_precos.items():
                    if not isinstance(info, dict):
                        continue
                    data_col = str(info.get("updated") or hoje)[:10]
                    last_val = info.get("last") or info.get("min") or info.get("avg")
                    min_val = info.get("min") or last_val
                    if last_val is None:
                        continue
                    if registrar_preco_dia(
                        conn,
                        sku=sku,
                        loja=inferir_loja_por_sku(sku),
                        preco=last_val,
                        data_coleta=data_col,
                        atualizado_em=f"{data_col}T00:00:00",
                        preco_min_inicial=min_val,
                    ):
                        precos_migrados += 1
        except Exception as exc:
            logging.warning(f"Aviso ao migrar {precos_path}: {exc}")

    if postados_path and os.path.exists(postados_path):
        try:
            with open(postados_path, "r", encoding="utf-8") as f:
                dados_postados = json.load(f)
            if isinstance(dados_postados, dict):
                for sku, ts_str in dados_postados.items():
                    if not sku or not ts_str:
                        continue
                    try:
                        datetime.fromisoformat(str(ts_str))
                    except ValueError:
                        continue
                    if registrar_postagem(
                        conn,
                        sku=sku,
                        loja=inferir_loja_por_sku(sku),
                        preco_postado=None,
                        canal_resumo="legado_json",
                        postado_em=str(ts_str),
                    ):
                        postados_migrados += 1
        except Exception as exc:
            logging.warning(f"Aviso ao migrar {postados_path}: {exc}")

    definir_metadado(
        conn,
        "ultima_migracao_em",
        datetime.now().isoformat(),
    )
    conn.commit()
    logging.info(
        f"Migração SQLite concluída: {precos_migrados} preços e {postados_migrados} postagens processadas."
    )
    return {
        "precos_migrados": precos_migrados,
        "postados_migrados": postados_migrados,
    }


def limpar_historico_antigo(
    conn,
    dias=180,
    dias_postados=30,
    dias_rss=90,
    executar_vacuum=True,
    data_referencia=None,
):
    """
    Aplica janela deslizante de retenção (180 dias para preços) e compacta o banco via VACUUM.
    Grava a quantidade removida em metadados_sync para evitar falso positivo no guardrail.
    """
    ref_dt = (
        datetime.strptime(str(data_referencia)[:10], "%Y-%m-%d")
        if data_referencia
        else datetime.now()
    )
    limite_precos = (ref_dt - timedelta(days=int(dias))).strftime("%Y-%m-%d")
    limite_postados = (ref_dt - timedelta(days=int(dias_postados))).isoformat()
    limite_rss = (ref_dt - timedelta(days=int(dias_rss))).isoformat()

    cur_p = conn.execute(
        "DELETE FROM historico_precos WHERE data_coleta < ?",
        (limite_precos,),
    )
    cur_post = conn.execute(
        "DELETE FROM historico_postados WHERE postado_em < ?",
        (limite_postados,),
    )
    cur_rss = conn.execute(
        "DELETE FROM pautas_rss WHERE publicado_em < ?",
        (limite_rss,),
    )

    precos_removidos = cur_p.rowcount if cur_p.rowcount is not None and cur_p.rowcount >= 0 else 0
    postados_removidos = cur_post.rowcount if cur_post.rowcount is not None and cur_post.rowcount >= 0 else 0
    rss_removidos = cur_rss.rowcount if cur_rss.rowcount is not None and cur_rss.rowcount >= 0 else 0

    agora_iso = datetime.now().isoformat()
    definir_metadado(conn, "ultima_limpeza_removidos", str(precos_removidos), agora_iso)
    definir_metadado(conn, "ultima_limpeza_em", agora_iso, agora_iso)
    conn.commit()

    if executar_vacuum:
        old_iso = conn.isolation_level
        try:
            conn.isolation_level = None
            conn.execute("VACUUM")
        finally:
            conn.isolation_level = old_iso

    logging.info(
        f"Limpeza concluída (>{dias}d): {precos_removidos} preços, "
        f"{postados_removidos} postagens e {rss_removidos} pautas removidos."
    )
    return {
        "precos_removidos": precos_removidos,
        "postados_removidos": postados_removidos,
        "rss_removidos": rss_removidos,
    }


def contar_linhas_precos(db_path=DEFAULT_DB_PATH):
    """Retorna o total de linhas em historico_precos sem manter conexão aberta."""
    if not db_path or not os.path.exists(db_path):
        return 0
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='historico_precos'"
        ).fetchone()
        if not row:
            return 0
        total = conn.execute("SELECT COUNT(*) FROM historico_precos").fetchone()[0]
        return int(total or 0)
    except Exception:
        return 0
    finally:
        if conn is not None:
            conn.close()


def validar_integridade_db(
    db_path=DEFAULT_DB_PATH,
    baseline_linhas=0,
    max_queda_pct=0.15,
    removidos_esperados=None,
):
    """
    Valida PRAGMA integrity_check, tabelas obrigatórias, journal_mode=DELETE
    e proteção contra queda abrupta de linhas (descontando expurgos legítimos de 180d).
    """
    detalhes = {
        "db_path": db_path,
        "baseline_linhas": int(baseline_linhas or 0),
        "linhas_atuais": 0,
        "removidos_justificados": 0,
        "integrity_check": None,
        "journal_mode": None,
        "motivo": "ok",
    }

    if not db_path or not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        detalhes["motivo"] = "arquivo_ausente_ou_vazio"
        return False, detalhes

    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row

        chk = conn.execute("PRAGMA integrity_check").fetchall()
        chk_val = chk[0][0] if chk else ""
        detalhes["integrity_check"] = chk_val
        if str(chk_val).lower() != "ok":
            detalhes["motivo"] = f"integrity_check_falhou: {chk_val}"
            return False, detalhes

        jm = conn.execute("PRAGMA journal_mode").fetchone()
        jm_val = str(jm[0]).lower() if jm else ""
        detalhes["journal_mode"] = jm_val
        if jm_val != "delete":
            conn.execute("PRAGMA journal_mode=DELETE;")
            jm2 = conn.execute("PRAGMA journal_mode").fetchone()
            detalhes["journal_mode"] = str(jm2[0]).lower() if jm2 else ""

        tabelas_existentes = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        faltando = [t for t in TABELAS_OBRIGATORIAS if t not in tabelas_existentes]
        if faltando:
            detalhes["motivo"] = f"tabelas_ausentes: {faltando}"
            return False, detalhes

        linhas_atuais = int(
            conn.execute("SELECT COUNT(*) FROM historico_precos").fetchone()[0] or 0
        )
        detalhes["linhas_atuais"] = linhas_atuais

        base = int(baseline_linhas or 0)
        if base > 0 and linhas_atuais == 0:
            detalhes["motivo"] = "banco_vazio_com_baseline_positivo"
            return False, detalhes

        if base > 0:
            removidos_just = 0
            if removidos_esperados is not None:
                removidos_just = max(0, int(removidos_esperados))
            else:
                val_rem, ts_rem = obter_metadado(conn, "ultima_limpeza_removidos", "0")
                if ts_rem:
                    try:
                        if datetime.now() - datetime.fromisoformat(ts_rem) <= timedelta(hours=6):
                            removidos_just = max(0, int(val_rem or 0))
                    except ValueError:
                        removidos_just = 0

            detalhes["removidos_justificados"] = removidos_just
            base_esperada = max(0, base - removidos_just)
            queda_injustificada = max(0, base_esperada - linhas_atuais)
            queda_pct = queda_injustificada / float(base)
            detalhes["queda_injustificada_pct"] = round(queda_pct * 100, 2)

            if queda_pct > float(max_queda_pct):
                detalhes["motivo"] = (
                    f"queda_anomala_linhas ({linhas_atuais} vs esperado {base_esperada}, "
                    f"queda injustificada {queda_pct * 100:.1f}% > {max_queda_pct * 100:.1f}%)"
                )
                return False, detalhes

        return True, detalhes
    except sqlite3.DatabaseError as exc:
        detalhes["motivo"] = f"sqlite_corrompido: {exc}"
        return False, detalhes
    finally:
        if conn is not None:
            conn.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="CLI da camada SQLite do Alpha-Profit.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Caminho para o arquivo .db")
    parser.add_argument("--init", action="store_true", help="Inicializa esquema SQLite")
    parser.add_argument("--migrate", action="store_true", help="Migra JSONs legados de forma idempotente")
    parser.add_argument("--precos-json", default="historico_precos.json", help="Caminho do historico_precos.json")
    parser.add_argument("--postados-json", default="historico_postados.json", help="Caminho do historico_postados.json")
    parser.add_argument("--baseline", action="store_true", help="Imprime apenas o COUNT(*) atual de historico_precos")
    parser.add_argument("--cleanup", action="store_true", help="Limpa registros antigos (>N dias) e executa VACUUM")
    parser.add_argument("--dias", type=int, default=180, help="Janela de retenção em dias (padrão: 180)")
    parser.add_argument("--validate", action="store_true", help="Valida integridade do DB antes do upload")
    parser.add_argument("--baseline-count", type=int, default=0, help="Baseline capturado no início da execução")
    parser.add_argument("--max-queda-pct", type=float, default=0.15, help="Tolerância máxima de queda injustificada (padrão: 0.15)")

    args = parser.parse_args()

    if args.baseline and not (args.init or args.migrate or args.cleanup or args.validate):
        print(contar_linhas_precos(args.db))
        return 0

    if args.init or args.migrate or args.cleanup:
        conn = conectar_db(args.db)
        try:
            if args.init:
                inicializar_db(conn)
            if args.migrate:
                migrar_jsons_legados(
                    conn,
                    precos_path=args.precos_json,
                    postados_path=args.postados_json,
                )
            if args.cleanup:
                limpar_historico_antigo(conn, dias=args.dias, executar_vacuum=True)
        finally:
            conn.close()

    if args.baseline:
        print(contar_linhas_precos(args.db))

    if args.validate:
        ok, detalhes = validar_integridade_db(
            db_path=args.db,
            baseline_linhas=args.baseline_count,
            max_queda_pct=args.max_queda_pct,
        )
        print(json.dumps(detalhes, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
