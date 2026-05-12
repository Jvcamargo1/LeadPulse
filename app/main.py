import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Form, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.routes import oportunidades, mensagens, canais, tarefas, auth
from app.api.webhooks import whatsapp as webhook_whatsapp
from app.core.config import get_settings
from app.core.dependencies import get_db, get_current_tenant_id
from app.core.database import init_db
from app.core.cache import get_cache, kanban_cache_key, invalidar_kanban
from app.models import Oportunidade, Lead
from app.workers.imap_worker import imap_polling_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    
    settings = get_settings()
    imap_task = None
    
    if not settings.DISABLE_BACKGROUND_WORKERS:
        imap_task = asyncio.create_task(imap_polling_loop())
        logger.info("Worker IMAP agendado.")
    else:
        logger.warning("Workers em background DESABILITADOS via env.")
    
    yield
    
    if imap_task:
        imap_task.cancel()
        try:
            await imap_task
        except asyncio.CancelledError:
            pass
    
    await get_cache().close()


app = FastAPI(
    title="LeadPulse",
    description="SaaS CRM com IA para PMEs",
    version="0.3.0",
    lifespan=lifespan,
)

# Rotas de API REST
app.include_router(oportunidades.router, prefix="/api")
app.include_router(mensagens.router, prefix="/api")
app.include_router(tarefas.router)
app.include_router(auth.router, prefix="/api")

# Rotas de UI (HTMX)
app.include_router(canais.router)

# Webhooks externos
app.include_router(webhook_whatsapp.router)

templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        if request.url.path.startswith("/api") or request.url.path.startswith("/webhooks"):
            return JSONResponse({"detail": exc.detail}, status_code=401)
        return RedirectResponse(url="/login")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/login")
async def login_view(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/")
async def kanban_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Kanban com cache-aside no Redis."""
    settings = get_settings()
    cache = get_cache()
    cache_key = kanban_cache_key(tenant_id)
    
    estagios_padrao = [
        "Prospecção",
        "Qualificação",
        "Proposta",
        "Negociação",
        "Fechado Ganho",
        "Fechado Perdido",
    ]
    
    # Tenta cache primeiro
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return templates.TemplateResponse(
            "kanban.html",
            {
                "request": request,
                "estagios": cached,
                "tenant_id": str(tenant_id),
                "from_cache": True,
            },
        )
    
    # Cache miss — busca no banco
    stmt = (
        select(Oportunidade)
        .where(Oportunidade.tenant_id == tenant_id)
        .options(joinedload(Oportunidade.lead))
    )
    result = await db.execute(stmt)
    oportunidades_db = result.scalars().all()
    
    # Serializa para algo que cabe no JSON do Redis
    estagios_dict = {estagio: [] for estagio in estagios_padrao}
    for op in oportunidades_db:
        item = {
            "id": str(op.id),
            "valor": op.valor,
            "estagio_funil": op.estagio_funil,
            "temperatura_ia": op.temperatura_ia,
            "status_conversa_ia": op.status_conversa_ia,
            "lead_nome": op.lead.nome if op.lead else "Desconhecido",
        }
        estagios_dict.setdefault(op.estagio_funil, []).append(item)
    
    await cache.set_json(cache_key, estagios_dict, ttl=settings.CACHE_TTL_KANBAN_SECONDS)
    
    return templates.TemplateResponse(
        "kanban.html",
        {
            "request": request,
            "estagios": estagios_dict,
            "tenant_id": str(tenant_id),
            "from_cache": False,
        },
    )


@app.get("/ui/oportunidades/modal-nova")
async def ui_modal_nova_oportunidade(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    stmt = select(Lead).where(Lead.tenant_id == tenant_id)
    result = await db.execute(stmt)
    leads = result.scalars().all()
    return templates.TemplateResponse(
        "modal_nova_oportunidade.html", {"request": request, "leads": leads}
    )


@app.post("/ui/oportunidades")
async def ui_criar_oportunidade(
    lead_id: uuid.UUID = Form(...),
    valor: float = Form(0.0),
    estagio_funil: str = Form("Prospecção"),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    nova_op = Oportunidade(
        tenant_id=tenant_id, lead_id=lead_id, valor=valor, estagio_funil=estagio_funil
    )
    db.add(nova_op)
    await db.commit()
    
    # Invalida cache do Kanban deste tenant
    await invalidar_kanban(tenant_id)
    
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@app.put("/ui/oportunidades/{oportunidade_id}/estagio")
async def ui_atualizar_estagio_oportunidade(
    oportunidade_id: uuid.UUID,
    estagio_funil: str = Form(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    stmt = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    op = result.scalars().first()
    if op:
        op.estagio_funil = estagio_funil
        await db.commit()
        await invalidar_kanban(tenant_id)
    return Response(status_code=204)
