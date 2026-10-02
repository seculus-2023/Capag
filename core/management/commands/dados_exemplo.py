"""Cria um usuário administrador (se não existir) e uma empresa/análise de exemplo."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import AnaliseCapag, Empresa, Parametro


class Command(BaseCommand):
    help = "Cria dados de exemplo (Ideal Terraplanagem) e o usuário admin/admin123 se não houver usuários."

    def handle(self, *args, **opts):
        User = get_user_model()
        if not User.objects.exists():
            User.objects.create_superuser("admin", "", "admin123")
            self.stdout.write(self.style.WARNING("Usuário admin / senha admin123 criado. TROQUE A SENHA."))
        Parametro.atual()
        emp, _ = Empresa.objects.get_or_create(cnpj="23.244.622/0001-60", defaults=dict(
            razao_social="IDEAL TERRAPLANAGEM LTDA", nome_fantasia="IDEAL TERRAPLANAGEM", porte="EPP",
            atividade="Obras de terraplenagem",
            endereco="Avenida Sul, 1855, Quadra IA, Lote 27, Setor Industrial, CEP 78643-000",
            municipio="Querência", uf="MT", responsavel="ANDERSON HOMMEL"))
        if not emp.analises.exists():
            AnaliseCapag.objects.create(
                empresa=emp, data_referencia=date.today(), descricao="Exemplo – valores fictícios",
                divida_principal=D("800000"), divida_multa=D("160000"), divida_juros=D("290000"), divida_encargos=D("150000"),
                capag_presumida=D("1900000"),
                receita_bruta_12m=D("2400000"), custos_despesas_12m=D("1950000"),
                parcelas_financiamento_12m=D("300000"), outras_dividas_12m=D("80000"),
                patrimonio_total=D("2600000"), bens_onerados=D("2200000"), disponibilidades=D("45000"),
                justificativa="Atividade sazonal (paralisação no período chuvoso), frota financiada com alienação "
                              "fiduciária e redução de faturamento no último exercício.")
        self.stdout.write(self.style.SUCCESS("Dados de exemplo prontos."))
