"""
Relatórios gerenciais da CAPAG: ranking por faixa, evolução plurianual,
composição dos indicadores e alertas de risco/inconsistência.

Indicadores (adaptação da metodologia CAPAG para empresas):

    Endividamento     = dívida ativa consolidada ÷ receita bruta 12 meses (equivale a Dívida ÷ RCL)
    Poupança corrente = (custos + parcelas de financiamento + outras dívidas) ÷ receita bruta
    Liquidez          = ativo circulante ÷ passivo circulante
                        (sem balanço informado: caixa ÷ obrigações de 12 meses, marcada como estimada)

As faixas de cada indicador são referências de leitura; a nota oficial continua sendo o rating
da CAPAG real (CAPAG ÷ dívida), calculado em services.py.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .services import _razao, brl

NIVEIS = "ABCD"

# (limite "bom", limite "atenção", maior_melhor)
FAIXAS = {
    "endividamento": (Decimal("0.60"), Decimal("1.50"), False),
    "poupanca": (Decimal("0.90"), Decimal("0.95"), False),
    "liquidez": (Decimal("1.50"), Decimal("1.00"), True),
}
SITUACAO = {"bom": ("Adequado", "success"), "atencao": ("Atenção", "warning"),
            "critico": ("Crítico", "danger"), None: ("Sem dados", "secondary")}


def _div(a, b):
    return (Decimal(a) / Decimal(b)) if b else None


def _situacao(nome, valor):
    if valor is None:
        return None
    bom, atencao, maior_melhor = FAIXAS[nome]
    if maior_melhor:
        return "bom" if valor >= bom else "atencao" if valor >= atencao else "critico"
    return "bom" if valor <= bom else "atencao" if valor <= atencao else "critico"


def fmt_razao(v, casas=2):
    return "—" if v is None else f"{v:.{casas}f}".replace(".", ",")


def fmt_pct(v):
    return "—" if v is None else f"{v * 100:.1f}%".replace(".", ",")


# ------------------------------------------------------------------ indicadores
def indicadores(a):
    """Rácios de uma análise, com numerador, denominador e situação de cada um."""
    despesas = a.custos_despesas_12m + a.parcelas_financiamento_12m + a.outras_dividas_12m
    obrigacoes_12m = a.parcelas_financiamento_12m + a.outras_dividas_12m
    if a.passivo_circulante:
        liq_num, liq_den, liq_estimada = a.ativo_circulante, a.passivo_circulante, False
        liq_formula = "Ativo circulante ÷ Passivo circulante"
        liq_labels = ("Ativo circulante", "Passivo circulante")
    else:
        liq_num, liq_den, liq_estimada = a.disponibilidades, obrigacoes_12m, True
        liq_formula = "Caixa e bancos ÷ Obrigações de 12 meses (estimada: balanço não informado)"
        liq_labels = ("Caixa e bancos", "Parcelas de financiamento + outras dívidas (12 meses)")

    itens = [
        dict(chave="endividamento", nome="Endividamento", formula="Dívida consolidada ÷ Receita corrente (12 meses)",
             num_label="Dívida ativa consolidada", num=a.divida_total,
             den_label="Receita bruta (12 meses)", den=a.receita_bruta_12m, pct=False),
        dict(chave="poupanca", nome="Poupança corrente", formula="Despesas correntes ÷ Receitas correntes",
             num_label="Custos + parcelas de financiamento + outras dívidas", num=despesas,
             den_label="Receita bruta (12 meses)", den=a.receita_bruta_12m, pct=True),
        dict(chave="liquidez", nome="Liquidez", formula=liq_formula, estimada=liq_estimada,
             num_label=liq_labels[0], num=liq_num, den_label=liq_labels[1], den=liq_den, pct=False),
    ]
    for i in itens:
        i["valor"] = _div(i["num"], i["den"])
        i["situacao"] = _situacao(i["chave"], i["valor"])
        i["situacao_label"], i["cor"] = SITUACAO[i["situacao"]]
        i["texto"] = fmt_pct(i["valor"]) if i["pct"] else (fmt_razao(i["valor"]) + ("×" if i["valor"] is not None else ""))
        bom, atencao, maior = FAIXAS[i["chave"]]
        f = fmt_pct if i["pct"] else (lambda v: fmt_razao(v) + "×")
        i["referencia"] = (f"Adequado ≥ {f(bom)} · Atenção ≥ {f(atencao)} · Crítico abaixo" if maior
                           else f"Adequado ≤ {f(bom)} · Atenção ≤ {f(atencao)} · Crítico acima")
    return {i["chave"]: i for i in itens}


def passos_rating(a):
    """Passo a passo da nota (CAPAG real ÷ dívida) com os parâmetros gravados na análise."""
    pu = a.parametros_usados or {}
    razao = _div(a.capag_real, a.divida_total)
    fa, fb, fc = (Decimal(pu.get(k, d)) for k, d in
                  (("fator_rating_a", "2"), ("fator_rating_b", "1"), ("fator_rating_c", "0.5")))
    return {
        "razao": razao,
        "razao_txt": _razao(a.capag_real, a.divida_total),
        "faixas": [("A", f"≥ {fmt_razao(fa)}×"), ("B", f"≥ {fmt_razao(fb)}× e < {fmt_razao(fa)}×"),
                   ("C", f"≥ {fmt_razao(fc)}× e < {fmt_razao(fb)}×"), ("D", f"< {fmt_razao(fc)}× ou irrecuperável")],
        "horizonte": pu.get("horizonte_anos", 5),
        "realizacao": pu.get("percentual_realizacao_bens", "100"),
        "irrecuperavel": a.situacao_irrecuperavel,
    }


# ------------------------------------------------------------------ seleção
def ultimas_por_empresa(qs, por_ano=False):
    """Última análise de cada empresa (ou de cada empresa/ano) — qs deve vir ordenado por data desc."""
    vistos, saida = set(), []
    for a in qs.order_by("-data_referencia", "-pk"):
        chave = (a.empresa_id, a.data_referencia.year) if por_ano else a.empresa_id
        if chave not in vistos:
            vistos.add(chave)
            saida.append(a)
    return saida


def ranking(analises):
    """Agrupa por faixa A→D; dentro da faixa, maior relação CAPAG ÷ dívida primeiro."""
    grupos = {r: [] for r in NIVEIS}
    for a in analises:
        a.ind = indicadores(a)
        a.razao = _div(a.capag_real, a.divida_total)
        grupos.setdefault(a.rating_real or "D", []).append(a)
    for lst in grupos.values():
        lst.sort(key=lambda x: (x.razao is None, -(x.razao or 0)))
    return grupos


# ------------------------------------------------------------------ evolução
def evolucao(empresa, ano_ini=None, ano_fim=None):
    qs = empresa.analises.all()
    if ano_ini:
        qs = qs.filter(data_referencia__year__gte=ano_ini)
    if ano_fim:
        qs = qs.filter(data_referencia__year__lte=ano_fim)
    linhas = sorted(ultimas_por_empresa(qs, por_ano=True), key=lambda a: a.data_referencia)
    anterior = None
    for a in linhas:
        a.ano = a.data_referencia.year
        a.ind = indicadores(a)
        a.razao_txt = _razao(a.capag_real, a.divida_total)
        a.tendencia = None
        if anterior and a.rating_real and anterior.rating_real:
            d = NIVEIS.index(a.rating_real) - NIVEIS.index(anterior.rating_real)
            a.tendencia = "melhora" if d < 0 else "piora" if d > 0 else "estavel"
        anterior = a
    return linhas


def variacoes(ini, fim):
    """Compara os indicadores do primeiro e do último ano: (nome, início, fim, tendência)."""
    out = []
    for k in ("endividamento", "poupanca", "liquidez"):
        a, b = ini.ind[k], fim.ind[k]
        tendencia = None
        if a["valor"] is not None and b["valor"] is not None and a["valor"] != b["valor"]:
            subiu = b["valor"] > a["valor"]
            tendencia = "melhora" if subiu == FAIXAS[k][2] else "piora"
        out.append((a["nome"], a["texto"], b["texto"], tendencia))
    return out


def grafico_linhas(rotulos, series, largura=760, altura=280):
    """Geometria de um gráfico de linhas em SVG (sem dependências externas)."""
    esq, dir_, topo, base = 92, 16, 16, 34
    w, h = largura - esq - dir_, altura - topo - base
    valores = [float(v) for s in series for v in s["valores"] if v is not None]
    maximo = max(valores + [0]) or 1
    passo = _passo_eixo(maximo)
    teto = passo * max(1, -(-maximo // passo))
    n = len(rotulos)

    def x(i):
        return esq + (w / 2 if n == 1 else w * i / (n - 1))

    def y(v):
        return topo + h - h * float(v) / teto

    grade = []
    k = 0
    while k * passo <= teto + 1e-9:
        v = k * passo
        grade.append({"y": round(y(v), 1), "rotulo": _abreviar(v)})
        k += 1
    for s in series:
        s["pontos"] = [{"x": round(x(i), 1), "y": round(y(v), 1), "valor": brl(v), "rotulo": rotulos[i]}
                       for i, v in enumerate(s["valores"]) if v is not None]
        s["polyline"] = " ".join(f'{p["x"]},{p["y"]}' for p in s["pontos"])
    return {"largura": largura, "altura": altura, "esq": esq, "dir": largura - dir_, "base": topo + h,
            "grade": grade, "series": series,
            "eixo_x": [{"x": round(x(i), 1), "rotulo": r} for i, r in enumerate(rotulos)]}


def _passo_eixo(maximo, alvo=4):
    bruto = maximo / alvo
    mag = 10 ** (len(str(int(bruto))) - 1) if bruto >= 1 else 1
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


def _abreviar(v):
    for lim, suf in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(v) >= lim:
            return f"R$ {v / lim:.1f}".replace(".", ",").replace(",0", "") + suf
    return f"R$ {v:.0f}"


# ------------------------------------------------------------------ alertas
@dataclass
class Alerta:
    analise: object
    severidade: str   # "critico" | "atencao" | "info"
    tipo: str         # "inconsistencia" | "risco" | "rebaixamento" | "desatualizada"
    mensagem: str
    anterior: object = field(default=None)

    @property
    def cor(self):
        return {"critico": "danger", "atencao": "warning", "info": "secondary"}[self.severidade]

    @property
    def severidade_label(self):
        return {"critico": "Crítico", "atencao": "Atenção", "info": "Informativo"}[self.severidade]

    @property
    def tipo_label(self):
        return dict(TIPOS_ALERTA)[self.tipo]


ORDEM_SEVERIDADE = {"critico": 0, "atencao": 1, "info": 2}
TIPOS_ALERTA = [("inconsistencia", "Inconsistência de dados"), ("risco", "Risco financeiro"),
                ("rebaixamento", "Rebaixamento de nota"), ("desatualizada", "Análise desatualizada")]


def alertas_da_analise(a, anterior=None, hoje=None):
    hoje = hoje or timezone.localdate()
    ind = indicadores(a)
    out = []

    def add(sev, tipo, msg, ant=None):
        out.append(Alerta(a, sev, tipo, msg, ant))

    # inconsistências / indicadores zerados
    if not a.receita_bruta_12m:
        add("critico", "inconsistencia", "Receita bruta dos últimos 12 meses zerada.")
    if not a.divida_total:
        add("atencao", "inconsistencia", "Dívida consolidada zerada — confira se os débitos foram lançados.")
    if a.receita_bruta_12m and not a.custos_despesas_12m:
        add("atencao", "inconsistencia", "Há receita, mas custos e despesas estão zerados.")
    if a.bens_onerados > a.patrimonio_total:
        add("critico", "inconsistencia", "Bens onerados superam o patrimônio total informado.")
    if a.divida_total and a.divida_principal == 0:
        add("atencao", "inconsistencia", "Dívida sem valor principal (apenas multa/juros/encargos).")
    if a.passivo_circulante and a.ativo_circulante == 0:
        add("atencao", "inconsistencia", "Passivo circulante informado com ativo circulante zerado.")
    if a.disponibilidades < 0:
        add("atencao", "inconsistencia", "Saldo de caixa e bancos negativo.")

    # risco financeiro
    if a.situacao_irrecuperavel:
        add("critico", "risco", "Situação de irrecuperabilidade (art. 25) — rating D forçado.")
    end, poup, liq = ind["endividamento"], ind["poupanca"], ind["liquidez"]
    if end["valor"] is not None and end["valor"] > 3:
        add("critico", "risco", f"Endividamento muito alto: dívida equivale a {end['texto']} da receita anual.")
    if poup["valor"] is not None and poup["valor"] > 1:
        add("critico", "risco", f"Despesas superam as receitas (poupança corrente {poup['texto']}).")
    if liq["valor"] is not None and liq["valor"] < 1 and not liq.get("estimada"):
        add("atencao", "risco", f"Liquidez abaixo de 1 ({liq['texto']}): passivo circulante maior que o ativo.")
    if a.rating_pgfn and a.rating_real and abs(NIVEIS.index(a.rating_real) - NIVEIS.index(a.rating_pgfn)) >= 2:
        add("atencao", "inconsistencia",
            f"Divergência grande entre rating PGFN ({a.rating_pgfn}) e rating real ({a.rating_real}).")

    # rebaixamento de um ano para o outro
    if anterior and anterior.rating_real and a.rating_real:
        queda = NIVEIS.index(a.rating_real) - NIVEIS.index(anterior.rating_real)
        if queda >= 1:
            add("critico" if queda >= 2 else "atencao", "rebaixamento",
                f"Nota caiu de {anterior.rating_real} ({anterior.data_referencia:%Y}) para "
                f"{a.rating_real} ({a.data_referencia:%Y}) — {queda} nível(is).", anterior)

    if a.data_referencia < hoje - timedelta(days=365):
        add("info", "desatualizada", f"Última análise é de {a.data_referencia:%d/%m/%Y} (mais de 12 meses).")
    return out


def alertas(analises_qs, ano=None, hoje=None):
    """Avalia a análise mais recente de cada empresa (no ano, se informado) e compara
    com a análise mais recente do ano anterior para detectar rebaixamentos."""
    todas = list(analises_qs.select_related("empresa").order_by("-data_referencia", "-pk"))
    por_empresa = {}
    for a in todas:
        por_empresa.setdefault(a.empresa_id, []).append(a)
    saida = []
    for lst in por_empresa.values():
        candidatas = [a for a in lst if not ano or a.data_referencia.year == ano]
        if not candidatas:
            continue
        atual = candidatas[0]
        anterior = next((a for a in lst if a.data_referencia.year < atual.data_referencia.year), None)
        saida += alertas_da_analise(atual, anterior, hoje)
    saida.sort(key=lambda x: (ORDEM_SEVERIDADE[x.severidade], x.analise.empresa.razao_social))
    return saida


# ------------------------------------------------------------------ carteira por serviço
def por_servico(empresas, servico_id=None):
    """Agrupa as empresas por serviço contratado/oferecido. Uma empresa com dois serviços aparece nos dois grupos.

    Com `servico_id`, mostra só o grupo daquele serviço; sem ele, inclui "Sem serviço definido" no fim.
    """
    grupos = {}
    sem = []
    for e in empresas:
        servicos = [p for p in e.servicos.all() if not servico_id or p.pk == servico_id]
        if not servicos and not servico_id:
            sem.append(e)
        for p in servicos:
            grupos.setdefault(p.pk, {"produto": p, "nome": p.nome, "area": p.get_area_display(),
                                     "empresas": []})["empresas"].append(e)
    saida = sorted(grupos.values(), key=lambda g: (-len(g["empresas"]), g["nome"]))
    if sem:
        saida.append({"produto": None, "nome": "Sem serviço definido", "area": "", "empresas": sem})
    for g in saida:
        g["ratings"] = {r: sum(1 for e in g["empresas"] if e.ultima and e.ultima.rating_real == r) for r in NIVEIS}
        g["divida"] = sum((e.ultima.divida_total for e in g["empresas"] if e.ultima), Decimal("0"))
    return saida


def contagem(itens, chave):
    """[(rótulo, quantidade, %)] do maior para o menor."""
    cont = {}
    for i in itens:
        k = chave(i)
        cont[k] = cont.get(k, 0) + 1
    total = len(itens)
    return [(k, n, round(100 * n / total) if total else 0)
            for k, n in sorted(cont.items(), key=lambda x: (-x[1], x[0]))]
