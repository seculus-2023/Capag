import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from crm.models import AREAS, Contato


class Processo(models.Model):
    TIPOS = [("JUDICIAL", "Judicial"), ("ADMINISTRATIVO", "Administrativo")]
    POSICOES = [("AUTOR", "Autor / requerente"), ("REU", "Réu / requerido"), ("INTERESSADO", "Interessado / terceiro")]
    STATUS = [("ATIVO", "Ativo"), ("SUSPENSO", "Suspenso"), ("ENCERRADO", "Encerrado")]

    cliente = models.ForeignKey(Contato, verbose_name="Cliente", on_delete=models.PROTECT, related_name="processos")
    tipo = models.CharField("Tipo", max_length=14, choices=TIPOS, default="JUDICIAL")
    numero = models.CharField("Número do processo", max_length=60, blank=True,
                              help_text="Número CNJ ou do processo administrativo (PGFN, Sefaz, CARF, Ibama...).")
    titulo = models.CharField("Assunto", max_length=200, help_text="Ex.: Execução fiscal – ICMS 2021.")
    area = models.CharField("Área do direito", max_length=10, choices=AREAS)
    orgao = models.CharField("Vara / órgão", max_length=150, blank=True,
                             help_text="Ex.: 2ª Vara Federal de Cuiabá, PGFN, Sefaz-MT, Sema-MT.")
    parte_contraria = models.CharField("Parte contrária", max_length=200, blank=True)
    posicao = models.CharField("Posição do cliente", max_length=11, choices=POSICOES, default="AUTOR")
    fase = models.CharField("Fase atual", max_length=100, blank=True, help_text="Ex.: Contestação, recurso, cumprimento.")
    valor_causa = models.DecimalField("Valor da causa", max_digits=16, decimal_places=2, default=Decimal("0.00"))
    data_distribuicao = models.DateField("Data de distribuição / protocolo", null=True, blank=True)
    status = models.CharField("Situação", max_length=9, choices=STATUS, default="ATIVO")
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Advogado responsável", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="processos")
    observacoes = models.TextField("Observações", blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Processo"

    def __str__(self):
        return f"{self.numero or 'Sem número'} – {self.titulo}"

    def get_absolute_url(self):
        return reverse("juridico:processo_detalhe", args=[self.pk])


class Andamento(models.Model):
    processo = models.ForeignKey(Processo, on_delete=models.CASCADE, related_name="andamentos")
    data = models.DateField("Data", default=timezone.localdate)
    descricao = models.TextField("Andamento")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "Andamento"


class Prazo(models.Model):
    TIPOS = [("PRAZO", "Prazo processual"), ("AUDIENCIA", "Audiência"), ("DILIGENCIA", "Diligência / providência")]
    STATUS = [("PENDENTE", "Pendente"), ("CUMPRIDO", "Cumprido"), ("CANCELADO", "Cancelado")]

    processo = models.ForeignKey(Processo, on_delete=models.CASCADE, related_name="prazos")
    tipo = models.CharField("Tipo", max_length=10, choices=TIPOS, default="PRAZO")
    descricao = models.CharField("O que deve ser feito", max_length=250)
    data_limite = models.DateField("Data limite")
    hora = models.TimeField("Hora", null=True, blank=True, help_text="Para audiências.")
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Responsável", on_delete=models.PROTECT,
                                    related_name="prazos")
    status = models.CharField(max_length=9, choices=STATUS, default="PENDENTE")
    observacoes = models.TextField("Observações", blank=True)
    cumprido_em = models.DateTimeField(null=True, blank=True, editable=False)
    cumprido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
                                     on_delete=models.SET_NULL, related_name="+")
    avisado_antes = models.BooleanField(default=False, editable=False)
    avisado_no_dia = models.BooleanField(default=False, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_limite", "hora", "pk"]
        verbose_name = "Prazo"

    def __str__(self):
        return f"{self.data_limite:%d/%m/%Y} – {self.descricao}"

    @property
    def dias_restantes(self):
        return (self.data_limite - timezone.localdate()).days

    @property
    def situacao(self):
        """('vencido' | 'hoje' | 'proximo' | 'futuro' | status final, cor do Bootstrap)."""
        if self.status != "PENDENTE":
            return (self.status.lower(), "success" if self.status == "CUMPRIDO" else "secondary")
        d = self.dias_restantes
        if d < 0:
            return ("vencido", "danger")
        if d == 0:
            return ("hoje", "danger")
        return ("proximo", "warning") if d <= settings.PRAZO_AVISO_DIAS else ("futuro", "info")


class Lancamento(models.Model):
    """Honorário a receber do cliente ou despesa do caso (custas, deslocamento...)."""
    NATUREZAS = [("RECEBER", "Honorário a receber"), ("PAGAR", "Despesa do caso")]
    CATEGORIAS = [("CONTRATUAL", "Honorários contratuais"), ("EXITO", "Honorários de êxito"),
                  ("MENSAL", "Mensalidade / partido"), ("SUCUMBENCIA", "Honorários de sucumbência"),
                  ("REEMBOLSO", "Reembolso de despesa"), ("CUSTAS", "Custas e taxas"),
                  ("DESLOCAMENTO", "Deslocamento / diligência"), ("OUTRO", "Outro")]
    FORMAS = [("PIX", "Pix"), ("BOLETO", "Boleto"), ("TRANSFERENCIA", "Transferência"), ("CARTAO", "Cartão"),
              ("DINHEIRO", "Dinheiro"), ("ALVARA", "Alvará / levantamento")]

    cliente = models.ForeignKey(Contato, verbose_name="Cliente", on_delete=models.PROTECT, related_name="lancamentos")
    processo = models.ForeignKey(Processo, verbose_name="Processo", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="lancamentos")
    natureza = models.CharField("Natureza", max_length=7, choices=NATUREZAS, default="RECEBER")
    categoria = models.CharField("Categoria", max_length=12, choices=CATEGORIAS, default="CONTRATUAL")
    descricao = models.CharField("Descrição", max_length=200)
    valor = models.DecimalField("Valor", max_digits=14, decimal_places=2)
    vencimento = models.DateField("Vencimento")
    pago_em = models.DateField("Pago em", null=True, blank=True)
    forma_pagamento = models.CharField("Forma de pagamento", max_length=13, choices=FORMAS, blank=True)
    observacoes = models.TextField("Observações", blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vencimento", "pk"]
        verbose_name = "Lançamento financeiro"
        verbose_name_plural = "Lançamentos financeiros"

    def __str__(self):
        return f"{self.descricao} – {self.vencimento:%d/%m/%Y}"

    @property
    def situacao(self):
        if self.pago_em:
            return ("Pago", "success")
        if self.vencimento < timezone.localdate():
            return ("Em atraso", "danger")
        return ("Em aberto", "secondary")


EXTENSOES = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".xls", ".xlsx", ".ods", ".csv",
             ".jpg", ".jpeg", ".png", ".zip", ".msg", ".eml", ".p7s"}
TAMANHO_MAX_MB = 25


def validar_arquivo(arquivo):
    ext = os.path.splitext(arquivo.name)[1].lower()
    if ext not in EXTENSOES:
        raise ValidationError(f"Tipo de arquivo não aceito ({ext or 'sem extensão'}). Use PDF, Word, Excel, imagem ou ZIP.")
    if arquivo.size > TAMANHO_MAX_MB * 1024 * 1024:
        raise ValidationError(f"Arquivo maior que {TAMANHO_MAX_MB} MB.")


def caminho_documento(instancia, nome):
    """Guarda com nome aleatório; o nome original fica no banco (evita colisão e nomes inseguros)."""
    ext = os.path.splitext(nome)[1].lower()
    return f"clientes/{instancia.cliente_id}/{uuid.uuid4().hex}{ext}"


class Documento(models.Model):
    CATEGORIAS = [("PROCURACAO", "Procuração"), ("CONTRATO", "Contrato de honorários"), ("PETICAO", "Petição"),
                  ("DECISAO", "Decisão / intimação"), ("COMPROVANTE", "Comprovante / guia"),
                  ("FISCAL", "Documento fiscal / contábil"), ("PESSOAL", "Documento pessoal / societário"),
                  ("OUTRO", "Outro")]

    cliente = models.ForeignKey(Contato, on_delete=models.PROTECT, related_name="documentos")
    processo = models.ForeignKey(Processo, verbose_name="Processo", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="documentos")
    titulo = models.CharField("Título", max_length=200, blank=True, help_text="Em branco = nome do arquivo.")
    categoria = models.CharField("Categoria", max_length=11, choices=CATEGORIAS, default="OUTRO")
    arquivo = models.FileField("Arquivo", upload_to=caminho_documento, max_length=300, validators=[validar_arquivo])
    nome_original = models.CharField(max_length=255, editable=False)
    tamanho = models.PositiveIntegerField(default=0, editable=False)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Documento"

    def __str__(self):
        return self.titulo or self.nome_original

    def save(self, *args, **kwargs):
        if self.arquivo and not self.pk:
            self.nome_original = os.path.basename(self.arquivo.name)[:255]
            self.tamanho = self.arquivo.size
            self.titulo = self.titulo or os.path.splitext(self.nome_original)[0][:200]
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        arquivo = self.arquivo
        resultado = super().delete(*args, **kwargs)
        arquivo.delete(save=False)  # remove também o arquivo do disco
        return resultado
