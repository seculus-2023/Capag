from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "CAPAG – Administração"
admin.site.site_title = "CAPAG"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("crm/", include("crm.urls")),
    path("juridico/", include("juridico.urls")),
    path("", include("core.urls")),
]
