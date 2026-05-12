import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.routes import oportunidades, mensagens
from app.core.dependencies import get_db, get_current_tenant_id
from app.core.database import init_db
from app.models import Oportunidade

app = FastAPI(title="LeadPulse", description="SaaS CRM com IA para PMEs", version="0.1.0")
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cria as tabelas no banco de dados ao iniciar a aplicação
    await init_db()
    yield
    # Aqui iria o código de desligamento (se necessário)

app = FastAPI(title="LeadPulse", description="SaaS CRM com IA para PMEs", version="0.1.0", lifespan=lifespan)

# Inclui os endpoints da API REST
app.include_router(oportunidades.router, prefix="/api")
app.include_router(mensagens.router, prefix="/api")

# Configura o diretório de templates Jinja2
templates = Jinja2Templates(directory="app/templates")

@app.get("/")
async def kanban_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    """
    Tela inicial: Exibe o quadro Kanban de Oportunidades.
    Utiliza SSR (Server-Side Rendering) com Jinja2, separando as oportunidades por estágio do funil.
    """
    
    # Ordem padrão e esperada do funil de vendas
    estagios_padrao = [
        "Prospecção", 
        "Qualificação", 
        "Proposta", 
        "Negociação", 
        "Fechado Ganho", 
        "Fechado Perdido"
    ]
    
    # Inicializa o dicionário com as colunas vazias
    estagios_dict = {estagio: [] for estagio in estagios_padrao}
    
    # Busca todas as oportunidades do tenant, trazendo também o relacionamento com 'Lead' (N+1 safe)
    # REGRA DE ARQUITETURA: Filtro por tenant_id garantido aqui.
    stmt = select(Oportunidade).where(
        Oportunidade.tenant_id == tenant_id
    ).options(joinedload(Oportunidade.lead))
    
    # NOTA: Em um cenário real com banco de dados operando, descomentaríamos isso:
    # result = await db.execute(stmt)
    # oportunidades_db = result.scalars().all()
    # Para o MVP estrutural onde o BD não está instanciado, vamos criar uma lista vazia.
    oportunidades_db = []
    # Executa a query no banco de dados e traz os registros
    result = await db.execute(stmt)
    oportunidades_db = result.scalars().all()
    
    # Agrupa as oportunidades em suas respectivas colunas
    for op in oportunidades_db:
        estagio = op.estagio_funil
        if estagio in estagios_dict:
            estagios_dict[estagio].append(op)
        else:
            # Captura eventuais estágios customizados ou erros de digitação e cria nova coluna
            if estagio not in estagios_dict:
                estagios_dict[estagio] = []
            estagios_dict[estagio].append(op)
            
    return templates.TemplateResponse(
        "kanban.html", 
        {
            "request": request, 
            "estagios": estagios_dict,
            "tenant_id": str(tenant_id)
        }
    )
