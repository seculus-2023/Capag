from django.contrib import admin

from .models import Etapa, ItemProposta, Produto, Projeto, Proposta


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "area", "cobranca", "valor_referencia", "percentual_exito", "prazo_dias", "ativo"]
    list_filter = ["area", "cobranca", "ativo"]
    search_fields = ["nome"]


class ItemInline(admin.TabularInline):
    model = ItemProposta
    extra = 0


@admin.register(Proposta)
class PropostaAdmin(admin.ModelAdmin):
    list_display = ["__str__", "status", "validade", "enviada_em", "respondida_em"]
    list_filter = ["status"]
    search_fields = ["oportunidade__contato__nome", "oportunidade__titulo"]
    inlines = [ItemInline]


class EtapaInline(admin.TabularInline):
    model = Etapa
    extra = 0


@admin.register(Projeto)
class ProjetoAdmin(admin.ModelAdmin):
    list_display = ["titulo", "cliente", "responsavel", "prazo", "status"]
    list_filter = ["status"]
    search_fields = ["titulo", "cliente__nome"]
    inlines = [EtapaInline]
