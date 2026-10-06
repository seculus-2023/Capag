"""PDF da proposta de prestação de serviços (ReportLab), no mesmo padrão visual do relatório CAPAG."""
from io import BytesIO

from django.conf import settings
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from core.pdf import _estilos, _tabela
from core.services import brl, quadro_comparativo

from .models import pct


def _p(texto):
    return (texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _forma(item):
    partes = []
    if item.cobranca == "MENSAL":
        partes.append(f"{brl(item.valor)} por mês")
    elif item.valor:
        partes.append(brl(item.valor))
    if item.percentual_exito:
        partes.append(f"{pct(item.percentual_exito)}% do benefício obtido")
    return " + ".join(partes) or "—"


def gerar_pdf(proposta):
    buf = BytesIO()
    s = _estilos()
    c, op = proposta.contato, proposta.oportunidade
    itens = list(proposta.itens.select_related("produto"))
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Proposta {proposta.numero} – {c.nome}", author=settings.ESCRITORIO_NOME)
    escritorio = settings.ESCRITORIO_NOME + (f" · OAB {settings.ESCRITORIO_OAB}" if settings.ESCRITORIO_OAB else "")
    el = [
        Paragraph("PROPOSTA DE PRESTAÇÃO DE SERVIÇOS", s["Tit"]),
        Paragraph(f"{_p(escritorio)} · Proposta nº {proposta.numero}", s["Sub"]),
        Spacer(1, 10),
        Paragraph("1. Cliente", s["H"]),
        _tabela([
            ["Nome / razão social", Paragraph(_p(c.nome), s["Cel"])],
            ["CPF / CNPJ", c.documento or "—"],
            ["Assunto", Paragraph(_p(op.titulo), s["Cel"])],
            ["Data", (timezone.localtime(proposta.criado_em).date() if proposta.criado_em else timezone.localdate()).strftime("%d/%m/%Y")],
            ["Válida até", proposta.validade.strftime("%d/%m/%Y")],
        ], [5 * cm, 12 * cm], cab=False),
    ]

    n = 2
    a = proposta.analise
    if a:
        el.append(Paragraph(f"{n}. Diagnóstico – capacidade de pagamento (CAPAG)", s["H"]))
        linhas = [["Indicador", "Presumido pela PGFN", "Real apurado"]]
        for nome, pres, real in quadro_comparativo(a):
            fmt = brl if nome not in ("Rating", "Relação CAPAG ÷ dívida") else str
            linhas.append([nome, fmt(pres), fmt(real)])
        el.append(_tabela(linhas, [7 * cm, 5 * cm, 5 * cm]))
        if a.rating_real in ("C", "D") and a.desconto_estimado:
            el.append(Paragraph(
                f"Simulação com a CAPAG real: desconto estimado de {brl(a.desconto_estimado)}, em até {a.prazo_maximo} "
                f"meses. Valores de simulação, sujeitos à análise da PGFN.", s["Nota"]))
        n += 1

    el.append(Paragraph(f"{n}. Serviços", s["H"]))
    for i in itens:
        el.append(Paragraph(f"<b>{_p(i.descricao)}</b> – prazo estimado de {i.produto.prazo_dias} dias", s["J"]))
        el.append(Paragraph(_p(i.produto.escopo), s["J"]))
        el.append(Spacer(1, 4))
    n += 1

    el.append(Paragraph(f"{n}. Honorários", s["H"]))
    linhas = [["Serviço", "Honorários"]] + [[Paragraph(_p(i.descricao), s["Cel"]), _forma(i)] for i in itens]
    if proposta.total_fixo:
        parc = f" em {proposta.parcelas}× de {brl(proposta.total_fixo / proposta.parcelas)}" if proposta.parcelas > 1 else ""
        linhas.append(["Total dos valores fixos" + parc, brl(proposta.total_fixo)])
    if proposta.total_mensal:
        linhas.append([f"Mensalidade ({proposta.meses_mensalidade} meses)", f"{brl(proposta.total_mensal)} por mês"])
    el.append(_tabela(linhas, [11 * cm, 6 * cm]))
    n += 1

    condicoes = []
    if proposta.primeiro_vencimento:
        condicoes.append(f"Primeiro vencimento em {proposta.primeiro_vencimento:%d/%m/%Y}.")
    if proposta.tem_exito:
        condicoes.append("Os honorários de êxito são devidos somente sobre o benefício efetivamente obtido.")
    if proposta.condicoes:
        condicoes.append(proposta.condicoes)
    if condicoes:
        el += [Paragraph(f"{n}. Condições", s["H"]), Paragraph(_p("\n".join(condicoes)), s["J"])]
        n += 1

    docs = []
    for i in itens:
        docs += [d for d in i.produto.lista_documentos if d not in docs]
    if docs:
        el += [Paragraph(f"{n}. Documentos necessários", s["H"]),
               Paragraph("<br/>".join(f"• {_p(d)}" for d in docs), s["J"])]

    el += [Spacer(1, 16), Paragraph(
        "Proposta individual e confidencial, elaborada a pedido do cliente. A atuação é de meio e não constitui "
        "promessa de resultado. A contratação se formaliza com a assinatura do contrato de prestação de serviços. "
        f"Gerado em {timezone.localtime():%d/%m/%Y %H:%M}.", s["Nota"])]
    doc.build(el)
    return buf.getvalue()


def nome_arquivo(proposta):
    return f"Proposta_{proposta.numero.replace('/', '-')}.pdf"
