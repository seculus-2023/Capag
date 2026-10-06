from django.urls import path

from . import views

app_name = "consultoria"

urlpatterns = [
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo/novo/", views.produto_form, name="produto_novo"),
    path("catalogo/<int:pk>/editar/", views.produto_form, name="produto_editar"),

    path("propostas/", views.proposta_lista, name="proposta_lista"),
    path("atendimentos/<int:oportunidade_pk>/proposta/", views.proposta_form, name="proposta_nova"),
    path("propostas/<int:pk>/", views.proposta_detalhe, name="proposta_detalhe"),
    path("propostas/<int:pk>/editar/", views.proposta_form, name="proposta_editar"),
    path("propostas/<int:pk>/pdf/", views.proposta_pdf, name="proposta_pdf"),
    path("propostas/<int:pk>/enviar/", views.proposta_enviar, name="proposta_enviar"),
    path("propostas/<int:pk>/<str:acao>/", views.proposta_acao, name="proposta_acao"),
    path("p/<str:token>/", views.pdf_publico, name="pdf_publico"),

    path("projetos/", views.projeto_lista, name="projeto_lista"),
    path("projetos/<int:pk>/", views.projeto_detalhe, name="projeto_detalhe"),
    path("projetos/<int:pk>/editar/", views.projeto_form, name="projeto_editar"),
    path("projetos/<int:pk>/status/", views.projeto_status, name="projeto_status"),
    path("projetos/<int:pk>/etapas/nova/", views.etapa_nova, name="etapa_nova"),
    path("etapas/<int:pk>/marcar/", views.etapa_marcar, name="etapa_marcar"),

    path("indicadores/", views.indicadores, name="indicadores"),
]
