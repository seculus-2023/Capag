"""Permissões por perfil. Cada usuário tem um perfil (grupo do Django) e cada perfil
libera um conjunto de áreas do sistema. Para mudar o que um perfil pode fazer, altere PERFIS."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

PERMISSOES = {
    "crm": "Contatos, funil, consultas e conteúdos",
    "capag": "Empresas e análises de CAPAG",
    "processos": "Consultar processos e prazos e lançar andamentos",
    "processos_editar": "Cadastrar e alterar processos e prazos",
    "documentos": "Documentos dos clientes",
    "financeiro": "Honorários e despesas",
    "bi": "Inteligência comercial",
    "excluir": "Excluir registros",
    "administrar": "Usuários, parâmetros e aprovação de conteúdos",
}

PERFIS = {
    "SOCIO": ("Sócio", set(PERMISSOES)),
    "ADVOGADO": ("Advogado", {"crm", "capag", "processos", "processos_editar", "documentos"}),
    "ESTAGIARIO": ("Estagiário", {"crm", "capag", "processos", "documentos"}),
    "SECRETARIA": ("Secretaria", {"crm", "processos", "documentos"}),
    "FINANCEIRO": ("Financeiro", {"crm", "documentos", "financeiro"}),
}
PADRAO = "ADVOGADO"  # usuário comum ainda sem perfil definido
_POR_NOME = {nome: cod for cod, (nome, _) in PERFIS.items()}


def perfil_de(user):
    """Código do perfil do usuário. Superusuário e staff são sempre Sócio."""
    if not user.is_authenticated:
        return None
    if not hasattr(user, "_perfil"):
        if user.is_superuser or user.is_staff:
            user._perfil = "SOCIO"
        else:
            nomes = set(user.groups.values_list("name", flat=True))
            user._perfil = next((cod for cod, (nome, _) in PERFIS.items() if nome in nomes), PADRAO)
    return user._perfil


def nome_perfil(user):
    cod = perfil_de(user)
    return PERFIS[cod][0] if cod else ""


def pode(user, permissao):
    cod = perfil_de(user)
    return bool(cod) and permissao in PERFIS[cod][1]


def definir_perfil(user, cod):
    """Troca o perfil do usuário. Só o Sócio fica com acesso à área administrativa do Django."""
    nome = PERFIS[cod][0]
    user.groups.remove(*Group.objects.filter(name__in=_POR_NOME))
    user.groups.add(Group.objects.get_or_create(name=nome)[0])
    if not user.is_superuser:
        user.is_staff = cod == "SOCIO"
        user.save(update_fields=["is_staff"])
    user.__dict__.pop("_perfil", None)


def exige(*permissoes):
    """Decorator de view: exige login e todas as permissões informadas (senão, erro 403)."""
    def decorador(view):
        @wraps(view)
        @login_required
        def interna(request, *args, **kwargs):
            if not all(pode(request.user, p) for p in permissoes):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return interna
    return decorador


def contexto(request):
    """Context processor: {{ pode.financeiro }}, {{ perfil_nome }} nos templates."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"pode": {}, "perfil_nome": ""}
    return {"pode": {p: pode(user, p) for p in PERMISSOES}, "perfil_nome": nome_perfil(user)}
