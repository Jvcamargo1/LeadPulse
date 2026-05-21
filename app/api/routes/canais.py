"""
Rotas de UI (HTMX) para gerenciar canais de comunicação.
Cadastro de credenciais Z-API e Gmail pelo tenant.
"""
import uuid
import logging
from fastapi import APIRouter, Depends, Form, Request, Response, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.crypto import get_cipher
from app.core.dependencies import get_db, get_current_tenant_id
from app.models import CanalComunicacao, TipoCanal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/canais", tags=["UI - Canais"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def listar_canais(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Lista os canais já cadastrados pelo tenant."""
    stmt = select(CanalComunicacao).where(CanalComunicacao.tenant_id == tenant_id)
    result = await db.execute(stmt)
    canais = result.scalars().all()
    
    return templates.TemplateResponse(
        request, "canais.html", {"canais": canais, "tenant_id": str(tenant_id)},
    )


@router.post("/whatsapp")
async def conectar_whatsapp_zapi(
    instance_id: str = Form(...),
    token: str = Form(...),
    client_token: str = Form(""),
    identificador: str = Form(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Cadastra um canal WhatsApp Z-API. Cifra as credenciais antes de salvar."""
    credenciais = {
        "instance_id": instance_id.strip(),
        "token": token.strip(),
    }
    if client_token.strip():
        credenciais["client_token"] = client_token.strip()
    
    creds_cifradas = get_cipher().encrypt(credenciais)
    
    canal = CanalComunicacao(
        tenant_id=tenant_id,
        tipo=TipoCanal.WHATSAPP_ZAPI,
        identificador=identificador.strip(),
        credenciais_cifradas=creds_cifradas,
        ativo=True,
    )
    db.add(canal)
    await db.commit()
    
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/gmail")
async def conectar_gmail(
    email: str = Form(...),
    app_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Cadastra um canal Gmail. Espera senha de aplicativo (não a senha real do Gmail)."""
    credenciais = {
        "email": email.strip().lower(),
        "app_password": app_password.strip(),
    }
    creds_cifradas = get_cipher().encrypt(credenciais)
    
    canal = CanalComunicacao(
        tenant_id=tenant_id,
        tipo=TipoCanal.EMAIL_GMAIL,
        identificador=email.strip().lower(),
        credenciais_cifradas=creds_cifradas,
        ativo=True,
    )
    db.add(canal)
    await db.commit()
    
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.delete("/{canal_id}")
async def remover_canal(
    canal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    stmt = select(CanalComunicacao).where(
        CanalComunicacao.id == canal_id,
        CanalComunicacao.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    canal = result.scalars().first()
    
    if not canal:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    
    await db.delete(canal)
    await db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})
