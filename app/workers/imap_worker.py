"""
Worker assíncrono que faz polling dos canais Gmail (IMAP) buscando e-mails novos.

ATENÇÃO ARQUITETURAL: este worker roda dentro do mesmo processo do FastAPI
(via lifespan/asyncio.create_task). Funciona para MVP, mas em produção real
recomenda-se mover para um processo separado (Celery, ARQ, ou um container worker).
"""
import asyncio
import logging
from typing import List

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models import CanalComunicacao, TipoCanal, TipoMensagem
from app.services.gmail_service import buscar_emails_novos
from app.services.routing import (
    resolver_lead_por_email,
    resolver_oportunidade_ativa,
    registrar_mensagem_recebida,
)
from app.api.routes.oportunidades import _task_analisar_ia_background
from app.core.cache import invalidar_kanban

logger = logging.getLogger(__name__)


async def _processar_canal_gmail(canal_id) -> None:
    """Processa um único canal Gmail: busca e-mails novos, salva e dispara IA."""
    async with AsyncSessionLocal() as db:
        stmt = select(CanalComunicacao).where(CanalComunicacao.id == canal_id)
        result = await db.execute(stmt)
        canal = result.scalars().first()
        
        if not canal or not canal.ativo:
            return
        
        try:
            emails_novos, novo_uid = await buscar_emails_novos(canal)
        except Exception as e:
            logger.exception(f"Falha ao buscar e-mails do canal {canal.id}: {e}")
            return
        
        if not emails_novos:
            return
        
        logger.info(f"Canal Gmail {canal.identificador}: {len(emails_novos)} e-mail(s) novo(s)")
        
        oportunidades_para_analisar = []
        
        for email_data in emails_novos:
            try:
                lead = await resolver_lead_por_email(
                    db,
                    tenant_id=canal.tenant_id,
                    email=email_data["email_remetente"],
                    nome_fallback=email_data.get("nome_remetente"),
                )
                oportunidade = await resolver_oportunidade_ativa(db, canal.tenant_id, lead.id)
                
                # Concatena assunto + corpo para a IA ter contexto
                conteudo_completo = f"[Assunto: {email_data['assunto']}]\n\n{email_data['conteudo']}"
                
                msg = await registrar_mensagem_recebida(
                    db,
                    tenant_id=canal.tenant_id,
                    oportunidade_id=oportunidade.id,
                    conteudo=conteudo_completo,
                    tipo=TipoMensagem.EMAIL,
                    id_externo=email_data.get("id_externo"),
                )
                if msg:
                    oportunidades_para_analisar.append(oportunidade.id)
            except Exception as e:
                logger.exception(f"Erro processando e-mail individual: {e}")
                continue
        
        # Atualiza o ponteiro do canal para não reprocessar e-mails
        if novo_uid:
            canal.ultimo_uid_lido = str(novo_uid)
        
        await db.commit()
        
        if oportunidades_para_analisar:
            await invalidar_kanban(canal.tenant_id)
        
        # Dispara análises IA depois do commit (evita lock no banco)
        for op_id in set(oportunidades_para_analisar):
            asyncio.create_task(_task_analisar_ia_background(op_id, canal.tenant_id))


async def imap_polling_loop() -> None:
    """
    Loop infinito que verifica todos os canais Gmail ativos periodicamente.
    Cada iteração:
      1. Busca canais Gmail ativos de todos os tenants
      2. Processa cada um em paralelo (gather)
      3. Aguarda o intervalo configurado
    """
    settings = get_settings()
    intervalo = settings.IMAP_POLL_INTERVAL_SECONDS
    
    logger.info(f"Worker IMAP iniciado (intervalo={intervalo}s)")
    
    while True:
        try:
            async with AsyncSessionLocal() as db:
                stmt = select(CanalComunicacao.id).where(
                    CanalComunicacao.tipo == TipoCanal.EMAIL_GMAIL,
                    CanalComunicacao.ativo == True,
                )
                result = await db.execute(stmt)
                canal_ids = [row[0] for row in result.all()]
            
            if canal_ids:
                await asyncio.gather(
                    *[_processar_canal_gmail(cid) for cid in canal_ids],
                    return_exceptions=True,
                )
        except asyncio.CancelledError:
            logger.info("Worker IMAP cancelado (shutdown)")
            raise
        except Exception as e:
            logger.exception(f"Erro no loop IMAP: {e}")
        
        await asyncio.sleep(intervalo)
