import csv
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.http import require_POST

from .envio import enviar_email, enviar_whatsapp, validar_token, whatsapp_api_configurada
from .forms import AnaliseForm, EmpresaForm, EnvioEmailForm, EnvioWhatsappForm, ParametroForm, UsuarioForm
from .perfis import PERFIS, PERMISSOES, definir_perfil, exige, perfil_de, pode
from .models import AnaliseCapag, Empresa, EnvioCapag, Parametro
from . import relatorios as rel
from .pdf import gerar_pdf, gerar_pdf_composicao, nome_arquivo
from .services import quadro_comparativo
from .validators import cnpj_valido, formatar_cnpj, somente_digitos


# ------------------------------------------------------------------ painel
@login_required
def dashboard(request):
    if not pode(request.user, "capag"):  # perfis sem CAPAG caem na sua área de trabalho
        return redirect("juridico:agenda" if pode(request.user, "processos")
                        else "juridico:financeiro" if pode(request.user, "financeiro") else "crm:painel")
    hoje = timezone.localdate()
    pendentes = (AnaliseCapag.objects.select_related("empresa")
                 .filter(data_ciencia__isnull=False, data_ciencia__gte=hoje - timedelta(days=30))
                 .exclude(status="ENVIADA").order_by("data_ciencia"))
    ctx = {
        "total_empresas": Empresa.objects.filter(ativo=True).count(),
        "total_analises": AnaliseCapag.objects.count(),
        "total_envios": EnvioCapag.objects.exclude(status="ERRO").count(),
        "por_rating": dict(AnaliseCapag.objects.values_list("rating_real").annotate(n=Count("id"))),
        "ultimas": AnaliseCapag.objects.select_related("empresa")[:8],
        "prazos": pendentes[:8],
        "hoje": hoje,
    }
    return render(request, "core/dashboard.html", ctx)


# ------------------------------------------------------------------ empresas
@exige("capag")
def empresa_lista(request):
    q = request.GET.get("q", "").strip()
    qs = Empresa.objects.annotate(n_analises=Count("analises")).order_by("razao_social")
    if q:
        dig = somente_digitos(q)
        filtro = (Q(razao_social__icontains=q) | Q(nome_fantasia__icontains=q)
                  | Q(municipio__icontains=q) | Q(cnpj__icontains=q))
        if len(dig) == 14:
            filtro |= Q(cnpj=formatar_cnpj(dig))
        qs = qs.filter(filtro)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "core/empresa_lista.html", {"page": page, "q": q})


@exige("capag")
def empresa_form(request, pk=None):
    empresa = get_object_or_404(Empresa, pk=pk) if pk else None
    form = EmpresaForm(request.POST or None, instance=empresa)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.criado_por = request.user
        obj.save()
        messages.success(request, "Empresa salva com sucesso.")
        return redirect(obj)
    return render(request, "core/empresa_form.html", {"form": form, "empresa": empresa})


@exige("capag")
def empresa_detalhe(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    return render(request, "core/empresa_detalhe.html", {
        "empresa": empresa,
        "analises": empresa.analises.all(),
    })


@exige("capag", "excluir")
@require_POST
def empresa_excluir(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    empresa.delete()
    messages.success(request, "Empresa excluída.")
    return redirect("empresa_lista")


@exige("capag")
def consulta_cnpj(request):
    """Busca dados públicos do CNPJ (publica.cnpj.ws) para preencher o cadastro."""
    cnpj = somente_digitos(request.GET.get("cnpj"))
    if not cnpj_valido(cnpj):
        return JsonResponse({"erro": "CNPJ inválido."}, status=400)
    try:
        r = requests.get(f"https://publica.cnpj.ws/cnpj/{cnpj}", timeout=15)
        if r.status_code == 429:
            return JsonResponse({"erro": "Limite de consultas atingido. Aguarde um minuto."}, status=429)
        r.raise_for_status()
        d = r.json()
    except Exception:  # noqa: BLE001
        return JsonResponse({"erro": "Não foi possível consultar o CNPJ agora."}, status=502)
    est = d.get("estabelecimento") or {}
    porte = ((d.get("porte") or {}).get("descricao") or "").upper()
    endereco = ", ".join(x for x in [
        " ".join(x for x in [est.get("tipo_logradouro"), est.get("logradouro")] if x),
        est.get("numero"), est.get("complemento"), est.get("bairro"),
        f"CEP {est.get('cep')}" if est.get("cep") else None] if x)
    socios = d.get("socios") or []
    return JsonResponse({
        "razao_social": d.get("razao_social", ""),
        "nome_fantasia": est.get("nome_fantasia") or "",
        "atividade": (est.get("atividade_principal") or {}).get("descricao", ""),
        "endereco": endereco,
        "municipio": (est.get("cidade") or {}).get("nome", ""),
        "uf": (est.get("estado") or {}).get("sigla", ""),
        "email": est.get("email") or "",
        "porte": "ME" if "MICRO" in porte else "EPP" if "PEQUENO" in porte else "DEMAIS",
        "responsavel": socios[0].get("nome", "") if socios else "",
    })


# ------------------------------------------------------------------ análises
@exige("capag")
def analise_lista(request):
    qs = AnaliseCapag.objects.select_related("empresa")
    rating = request.GET.get("rating")
    status = request.GET.get("status")
    q = request.GET.get("q", "").strip()
    if rating:
        qs = qs.filter(rating_real=rating)
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(empresa__razao_social__icontains=q) | Q(empresa__cnpj__icontains=q) | Q(descricao__icontains=q))
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "core/analise_lista.html", {
        "page": page, "q": q, "rating": rating, "status": status,
        "status_choices": AnaliseCapag.STATUS,
    })


@exige("capag")
def analise_form(request, empresa_pk=None, pk=None):
    analise = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), pk=pk) if pk else None
    empresa = analise.empresa if analise else get_object_or_404(Empresa, pk=empresa_pk)
    inicial = {"data_referencia": timezone.localdate()} if not analise else None
    form = AnaliseForm(request.POST or None, instance=analise, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.empresa = empresa
        if not obj.pk:
            obj.criado_por = request.user
        obj.save()
        messages.success(request, f"Análise salva. CAPAG real: rating {obj.rating_real}.")
        return redirect(obj)
    return render(request, "core/analise_form.html", {"form": form, "empresa": empresa, "analise": analise})


@exige("capag")
def analise_detalhe(request, pk):
    a = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), pk=pk)
    return render(request, "core/analise_detalhe.html", {
        "a": a, "quadro": quadro_comparativo(a), "envios": a.envios.select_related("usuario"),
        "ind": rel.indicadores(a), "passos": rel.passos_rating(a),
    })


@exige("capag")
@require_POST
def analise_recalcular(request, pk):
    a = get_object_or_404(AnaliseCapag, pk=pk)
    a.save()  # recalcula com os parâmetros atuais
    messages.success(request, "Análise recalculada com os parâmetros atuais.")
    return redirect(a)


@exige("capag")
@require_POST
def analise_duplicar(request, pk):
    a = get_object_or_404(AnaliseCapag, pk=pk)
    a.pk = None
    a._state.adding = True
    import uuid
    a.token = uuid.uuid4()
    a.status = "RASCUNHO"
    a.data_referencia = timezone.localdate()
    a.descricao = (a.descricao + " (cópia)").strip()
    a.criado_por = request.user
    a.save()
    messages.success(request, "Análise duplicada. Ajuste os valores e salve.")
    return redirect("analise_editar", pk=a.pk)


@exige("capag", "excluir")
@require_POST
def analise_excluir(request, pk):
    a = get_object_or_404(AnaliseCapag, pk=pk)
    empresa = a.empresa
    a.delete()
    messages.success(request, "Análise excluída.")
    return redirect(empresa)


@exige("capag")
def analise_pdf(request, pk):
    a = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), pk=pk)
    return _resposta_pdf(a, inline=request.GET.get("download") is None)


def pdf_publico(request, token):
    """Link público assinado e com validade, enviado pelo WhatsApp."""
    try:
        uuid_str = validar_token(token)
    except signing.SignatureExpired:
        raise Http404("Link expirado. Solicite um novo envio.")
    except signing.BadSignature:
        raise Http404("Link inválido.")
    a = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), token=uuid_str)
    return _resposta_pdf(a, inline=True)


def _resposta_pdf(a, inline=True):
    resp = HttpResponse(gerar_pdf(a), content_type="application/pdf")
    modo = "inline" if inline else "attachment"
    resp["Content-Disposition"] = f'{modo}; filename="{nome_arquivo(a)}"'
    return resp


# ------------------------------------------------------------------ envios
@exige("capag")
def enviar_email_view(request, pk):
    a = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), pk=pk)
    form = EnvioEmailForm(request.POST or None, analise=a)
    if request.method == "POST" and form.is_valid():
        envio = enviar_email(a, form.cleaned_data["destino"], form.cleaned_data["assunto"],
                             form.cleaned_data["mensagem"], request.user)
        if envio.status == "ERRO":
            messages.error(request, f"Falha ao enviar e-mail: {envio.resposta}")
        else:
            messages.success(request, f"E-mail enviado para {envio.destino}.")
        return redirect(a)
    return render(request, "core/enviar.html", {"a": a, "form": form, "canal": "E-mail"})


@exige("capag")
def enviar_whatsapp_view(request, pk):
    a = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), pk=pk)
    form = EnvioWhatsappForm(request.POST or None, analise=a)
    if request.method == "POST" and form.is_valid():
        envio = enviar_whatsapp(a, form.cleaned_data["numero"], form.cleaned_data["mensagem"], request.user)
        if envio.status == "ERRO":
            messages.error(request, f"Falha no envio pelo WhatsApp: {envio.resposta[:300]}")
            return redirect(a)
        if envio.status == "LINK":
            return render(request, "core/whatsapp_link.html", {"a": a, "envio": envio})
        messages.success(request, f"PDF enviado pelo WhatsApp para {envio.destino}.")
        return redirect(a)
    return render(request, "core/enviar.html", {
        "a": a, "form": form, "canal": "WhatsApp", "api": whatsapp_api_configurada(),
    })


@exige("capag")
def envio_lista(request):
    page = Paginator(EnvioCapag.objects.select_related("analise__empresa", "usuario"), 30).get_page(request.GET.get("page"))
    return render(request, "core/envio_lista.html", {"page": page})


# ------------------------------------------------------------------ parâmetros
@exige("administrar")
def parametros(request):
    form = ParametroForm(request.POST or None, instance=Parametro.atual())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Parâmetros atualizados. Use \"Recalcular\" nas análises antigas se quiser aplicá-los.")
        return redirect("parametros")
    return render(request, "core/parametros.html", {"form": form})


# ------------------------------------------------------------------ usuários e perfis
@exige("administrar")
def usuarios(request):
    form = UsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        novo = form.save()
        definir_perfil(novo, form.cleaned_data["perfil"])
        messages.success(request, f"Usuário {novo.username} criado com o perfil {PERFIS[form.cleaned_data['perfil']][0]}.")
        return redirect("usuarios")
    lista = list(get_user_model().objects.order_by("-is_active", "first_name", "username"))
    for u in lista:
        u.perfil = perfil_de(u)
    matriz = [(rotulo, [cod in permitidas for _, permitidas in PERFIS.values()]) for cod, rotulo in PERMISSOES.items()]
    return render(request, "core/usuarios.html", {
        "form": form, "usuarios": lista, "perfis": [(cod, nome) for cod, (nome, _) in PERFIS.items()],
        "matriz": matriz})


@exige("administrar")
@require_POST
def usuario_alterar(request, pk):
    alvo = get_object_or_404(get_user_model(), pk=pk)
    if alvo == request.user:
        messages.error(request, "Você não pode alterar o próprio perfil. Peça a outro sócio.")
    elif alvo.is_superuser:
        messages.error(request, "O superusuário é sempre Sócio e só é alterado na área administrativa.")
    elif request.POST.get("acao") == "ativo":
        alvo.is_active = not alvo.is_active
        alvo.save(update_fields=["is_active"])
        messages.success(request, f"{alvo.username}: acesso {'liberado' if alvo.is_active else 'bloqueado'}.")
    elif request.POST.get("perfil") in PERFIS:
        definir_perfil(alvo, request.POST["perfil"])
        messages.success(request, f"{alvo.username} agora é {PERFIS[request.POST['perfil']][0]}.")
    return redirect("usuarios")


# ------------------------------------------------------------------ relatórios
def _anos_disponiveis():
    return [d.year for d in AnaliseCapag.objects.dates("data_referencia", "year", order="DESC")]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _csv(nome, cabecalho, linhas):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    resp.write("﻿")  # BOM para o Excel reconhecer UTF-8
    w = csv.writer(resp, delimiter=";")
    w.writerow(cabecalho)
    w.writerows(linhas)
    return resp


def _dec(v, casas=4):
    return "" if v is None else f"{v:.{casas}f}".replace(".", ",")


@exige("capag")
def relatorios(request):
    return render(request, "core/relatorios/index.html")


@exige("capag")
def relatorio_ranking(request):
    ano = _int(request.GET.get("ano"))
    setor = request.GET.get("setor", "").strip()
    faixa = request.GET.get("faixa", "")
    porte = request.GET.get("porte", "")
    qs = AnaliseCapag.objects.select_related("empresa").filter(empresa__ativo=True)
    if ano:
        qs = qs.filter(data_referencia__year=ano)
    if setor:
        qs = qs.filter(empresa__atividade__icontains=setor)
    if porte:
        qs = qs.filter(empresa__porte=porte)
    grupos = rel.ranking(rel.ultimas_por_empresa(qs))
    if faixa in grupos:
        grupos = {faixa: grupos[faixa]}

    if request.GET.get("formato") == "csv":
        linhas = [[r, a.empresa.razao_social, a.empresa.cnpj, a.empresa.atividade, a.empresa.get_porte_display(),
                   a.data_referencia.strftime("%d/%m/%Y"), _dec(a.divida_total, 2), _dec(a.capag_real, 2),
                   _dec(a.razao), _dec(a.ind["endividamento"]["valor"]), _dec(a.ind["poupanca"]["valor"]),
                   _dec(a.ind["liquidez"]["valor"]), a.rating_pgfn]
                  for r, lst in grupos.items() for a in lst]
        return _csv(f"ranking_capag_{ano or 'todos'}.csv",
                    ["Faixa", "Razão social", "CNPJ", "Atividade", "Porte", "Data ref.", "Dívida", "CAPAG real",
                     "CAPAG/Dívida", "Endividamento", "Poupança corrente", "Liquidez", "Rating PGFN"], linhas)

    total = sum(len(v) for v in grupos.values())
    resumo = [(r, len(lst), round(100 * len(lst) / total) if total else 0) for r, lst in grupos.items()]
    setores = (Empresa.objects.exclude(atividade="").values_list("atividade", flat=True)
               .distinct().order_by("atividade"))
    return render(request, "core/relatorios/ranking.html", {
        "grupos": grupos, "resumo": resumo, "total": total, "anos": _anos_disponiveis(), "setores": setores,
        "ano": ano, "setor": setor, "faixa": faixa, "porte": porte, "portes": Empresa.PORTES,
    })


@exige("capag")
def relatorio_evolucao(request):
    empresas = Empresa.objects.annotate(n=Count("analises")).filter(n__gt=0).order_by("razao_social")
    pk = _int(request.GET.get("empresa"))
    empresa = get_object_or_404(Empresa, pk=pk) if pk else None
    ano_ini, ano_fim = _int(request.GET.get("ano_ini")), _int(request.GET.get("ano_fim"))
    ctx = {"empresas": empresas, "empresa": empresa, "ano_ini": ano_ini, "ano_fim": ano_fim,
           "anos": _anos_disponiveis()}
    if empresa:
        linhas = rel.evolucao(empresa, ano_ini, ano_fim)
        ctx["linhas"] = linhas
        if linhas:
            ctx["grafico"] = rel.grafico_linhas([str(a.ano) for a in linhas], [
                {"nome": "Dívida consolidada", "cor": "#C62828", "valores": [a.divida_total for a in linhas]},
                {"nome": "Receita corrente (12 meses)", "cor": "#1F4E79", "valores": [a.receita_bruta_12m for a in linhas]},
                {"nome": "CAPAG real", "cor": "#2E7D32", "valores": [a.capag_real for a in linhas]},
            ])
        if len(linhas) >= 2:
            ctx["variacoes"] = rel.variacoes(linhas[0], linhas[-1])
    return render(request, "core/relatorios/evolucao.html", ctx)


@exige("capag")
def relatorio_composicao(request, pk=None):
    pk = pk or _int(request.GET.get("analise"))
    a = get_object_or_404(AnaliseCapag.objects.select_related("empresa"), pk=pk) if pk else None
    if a and request.GET.get("formato") == "pdf":
        resp = HttpResponse(gerar_pdf_composicao(a), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{nome_arquivo(a).replace("CAPAG_", "COMPOSICAO_")}"'
        return resp
    analises = rel.ultimas_por_empresa(AnaliseCapag.objects.select_related("empresa"), por_ano=True)
    analises.sort(key=lambda x: (x.empresa.razao_social, -x.data_referencia.toordinal()))
    ctx = {"a": a, "analises": analises}
    if a:
        ctx.update(ind=rel.indicadores(a), passos=rel.passos_rating(a))
    return render(request, "core/relatorios/composicao.html", ctx)


@exige("capag")
def relatorio_alertas(request):
    ano = _int(request.GET.get("ano"))
    severidade = request.GET.get("severidade", "")
    tipo = request.GET.get("tipo", "")
    lista = rel.alertas(AnaliseCapag.objects.filter(empresa__ativo=True), ano=ano)
    if severidade:
        lista = [x for x in lista if x.severidade == severidade]
    if tipo:
        lista = [x for x in lista if x.tipo == tipo]

    if request.GET.get("formato") == "csv":
        return _csv(f"alertas_capag_{ano or 'todos'}.csv",
                    ["Severidade", "Tipo", "Razão social", "CNPJ", "Data ref.", "Rating real", "Alerta"],
                    [[x.severidade_label, x.tipo_label, x.analise.empresa.razao_social, x.analise.empresa.cnpj,
                      x.analise.data_referencia.strftime("%d/%m/%Y"), x.analise.rating_real, x.mensagem]
                     for x in lista])

    empresas = {}
    for x in lista:
        empresas.setdefault(x.analise.empresa_id, {"analise": x.analise, "alertas": []})["alertas"].append(x)
    contagem = {s: sum(1 for x in lista if x.severidade == s) for s in ("critico", "atencao", "info")}
    return render(request, "core/relatorios/alertas.html", {
        "empresas": list(empresas.values()), "contagem": contagem, "total": len(lista),
        "anos": _anos_disponiveis(), "ano": ano, "severidade": severidade, "tipo": tipo,
        "tipos": rel.TIPOS_ALERTA,
    })


# ------------------------------------------------------------------ PWA
def _icone_pwa(nome, tamanho, uso):
    return {"src": static(f"pwa/{nome}"), "sizes": f"{tamanho}x{tamanho}", "type": "image/png", "purpose": uso}


def pwa_manifest(request):
    return JsonResponse({
        "name": "Sistema CAPAG", "short_name": "CAPAG", "lang": "pt-BR",
        "description": "CAPAG (PGFN) e CRM jurídico do escritório.",
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#f4f6f9", "theme_color": "#000000",
        "icons": [_icone_pwa("icon-192.png", 192, "any"), _icone_pwa("icon-512.png", 512, "any"),
                  _icone_pwa("icon-maskable-512.png", 512, "maskable")],
        "shortcuts": [{"name": "Painel do advogado", "url": "/crm/"},
                      {"name": "Novo contato", "url": "/crm/contatos/novo/"},
                      {"name": "Atualizações jurídicas", "url": "/crm/atualizacoes/"}],
    }, content_type="application/manifest+json")


def pwa_sw(request):
    resp = render(request, "pwa/sw.js", {"static_prefix": settings.STATIC_URL.strip("/") + "/"},
                  content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"  # o navegador sempre confere se há versão nova
    return resp


def pwa_offline(request):
    return render(request, "pwa/offline.html")
