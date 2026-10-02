import csv

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.perfis import exige, pode
from crm.models import AREAS, Contato

from . import services
from .forms import AndamentoForm, DocumentoForm, LancamentoForm, PrazoForm, ProcessoForm
from .models import Documento, Lancamento, Prazo, Processo


def _voltar(request, padrao):
    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect(padrao)


# ------------------------------------------------------------------ agenda de prazos
@exige("processos")
def agenda(request):
    todos = request.GET.get("todos") == "1"
    qs = Prazo.objects.all() if todos else Prazo.objects.filter(responsavel=request.user)
    grupos = services.agenda(qs)
    return render(request, "juridico/agenda.html", {
        "todos": todos,
        "grupos": [("Vencidos", "danger", grupos["vencidos"]), ("Hoje", "danger", grupos["hoje"]),
                   ("Próximos 7 dias", "warning", grupos["semana"]), ("Depois", "info", grupos["depois"])],
        "total": sum(len(v) for v in grupos.values()),
    })


# ------------------------------------------------------------------ processos
@exige("processos")
def processo_lista(request):
    q = request.GET.get("q", "").strip()
    area, status = request.GET.get("area", ""), request.GET.get("status", "ATIVO")
    qs = (Processo.objects.select_related("cliente", "responsavel")
          .annotate(n_prazos=Count("prazos", filter=Q(prazos__status="PENDENTE"))).order_by("-criado_em"))
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(titulo__icontains=q) | Q(cliente__nome__icontains=q)
                       | Q(parte_contraria__icontains=q) | Q(orgao__icontains=q))
    if area:
        qs = qs.filter(area=area)
    if status:
        qs = qs.filter(status=status)
    if request.GET.get("meus") == "1":
        qs = qs.filter(responsavel=request.user)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "juridico/processo_lista.html", {
        "page": page, "q": q, "area": area, "status": status, "areas": AREAS, "status_choices": Processo.STATUS,
        "meus": request.GET.get("meus") == "1"})


@exige("processos", "processos_editar")
def processo_form(request, pk=None):
    processo = get_object_or_404(Processo, pk=pk) if pk else None
    inicial = None
    if not processo:
        cliente = Contato.objects.filter(pk=request.GET.get("cliente") or 0).first()
        inicial = {"responsavel": request.user.pk, "cliente": cliente and cliente.pk,
                   "area": cliente.area_interesse if cliente else None}
    form = ProcessoForm(request.POST or None, instance=processo, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.criado_por = request.user
        obj.save()
        messages.success(request, "Processo salvo.")
        return redirect(obj)
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar processo" if processo else "Novo processo",
        "voltar": processo.get_absolute_url() if processo else reverse("juridico:processo_lista")})


@exige("processos")
def processo_detalhe(request, pk):
    p = get_object_or_404(Processo.objects.select_related("cliente", "responsavel"), pk=pk)
    ctx = {"p": p, "prazos": p.prazos.select_related("responsavel"),
           "andamentos": p.andamentos.select_related("usuario"), "andamento_form": AndamentoForm()}
    if pode(request.user, "documentos"):
        ctx.update(documentos=p.documentos.select_related("enviado_por"),
                   documento_form=DocumentoForm(cliente=p.cliente, initial={"processo": p.pk}))
    if pode(request.user, "financeiro"):
        ctx.update(lancamentos=p.lancamentos.all(), resumo=services.resumo_financeiro(p.lancamentos.all()),
                   novo_query=f"processo={p.pk}")
    return render(request, "juridico/processo_detalhe.html", ctx)


@exige("processos", "processos_editar", "excluir")
@require_POST
def processo_excluir(request, pk):
    p = get_object_or_404(Processo, pk=pk)
    cliente = p.cliente
    p.delete()
    messages.success(request, "Processo excluído. Os documentos e lançamentos continuam na pasta do cliente.")
    return redirect("juridico:pasta", pk=cliente.pk)


@exige("processos")
@require_POST
def andamento_novo(request, pk):
    p = get_object_or_404(Processo, pk=pk)
    form = AndamentoForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.processo, obj.usuario = p, request.user
        obj.save()
        messages.success(request, "Andamento lançado.")
    else:
        messages.error(request, "Informe a data e a descrição do andamento.")
    return redirect(p)


# ------------------------------------------------------------------ prazos
@exige("processos", "processos_editar")
def prazo_form(request, processo_pk=None, pk=None):
    prazo = get_object_or_404(Prazo.objects.select_related("processo"), pk=pk) if pk else None
    processo = prazo.processo if prazo else get_object_or_404(Processo, pk=processo_pk)
    data_antiga = prazo.data_limite if prazo else None
    inicial = None if prazo else {"responsavel": processo.responsavel_id or request.user.pk}
    form = PrazoForm(request.POST or None, instance=prazo, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.processo = processo
        if not obj.pk:
            obj.criado_por = request.user
        elif obj.data_limite != data_antiga:
            obj.avisado_antes = obj.avisado_no_dia = False  # nova data: avisa de novo
        obj.save()
        messages.success(request, "Prazo salvo. O responsável será avisado por e-mail antes do vencimento.")
        return redirect(processo)
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar prazo" if prazo else "Novo prazo", "subtitulo": str(processo),
        "voltar": processo.get_absolute_url()})


@exige("processos", "processos_editar")
@require_POST
def prazo_status(request, pk):
    prazo = get_object_or_404(Prazo, pk=pk)
    status = request.POST.get("status")
    if status not in dict(Prazo.STATUS):
        raise Http404
    prazo.status = status
    prazo.cumprido_em = timezone.now() if status == "CUMPRIDO" else None
    prazo.cumprido_por = request.user if status == "CUMPRIDO" else None
    prazo.save()
    messages.success(request, f"Prazo marcado como {prazo.get_status_display().lower()}.")
    return _voltar(request, prazo.processo)


# ------------------------------------------------------------------ pasta do cliente e documentos
@exige("crm")
def pasta(request, pk):
    cliente = get_object_or_404(Contato.objects.select_related("responsavel"), pk=pk)
    u = request.user
    ctx = {"cliente": cliente}
    if pode(u, "processos"):
        ctx["processos"] = cliente.processos.select_related("responsavel")
    if pode(u, "documentos"):
        ctx.update(documentos=cliente.documentos.select_related("processo", "enviado_por"),
                   documento_form=DocumentoForm(cliente=cliente))
    if pode(u, "financeiro"):
        ctx.update(lancamentos=cliente.lancamentos.select_related("processo"),
                   resumo=services.resumo_financeiro(cliente.lancamentos.all()),
                   novo_query=f"cliente={cliente.pk}")
    return render(request, "juridico/pasta.html", ctx)


@exige("documentos")
@require_POST
def documento_novo(request, cliente_pk):
    cliente = get_object_or_404(Contato, pk=cliente_pk)
    form = DocumentoForm(request.POST, request.FILES, cliente=cliente, instance=Documento(cliente=cliente))
    if form.is_valid():
        doc = form.save(commit=False)
        doc.enviado_por = request.user
        doc.save()
        messages.success(request, f"Documento “{doc}” guardado.")
    else:
        messages.error(request, " ".join(e for erros in form.errors.values() for e in erros))
    return _voltar(request, reverse("juridico:pasta", args=[cliente.pk]))


@exige("documentos")
def documento_baixar(request, pk):
    """Os arquivos não têm endereço público: só saem por aqui, para quem tem a permissão."""
    doc = get_object_or_404(Documento, pk=pk)
    try:
        arquivo = doc.arquivo.open("rb")
    except FileNotFoundError:
        raise Http404("Arquivo não encontrado no servidor.")
    return FileResponse(arquivo, as_attachment=request.GET.get("ver") is None, filename=doc.nome_original)


@exige("documentos", "excluir")
@require_POST
def documento_excluir(request, pk):
    doc = get_object_or_404(Documento, pk=pk)
    cliente_pk = doc.cliente_id
    doc.delete()
    messages.success(request, "Documento excluído.")
    return _voltar(request, reverse("juridico:pasta", args=[cliente_pk]))


# ------------------------------------------------------------------ financeiro
@exige("financeiro")
def financeiro(request):
    hoje = timezone.localdate()
    q = request.GET.get("q", "").strip()
    natureza, situacao = request.GET.get("natureza", ""), request.GET.get("situacao", "aberto")
    de, ate = parse_date(request.GET.get("de") or ""), parse_date(request.GET.get("ate") or "")
    qs = Lancamento.objects.select_related("cliente", "processo")
    if q:
        qs = qs.filter(Q(cliente__nome__icontains=q) | Q(descricao__icontains=q) | Q(processo__numero__icontains=q))
    if natureza:
        qs = qs.filter(natureza=natureza)
    if de:
        qs = qs.filter(vencimento__gte=de)
    if ate:
        qs = qs.filter(vencimento__lte=ate)
    resumo = services.resumo_financeiro(qs, hoje)
    if situacao == "aberto":
        qs = qs.filter(pago_em__isnull=True)
    elif situacao == "atraso":
        qs = qs.filter(pago_em__isnull=True, vencimento__lt=hoje)
    elif situacao == "pago":
        qs = qs.filter(pago_em__isnull=False).order_by("-pago_em")

    if request.GET.get("formato") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="financeiro.csv"'
        resp.write("﻿")  # BOM para o Excel reconhecer UTF-8
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Vencimento", "Cliente", "Processo", "Natureza", "Categoria", "Descrição", "Valor", "Situação",
                    "Pago em", "Forma"])
        w.writerows([x.vencimento.strftime("%d/%m/%Y"), x.cliente.nome, x.processo.numero if x.processo else "",
                     x.get_natureza_display(), x.get_categoria_display(), x.descricao, f"{x.valor:.2f}".replace(".", ","),
                     x.situacao[0], x.pago_em.strftime("%d/%m/%Y") if x.pago_em else "", x.get_forma_pagamento_display()]
                    for x in qs)
        return resp

    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "juridico/financeiro.html", {
        "page": page, "resumo": resumo, "q": q, "natureza": natureza, "situacao": situacao, "de": de, "ate": ate,
        "naturezas": Lancamento.NATUREZAS, "formas": Lancamento.FORMAS, "hoje": hoje})


@exige("financeiro")
def lancamento_form(request, pk=None):
    lanc = get_object_or_404(Lancamento, pk=pk) if pk else None
    inicial = None
    if not lanc:
        processo = Processo.objects.filter(pk=request.GET.get("processo") or 0).first()
        cliente_pk = processo.cliente_id if processo else request.GET.get("cliente")
        inicial = {"cliente": cliente_pk, "processo": processo and processo.pk, "vencimento": timezone.localdate()}
    form = LancamentoForm(request.POST or None, instance=lanc, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if lanc:
            obj.save()
            messages.success(request, "Lançamento salvo.")
        else:
            obj.criado_por = request.user
            criados = services.gerar_parcelas(obj, form.cleaned_data["parcelas"])
            messages.success(request, f"{len(criados)} lançamento(s) criado(s).")
        return _voltar(request, reverse("juridico:pasta", args=[obj.cliente_id]))
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar lançamento" if lanc else "Novo lançamento",
        "voltar": reverse("juridico:financeiro")})


@exige("financeiro")
@require_POST
def lancamento_pagar(request, pk):
    lanc = get_object_or_404(Lancamento, pk=pk)
    if request.POST.get("acao") == "estornar":
        lanc.pago_em, lanc.forma_pagamento = None, ""
        msg = "Baixa desfeita."
    else:
        lanc.pago_em = parse_date(request.POST.get("pago_em") or "") or timezone.localdate()
        forma = request.POST.get("forma_pagamento", "")
        lanc.forma_pagamento = forma if forma in dict(Lancamento.FORMAS) else ""
        msg = f"Baixa registrada em {lanc.pago_em:%d/%m/%Y}."
    lanc.save()
    messages.success(request, msg)
    return _voltar(request, "juridico:financeiro")


@exige("financeiro", "excluir")
@require_POST
def lancamento_excluir(request, pk):
    get_object_or_404(Lancamento, pk=pk).delete()
    messages.success(request, "Lançamento excluído.")
    return _voltar(request, "juridico:financeiro")
