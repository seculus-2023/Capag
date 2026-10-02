"""Automações do CRM: lembretes de reunião, alertas de follow-up, nutrição de contatos
e indicadores comerciais (conversão, maturação, motivos de perda)."""
import re
from datetime import timedelta, timezone as dt_timezone
from statistics import median

import requests
from django.conf import settings
from django.core import signing
from django.core.mail import EmailMessage
from django.urls import reverse
from django.utils import timezone

from core.envio import link_wame, whatsapp_api_configurada

from .models import AREAS, Contato, Conteudo, Mensagem, Oportunidade, Reuniao

SALT_DESCADASTRO = "crm-descadastro"


# ------------------------------------------------------------------ ética (OAB)
# Provimento 205/2021 do CFOAB: a publicidade é informativa e sóbria. É vedado prometer
# resultado, divulgar preço/gratuidade/desconto, se autopromover e chamar para contratação.
# Os padrões miram a oferta de serviços, não os termos técnicos ("seguro garantia",
# "desconto na transação", "justiça gratuita" continuam permitidos).
TERMOS_VEDADOS = [
    (r"\bgarantimos\b|\b(resultado|[êe]xito|sucesso) (garantido|certo)\b|\bgarantia de (resultado|[êe]xito|sucesso|vit[óo]ria)\b"
     r"|\bcausa ganha\b|\b100\s?% de ([êe]xito|sucesso|aprova[çc][ãa]o)\b", "promessa ou garantia de resultado"),
    (r"\b(consulta|an[áa]lise|avalia[çc][ãa]o|diagn[óo]stico) (gr[áa]tis|gratuit[ao])\b|\bsem compromisso\b"
     r"|\b(consulta|atendimento) sem custo\b", "oferta de gratuidade"),
    (r"\bhonor[áa]rios? (a partir|de apenas|reduzidos|promocionais)\b|\bdescontos? (em|nos|de) honor[áa]rios\b"
     r"|\bpre[çc]os? (baixos?|acess[íi]ve(l|is)|especia(l|is)|promociona(l|is))\b|\bpromo[çc][ãa]o\b|\bparcelamos\b",
     "divulgação de valores, descontos ou promoções de serviços"),
    (r"\bmelhor(es)? (escrit[óo]rio|advogad\w+)\b|\bo maior escrit[óo]rio\b|\bl[íi]der(es)? (em|no|na)\b|\bn[ºo°]\s?1\b",
     "autopromoção ou comparação com outros escritórios"),
    (r"\bcontrate\b|\bligue (agora|j[áa])\b|\bagende (agora|j[áa])\b|\bn[ãa]o perca\b|\b[úu]ltimas vagas\b|\bcorra\b"
     r"|\bfale agora\b|\baproveite\b", "chamada para contratação (captação de clientela)"),
]


def verificar_oab(texto):
    """Devolve os trechos que ferem as regras de publicidade da advocacia: [(trecho, motivo)].
    É um filtro automático de apoio; a aprovação final é sempre de um advogado."""
    achados = []
    for padrao, motivo in TERMOS_VEDADOS:
        for m in re.finditer(padrao, texto or "", flags=re.IGNORECASE):
            achados.append((m.group(0), motivo))
    return achados


# ------------------------------------------------------------------ WhatsApp (Cloud API)
def _whatsapp_post(payload):
    base = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
    r = requests.post(f"{base}/messages", timeout=30, json={"messaging_product": "whatsapp", **payload},
                      headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"})
    r.raise_for_status()
    return r.text


def _registrar(mensagem, enviar):
    """Executa o envio e grava o resultado (ENVIADO/ERRO) na mensagem."""
    try:
        mensagem.resposta = enviar() or ""
        mensagem.status = "ENVIADO"
    except Exception as exc:  # noqa: BLE001 – qualquer falha de SMTP/API fica registrada
        resp = getattr(exc, "response", None)
        mensagem.status = "ERRO"
        mensagem.resposta = f"{exc}\n{resp.text if resp is not None else ''}".strip()
    mensagem.save()
    return mensagem


# ------------------------------------------------------------------ lembretes de reunião
def dados_lembrete(reuniao):
    inicio = timezone.localtime(reuniao.inicio)
    return {
        "nome": reuniao.contato.primeiro_nome,
        "data": inicio.strftime("%d/%m/%Y"),
        "hora": inicio.strftime("%H:%M"),
        "local": reuniao.local or reuniao.get_modalidade_display(),
        "advogado": reuniao.advogado.get_full_name() or reuniao.advogado.username,
    }


def texto_lembrete(reuniao):
    d = dados_lembrete(reuniao)
    return (f"Olá, {d['nome']}! Lembramos da sua consulta com {d['advogado']} no dia {d['data']} às {d['hora']} "
            f"({reuniao.get_modalidade_display().lower()}"
            f"{': ' + reuniao.local if reuniao.local else ''}).\n"
            f"Se precisar remarcar, é só responder esta mensagem.\n\n{settings.ESCRITORIO_NOME}")


def _ics(reuniao):
    """Convite de calendário (.ics) anexado ao e-mail de lembrete."""
    def utc(dt):
        return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def esc(s):
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CAPAG CRM//PT-BR", "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:reuniao-{reuniao.pk}@capag-crm", f"DTSTAMP:{utc(timezone.now())}",
        f"DTSTART:{utc(reuniao.inicio)}", f"DTEND:{utc(reuniao.fim)}",
        f"SUMMARY:{esc('Consulta – ' + settings.ESCRITORIO_NOME)}",
        f"LOCATION:{esc(reuniao.local or reuniao.get_modalidade_display())}",
        "END:VEVENT", "END:VCALENDAR", ""])


def canais_lembrete(reuniao):
    """Canais em que o lembrete pode sair sozinho. WhatsApp só com a Cloud API configurada."""
    c = reuniao.contato
    canais = ["EMAIL"] if c.email else []
    if c.whatsapp and whatsapp_api_configurada():
        canais.append("WHATSAPP")
    return canais


def lembrar_reuniao(reuniao, canais=None):
    """Envia o lembrete da reunião pelos canais disponíveis e devolve as mensagens registradas."""
    c = reuniao.contato
    texto = texto_lembrete(reuniao)
    saida = []
    for canal in canais or canais_lembrete(reuniao):
        if canal == "EMAIL":
            def enviar():
                email = EmailMessage(f"Lembrete da sua consulta – {dados_lembrete(reuniao)['data']}", texto,
                                     settings.DEFAULT_FROM_EMAIL, [c.email])
                email.attach("consulta.ics", _ics(reuniao), "text/calendar")
                email.send(fail_silently=False)
            destino = c.email
        else:
            def enviar():
                if settings.WHATSAPP_TEMPLATE_LEMBRETE:
                    d = dados_lembrete(reuniao)
                    return _whatsapp_post({"to": c.whatsapp, "type": "template", "template": {
                        "name": settings.WHATSAPP_TEMPLATE_LEMBRETE,
                        "language": {"code": settings.WHATSAPP_TEMPLATE_IDIOMA},
                        "components": [{"type": "body", "parameters": [
                            {"type": "text", "text": d[k]} for k in ("nome", "data", "hora", "local")]}]}})
                return _whatsapp_post({"to": c.whatsapp, "type": "text", "text": {"body": texto}})
            destino = c.whatsapp
        saida.append(_registrar(Mensagem(contato=c, tipo="LEMBRETE", canal=canal, reuniao=reuniao, destino=destino), enviar))
    return saida


def enviar_lembretes(agora=None):
    """Lembra as reuniões agendadas que começam nas próximas CRM_LEMBRETE_HORAS horas.
    Cada reunião recebe um lembrete por canal (ou um novo, se for remarcada)."""
    agora = agora or timezone.now()
    limite = agora + timedelta(hours=settings.CRM_LEMBRETE_HORAS)
    enviadas = []
    for r in (Reuniao.objects.select_related("oportunidade__contato", "advogado")
              .filter(status="AGENDADA", inicio__gt=agora, inicio__lte=limite)):
        ja = r.mensagens.filter(tipo="LEMBRETE")
        if r.remarcada_em:
            ja = ja.filter(enviado_em__gte=r.remarcada_em)
        feitos = set(ja.values_list("canal", flat=True))
        pendentes = [c for c in canais_lembrete(r) if c not in feitos]
        if pendentes:
            enviadas += lembrar_reuniao(r, pendentes)
    return enviadas


def link_wame_lembrete(reuniao):
    """Sem a Cloud API, o lembrete por WhatsApp é enviado pelo advogado com um clique."""
    c = reuniao.contato
    return link_wame(c.whatsapp, texto_lembrete(reuniao)) if c.whatsapp else ""


# ------------------------------------------------------------------ follow-up
def pendentes_followup(qs=None):
    """Propostas enviadas há mais de CRM_FOLLOWUP_DIAS dias sem novo contato com o cliente."""
    qs = Oportunidade.objects.all() if qs is None else qs
    lista = [o for o in qs.filter(etapa="PROPOSTA").select_related("contato", "responsavel") if o.precisa_followup]
    lista.sort(key=lambda o: -o.dias_sem_contato)
    return lista


# ------------------------------------------------------------------ nutrição
def link_descadastro(contato):
    token = signing.Signer(salt=SALT_DESCADASTRO).sign(str(contato.token))
    return settings.SITE_URL + reverse("crm:descadastrar", args=[token])


def contato_do_token(token):
    """Devolve o contato do link de descadastro ou levanta signing.BadSignature."""
    uuid_str = signing.Signer(salt=SALT_DESCADASTRO).unsign(token)
    return Contato.objects.filter(token=uuid_str).first()


def destinatarios(conteudo):
    """Somente quem autorizou o recebimento (opt-in), tem e-mail e ainda não recebeu este conteúdo."""
    qs = Contato.objects.filter(aceita_conteudo=True).exclude(email="")
    if conteudo.area:
        qs = qs.filter(area_interesse=conteudo.area)
    return qs.exclude(mensagens__conteudo=conteudo, mensagens__status="ENVIADO")


def corpo_conteudo(conteudo, contato):
    partes = [f"Olá, {contato.primeiro_nome}.", "", conteudo.texto.strip()]
    if conteudo.link:
        partes += ["", f"Leia mais: {conteudo.link}"]
    partes += ["", "—", settings.ESCRITORIO_NOME + (f" · {settings.ESCRITORIO_OAB}" if settings.ESCRITORIO_OAB else ""),
               "Conteúdo de caráter exclusivamente informativo, enviado porque você autorizou o recebimento "
               "(Provimento 205/2021 do Conselho Federal da OAB).",
               f"Para deixar de receber: {link_descadastro(contato)}"]
    return "\n".join(partes)


def disparar_conteudo(conteudo):
    """Envia o conteúdo aprovado, por e-mail, a cada destinatário. Devolve as mensagens registradas."""
    if conteudo.status == "RASCUNHO":
        raise ValueError("O conteúdo precisa ser aprovado por um advogado antes do envio.")
    problemas = verificar_oab(f"{conteudo.titulo}\n{conteudo.texto}")
    if problemas:
        raise ValueError("Conteúdo fora das regras de publicidade da OAB: "
                         + "; ".join(f"“{t}” ({m})" for t, m in problemas))
    saida = []
    for c in destinatarios(conteudo):
        def enviar(c=c):
            EmailMessage(conteudo.titulo, corpo_conteudo(conteudo, c), settings.DEFAULT_FROM_EMAIL, [c.email]
                         ).send(fail_silently=False)
        saida.append(_registrar(Mensagem(contato=c, tipo="NUTRICAO", canal="EMAIL", conteudo=conteudo, destino=c.email), enviar))
    conteudo.status = "ENVIADO"
    conteudo.enviado_em = timezone.now()
    conteudo.save(update_fields=["status", "enviado_em"])
    return saida


def disparar_conteudos_pendentes(hoje=None):
    hoje = hoje or timezone.localdate()
    saida = []
    for conteudo in Conteudo.objects.filter(status="APROVADO", enviar_a_partir__lte=hoje):
        try:
            saida += disparar_conteudo(conteudo)
        except ValueError:
            continue  # conteúdo reprovado no filtro da OAB fica parado até ser corrigido
    return saida


# ------------------------------------------------------------------ inteligência comercial
def _pct(parte, total):
    return round(100 * parte / total, 1) if total else None


def _grupo(nome, itens):
    fechados = [o for o in itens if o.etapa == "FECHADO"]
    perdidos = [o for o in itens if o.etapa == "PERDIDO"]
    dias = [o.dias_maturacao for o in fechados if o.dias_maturacao is not None]
    return {
        "nome": nome, "total": len(itens), "fechados": len(fechados), "perdidos": len(perdidos),
        "abertos": len(itens) - len(fechados) - len(perdidos),
        "conversao": _pct(len(fechados), len(itens)),
        "conversao_decididos": _pct(len(fechados), len(fechados) + len(perdidos)),
        "maturacao_media": round(sum(dias) / len(dias), 1) if dias else None,
        "maturacao_mediana": median(dias) if dias else None,
        "maturacao_min": min(dias) if dias else None,
        "maturacao_max": max(dias) if dias else None,
        "honorarios_fechados": sum(o.valor_estimado for o in fechados),
    }


def indicadores(qs):
    """Taxa de conversão, tempo de maturação e motivos de perda dos atendimentos do queryset."""
    itens = list(qs.select_related("contato"))
    perdidos = [o for o in itens if o.etapa == "PERDIDO"]
    motivos = []
    for cod, nome in Oportunidade.MOTIVOS:
        n = sum(1 for o in perdidos if (o.motivo_perda or "OUTRO") == cod)
        if n:
            motivos.append({"nome": nome, "n": n, "pct": _pct(n, len(perdidos))})
    motivos.sort(key=lambda m: -m["n"])
    funil = [{"nome": nome, "n": sum(1 for o in itens if o.etapa == cod), "cod": cod} for cod, nome in Oportunidade.ETAPAS]
    for f in funil:
        f["pct"] = _pct(f["n"], len(itens)) or 0
    return {
        "geral": _grupo("Todas as áreas", itens),
        "por_area": [_grupo(nome, [o for o in itens if o.area == cod]) for cod, nome in AREAS],
        "por_origem": [g for g in (_grupo(nome, [o for o in itens if o.contato.origem == cod])
                                   for cod, nome in Contato.ORIGENS) if g["total"]],
        "motivos": motivos, "funil": funil,
    }
