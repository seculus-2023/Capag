import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from crm.models import AREAS, Contato, Oportunidade

COBRANCAS = [("FIXO", "Valor fixo"), ("MENSAL", "Mensalidade"), ("EXITO", "Somente êxito")]


def _linhas(texto):
    return [x.strip(" -•\t") for x in (texto or "").splitlines() if x.strip(" -•\t")]


def pct(valor):
    """10.00 → "10"; 12.50 → "12,5"."""
    return f"{valor.normalize():f}".replace(".", ",")


def _validade_padrao():
    return timezone.localdate() + timedelta(days=15)


class Produto(models.Model):
    """Serviço do catálogo da consultoria. O preço é de referência: cada proposta pode ajustá-lo."""
    nome = models.CharField("Nome", max_length=150)
    area = models.CharField("Área do direito", max_length=10, choices=AREAS)
    cobranca = models.CharField("Forma de cobrança", max_length=6, choices=COBRANCAS, default="FIXO")
    valor_referencia = models.DecimalField("Valor de referência", max_digits=14, decimal_places=2, default=Decimal("0.00"),
                                           help_text="Valor fixo ou da mensalidade. Pode ser ajustado em cada proposta.")
    percentual_exito = models.DecimalField("Êxito (%)", max_digits=5, decimal_places=2, default=Decimal("0.00"),
                                           help_text="Percentual sobre o benefício obtido (0 = sem êxito).")
    prazo_dias = models.PositiveSmallIntegerField("Prazo de entrega (dias)", default=30)
    escopo = models.TextField("Escopo", help_text="O que está incluído no serviço. Vai para o PDF da proposta.")
    entregas = models.TextField("Etapas de entrega", blank=True,
                                help_text="Uma por linha. Viram o checklist do projeto quando a proposta é aceita.")
    documentos = models.TextField("Documentos exigidos do cliente", blank=True, help_text="Um por linha.")
    usa_capag = models.BooleanField("Usa a análise de CAPAG",
                                    default=False, help_text="A proposta pode trazer os números da análise do cliente.")
    ativo = models.BooleanField("Ativo", default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["area", "nome"]
        verbose_name = "Produto da consultoria"
        verbose_name_plural = "Produtos da consultoria"

    def __str__(self):
        return self.nome

    @property
    def lista_entregas(self):
        return _linhas(self.entregas)

    @property
    def lista_documentos(self):
        return _linhas(self.documentos)


class Proposta(models.Model):
    """Proposta de honorários montada com produtos do catálogo, ligada a um atendimento do funil."""
    STATUS = [("RASCUNHO", "Rascunho"), ("ENVIADA", "Enviada"), ("ACEITA", "Aceita"), ("RECUSADA", "Recusada")]

    oportunidade = models.ForeignKey(Oportunidade, on_delete=models.CASCADE, related_name="propostas")
    analise = models.ForeignKey("core.AnaliseCapag", verbose_name="Análise de CAPAG anexada", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="propostas",
                                help_text="Opcional. Os números da análise entram no PDF como diagnóstico.")
    status = models.CharField(max_length=8, choices=STATUS, default="RASCUNHO")
    validade = models.DateField("Válida até", default=_validade_padrao)
    parcelas = models.PositiveSmallIntegerField("Parcelas dos valores fixos", default=1)
    meses_mensalidade = models.PositiveSmallIntegerField("Meses de mensalidade", default=12,
                                                         help_text="Usado só nos itens cobrados por mês.")
    primeiro_vencimento = models.DateField("Primeiro vencimento", null=True, blank=True,
                                           help_text="Em branco = 30 dias depois do aceite.")
    condicoes = models.TextField("Condições e observações", blank=True)
    enviada_em = models.DateField(null=True, blank=True, editable=False)
    respondida_em = models.DateField(null=True, blank=True, editable=False)
    motivo_recusa = models.CharField("Motivo da recusa", max_length=250, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Proposta"

    def __str__(self):
        return f"Proposta {self.numero} – {self.contato.nome}"

    def get_absolute_url(self):
        return reverse("consultoria:proposta_detalhe", args=[self.pk])

    @property
    def numero(self):
        return f"{timezone.localtime(self.criado_em).year}/{self.pk:04d}" if self.pk and self.criado_em else "—"

    @property
    def contato(self):
        return self.oportunidade.contato

    @property
    def editavel(self):
        return self.status == "RASCUNHO"

    @property
    def expirada(self):
        return self.status == "ENVIADA" and self.validade < timezone.localdate()

    def _soma(self, cobranca):
        return sum((i.valor for i in self.itens.all() if i.cobranca == cobranca), Decimal("0.00"))

    @property
    def total_fixo(self):
        return self._soma("FIXO")

    @property
    def total_mensal(self):
        return self._soma("MENSAL")

    @property
    def total_estimado(self):
        """Valor fixo + mensalidades do período (o êxito não entra: depende do resultado)."""
        return self.total_fixo + self.total_mensal * self.meses_mensalidade

    @property
    def tem_exito(self):
        return any(i.percentual_exito for i in self.itens.all())


class ItemProposta(models.Model):
    proposta = models.ForeignKey(Proposta, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, verbose_name="Produto", on_delete=models.PROTECT, related_name="itens")
    descricao = models.CharField("Descrição na proposta", max_length=200, blank=True,
                                 help_text="Em branco = nome do produto.")
    cobranca = models.CharField(max_length=6, choices=COBRANCAS, editable=False)
    valor = models.DecimalField("Valor", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    percentual_exito = models.DecimalField("Êxito (%)", max_digits=5, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["pk"]
        verbose_name = "Item da proposta"
        verbose_name_plural = "Itens da proposta"

    def __str__(self):
        return self.descricao or self.produto.nome

    def save(self, *args, **kwargs):
        self.cobranca = self.produto.cobranca
        if not self.descricao:
            self.descricao = self.produto.nome
        super().save(*args, **kwargs)


class Projeto(models.Model):
    """Execução da consultoria contratada: nasce do aceite da proposta, com checklist de entregas e documentos."""
    STATUS = [("ANDAMENTO", "Em andamento"), ("CONCLUIDO", "Concluído"), ("CANCELADO", "Cancelado")]

    proposta = models.OneToOneField(Proposta, on_delete=models.PROTECT, related_name="projeto")
    cliente = models.ForeignKey(Contato, on_delete=models.PROTECT, related_name="projetos_consultoria")
    titulo = models.CharField("Título", max_length=200)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Responsável", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="projetos_consultoria")
    inicio = models.DateField("Início", default=timezone.localdate)
    prazo = models.DateField("Prazo de entrega")
    status = models.CharField(max_length=9, choices=STATUS, default="ANDAMENTO")
    concluido_em = models.DateField(null=True, blank=True, editable=False)
    observacoes = models.TextField("Observações", blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["prazo", "pk"]
        verbose_name = "Projeto de consultoria"
        verbose_name_plural = "Projetos de consultoria"

    def __str__(self):
        return f"{self.titulo} – {self.cliente.nome}"

    def get_absolute_url(self):
        return reverse("consultoria:projeto_detalhe", args=[self.pk])

    @property
    def progresso(self):
        etapas = list(self.etapas.all())
        if not etapas:
            return 0
        return round(100 * sum(1 for e in etapas if e.concluida_em) / len(etapas))

    @property
    def atrasado(self):
        return self.status == "ANDAMENTO" and self.prazo < timezone.localdate()


class Etapa(models.Model):
    TIPOS = [("DOCUMENTO", "Documento do cliente"), ("ENTREGA", "Entrega")]

    projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name="etapas")
    tipo = models.CharField(max_length=9, choices=TIPOS, default="ENTREGA")
    descricao = models.CharField("Descrição", max_length=250)
    ordem = models.PositiveSmallIntegerField(default=0)
    concluida_em = models.DateTimeField(null=True, blank=True)
    concluida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")

    class Meta:
        ordering = ["ordem", "pk"]
        verbose_name = "Etapa do projeto"
        verbose_name_plural = "Etapas do projeto"

    def __str__(self):
        return self.descricao
