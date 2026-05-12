import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Mensagem, Oportunidade
from app.schemas.mensagem import MensagemCreate, MensagemResponse
from app.core.dependencies import get_db, get_current_tenant_id

router = APIRouter(prefix="/mensagens", tags=["Mensagens"])

@router.post("/", response_model=MensagemResponse, status_code=status.HTTP_201_CREATED)
async def create_mensagem(
    mensagem_in: MensagemCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    # REGRA DE ARQUITETURA: Verifica se a oportunidade pertence ao tenant
    stmt = select(Oportunidade).where(
        Oportunidade.id == mensagem_in.oportunidade_id,
        Oportunidade.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Oportunidade não encontrada no tenant atual")

    nova_mensagem = Mensagem(
        **mensagem_in.model_dump(),
        tenant_id=tenant_id
    )
    db.add(nova_mensagem)
    await db.commit()
    await db.refresh(nova_mensagem)
    return nova_mensagem

@router.get("/oportunidade/{oportunidade_id}", response_model=List[MensagemResponse])
async def list_mensagens_oportunidade(
    oportunidade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    # O filtro por tenant_id na mensagem já garante a segurança multi-tenant
    stmt = select(Mensagem).where(
        Mensagem.oportunidade_id == oportunidade_id,
        Mensagem.tenant_id == tenant_id
    ).order_by(Mensagem.data_envio.asc())
    
    result = await db.execute(stmt)
    return result.scalars().all()
