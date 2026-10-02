from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import AnaliseCapag, Empresa, Parametro
from .services import texto_resumo


class BootstrapMixin:
    def _bootstrap(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, forms.Select):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")


class LoginForm(BootstrapMixin, AuthenticationForm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["username"].label = "Usuário"
        self.fields["username"].widget.attrs["autofocus"] = True
        self._bootstrap()


class EmpresaForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Empresa
        exclude = ["criado_por", "ativo"]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["cnpj"].widget.attrs.update({"placeholder": "00.000.000/0000-00", "data-mask": "cnpj"})
        self.fields["whatsapp"].widget.attrs.update({"placeholder": "(65) 99999-9999"})
        self.fields["uf"].widget.attrs.update({"maxlength": 2, "style": "text-transform:uppercase"})
        self._bootstrap()

    def clean_cnpj(self):
        from .validators import formatar_cnpj
        cnpj = formatar_cnpj(self.cleaned_data["cnpj"])
        qs = Empresa.objects.filter(cnpj=cnpj)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe empresa cadastrada com este CNPJ.")
        return cnpj


class AnaliseForm(BootstrapMixin, forms.ModelForm):
    GRUPOS = {
        "Identificação": ["data_referencia", "descricao", "status", "numero_requerimento", "data_ciencia"],
        "Dívida ativa da União (consolidada)": ["divida_principal", "divida_multa", "divida_juros", "divida_encargos"],
        "CAPAG informada pela PGFN": ["capag_presumida", "rating_presumido"],
        "Situação real – últimos 12 meses": ["receita_bruta_12m", "custos_despesas_12m",
                                             "parcelas_financiamento_12m", "outras_dividas_12m"],
        "Patrimônio e liquidez": ["patrimonio_total", "bens_onerados", "disponibilidades",
                                  "ativo_circulante", "passivo_circulante", "situacao_irrecuperavel"],
        "Justificativa": ["justificativa"],
    }

    class Meta:
        model = AnaliseCapag
        fields = ["data_referencia", "descricao", "status", "numero_requerimento", "data_ciencia",
                  "divida_principal", "divida_multa", "divida_juros", "divida_encargos",
                  "capag_presumida", "rating_presumido",
                  "receita_bruta_12m", "custos_despesas_12m", "parcelas_financiamento_12m", "outras_dividas_12m",
                  "patrimonio_total", "bens_onerados", "disponibilidades",
                  "ativo_circulante", "passivo_circulante", "situacao_irrecuperavel",
                  "justificativa"]
        widgets = {
            "data_referencia": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_ciencia": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "justificativa": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for nome, f in self.fields.items():
            if isinstance(f, forms.DecimalField):
                f.localize = True
                f.widget = forms.TextInput(attrs={"inputmode": "decimal", "class": "form-control text-end money"})
                f.widget.is_localized = True
        self.fields["rating_presumido"].help_text = "Deixe em branco para o sistema calcular pela CAPAG presumida."
        for nome in self.OPCIONAIS:
            self.fields[nome].required = False
        self._bootstrap()

    OPCIONAIS = ["ativo_circulante", "passivo_circulante"]

    def clean_ativo_circulante(self):
        return self.cleaned_data.get("ativo_circulante") or Decimal("0")

    def clean_passivo_circulante(self):
        return self.cleaned_data.get("passivo_circulante") or Decimal("0")

    def grupos(self):
        return [(titulo, [self[n] for n in nomes]) for titulo, nomes in self.GRUPOS.items()]

    def clean(self):
        d = super().clean()
        for campo in ["bens_onerados"]:
            if d.get(campo) and d.get("patrimonio_total") is not None and d[campo] > d["patrimonio_total"]:
                self.add_error(campo, "Os bens onerados não podem superar o patrimônio total.")
        return d


class ParametroForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Parametro
        exclude = []

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._bootstrap()


class EnvioEmailForm(BootstrapMixin, forms.Form):
    destino = forms.CharField(label="Para (separe vários e-mails com vírgula)")
    assunto = forms.CharField(label="Assunto")
    mensagem = forms.CharField(label="Mensagem", widget=forms.Textarea(attrs={"rows": 10}))

    def __init__(self, *a, analise=None, **kw):
        super().__init__(*a, **kw)
        if analise and not self.is_bound:
            e = analise.empresa
            self.initial.update({
                "destino": e.email,
                "assunto": f"Análise de CAPAG – {e.razao_social} ({e.cnpj})",
                "mensagem": texto_resumo(analise).replace("*", "") + "\n\nO relatório completo segue em anexo (PDF).",
            })
        self._bootstrap()

    def clean_destino(self):
        v = self.cleaned_data["destino"]
        validador = forms.EmailField()
        for d in v.replace(";", ",").split(","):
            if d.strip():
                validador.clean(d.strip())
        return v


class EnvioWhatsappForm(BootstrapMixin, forms.Form):
    numero = forms.CharField(label="WhatsApp (com DDD)")
    mensagem = forms.CharField(label="Mensagem", widget=forms.Textarea(attrs={"rows": 10}))

    def __init__(self, *a, analise=None, **kw):
        super().__init__(*a, **kw)
        if analise and not self.is_bound:
            self.initial.update({"numero": analise.empresa.whatsapp, "mensagem": texto_resumo(analise)})
        self._bootstrap()

    def clean_numero(self):
        from .validators import normalizar_whatsapp
        n = normalizar_whatsapp(self.cleaned_data["numero"])
        if len(n) not in (12, 13):
            raise forms.ValidationError("Número inválido. Informe com DDD, ex.: (65) 99999-9999.")
        return n


class UsuarioForm(BootstrapMixin, UserCreationForm):
    perfil = forms.ChoiceField(label="Perfil")

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *a, **kw):
        from .perfis import PADRAO, PERFIS
        super().__init__(*a, **kw)
        self.fields["perfil"].choices = [(cod, nome) for cod, (nome, _) in PERFIS.items()]
        self.fields["perfil"].initial = PADRAO
        self.fields["username"].label = "Usuário (login)"
        self.fields["email"].help_text = "Recebe os avisos de prazo."
        self.fields["password1"].help_text = "Mínimo de 8 caracteres, não só números."
        self.fields["username"].help_text = ""
        self._bootstrap()
