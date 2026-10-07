from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .envio import link_publico
from .models import AnaliseCapag, Empresa, EnvioCapag
from .validators import cnpj_valido, normalizar_whatsapp


def nova_analise(empresa, **kw):
    dados = dict(data_referencia=date(2026, 9, 1),
                 divida_principal=D("800000"), divida_multa=D("160000"), divida_juros=D("290000"),
                 divida_encargos=D("150000"), capag_presumida=D("1900000"),
                 receita_bruta_12m=D("2400000"), custos_despesas_12m=D("1950000"),
                 parcelas_financiamento_12m=D("300000"), outras_dividas_12m=D("80000"),
                 patrimonio_total=D("2600000"), bens_onerados=D("2200000"), disponibilidades=D("45000"))
    dados.update(kw)
    return AnaliseCapag.objects.create(empresa=empresa, **dados)


class Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("antonio", password="Senha@12345", is_staff=True)
        self.empresa = Empresa.objects.create(cnpj="23244622000160", razao_social="IDEAL TERRAPLANAGEM LTDA",
                                              porte="EPP", email="cliente@exemplo.com", whatsapp="(65) 99999-8888")


class ValidadoresTest(TestCase):
    def test_cnpj(self):
        self.assertTrue(cnpj_valido("23.244.622/0001-60"))
        self.assertFalse(cnpj_valido("23.244.622/0001-61"))
        self.assertFalse(cnpj_valido("11111111111111"))

    def test_whatsapp(self):
        self.assertEqual(normalizar_whatsapp("(65) 99999-8888"), "5565999998888")
        self.assertEqual(normalizar_whatsapp("+55 65 99999-8888"), "5565999998888")


class CalculoTest(Base):
    def test_capag_real_e_rating(self):
        a = nova_analise(self.empresa)
        # resultado anual = 2.400.000 − 1.950.000 − 300.000 − 80.000 = 70.000
        self.assertEqual(a.resultado_anual_livre, D("70000.00"))
        self.assertEqual(a.geracao_futura, D("350000.00"))
        self.assertEqual(a.patrimonio_livre, D("400000.00"))
        self.assertEqual(a.capag_real, D("795000.00"))
        self.assertEqual(a.divida_total, D("1400000.00"))
        self.assertEqual(a.rating_real, "C")            # 0,57× a dívida
        self.assertEqual(a.rating_presumido_calc, "B")  # 1,36× a dívida
        self.assertTrue(a.revisao_favoravel)

    def test_desconto_respeita_limites(self):
        a = nova_analise(self.empresa)
        # necessário 605.000; limite 70% (EPP) = 980.000; acréscimos = 600.000 → 600.000
        self.assertEqual(a.desconto_estimado, D("600000.00"))
        self.assertEqual(a.valor_apos_desconto, D("800000.00"))  # nunca abaixo do principal
        self.assertEqual(a.prazo_maximo, 145)

    def test_irrecuperavel_forca_d(self):
        a = nova_analise(self.empresa, situacao_irrecuperavel=True, receita_bruta_12m=D("90000000"))
        self.assertEqual(a.rating_real, "D")

    def test_rating_a_sem_desconto(self):
        a = nova_analise(self.empresa, receita_bruta_12m=D("5000000"))
        self.assertEqual(a.rating_real, "A")
        self.assertEqual(a.desconto_estimado, D("0.00"))


class TelasTest(Base):
    def test_login_obrigatorio(self):
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, reverse("login") + "?next=/")

    def test_fluxo_completo(self):
        self.client.login(username="antonio", password="Senha@12345")
        for nome in ["dashboard", "empresa_lista", "analise_lista", "envio_lista", "parametros"]:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)
        r = self.client.post(reverse("analise_nova", args=[self.empresa.pk]), {
            "data_referencia": "2026-09-30", "status": "RASCUNHO",
            "divida_principal": "800.000,00", "divida_multa": "160.000,00", "divida_juros": "290.000,00",
            "divida_encargos": "150.000,00", "capag_presumida": "1.900.000,00",
            "receita_bruta_12m": "2.400.000,00", "custos_despesas_12m": "1.950.000,00",
            "parcelas_financiamento_12m": "300.000,00", "outras_dividas_12m": "80.000,00",
            "patrimonio_total": "2.600.000,00", "bens_onerados": "2.200.000,00", "disponibilidades": "45.000,00",
        })
        a = AnaliseCapag.objects.get()
        self.assertRedirects(r, a.get_absolute_url())
        self.assertEqual(a.capag_real, D("795000.00"))
        for nome in ["analise_detalhe", "analise_editar", "enviar_email", "enviar_whatsapp"]:
            self.assertEqual(self.client.get(reverse(nome, args=[a.pk])).status_code, 200, nome)
        r = self.client.get(reverse("analise_pdf", args=[a.pk]))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_envio_email_com_pdf(self):
        self.client.login(username="antonio", password="Senha@12345")
        a = nova_analise(self.empresa)
        r = self.client.post(reverse("enviar_email", args=[a.pk]),
                             {"destino": "cliente@exemplo.com", "assunto": "CAPAG", "mensagem": "Segue"})
        self.assertRedirects(r, a.get_absolute_url())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0][2], "application/pdf")
        a.refresh_from_db()
        self.assertEqual(a.status, "ENVIADA")

    @override_settings(WHATSAPP_TOKEN="", WHATSAPP_PHONE_NUMBER_ID="")
    def test_whatsapp_sem_api_gera_link(self):
        self.client.login(username="antonio", password="Senha@12345")
        a = nova_analise(self.empresa)
        r = self.client.post(reverse("enviar_whatsapp", args=[a.pk]), {"numero": "65999998888", "mensagem": "Olá"})
        self.assertContains(r, "https://wa.me/5565999998888")
        self.assertEqual(EnvioCapag.objects.get().status, "LINK")

    @override_settings(WHATSAPP_TOKEN="tok", WHATSAPP_PHONE_NUMBER_ID="123")
    def test_whatsapp_cloud_api(self):
        self.client.login(username="antonio", password="Senha@12345")
        a = nova_analise(self.empresa)
        up = mock.Mock(status_code=200, **{"json.return_value": {"id": "MEDIA1"}})
        msg = mock.Mock(status_code=200, text='{"messages":[{"id":"x"}]}')
        with mock.patch("core.envio.requests.post", side_effect=[up, msg]) as post:
            self.client.post(reverse("enviar_whatsapp", args=[a.pk]), {"numero": "65999998888", "mensagem": "Olá"})
        self.assertEqual(post.call_args_list[1].kwargs["json"]["document"]["id"], "MEDIA1")
        self.assertEqual(EnvioCapag.objects.get().status, "ENVIADO")

    def test_pdf_publico(self):
        a = nova_analise(self.empresa)
        url = link_publico(a).split("8000", 1)[-1]
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/p/token-falso/").status_code, 404)


class RelatoriosTest(Base):
    def setUp(self):
        super().setUp()
        self.client.login(username="antonio", password="Senha@12345")

    def test_indicadores(self):
        from .relatorios import indicadores
        a = nova_analise(self.empresa, ativo_circulante=D("300000"), passivo_circulante=D("200000"))
        ind = indicadores(a)
        self.assertEqual(ind["endividamento"]["valor"], D("1400000") / D("2400000"))
        self.assertEqual(ind["poupanca"]["valor"], D("2330000") / D("2400000"))
        self.assertEqual(ind["liquidez"]["valor"], D("1.5"))
        self.assertFalse(ind["liquidez"]["estimada"])
        self.assertTrue(indicadores(nova_analise(self.empresa))["liquidez"]["estimada"])

    def test_ranking_e_filtros(self):
        nova_analise(self.empresa)
        outra = Empresa.objects.create(cnpj="11222333000181", razao_social="BETA LTDA", atividade="Comércio")
        nova_analise(outra, receita_bruta_12m=D("5000000"))
        r = self.client.get(reverse("relatorio_ranking"))
        self.assertEqual([len(v) for v in r.context["grupos"].values()], [1, 0, 1, 0])
        r = self.client.get(reverse("relatorio_ranking"), {"setor": "comér", "faixa": "A"})
        self.assertEqual(list(r.context["grupos"]), ["A"])
        self.assertEqual(r.context["total"], 1)
        r = self.client.get(reverse("relatorio_ranking"), {"formato": "csv"})
        self.assertIn("BETA LTDA", r.content.decode("utf-8"))

    def test_evolucao(self):
        nova_analise(self.empresa, data_referencia=date(2024, 12, 31), receita_bruta_12m=D("5000000"))
        nova_analise(self.empresa, data_referencia=date(2025, 6, 1))
        nova_analise(self.empresa, data_referencia=date(2025, 12, 31), receita_bruta_12m=D("5000000"))
        r = self.client.get(reverse("relatorio_evolucao"), {"empresa": self.empresa.pk})
        self.assertEqual([a.ano for a in r.context["linhas"]], [2024, 2025])  # última de cada ano
        self.assertContains(r, "<polyline")
        self.assertNotContains(r, 'cx="92,')  # coordenadas do SVG sem vírgula decimal

    def test_composicao_tela_e_pdf(self):
        a = nova_analise(self.empresa)
        r = self.client.get(reverse("relatorio_composicao_analise", args=[a.pk]))
        self.assertContains(r, "Poupança corrente")
        r = self.client.get(reverse("relatorio_composicao_analise", args=[a.pk]), {"formato": "pdf"})
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertContains(self.client.get(reverse("analise_detalhe", args=[a.pk])), "modalComposicao")

    def test_alertas(self):
        from .relatorios import alertas
        nova_analise(self.empresa, data_referencia=date(2025, 6, 1), receita_bruta_12m=D("9000000"))  # A
        nova_analise(self.empresa, data_referencia=date(2026, 6, 1), receita_bruta_12m=D("0"))         # D
        lista = alertas(AnaliseCapag.objects.all(), hoje=date(2026, 9, 30))
        tipos = {(x.tipo, x.severidade) for x in lista}
        self.assertIn(("rebaixamento", "critico"), tipos)
        self.assertIn(("inconsistencia", "critico"), tipos)  # receita zerada
        r = self.client.get(reverse("relatorio_alertas"), {"severidade": "critico"})
        self.assertContains(r, "Nota caiu de A")
        self.assertEqual(self.client.get(reverse("relatorio_alertas"), {"formato": "csv"}).status_code, 200)

    def test_regime_indicacao_e_servicos(self):
        from consultoria.models import Produto
        capag = Produto.objects.create(nome="Revisão de CAPAG", area="TRIB_FED", escopo="x")
        transacao = Produto.objects.create(nome="Transação tributária", area="TRIB_FED", escopo="x")
        r = self.client.post(reverse("empresa_editar", args=[self.empresa.pk]), {
            "cnpj": self.empresa.cnpj, "razao_social": self.empresa.razao_social, "porte": "EPP",
            "regime_tributario": "PRESUMIDO", "indicado_por": "Contador João", "servicos": [capag.pk, transacao.pk],
        })
        self.assertRedirects(r, self.empresa.get_absolute_url())
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.get_regime_tributario_display(), "Lucro Presumido")
        self.assertEqual(set(self.empresa.servicos.all()), {capag, transacao})
        self.assertContains(self.client.get(self.empresa.get_absolute_url()), "Contador João")

        outra = Empresa.objects.create(cnpj="11222333000181", razao_social="BETA LTDA", regime_tributario="SIMPLES")
        outra.servicos.add(transacao)
        nova_analise(self.empresa)
        nova_analise(outra)

        r = self.client.get(reverse("relatorio_servicos"))
        grupos = {g["nome"]: [e.razao_social for e in g["empresas"]] for g in r.context["grupos"]}
        self.assertEqual(grupos, {"Transação tributária": ["BETA LTDA", "IDEAL TERRAPLANAGEM LTDA"],
                                  "Revisão de CAPAG": ["IDEAL TERRAPLANAGEM LTDA"]})
        r = self.client.get(reverse("relatorio_servicos"), {"servico": capag.pk})
        self.assertEqual([g["nome"] for g in r.context["grupos"]], ["Revisão de CAPAG"])
        r = self.client.get(reverse("relatorio_servicos"), {"regime": "SIMPLES"})
        self.assertEqual(r.context["total"], 1)
        csv = self.client.get(reverse("relatorio_servicos"), {"formato": "csv"}).content.decode("utf-8")
        self.assertIn("Lucro Presumido;Contador João", csv)

        r = self.client.get(reverse("relatorio_ranking"), {"servico": capag.pk})
        self.assertEqual(r.context["total"], 1)
        r = self.client.get(reverse("relatorio_ranking"), {"indicado": "joão", "formato": "csv"})
        self.assertIn("Revisão de CAPAG, Transação tributária", r.content.decode("utf-8"))
        r = self.client.get(reverse("empresa_lista"), {"regime": "SIMPLES"})
        self.assertEqual([e.razao_social for e in r.context["page"]], ["BETA LTDA"])

    def test_telas_vazias(self):
        for nome in ["relatorios", "relatorio_ranking", "relatorio_evolucao", "relatorio_composicao", "relatorio_alertas",
                     "relatorio_servicos"]:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)


class PwaTest(TestCase):
    def test_manifest_sw_e_offline_sem_login(self):
        m = self.client.get(reverse("pwa_manifest"))
        self.assertEqual(m["Content-Type"], "application/manifest+json")
        self.assertEqual((m.json()["display"], m.json()["start_url"]), ("standalone", "/"))
        self.assertEqual({i["sizes"] for i in m.json()["icons"]}, {"192x192", "512x512"})
        sw = self.client.get("/sw.js")
        self.assertEqual(sw["Content-Type"], "application/javascript")
        self.assertIn("startsWith('/static/')", sw.content.decode())
        self.assertContains(self.client.get(reverse("pwa_offline")), "Sem conexão")

    def test_telas_trazem_o_manifest(self):
        r = self.client.get(reverse("login"))
        self.assertContains(r, 'rel="manifest"')
        self.assertContains(r, "serviceWorker")
