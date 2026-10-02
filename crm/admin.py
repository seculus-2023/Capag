from django.contrib import admin

from .models import (Atualizacao, Contato, Conteudo, Fonte, Interacao, Mensagem, Oportunidade, PesquisaMercado,
                     Reuniao)


@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo", "email", "whatsapp", "area_interesse", "origem", "responsavel", "aceita_conteudo"]
    list_filter = ["area_interesse", "origem", "aceita_conteudo"]
    search_fields = ["nome", "email", "documento"]


class InteracaoInline(admin.TabularInline):
    model = Interacao
    extra = 0


@admin.register(Oportunidade)
class OportunidadeAdmin(admin.ModelAdmin):
    list_display = ["contato", "titulo", "area", "etapa", "responsavel", "aberto_em", "fechado_em", "motivo_perda"]
    list_filter = ["etapa", "area", "motivo_perda"]
    search_fields = ["contato__nome", "titulo"]
    inlines = [InteracaoInline]


@admin.register(Reuniao)
class ReuniaoAdmin(admin.ModelAdmin):
    list_display = ["oportunidade", "advogado", "inicio", "modalidade", "status"]
    list_filter = ["status", "modalidade"]


@admin.register(Conteudo)
class ConteudoAdmin(admin.ModelAdmin):
    list_display = ["titulo", "area", "status", "enviar_a_partir", "enviado_em"]
    list_filter = ["status", "area"]
    readonly_fields = ["status", "aprovado_por", "enviado_em"]  # aprovação e envio só pelas telas do CRM


@admin.register(Mensagem)
class MensagemAdmin(admin.ModelAdmin):
    list_display = ["contato", "tipo", "canal", "destino", "status", "enviado_em"]
    list_filter = ["tipo", "canal", "status"]


@admin.register(Fonte)
class FonteAdmin(admin.ModelAdmin):
    list_display = ["nome", "area", "palavras_chave", "ativo", "ultima_leitura", "ultimo_erro"]
    list_filter = ["area", "ativo"]


@admin.register(Atualizacao)
class AtualizacaoAdmin(admin.ModelAdmin):
    list_display = ["titulo", "fonte", "area", "publicado_em", "lida", "excluida"]
    list_filter = ["area", "fonte", "lida", "excluida"]
    search_fields = ["titulo", "resumo"]


@admin.register(PesquisaMercado)
class PesquisaMercadoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "total", "usuario", "criado_em"]
