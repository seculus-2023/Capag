import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse

from .validators import formatar_cnpj, normalizar_whatsapp, somente_digitos, validar_cnpj, validar_whatsapp

ZERO = Decimal("0.00")
RATINGS = [("A", "A – Alta perspectiva de recuperação"),
           ("B", "B – Média perspectiva de recuperação"),
           ("C", "C – Difícil recuperação"),
           ("D", "D – Irrecuperável")]


def money(**kw):
    return models.DecimalField(max_digits=16, decimal_places=2, default=ZERO, **kw)


class Parametro(models.Model):
    """Parâmetros do cálculo (registro único, editável na tela de Parâmetros).

    Os valores padrão são referências de mercado para simulação. Confira sempre a
    metodologia e a portaria da PGFN vigentes antes de usar num pedido real.
    """
    horizonte_anos = models.PositiveSmallIntegerField(
        "Horizonte de pagamento (anos)", default=5,
        help_text="Art. 21 da Portaria PGFN 6.757/2022: pagamento integral em até 5 anos.")
    fator_rating_a = models.DecimalField("Rating A: CAPAG ≥ dívida ×", max_digits=5, decimal_places=2, default=Decimal("2.00"))
    fator_rating_b = models.DecimalField("Rating B: CAPAG ≥ dívida ×", max_digits=5, decimal_places=2, default=Decimal("1.00"))
    fator_rating_c = models.DecimalField("Rating C: CAPAG ≥ dívida ×", max_digits=5, decimal_places=2, default=Decimal("0.50"))
    percentual_realizacao_bens = models.DecimalField(
        "Realização dos bens livres (%)", max_digits=5, decimal_places=2, default=Decimal("100.00"),
        help_text="Quanto do valor dos bens livres entra na capacidade (deságio de venda).")
    desconto_max_geral = models.DecimalField("Desconto máximo – demais empresas (%)", max_digits=5, decimal_places=2, default=Decimal("65.00"))
    desconto_max_me_epp = models.DecimalField("Desconto máximo – ME/EPP (%)", max_digits=5, decimal_places=2, default=Decimal("70.00"))
    prazo_max_geral = models.PositiveSmallIntegerField("Prazo máximo – demais empresas (meses)", default=120)
    prazo_max_me_epp = models.PositiveSmallIntegerField("Prazo máximo – ME/EPP (meses)", default=145)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Parâmetros do cálculo"
        verbose_name_plural = "Parâmetros do cálculo"

    def __str__(self):
        return "Parâmetros do cálculo da CAPAG"

    @classmethod
    def atual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Empresa(models.Model):
    PORTES = [("ME", "Microempresa"), ("EPP", "Empresa de Pequeno Porte"), ("DEMAIS", "Demais")]

    cnpj = models.CharField("CNPJ", max_length=18, unique=True, validators=[validar_cnpj])
    razao_social = models.CharField("Razão social", max_length=200)
    nome_fantasia = models.CharField("Nome fantasia", max_length=200, blank=True)
    porte = models.CharField("Porte", max_length=6, choices=PORTES, default="DEMAIS")
    atividade = models.CharField("Atividade principal", max_length=200, blank=True)
    endereco = models.CharField("Endereço", max_length=250, blank=True)
    municipio = models.CharField("Município", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    responsavel = models.CharField("Responsável / sócio-administrador", max_length=150, blank=True)
    email = models.EmailField("E-mail", blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True, validators=[validar_whatsapp])
    observacoes = models.TextField("Observações", blank=True)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["razao_social"]
        verbose_name = "Empresa"

    def __str__(self):
        return f"{self.razao_social} ({self.cnpj})"

    def save(self, *args, **kwargs):
        self.cnpj = formatar_cnpj(somente_digitos(self.cnpj))
        self.whatsapp = normalizar_whatsapp(self.whatsapp)
        self.uf = (self.uf or "").upper()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("empresa_detalhe", args=[self.pk])

    @property
    def me_epp(self):
        return self.porte in ("ME", "EPP")

    @property
    def ultima_analise(self):
        return self.analises.order_by("-data_referencia", "-pk").first()


class AnaliseCapag(models.Model):
    STATUS = [("RASCUNHO", "Rascunho"), ("FINALIZADA", "Finalizada"), ("ENVIADA", "Enviada")]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="analises")
    data_referencia = models.DateField("Data de referência")
    descricao = models.CharField("Descrição", max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="RASCUNHO")
    numero_requerimento = models.CharField("Nº requerimento REGULARIZE", max_length=50, blank=True)
    data_ciencia = models.DateField("Data da ciência da CAPAG", null=True, blank=True,
                                    help_text="O pedido de revisão deve ser feito em até 30 dias desta data.")

    # Dívida ativa da União (consolidada)
    divida_principal = money(verbose_name="Principal")
    divida_multa = money(verbose_name="Multa")
    divida_juros = money(verbose_name="Juros")
    divida_encargos = money(verbose_name="Encargos legais")

    # CAPAG informada pela PGFN
    capag_presumida = money(verbose_name="CAPAG presumida (PGFN)")
    rating_presumido = models.CharField("Rating informado pela PGFN", max_length=1, choices=RATINGS, blank=True)

    # Situação real (últimos 12 meses)
    receita_bruta_12m = money(verbose_name="Receita bruta (12 meses)")
    custos_despesas_12m = money(verbose_name="Custos e despesas operacionais (12 meses)",
                                help_text="Folha, combustível, manutenção, impostos correntes, aluguel etc.")
    parcelas_financiamento_12m = money(verbose_name="Parcelas de financiamentos (12 meses)",
                                       help_text="FINAME, CDC, leasing, empréstimos bancários.")
    outras_dividas_12m = money(verbose_name="Outras dívidas a pagar (12 meses)",
                               help_text="Fornecedores, parcelamentos estaduais/municipais, trabalhistas.")
    patrimonio_total = money(verbose_name="Patrimônio em bens (máquinas, veículos, imóveis)")
    bens_onerados = money(verbose_name="Bens alienados / onerados",
                          help_text="Valor dos bens com alienação fiduciária, penhora ou hipoteca.")
    disponibilidades = money(verbose_name="Caixa e bancos")
    ativo_circulante = money(verbose_name="Ativo circulante",
                             help_text="Do balanço/balancete. Usado no índice de liquidez (opcional).")
    passivo_circulante = money(verbose_name="Passivo circulante",
                               help_text="Do balanço/balancete. Usado no índice de liquidez (opcional).")
    situacao_irrecuperavel = models.BooleanField(
        "Situação de irrecuperabilidade (art. 25)", default=False,
        help_text="Falência, recuperação judicial, liquidação, CNPJ inapto etc. Força rating D.")
    justificativa = models.TextField("Justificativa / observações", blank=True)

    # Resultado (gravado no momento do cálculo para manter o histórico)
    resultado_anual_livre = money(editable=False)
    geracao_futura = money(editable=False)
    patrimonio_livre = money(editable=False)
    capag_real = money(editable=False)
    rating_real = models.CharField(max_length=1, choices=RATINGS, blank=True, editable=False)
    rating_presumido_calc = models.CharField(max_length=1, choices=RATINGS, blank=True, editable=False)
    desconto_estimado = money(editable=False)
    valor_apos_desconto = money(editable=False)
    prazo_maximo = models.PositiveSmallIntegerField(default=0, editable=False)
    parcela_estimada = money(editable=False)
    parametros_usados = models.JSONField(default=dict, editable=False)

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_referencia", "-pk"]
        verbose_name = "Análise de CAPAG"
        verbose_name_plural = "Análises de CAPAG"

    def __str__(self):
        return f"CAPAG {self.empresa.razao_social} – {self.data_referencia:%d/%m/%Y}"

    def get_absolute_url(self):
        return reverse("analise_detalhe", args=[self.pk])

    @property
    def divida_total(self):
        return self.divida_principal + self.divida_multa + self.divida_juros + self.divida_encargos

    @property
    def rating_pgfn(self):
        return self.rating_presumido or self.rating_presumido_calc

    @property
    def prazo_revisao(self):
        return self.data_ciencia + timedelta(days=30) if self.data_ciencia else None

    @property
    def revisao_favoravel(self):
        """True quando a capacidade real leva a um rating mais baixo que o da PGFN
        (ex.: B → C), o que abre acesso a descontos na transação."""
        return bool(self.rating_pgfn) and self.rating_real > self.rating_pgfn

    def save(self, *args, **kwargs):
        from .services import calcular
        calcular(self)
        super().save(*args, **kwargs)


class EnvioCapag(models.Model):
    CANAIS = [("EMAIL", "E-mail"), ("WHATSAPP", "WhatsApp")]
    STATUS = [("ENVIADO", "Enviado"), ("LINK", "Link gerado (wa.me)"), ("ERRO", "Erro")]

    analise = models.ForeignKey(AnaliseCapag, on_delete=models.CASCADE, related_name="envios")
    canal = models.CharField(max_length=8, choices=CANAIS)
    destino = models.CharField(max_length=200)
    mensagem = models.TextField(blank=True)
    status = models.CharField(max_length=7, choices=STATUS)
    resposta = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em"]
        verbose_name = "Envio"

    def __str__(self):
        return f"{self.get_canal_display()} para {self.destino}"
