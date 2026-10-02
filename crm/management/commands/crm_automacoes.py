"""Rotina automática do CRM. Agende para rodar de hora em hora (Agendador de Tarefas / cron):

    python manage.py crm_automacoes
"""
from django.core.management.base import BaseCommand

from crm import feeds, services
from juridico.services import avisar_prazos


class Command(BaseCommand):
    help = "Envia lembretes de reunião e avisos de prazo, dispara os conteúdos aprovados e busca as atualizações."

    def add_arguments(self, parser):
        parser.add_argument("--sem-feeds", action="store_true", help="Não consulta as fontes de atualização.")

    def handle(self, *args, **opts):
        lembretes = services.enviar_lembretes()
        conteudos = services.disparar_conteudos_pendentes()
        erros = sum(1 for m in lembretes + conteudos if m.status == "ERRO")
        self.stdout.write(f"Lembretes de reunião: {len(lembretes)} · Conteúdos informativos: {len(conteudos)} · Falhas: {erros}")
        self.stdout.write(f"Propostas aguardando follow-up: {len(services.pendentes_followup())}")
        self.stdout.write(f"Avisos de prazo enviados por e-mail: {avisar_prazos()}")
        if not opts["sem_feeds"]:
            self.stdout.write(f"Atualizações jurídicas novas: {feeds.atualizar_tudo()}")
