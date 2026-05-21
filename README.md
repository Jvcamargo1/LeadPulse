# LeadPulse

CRM moderno para PMEs com IA integrada (Groq/Llama 3) para análise de leads, medição de temperatura e sugestão automática de follow-ups via WhatsApp e E-mail.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (Async)
- **Frontend:** HTMX, Jinja2, CSS puro
- **Banco de Dados:** PostgreSQL
- **Cache:** Redis
- **IA:** Groq API (Llama 3.3-70b)

---

## Rodando com Docker (recomendado)

> **Pré-requisito único:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado.
> Não é necessário ter Python, PostgreSQL ou Redis instalados na sua máquina.

### 1. Clonar o repositório

```bash
git clone https://github.com/Jvcamargo1/LeadPulse.git
cd LeadPulse
```

### 2. Criar o arquivo `.env`

Copie o arquivo de exemplo:

```bash
cp .env.example .env
```

Para rodar em modo de demonstração, o `.env` já vem configurado com valores padrão. O único campo opcional é a chave da IA:

```env
GROQ_API_KEY=gsk_sua_chave_aqui   # opcional — sem ela, a IA usa respostas simuladas
```

> Obtenha uma chave gratuita em [console.groq.com/keys](https://console.groq.com/keys)

### 3. Subir os containers

```bash
docker compose up --build -d
```

Isso vai baixar as imagens (PostgreSQL, Redis) e construir a aplicação. Na primeira vez pode demorar alguns minutos.

### 4. Popular o banco com dados de demonstração

```bash
docker compose exec web python seed.py
```

Esse comando cria as tabelas, os usuários de acesso e alguns leads/oportunidades de exemplo.

### 5. Acessar

Abra no navegador: **http://localhost:8000**

---

## Usuários de acesso

| Perfil   | E-mail                | Senha  |
|----------|-----------------------|--------|
| Vendedor | `joao@techcorp.com`   | 123456 |
| Admin    | `admin@leadpulse.com` | 123456 |

O perfil **Admin** dá acesso ao painel de gerenciamento de usuários em `/admin`.

---

## Comandos úteis

```bash
# Ver logs da aplicação em tempo real
docker compose logs -f web

# Parar todos os containers
docker compose down

# Parar e apagar os dados do banco (reset completo)
docker compose down -v

# Recriar os dados de demonstração após reset
docker compose exec web python seed.py
```

---

## Funcionalidades

- **Kanban** de oportunidades com drag-and-drop e filtro por temperatura de lead
- **Dashboard** com KPIs, funil de vendas e atividade recente
- **Leads** — cadastro, edição e exportação CSV
- **Tarefas** — lista de follow-ups pendentes e concluídos gerados pela IA
- **Análise de IA** — temperatura do lead (Quente/Morno/Frio) e rascunho de resposta
- **Simulador de mensagens** — para demonstração sem credenciais reais de WhatsApp/Email
- **Painel Admin** — cadastro e remoção de usuários
- **Dark mode** e suporte a PWA (instalável no celular/desktop)
- **Busca global** de leads e oportunidades
