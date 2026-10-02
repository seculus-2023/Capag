from django.urls import path

from . import views

app_name = "juridico"

urlpatterns = [
    path("prazos/", views.agenda, name="agenda"),
    path("prazos/<int:pk>/editar/", views.prazo_form, name="prazo_editar"),
    path("prazos/<int:pk>/status/", views.prazo_status, name="prazo_status"),

    path("processos/", views.processo_lista, name="processo_lista"),
    path("processos/novo/", views.processo_form, name="processo_novo"),
    path("processos/<int:pk>/", views.processo_detalhe, name="processo_detalhe"),
    path("processos/<int:pk>/editar/", views.processo_form, name="processo_editar"),
    path("processos/<int:pk>/excluir/", views.processo_excluir, name="processo_excluir"),
    path("processos/<int:pk>/andamento/", views.andamento_novo, name="andamento_novo"),
    path("processos/<int:processo_pk>/prazos/novo/", views.prazo_form, name="prazo_novo"),

    path("clientes/<int:pk>/", views.pasta, name="pasta"),
    path("clientes/<int:cliente_pk>/documentos/novo/", views.documento_novo, name="documento_novo"),
    path("documentos/<int:pk>/baixar/", views.documento_baixar, name="documento_baixar"),
    path("documentos/<int:pk>/excluir/", views.documento_excluir, name="documento_excluir"),

    path("financeiro/", views.financeiro, name="financeiro"),
    path("financeiro/novo/", views.lancamento_form, name="lancamento_novo"),
    path("financeiro/<int:pk>/editar/", views.lancamento_form, name="lancamento_editar"),
    path("financeiro/<int:pk>/pagar/", views.lancamento_pagar, name="lancamento_pagar"),
    path("financeiro/<int:pk>/excluir/", views.lancamento_excluir, name="lancamento_excluir"),
]
