"""
Webhook que recebe callbacks da Z-API quando uma mensagem chega no WhatsApp.

URL no painel da Z-API:
    https://seu-dominio.com/webhooks/whatsapp/{tenant_id}?secret=XXX

A validação por query-string é simples mas suficiente para MVP. Em produção,
considere validar assinatura HMAC se a Z-API passar a oferecer.
"""
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.dependencies import get_db
from app.models import CanalComunicacao, TipoCanal, TipoMensagem
from app.services.zapi_service import parse_webhook_payload
from app.services.routing import (
    resolver_lead_por_whatsapp,
    resolver_oportunidade_ativa,
    registrar_mensagem_recebida,
)
from app.api.routes.oportunidades import _task_analisar_ia_background
from app.core.cache import invalidar_kanban

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/whatsapp/{tenant_id}", status_code=status.HTTP_200_OK)
async def webhook_whatsapp(
    tenant_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Recebe mensagens da Z-API e:
      1. Valida o segredo do webhook
      2. Identifica o lead pelo número
      3. Roteia para a oportunidade ativa (ou cria nova)
      4. Salva a mensagem
      5. Dispara a análise da IA em background
    """
    settings = get_settings()
    
    # Validação de segurança simples por query-string
    secret = request.query_params.get("secret")
    if secret != settings.ZAPI_WEBHOOK_SECRET:
        logger.warning(f"Webhook WhatsApp com secret inválido para tenant {tenant_id}")
        raise HTTPException(status_code=403, detail="Secret inválido")
    
    payload = await request.json()
    parsed = parse_webhook_payload(payload)
    
    if not parsed:
        # Evento ignorado (mensagem outbound, status, mídia não-textual) — responde 200 para Z-API não reenviar
        return {"status": "ignored"}
    
    # Confirma que o tenant tem um canal Z-API ativo (segurança extra)
    stmt = select(CanalComunicacao).where(
        CanalComunicacao.tenant_id == tenant_id,
        CanalComunicacao.tipo == TipoCanal.WHATSAPP_ZAPI,
        CanalComunicacao.ativo == True,
    )
    result = await db.execute(stmt)
    canal = result.scalars().first()
    if not canal:
        logger.warning(f"Webhook recebido para tenant {tenant_id} sem canal Z-API ativo")
        raise HTTPException(status_code=404, detail="Canal não configurado")
    
    # Roteia: número → Lead → Oportunidade
    lead = await resolver_lead_por_whatsapp(
        db, tenant_id, parsed["whatsapp_id"], nome_fallback=parsed.get("nome_remetente")
    )
    oportunidade = await resolver_oportunidade_ativa(db, tenant_id, lead.id)
    
    mensagem = await registrar_mensagem_recebida(
        db,
        tenant_id=tenant_id,
        oportunidade_id=oportunidade.id,
        conteudo=parsed["conteudo"],
        tipo=TipoMensagem.WHATSAPP,
        id_externo=parsed.get("id_externo"),
    )
    
    await db.commit()
    
    if mensagem:
        # Mensagem nova chegou — kanban precisa refletir (ultima_interacao mudou)
        await invalidar_kanban(tenant_id)
        background_tasks.add_task(_task_analisar_ia_background, oportunidade.id, tenant_id)
    
    return {"status": "ok", "oportunidade_id": str(oportunidade.id)}
