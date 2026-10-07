from django.contrib import admin

from .models import AnaliseCapag, Empresa, EnvioCapag, Parametro


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ["razao_social", "cnpj", "porte", "regime_tributario", "indicado_por", "municipio", "uf", "ativo"]
    list_filter = ["porte", "regime_tributario", "servicos", "uf", "ativo"]
    search_fields = ["razao_social", "nome_fantasia", "cnpj", "indicado_por"]
    filter_horizontal = ["servicos"]


class EnvioInline(admin.TabularInline):
    model = EnvioCapag
    extra = 0
    readonly_fields = ["canal", "destino", "status", "usuario", "enviado_em"]
    fields = readonly_fields
    can_delete = False


@admin.register(AnaliseCapag)
class AnaliseAdmin(admin.ModelAdmin):
    list_display = ["empresa", "data_referencia", "capag_presumida", "capag_real", "rating_presumido", "rating_real", "status"]
    list_filter = ["rating_real", "status"]
    search_fields = ["empresa__razao_social", "empresa__cnpj"]
    readonly_fields = ["resultado_anual_livre", "geracao_futura", "patrimonio_livre", "capag_real", "rating_real",
                       "rating_presumido_calc", "desconto_estimado", "valor_apos_desconto", "prazo_maximo",
                       "parcela_estimada", "parametros_usados"]
    inlines = [EnvioInline]


@admin.register(EnvioCapag)
class EnvioAdmin(admin.ModelAdmin):
    list_display = ["analise", "canal", "destino", "status", "usuario", "enviado_em"]
    list_filter = ["canal", "status"]


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not Parametro.objects.exists()
