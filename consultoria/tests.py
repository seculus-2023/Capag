from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.perfis import definir_perfil
from crm.models import Contato, Interacao, Oportunidade
from juridico.models import Lancamento

from . import services
from .models import ItemProposta, Produto, Projeto, Proposta


class Base(TestCase):
    def setUp(self):
        User = get_user_model()
        self.socio = User.objects.create_user("socia", password="Senha@12345", is_staff=True)
        self.adv = User.objects.create_user("adv", password="Senha@12345")
        definir_perfil(self.adv, "ADVOGADO")
        self.contato = Contato.objects.create(nome="Transportes Rio Ltda", email="rio@exemplo.com",
                                              whatsapp="65999998888", area_interesse="TRIB_FED")
        self.op = Oportunidade.objects.create(contato=self.contato, titulo="Revisão de CAPAG", area="TRIB_FED",
                                              responsavel=self.adv)
        self.diag = Produto.objects.create(nome="Diagnóstico X", area="TRIB_FED", cobranca="FIXO",
                                           valor_referencia=D("10000.00"), prazo_dias=15, escopo="Diagnóstico.",
                                           entregas="Levantamento\nRelatório", documentos="Balanço\nCartão CNPJ")
        self.mensal = Produto.objects.create(nome="Assessoria X", area="TRIB_FED", cobranca="MENSAL",
                                             valor_referencia=D("2000.00"), prazo_dias=30, escopo="Assessoria.",
                                             documentos="cartão cnpj", percentual_exito=D("10"))
        self.client.force_login(self.adv)

    def proposta(self, **kw):
        p = Proposta.objects.create(oportunidade=self.op, criado_por=self.adv, **kw)
        ItemProposta.objects.create(proposta=p, produto=self.diag, valor=D("10000.00"))
        ItemProposta.objects.create(proposta=p, produto=self.mensal, valor=D("2000.00"), percentual_exito=D("10"))
        return p


class CatalogoTest(Base):
    def test_catalogo_inicial_criado_pela_migracao(self):
        self.assertTrue(Produto.objects.filter(nome="Diagnóstico de CAPAG", usa_capag=True).exists())

    def test_so_socio_edita_precos(self):
        self.assertEqual(self.client.get(reverse("consultoria:catalogo")).status_code, 200)
        self.assertEqual(self.client.get(reverse("consultoria:produto_novo")).status_code, 403)
        self.client.force_login(self.socio)
        r = self.client.post(reverse("consultoria:produto_novo"), {
            "nome": "Parecer Y", "area": "AMBIENTAL", "cobranca": "FIXO", "valor_referencia": "3.500,00",
            "percentual_exito": "0", "prazo_dias": 20, "ativo": "on", "escopo": "Parecer."})
        self.assertRedirects(r, reverse("consultoria:catalogo"))
        self.assertEqual(Produto.objects.get(nome="Parecer Y").valor_referencia, D("3500.00"))

    def test_perfis_sem_acesso(self):
        for perfil in ("SECRETARIA", "FINANCEIRO", "ESTAGIARIO"):
            u = get_user_model().objects.create_user(f"u_{perfil}", password="Senha@12345")
            definir_perfil(u, perfil)
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("consultoria:proposta_lista")).status_code, 403, perfil)


class PropostaTest(Base):
    def test_criar_com_valor_do_catalogo(self):
        url = reverse("consultoria:proposta_nova", args=[self.op.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        dados = {"validade": "2026-12-31", "parcelas": 2, "meses_mensalidade": 6, "condicoes": "",
                 "itens-TOTAL_FORMS": 3, "itens-INITIAL_FORMS": 0, "itens-MIN_NUM_FORMS": 1, "itens-MAX_NUM_FORMS": 1000,
                 "itens-0-produto": self.diag.pk, "itens-0-descricao": "", "itens-0-valor": "", "itens-0-percentual_exito": "",
                 "itens-1-produto": self.mensal.pk, "itens-1-descricao": "Assessoria 6 meses", "itens-1-valor": "1.500,00",
                 "itens-1-percentual_exito": "0"}
        r = self.client.post(url, dados)
        p = Proposta.objects.get()
        self.assertRedirects(r, p.get_absolute_url())
        itens = {i.produto_id: i for i in p.itens.all()}
        self.assertEqual((itens[self.diag.pk].valor, itens[self.diag.pk].descricao), (D("10000.00"), "Diagnóstico X"))
        self.assertEqual((itens[self.mensal.pk].valor, itens[self.mensal.pk].cobranca), (D("1500.00"), "MENSAL"))
        self.assertEqual(p.total_estimado, D("10000.00") + D("1500.00") * 6)

    def test_sem_itens_nao_salva(self):
        r = self.client.post(reverse("consultoria:proposta_nova", args=[self.op.pk]), {
            "validade": "2026-12-31", "parcelas": 1, "meses_mensalidade": 12,
            "itens-TOTAL_FORMS": 1, "itens-INITIAL_FORMS": 0, "itens-MIN_NUM_FORMS": 1, "itens-MAX_NUM_FORMS": 1000})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Proposta.objects.exists())

    def test_pdf(self):
        p = self.proposta()
        r = self.client.get(reverse("consultoria:proposta_pdf", args=[p.pk]))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_pdf_com_diagnostico_capag_e_analise_sugerida(self):
        from core.models import Empresa
        from core.tests import nova_analise
        empresa = Empresa.objects.create(cnpj="23244622000160", razao_social="TRANSPORTES RIO LTDA", porte="EPP")
        self.contato.empresa = empresa
        self.contato.save()
        analise = nova_analise(empresa)
        r = self.client.get(reverse("consultoria:proposta_nova", args=[self.op.pk]))
        self.assertEqual(r.context["form"].initial["analise"], analise.pk)  # sugere a última análise da empresa
        p = self.proposta(analise=analise)
        self.assertTrue(self.client.get(reverse("consultoria:proposta_pdf", args=[p.pk])).content.startswith(b"%PDF"))
        self.assertEqual(self.client.get(p.get_absolute_url()).status_code, 200)

    def test_envio_email_move_o_funil(self):
        p = self.proposta()
        r = self.client.post(reverse("consultoria:proposta_enviar", args=[p.pk]),
                             {"canal": "EMAIL", "destino": "rio@exemplo.com", "mensagem": "Segue."})
        self.assertRedirects(r, p.get_absolute_url())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0][2], "application/pdf")
        p.refresh_from_db()
        self.op.refresh_from_db()
        self.assertEqual((p.status, p.enviada_em), ("ENVIADA", timezone.localdate()))
        self.assertEqual((self.op.etapa, self.op.valor_estimado), ("PROPOSTA", D("34000.00")))
        self.assertTrue(Interacao.objects.filter(oportunidade=self.op, tipo="EMAIL").exists())
        # enviada não se edita
        self.assertRedirects(self.client.get(reverse("consultoria:proposta_editar", args=[p.pk])), p.get_absolute_url())

    def test_whatsapp_link_publico(self):
        p = self.proposta()
        r = self.client.post(reverse("consultoria:proposta_enviar", args=[p.pk]),
                             {"canal": "WHATSAPP", "destino": "(65) 99999-8888", "mensagem": "Segue."})
        self.assertTrue(r.url.startswith("https://wa.me/5565999998888"))
        self.client.logout()
        link = services.link_publico(p).split("/consultoria/")[1]
        self.assertEqual(self.client.get(f"/consultoria/{link}")["Content-Type"], "application/pdf")
        self.assertEqual(self.client.get("/consultoria/p/token-falso/").status_code, 404)

    def test_aceite_abre_projeto_e_lanca_honorarios(self):
        p = self.proposta(status="ENVIADA", parcelas=3, meses_mensalidade=12, primeiro_vencimento=date(2026, 11, 10))
        r = self.client.post(reverse("consultoria:proposta_acao", args=[p.pk, "aceitar"]), {"data": "2026-10-05"})
        projeto = Projeto.objects.get()
        self.assertRedirects(r, projeto.get_absolute_url())
        self.assertEqual((projeto.cliente, projeto.responsavel, projeto.prazo), (self.contato, self.adv, date(2026, 11, 4)))
        # documentos sem repetição ("Cartão CNPJ" e "cartão cnpj") + entregas
        self.assertEqual([e.descricao for e in projeto.etapas.filter(tipo="DOCUMENTO")],
                         ["Receber: Balanço", "Receber: Cartão CNPJ"])
        self.assertEqual(projeto.etapas.filter(tipo="ENTREGA").count(), 2)
        self.assertIn("10% sobre o benefício", projeto.observacoes)
        fixos = Lancamento.objects.filter(cliente=self.contato, categoria="CONTRATUAL").order_by("vencimento")
        self.assertEqual([x.valor for x in fixos], [D("3333.33"), D("3333.33"), D("3333.34")])
        self.assertEqual(fixos[1].vencimento, date(2026, 12, 10))
        mensais = Lancamento.objects.filter(categoria="MENSAL")
        self.assertEqual((mensais.count(), mensais.first().valor), (12, D("2000.00")))
        # proposta aceita não se exclui
        self.client.post(reverse("consultoria:proposta_acao", args=[p.pk, "excluir"]))
        self.assertTrue(Proposta.objects.filter(pk=p.pk).exists())

    def test_rascunho_nao_pode_ser_aceito(self):
        p = self.proposta()
        self.client.post(reverse("consultoria:proposta_acao", args=[p.pk, "aceitar"]))
        self.assertFalse(Projeto.objects.exists())

    def test_recusar_voltar_e_duplicar(self):
        p = self.proposta(status="ENVIADA")
        self.client.post(reverse("consultoria:proposta_acao", args=[p.pk, "recusar"]), {"motivo": "Preço"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.motivo_recusa), ("RECUSADA", "Preço"))
        self.client.post(reverse("consultoria:proposta_acao", args=[p.pk, "rascunho"]))
        p.refresh_from_db()
        self.assertEqual(p.status, "RASCUNHO")
        self.client.post(reverse("consultoria:proposta_acao", args=[p.pk, "duplicar"]))
        nova = Proposta.objects.exclude(pk=p.pk).get()
        self.assertEqual((nova.status, nova.itens.count()), ("RASCUNHO", 2))
        self.assertNotEqual(nova.token, p.token)

    def test_expirada(self):
        p = self.proposta(status="ENVIADA", validade=timezone.localdate() - timedelta(days=1))
        self.assertTrue(p.expirada)


class ProjetoEIndicadoresTest(Base):
    def test_etapas_e_conclusao(self):
        p = self.proposta(status="ENVIADA")
        projeto = services.aceitar(p, self.adv)
        etapa = projeto.etapas.first()
        self.client.post(reverse("consultoria:etapa_marcar", args=[etapa.pk]))
        self.assertEqual(Projeto.objects.get().progresso, 25)
        self.client.post(reverse("consultoria:etapa_nova", args=[projeto.pk]), {"descricao": "Reunião final"})
        self.assertEqual(projeto.etapas.count(), 5)
        self.client.post(reverse("consultoria:projeto_status", args=[projeto.pk]), {"status": "CONCLUIDO"})
        projeto.refresh_from_db()
        self.assertEqual((projeto.status, projeto.concluido_em), ("CONCLUIDO", timezone.localdate()))
        self.assertEqual(self.client.get(reverse("juridico:pasta", args=[self.contato.pk])).status_code, 200)

    def test_indicadores(self):
        services.aceitar(self.proposta(status="ENVIADA"), self.adv)
        services.recusar(self.proposta(status="ENVIADA"), self.adv)
        i = services.indicadores(Proposta.objects.all())
        self.assertEqual((i["taxa_aceite"], i["receita"], i["recorrente"]), (50, D("34000.00"), D("2000.00")))
        self.assertEqual(dict(i["produtos"])["Diagnóstico X"]["vendas"], 1)
        self.assertEqual(self.client.get(reverse("consultoria:indicadores")).status_code, 403)  # advogado sem BI
        self.client.force_login(self.socio)
        self.assertEqual(self.client.get(reverse("consultoria:indicadores")).status_code, 200)

    def test_telas_abrem(self):
        p = self.proposta()
        for url in (reverse("consultoria:proposta_lista"), reverse("consultoria:projeto_lista"),
                    p.get_absolute_url(), reverse("consultoria:proposta_editar", args=[p.pk]),
                    self.op.get_absolute_url()):
            self.assertEqual(self.client.get(url).status_code, 200, url)
