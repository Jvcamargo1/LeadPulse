import uuid
from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import AsyncSessionLocal

from app.models import Oportunidade, Mensagem, Tarefa_FollowUp
from app.schemas.oportunidade import OportunidadeCreate, OportunidadeUpdate, OportunidadeResponse
from app.core.dependencies import get_db, get_current_tenant_id
from app.services.groq_service import analisar_interacao_lead

router = APIRouter(prefix="/oportunidades", tags=["Oportunidades"])

@router.post("/", response_model=OportunidadeResponse, status_code=status.HTTP_201_CREATED)
async def create_oportunidade(
    oportunidade_in: OportunidadeCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    nova_oportunidade = Oportunidade(
        **oportunidade_in.model_dump(),
        tenant_id=tenant_id
    )
    db.add(nova_oportunidade)
    await db.commit()
    await db.refresh(nova_oportunidade)
    return nova_oportunidade

@router.get("/", response_model=List[OportunidadeResponse])
async def list_oportunidades(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    # REGRA DE ARQUITETURA: Filtro multi-tenant obrigatório
    stmt = select(Oportunidade).where(Oportunidade.tenant_id == tenant_id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    oportunidades = result.scalars().all()
    return oportunidades

@router.get("/{oportunidade_id}", response_model=OportunidadeResponse)
async def get_oportunidade(
    oportunidade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    # REGRA DE ARQUITETURA: Filtro multi-tenant obrigatório na busca por ID
    stmt = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id,
        Oportunidade.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    oportunidade = result.scalars().first()
    
    if not oportunidade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oportunidade não encontrada")
    
    return oportunidade

@router.put("/{oportunidade_id}", response_model=OportunidadeResponse)
async def update_oportunidade(
    oportunidade_id: uuid.UUID,
    oportunidade_in: OportunidadeUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    stmt = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id,
        Oportunidade.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    oportunidade = result.scalars().first()
    
    if not oportunidade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oportunidade não encontrada")
    
    update_data = oportunidade_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(oportunidade, field, value)
        
    db.add(oportunidade)
    await db.commit()
    await db.refresh(oportunidade)
    return oportunidade

@router.delete("/{oportunidade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oportunidade(
    oportunidade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    stmt = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id,
        Oportunidade.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    oportunidade = result.scalars().first()
    
    if not oportunidade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oportunidade não encontrada")
    
    await db.delete(oportunidade)
    await db.commit()
    return None

@router.post("/{oportunidade_id}/analisar-ia", response_model=OportunidadeResponse)
async def _task_analisar_ia_background(
    oportunidade_id: uuid.UUID,
    tenant_id: uuid.UUID
):
    """
    Tarefa em background (assíncrona isolada) para chamar a Groq.
    Precisamos criar uma nova sessão de BD pois a original da rota HTTP já foi fechada.
    """
    async with AsyncSessionLocal() as db:
        stmt_op = select(Oportunidade).where(
            Oportunidade.id == oportunidade_id,
            Oportunidade.tenant_id == tenant_id
        )
        result_op = await db.execute(stmt_op)
        oportunidade = result_op.scalars().first()
        
        if not oportunidade:
            return # Silenciosamente aborta se não achar no DB em background

        stmt_msg = select(Mensagem).where(
            Mensagem.oportunidade_id == oportunidade_id,
            Mensagem.tenant_id == tenant_id
        ).order_by(Mensagem.data_envio.asc())
        result_msg = await db.execute(stmt_msg)
        mensagens = result_msg.scalars().all()
        
        if not mensagens:
            return

        historico_ia = []
        for msg in mensagens:
            role = "user" if msg.remetente.upper() == "LEAD" else "assistant"
            historico_ia.append({"role": role, "content": msg.conteudo_texto})
            msg.analisada_pela_ia = True
            db.add(msg)

        resultado_ia = await analisar_interacao_lead(historico_ia)
        
        if resultado_ia:
            oportunidade.temperatura_ia = resultado_ia.get("temperatura")
            oportunidade.status_conversa_ia = resultado_ia.get("status_conversa")
            db.add(oportunidade)
            
            rascunho = resultado_ia.get("rascunho_sugerido")
            if rascunho:
                nova_tarefa = Tarefa_FollowUp(
                    tenant_id=tenant_id,
                    oportunidade_id=oportunidade.id,
                    status="PENDENTE",
                    data_limite=datetime.now(timezone.utc),
                    rascunho_sugerido_ia=rascunho
                )
                db.add(nova_tarefa)

        await db.commit()

@router.post("/{oportunidade_id}/analisar-ia", status_code=status.HTTP_202_ACCEPTED)
async def analisar_oportunidade_com_ia(
    oportunidade_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id)
):
    """
    Aciona a IA da Groq para analisar o histórico de mensagens da Oportunidade.
    Atualiza a Temperatura, Status da Conversa e cria uma Tarefa de Follow-Up sugerida.
    Aciona a IA da Groq em BACKGROUND. Retorna 202 (Accepted) imediatamente, 
    deixando o processamento pesado para rodar depois sem travar o usuário.
    """
    # 1. Busca a oportunidade
    # Valida se a oportunidade existe antes de despachar a tarefa
    stmt_op = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id,
        Oportunidade.tenant_id == tenant_id
    )
    result_op = await db.execute(stmt_op)
    oportunidade = result_op.scalars().first()
    
    if not oportunidade:
        raise HTTPException(status_code=404, detail="Oportunidade não encontrada no tenant atual")

    # 2. Busca o histórico de mensagens
    stmt_msg = select(Mensagem).where(
        Mensagem.oportunidade_id == oportunidade_id,
        Mensagem.tenant_id == tenant_id
    ).order_by(Mensagem.data_envio.asc())
    result_msg = await db.execute(stmt_msg)
    mensagens = result_msg.scalars().all()
    # Adiciona a tarefa na fila do FastAPI
    background_tasks.add_task(_task_analisar_ia_background, oportunidade_id, tenant_id)
    
    if not mensagens:
        raise HTTPException(status_code=400, detail="Não há mensagens para serem analisadas nesta oportunidade.")

    # 3. Formata para o padrão esperado pelo Llama 3
    historico_ia = []
    for msg in mensagens:
        # Se for LEAD, é o 'user' que enviou a mensagem (quem estamos analisando).
        # Qualquer outro remetente (VENDEDOR, SISTEMA) é o 'assistant'.
        role = "user" if msg.remetente.upper() == "LEAD" else "assistant"
        historico_ia.append({"role": role, "content": msg.conteudo_texto})
        
        # Marca a mensagem como analisada
        msg.analisada_pela_ia = True
        db.add(msg)

    # 4. Chama o serviço da IA (Groq)
    resultado_ia = await analisar_interacao_lead(historico_ia)
    
    if not resultado_ia:
        raise HTTPException(status_code=500, detail="Falha ao analisar a conversa com a Inteligência Artificial.")

    # 5. Atualiza a Oportunidade
    oportunidade.temperatura_ia = resultado_ia.get("temperatura")
    oportunidade.status_conversa_ia = resultado_ia.get("status_conversa")
    db.add(oportunidade)
    
    # 6. Cria a Tarefa de Follow Up com a sugestão de rascunho
    rascunho = resultado_ia.get("rascunho_sugerido")
    if rascunho:
        nova_tarefa = Tarefa_FollowUp(
            tenant_id=tenant_id,
            oportunidade_id=oportunidade.id,
            status="PENDENTE",
            data_limite=datetime.now(timezone.utc), # Mock: Ideal seria calcular para +1 ou +2 dias
            rascunho_sugerido_ia=rascunho
        )
        db.add(nova_tarefa)

    await db.commit()
    await db.refresh(oportunidade)
    
    return oportunidade
    return {"mensagem": "Análise iniciada em background."}
