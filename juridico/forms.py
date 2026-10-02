from django import forms
from django.contrib.auth import get_user_model

from core.forms import BootstrapMixin

from .models import Andamento, Documento, Lancamento, Prazo, Processo

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _usuarios():
    return get_user_model().objects.filter(is_active=True).order_by("first_name", "username")


def _nome(u):
    return u.get_full_name() or u.username


def _dinheiro(campo):
    campo.localize = True
    campo.widget = forms.TextInput(attrs={"inputmode": "decimal", "class": "form-control text-end money"})
    campo.widget.is_localized = True


class ProcessoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Processo
        fields = ["cliente", "tipo", "numero", "titulo", "area", "orgao", "parte_contraria", "posicao", "fase",
                  "valor_causa", "data_distribuicao", "status", "responsavel", "observacoes"]
        widgets = {"data_distribuicao": DATA, "observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["responsavel"].queryset = _usuarios()
        self.fields["responsavel"].label_from_instance = _nome
        _dinheiro(self.fields["valor_causa"])
        self._bootstrap()


class AndamentoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Andamento
        fields = ["data", "descricao"]
        widgets = {"data": DATA, "descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._bootstrap()


class PrazoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Prazo
        fields = ["tipo", "descricao", "data_limite", "hora", "responsavel", "observacoes"]
        widgets = {"data_limite": DATA, "hora": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "observacoes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["responsavel"].queryset = _usuarios()
        self.fields["responsavel"].label_from_instance = _nome
        self._bootstrap()


class DocumentoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Documento
        fields = ["arquivo", "titulo", "categoria", "processo"]

    def __init__(self, *a, cliente=None, **kw):
        super().__init__(*a, **kw)
        self.fields["processo"].queryset = Processo.objects.filter(cliente=cliente)
        self.fields["processo"].empty_label = "Documento geral do cliente"
        self._bootstrap()


class LancamentoForm(BootstrapMixin, forms.ModelForm):
    parcelas = forms.IntegerField(label="Parcelas mensais", min_value=1, max_value=120, initial=1,
                                  help_text="Mais de 1: repete o valor todo mês a partir do vencimento.")

    class Meta:
        model = Lancamento
        fields = ["cliente", "processo", "natureza", "categoria", "descricao", "valor", "vencimento",
                  "pago_em", "forma_pagamento", "observacoes"]
        widgets = {"vencimento": DATA, "pago_em": DATA, "observacoes": forms.Textarea(attrs={"rows": 2})}
        labels = {"valor": "Valor (de cada parcela)"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _dinheiro(self.fields["valor"])
        if self.instance.pk:
            del self.fields["parcelas"]
            self.fields["valor"].label = "Valor"
        self._bootstrap()

    def clean(self):
        d = super().clean()
        if d.get("processo") and d.get("cliente") and d["processo"].cliente_id != d["cliente"].pk:
            self.add_error("processo", "Este processo é de outro cliente.")
        if d.get("valor") is not None and d["valor"] <= 0:
            self.add_error("valor", "Informe um valor maior que zero.")
        return d
