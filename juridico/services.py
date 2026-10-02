"""Regras de prazos (agenda e avisos por e-mail) e do financeiro de honorários."""
import calendar
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from .models import Lancamento, Prazo


# ------------------------------------------------------------------ prazos
def agenda(qs, hoje=None):
    """Separa os prazos pendentes em vencidos, de hoje, dos próximos 7 dias e posteriores."""
    hoje = hoje or timezone.localdate()
    pend = qs.filter(status="PENDENTE").select_related("processo__cliente", "responsavel")
    return {
        "vencidos": list(pend.filter(data_limite__lt=hoje)),
        "hoje": list(pend.filter(data_limite=hoje)),
        "semana": list(pend.filter(data_limite__gt=hoje, data_limite__lte=hoje + timedelta(days=7))),
        "depois": list(pend.filter(data_limite__gt=hoje + timedelta(days=7))[:50]),
    }


def avisar_prazos(hoje=None):
    """E-mail ao responsável PRAZO_AVISO_DIAS antes do prazo e de novo no dia (ou se já venceu).
    Cada aviso sai uma única vez. Devolve a quantidade de e-mails enviados."""
    hoje = hoje or timezone.localdate()
    limite = hoje + timedelta(days=settings.PRAZO_AVISO_DIAS)
    enviados = 0
    for p in (Prazo.objects.filter(status="PENDENTE", data_limite__lte=limite)
              .select_related("processo__cliente", "responsavel")):
        no_dia = p.data_limite <= hoje
        if (no_dia and p.avisado_no_dia) or (not no_dia and p.avisado_antes):
            continue
        if p.responsavel.email:
            dias = (p.data_limite - hoje).days
            quando = "VENCIDO" if dias < 0 else "vence HOJE" if dias == 0 else f"vence em {dias} dia(s)"
            try:
                send_mail(
                    f"Prazo {quando}: {p.descricao[:80]}",
                    f"{p.get_tipo_display()}: {p.descricao}\n"
                    f"Data limite: {p.data_limite:%d/%m/%Y}{f' às {p.hora:%H:%M}' if p.hora else ''}\n"
                    f"Processo: {p.processo}\nCliente: {p.processo.cliente.nome}\n\n"
                    f"{settings.SITE_URL}{reverse('juridico:processo_detalhe', args=[p.processo_id])}",
                    settings.DEFAULT_FROM_EMAIL, [p.responsavel.email], fail_silently=False)
                enviados += 1
            except Exception:  # noqa: BLE001 – sem SMTP agora: tenta de novo na próxima rodada
                continue
        if no_dia:
            p.avisado_no_dia = True
        else:
            p.avisado_antes = True
        p.save(update_fields=["avisado_no_dia", "avisado_antes"])
    return enviados


# ------------------------------------------------------------------ financeiro
def somar_meses(data, meses):
    """Mesma data N meses depois (dia 31 vira o último dia do mês quando não existe)."""
    m = data.month - 1 + meses
    ano, mes = data.year + m // 12, m % 12 + 1
    return data.replace(year=ano, month=mes, day=min(data.day, calendar.monthrange(ano, mes)[1]))


def gerar_parcelas(lancamento, parcelas):
    """Grava o lançamento em N parcelas mensais de mesmo valor. Devolve a lista criada."""
    if parcelas <= 1:
        lancamento.save()
        return [lancamento]
    base, primeiro = lancamento.descricao, lancamento.vencimento
    criados = []
    for i in range(parcelas):
        lancamento.pk = None
        lancamento._state.adding = True
        lancamento.descricao = f"{base} ({i + 1}/{parcelas})"[:200]
        lancamento.vencimento = somar_meses(primeiro, i)
        lancamento.save()
        criados.append(Lancamento.objects.get(pk=lancamento.pk))
    return criados


def _total(qs):
    return qs.aggregate(t=Sum("valor"))["t"] or 0


def resumo_financeiro(qs=None, hoje=None):
    """Totais para os cartões do financeiro (sobre o queryset informado ou todos os lançamentos)."""
    qs = Lancamento.objects.all() if qs is None else qs
    hoje = hoje or timezone.localdate()
    receber = qs.filter(natureza="RECEBER")
    mes = {"pago_em__year": hoje.year, "pago_em__month": hoje.month}
    return {
        "a_receber": _total(receber.filter(pago_em__isnull=True)),
        "em_atraso": _total(receber.filter(pago_em__isnull=True, vencimento__lt=hoje)),
        "recebido_mes": _total(receber.filter(**mes)),
        "despesas_abertas": _total(qs.filter(natureza="PAGAR", pago_em__isnull=True)),
    }
