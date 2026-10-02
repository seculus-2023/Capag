"""Envio da análise por e-mail (SMTP) e WhatsApp (Cloud API da Meta ou link wa.me)."""
from datetime import timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.core import signing
from django.core.mail import EmailMessage
from django.urls import reverse

from .models import EnvioCapag
from .pdf import gerar_pdf, nome_arquivo
from .validators import normalizar_whatsapp

SALT = "capag-pdf-publico"


# ------------------------------------------------------------------ link público assinado
def link_publico(analise):
    token = signing.TimestampSigner(salt=SALT).sign(str(analise.token))
    return settings.SITE_URL + reverse("pdf_publico", args=[token])


def validar_token(token):
    """Devolve o UUID da análise ou levanta signing.BadSignature / SignatureExpired."""
    max_age = timedelta(days=settings.LINK_PDF_VALIDADE_DIAS)
    return signing.TimestampSigner(salt=SALT).unsign(token, max_age=max_age)


# ------------------------------------------------------------------ e-mail
def enviar_email(analise, destino, assunto, mensagem, usuario):
    envio = EnvioCapag(analise=analise, canal="EMAIL", destino=destino, mensagem=mensagem, usuario=usuario)
    try:
        email = EmailMessage(assunto, mensagem, settings.DEFAULT_FROM_EMAIL,
                             [d.strip() for d in destino.replace(";", ",").split(",") if d.strip()])
        email.attach(nome_arquivo(analise), gerar_pdf(analise), "application/pdf")
        email.send(fail_silently=False)
        envio.status = "ENVIADO"
    except Exception as exc:  # noqa: BLE001 – queremos registrar qualquer falha de SMTP
        envio.status = "ERRO"
        envio.resposta = str(exc)
    envio.save()
    _marcar_enviada(analise, envio)
    return envio


# ------------------------------------------------------------------ WhatsApp
def whatsapp_api_configurada():
    return bool(settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID)


def link_wame(numero, mensagem):
    return f"https://wa.me/{normalizar_whatsapp(numero)}?text={quote(mensagem)}"


def enviar_whatsapp(analise, numero, mensagem, usuario):
    """Com a Cloud API configurada, envia o PDF como documento.
    Sem ela, registra o envio e devolve o link wa.me (o usuário confirma no WhatsApp)."""
    numero = normalizar_whatsapp(numero)
    envio = EnvioCapag(analise=analise, canal="WHATSAPP", destino=numero, mensagem=mensagem, usuario=usuario)

    if not whatsapp_api_configurada():
        texto = f"{mensagem}\n\nRelatório em PDF: {link_publico(analise)}"
        envio.status = "LINK"
        envio.resposta = link_wame(numero, texto)
        envio.save()
        _marcar_enviada(analise, envio)
        return envio

    base = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    try:
        up = requests.post(f"{base}/media", headers=headers, timeout=30,
                           data={"messaging_product": "whatsapp", "type": "application/pdf"},
                           files={"file": (nome_arquivo(analise), gerar_pdf(analise), "application/pdf")})
        up.raise_for_status()
        media_id = up.json()["id"]
        r = requests.post(f"{base}/messages", headers=headers, timeout=30, json={
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "document",
            "document": {"id": media_id, "filename": nome_arquivo(analise), "caption": mensagem[:1024]},
        })
        r.raise_for_status()
        envio.status = "ENVIADO"
        envio.resposta = r.text
    except Exception as exc:  # noqa: BLE001
        envio.status = "ERRO"
        resp = getattr(exc, "response", None)
        envio.resposta = f"{exc}\n{resp.text if resp is not None else ''}".strip()
    envio.save()
    _marcar_enviada(analise, envio)
    return envio


def _marcar_enviada(analise, envio):
    if envio.status != "ERRO" and analise.status != "ENVIADA":
        type(analise).objects.filter(pk=analise.pk).update(status="ENVIADA")
