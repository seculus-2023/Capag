# Sistema CAPAG – Capacidade de Pagamento (PGFN)

Sistema web em **Django + PostgreSQL** para cadastrar empresas, calcular a CAPAG real,
comparar com a CAPAG presumida pela PGFN, guardar o histórico e enviar o relatório em PDF
por **e-mail** ou **WhatsApp**.

## Funcionalidades
- Login com usuário e senha (Django auth), troca de senha e área administrativa
- Cadastro de empresas com validação de CNPJ e busca automática dos dados na Receita (publica.cnpj.ws)
- Análises de CAPAG por empresa, com histórico:
  - dívida ativa (principal, multa, juros, encargos)
  - CAPAG presumida pela PGFN e rating informado
  - receita, custos, parcelas de financiamento, outras dívidas, bens, bens onerados e caixa
  - cálculo automático da CAPAG real, do rating (A/B/C/D), do desconto estimado, do prazo e da parcela
  - prazo de 30 dias para o pedido de revisão, contado da data da ciência
- Relatório em PDF (quadro comparativo e memória de cálculo)
- Envio por e-mail (SMTP, com o PDF anexado)
- Envio por WhatsApp:
  - **com WhatsApp Cloud API (Meta)** configurada: o PDF vai como documento;
  - **sem API**: abre o WhatsApp (wa.me) com a mensagem pronta e um link seguro para o PDF, que expira
- Histórico de envios (canal, destino, status, usuário)
- Parâmetros do cálculo editáveis na tela (somente usuários staff)

## CRM jurídico (menu CRM)
Áreas atendidas: **Direito Tributário Federal**, **Direito Tributário Estadual** e **Direito Ambiental**.

- **Contatos**: cadastro com origem, área de interesse, advogado responsável e autorização para receber conteúdos.
  Todo contato novo entra no funil na etapa *Novo contato*.
- **Funil**: Novo contato → Consulta agendada → Proposta enviada → Contrato assinado (ou Perdido, com o motivo).
- **Agendamento**: consulta inicial com o advogado especialista (presencial, vídeo ou telefone).
- **Lembretes automáticos da consulta**: e-mail (Gmail/SMTP, com convite `.ics`) e WhatsApp, 24 horas antes.
  O WhatsApp automático exige a Cloud API; sem ela, o painel traz o botão *Lembrar no WhatsApp* (wa.me).
- **Fechamento**: registre o link do contrato gerado na plataforma de assinatura digital (gov.br, ZapSign,
  Clicksign, D4Sign...), envie ao cliente pelo sistema e marque a data da assinatura. O sistema não assina
  documentos: ele acompanha o contrato até a assinatura.
- **Alertas de follow-up**: proposta com o cliente há mais de 3 dias sem novo contato aparece em vermelho no
  *Painel do advogado*. O alerta some quando o advogado registra a ligação no histórico.
- **Nutrição de leads**: conteúdos informativos por e-mail, só para quem autorizou, com link de descadastro.
- **Inteligência comercial**: taxa de conversão, tempo de maturação por área e motivos de perda, com filtro
  por período e por advogado.
- **Atualizações jurídicas**: notícias e decisões de tributário federal (PGFN, Receita, CARF), tributário
  estadual (PGE, Sefaz, ICMS) e ambiental, lidas de feeds RSS. As fontes ficam em *Administração → Fontes de
  atualização*. PGFN e PGEs não publicam feed próprio; são acompanhadas pelas notícias que as citam.

- **Pesquisa de mercado (mapa)**: extrai do OpenStreetMap (gratuito, sem chave) as empresas de um município
  por segmento ou nome, com endereço, telefone, e-mail e site quando existirem, e exporta em CSV. É uma lista
  de estudo: as empresas não entram no funil nem recebem mensagens. A base é colaborativa e menos completa
  que a do Google Maps.

### Rotina automática
Lembretes, envio dos conteúdos aprovados e busca das atualizações rodam com um comando. Agende-o de hora em hora:
```
python manage.py crm_automacoes
```
Windows (Agendador de Tarefas): programa `C:\PROJETOS_PYTHON\Capag\.venv\Scripts\python.exe`,
argumentos `manage.py crm_automacoes`, iniciar em `C:\PROJETOS_PYTHON\Capag`. Linux: `cron`.

### Regras da OAB e LGPD
O CRM segue o Provimento 205/2021 do Conselho Federal da OAB (publicidade informativa, sem captação de clientela):
- conteúdos só são enviados a contatos que **autorizaram** o recebimento (a data do consentimento fica gravada);
- todo e-mail identifica o escritório e traz o link para deixar de receber;
- um filtro bloqueia promessa de resultado, divulgação de honorários, gratuidade, desconto, autopromoção e
  chamada para contratação. O filtro é um apoio: **o envio depende da aprovação de um advogado** (usuário staff);
- o sistema não faz disparo para listas compradas nem contato ativo com quem não procurou o escritório.

Configure no `.env`: `ESCRITORIO_NOME`, `ESCRITORIO_OAB`, `CRM_FOLLOWUP_DIAS`, `CRM_LEMBRETE_HORAS` e, para o
lembrete por WhatsApp fora da janela de 24 horas, `WHATSAPP_TEMPLATE_LEMBRETE` (template aprovado na Meta com
4 variáveis no corpo: nome, data, hora e local).

## Processos, prazos, financeiro e documentos (menu Jurídico)
- **Processos**: judiciais e administrativos (PGFN, Sefaz, CARF, Ibama...), ligados ao cliente (contato do CRM),
  com vara/órgão, parte contrária, fase, valor da causa, responsável e andamentos.
- **Prazos**: lançados à mão em cada processo (prazo, audiência ou diligência). A *Agenda de prazos* separa
  vencidos, de hoje, dos próximos 7 dias e posteriores. O responsável recebe e-mail 3 dias antes
  (`PRAZO_AVISO_DIAS`) e de novo no dia; os avisos saem pela rotina `crm_automacoes`.
  **O sistema não lê intimações nem publicações dos tribunais.**
- **Financeiro**: honorários a receber (contratuais, êxito, mensalidade, sucumbência) e despesas do caso,
  com parcelamento mensal, baixa, forma de pagamento, atraso e exportação em CSV.
- **Pasta do cliente**: processos, documentos e honorários do cliente numa tela. Os documentos (PDF, Word,
  Excel, imagem, ZIP, até 25 MB) ficam em `media/clientes/` e só são baixados por usuário logado com permissão.
  **Inclua a pasta `media/` no backup**, junto com o banco de dados.

## Permissões por perfil
Em *Usuários e perfis* (menu do usuário, só para sócios) cria-se o usuário e escolhe-se o perfil:

| Área | Sócio | Advogado | Estagiário | Secretaria | Financeiro |
|---|---|---|---|---|---|
| CRM (contatos, funil, consultas) | sim | sim | sim | sim | sim |
| CAPAG (empresas e análises) | sim | sim | sim | – | – |
| Consultar processos e prazos, lançar andamentos | sim | sim | sim | sim | – |
| Cadastrar e alterar processos e prazos | sim | sim | – | – | – |
| Documentos dos clientes | sim | sim | sim | sim | sim |
| Honorários e despesas | sim | – | – | – | sim |
| Inteligência comercial | sim | – | – | – | – |
| Excluir registros | sim | – | – | – | – |
| Usuários, parâmetros, aprovar conteúdos | sim | – | – | – | – |

Usuário *staff* ou superusuário é sempre Sócio; usuário comum sem perfil definido é tratado como Advogado.
A matriz fica em `core/perfis.py` (dicionário `PERFIS`).

## Regra de cálculo
```
resultado anual livre = receita bruta − custos/despesas − parcelas de financiamento − outras dívidas
geração futura        = max(0, resultado anual livre) × 5 anos
patrimônio livre      = (bens − bens onerados) × % de realização
CAPAG real            = geração futura + patrimônio livre + caixa

Rating (CAPAG ÷ dívida total): A ≥ 2×  |  B ≥ 1×  |  C ≥ 0,5×  |  D < 0,5×  (ou irrecuperável, art. 25)
Desconto (só C e D): até 65% (70% ME/EPP) da dívida e nunca sobre o principal
Prazo: 120 meses (145 ME/EPP)
```
O horizonte de 5 anos está no art. 21 da Portaria PGFN/ME 6.757/2022.
**Os fatores do rating e os limites são parâmetros de simulação.** Confira a metodologia e a
legislação vigentes e ajuste-os na tela *Parâmetros*.

## Instalação
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # edite banco, e-mail e WhatsApp
# banco: crie o database "capag" no seu PostgreSQL
#        (ou suba um com: docker compose up -d)

python manage.py migrate
python manage.py createsuperuser   # ou: python manage.py dados_exemplo  (cria admin/admin123 + exemplo)
python manage.py runserver
```
Acesse http://localhost:8000.

Testes: `python manage.py test core crm juridico`

## E-mail
Gmail: ative a verificação em duas etapas e gere uma **senha de app**. Use-a em `EMAIL_HOST_PASSWORD`.
Para testar sem SMTP: `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`.

## WhatsApp Cloud API (opcional)
1. Crie um app em developers.facebook.com com o produto **WhatsApp**.
2. Copie o **token de acesso** (use um token permanente de usuário de sistema) e o **Phone number ID**.
3. Preencha `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_NUMBER_ID` no `.env`.

Observação da Meta: mensagem livre com documento só é entregue se o cliente tiver falado com o seu
número nas últimas 24 horas. Fora dessa janela é preciso um *template* aprovado.
Sem a API, o sistema usa o link wa.me, que funciona sem configuração.

`SITE_URL` precisa ser o endereço público do sistema, para o link do PDF abrir no celular do cliente.

## Produção
- `DEBUG=False`, `SECRET_KEY` forte, `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` preenchidos
- `python manage.py collectstatic`
- `gunicorn config.wsgi:application` atrás de Nginx com HTTPS
- O Bootstrap está incluído em `core/static/vendor`, então o sistema funciona sem internet (intranet).

## Estrutura
```
config/            settings (lê o .env), urls
core/models.py     Parametro, Empresa, AnaliseCapag, EnvioCapag
core/services.py   motor de cálculo da CAPAG e texto do resumo
core/pdf.py        relatório PDF (ReportLab)
core/envio.py      e-mail, WhatsApp Cloud API, wa.me e link público assinado
core/views.py      telas
crm/models.py      Contato, Oportunidade, Interacao, Reuniao, Conteudo, Mensagem, Fonte, Atualizacao
crm/services.py    lembretes, follow-up, nutrição, filtro da OAB e indicadores comerciais
crm/feeds.py       leitura dos feeds de atualizações jurídicas
crm/mapas.py       extrator de empresas do OpenStreetMap (pesquisa de mercado)
juridico/          processos, andamentos, prazos, lançamentos financeiros e documentos
core/perfis.py     permissões por perfil (Sócio, Advogado, Estagiário, Secretaria, Financeiro)
templates/         HTML (Bootstrap 5)
```

## Aplicativo (PWA)
Todas as telas podem ser instaladas como aplicativo no celular ou no computador (Chrome/Edge: *Instalar
aplicativo*; iPhone: *Compartilhar → Adicionar à Tela de Início*). A instalação só é oferecida quando o
sistema é acessado por **HTTPS** (ou por `localhost`). As telas não ficam guardadas no aparelho: sem
internet, o aplicativo mostra o aviso "Sem conexão".
