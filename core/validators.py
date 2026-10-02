import re

from django.core.exceptions import ValidationError


def somente_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def cnpj_valido(cnpj):
    cnpj = somente_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False

    def dv(base, pesos):
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(cnpj[:12], p1)
    d2 = dv(cnpj[:12] + d1, [6] + p1)
    return cnpj[12:] == d1 + d2


def validar_cnpj(valor):
    if not cnpj_valido(valor):
        raise ValidationError("CNPJ inválido.")


def formatar_cnpj(valor):
    c = somente_digitos(valor)
    if len(c) != 14:
        return valor
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def normalizar_whatsapp(valor):
    """Devolve o número no formato internacional 55DDDNUMERO (somente dígitos)."""
    n = somente_digitos(valor)
    if not n:
        return ""
    if not n.startswith("55") or len(n) <= 11:
        n = "55" + n.lstrip("0")
    return n


def validar_whatsapp(valor):
    n = normalizar_whatsapp(valor)
    if n and len(n) not in (12, 13):
        raise ValidationError("Informe o WhatsApp com DDD, ex.: (65) 99999-9999.")
