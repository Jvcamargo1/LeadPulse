# LeadPulse 🚀

LeadPulse é um SaaS de CRM moderno focado em PMEs (Pequenas e Médias Empresas). Ele é integrado com Inteligência Artificial (Groq/Llama 3) para análise de interações com clientes, medição de temperatura do lead e sugestão automática de respostas via WhatsApp ou E-mail.

## 🏗️ Stack Tecnológico
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (Async)
- **Frontend:** HTMX, Jinja2, CSS puro (Padrão de Design Editorial)
- **Banco de Dados:** PostgreSQL (Armazenamento Principal)
- **Cache:** Redis (Para alta performance do Kanban)
- **IA:** Integração nativa com Groq API

---

## 🛠️ Pré-requisitos

Antes de rodar o projeto, certifique-se de ter os seguintes itens instalados no seu computador:

1. **[Python 3.10+](https://www.python.org/downloads/)**
2. **PostgreSQL** (Recomendamos rodar via Docker ou instalar localmente)
3. **Redis** (Recomendamos rodar via Docker ou usar Memurai no Windows)

> **Dica de Infraestrutura:** A maneira mais fácil de rodar o Banco de Dados e o Redis na sua máquina é utilizando o **Docker Desktop**.

---

## ⚙️ Passo a Passo de Instalação e Execução

### 1. Clonar o Repositório
Abra o seu terminal (PowerShell ou Git Bash) e clone o projeto:
```bash
git clone https://github.com/Jvcamargo1/LeadPulse.git
cd LeadPulse
```

### 2. Criar e Ativar o Ambiente Virtual
Para não misturar as dependências do projeto com o seu sistema, crie um ambiente virtual (Venv):

**No Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(No Linux/Mac, use `source venv/bin/activate`)*

> **Nota:** Se o PowerShell bloquear a execução do script no Windows, rode este comando como Administrador primeiro: `Set-ExecutionPolicy Unrestricted -Force`.

### 3. Instalar as Dependências
Com o ambiente virtual ativado (aparecerá um `(venv)` verde no terminal), instale as bibliotecas Python:
```bash
pip install -r requirements.txt
```

### 4. Configurar as Variáveis de Ambiente
Na raiz do projeto, crie um arquivo chamado **`.env`** e insira a sua chave da Groq (e as credenciais de banco, se forem diferentes do padrão):

```env
GROQ_API_KEY=gsk_sua_chave_aqui

# Opcional (As URLs abaixo já são o padrão do sistema)
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/leadpulse
# REDIS_URL=redis://localhost:6379/0
```

### 5. Preparar o Banco de Dados
Certifique-se de que o **PostgreSQL e o Redis estão ligados**. Crie um banco de dados vazio chamado `leadpulse` no seu gerenciador do Postgres (pgAdmin, DBeaver, etc).

Depois, rode o nosso script de seed. Ele criará todas as tabelas e populará o sistema com leads e conversas fictícias:
```bash
python seed.py
```

### 6. Rodar a Aplicação
Inicie o servidor Uvicorn forçando o carregamento dos módulos do ambiente virtual:
```bash
python -m uvicorn app.main:app --reload
```

O servidor iniciará na URL: **http://127.0.0.1:8000**

---

## 🔑 Acesso ao Sistema (Modo Teste)

Acesse a URL acima. Para fazer login no sistema populado pelo `seed.py`, utilize:

- **E-mail:** `joao@techcorp.com`
- **Senha:** `123456`

Pronto! Você pode visualizar as Oportunidades, arrastar os cards no Kanban e clicar nos Leads para testar as **Sugestões da IA**.