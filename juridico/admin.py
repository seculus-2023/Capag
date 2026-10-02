from django.contrib import admin

from .models import Andamento, Documento, Lancamento, Prazo, Processo


class AndamentoInline(admin.TabularInline):
    model = Andamento
    extra = 0


@admin.register(Processo)
class ProcessoAdmin(admin.ModelAdmin):
    list_display = ["numero", "titulo", "cliente", "area", "orgao", "status", "responsavel"]
    list_filter = ["status", "area", "tipo"]
    search_fields = ["numero", "titulo", "cliente__nome", "parte_contraria"]
    inlines = [AndamentoInline]


@admin.register(Prazo)
class PrazoAdmin(admin.ModelAdmin):
    list_display = ["data_limite", "descricao", "processo", "responsavel", "status"]
    list_filter = ["status", "tipo"]


@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ["vencimento", "cliente", "descricao", "natureza", "valor", "pago_em"]
    list_filter = ["natureza", "categoria"]
    search_fields = ["cliente__nome", "descricao"]


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "cliente", "processo", "categoria", "enviado_por", "criado_em"]
    list_filter = ["categoria"]
    search_fields = ["titulo", "nome_original", "cliente__nome"]
