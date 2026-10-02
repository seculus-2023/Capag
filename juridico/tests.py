import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.perfis import definir_perfil, perfil_de, pode
from crm.models import Contato

from . import services
from .models import Documento, Lancamento, Prazo, Processo

MEDIA = tempfile.mkdtemp(prefix="capag_test_media_")


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=MEDIA)
class Base(TestCase):
    def setUp(self):
        User = get_user_model()
        self.socio = User.objects.create_user("socia", password="Senha@12345", is_staff=True, email="socia@exemplo.com")
        self.adv = User.objects.create_user("adv", password="Senha@12345", email="adv@exemplo.com")
        definir_perfil(self.adv, "ADVOGADO")
        self.cliente = Contato.objects.create(nome="Agro Sul Ltda", email="agro@exemplo.com", area_interesse="TRIB_EST")
        self.processo = Processo.objects.create(cliente=self.cliente, numero="1000123-45.2026.4.01.3600",
                                                titulo="Execução fiscal ICMS", area="TRIB_EST", responsavel=self.adv)
        self.client.force_login(self.socio)

    def usuario(self, perfil):
        u = get_user_model().objects.create_user(f"u_{perfil.lower()}", password="Senha@12345")
        definir_perfil(u, perfil)
        return u

    def prazo(self, dias, **kw):
        return Prazo.objects.create(processo=self.processo, descricao="Contestação", responsavel=self.adv,
                                    data_limite=timezone.localdate() + timedelta(days=dias), **kw)


class ProcessoTest(Base):
    def test_cadastro_andamento_e_prazo(self):
        r = self.client.post(reverse("juridico:processo_novo"), {
            "cliente": self.cliente.pk, "tipo": "ADMINISTRATIVO", "numero": "10183.000111/2026-11",
            "titulo": "Transação PGFN", "area": "TRIB_FED", "orgao": "PGFN", "posicao": "AUTOR",
            "valor_causa": "1.500.000,00", "status": "ATIVO", "responsavel": self.adv.pk})
        p = Processo.objects.get(titulo="Transação PGFN")
        self.assertRedirects(r, p.get_absolute_url())
        self.assertEqual((p.valor_causa, p.criado_por), (D("1500000.00"), self.socio))
        self.client.post(reverse("juridico:andamento_novo", args=[p.pk]), {"data": "2026-10-01", "descricao": "Protocolo."})
        self.client.post(reverse("juridico:prazo_novo", args=[p.pk]), {
            "tipo": "PRAZO", "descricao": "Juntar documentos", "data_limite": "2026-10-20", "responsavel": self.adv.pk})
        self.assertEqual((p.andamentos.count(), p.prazos.get().criado_por), (1, self.socio))
        self.assertContains(self.client.get(p.get_absolute_url()), "Juntar documentos")

    def test_agenda_separa_vencidos_hoje_e_proximos(self):
        venc, hoje, prox = self.prazo(-2), self.prazo(0), self.prazo(5)
        self.prazo(3, status="CUMPRIDO")
        g = services.agenda(Prazo.objects.all())
        self.assertEqual((g["vencidos"], g["hoje"], g["semana"], g["depois"]), ([venc], [hoje], [prox], []))
        self.assertEqual(self.client.get(reverse("juridico:agenda")).context["total"], 0)  # sócia não é a responsável
        self.assertEqual(self.client.get(reverse("juridico:agenda") + "?todos=1").context["total"], 3)

    def test_cumprir_e_reabrir_prazo(self):
        p = self.prazo(1)
        url = reverse("juridico:prazo_status", args=[p.pk])
        self.client.post(url, {"status": "CUMPRIDO"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.cumprido_por), ("CUMPRIDO", self.socio))
        self.client.post(url, {"status": "PENDENTE"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.cumprido_em), ("PENDENTE", None))

    def test_aviso_por_email_antes_e_no_dia_uma_vez_cada(self):
        hoje = date(2026, 10, 10)
        p = Prazo.objects.create(processo=self.processo, descricao="Recurso", responsavel=self.adv, data_limite=date(2026, 10, 12))
        Prazo.objects.create(processo=self.processo, descricao="Longe", responsavel=self.adv, data_limite=date(2026, 11, 30))
        self.assertEqual(services.avisar_prazos(hoje), 1)
        self.assertEqual(services.avisar_prazos(hoje), 0)
        self.assertEqual(mail.outbox[0].to, ["adv@exemplo.com"])
        self.assertIn("vence em 2 dia(s)", mail.outbox[0].subject)
        self.assertEqual(services.avisar_prazos(date(2026, 10, 12)), 1)
        self.assertEqual(services.avisar_prazos(date(2026, 10, 13)), 0)
        self.assertIn("vence HOJE", mail.outbox[1].subject)
        p.status = "CUMPRIDO"
        p.save()
        self.assertEqual(len(mail.outbox), 2)

    def test_nova_data_reabre_o_aviso(self):
        p = self.prazo(1, avisado_antes=True)
        self.client.post(reverse("juridico:prazo_editar", args=[p.pk]), {
            "tipo": "PRAZO", "descricao": "Contestação", "responsavel": self.adv.pk,
            "data_limite": (timezone.localdate() + timedelta(days=2)).isoformat()})
        p.refresh_from_db()
        self.assertFalse(p.avisado_antes)


class FinanceiroTest(Base):
    def lanc(self, **kw):
        dados = dict(cliente=self.cliente, descricao="Honorários", valor=D("1000"), vencimento=timezone.localdate())
        dados.update(kw)
        return Lancamento.objects.create(**dados)

    def test_parcelamento_mensal(self):
        self.client.post(reverse("juridico:lancamento_novo"), {
            "cliente": self.cliente.pk, "processo": self.processo.pk, "natureza": "RECEBER", "categoria": "CONTRATUAL",
            "descricao": "Honorários contratuais", "valor": "2.500,00", "vencimento": "2026-01-31", "parcelas": 3})
        ls = list(Lancamento.objects.order_by("vencimento"))
        self.assertEqual([x.vencimento for x in ls], [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)])
        self.assertEqual([x.descricao for x in ls][0], "Honorários contratuais (1/3)")
        self.assertEqual({x.valor for x in ls}, {D("2500.00")})

    def test_processo_de_outro_cliente_e_recusado(self):
        outro = Contato.objects.create(nome="Outro", email="o@exemplo.com")
        r = self.client.post(reverse("juridico:lancamento_novo"), {
            "cliente": outro.pk, "processo": self.processo.pk, "natureza": "RECEBER", "categoria": "EXITO",
            "descricao": "x", "valor": "10,00", "vencimento": "2026-01-10", "parcelas": 1})
        self.assertContains(r, "de outro cliente")
        self.assertFalse(Lancamento.objects.exists())

    def test_resumo_baixa_e_estorno(self):
        hoje = timezone.localdate()
        aberto = self.lanc(vencimento=hoje + timedelta(days=5))
        self.lanc(vencimento=hoje - timedelta(days=5), valor=D("300"))
        self.lanc(natureza="PAGAR", categoria="CUSTAS", valor=D("80"))
        r = services.resumo_financeiro()
        self.assertEqual((r["a_receber"], r["em_atraso"], r["recebido_mes"], r["despesas_abertas"]),
                         (D("1300"), D("300"), 0, D("80")))
        url = reverse("juridico:lancamento_pagar", args=[aberto.pk])
        self.client.post(url, {"forma_pagamento": "PIX"})
        aberto.refresh_from_db()
        self.assertEqual((aberto.pago_em, aberto.forma_pagamento, aberto.situacao[0]), (hoje, "PIX", "Pago"))
        self.assertEqual(services.resumo_financeiro()["recebido_mes"], D("1000"))
        self.client.post(url, {"acao": "estornar"})
        aberto.refresh_from_db()
        self.assertIsNone(aberto.pago_em)

    def test_tela_filtros_e_csv(self):
        self.lanc(descricao="Parcela de êxito")
        self.lanc(descricao="Já paga", pago_em=timezone.localdate())
        r = self.client.get(reverse("juridico:financeiro"))
        self.assertContains(r, "Parcela de êxito")
        self.assertNotContains(r, "Já paga")
        csv_ = self.client.get(reverse("juridico:financeiro") + "?situacao=todos&formato=csv").content.decode("utf-8-sig")
        self.assertIn("Agro Sul Ltda", csv_)
        self.assertIn("Já paga;1000,00;Pago", csv_)


class DocumentoTest(Base):
    def enviar(self, nome="procuracao.pdf", conteudo=b"%PDF-1.4 teste", **extra):
        return self.client.post(reverse("juridico:documento_novo", args=[self.cliente.pk]),
                                {"arquivo": SimpleUploadedFile(nome, conteudo), "categoria": "PROCURACAO", **extra})

    def test_envio_download_e_exclusao(self):
        self.enviar(processo=self.processo.pk)
        d = Documento.objects.get()
        self.assertEqual((d.titulo, d.nome_original, d.tamanho, d.processo, d.enviado_por),
                         ("procuracao", "procuracao.pdf", 14, self.processo, self.socio))
        self.assertTrue(d.arquivo.name.startswith(f"clientes/{self.cliente.pk}/"))
        self.assertNotIn("procuracao", d.arquivo.name)
        r = self.client.get(reverse("juridico:documento_baixar", args=[d.pk]))
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 teste")
        self.assertIn('filename="procuracao.pdf"', r["Content-Disposition"])
        caminho = d.arquivo.path
        self.client.post(reverse("juridico:documento_excluir", args=[d.pk]))
        self.assertFalse(Documento.objects.exists())
        import os
        self.assertFalse(os.path.exists(caminho))

    def test_recusa_tipo_nao_aceito(self):
        self.enviar("virus.exe", b"MZ")
        self.assertFalse(Documento.objects.exists())

    def test_download_exige_login_e_permissao(self):
        self.enviar()
        url = reverse("juridico:documento_baixar", args=[Documento.objects.get().pk])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.usuario("FINANCEIRO"))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_cliente_com_pasta_nao_e_excluido(self):
        r = self.client.post(reverse("crm:contato_excluir", args=[self.cliente.pk]), follow=True)
        self.assertTrue(Contato.objects.filter(pk=self.cliente.pk).exists())
        self.assertContains(r, "tem processos, documentos ou lançamentos")


class PerfisTest(Base):
    def acesso(self, perfil):
        self.client.force_login(self.usuario(perfil))
        urls = {"capag": reverse("empresa_lista"), "crm": reverse("crm:contato_lista"), "bi": reverse("crm:relatorio"),
                "processos": reverse("juridico:processo_lista"), "processo_novo": reverse("juridico:processo_novo"),
                "financeiro": reverse("juridico:financeiro"), "usuarios": reverse("usuarios"),
                "parametros": reverse("parametros"), "pasta": reverse("juridico:pasta", args=[self.cliente.pk])}
        return {k for k, u in urls.items() if self.client.get(u).status_code == 200}

    def test_matriz_de_acesso(self):
        tudo = {"capag", "crm", "bi", "processos", "processo_novo", "financeiro", "usuarios", "parametros", "pasta"}
        self.assertEqual(self.acesso("SOCIO"), tudo)
        self.assertEqual(self.acesso("ADVOGADO"), {"capag", "crm", "processos", "processo_novo", "pasta"})
        self.assertEqual(self.acesso("ESTAGIARIO"), {"capag", "crm", "processos", "pasta"})
        self.assertEqual(self.acesso("SECRETARIA"), {"crm", "processos", "pasta"})
        self.assertEqual(self.acesso("FINANCEIRO"), {"crm", "financeiro", "pasta"})

    def test_so_socio_exclui(self):
        self.client.force_login(self.adv)
        self.assertEqual(self.client.post(reverse("juridico:processo_excluir", args=[self.processo.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("crm:contato_excluir", args=[self.cliente.pk])).status_code, 403)
        self.client.force_login(self.socio)
        self.client.post(reverse("juridico:processo_excluir", args=[self.processo.pk]))
        self.assertFalse(Processo.objects.exists())

    def test_estagiario_lanca_andamento_mas_nao_prazo(self):
        self.client.force_login(self.usuario("ESTAGIARIO"))
        self.client.post(reverse("juridico:andamento_novo", args=[self.processo.pk]), {"data": "2026-10-01", "descricao": "Carga."})
        self.assertEqual(self.processo.andamentos.count(), 1)
        r = self.client.get(reverse("juridico:prazo_novo", args=[self.processo.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "não tem acesso", status_code=403)

    def test_pasta_e_menu_escondem_o_financeiro(self):
        Lancamento.objects.create(cliente=self.cliente, descricao="Honorários sigilosos", valor=D("9"), vencimento=date(2026, 1, 1))
        self.client.force_login(self.adv)
        r = self.client.get(reverse("juridico:pasta", args=[self.cliente.pk]))
        self.assertNotContains(r, "Honorários sigilosos")
        self.assertNotContains(r, reverse("juridico:financeiro"))
        self.assertContains(r, "Execução fiscal ICMS")

    def test_perfil_padrao_troca_e_redirecionamento(self):
        sem = get_user_model().objects.create_user("semperfil", password="Senha@12345")
        self.assertEqual(perfil_de(sem), "ADVOGADO")
        fin = self.usuario("FINANCEIRO")
        self.client.force_login(fin)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("juridico:financeiro"))
        self.client.force_login(self.socio)
        self.client.post(reverse("usuario_alterar", args=[fin.pk]), {"perfil": "SOCIO"})
        fin = get_user_model().objects.get(pk=fin.pk)
        self.assertTrue(fin.is_staff and pode(fin, "administrar"))
        self.client.post(reverse("usuario_alterar", args=[fin.pk]), {"perfil": "SECRETARIA"})
        fin = get_user_model().objects.get(pk=fin.pk)
        self.assertEqual((fin.is_staff, perfil_de(fin)), (False, "SECRETARIA"))
        self.client.post(reverse("usuario_alterar", args=[self.socio.pk]), {"perfil": "ESTAGIARIO"})
        self.assertEqual(perfil_de(get_user_model().objects.get(pk=self.socio.pk)), "SOCIO")

    def test_criar_e_bloquear_usuario(self):
        r = self.client.post(reverse("usuarios"), {"username": "nova", "first_name": "Nova", "last_name": "Pessoa",
                                                   "email": "nova@exemplo.com", "perfil": "SECRETARIA",
                                                   "password1": "Xk9#mPq2vL", "password2": "Xk9#mPq2vL"})
        self.assertRedirects(r, reverse("usuarios"))
        nova = get_user_model().objects.get(username="nova")
        self.assertEqual(perfil_de(nova), "SECRETARIA")
        self.client.post(reverse("usuario_alterar", args=[nova.pk]), {"acao": "ativo"})
        self.assertFalse(get_user_model().objects.get(pk=nova.pk).is_active)
        self.assertContains(self.client.get(reverse("usuarios")), "bloqueado")
