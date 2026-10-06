from django import forms
from django.contrib import messages
from django.core import signing
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.perfis import exige, pode
from core.services import brl
from crm.models import AREAS, Oportunidade

from . import services
from .forms import ItemForm, ItemFormSet, ProdutoForm, ProjetoForm, PropostaForm
from .models import Etapa, ItemProposta, Produto, Projeto, Proposta, pct
from .pdf import gerar_pdf, nome_arquivo

PROPOSTAS = Proposta.objects.select_related("oportunidade__contato", "oportunidade__responsavel", "analise")


# ------------------------------------------------------------------ catálogo
@exige("consultoria")
def catalogo(request):
    area = request.GET.get("area", "")
    qs = Produto.objects.all() if request.GET.get("inativos") == "1" else Produto.objects.filter(ativo=True)
    if area:
        qs = qs.filter(area=area)
    return render(request, "consultoria/catalogo.html", {
        "produtos": qs, "area": area, "areas": AREAS, "inativos": request.GET.get("inativos") == "1"})


@exige("consultoria", "consultoria_precos")
def produto_form(request, pk=None):
    produto = get_object_or_404(Produto, pk=pk) if pk else None
    form = ProdutoForm(request.POST or None, instance=produto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Produto salvo.")
        return redirect("consultoria:catalogo")
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar produto" if produto else "Novo produto",
        "voltar": reverse("consultoria:catalogo")})


# ------------------------------------------------------------------ propostas
@exige("consultoria")
def proposta_lista(request):
    q, status = request.GET.get("q", "").strip(), request.GET.get("status", "")
    qs = PROPOSTAS.prefetch_related("itens")
    if q:
        qs = qs.filter(Q(oportunidade__contato__nome__icontains=q) | Q(oportunidade__titulo__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if request.GET.get("minhas") == "1":
        qs = qs.filter(oportunidade__responsavel=request.user)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "consultoria/proposta_lista.html", {
        "page": page, "q": q, "status": status, "status_choices": Proposta.STATUS,
        "minhas": request.GET.get("minhas") == "1"})


@exige("consultoria")
def proposta_form(request, oportunidade_pk=None, pk=None):
    proposta = get_object_or_404(PROPOSTAS, pk=pk) if pk else None
    if proposta and not proposta.editavel:
        messages.error(request, "A proposta já foi enviada. Volte-a para rascunho para alterar.")
        return redirect(proposta)
    op = proposta.oportunidade if proposta else get_object_or_404(Oportunidade.objects.select_related("contato"),
                                                                    pk=oportunidade_pk)
    instancia = proposta or Proposta(oportunidade=op)
    inicial = None
    if not proposta:
        ultima = op.contato.empresa.analises.order_by("-data_referencia").first() if op.contato.empresa_id else None
        inicial = {"analise": ultima and ultima.pk}
    form = PropostaForm(request.POST or None, instance=instancia, contato=op.contato, initial=inicial)
    classe = ItemFormSet if proposta else forms.inlineformset_factory(
        Proposta, ItemProposta, form=ItemForm, extra=3, can_delete=True, min_num=1, validate_min=True)
    itens = classe(request.POST or None, instance=instancia, prefix="itens")
    if request.method == "POST" and form.is_valid() and itens.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.criado_por = request.user
            obj.save()
            itens.instance = obj
            itens.save()
        messages.success(request, "Proposta salva. Confira o PDF e envie ao cliente.")
        return redirect(obj)
    return render(request, "consultoria/proposta_form.html", {
        "form": form, "itens": itens, "op": op, "proposta": proposta, "referencias": _referencias()})


def _referencias():
    """Valor de referência de cada produto, mostrado ao lado do item (o advogado compara com o que digitou)."""
    refs = {}
    for p in Produto.objects.all():
        txt = brl(p.valor_referencia) + ("/mês" if p.cobranca == "MENSAL" else "")
        refs[p.pk] = txt + (f" + {pct(p.percentual_exito)}% êxito" if p.percentual_exito else "")
    return refs


@exige("consultoria")
def proposta_detalhe(request, pk):
    p = get_object_or_404(PROPOSTAS, pk=pk)
    c = p.contato
    return render(request, "consultoria/proposta_detalhe.html", {
        "p": p, "op": p.oportunidade, "contato": c, "itens": p.itens.select_related("produto"),
        "mensagem": services.mensagem_padrao(p), "projeto": getattr(p, "projeto", None)})


@exige("consultoria")
def proposta_pdf(request, pk):
    p = get_object_or_404(PROPOSTAS, pk=pk)
    return _resposta_pdf(p, inline=request.GET.get("baixar") is None)


def pdf_publico(request, token):
    """Link assinado e com validade, enviado ao cliente pelo WhatsApp."""
    try:
        uuid_str = services.validar_token(token)
    except signing.SignatureExpired:
        raise Http404("Link expirado. Solicite um novo envio.")
    except signing.BadSignature:
        raise Http404("Link inválido.")
    return _resposta_pdf(get_object_or_404(PROPOSTAS, token=uuid_str), inline=True)


def _resposta_pdf(p, inline):
    resp = HttpResponse(gerar_pdf(p), content_type="application/pdf")
    resp["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{nome_arquivo(p)}"'
    return resp


@exige("consultoria")
@require_POST
def proposta_enviar(request, pk):
    p = get_object_or_404(PROPOSTAS, pk=pk)
    if p.status not in ("RASCUNHO", "ENVIADA"):
        messages.error(request, "Só é possível enviar propostas em rascunho ou já enviadas.")
        return redirect(p)
    if not p.itens.exists():
        messages.error(request, "Inclua ao menos um produto antes de enviar.")
        return redirect(p)
    canal = request.POST.get("canal")
    destino = request.POST.get("destino", "").strip()
    mensagem = request.POST.get("mensagem", "").strip() or services.mensagem_padrao(p)
    if not destino:
        messages.error(request, "Informe o destino (e-mail ou WhatsApp).")
        return redirect(p)
    if canal == "EMAIL":
        erro = services.enviar_email(p, destino, mensagem, request.user)
        if erro:
            messages.error(request, f"Falha no envio do e-mail: {erro}")
        else:
            messages.success(request, f"Proposta enviada para {destino}. O atendimento foi para “Proposta enviada”.")
        return redirect(p)
    if canal == "WHATSAPP":
        return redirect(services.link_whatsapp(p, destino, mensagem, request.user))
    raise Http404


@exige("consultoria")
@require_POST
def proposta_acao(request, pk, acao):
    p = get_object_or_404(PROPOSTAS, pk=pk)
    if acao == "aceitar" and p.status == "ENVIADA":
        data = parse_date(request.POST.get("data") or "") or timezone.localdate()
        projeto = services.aceitar(p, request.user, data)
        messages.success(request, "Proposta aceita. Projeto aberto e honorários lançados no financeiro. "
                                  "Registre o link do contrato no atendimento para a assinatura.")
        return redirect(projeto)
    if acao == "recusar" and p.status == "ENVIADA":
        services.recusar(p, request.user, request.POST.get("motivo", "").strip())
        messages.success(request, "Proposta marcada como recusada.")
    elif acao == "rascunho" and p.status in ("ENVIADA", "RECUSADA"):
        p.status, p.respondida_em, p.motivo_recusa = "RASCUNHO", None, ""
        p.save(update_fields=["status", "respondida_em", "motivo_recusa", "atualizado_em"])
        messages.success(request, "Proposta voltou para rascunho. Ao alterar, envie de novo ao cliente.")
    elif acao == "duplicar":
        nova = _duplicar(p, request.user)
        messages.success(request, f"Nova proposta nº {nova.numero} criada a partir da {p.numero}.")
        return redirect("consultoria:proposta_editar", pk=nova.pk)
    elif acao == "excluir" and p.status != "ACEITA":
        op = p.oportunidade
        p.delete()
        messages.success(request, "Proposta excluída.")
        return redirect(op)
    else:
        messages.error(request, "Ação não permitida nesta situação da proposta.")
    return redirect(p)


def _duplicar(p, usuario):
    itens = list(p.itens.all())
    p.pk, p._state.adding = None, True
    p.status, p.enviada_em, p.respondida_em, p.motivo_recusa = "RASCUNHO", None, None, ""
    p.validade = Proposta._meta.get_field("validade").get_default()
    p.token, p.criado_por = Proposta._meta.get_field("token").get_default(), usuario
    p.save()
    for i in itens:
        i.pk, i._state.adding, i.proposta = None, True, p
        i.save()
    return p


# ------------------------------------------------------------------ projetos
@exige("consultoria")
def projeto_lista(request):
    status = request.GET.get("status", "ANDAMENTO")
    qs = Projeto.objects.select_related("cliente", "responsavel", "proposta").prefetch_related("etapas")
    if status:
        qs = qs.filter(status=status)
    if request.GET.get("meus") == "1":
        qs = qs.filter(responsavel=request.user)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "consultoria/projeto_lista.html", {
        "page": page, "status": status, "status_choices": Projeto.STATUS, "meus": request.GET.get("meus") == "1"})


@exige("consultoria")
def projeto_detalhe(request, pk):
    projeto = get_object_or_404(Projeto.objects.select_related("cliente", "responsavel", "proposta__oportunidade"), pk=pk)
    etapas = list(projeto.etapas.select_related("concluida_por"))
    ctx = {"projeto": projeto, "documentos": [e for e in etapas if e.tipo == "DOCUMENTO"],
           "entregas": [e for e in etapas if e.tipo == "ENTREGA"]}
    if pode(request.user, "financeiro"):
        ctx["lancamentos"] = projeto.cliente.lancamentos.filter(
            descricao__startswith=f"Consultoria – proposta {projeto.proposta.numero}")
    return render(request, "consultoria/projeto_detalhe.html", ctx)


@exige("consultoria")
def projeto_form(request, pk):
    projeto = get_object_or_404(Projeto, pk=pk)
    form = ProjetoForm(request.POST or None, instance=projeto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Projeto salvo.")
        return redirect(projeto)
    return render(request, "crm/form.html", {"form": form, "titulo": "Editar projeto", "subtitulo": projeto.cliente.nome,
                                             "voltar": projeto.get_absolute_url()})


@exige("consultoria")
@require_POST
def projeto_status(request, pk):
    projeto = get_object_or_404(Projeto, pk=pk)
    status = request.POST.get("status")
    if status not in dict(Projeto.STATUS):
        raise Http404
    projeto.status = status
    projeto.concluido_em = timezone.localdate() if status == "CONCLUIDO" else None
    projeto.save(update_fields=["status", "concluido_em"])
    messages.success(request, f"Projeto {projeto.get_status_display().lower()}.")
    return redirect(projeto)


@exige("consultoria")
@require_POST
def etapa_nova(request, pk):
    projeto = get_object_or_404(Projeto, pk=pk)
    descricao = request.POST.get("descricao", "").strip()[:250]
    tipo = request.POST.get("tipo") if request.POST.get("tipo") in dict(Etapa.TIPOS) else "ENTREGA"
    if descricao:
        ultima = projeto.etapas.order_by("-ordem").first()
        Etapa.objects.create(projeto=projeto, tipo=tipo, descricao=descricao, ordem=(ultima.ordem + 1) if ultima else 1)
    return redirect(projeto)


@exige("consultoria")
@require_POST
def etapa_marcar(request, pk):
    etapa = get_object_or_404(Etapa, pk=pk)
    if etapa.concluida_em:
        etapa.concluida_em, etapa.concluida_por = None, None
    else:
        etapa.concluida_em, etapa.concluida_por = timezone.now(), request.user
    etapa.save(update_fields=["concluida_em", "concluida_por"])
    return redirect(etapa.projeto)


# ------------------------------------------------------------------ indicadores
@exige("consultoria", "bi")
def indicadores(request):
    hoje = timezone.localdate()
    de = parse_date(request.GET.get("de") or "") or hoje.replace(month=1, day=1)
    ate = parse_date(request.GET.get("ate") or "") or hoje
    qs = Proposta.objects.filter(criado_em__date__gte=de, criado_em__date__lte=ate)
    return render(request, "consultoria/indicadores.html", {"i": services.indicadores(qs), "de": de, "ate": ate,
                                                            "status_choices": Proposta.STATUS})
