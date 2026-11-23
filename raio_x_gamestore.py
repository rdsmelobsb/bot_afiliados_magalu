"""
Raio-X sob demanda da Página do Facebook (Gamestore) via Meta Graph API (100% stdlib / gratuito).

Como usar no Windows (CMD):
    set FACEBOOK_PAGE_TOKEN=SEU_TOKEN_AQUI
    python raio_x_gamestore.py

Ou rode apenas `python raio_x_gamestore.py` e cole o token quando solicitado.
"""

import getpass
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


def graph_get(path, params):
    url = f"https://graph.facebook.com/v21.0/{path.lstrip('/')}?{urlencode(params)}"
    try:
        with urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
            return None, err.get("error", {}).get("message", str(e))
        except Exception:
            return None, str(e)
    except Exception as e:
        return None, str(e)


def resolver_pagina(token, page_id=None):
    acc, _ = graph_get("me/accounts", {"fields": "id,name,access_token", "access_token": token})
    if acc and acc.get("data"):
        paginas = acc["data"]
        escolhida = next((p for p in paginas if page_id and str(p.get("id")) == str(page_id)), paginas[0])
        return escolhida.get("id"), escolhida.get("access_token") or token
    me, err = graph_get("me", {"fields": "id,name", "access_token": token})
    if not me:
        raise RuntimeError(f"Token inválido ou expirado: {err}")
    return me.get("id"), token


def utc_para_brt_hora(iso_str):
    try:
        dt = datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S") - timedelta(hours=3)
        return dt.strftime("%d/%m/%Y %H:%M"), dt.hour
    except Exception:
        return iso_str[:16], None


def executar_raio_x():
    token = os.getenv("FACEBOOK_PAGE_TOKEN", "").strip()
    if not token:
        print("Cole o seu FACEBOOK_PAGE_TOKEN (entrada oculta) e pressione Enter:")
        token = getpass.getpass("Token: ").strip()
    if not token:
        print("Nenhum token informado. Encerrando.")
        return

    page_id, page_token = resolver_pagina(token, os.getenv("FACEBOOK_PAGE_ID"))
    info, err = graph_get(
        page_id,
        {
            "fields": "id,name,category,followers_count,fan_count,about,website",
            "access_token": page_token,
        },
    )
    if not info:
        print(f"Erro ao ler dados da Página: {err}")
        return

    print("\n" + "=" * 64)
    print(f"📘 RAIO-X DA PÁGINA: {info.get('name')} (ID: {info.get('id')})")
    print("=" * 64)
    print(f"Categoria  : {info.get('category', 'N/A')}")
    print(f"Seguidores : {info.get('followers_count', 'N/A')}")
    print(f"Curtidas   : {info.get('fan_count', 'N/A')}")
    print(f"Website    : {info.get('website', 'Não definido')}")

    # 1. Posts históricos (últimos 50)
    posts_resp, p_err = graph_get(
        f"{page_id}/posts",
        {
            "fields": "id,message,created_time,shares,likes.summary(true),comments.summary(true)",
            "limit": 50,
            "access_token": page_token,
        },
    )
    posts = (posts_resp or {}).get("data", [])
    if p_err:
        print(f"\n⚠️ Aviso ao buscar posts: {p_err}")

    analisados = []
    por_hora = defaultdict(lambda: {"posts": 0, "eng": 0})
    for p in posts:
        likes = int(((p.get("likes") or {}).get("summary") or {}).get("total_count", 0) or 0)
        comments = int(((p.get("comments") or {}).get("summary") or {}).get("total_count", 0) or 0)
        shares = int((p.get("shares") or {}).get("count", 0) or 0)
        score = likes + (comments * 2) + (shares * 3)
        data_brt, hora = utc_para_brt_hora(str(p.get("created_time", "")))
        msg = str(p.get("message") or "(Mídia / Sem legenda)").replace("\n", " ").strip()
        analisados.append({
            "data": data_brt,
            "msg": (msg[:80] + "...") if len(msg) > 83 else msg,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "score": score,
        })
        if hora is not None:
            por_hora[hora]["posts"] += 1
            por_hora[hora]["eng"] += score

    analisados.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n📊 Posts analisados: {len(analisados)}")
    if analisados:
        media_eng = sum(x["score"] for x in analisados) / len(analisados)
        print(f"Engajamento médio ponderado/post: {media_eng:.1f}")
        print("\n🏆 TOP 10 POSTS COM MAIS ENGAJAMENTO:")
        for idx, p in enumerate(analisados[:10], start=1):
            print(f"  {idx:2d}. [{p['data']}] ❤️ {p['likes']} | 💬 {p['comments']} | 🔁 {p['shares']} — {p['msg']}")

    if por_hora:
        ranking_horas = sorted(
            por_hora.items(),
            key=lambda kv: kv[1]["eng"] / max(kv[1]["posts"], 1),
            reverse=True,
        )[:5]
        print("\n⏰ MELHORES HORÁRIOS HISTÓRICOS (BRT):")
        for h, d in ranking_horas:
            media_h = d["eng"] / max(d["posts"], 1)
            print(f"  • {h:02d}h BRT — média {media_h:.1f} pts de engajamento ({d['posts']} posts)")

    # 2. Insights de alcance & público (se read_insights estiver ativo)
    print("\n📈 INSIGHTS DE ALCANCE & PÚBLICO (requer permissão read_insights):")
    ins, ins_err = graph_get(
        f"{page_id}/insights",
        {
            "metric": "page_impressions_unique,page_post_engagements,page_views_total",
            "period": "days_28",
            "access_token": page_token,
        },
    )
    if ins and ins.get("data"):
        for m in ins["data"]:
            vals = m.get("values", [])
            val = vals[-1].get("value") if vals else "N/A"
            print(f"  • {m.get('title') or m.get('name')} (28d): {val}")
    else:
        print(f"  (Indisponível no token atual — adicione 'read_insights' no App AFILIADOS se quiser alcance/demografia. Detalhe: {ins_err})")

    # 3. Demografia (cidades/países — liberada com 100+ seguidores e read_insights)
    demo, _ = graph_get(
        f"{page_id}/insights",
        {
            "metric": "page_fans_city,page_fans_country",
            "period": "lifetime",
            "access_token": page_token,
        },
    )
    if demo and demo.get("data"):
        for m in demo["data"]:
            vals = m.get("values", [])
            mapa = vals[-1].get("value", {}) if vals else {}
            if isinstance(mapa, dict) and mapa:
                top5 = sorted(mapa.items(), key=lambda kv: kv[1], reverse=True)[:5]
                print(f"  • Top {m.get('name')}: " + ", ".join(f"{k} ({v})" for k, v in top5))

    print("\n✅ Raio-X concluído!\n")


if __name__ == "__main__":
    executar_raio_x()
