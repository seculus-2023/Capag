from django import template

register = template.Library()

CORES_ETAPA = {"NOVO": "secondary", "REUNIAO": "info", "PROPOSTA": "warning", "FECHADO": "success", "PERDIDO": "danger"}


@register.filter
def etapa_cor(etapa):
    return CORES_ETAPA.get(etapa, "secondary")


@register.filter
def nome_usuario(u):
    return (u.get_full_name() or u.username) if u else "—"
