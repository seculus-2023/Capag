from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import feeds, services
from .forms import ConteudoForm
from .models import Atualizacao, Contato, Conteudo, Fonte, Interacao, Mensagem, Oportunidade, Reuniao

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>PGFN abre novo edital de transa&#231;&#227;o</title><link>https://exemplo.com/a</link>
<description>&lt;p&gt;Edital da &lt;b&gt;PGFN&lt;/b&gt;.&lt;/p&gt;</description><pubDate>Mon, 21 Sep 2026 11:29:37 +0000</pubDate></item>
<item><title>Campeonato de futebol</title><link>https://exemplo.com/b</link><pubDate>Mon, 21 Sep 2026 12:00:00 +0000</pubDate></item>
</channel></rss>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns="http://purl.org/rss/1.0/">
<item rdf:about="https://exemplo.com/c"><title>Ibama publica norma</title><link>https://exemplo.com/c</link>
<dc:date>2026-09-30T17:08:02Z</dc:date></item></rdf:RDF>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Decisao do STJ</title>
<link href="https://exemplo.com/d"/><updated>2026-09-30T10:00:00-03:00</updated><summary>ICMS</summary></entry></feed>"""


class Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ana", password="Senha@12345", is_staff=True, first_name="Ana")
        self.client.force_login(self.user)
        self.contato = Contato.objects.create(nome="Maria Souza", email="maria@exemplo.com", whatsapp="(65) 99999-8888",
                                              area_interesse="TRIB_FED", responsavel=self.user, aceita_conteudo=True)
        self.op = Oportunidade.objects.create(contato=self.contato, titulo="Transação PGFN", area="TRIB_FED",
                                              responsavel=self.user)

    def reuniao(self, horas=5, **kw):
        return Reuniao.objects.create(oportunidade=self.op, advogado=self.user,
                                      inicio=timezone.now() + timedelta(hours=horas), **kw)


class ContatoTest(Base):
    def test_cadastro_cria_atendimento_no_funil(self):
        r = self.client.post(reverse("crm:contato_novo"), {
            "nome": "João Lima", "tipo": "PF", "email": "joao@exemplo.com", "origem": "INDICACAO",
            "area_interesse": "AMBIENTAL", "responsavel": self.user.pk, "assunto": "Auto de infração Ibama"})
        op = Oportunidade.objects.get(contato__nome="João Lima")
        self.assertRedirects(r, op.get_absolute_url())
        self.assertEqual((op.etapa, op.area, op.titulo), ("NOVO", "AMBIENTAL", "Auto de infração Ibama"))

    def test_exige_meio_de_contato(self):
        r = self.client.post(reverse("crm:contato_novo"), {"nome": "Sem contato", "tipo": "PF", "origem": "SITE",
                                                           "area_interesse": "TRIB_EST"})
        self.assertContains(r, "ao menos um meio de contato")

    def test_consentimento_registra_data(self):
        self.assertIsNotNone(self.contato.consentimento_em)
        self.contato.aceita_conteudo = False
        self.contato.save()
        self.assertIsNone(self.contato.consentimento_em)


class FunilTest(Base):
    def test_agendar_reuniao_avanca_etapa(self):
        inicio = (timezone.localtime() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("crm:reuniao_nova", args=[self.op.pk]), {
            "advogado": self.user.pk, "inicio": inicio, "duracao_min": 60, "modalidade": "VIDEO", "local": "https://meet/x"})
        self.op.refresh_from_db()
        self.assertEqual(self.op.etapa, "REUNIAO")
        self.assertEqual(self.op.reunioes.count(), 1)

    def test_proposta_contrato_assinatura(self):
        hoje = timezone.localdate()
        self.op.aberto_em = hoje - timedelta(days=20)
        self.op.save()
        url = lambda acao: reverse("crm:oportunidade_acao", args=[self.op.pk, acao])  # noqa: E731
        self.client.post(url("proposta"), {"proposta_enviada_em": hoje.isoformat(), "valor_estimado": "15.000,00"})
        self.op.refresh_from_db()
        self.assertEqual((self.op.etapa, str(self.op.valor_estimado)), ("PROPOSTA", "15000.00"))
        self.client.post(url("contrato"), {"contrato_link": "https://assinatura.exemplo.com/doc/1"})
        self.client.post(url("assinado"), {"contrato_assinado_em": hoje.isoformat()})
        self.op.refresh_from_db()
        self.assertEqual((self.op.etapa, self.op.fechado_em, self.op.dias_maturacao), ("FECHADO", hoje, 20))
        self.assertEqual(self.op.contrato_enviado_em, hoje)

    def test_perda_exige_motivo_e_reabre(self):
        url = reverse("crm:oportunidade_acao", args=[self.op.pk, "perdido"])
        self.client.post(url, {"motivo_perda": ""})
        self.op.refresh_from_db()
        self.assertEqual(self.op.etapa, "NOVO")
        self.client.post(url, {"motivo_perda": "PRECO", "detalhe_perda": "achou caro"})
        self.op.refresh_from_db()
        self.assertEqual((self.op.etapa, self.op.motivo_perda), ("PERDIDO", "PRECO"))
        self.client.post(reverse("crm:oportunidade_acao", args=[self.op.pk, "reabrir"]))
        self.op.refresh_from_db()
        self.assertEqual((self.op.etapa, self.op.motivo_perda), ("NOVO", ""))


class FollowupTest(Base):
    def proposta(self, dias):
        self.op.etapa, self.op.proposta_enviada_em = "PROPOSTA", timezone.localdate() - timedelta(days=dias)
        self.op.save()

    def test_alerta_depois_de_3_dias(self):
        self.proposta(3)
        self.assertEqual(services.pendentes_followup(), [])
        self.proposta(4)
        self.assertEqual(services.pendentes_followup(), [self.op])
        self.assertContains(self.client.get(reverse("crm:painel")), "4 dias")

    def test_contato_registrado_zera_o_alerta(self):
        self.proposta(10)
        self.client.post(reverse("crm:interacao_nova", args=[self.op.pk]), {"tipo": "LIGACAO", "descricao": "Vai avaliar."})
        self.assertEqual(services.pendentes_followup(), [])

    def test_anotacao_interna_nao_zera(self):
        self.proposta(10)
        Interacao.objects.create(oportunidade=self.op, tipo="NOTA", descricao="lembrar de ligar")
        self.assertEqual(len(services.pendentes_followup()), 1)


@override_settings(WHATSAPP_TOKEN="", WHATSAPP_PHONE_NUMBER_ID="", ESCRITORIO_NOME="Escritório Teste")
class LembreteTest(Base):
    def test_lembrete_por_email_uma_unica_vez(self):
        r = self.reuniao(horas=5)
        self.reuniao(horas=72)  # fora da janela de 24 horas
        self.assertEqual(len(services.enviar_lembretes()), 1)
        self.assertEqual(len(services.enviar_lembretes()), 0)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["maria@exemplo.com"])
        self.assertIn("Olá, Maria!", m.body)
        self.assertEqual(m.attachments[0][0], "consulta.ics")
        self.assertEqual(Mensagem.objects.get().reuniao, r)

    def test_reuniao_remarcada_recebe_novo_lembrete(self):
        r = self.reuniao(horas=5)
        services.enviar_lembretes()
        r.inicio, r.remarcada_em = timezone.now() + timedelta(hours=8), timezone.now()
        r.save()
        self.assertEqual(len(services.enviar_lembretes()), 1)

    def test_cancelada_nao_lembra(self):
        self.reuniao(horas=5, status="CANCELADA")
        self.assertEqual(services.enviar_lembretes(), [])

    @override_settings(WHATSAPP_TOKEN="t", WHATSAPP_PHONE_NUMBER_ID="1", WHATSAPP_TEMPLATE_LEMBRETE="lembrete_consulta")
    def test_whatsapp_usa_template(self):
        self.reuniao(horas=5)
        with mock.patch("crm.services.requests.post") as post:
            post.return_value.text = "{}"
            msgs = services.enviar_lembretes()
        self.assertEqual({m.canal for m in msgs}, {"EMAIL", "WHATSAPP"})
        corpo = post.call_args.kwargs["json"]
        self.assertEqual((corpo["to"], corpo["template"]["name"]), ("5565999998888", "lembrete_consulta"))
        self.assertEqual(len(corpo["template"]["components"][0]["parameters"]), 4)

    def test_falha_de_envio_fica_registrada(self):
        self.reuniao(horas=5)
        with mock.patch("crm.services.EmailMessage.send", side_effect=OSError("smtp fora")):
            (m,) = services.enviar_lembretes()
        self.assertEqual((m.status, m.resposta), ("ERRO", "smtp fora"))


@override_settings(ESCRITORIO_NOME="Escritório Teste")
class NutricaoTest(Base):
    def conteudo(self, **kw):
        dados = dict(titulo="Nova portaria de transação", texto="A PGFN publicou portaria sobre transação.",
                     area="TRIB_FED", status="APROVADO")
        dados.update(kw)
        return Conteudo.objects.create(**dados)

    def test_filtro_oab(self):
        self.assertEqual(services.verificar_oab("O seguro garantia e o desconto na transação tributária."), [])
        for ruim in ["Garantimos a redução da dívida", "Consulta gratuita hoje", "Contrate já",
                     "Somos o melhor escritório", "Honorários a partir de mil reais", "Resultado garantido"]:
            self.assertTrue(services.verificar_oab(ruim), ruim)
        form = ConteudoForm({"titulo": "Dívida", "texto": "Ligue agora e tenha êxito garantido.",
                             "enviar_a_partir": timezone.localdate().isoformat()})
        self.assertFalse(form.is_valid())

    def test_envia_so_para_quem_autorizou_e_da_area(self):
        Contato.objects.create(nome="Sem Opt-in", email="a@exemplo.com", area_interesse="TRIB_FED")
        Contato.objects.create(nome="Outra Area", email="b@exemplo.com", area_interesse="AMBIENTAL", aceita_conteudo=True)
        c = self.conteudo()
        self.assertEqual(len(services.disparar_conteudos_pendentes()), 1)
        self.assertEqual(mail.outbox[0].to, ["maria@exemplo.com"])
        self.assertIn("Para deixar de receber: ", mail.outbox[0].body)
        c.refresh_from_db()
        self.assertEqual(c.status, "ENVIADO")
        self.assertEqual(services.disparar_conteudos_pendentes(), [])

    def test_rascunho_e_data_futura_nao_saem(self):
        self.conteudo(status="RASCUNHO")
        self.conteudo(enviar_a_partir=timezone.localdate() + timedelta(days=3))
        self.assertEqual(services.disparar_conteudos_pendentes(), [])

    def test_aprovacao_so_por_staff(self):
        c = self.conteudo(status="RASCUNHO")
        comum = get_user_model().objects.create_user("estagio", password="Senha@12345")
        self.client.force_login(comum)
        self.client.post(reverse("crm:conteudo_acao", args=[c.pk, "aprovar"]))
        c.refresh_from_db()
        self.assertEqual(c.status, "RASCUNHO")
        self.client.force_login(self.user)
        self.client.post(reverse("crm:conteudo_acao", args=[c.pk, "aprovar"]))
        c.refresh_from_db()
        self.assertEqual((c.status, c.aprovado_por), ("APROVADO", self.user))

    def test_descadastro_pelo_link(self):
        self.client.logout()
        url = services.link_descadastro(self.contato).replace("http://localhost:8000", "")
        self.assertContains(self.client.get(url), "maria@exemplo.com")
        self.client.post(url)
        self.contato.refresh_from_db()
        self.assertFalse(self.contato.aceita_conteudo)
        self.assertEqual(self.client.get(url[:-3] + "xx/").status_code, 404)


class IndicadoresTest(Base):
    def test_conversao_maturacao_e_motivos(self):
        hoje = timezone.localdate()

        def op(area, etapa, dias=None, motivo=""):
            return Oportunidade.objects.create(
                contato=self.contato, titulo="x", area=area, etapa=etapa, motivo_perda=motivo,
                aberto_em=hoje - timedelta(days=dias or 0), fechado_em=hoje if etapa == "FECHADO" else None)

        self.op.delete()
        op("TRIB_FED", "FECHADO", 10)
        op("TRIB_FED", "FECHADO", 30)
        op("TRIB_FED", "PERDIDO", motivo="PRECO")
        op("TRIB_FED", "PROPOSTA")
        op("AMBIENTAL", "PERDIDO", motivo="PRECO")
        op("AMBIENTAL", "PERDIDO", motivo="DEMORA")
        ind = services.indicadores(Oportunidade.objects.all())
        fed = ind["por_area"][0]
        self.assertEqual((fed["total"], fed["conversao"], fed["conversao_decididos"]), (4, 50.0, 66.7))
        self.assertEqual((fed["maturacao_media"], fed["maturacao_mediana"]), (20.0, 20.0))
        self.assertEqual(ind["geral"]["conversao"], 33.3)
        self.assertEqual([(m["nome"], m["n"]) for m in ind["motivos"]], [("Preço alto", 2), ("Demora no atendimento", 1)])
        self.assertIsNone(ind["por_area"][1]["conversao"])
        self.assertContains(self.client.get(reverse("crm:relatorio")), "Preço alto")


class FeedsTest(Base):
    def test_le_rss_rdf_e_atom(self):
        itens = feeds.ler_feed(RSS)
        self.assertEqual(itens[0]["titulo"], "PGFN abre novo edital de transação")
        self.assertEqual(itens[0]["resumo"], "Edital da PGFN.")
        self.assertEqual(itens[0]["publicado_em"].year, 2026)
        self.assertEqual(feeds.ler_feed(RDF)[0]["link"], "https://exemplo.com/c")
        self.assertEqual(feeds.ler_feed(ATOM)[0]["link"], "https://exemplo.com/d")

    def test_palavras_chave_e_sem_duplicar(self):
        fonte = Fonte.objects.create(nome="Teste", url="https://exemplo.com/feed", area="TRIB_FED", palavras_chave="PGFN, CARF")
        with mock.patch("crm.feeds.requests.get") as get:
            get.return_value.content = RSS
            self.assertEqual(feeds.atualizar_fonte(fonte), 1)
            self.assertEqual(feeds.atualizar_fonte(fonte), 0)
        a = Atualizacao.objects.get()
        self.assertEqual((a.area, a.lida), ("TRIB_FED", False))
        self.client.post(reverse("crm:atualizacao_lida", args=[a.pk]))
        a.refresh_from_db()
        self.assertTrue(a.lida)

    def test_excluir_todas_nao_volta_na_proxima_busca(self):
        fed = Fonte.objects.create(nome="Fed", url="https://exemplo.com/feed", area="TRIB_FED")
        amb = Fonte.objects.create(nome="Amb", url="https://exemplo.com/rdf", area="AMBIENTAL")
        with mock.patch("crm.feeds.requests.get") as get:
            get.return_value.content = RSS
            feeds.atualizar_fonte(fed)
            get.return_value.content = RDF
            feeds.atualizar_fonte(amb)
            self.client.post(reverse("crm:atualizacoes_excluir"), {"area": "AMBIENTAL"})
            self.assertEqual(set(Atualizacao.objects.values_list("area", flat=True)), {"TRIB_FED"})
            self.client.post(reverse("crm:atualizacoes_excluir"))
            self.assertFalse(Atualizacao.objects.exists())
            fed.refresh_from_db()
            get.return_value.content = RSS
            self.assertEqual(feeds.atualizar_fonte(fed), 0)
        self.assertEqual(self.client.get(reverse("crm:atualizacoes_excluir")).status_code, 405)

    def test_excluir_uma_some_da_tela_e_nao_volta(self):
        fonte = Fonte.objects.create(nome="Teste", url="https://exemplo.com/feed", area="TRIB_FED")
        with mock.patch("crm.feeds.requests.get") as get:
            get.return_value.content = RSS
            feeds.atualizar_fonte(fonte)
            a = Atualizacao.objects.get(titulo__startswith="PGFN")
            self.client.post(reverse("crm:atualizacao_excluir", args=[a.pk]))
            self.assertEqual(feeds.atualizar_fonte(fonte), 0)
        r = self.client.get(reverse("crm:atualizacoes"))
        self.assertNotContains(r, "PGFN abre novo edital")
        self.assertContains(r, "Campeonato de futebol")
        self.assertNotContains(self.client.get(reverse("crm:painel")), "PGFN abre novo edital")
        self.assertEqual(self.client.post(reverse("crm:atualizacao_excluir", args=[a.pk])).status_code, 404)

    def test_fonte_fora_do_ar_registra_erro(self):
        fonte = Fonte.objects.create(nome="Teste", url="https://exemplo.com/feed", area="AMBIENTAL")
        with mock.patch("crm.feeds.requests.get", side_effect=OSError("timeout")):
            self.assertEqual(feeds.atualizar_fonte(fonte), 0)
        fonte.refresh_from_db()
        self.assertEqual(fonte.ultimo_erro, "timeout")


class TelasTest(Base):
    def test_telas_abrem(self):
        self.reuniao(horas=5)
        Conteudo.objects.create(titulo="t", texto="x")
        for nome, args in [("painel", []), ("funil", []), ("contato_lista", []), ("contato_novo", []),
                           ("contato_detalhe", [self.contato.pk]), ("contato_editar", [self.contato.pk]),
                           ("oportunidade_detalhe", [self.op.pk]), ("oportunidade_editar", [self.op.pk]),
                           ("oportunidade_nova", [self.contato.pk]), ("reuniao_nova", [self.op.pk]),
                           ("conteudo_lista", []), ("conteudo_novo", []), ("relatorio", []), ("atualizacoes", [])]:
            with self.subTest(nome):
                self.assertEqual(self.client.get(reverse(f"crm:{nome}", args=args)).status_code, 200)

    def test_exige_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("crm:painel")).status_code, 302)


class MapasTest(Base):
    ELEMENTOS = [
        {"type": "node", "id": 1, "lat": -15.58, "lon": -56.09,
         "tags": {"amenity": "fuel", "name": "Posto Papai", "phone": "+55 65 3333-0000", "addr:street": "Av. Brasil",
                  "addr:housenumber": "10", "website": "https://posto.exemplo.com"}},
        {"type": "way", "id": 2, "center": {"lat": -15.6, "lon": -56.1}, "tags": {"amenity": "fuel", "name": "Auto Posto Sul"}},
        {"type": "node", "id": 3, "lat": -15.6, "lon": -56.1, "tags": {"amenity": "fuel", "name": "Auto Posto Sul"}},
        {"type": "node", "id": 4, "lat": -15.6, "lon": -56.1, "tags": {"amenity": "fuel"}},
    ]

    def test_consulta_escapa_o_texto_digitado(self):
        from . import mapas
        q = mapas.montar_consulta('Cuiabá"];out;', "mt", "postos", "posto (sul)")
        self.assertIn('"ISO3166-2"="BR-MT"', q)
        self.assertIn('"name"~"^Cuiabá\\"\\\\];out;$",i', q)
        self.assertIn('nwr["amenity"="fuel"]["name"~"posto \\\\(sul\\\\)",i](area.a);', q)

    def test_extrai_grava_e_exporta(self):
        with mock.patch("crm.mapas.requests.post") as post:
            post.return_value.json.return_value = {"elements": self.ELEMENTOS}
            r = self.client.post(reverse("crm:pesquisa_lista"), {"categoria": "postos", "municipio": "Cuiabá", "uf": "mt"})
        from .models import PesquisaMercado
        p = PesquisaMercado.objects.get()
        self.assertRedirects(r, p.get_absolute_url())
        self.assertEqual((p.total, p.uf), (2, "MT"))  # sem nome e duplicada ficam de fora
        e = p.empresas.get(nome="Posto Papai")
        self.assertEqual((e.tipo, e.endereco, e.telefone), ("Posto de combustível", "Av. Brasil 10", "+55 65 3333-0000"))
        csv_ = self.client.get(p.get_absolute_url() + "?formato=csv").content.decode("utf-8-sig")
        self.assertIn("Posto Papai;Posto de combustível;Av. Brasil 10;Cuiabá;MT;+55 65 3333-0000", csv_)
        self.assertEqual(Contato.objects.count(), 1)  # nada entra no funil

    def test_exige_segmento_ou_nome_e_trata_falha(self):
        r = self.client.post(reverse("crm:pesquisa_lista"), {"categoria": "", "termo": "ab", "municipio": "Cuiabá", "uf": "MT"})
        self.assertContains(r, "Escolha um segmento")
        with mock.patch("crm.mapas.requests.post", side_effect=OSError("timeout")):
            r = self.client.post(reverse("crm:pesquisa_lista"), {"categoria": "postos", "municipio": "Cuiabá", "uf": "MT"})
        self.assertContains(r, "não respondeu agora")
        from .models import PesquisaMercado
        self.assertFalse(PesquisaMercado.objects.exists())
