"""Catálogo inicial da consultoria. Os valores ficam zerados: o sócio define os preços em Consultoria → Catálogo."""
from django.db import migrations

DOCS_EMPRESA = "Contrato social e última alteração\nCartão CNPJ"
DOCS_FINANCEIROS = ("Balanço e DRE dos dois últimos exercícios\nBalancete dos últimos 12 meses\n"
                    "Relação de bens, com indicação dos alienados ou penhorados\n"
                    "Extrato das dívidas bancárias e dos financiamentos")

PRODUTOS = [
    {"nome": "Diagnóstico de CAPAG", "area": "TRIB_FED", "cobranca": "FIXO", "prazo_dias": 15, "usa_capag": True,
     "escopo": "Levantamento da dívida ativa da União, cálculo da capacidade de pagamento real da empresa e "
               "comparação com a CAPAG presumida pela PGFN, com relatório e simulação das condições de transação.",
     "entregas": "Levantamento da dívida no REGULARIZE\nAnálise dos demonstrativos financeiros\n"
                 "Cálculo da CAPAG real\nRelatório de diagnóstico ao cliente",
     "documentos": f"{DOCS_EMPRESA}\n{DOCS_FINANCEIROS}\nAcesso ao REGULARIZE (procuração digital)"},
    {"nome": "Pedido de revisão de CAPAG", "area": "TRIB_FED", "cobranca": "FIXO", "prazo_dias": 30, "usa_capag": True,
     "escopo": "Elaboração e protocolo do pedido de revisão da capacidade de pagamento junto à PGFN, com "
               "fundamentação e documentos, e acompanhamento até a decisão.",
     "entregas": "Fundamentação do pedido\nMontagem do dossiê de documentos\nProtocolo no REGULARIZE\n"
                 "Acompanhamento até a decisão",
     "documentos": f"{DOCS_EMPRESA}\n{DOCS_FINANCEIROS}\nNotificação da CAPAG presumida"},
    {"nome": "Transação tributária PGFN", "area": "TRIB_FED", "cobranca": "FIXO", "prazo_dias": 60, "usa_capag": True,
     "escopo": "Análise das modalidades de transação disponíveis, simulação, adesão ou negociação individual com a "
               "PGFN e acompanhamento da formalização do acordo.",
     "entregas": "Simulação das modalidades de transação\nReunião de apresentação ao cliente\n"
                 "Adesão / proposta de transação individual\nAcompanhamento da formalização",
     "documentos": f"{DOCS_EMPRESA}\n{DOCS_FINANCEIROS}\nAcesso ao REGULARIZE (procuração digital)"},
    {"nome": "Planejamento tributário", "area": "TRIB_FED", "cobranca": "FIXO", "prazo_dias": 45,
     "escopo": "Estudo do enquadramento tributário e das operações da empresa para identificar alternativas lícitas "
               "de redução da carga tributária, com parecer conclusivo.",
     "entregas": "Levantamento das operações e do regime tributário\nSimulação dos cenários\nParecer conclusivo",
     "documentos": f"{DOCS_EMPRESA}\nApurações fiscais dos últimos 12 meses\nBalanço e DRE do último exercício"},
    {"nome": "Recuperação de créditos de ICMS", "area": "TRIB_EST", "cobranca": "EXITO", "prazo_dias": 90,
     "escopo": "Levantamento e recuperação de créditos de ICMS pagos indevidamente ou a maior, com o pedido "
               "administrativo correspondente.",
     "entregas": "Levantamento dos créditos\nRelatório de créditos identificados\nPedido administrativo na Sefaz",
     "documentos": f"{DOCS_EMPRESA}\nArquivos SPED Fiscal dos últimos 5 anos\nGuias de recolhimento do ICMS"},
    {"nome": "Defesa em auto de infração de ICMS", "area": "TRIB_EST", "cobranca": "FIXO", "prazo_dias": 30,
     "escopo": "Análise do auto de infração e elaboração da impugnação administrativa, com acompanhamento em "
               "primeira instância.",
     "entregas": "Análise do auto de infração\nImpugnação administrativa\nAcompanhamento do julgamento",
     "documentos": f"{DOCS_EMPRESA}\nCópia integral do auto de infração\nNotas fiscais e livros do período autuado"},
    {"nome": "Consultoria em licenciamento ambiental", "area": "AMBIENTAL", "cobranca": "FIXO", "prazo_dias": 60,
     "escopo": "Orientação jurídica no processo de licenciamento ambiental, análise das condicionantes e "
               "acompanhamento junto ao órgão ambiental.",
     "entregas": "Análise da atividade e do enquadramento\nChecklist de exigências do órgão ambiental\n"
                 "Acompanhamento do processo de licenciamento",
     "documentos": f"{DOCS_EMPRESA}\nLicenças e protocolos anteriores\nDescrição da atividade e do local"},
    {"nome": "Defesa em auto de infração ambiental", "area": "AMBIENTAL", "cobranca": "FIXO", "prazo_dias": 30,
     "escopo": "Defesa administrativa contra auto de infração ambiental (Ibama ou órgão estadual), com análise "
               "da possibilidade de conversão da multa.",
     "entregas": "Análise do auto de infração\nDefesa administrativa\nAcompanhamento do julgamento",
     "documentos": f"{DOCS_EMPRESA}\nCópia do auto de infração e do relatório de fiscalização"},
    {"nome": "Assessoria tributária mensal", "area": "TRIB_FED", "cobranca": "MENSAL", "prazo_dias": 30,
     "escopo": "Atendimento a consultas tributárias do dia a dia, acompanhamento da situação fiscal da empresa "
               "(certidões, débitos e parcelamentos) e alertas sobre mudanças na legislação.",
     "entregas": "Reunião inicial de alinhamento\nDiagnóstico da situação fiscal\nRotina mensal de acompanhamento",
     "documentos": f"{DOCS_EMPRESA}\nCertidões negativas atuais"},
    {"nome": "Parecer jurídico", "area": "TRIB_FED", "cobranca": "FIXO", "prazo_dias": 20,
     "escopo": "Parecer escrito sobre questão tributária ou ambiental específica apresentada pelo cliente.",
     "entregas": "Estudo da questão\nParecer escrito",
     "documentos": "Documentos relacionados à questão"},
]


def criar(apps, schema_editor):
    Produto = apps.get_model("consultoria", "Produto")
    if not Produto.objects.exists():
        Produto.objects.bulk_create(Produto(**p) for p in PRODUTOS)


class Migration(migrations.Migration):
    dependencies = [("consultoria", "0001_initial")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
