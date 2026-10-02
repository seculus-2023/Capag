"""Pesquisa de mercado: extrai empresas de um município a partir do OpenStreetMap
(Overpass API), que é gratuito e não exige chave. Os dados servem para estudo de mercado;
as empresas não entram no funil nem recebem mensagens (OAB, Provimento 205/2021)."""
import re
import time

import requests

from .models import EmpresaMapa

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TENTATIVAS = 3  # o servidor público devolve 504/429 quando está ocupado; vale tentar de novo
PAUSA = 5
LIMITE = 500

# segmento → filtros de tags do OpenStreetMap
CATEGORIAS = {
    "postos": ("Postos de combustível", ['["amenity"="fuel"]']),
    "supermercados": ("Supermercados e atacados", ['["shop"~"^(supermarket|wholesale)$"]']),
    "industrias": ("Indústrias e fábricas", ['["man_made"="works"]', '["industrial"]', '["landuse"="industrial"]']),
    "agro": ("Agropecuárias e insumos agrícolas", ['["shop"~"^(agrarian|farm)$"]']),
    "frigorificos": ("Frigoríficos e abatedouros", ['["industrial"="slaughterhouse"]', '["shop"="butcher"]']),
    "madeireiras": ("Madeireiras e serrarias", ['["craft"="sawmill"]', '["trade"="wood"]', '["industrial"="sawmill"]']),
    "mineracao": ("Mineração e pedreiras", ['["landuse"="quarry"]']),
    "construcao": ("Materiais de construção", ['["shop"~"^(doityourself|hardware|trade)$"]']),
    "veiculos": ("Concessionárias e oficinas", ['["shop"~"^(car|car_repair|truck|tyres)$"]']),
    "transporte": ("Transportadoras e logística", ['["office"="logistics"]', '["industrial"="logistics"]',
                                                    '["building"="warehouse"]']),
    "hoteis": ("Hotéis e pousadas", ['["tourism"~"^(hotel|motel|guest_house)$"]']),
    "saude": ("Clínicas, hospitais e farmácias", ['["amenity"~"^(clinic|hospital|pharmacy)$"]']),
    "empresas": ("Escritórios de empresas", ['["office"~"^(company|accountant|insurance|estate_agent)$"]']),
}
# sem segmento: qualquer estabelecimento cujo nome contenha o termo
GERAL = [f'["{k}"]' for k in ("shop", "office", "amenity", "craft", "industrial", "man_made", "tourism")]

ROTULOS = {"fuel": "Posto de combustível", "supermarket": "Supermercado", "wholesale": "Atacado", "works": "Indústria",
           "industrial": "Área industrial", "agrarian": "Agropecuária", "farm": "Produtos rurais",
           "slaughterhouse": "Frigorífico", "butcher": "Açougue", "sawmill": "Serraria", "wood": "Madeireira",
           "quarry": "Mineração / pedreira", "doityourself": "Materiais de construção", "hardware": "Ferragens",
           "trade": "Comércio de materiais", "car": "Concessionária", "car_repair": "Oficina", "truck": "Caminhões",
           "tyres": "Pneus", "logistics": "Logística", "warehouse": "Armazém", "hotel": "Hotel", "motel": "Motel",
           "guest_house": "Pousada", "clinic": "Clínica", "hospital": "Hospital", "pharmacy": "Farmácia",
           "company": "Empresa", "accountant": "Contabilidade", "insurance": "Seguros", "estate_agent": "Imobiliária"}
CHAVES_TIPO = ("industrial", "craft", "trade", "shop", "office", "amenity", "tourism", "man_made", "landuse", "building")


class ErroMapa(Exception):
    pass


def _regex(valor):
    """Escapa o texto digitado para uso numa expressão regular dentro de uma string do Overpass."""
    valor = re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", valor.strip())
    return valor.replace("\\", "\\\\").replace('"', '\\"')


def montar_consulta(municipio, uf, categoria="", termo=""):
    filtros = CATEGORIAS[categoria][1] if categoria else GERAL
    nome = f'["name"~"{_regex(termo)}",i]' if termo.strip() else '["name"]'
    linhas = "\n".join(f"  nwr{f}{nome}(area.a);" for f in filtros)
    return (f'[out:json][timeout:60];\n'
            f'area["ISO3166-2"="BR-{uf.upper()}"]->.uf;\n'
            f'rel(area.uf)["boundary"="administrative"]["admin_level"="8"]["name"~"^{_regex(municipio)}$",i];\n'
            f'map_to_area->.a;\n(\n{linhas}\n);\nout center tags {LIMITE};')


def _tipo(tags):
    for chave in CHAVES_TIPO:
        v = tags.get(chave)
        if v and v != "yes":
            return ROTULOS.get(v, v.replace("_", " ").capitalize())
    return ""


def _endereco(tags):
    rua = " ".join(x for x in [tags.get("addr:street"), tags.get("addr:housenumber")] if x)
    cep = f"CEP {tags['addr:postcode']}" if tags.get("addr:postcode") else ""
    return ", ".join(x for x in [rua, tags.get("addr:suburb"), cep] if x)


def interpretar(elementos):
    """Converte a resposta do Overpass em dicionários com os campos de EmpresaMapa."""
    saida, vistos = [], set()
    for el in elementos:
        tags = el.get("tags") or {}
        centro = el.get("center") or el
        chave = (tags.get("name", "").lower(), _endereco(tags))
        if not tags.get("name") or chave in vistos:
            continue
        vistos.add(chave)
        saida.append({
            "osm_ref": f"{el['type']}/{el['id']}", "nome": tags["name"][:200], "tipo": _tipo(tags)[:80],
            "endereco": _endereco(tags)[:250],
            "telefone": (tags.get("contact:phone") or tags.get("phone") or tags.get("contact:mobile") or "")[:60],
            "email": (tags.get("contact:email") or tags.get("email") or "")[:200],
            "site": (tags.get("contact:website") or tags.get("website") or "")[:300],
            "latitude": centro.get("lat"), "longitude": centro.get("lon"),
        })
    saida.sort(key=lambda e: e["nome"].lower())
    return saida


def extrair(pesquisa):
    """Executa a pesquisa no OpenStreetMap e grava as empresas encontradas. Devolve a quantidade."""
    consulta = montar_consulta(pesquisa.municipio, pesquisa.uf, pesquisa.categoria, pesquisa.termo)
    dados = None
    for tentativa in range(TENTATIVAS):
        if tentativa:
            time.sleep(PAUSA)
        try:
            r = requests.post(OVERPASS_URL, data={"data": consulta}, timeout=90,
                              headers={"User-Agent": "CAPAG-CRM/1.0 (pesquisa de mercado)"})
            if r.status_code in (429, 504):
                continue  # servidor ocupado
            r.raise_for_status()
            resposta = r.json()
        except Exception:  # noqa: BLE001 – fora do ar ou sem resposta em 90 s
            break
        if "remark" in resposta and not resposta.get("elements"):
            break  # a consulta estourou o tempo no servidor
        dados = resposta
        break
    if dados is None:
        raise ErroMapa("O OpenStreetMap não respondeu agora. Tente de novo em alguns minutos "
                       "ou use um segmento ou nome mais específico.")
    empresas = interpretar(dados.get("elements", []))
    pesquisa.empresas.all().delete()
    EmpresaMapa.objects.bulk_create(EmpresaMapa(pesquisa=pesquisa, **e) for e in empresas)
    pesquisa.total = len(empresas)
    pesquisa.save(update_fields=["total"])
    return len(empresas)
