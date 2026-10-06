from django import forms
from django.contrib.auth import get_user_model

from core.forms import BootstrapMixin
from core.models import AnaliseCapag

from .models import ItemProposta, Produto, Projeto, Proposta

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _dinheiro(campo):
    campo.localize = True
    campo.widget = forms.TextInput(attrs={"inputmode": "decimal", "class": "form-control text-end money"})
    campo.widget.is_localized = True


class ProdutoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Produto
        fields = ["nome", "area", "cobranca", "valor_referencia", "percentual_exito", "prazo_dias", "usa_capag",
                  "ativo", "escopo", "entregas", "documentos"]
        widgets = {"escopo": forms.Textarea(attrs={"rows": 4}), "entregas": forms.Textarea(attrs={"rows": 5}),
                   "documentos": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _dinheiro(self.fields["valor_referencia"])
        self._bootstrap()


class PropostaForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Proposta
        fields = ["analise", "validade", "parcelas", "meses_mensalidade", "primeiro_vencimento", "condicoes"]
        widgets = {"validade": DATA, "primeiro_vencimento": DATA, "condicoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, contato=None, **kw):
        super().__init__(*a, **kw)
        empresa = contato.empresa_id if contato else None
        self.fields["analise"].queryset = AnaliseCapag.objects.filter(empresa_id=empresa).order_by("-data_referencia")
        self.fields["analise"].label_from_instance = lambda x: f"{x.data_referencia:%d/%m/%Y} – rating {x.rating_real or '?'}"
        self.fields["analise"].empty_label = "Sem análise" if empresa else "O contato não tem empresa cadastrada na CAPAG"
        self.fields["parcelas"].widget.attrs["min"] = 1
        self.fields["meses_mensalidade"].widget.attrs["min"] = 1
        self._bootstrap()

    def clean_parcelas(self):
        return max(1, self.cleaned_data["parcelas"] or 1)

    def clean_meses_mensalidade(self):
        return max(1, self.cleaned_data["meses_mensalidade"] or 1)


class ItemForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ItemProposta
        fields = ["produto", "descricao", "valor", "percentual_exito"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        ativos = Produto.objects.filter(ativo=True)
        if self.instance.pk:  # mantém o produto atual mesmo se foi desativado depois
            ativos = Produto.objects.filter(pk=self.instance.produto_id) | ativos
        self.fields["produto"].queryset = ativos.order_by("area", "nome")
        self.fields["valor"].required = False
        self.fields["percentual_exito"].required = False
        self.fields["valor"].help_text = "Em branco = valor de referência do produto."
        _dinheiro(self.fields["valor"])
        self._bootstrap()

    def has_changed(self):
        # linha nova sem produto escolhido é linha em branco (valor e êxito têm valor inicial)
        if not self.instance.pk:
            return bool(self.data.get(self.add_prefix("produto")))
        return super().has_changed()

    def clean(self):
        d = super().clean()
        produto = d.get("produto")
        if produto:
            if d.get("valor") is None:
                d["valor"] = produto.valor_referencia
            if d.get("percentual_exito") is None:
                d["percentual_exito"] = produto.percentual_exito
            self.instance.valor, self.instance.percentual_exito = d["valor"], d["percentual_exito"]
        return d


ItemFormSet = forms.inlineformset_factory(Proposta, ItemProposta, form=ItemForm, extra=1, can_delete=True,
                                          min_num=1, validate_min=True)


class ProjetoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Projeto
        fields = ["titulo", "responsavel", "inicio", "prazo", "observacoes"]
        widgets = {"inicio": DATA, "prazo": DATA, "observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["responsavel"].queryset = get_user_model().objects.filter(is_active=True).order_by("first_name", "username")
        self.fields["responsavel"].label_from_instance = lambda u: u.get_full_name() or u.username
        self._bootstrap()
