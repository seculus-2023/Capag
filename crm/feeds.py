"""Monitor de atualizações jurídicas: lê feeds RSS/Atom de tribunais, órgãos e portais
e guarda as notícias por área (tributário federal, tributário estadual, ambiental)."""
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from django.utils import timezone
from django.utils.html import strip_tags

from .models import Atualizacao, Fonte

# Fontes iniciais (feeds públicos conferidos em 01/10/2026). A PGFN e as PGEs não publicam
# feed próprio; são acompanhadas pelas notícias que as citam. Outras fontes entram pela
# área administrativa (Fontes de atualização).
FONTES_PADRAO = [
    ("ConJur – Tributário", "https://www.conjur.com.br/tag/tributario/feed/", "TRIB_FED", ""),
    ("ConJur – PGFN", "https://www.conjur.com.br/tag/pgfn/feed/", "TRIB_FED", ""),
    ("Receita Federal – Notícias", "https://www.gov.br/receitafederal/pt-br/assuntos/noticias/RSS", "TRIB_FED", ""),
    ("JOTA – PGFN, CARF e transação", "https://www.jota.info/feed", "TRIB_FED",
     "PGFN, Procuradoria-Geral da Fazenda, transação tributária, dívida ativa, CARF, CAPAG"),
    ("ConJur – ICMS", "https://www.conjur.com.br/tag/icms/feed/", "TRIB_EST", ""),
    ("JOTA – PGE, Sefaz e ICMS", "https://www.jota.info/feed", "TRIB_EST",
     "PGE, Procuradoria-Geral do Estado, Sefaz, ICMS, ITCMD, IPVA, Confaz"),
    ("ConJur – Direito Ambiental", "https://www.conjur.com.br/tag/direito-ambiental/feed/", "AMBIENTAL", ""),
    ("Ibama", "https://www.gov.br/ibama/pt-br/RSS", "AMBIENTAL", ""),
    ("Câmara dos Deputados – Meio Ambiente", "https://www.camara.leg.br/noticias/rss/dinamico/MEIO-AMBIENTE", "AMBIENTAL", ""),
]


def criar_fontes_padrao():
    for nome, url, area, palavras in FONTES_PADRAO:
        Fonte.objects.get_or_create(nome=nome, defaults={"url": url, "area": area, "palavras_chave": palavras})


def _tag(el):
    return el.tag.rsplit("}", 1)[-1].lower()


def _filho(el, *nomes):
    for f in el:
        if _tag(f) in nomes:
            return f
    return None


def _texto(el, *nomes):
    f = _filho(el, *nomes)
    return (f.text or "").strip() if f is not None else ""


def _data(txt):
    if not txt:
        return None
    try:
        dt = parsedate_to_datetime(txt)  # RSS 2.0: "Mon, 21 Sep 2026 11:29:37 +0000"
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))  # Atom / RSS 1.0 (dc:date)
        except ValueError:
            return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _limpar(txt, limite=None):
    txt = re.sub(r"\s+", " ", html.unescape(strip_tags(html.unescape(txt or "")))).strip()
    return txt[:limite - 1] + "…" if limite and len(txt) > limite else txt


def ler_feed(xml):
    """Interpreta RSS 2.0, RSS 1.0 (RDF) e Atom. Devolve [{titulo, link, resumo, publicado_em}]."""
    raiz = ET.fromstring(xml)
    itens = []
    for el in raiz.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        link = _texto(el, "link")
        if not link:  # Atom: <link href="..."/>
            for f in el:
                if _tag(f) == "link" and f.get("rel", "alternate") == "alternate":
                    link = f.get("href", "")
                    break
        titulo = _limpar(_texto(el, "title"), 400)
        if not (titulo and link.startswith("http")):
            continue
        itens.append({
            "titulo": titulo, "link": link[:700],
            "resumo": _limpar(_texto(el, "description", "summary", "content"), 600),
            "publicado_em": _data(_texto(el, "pubdate", "date", "published", "updated")),
        })
    return itens


def _casa(palavras, texto):
    termos = [p.strip() for p in palavras.split(",") if p.strip()]
    if not termos:
        return True
    return any(re.search(rf"\b{re.escape(t)}\b", texto, flags=re.IGNORECASE) for t in termos)


def atualizar_fonte(fonte):
    """Baixa o feed da fonte e grava as notícias novas. Devolve quantas entraram."""
    novas = 0
    try:
        r = requests.get(fonte.url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (CAPAG CRM)"})
        r.raise_for_status()
        for item in ler_feed(r.content):
            if not _casa(fonte.palavras_chave, f"{item['titulo']} {item['resumo']}"):
                continue
            if fonte.ignorar_ate and item["publicado_em"] and item["publicado_em"] <= fonte.ignorar_ate:
                continue  # já excluída pelo usuário
            _, criada = Atualizacao.objects.get_or_create(link=item["link"], defaults={
                "fonte": fonte, "area": fonte.area, "titulo": item["titulo"], "resumo": item["resumo"],
                "publicado_em": item["publicado_em"] or timezone.now()})
            novas += criada
        fonte.ultimo_erro = ""
    except Exception as exc:  # noqa: BLE001 – uma fonte fora do ar não interrompe as demais
        fonte.ultimo_erro = str(exc)[:300]
    fonte.ultima_leitura = timezone.now()
    fonte.save(update_fields=["ultimo_erro", "ultima_leitura"])
    return novas


def atualizar_tudo():
    if not Fonte.objects.exists():
        criar_fontes_padrao()
    return sum(atualizar_fonte(f) for f in Fonte.objects.filter(ativo=True))
