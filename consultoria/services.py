"""Regras da consultoria: envio, aceite (projeto + honorários no financeiro) e indicadores."""
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMessage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.envio import link_wame
from crm.models import Interacao
from juridico.models import Lancamento
from juridico.services import somar_meses

from .models import Etapa, Projeto, pct

SALT = "consultoria-proposta-pdf"


# ------------------------------------------------------------------ link público assinado do PDF
def link_publico(proposta):
    token = signing.TimestampSigner(salt=SALT).sign(str(proposta.token))
    return settings.SITE_URL + reverse("consultoria:pdf_publico", args=[token])


def validar_token(token):
    """Devolve o UUID da proposta ou levanta signing.BadSignature / SignatureExpired."""
    return signing.TimestampSigner(salt=SALT).unsign(token, max_age=timedelta(days=settings.LINK_PDF_VALIDADE_DIAS))


# ------------------------------------------------------------------ envio
def mensagem_padrao(proposta):
    c = proposta.contato
    return (f"Olá, {c.primeiro_nome}! Conforme conversamos, segue a proposta de prestação de serviços "
            f"nº {proposta.numero}, válida até {proposta.validade:%d/%m/%Y}. Fico à disposição para esclarecer "
            f"qualquer ponto.\n\n{settings.ESCRITORIO_NOME}")


def enviar_email(proposta, destino, mensagem, usuario):
    """Envia o PDF por e-mail. Devolve a mensagem de erro ou "" quando deu certo."""
    from .pdf import gerar_pdf, nome_arquivo

    try:
        email = EmailMessage(f"Proposta de prestação de serviços nº {proposta.numero}", mensagem,
                             settings.DEFAULT_FROM_EMAIL,
                             [d.strip() for d in destino.replace(";", ",").split(",") if d.strip()])
        email.attach(nome_arquivo(proposta), gerar_pdf(proposta), "application/pdf")
        email.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 – qualquer falha de SMTP volta para a tela
        return str(exc)
    marcar_enviada(proposta, usuario, "EMAIL", f"Proposta nº {proposta.numero} enviada por e-mail para {destino}.")
    return ""


def link_whatsapp(proposta, numero, mensagem, usuario):
    """Registra o envio e devolve o link wa.me com a mensagem e o link seguro do PDF."""
    marcar_enviada(proposta, usuario, "WHATSAPP", f"Proposta nº {proposta.numero} enviada pelo WhatsApp.")
    return link_wame(numero, f"{mensagem}\n\nProposta em PDF: {link_publico(proposta)}")


def marcar_enviada(proposta, usuario, tipo, descricao):
    """A proposta sai do rascunho e o atendimento vai para "Proposta enviada" com o valor estimado."""
    hoje = timezone.localdate()
    if proposta.status == "RASCUNHO":
        proposta.status, proposta.enviada_em = "ENVIADA", hoje
        proposta.save(update_fields=["status", "enviada_em", "atualizado_em"])
    op = proposta.oportunidade
    if op.aberta:
        op.etapa, op.proposta_enviada_em, op.valor_estimado = "PROPOSTA", hoje, proposta.total_estimado
        op.save(update_fields=["etapa", "proposta_enviada_em", "valor_estimado", "atualizado_em"])
    Interacao.objects.create(oportunidade=op, tipo=tipo, descricao=descricao, usuario=usuario)


# ------------------------------------------------------------------ aceite
def _parcelas(total, n):
    """Divide em n parcelas; os centavos que sobram ficam na última."""
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return [base] * (n - 1) + [total - base * (n - 1)]


@transaction.atomic
def aceitar(proposta, usuario, data=None):
    """Proposta aceita: abre o projeto (entregas + documentos) e lança os honorários no financeiro."""
    data = data or timezone.localdate()
    itens = list(proposta.itens.select_related("produto"))
    proposta.status, proposta.respondida_em, proposta.motivo_recusa = "ACEITA", data, ""
    proposta.save(update_fields=["status", "respondida_em", "motivo_recusa", "atualizado_em"])

    op, cliente = proposta.oportunidade, proposta.contato
    exito = [f"{i.descricao}: {pct(i.percentual_exito)}% sobre o benefício obtido" for i in itens if i.percentual_exito]
    projeto = Projeto.objects.create(
        proposta=proposta, cliente=cliente, titulo=op.titulo, responsavel=op.responsavel or usuario, inicio=data,
        prazo=data + timedelta(days=max((i.produto.prazo_dias for i in itens), default=30)),
        observacoes=("Honorários de êxito (lançar no financeiro quando apurado):\n" + "\n".join(exito)) if exito else "")

    ordem, vistos = 0, set()
    for i in itens:
        for doc in i.produto.lista_documentos:
            if doc.lower() not in vistos:
                vistos.add(doc.lower())
                ordem += 1
                Etapa.objects.create(projeto=projeto, tipo="DOCUMENTO", descricao=f"Receber: {doc}"[:250], ordem=ordem)
    for i in itens:
        for entrega in i.produto.lista_entregas:
            ordem += 1
            descricao = f"{entrega} ({i.descricao})" if len(itens) > 1 else entrega
            Etapa.objects.create(projeto=projeto, tipo="ENTREGA", descricao=descricao[:250], ordem=ordem)

    primeiro = proposta.primeiro_vencimento or data + timedelta(days=30)
    base = f"Consultoria – proposta {proposta.numero}"
    comum = {"cliente": cliente, "natureza": "RECEBER", "criado_por": usuario}
    if proposta.total_fixo > 0:
        n = max(1, proposta.parcelas)
        for k, valor in enumerate(_parcelas(proposta.total_fixo, n)):
            Lancamento.objects.create(categoria="CONTRATUAL", valor=valor, vencimento=somar_meses(primeiro, k),
                                      descricao=(f"{base} ({k + 1}/{n})" if n > 1 else base)[:200], **comum)
    if proposta.total_mensal > 0:
        n = max(1, proposta.meses_mensalidade)
        for k in range(n):
            Lancamento.objects.create(categoria="MENSAL", valor=proposta.total_mensal,
                                      vencimento=somar_meses(primeiro, k),
                                      descricao=f"{base} – mensalidade ({k + 1}/{n})"[:200], **comum)

    Interacao.objects.create(oportunidade=op, tipo="NOTA", usuario=usuario,
                             descricao=f"Proposta nº {proposta.numero} aceita em {data:%d/%m/%Y}. Projeto aberto.")
    return projeto


def recusar(proposta, usuario, motivo=""):
    proposta.status, proposta.respondida_em, proposta.motivo_recusa = "RECUSADA", timezone.localdate(), motivo[:250]
    proposta.save(update_fields=["status", "respondida_em", "motivo_recusa", "atualizado_em"])
    Interacao.objects.create(oportunidade=proposta.oportunidade, tipo="NOTA", usuario=usuario,
                             descricao=f"Proposta nº {proposta.numero} recusada.{f' Motivo: {motivo}' if motivo else ''}")


# ------------------------------------------------------------------ indicadores
def indicadores(propostas):
    """Taxa de aceite, ticket médio, receita por produto e por área (propostas do período)."""
    propostas = list(propostas.select_related("oportunidade", "projeto").prefetch_related("itens__produto"))
    por_status = defaultdict(int)
    for p in propostas:
        por_status[p.status] += 1
    aceitas = [p for p in propostas if p.status == "ACEITA"]
    decididas = len(aceitas) + por_status["RECUSADA"]
    produtos = defaultdict(lambda: {"propostas": 0, "vendas": 0, "receita": Decimal("0.00")})
    areas = defaultdict(lambda: Decimal("0.00"))
    for p in propostas:
        for i in p.itens.all():
            linha = produtos[i.produto.nome]
            linha["propostas"] += 1
            if p.status == "ACEITA":
                valor = i.valor * (p.meses_mensalidade if i.cobranca == "MENSAL" else 1)
                linha["vendas"] += 1
                linha["receita"] += valor
                areas[i.produto.get_area_display()] += valor
    receita = sum((p.total_estimado for p in aceitas), Decimal("0.00"))
    return {
        "total": len(propostas),
        "por_status": dict(por_status),
        "taxa_aceite": round(100 * len(aceitas) / decididas) if decididas else None,
        "receita": receita,
        "ticket_medio": receita / len(aceitas) if aceitas else Decimal("0.00"),
        "recorrente": sum((p.total_mensal for p in aceitas if hasattr(p, "projeto") and p.projeto.status == "ANDAMENTO"),
                          Decimal("0.00")),
        "produtos": sorted(produtos.items(), key=lambda kv: (-kv[1]["receita"], -kv[1]["propostas"])),
        "areas": sorted(areas.items(), key=lambda kv: -kv[1]),
    }
