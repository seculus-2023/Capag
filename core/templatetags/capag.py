from django import template

from ..services import brl as _brl

register = template.Library()

CORES = {"A": "success", "B": "info", "C": "warning", "D": "danger"}


@register.filter
def brl(v):
    return _brl(v) if v not in (None, "") else "—"


@register.filter
def rating_cor(r):
    return CORES.get(r, "secondary")


@register.inclusion_tag("core/_rating.html")
def rating(r, grande=False):
    return {"r": r or "—", "cor": CORES.get(r, "secondary"), "grande": grande}


@register.filter
def whatsapp_fmt(n):
    if not n:
        return ""
    d = n[2:] if n.startswith("55") else n
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return n


@register.filter
def split(s, sep=None):
    return s.split(sep)


@register.filter
def get_item(d, k):
    return (d or {}).get(k, 0)
