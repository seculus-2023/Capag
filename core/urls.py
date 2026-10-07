from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html",
                                               authentication_form=LoginForm, redirect_authenticated_user=True),
         name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("senha/", auth_views.PasswordChangeView.as_view(template_name="registration/senha.html",
                                                         success_url="/"), name="senha"),

    path("", views.dashboard, name="dashboard"),

    path("empresas/", views.empresa_lista, name="empresa_lista"),
    path("empresas/nova/", views.empresa_form, name="empresa_nova"),
    path("empresas/consulta-cnpj/", views.consulta_cnpj, name="consulta_cnpj"),
    path("empresas/<int:pk>/", views.empresa_detalhe, name="empresa_detalhe"),
    path("empresas/<int:pk>/editar/", views.empresa_form, name="empresa_editar"),
    path("empresas/<int:pk>/excluir/", views.empresa_excluir, name="empresa_excluir"),
    path("empresas/<int:empresa_pk>/analises/nova/", views.analise_form, name="analise_nova"),

    path("analises/", views.analise_lista, name="analise_lista"),
    path("analises/<int:pk>/", views.analise_detalhe, name="analise_detalhe"),
    path("analises/<int:pk>/editar/", views.analise_form, name="analise_editar"),
    path("analises/<int:pk>/recalcular/", views.analise_recalcular, name="analise_recalcular"),
    path("analises/<int:pk>/duplicar/", views.analise_duplicar, name="analise_duplicar"),
    path("analises/<int:pk>/excluir/", views.analise_excluir, name="analise_excluir"),
    path("analises/<int:pk>/pdf/", views.analise_pdf, name="analise_pdf"),
    path("analises/<int:pk>/enviar/email/", views.enviar_email_view, name="enviar_email"),
    path("analises/<int:pk>/enviar/whatsapp/", views.enviar_whatsapp_view, name="enviar_whatsapp"),

    path("envios/", views.envio_lista, name="envio_lista"),
    path("relatorios/", views.relatorios, name="relatorios"),
    path("relatorios/ranking/", views.relatorio_ranking, name="relatorio_ranking"),
    path("relatorios/evolucao/", views.relatorio_evolucao, name="relatorio_evolucao"),
    path("relatorios/composicao/", views.relatorio_composicao, name="relatorio_composicao"),
    path("relatorios/composicao/<int:pk>/", views.relatorio_composicao, name="relatorio_composicao_analise"),
    path("relatorios/alertas/", views.relatorio_alertas, name="relatorio_alertas"),
    path("relatorios/servicos/", views.relatorio_servicos, name="relatorio_servicos"),

    path("parametros/", views.parametros, name="parametros"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/<int:pk>/", views.usuario_alterar, name="usuario_alterar"),

    path("p/<str:token>/", views.pdf_publico, name="pdf_publico"),

    # PWA: o service worker precisa ser servido da raiz para valer em todas as telas
    path("manifest.webmanifest", views.pwa_manifest, name="pwa_manifest"),
    path("sw.js", views.pwa_sw, name="pwa_sw"),
    path("offline/", views.pwa_offline, name="pwa_offline"),
]
