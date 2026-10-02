from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("funil/", views.funil, name="funil"),

    path("contatos/", views.contato_lista, name="contato_lista"),
    path("contatos/novo/", views.contato_form, name="contato_novo"),
    path("contatos/<int:pk>/", views.contato_detalhe, name="contato_detalhe"),
    path("contatos/<int:pk>/editar/", views.contato_form, name="contato_editar"),
    path("contatos/<int:pk>/excluir/", views.contato_excluir, name="contato_excluir"),
    path("contatos/<int:contato_pk>/atendimentos/novo/", views.oportunidade_form, name="oportunidade_nova"),

    path("atendimentos/<int:pk>/", views.oportunidade_detalhe, name="oportunidade_detalhe"),
    path("atendimentos/<int:pk>/editar/", views.oportunidade_form, name="oportunidade_editar"),
    path("atendimentos/<int:pk>/interacao/", views.interacao_nova, name="interacao_nova"),
    path("atendimentos/<int:pk>/<str:acao>/", views.oportunidade_acao, name="oportunidade_acao"),
    path("atendimentos/<int:oportunidade_pk>/reunioes/nova/", views.reuniao_form, name="reuniao_nova"),

    path("reunioes/<int:pk>/editar/", views.reuniao_form, name="reuniao_editar"),
    path("reunioes/<int:pk>/status/", views.reuniao_status, name="reuniao_status"),
    path("reunioes/<int:pk>/lembrar/", views.reuniao_lembrar, name="reuniao_lembrar"),

    path("conteudos/", views.conteudo_lista, name="conteudo_lista"),
    path("conteudos/novo/", views.conteudo_form, name="conteudo_novo"),
    path("conteudos/<int:pk>/editar/", views.conteudo_form, name="conteudo_editar"),
    path("conteudos/<int:pk>/<str:acao>/", views.conteudo_acao, name="conteudo_acao"),
    path("d/<str:token>/", views.descadastrar, name="descadastrar"),

    path("relatorios/", views.relatorio, name="relatorio"),

    path("mercado/", views.pesquisa_lista, name="pesquisa_lista"),
    path("mercado/<int:pk>/", views.pesquisa_detalhe, name="pesquisa_detalhe"),
    path("mercado/<int:pk>/excluir/", views.pesquisa_excluir, name="pesquisa_excluir"),

    path("atualizacoes/", views.atualizacoes, name="atualizacoes"),
    path("atualizacoes/buscar/", views.atualizacoes_buscar, name="atualizacoes_buscar"),
    path("atualizacoes/excluir/", views.atualizacoes_excluir, name="atualizacoes_excluir"),
    path("atualizacoes/lidas/", views.atualizacao_lida, name="atualizacoes_lidas"),
    path("atualizacoes/<int:pk>/excluir/", views.atualizacao_excluir, name="atualizacao_excluir"),
    path("atualizacoes/<int:pk>/lida/", views.atualizacao_lida, name="atualizacao_lida"),
]
