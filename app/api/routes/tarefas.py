"""
Rota que pega um rascunho gerado pela IA (Tarefa_FollowUp) e:
  1. Identifica o canal correto (WhatsApp ou Email) baseado nas mensagens da oportunidade
  2. Envia a mensagem
  3. Registra como Mensagem(remetente=VENDEDOR)
  4. Marca a tarefa como CONCLUIDA
"""
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.dependencies import get_db, get_current_tenant_id
from app.models import (
    Tarefa_FollowUp,
    Mensagem,
    Oportunidade,
    Lead,
    CanalComunicacao,
    TipoCanal,
    TipoMensagem,
    RemetenteRole,
)
from app.services.zapi_service import enviar_mensagem_texto as enviar_whatsapp
from app.services.gmail_service import enviar_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tarefas", tags=["Tarefas Follow-Up"])


@router.post("/{tarefa_id}/aprovar-enviar")
async def aprovar_e_enviar_rascunho(
    tarefa_id: uuid.UUID,
    texto_editado: str = Form(None),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """
    Aprova um rascunho da IA e envia pelo canal usado mais recentemente na oportunidade.
    
    Estratégia: olha a última mensagem do tipo WHATSAPP ou EMAIL na oportunidade
    para decidir o canal. Se não houver, retorna erro pedindo escolha manual.
    """
    # Busca tarefa + oportunidade + lead
    stmt = (
        select(Tarefa_FollowUp)
        .where(
            Tarefa_FollowUp.id == tarefa_id,
            Tarefa_FollowUp.tenant_id == tenant_id,
        )
    )
    result = await db.execute(stmt)
    tarefa = result.scalars().first()
    
    if not tarefa:
        raise HTTPException(404, "Tarefa não encontrada")
    
    if tarefa.status == "CONCLUIDA":
        raise HTTPException(400, "Tarefa já foi concluída")
    
    texto_final = (texto_editado or tarefa.rascunho_sugerido_ia or "").strip()
    if not texto_final:
        raise HTTPException(400, "Não há texto para enviar")
    
    # Busca oportunidade + lead
    stmt_op = (
        select(Oportunidade)
        .where(
            Oportunidade.id == tarefa.oportunidade_id,
            Oportunidade.tenant_id == tenant_id,
        )
    )
    result_op = await db.execute(stmt_op)
    oportunidade = result_op.scalars().first()
    if not oportunidade:
        raise HTTPException(404, "Oportunidade não encontrada")
    
    stmt_lead = select(Lead).where(Lead.id == oportunidade.lead_id, Lead.tenant_id == tenant_id)
    result_lead = await db.execute(stmt_lead)
    lead = result_lead.scalars().first()
    if not lead:
        raise HTTPException(404, "Lead não encontrado")
    
    # Detecta canal pela última mensagem
    stmt_msg = (
        select(Mensagem)
        .where(
            Mensagem.oportunidade_id == oportunidade.id,
            Mensagem.tenant_id == tenant_id,
            Mensagem.tipo.in_([TipoMensagem.WHATSAPP, TipoMensagem.EMAIL]),
        )
        .order_by(desc(Mensagem.data_envio))
        .limit(1)
    )
    result_msg = await db.execute(stmt_msg)
    ultima_msg_canal = result_msg.scalars().first()
    
    if not ultima_msg_canal:
        raise HTTPException(
            400,
            "Esta oportunidade ainda não tem mensagens de WhatsApp ou Email. "
            "Envie uma mensagem inicial manualmente primeiro.",
        )
    
    # Busca o canal ativo correspondente
    tipo_canal = (
        TipoCanal.WHATSAPP_ZAPI if ultima_msg_canal.tipo == TipoMensagem.WHATSAPP else TipoCanal.EMAIL_GMAIL
    )
    stmt_canal = select(CanalComunicacao).where(
        CanalComunicacao.tenant_id == tenant_id,
        CanalComunicacao.tipo == tipo_canal,
        CanalComunicacao.ativo == True,
    )
    result_canal = await db.execute(stmt_canal)
    canal = result_canal.scalars().first()
    if not canal:
        raise HTTPException(400, f"Nenhum canal {tipo_canal.value} ativo configurado")
    
    # Envia pelo canal apropriado
    try:
        if tipo_canal == TipoCanal.WHATSAPP_ZAPI:
            if not lead.whatsapp_id:
                raise HTTPException(400, "Lead sem WhatsApp cadastrado")
            await enviar_whatsapp(canal, lead.whatsapp_id, texto_final)
        else:
            if not lead.email_principal:
                raise HTTPException(400, "Lead sem e-mail cadastrado")
            await enviar_email(
                canal,
                destinatario=lead.email_principal,
                assunto=f"Re: Oportunidade #{str(oportunidade.id)[:8]}",
                corpo_texto=texto_final,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Falha ao enviar mensagem da tarefa {tarefa_id}: {e}")
        raise HTTPException(502, f"Falha no envio: {str(e)}")
    
    # Registra mensagem no banco
    nova_msg = Mensagem(
        tenant_id=tenant_id,
        oportunidade_id=oportunidade.id,
        remetente=RemetenteRole.VENDEDOR,
        tipo=ultima_msg_canal.tipo,
        conteudo_texto=texto_final,
    )
    db.add(nova_msg)
    
    tarefa.status = "CONCLUIDA"
    oportunidade.ultima_interacao = datetime.now(timezone.utc)
    
    await db.commit()
    
    return {"status": "enviado", "canal": tipo_canal.value}
