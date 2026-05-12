import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Form, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.routes import oportunidades, mensagens
from app.core.dependencies import get_db, get_current_tenant_id
from app.core.database import init_db
from app.models import Oportunidade, Lead

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

@app.get("/ui/oportunidades/modal-nova")
async def ui_modal_nova_oportunidade(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    """Retorna apenas o fragmento HTML do Modal de Nova Oportunidade."""
    # Busca os leads do tenant para preencher o campo <select>
    stmt = select(Lead).where(Lead.tenant_id == tenant_id)
    result = await db.execute(stmt)
    leads = result.scalars().all()
    
    return templates.TemplateResponse(
        "partials/modal_nova_oportunidade.html", 
        {"request": request, "leads": leads}
    )

@app.post("/ui/oportunidades")
async def ui_criar_oportunidade(
    lead_id: uuid.UUID = Form(...),
    valor: float = Form(0.0),
    estagio_funil: str = Form("Prospecção"),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    """Recebe os dados do formulário via HTMX, salva no banco e comanda o refresh da tela."""
    nova_op = Oportunidade(
        tenant_id=tenant_id,
        lead_id=lead_id,
        valor=valor,
        estagio_funil=estagio_funil
    )
    db.add(nova_op)
    await db.commit()
    
    # Retorna o status 204 (Sucesso sem conteúdo) e o Header do HTMX para atualizar a página
    return Response(status_code=204, headers={"HX-Refresh": "true"})

@app.put("/ui/oportunidades/{oportunidade_id}/estagio")
async def ui_atualizar_estagio_oportunidade(
    oportunidade_id: uuid.UUID,
    estagio_funil: str = Form(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    """Atualiza o estágio da Oportunidade após um Drag and Drop."""
    stmt = select(Oportunidade).where(Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id)
    result = await db.execute(stmt)
    op = result.scalars().first()
    if op:
        op.estagio_funil = estagio_funil
        await db.commit()
    
    # Retornamos 204 OK sem recarregar a página, pois o JS já reposicionou o Card
    return Response(status_code=204)
