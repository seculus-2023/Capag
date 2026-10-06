"""
Configurações do projeto CAPAG (PGFN).
Todas as credenciais vêm do arquivo .env (veja .env.example).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return str(env(key, default)).lower() in ("1", "true", "yes", "sim")


SECRET_KEY = env("SECRET_KEY", "troque-esta-chave-em-producao")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [h.strip() for h in env("CSRF_TRUSTED_ORIGINS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "crm",
    "juridico",
    "consultoria",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.perfis.contexto",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------- PostgreSQL
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "capag"),
        "USER": env("DB_USER", "postgres"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "OPTIONS": {"options": f"-c search_path={env('DB_SCHEMA', 'public')}"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Cuiaba"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise serve os estáticos quando DEBUG=False (rode "collectstatic" no deploy)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# ---------------------------------------------------------------- E-mail (SMTP)
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "capag@localhost")

# ---------------------------------------------------------------- WhatsApp
# Se WHATSAPP_TOKEN e WHATSAPP_PHONE_NUMBER_ID estiverem preenchidos, o PDF é enviado
# pela WhatsApp Cloud API (Meta). Caso contrário, o sistema abre o link wa.me com o
# resumo e um link público (assinado) para baixar o PDF.
WHATSAPP_TOKEN = env("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = env("WHATSAPP_API_VERSION", "v20.0")

# URL pública do sistema, usada nos links enviados por WhatsApp/e-mail
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
# Validade (dias) do link público do PDF
LINK_PDF_VALIDADE_DIAS = int(env("LINK_PDF_VALIDADE_DIAS", "15"))

# ---------------------------------------------------------------- CRM
# Identificação do escritório no rodapé dos lembretes e dos conteúdos informativos
ESCRITORIO_NOME = env("ESCRITORIO_NOME", "Escritório de Advocacia")
ESCRITORIO_OAB = env("ESCRITORIO_OAB", "")
# Proposta sem novo contato há mais de N dias gera alerta de follow-up no painel do advogado
CRM_FOLLOWUP_DIAS = int(env("CRM_FOLLOWUP_DIAS", "3"))
# O lembrete da consulta sai N horas antes do horário marcado
CRM_LEMBRETE_HORAS = int(env("CRM_LEMBRETE_HORAS", "24"))
# O responsável recebe e-mail N dias antes do prazo processual e de novo no dia
PRAZO_AVISO_DIAS = int(env("PRAZO_AVISO_DIAS", "3"))
# Template aprovado na Meta para o lembrete por WhatsApp, com 4 variáveis no corpo:
# {{1}} nome, {{2}} data, {{3}} hora, {{4}} local. Vazio = mensagem de texto livre
# (só é entregue se o cliente falou com o número nas últimas 24 horas).
WHATSAPP_TEMPLATE_LEMBRETE = env("WHATSAPP_TEMPLATE_LEMBRETE", "")
WHATSAPP_TEMPLATE_IDIOMA = env("WHATSAPP_TEMPLATE_IDIOMA", "pt_BR")
