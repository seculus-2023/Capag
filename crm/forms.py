from django import forms
from django.contrib.auth import get_user_model

from core.forms import BootstrapMixin

from .models import Contato, Conteudo, Interacao, Oportunidade, PesquisaMercado, Reuniao
from .services import verificar_oab


def _advogados():
    return get_user_model().objects.filter(is_active=True).order_by("first_name", "username")


def _nome_usuario(u):
    return u.get_full_name() or u.username


def _campo_dinheiro(f):
    f.localize = True
    f.widget = forms.TextInput(attrs={"inputmode": "decimal", "class": "form-control text-end money"})
    f.widget.is_localized = True


class ContatoForm(BootstrapMixin, forms.ModelForm):
    assunto = forms.CharField(label="Assunto do primeiro atendimento", max_length=200, required=False,
                              help_text="Ex.: Transação tributária PGFN, auto de infração ICMS, licenciamento ambiental.")

    class Meta:
        model = Contato
        fields = ["nome", "tipo", "documento", "empresa", "email", "whatsapp", "municipio", "uf",
                  "origem", "area_interesse", "responsavel", "aceita_conteudo", "observacoes"]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["responsavel"].queryset = _advogados()
        self.fields["responsavel"].label_from_instance = _nome_usuario
        self.fields["whatsapp"].widget.attrs["placeholder"] = "(65) 99999-9999"
        self.fields["uf"].widget.attrs.update({"maxlength": 2, "style": "text-transform:uppercase"})
        if self.instance.pk:
            del self.fields["assunto"]
        self._bootstrap()

    def clean(self):
        d = super().clean()
        if not d.get("email") and not d.get("whatsapp"):
            raise forms.ValidationError("Informe ao menos um meio de contato: e-mail ou WhatsApp.")
        if d.get("aceita_conteudo") and not d.get("email"):
            self.add_error("email", "Os conteúdos informativos são enviados por e-mail. Informe o e-mail.")
        return d


class OportunidadeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Oportunidade
        fields = ["titulo", "area", "responsavel", "valor_estimado", "aberto_em"]
        widgets = {"aberto_em": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["responsavel"].queryset = _advogados()
        self.fields["responsavel"].label_from_instance = _nome_usuario
        _campo_dinheiro(self.fields["valor_estimado"])
        self._bootstrap()


class InteracaoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Interacao
        fields = ["tipo", "descricao"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._bootstrap()


class ReuniaoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Reuniao
        fields = ["advogado", "inicio", "duracao_min", "modalidade", "local", "observacoes"]
        widgets = {"inicio": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
                   "observacoes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["advogado"].queryset = _advogados()
        self.fields["advogado"].label_from_instance = _nome_usuario
        self._bootstrap()


class PropostaForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Oportunidade
        fields = ["proposta_enviada_em", "valor_estimado"]
        widgets = {"proposta_enviada_em": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["proposta_enviada_em"].required = True
        _campo_dinheiro(self.fields["valor_estimado"])
        self._bootstrap()


class ContratoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Oportunidade
        fields = ["contrato_link"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["contrato_link"].required = True
        self._bootstrap()


class AssinaturaForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Oportunidade
        fields = ["contrato_assinado_em"]
        widgets = {"contrato_assinado_em": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["contrato_assinado_em"].required = True
        self._bootstrap()

    def clean_contrato_assinado_em(self):
        d = self.cleaned_data["contrato_assinado_em"]
        if d < self.instance.aberto_em:
            raise forms.ValidationError("A assinatura não pode ser anterior à data de entrada do contato.")
        return d


class PerdaForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Oportunidade
        fields = ["motivo_perda", "detalhe_perda"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["motivo_perda"].required = True
        self._bootstrap()


class ConteudoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Conteudo
        fields = ["titulo", "area", "texto", "link", "enviar_a_partir"]
        widgets = {"texto": forms.Textarea(attrs={"rows": 10}),
                   "enviar_a_partir": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["area"].choices = [("", "Todas as áreas")] + list(self.fields["area"].choices)[1:]
        self._bootstrap()

    def clean(self):
        d = super().clean()
        problemas = verificar_oab(f"{d.get('titulo', '')}\n{d.get('texto', '')}")
        if problemas:
            raise forms.ValidationError(
                ["Texto fora das regras de publicidade da advocacia (Provimento 205/2021 da OAB). Retire:"]
                + [f"“{trecho}” – {motivo}" for trecho, motivo in problemas])
        return d


class PesquisaMercadoForm(BootstrapMixin, forms.ModelForm):
    categoria = forms.ChoiceField(label="Segmento", required=False)

    class Meta:
        model = PesquisaMercado
        fields = ["categoria", "termo", "municipio", "uf"]

    def __init__(self, *a, **kw):
        from .mapas import CATEGORIAS
        super().__init__(*a, **kw)
        self.fields["categoria"].choices = [("", "Qualquer segmento (buscar pelo nome)")] + [
            (cod, nome) for cod, (nome, _) in CATEGORIAS.items()]
        self.fields["uf"].widget.attrs.update({"maxlength": 2, "style": "text-transform:uppercase"})
        self._bootstrap()

    def clean_uf(self):
        uf = self.cleaned_data["uf"].upper()
        if not uf.isalpha() or len(uf) != 2:
            raise forms.ValidationError("Informe a sigla do estado, ex.: MT.")
        return uf

    def clean(self):
        d = super().clean()
        if not d.get("categoria") and len((d.get("termo") or "").strip()) < 3:
            raise forms.ValidationError("Escolha um segmento ou informe ao menos 3 letras do nome.")
        return d
