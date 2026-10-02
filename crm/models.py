import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.validators import normalizar_whatsapp, validar_whatsapp

AREAS = [("TRIB_FED", "Direito Tributário Federal"),
         ("TRIB_EST", "Direito Tributário Estadual"),
         ("AMBIENTAL", "Direito Ambiental")]


class Contato(models.Model):
    TIPOS = [("PJ", "Pessoa jurídica"), ("PF", "Pessoa física")]
    ORIGENS = [("INDICACAO", "Indicação"), ("CLIENTE", "Já é cliente do escritório"),
               ("SITE", "Site / formulário"), ("REDES", "Redes sociais"),
               ("EVENTO", "Evento / palestra"), ("OUTRO", "Outro")]

    nome = models.CharField("Nome", max_length=150)
    tipo = models.CharField("Tipo", max_length=2, choices=TIPOS, default="PJ")
    documento = models.CharField("CPF / CNPJ", max_length=18, blank=True)
    empresa = models.ForeignKey("core.Empresa", verbose_name="Empresa cadastrada (CAPAG)", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="contatos")
    email = models.EmailField("E-mail", blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True, validators=[validar_whatsapp])
    municipio = models.CharField("Município", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    origem = models.CharField("Como chegou ao escritório", max_length=10, choices=ORIGENS, default="INDICACAO",
                              help_text="O contato deve partir do interessado ou de indicação (sem captação ativa).")
    area_interesse = models.CharField("Área de interesse", max_length=10, choices=AREAS, default="TRIB_FED")
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Advogado responsável", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="contatos_crm")
    aceita_conteudo = models.BooleanField(
        "Autorizou receber conteúdos informativos", default=False,
        help_text="Marque somente se a pessoa pediu ou autorizou expressamente (OAB, Provimento 205/2021, e LGPD).")
    consentimento_em = models.DateTimeField(null=True, blank=True, editable=False)
    observacoes = models.TextField("Observações", blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Contato"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        self.whatsapp = normalizar_whatsapp(self.whatsapp)
        self.uf = (self.uf or "").upper()
        if self.aceita_conteudo and not self.consentimento_em:
            self.consentimento_em = timezone.now()
        elif not self.aceita_conteudo:
            self.consentimento_em = None
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("crm:contato_detalhe", args=[self.pk])

    @property
    def primeiro_nome(self):
        return self.nome.split()[0] if self.nome.strip() else ""


class Oportunidade(models.Model):
    """Um atendimento do contato no funil: novo → consulta → proposta → contrato assinado (ou perdido)."""
    ETAPAS = [("NOVO", "Novo contato"), ("REUNIAO", "Consulta agendada"), ("PROPOSTA", "Proposta enviada"),
              ("FECHADO", "Contrato assinado"), ("PERDIDO", "Perdido")]
    ABERTAS = ("NOVO", "REUNIAO", "PROPOSTA")
    MOTIVOS = [("PRECO", "Preço alto"), ("DEMORA", "Demora no atendimento"),
               ("SEM_DIREITO", "Falta de direito na ação"), ("CONCORRENTE", "Fechou com outro escritório"),
               ("DESISTIU", "Desistiu / sem retorno"), ("OUTRO", "Outro")]

    contato = models.ForeignKey(Contato, on_delete=models.CASCADE, related_name="oportunidades")
    titulo = models.CharField("Assunto", max_length=200, help_text="Ex.: Transação tributária PGFN, auto de infração ICMS.")
    area = models.CharField("Área do direito", max_length=10, choices=AREAS)
    etapa = models.CharField(max_length=8, choices=ETAPAS, default="NOVO")
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Advogado responsável", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="oportunidades_crm")
    valor_estimado = models.DecimalField("Honorários estimados", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    aberto_em = models.DateField("Data de entrada", default=timezone.localdate)
    proposta_enviada_em = models.DateField("Proposta enviada em", null=True, blank=True)
    ultimo_contato_em = models.DateTimeField(null=True, blank=True, editable=False)

    # Fechamento: contrato assinado digitalmente numa plataforma de assinatura
    contrato_link = models.URLField("Link do contrato para assinatura digital", blank=True, max_length=500,
                                    help_text="Link gerado na plataforma de assinatura (gov.br, ZapSign, Clicksign, D4Sign etc.).")
    contrato_enviado_em = models.DateField(null=True, blank=True, editable=False)
    contrato_assinado_em = models.DateField("Contrato assinado em", null=True, blank=True)
    fechado_em = models.DateField(null=True, blank=True, editable=False)

    motivo_perda = models.CharField("Motivo da perda", max_length=12, choices=MOTIVOS, blank=True)
    detalhe_perda = models.CharField("Detalhe", max_length=250, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-aberto_em", "-pk"]
        verbose_name = "Atendimento"

    def __str__(self):
        return f"{self.contato.nome} – {self.titulo}"

    def get_absolute_url(self):
        return reverse("crm:oportunidade_detalhe", args=[self.pk])

    @property
    def aberta(self):
        return self.etapa in self.ABERTAS

    @property
    def dias_maturacao(self):
        """Dias entre a entrada do contato e a assinatura do contrato."""
        if self.etapa == "FECHADO" and self.fechado_em:
            return max(0, (self.fechado_em - self.aberto_em).days)
        return None

    @property
    def referencia_followup(self):
        """Último movimento com o cliente depois da proposta (data da proposta ou último contato)."""
        ref = self.proposta_enviada_em
        if ref and self.ultimo_contato_em:
            ref = max(ref, timezone.localtime(self.ultimo_contato_em).date())
        return ref

    @property
    def dias_sem_contato(self):
        ref = self.referencia_followup
        return (timezone.localdate() - ref).days if ref else None

    @property
    def precisa_followup(self):
        d = self.dias_sem_contato
        return self.etapa == "PROPOSTA" and d is not None and d > settings.CRM_FOLLOWUP_DIAS


class Interacao(models.Model):
    TIPOS = [("LIGACAO", "Ligação"), ("WHATSAPP", "WhatsApp"), ("EMAIL", "E-mail"),
             ("REUNIAO", "Reunião"), ("NOTA", "Anotação interna")]

    oportunidade = models.ForeignKey(Oportunidade, on_delete=models.CASCADE, related_name="interacoes")
    tipo = models.CharField("Tipo", max_length=8, choices=TIPOS, default="LIGACAO")
    descricao = models.TextField("O que foi tratado")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Interação"
        verbose_name_plural = "Interações"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.tipo != "NOTA":  # anotação interna não conta como contato com o cliente
            Oportunidade.objects.filter(pk=self.oportunidade_id).update(ultimo_contato_em=self.criado_em)


class Reuniao(models.Model):
    MODALIDADES = [("PRESENCIAL", "Presencial"), ("VIDEO", "Videochamada"), ("TELEFONE", "Telefone")]
    STATUS = [("AGENDADA", "Agendada"), ("REALIZADA", "Realizada"),
              ("CANCELADA", "Cancelada"), ("FALTOU", "Cliente não compareceu")]

    oportunidade = models.ForeignKey(Oportunidade, on_delete=models.CASCADE, related_name="reunioes")
    advogado = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Advogado especialista",
                                 on_delete=models.PROTECT, related_name="reunioes_crm")
    inicio = models.DateTimeField("Data e hora")
    duracao_min = models.PositiveSmallIntegerField("Duração (minutos)", default=60)
    modalidade = models.CharField("Modalidade", max_length=10, choices=MODALIDADES, default="PRESENCIAL")
    local = models.CharField("Local ou link da videochamada", max_length=250, blank=True)
    status = models.CharField(max_length=9, choices=STATUS, default="AGENDADA")
    observacoes = models.TextField("Observações", blank=True)
    remarcada_em = models.DateTimeField(null=True, blank=True, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "Reunião"
        verbose_name_plural = "Reuniões"

    def __str__(self):
        return f"Consulta com {self.oportunidade.contato.nome} em {timezone.localtime(self.inicio):%d/%m/%Y %H:%M}"

    @property
    def fim(self):
        return self.inicio + timedelta(minutes=self.duracao_min)

    @property
    def contato(self):
        return self.oportunidade.contato


class Conteudo(models.Model):
    """Conteúdo educativo/informativo para nutrição dos contatos que autorizaram o recebimento."""
    STATUS = [("RASCUNHO", "Rascunho"), ("APROVADO", "Aprovado para envio"), ("ENVIADO", "Enviado")]

    titulo = models.CharField("Título", max_length=200)
    area = models.CharField("Área do direito", max_length=10, choices=AREAS, blank=True,
                            help_text="Em branco = todos os contatos que autorizaram o recebimento.")
    texto = models.TextField("Texto", help_text="Somente conteúdo informativo, em linguagem sóbria, sem oferta de serviços.")
    link = models.URLField("Link para ler mais", blank=True, max_length=500)
    status = models.CharField(max_length=8, choices=STATUS, default="RASCUNHO")
    enviar_a_partir = models.DateField("Enviar a partir de", default=timezone.localdate)
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    enviado_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Conteúdo informativo"
        verbose_name_plural = "Conteúdos informativos"

    def __str__(self):
        return self.titulo


class Mensagem(models.Model):
    """Registro de cada mensagem automática (lembrete de reunião ou conteúdo informativo)."""
    TIPOS = [("LEMBRETE", "Lembrete de reunião"), ("NUTRICAO", "Conteúdo informativo")]
    CANAIS = [("EMAIL", "E-mail"), ("WHATSAPP", "WhatsApp")]
    STATUS = [("ENVIADO", "Enviado"), ("ERRO", "Erro")]

    contato = models.ForeignKey(Contato, on_delete=models.CASCADE, related_name="mensagens")
    tipo = models.CharField(max_length=8, choices=TIPOS)
    canal = models.CharField(max_length=8, choices=CANAIS)
    reuniao = models.ForeignKey(Reuniao, null=True, blank=True, on_delete=models.CASCADE, related_name="mensagens")
    conteudo = models.ForeignKey(Conteudo, null=True, blank=True, on_delete=models.CASCADE, related_name="mensagens")
    destino = models.CharField(max_length=200)
    status = models.CharField(max_length=7, choices=STATUS)
    resposta = models.TextField(blank=True)
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em"]
        verbose_name = "Mensagem automática"
        verbose_name_plural = "Mensagens automáticas"

    def __str__(self):
        return f"{self.get_tipo_display()} por {self.get_canal_display()} para {self.destino}"


class Fonte(models.Model):
    """Feed (RSS/Atom) acompanhado para manter o escritório atualizado."""
    nome = models.CharField("Nome", max_length=120)
    url = models.URLField("Endereço do feed (RSS/Atom)", max_length=500)
    area = models.CharField("Área do direito", max_length=10, choices=AREAS)
    palavras_chave = models.CharField(
        "Palavras-chave", max_length=300, blank=True,
        help_text="Separadas por vírgula. Se preenchido, só entram notícias que contenham alguma delas.")
    ativo = models.BooleanField(default=True)
    ultima_leitura = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_erro = models.CharField(max_length=300, blank=True, editable=False)
    # preenchido ao excluir as atualizações: notícias publicadas até esta data não voltam na próxima busca
    ignorar_ate = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["area", "nome"]
        verbose_name = "Fonte de atualização"
        verbose_name_plural = "Fontes de atualização"

    def __str__(self):
        return self.nome


class AtualizacoesVisiveis(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(excluida=False)


class Atualizacao(models.Model):
    fonte = models.ForeignKey(Fonte, on_delete=models.CASCADE, related_name="atualizacoes")
    area = models.CharField(max_length=10, choices=AREAS)
    titulo = models.CharField(max_length=400)
    link = models.URLField(max_length=700, unique=True)
    resumo = models.TextField(blank=True)
    publicado_em = models.DateTimeField()
    lida = models.BooleanField(default=False)
    # exclusão individual: o registro fica oculto para a notícia não voltar na próxima busca
    excluida = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visiveis = AtualizacoesVisiveis()

    class Meta:
        ordering = ["-publicado_em", "-pk"]
        verbose_name = "Atualização jurídica"
        verbose_name_plural = "Atualizações jurídicas"

    def __str__(self):
        return self.titulo


class PesquisaMercado(models.Model):
    """Extração de empresas de um município (OpenStreetMap) para estudo de mercado."""
    categoria = models.CharField("Segmento", max_length=20, blank=True)
    termo = models.CharField("Nome contém", max_length=80, blank=True,
                             help_text="Opcional com segmento. Ex.: transportadora, cerealista.")
    municipio = models.CharField("Município", max_length=100, help_text="Com acentos, como no mapa. Ex.: Cuiabá.")
    uf = models.CharField("UF", max_length=2)
    total = models.PositiveIntegerField(default=0, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Pesquisa de mercado"
        verbose_name_plural = "Pesquisas de mercado"

    def __str__(self):
        return f"{self.descricao} em {self.municipio}/{self.uf}"

    @property
    def descricao(self):
        from .mapas import CATEGORIAS
        nome = CATEGORIAS[self.categoria][0] if self.categoria in CATEGORIAS else ""
        return " · ".join(x for x in [nome, f"“{self.termo}”" if self.termo else ""] if x)

    def get_absolute_url(self):
        return reverse("crm:pesquisa_detalhe", args=[self.pk])


class EmpresaMapa(models.Model):
    pesquisa = models.ForeignKey(PesquisaMercado, on_delete=models.CASCADE, related_name="empresas")
    osm_ref = models.CharField(max_length=40)
    nome = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80, blank=True)
    endereco = models.CharField(max_length=250, blank=True)
    telefone = models.CharField(max_length=60, blank=True)
    email = models.CharField(max_length=200, blank=True)
    site = models.CharField(max_length=300, blank=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Empresa do mapa"
        verbose_name_plural = "Empresas do mapa"

    def __str__(self):
        return self.nome

    @property
    def link_google_maps(self):
        if self.latitude is None:
            return ""
        return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
