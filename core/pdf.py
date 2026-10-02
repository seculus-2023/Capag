"""Relatório PDF da análise de CAPAG (ReportLab)."""
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .services import brl, quadro_comparativo

AZUL = colors.HexColor("#1F4E79")
CINZA = colors.HexColor("#F2F2F2")
RATING_COR = {"A": "#2E7D32", "B": "#558B2F", "C": "#EF6C00", "D": "#C62828"}


def _estilos():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("Tit", parent=s["Title"], fontSize=15, textColor=AZUL, spaceAfter=4))
    s.add(ParagraphStyle("Sub", parent=s["Normal"], alignment=TA_CENTER, textColor=colors.grey, fontSize=9))
    s.add(ParagraphStyle("H", parent=s["Heading3"], textColor=AZUL, spaceBefore=10, spaceAfter=4))
    s.add(ParagraphStyle("J", parent=s["Normal"], alignment=TA_JUSTIFY, fontSize=9.5, leading=13))
    s.add(ParagraphStyle("Cel", parent=s["Normal"], fontSize=9, leading=11))
    s.add(ParagraphStyle("Nota", parent=s["Normal"], fontSize=7.5, textColor=colors.grey, leading=9.5))
    return s


def _tabela(dados, larguras, cab=True):
    t = Table(dados, colWidths=larguras)
    estilo = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0C4DE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if cab:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                   ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (0, 0), (-1, 0), "CENTER")]
    for i in range(1 if cab else 0, len(dados)):
        if i % 2 == 0:
            estilo.append(("BACKGROUND", (0, i), (-1, i), CINZA))
    t.setStyle(TableStyle(estilo))
    return t


def _pct(v):
    try:
        return f"{float(v):g}".replace(".", ",")
    except (TypeError, ValueError):
        return v


def gerar_pdf(a):
    buf = BytesIO()
    e = a.empresa
    s = _estilos()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"CAPAG {e.razao_social}", author="Sistema CAPAG")
    el = [
        Paragraph("ANÁLISE DE CAPACIDADE DE PAGAMENTO – CAPAG", s["Tit"]),
        Paragraph("Transação tributária na Dívida Ativa da União (PGFN) – simulação para pedido de revisão", s["Sub"]),
        Spacer(1, 10),
        Paragraph("1. Contribuinte", s["H"]),
        _tabela([
            ["Razão social", Paragraph(e.razao_social, s["Cel"])],
            ["CNPJ", e.cnpj],
            ["Porte", e.get_porte_display()],
            ["Município/UF", f"{e.municipio}/{e.uf}" if e.municipio else "—"],
            ["Data de referência", a.data_referencia.strftime("%d/%m/%Y")],
            ["Requerimento REGULARIZE", a.numero_requerimento or "—"],
            ["Prazo para revisão", a.prazo_revisao.strftime("%d/%m/%Y") if a.prazo_revisao else "—"],
        ], [5 * cm, 12 * cm], cab=False),
    ]

    el += [Paragraph("2. Quadro comparativo", s["H"])]
    linhas = [["Indicador", "Presumido pela PGFN", "Real apurado"]]
    for nome, pres, real in quadro_comparativo(a):
        fmt = (lambda v: brl(v)) if nome not in ("Rating", "Relação CAPAG ÷ dívida") else str
        linhas.append([nome, fmt(pres), fmt(real)])
    t = _tabela(linhas, [7 * cm, 5 * cm, 5 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (2, -1), (2, -1), colors.HexColor(RATING_COR.get(a.rating_real, "#000000"))),
    ]))
    el.append(t)

    el += [Paragraph("3. Composição da dívida", s["H"]), _tabela([
        ["Item", "Valor"],
        ["Principal", brl(a.divida_principal)],
        ["Multa", brl(a.divida_multa)],
        ["Juros", brl(a.divida_juros)],
        ["Encargos legais", brl(a.divida_encargos)],
        ["Total", brl(a.divida_total)],
    ], [12 * cm, 5 * cm])]

    pu = a.parametros_usados or {}
    el += [Paragraph("4. Memória de cálculo da CAPAG real", s["H"]), _tabela([
        ["Item", "Valor"],
        ["(+) Receita bruta – últimos 12 meses", brl(a.receita_bruta_12m)],
        ["(−) Custos e despesas operacionais", brl(a.custos_despesas_12m)],
        ["(−) Parcelas de financiamentos", brl(a.parcelas_financiamento_12m)],
        ["(−) Outras dívidas a pagar no período", brl(a.outras_dividas_12m)],
        ["(=) Resultado anual livre", brl(a.resultado_anual_livre)],
        [f"Geração futura ({pu.get('horizonte_anos', 5)} anos)", brl(a.geracao_futura)],
        ["Patrimônio em bens", brl(a.patrimonio_total)],
        ["(−) Bens alienados / onerados", brl(a.bens_onerados)],
        [f"Patrimônio livre realizável ({_pct(pu.get('percentual_realizacao_bens', '100'))}%)", brl(a.patrimonio_livre)],
        ["Caixa e bancos", brl(a.disponibilidades)],
        ["CAPAG real (geração futura + patrimônio livre + caixa)", brl(a.capag_real)],
    ], [12 * cm, 5 * cm])]

    if a.rating_real in ("C", "D"):
        el += [Paragraph("5. Estimativa de transação", s["H"]), _tabela([
            ["Item", "Valor"],
            [f"Desconto estimado (limite {_pct(pu.get('desconto_max', ''))}% e sem reduzir o principal)", brl(a.desconto_estimado)],
            ["Valor após desconto", brl(a.valor_apos_desconto)],
            ["Prazo máximo", f"{a.prazo_maximo} meses"],
            ["Parcela estimada", brl(a.parcela_estimada)],
        ], [12 * cm, 5 * cm])]
    else:
        el += [Paragraph("5. Estimativa de transação", s["H"]),
               Paragraph(f"Com rating {a.rating_real}, a dívida é considerada recuperável e, em regra, "
                         "não há descontos na transação.", s["J"])]

    if a.justificativa:
        el += [Paragraph("6. Justificativa", s["H"]),
               Paragraph(a.justificativa.replace("\n", "<br/>"), s["J"])]

    el += [Spacer(1, 16), Paragraph(
        "Rating: A = CAPAG ≥ {a}× dívida; B ≥ {b}×; C ≥ {c}×; D abaixo disso ou situação de irrecuperabilidade "
        "(art. 25 da Portaria PGFN 6.757/2022). Documento de simulação, elaborado a partir das informações "
        "prestadas pelo contribuinte, para subsidiar o pedido de revisão da capacidade de pagamento. "
        "Os valores finais dependem da análise da PGFN. Gerado em {d}.".format(
            a=_pct(pu.get("fator_rating_a", "2")), b=_pct(pu.get("fator_rating_b", "1")), c=_pct(pu.get("fator_rating_c", "0.5")),
            d=timezone.localtime().strftime("%d/%m/%Y %H:%M")), s["Nota"])]

    doc.build(el)
    return buf.getvalue()


def gerar_pdf_composicao(a):
    """Relatório de composição dos indicadores (auditoria do cálculo da nota)."""
    from .relatorios import indicadores, passos_rating

    buf = BytesIO()
    e = a.empresa
    s = _estilos()
    ind, passos = indicadores(a), passos_rating(a)
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Composição CAPAG {e.razao_social}", author="Sistema CAPAG")
    el = [
        Paragraph("COMPOSIÇÃO DOS INDICADORES – CAPAG", s["Tit"]),
        Paragraph(f"{e.razao_social} · CNPJ {e.cnpj} · referência {a.data_referencia:%d/%m/%Y}", s["Sub"]),
        Spacer(1, 10),
        Paragraph("1. Rácios financeiros", s["H"]),
    ]
    linhas = [["Indicador / componente", "Valor"]]
    for i in ind.values():
        linhas += [
            [Paragraph(f"<b>{i['nome']}</b> = {i['formula']}", s["Cel"]), ""],
            [f"   {i['num_label']}", brl(i["num"])],
            [f"   ÷ {i['den_label']}", brl(i["den"])],
            [f"   = Resultado ({i['situacao_label']})", i["texto"]],
        ]
    t = _tabela(linhas, [12 * cm, 5 * cm])
    extra = []
    for n, i in enumerate(ind.values()):
        base = 1 + n * 4
        extra += [("SPAN", (0, base), (1, base)), ("BACKGROUND", (0, base), (-1, base), colors.HexColor("#E8EEF5")),
                  ("FONTNAME", (0, base + 3), (-1, base + 3), "Helvetica-Bold")]
    t.setStyle(TableStyle(extra))
    el.append(t)
    el.append(Paragraph("Faixas de referência: " + " | ".join(f"{i['nome']}: {i['referencia']}" for i in ind.values()),
                        s["Nota"]))

    el += [Paragraph("2. Cálculo da nota (rating da CAPAG real)", s["H"]), _tabela([
        ["Passo", "Valor"],
        ["(+) Receita bruta 12 meses", brl(a.receita_bruta_12m)],
        ["(−) Custos, parcelas e outras dívidas", brl(a.custos_despesas_12m + a.parcelas_financiamento_12m
                                                     + a.outras_dividas_12m)],
        ["(=) Resultado anual livre", brl(a.resultado_anual_livre)],
        [f"Geração futura (resultado positivo × {passos['horizonte']} anos)", brl(a.geracao_futura)],
        [f"Patrimônio livre ((bens − onerados) × {_pct(passos['realizacao'])}%)", brl(a.patrimonio_livre)],
        ["Caixa e bancos", brl(a.disponibilidades)],
        ["CAPAG real", brl(a.capag_real)],
        ["Dívida consolidada", brl(a.divida_total)],
        ["Relação CAPAG ÷ dívida", passos["razao_txt"]],
        ["Nota obtida", a.rating_real + (" (irrecuperabilidade – art. 25)" if passos["irrecuperavel"] else "")],
    ], [12 * cm, 5 * cm])]
    el += [Paragraph("Faixas da nota: " + "; ".join(f"{r} {txt}" for r, txt in passos["faixas"]) + ".", s["Nota"])]
    el += [Spacer(1, 12), Paragraph(
        "Os rácios de endividamento, poupança corrente e liquidez são indicadores de apoio; a nota é definida "
        "pela relação CAPAG ÷ dívida. Gerado em {}.".format(timezone.localtime().strftime("%d/%m/%Y %H:%M")), s["Nota"])]
    doc.build(el)
    return buf.getvalue()


def nome_arquivo(a):
    cnpj = "".join(ch for ch in a.empresa.cnpj if ch.isdigit())
    return f"CAPAG_{cnpj}_{a.data_referencia:%Y%m%d}.pdf"
