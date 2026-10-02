"""
Motor de cálculo da CAPAG real (modelo de simulação para pedido de revisão na PGFN).

Lógica (Portaria PGFN 6.757/2022, art. 21: capacidade de pagar a dívida integral em 5 anos):

    resultado anual livre = receita bruta − custos/despesas − parcelas de financiamento − outras dívidas
    geração futura        = max(0, resultado anual livre) × horizonte (anos)
    patrimônio livre      = max(0, bens − bens onerados) × % de realização
    CAPAG real            = geração futura + patrimônio livre + caixa

    Rating = relação CAPAG ÷ dívida total, com os fatores configuráveis em Parâmetros.
    Situação de irrecuperabilidade (art. 25) força o rating D.

    Desconto (somente C e D): nunca sobre o principal e limitado ao % máximo da dívida
    (65% geral / 70% ME-EPP). O desconto estimado é o necessário para a dívida caber
    na capacidade, respeitando esses limites.
"""
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def q(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def classificar(capag, divida, p, irrecuperavel=False):
    if irrecuperavel:
        return "D"
    if divida <= 0:
        return "A"
    razao = Decimal(capag) / Decimal(divida)
    if razao >= p.fator_rating_a:
        return "A"
    if razao >= p.fator_rating_b:
        return "B"
    if razao >= p.fator_rating_c:
        return "C"
    return "D"


def calcular(a, p=None):
    from .models import Parametro
    p = p or Parametro.atual()
    me_epp = a.empresa.me_epp

    total = a.divida_total
    a.resultado_anual_livre = q(a.receita_bruta_12m - a.custos_despesas_12m
                                - a.parcelas_financiamento_12m - a.outras_dividas_12m)
    a.geracao_futura = q(max(ZERO, a.resultado_anual_livre) * p.horizonte_anos)
    a.patrimonio_livre = q(max(ZERO, a.patrimonio_total - a.bens_onerados) * p.percentual_realizacao_bens / 100)
    a.capag_real = q(a.geracao_futura + a.patrimonio_livre + max(ZERO, a.disponibilidades))

    a.rating_real = classificar(a.capag_real, total, p, a.situacao_irrecuperavel)
    a.rating_presumido_calc = classificar(a.capag_presumida, total, p) if a.capag_presumida else ""

    desconto = ZERO
    if a.rating_real in ("C", "D") and total > 0:
        pct = p.desconto_max_me_epp if me_epp else p.desconto_max_geral
        limite = total * pct / 100
        acrescimos = total - a.divida_principal
        necessario = max(ZERO, total - a.capag_real)
        desconto = min(limite, acrescimos, necessario)
    a.desconto_estimado = q(max(ZERO, desconto))
    a.valor_apos_desconto = q(total - a.desconto_estimado)
    a.prazo_maximo = p.prazo_max_me_epp if me_epp else p.prazo_max_geral
    a.parcela_estimada = q(a.valor_apos_desconto / a.prazo_maximo) if a.prazo_maximo else ZERO

    a.parametros_usados = {
        "horizonte_anos": p.horizonte_anos,
        "fator_rating_a": str(p.fator_rating_a),
        "fator_rating_b": str(p.fator_rating_b),
        "fator_rating_c": str(p.fator_rating_c),
        "percentual_realizacao_bens": str(p.percentual_realizacao_bens),
        "desconto_max": str(p.desconto_max_me_epp if me_epp else p.desconto_max_geral),
        "prazo_max": a.prazo_maximo,
    }
    return a


def quadro_comparativo(a):
    """Linhas do quadro comparativo usado na tela, no PDF e nas mensagens."""
    return [
        ("Dívida ativa consolidada", a.divida_total, a.divida_total),
        ("Capacidade de pagamento (5 anos)", a.capag_presumida, a.capag_real),
        ("Relação CAPAG ÷ dívida", _razao(a.capag_presumida, a.divida_total), _razao(a.capag_real, a.divida_total)),
        ("Rating", a.rating_pgfn or "—", a.rating_real),
    ]


def _razao(capag, divida):
    if not divida:
        return "—"
    return f"{(Decimal(capag) / Decimal(divida)):.2f}×".replace(".", ",")


def brl(v):
    try:
        v = Decimal(v)
    except Exception:
        return v
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def texto_resumo(a):
    """Resumo em texto simples (WhatsApp / corpo do e-mail)."""
    e = a.empresa
    linhas = [
        f"*Análise de CAPAG – {e.razao_social}*",
        f"CNPJ: {e.cnpj}",
        f"Data de referência: {a.data_referencia:%d/%m/%Y}",
        "",
        f"Dívida ativa consolidada: {brl(a.divida_total)}",
        f"CAPAG presumida (PGFN): {brl(a.capag_presumida)} – Rating {a.rating_pgfn or '—'}",
        f"CAPAG real apurada: {brl(a.capag_real)} – Rating {a.rating_real}",
    ]
    if a.desconto_estimado:
        linhas += [
            f"Desconto estimado na transação: {brl(a.desconto_estimado)}",
            f"Valor após desconto: {brl(a.valor_apos_desconto)} em até {a.prazo_maximo} meses "
            f"(≈ {brl(a.parcela_estimada)}/mês)",
        ]
    if a.prazo_revisao:
        linhas.append(f"Prazo para pedido de revisão: {a.prazo_revisao:%d/%m/%Y}")
    linhas += ["", "Simulação para apoio ao pedido de revisão. Valores sujeitos à análise da PGFN."]
    return "\n".join(linhas)
