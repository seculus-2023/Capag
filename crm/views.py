import csv
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.envio import link_wame, whatsapp_api_configurada
from core.perfis import exige

from . import feeds, mapas, services
from .forms import (AssinaturaForm, ContatoForm, ContratoForm, ConteudoForm, InteracaoForm, OportunidadeForm,
                    PerdaForm, PesquisaMercadoForm, PropostaForm, ReuniaoForm)
from .models import AREAS, Atualizacao, Contato, Conteudo, Fonte, Interacao, Oportunidade, PesquisaMercado, Reuniao

FORMS_ACAO = {"proposta": ("proposta_form", PropostaForm), "contrato": ("contrato_form", ContratoForm),
              "assinado": ("assinatura_form", AssinaturaForm), "perdido": ("perda_form", PerdaForm)}


def _voltar(request, padrao):
    """Redireciona para o "next" do formulário quando ele aponta para o próprio sistema."""
    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect(padrao)


# ------------------------------------------------------------------ painel do advogado
@exige("crm")
def painel(request):
    todos = request.GET.get("todos") == "1"
    ops = Oportunidade.objects.select_related("contato", "responsavel")
    reunioes = Reuniao.objects.select_related("oportunidade__contato", "advogado")
    if not todos:
        ops = ops.filter(responsavel=request.user)
        reunioes = reunioes.filter(advogado=request.user)
    hoje = timezone.localdate()
    inicio_dia = timezone.make_aware(datetime.combine(hoje, time.min))
    proximas = list(reunioes.filter(status="AGENDADA", inicio__gte=inicio_dia, inicio__lt=inicio_dia + timedelta(days=8)))
    api = whatsapp_api_configurada()
    for r in proximas:
        r.wame = "" if api else services.link_wame_lembrete(r)
        r.lembrada = r.mensagens.filter(tipo="LEMBRETE", status="ENVIADO").exists()
    contagem = dict(ops.values_list("etapa").annotate(n=Count("id")))
    return render(request, "crm/painel.html", {
        "todos": todos, "hoje": hoje, "dias_followup": settings.CRM_FOLLOWUP_DIAS,
        "followups": services.pendentes_followup(ops),
        "reunioes": proximas,
        "novos": ops.filter(etapa="NOVO")[:8],
        "assinaturas": ops.filter(etapa__in=Oportunidade.ABERTAS, contrato_enviado_em__isnull=False)[:8],
        "funil": [(cod, nome, contagem.get(cod, 0)) for cod, nome in Oportunidade.ETAPAS],
        "atualizacoes": Atualizacao.visiveis.filter(lida=False).select_related("fonte")[:6],
        "nao_lidas": Atualizacao.visiveis.filter(lida=False).count(),
    })


@exige("crm")
def funil(request):
    ops = Oportunidade.objects.select_related("contato", "responsavel")
    area = request.GET.get("area", "")
    if area:
        ops = ops.filter(area=area)
    if request.GET.get("meus") == "1":
        ops = ops.filter(responsavel=request.user)
    limite = timezone.localdate() - timedelta(days=90)  # encerrados antigos saem do quadro
    colunas = []
    for cod, nome in Oportunidade.ETAPAS:
        itens = ops.filter(etapa=cod)
        if cod in ("FECHADO", "PERDIDO"):
            itens = itens.filter(atualizado_em__date__gte=limite)
        itens = list(itens[:50])
        colunas.append({"cod": cod, "nome": nome, "itens": itens, "total": sum(o.valor_estimado for o in itens)})
    return render(request, "crm/funil.html", {"colunas": colunas, "area": area, "areas": AREAS,
                                              "meus": request.GET.get("meus") == "1"})


# ------------------------------------------------------------------ contatos
@exige("crm")
def contato_lista(request):
    q = request.GET.get("q", "").strip()
    area = request.GET.get("area", "")
    qs = Contato.objects.select_related("responsavel").annotate(n_ops=Count("oportunidades")).order_by("nome")
    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(email__icontains=q) | Q(documento__icontains=q)
                       | Q(whatsapp__icontains=q) | Q(municipio__icontains=q))
    if area:
        qs = qs.filter(area_interesse=area)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "crm/contato_lista.html", {"page": page, "q": q, "area": area, "areas": AREAS})


@exige("crm")
def contato_form(request, pk=None):
    contato = get_object_or_404(Contato, pk=pk) if pk else None
    inicial = None if contato else {"responsavel": request.user.pk, "empresa": request.GET.get("empresa")}
    form = ContatoForm(request.POST or None, instance=contato, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        novo = not obj.pk
        if novo:
            obj.criado_por = request.user
        obj.save()
        if novo:  # todo contato novo entra no funil na etapa "Novo contato"
            op = Oportunidade.objects.create(
                contato=obj, area=obj.area_interesse, responsavel=obj.responsavel, criado_por=request.user,
                titulo=form.cleaned_data.get("assunto") or obj.get_area_interesse_display())
            messages.success(request, "Contato cadastrado. Agende a consulta inicial com o advogado especialista.")
            return redirect(op)
        messages.success(request, "Contato salvo.")
        return redirect(obj)
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar contato" if contato else "Novo contato",
        "voltar": contato.get_absolute_url() if contato else reverse("crm:contato_lista")})


@exige("crm")
def contato_detalhe(request, pk):
    contato = get_object_or_404(Contato.objects.select_related("responsavel", "empresa"), pk=pk)
    return render(request, "crm/contato_detalhe.html", {
        "contato": contato, "oportunidades": contato.oportunidades.select_related("responsavel"),
        "mensagens": contato.mensagens.select_related("conteudo", "reuniao")[:30],
    })


@exige("crm", "excluir")
@require_POST
def contato_excluir(request, pk):
    contato = get_object_or_404(Contato, pk=pk)
    try:
        contato.delete()
    except ProtectedError:
        messages.error(request, "Este cliente tem processos, documentos ou lançamentos financeiros. "
                                "Exclua-os na pasta do cliente antes de excluir o contato.")
        return redirect(contato)
    messages.success(request, "Contato excluído.")
    return redirect("crm:contato_lista")


# ------------------------------------------------------------------ atendimentos (funil)
@exige("crm")
def oportunidade_form(request, contato_pk=None, pk=None):
    op = get_object_or_404(Oportunidade.objects.select_related("contato"), pk=pk) if pk else None
    contato = op.contato if op else get_object_or_404(Contato, pk=contato_pk)
    inicial = None if op else {"area": contato.area_interesse, "responsavel": contato.responsavel_id or request.user.pk}
    form = OportunidadeForm(request.POST or None, instance=op, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.contato = contato
        if not obj.pk:
            obj.criado_por = request.user
        obj.save()
        messages.success(request, "Atendimento salvo.")
        return redirect(obj)
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar atendimento" if op else "Novo atendimento", "subtitulo": contato.nome,
        "voltar": (op or contato).get_absolute_url()})


def _ctx_oportunidade(op, **forms_):
    contato = op.contato
    msg_contrato = (f"Olá, {contato.primeiro_nome}! Segue o link para assinatura digital do contrato de "
                    f"prestação de serviços: {op.contrato_link}")
    ctx = {
        "op": op, "contato": contato,
        "reunioes": op.reunioes.select_related("advogado"),
        "interacoes": op.interacoes.select_related("usuario"),
        "interacao_form": InteracaoForm(),
        "proposta_form": PropostaForm(instance=op, initial={"proposta_enviada_em": op.proposta_enviada_em or timezone.localdate()}),
        "contrato_form": ContratoForm(instance=op),
        "assinatura_form": AssinaturaForm(instance=op, initial={"contrato_assinado_em": timezone.localdate()}),
        "perda_form": PerdaForm(instance=op),
        "wame_contrato": link_wame(contato.whatsapp, msg_contrato) if op.contrato_link and contato.whatsapp else "",
        "followup_dias": op.dias_sem_contato,
    }
    ctx.update(forms_)
    return ctx


@exige("crm")
def oportunidade_detalhe(request, pk):
    op = get_object_or_404(Oportunidade.objects.select_related("contato", "responsavel"), pk=pk)
    return render(request, "crm/oportunidade_detalhe.html", _ctx_oportunidade(op))


@exige("crm")
@require_POST
def oportunidade_acao(request, pk, acao):
    """Movimenta o atendimento no funil: proposta → contrato → assinatura (fechado) ou perda."""
    op = get_object_or_404(Oportunidade.objects.select_related("contato", "responsavel"), pk=pk)
    if acao == "reabrir":
        op.etapa = "PROPOSTA" if op.proposta_enviada_em else "REUNIAO" if op.reunioes.exists() else "NOVO"
        op.motivo_perda, op.detalhe_perda, op.fechado_em, op.contrato_assinado_em = "", "", None, None
        op.save()
        messages.success(request, "Atendimento reaberto.")
        return redirect(op)
    if acao not in FORMS_ACAO:
        raise Http404
    nome_form, classe = FORMS_ACAO[acao]
    form = classe(request.POST, instance=op)
    if not form.is_valid():
        # o ModelForm já alterou a instância em memória; recarrega para exibir os dados gravados
        op = Oportunidade.objects.select_related("contato", "responsavel").get(pk=pk)
        form.instance = op
        return render(request, "crm/oportunidade_detalhe.html", _ctx_oportunidade(op, **{nome_form: form}))
    obj = form.save(commit=False)
    if acao == "proposta":
        obj.etapa = "PROPOSTA"
        msg = (f"Proposta registrada. Sem novo contato em {settings.CRM_FOLLOWUP_DIAS} dias, "
               f"o alerta de follow-up aparece no painel do advogado.")
    elif acao == "contrato":
        obj.contrato_enviado_em = timezone.localdate()
        msg = "Link do contrato registrado. Envie ao cliente e marque a assinatura quando concluída."
    elif acao == "assinado":
        obj.etapa, obj.fechado_em = "FECHADO", obj.contrato_assinado_em
        obj.motivo_perda = obj.detalhe_perda = ""
        msg = "Contrato assinado. Atendimento fechado."
    else:
        obj.etapa = "PERDIDO"
        msg = "Atendimento marcado como perdido."
    obj.save()
    messages.success(request, msg)
    return redirect(obj)


@exige("crm")
@require_POST
def interacao_nova(request, pk):
    op = get_object_or_404(Oportunidade, pk=pk)
    form = InteracaoForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.oportunidade, obj.usuario = op, request.user
        obj.save()
        messages.success(request, "Contato registrado.")
    else:
        messages.error(request, "Descreva o que foi tratado.")
    return redirect(op)


# ------------------------------------------------------------------ reuniões
@exige("crm")
def reuniao_form(request, oportunidade_pk=None, pk=None):
    reuniao = get_object_or_404(Reuniao.objects.select_related("oportunidade__contato"), pk=pk) if pk else None
    op = reuniao.oportunidade if reuniao else get_object_or_404(Oportunidade.objects.select_related("contato"), pk=oportunidade_pk)
    inicio_antigo = reuniao.inicio if reuniao else None
    inicial = None if reuniao else {"advogado": op.responsavel_id or request.user.pk}
    form = ReuniaoForm(request.POST or None, instance=reuniao, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.oportunidade = op
        if inicio_antigo and obj.inicio != inicio_antigo:
            obj.remarcada_em = timezone.now()  # libera um novo lembrete automático
            obj.status = "AGENDADA"
        obj.save()
        if op.etapa == "NOVO":
            Oportunidade.objects.filter(pk=op.pk).update(etapa="REUNIAO")
        canais = services.canais_lembrete(obj)
        aviso = ("O cliente será lembrado automaticamente por " + " e ".join(
            {"EMAIL": "e-mail", "WHATSAPP": "WhatsApp"}[c] for c in canais) + "."
                 if canais else "Sem e-mail cadastrado: o lembrete automático não será enviado.")
        messages.success(request, f"Consulta agendada. {aviso}")
        return redirect(op)
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Remarcar consulta" if reuniao else "Agendar consulta inicial",
        "subtitulo": f"{op.contato.nome} · {op.titulo}", "voltar": op.get_absolute_url()})


@exige("crm")
@require_POST
def reuniao_status(request, pk):
    r = get_object_or_404(Reuniao, pk=pk)
    status = request.POST.get("status")
    if status not in dict(Reuniao.STATUS):
        raise Http404
    r.status = status
    r.save(update_fields=["status"])
    if status == "REALIZADA":
        Interacao.objects.create(oportunidade=r.oportunidade, tipo="REUNIAO", usuario=request.user,
                                 descricao="Consulta realizada.")
    messages.success(request, f"Reunião: {r.get_status_display().lower()}.")
    return _voltar(request, r.oportunidade)


@exige("crm")
@require_POST
def reuniao_lembrar(request, pk):
    r = get_object_or_404(Reuniao.objects.select_related("oportunidade__contato", "advogado"), pk=pk)
    enviadas = services.lembrar_reuniao(r)
    if not enviadas:
        messages.warning(request, "O contato não tem e-mail (nem WhatsApp com a API configurada) para o lembrete.")
    for m in enviadas:
        if m.status == "ERRO":
            messages.error(request, f"Falha no lembrete por {m.get_canal_display()}: {m.resposta[:200]}")
        else:
            messages.success(request, f"Lembrete enviado por {m.get_canal_display()} para {m.destino}.")
    return _voltar(request, r.oportunidade)


# ------------------------------------------------------------------ nutrição (conteúdos informativos)
@exige("crm")
def conteudo_lista(request):
    conteudos = list(Conteudo.objects.annotate(
        n_enviados=Count("mensagens", filter=Q(mensagens__status="ENVIADO"))))
    for c in conteudos:
        c.n_destinatarios = services.destinatarios(c).count() if c.status != "ENVIADO" else None
    return render(request, "crm/conteudo_lista.html", {
        "conteudos": conteudos, "inscritos": Contato.objects.filter(aceita_conteudo=True).exclude(email="").count()})


@exige("crm")
def conteudo_form(request, pk=None):
    conteudo = get_object_or_404(Conteudo, pk=pk) if pk else None
    if conteudo and conteudo.status == "ENVIADO":
        messages.warning(request, "Conteúdo já enviado não pode ser alterado.")
        return redirect("crm:conteudo_lista")
    form = ConteudoForm(request.POST or None, instance=conteudo)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.criado_por = request.user
        obj.status, obj.aprovado_por = "RASCUNHO", None  # toda alteração volta para aprovação
        obj.save()
        messages.success(request, "Conteúdo salvo como rascunho. Um advogado (usuário staff) precisa aprovar o envio.")
        return redirect("crm:conteudo_lista")
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar conteúdo informativo" if conteudo else "Novo conteúdo informativo",
        "voltar": reverse("crm:conteudo_lista"), "aviso_oab": True})


@exige("crm", "administrar")
@require_POST
def conteudo_acao(request, pk, acao):
    c = get_object_or_404(Conteudo, pk=pk)
    if acao == "aprovar" and c.status == "RASCUNHO":
        c.status, c.aprovado_por = "APROVADO", request.user
        c.save()
        messages.success(request, f"Aprovado. O envio automático ocorre a partir de {c.enviar_a_partir:%d/%m/%Y}.")
    elif acao == "enviar" and c.status == "APROVADO":
        try:
            msgs = services.disparar_conteudo(c)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            erros = sum(1 for m in msgs if m.status == "ERRO")
            messages.success(request, f"Conteúdo enviado a {len(msgs) - erros} contato(s)."
                             + (f" {erros} falha(s) – veja o histórico do contato." if erros else ""))
    elif acao == "excluir" and c.status != "ENVIADO":
        c.delete()
        messages.success(request, "Conteúdo excluído.")
    return redirect("crm:conteudo_lista")


def descadastrar(request, token):
    """Link público do rodapé dos conteúdos: o contato deixa de receber os informativos."""
    try:
        contato = services.contato_do_token(token)
    except signing.BadSignature:
        raise Http404("Link inválido.")
    if contato is None:
        raise Http404("Link inválido.")
    if request.method == "POST":
        contato.aceita_conteudo = False
        contato.save()
        return render(request, "crm/descadastrar.html", {"feito": True})
    return render(request, "crm/descadastrar.html", {"contato": contato})


# ------------------------------------------------------------------ inteligência comercial
@exige("crm", "bi")
def relatorio(request):
    de, ate = parse_date(request.GET.get("de") or ""), parse_date(request.GET.get("ate") or "")
    resp = request.GET.get("responsavel", "")
    qs = Oportunidade.objects.all()
    if de:
        qs = qs.filter(aberto_em__gte=de)
    if ate:
        qs = qs.filter(aberto_em__lte=ate)
    if resp.isdigit():
        qs = qs.filter(responsavel_id=int(resp))
    advogados = get_user_model().objects.filter(oportunidades_crm__isnull=False).distinct()
    return render(request, "crm/relatorio.html", {
        "ind": services.indicadores(qs), "de": de, "ate": ate, "responsavel": resp, "advogados": advogados})


# ------------------------------------------------------------------ atualizações jurídicas
@exige("crm")
def atualizacoes(request):
    area = request.GET.get("area", "")
    q = request.GET.get("q", "").strip()
    so_novas = request.GET.get("novas") == "1"
    qs = Atualizacao.visiveis.select_related("fonte")
    if area:
        qs = qs.filter(area=area)
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(resumo__icontains=q))
    if so_novas:
        qs = qs.filter(lida=False)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "crm/atualizacoes.html", {
        "page": page, "area": area, "q": q, "so_novas": so_novas, "areas": AREAS,
        "fontes": Fonte.objects.all(), "nao_lidas": Atualizacao.visiveis.filter(lida=False).count()})


@exige("crm")
@require_POST
def atualizacoes_buscar(request):
    novas = feeds.atualizar_tudo()
    falhas = Fonte.objects.filter(ativo=True).exclude(ultimo_erro="").count()
    messages.success(request, f"{novas} nova(s) atualização(ões)." + (f" {falhas} fonte(s) com falha." if falhas else ""))
    return redirect("crm:atualizacoes")


@exige("crm")
@require_POST
def atualizacoes_excluir(request):
    """Exclui todas as atualizações (ou só as da área filtrada). As já excluídas não voltam na próxima busca."""
    area = request.POST.get("area", "")
    qs, fontes = Atualizacao.objects.all(), Fonte.objects.all()
    if area:
        qs, fontes = qs.filter(area=area), fontes.filter(area=area)
    n = qs.filter(excluida=False).count()
    qs.delete()
    fontes.update(ignorar_ate=timezone.now())
    messages.success(request, f"{n} atualização(ões) excluída(s).")
    return redirect("crm:atualizacoes")


@exige("crm")
@require_POST
def atualizacao_excluir(request, pk):
    get_object_or_404(Atualizacao.visiveis, pk=pk)
    Atualizacao.objects.filter(pk=pk).update(excluida=True, lida=True)
    messages.success(request, "Atualização excluída.")
    return _voltar(request, "crm:atualizacoes")


@exige("crm")
@require_POST
def atualizacao_lida(request, pk=None):
    if pk:
        a = get_object_or_404(Atualizacao.visiveis, pk=pk)
        a.lida = not a.lida
        a.save(update_fields=["lida"])
    else:
        qs = Atualizacao.visiveis.filter(lida=False)
        if request.POST.get("area"):
            qs = qs.filter(area=request.POST["area"])
        qs.update(lida=True)
    return _voltar(request, "crm:atualizacoes")


# ------------------------------------------------------------------ pesquisa de mercado (OpenStreetMap)
@exige("crm")
def pesquisa_lista(request):
    form = PesquisaMercadoForm(request.POST or None, initial={"uf": "MT"})
    if request.method == "POST" and form.is_valid():
        pesquisa = form.save(commit=False)
        pesquisa.usuario = request.user
        pesquisa.save()
        try:
            n = mapas.extrair(pesquisa)
        except mapas.ErroMapa as exc:
            pesquisa.delete()
            messages.error(request, str(exc))
        else:
            if n:
                messages.success(request, f"{n} empresa(s) encontrada(s).")
            else:
                messages.warning(request, "Nenhuma empresa encontrada. Confira o nome do município (com acentos) e a UF.")
            return redirect(pesquisa)
    return render(request, "crm/pesquisa_lista.html", {
        "form": form, "pesquisas": PesquisaMercado.objects.select_related("usuario")[:50]})


@exige("crm")
def pesquisa_detalhe(request, pk):
    pesquisa = get_object_or_404(PesquisaMercado, pk=pk)
    empresas = pesquisa.empresas.all()
    if request.GET.get("formato") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="pesquisa_mercado_{pesquisa.pk}.csv"'
        resp.write("\ufeff")  # BOM para o Excel reconhecer UTF-8
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Nome", "Tipo", "Endereço", "Município", "UF", "Telefone", "E-mail", "Site", "Mapa"])
        w.writerows([e.nome, e.tipo, e.endereco, pesquisa.municipio, pesquisa.uf, e.telefone, e.email, e.site,
                     e.link_google_maps] for e in empresas)
        return resp
    return render(request, "crm/pesquisa_detalhe.html", {
        "pesquisa": pesquisa, "empresas": empresas, "com_telefone": empresas.exclude(telefone="").count()})


@exige("crm")
@require_POST
def pesquisa_excluir(request, pk):
    get_object_or_404(PesquisaMercado, pk=pk).delete()
    messages.success(request, "Pesquisa excluída.")
    return redirect("crm:pesquisa_lista")
