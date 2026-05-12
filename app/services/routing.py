import uuid
import re
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.models import Lead, Oportunidade, Mensagem, RemetenteRole, TipoMensagem

logger = logging.getLogger(__name__)


def normalizar_whatsapp(numero: str) -> str:
    """
    Normaliza um número de WhatsApp para o formato E.164 sem o '+'.
    Ex: '+55 11 99999-9999' -> '5511999999999'
    """
    return re.sub(r"\D", "", numero or "")


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


async def resolver_lead_por_whatsapp(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    whatsapp_id: str,
    nome_fallback: Optional[str] = None,
) -> Lead:
    """
    Acha o Lead correspondente ao número de WhatsApp dentro do tenant.
    Se não existir, cria um novo Lead com o número informado (e nome fallback se vier).
    """
    whatsapp_norm = normalizar_whatsapp(whatsapp_id)
    
    stmt = select(Lead).where(
        Lead.tenant_id == tenant_id,
        Lead.whatsapp_id == whatsapp_norm,
    )
    result = await db.execute(stmt)
    lead = result.scalars().first()
    
    if lead:
        return lead
    
    # Cria lead novo "frio" a partir do número que entrou em contato
    lead = Lead(
        tenant_id=tenant_id,
        nome=nome_fallback or f"Lead WhatsApp {whatsapp_norm[-4:]}",
        telefone=whatsapp_norm,
        whatsapp_id=whatsapp_norm,
        origem="WhatsApp Inbound",
    )
    db.add(lead)
    await db.flush()  # gera o ID
    logger.info(f"Novo lead criado via WhatsApp inbound: {lead.id} ({whatsapp_norm})")
    return lead


async def resolver_lead_por_email(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
    nome_fallback: Optional[str] = None,
) -> Lead:
    """Análogo ao resolver_lead_por_whatsapp mas para e-mail."""
    email_norm = normalizar_email(email)
    
    stmt = select(Lead).where(
        Lead.tenant_id == tenant_id,
        Lead.email_principal == email_norm,
    )
    result = await db.execute(stmt)
    lead = result.scalars().first()
    
    if lead:
        return lead
    
    lead = Lead(
        tenant_id=tenant_id,
        nome=nome_fallback or email_norm.split("@")[0],
        email_principal=email_norm,
        origem="Email Inbound",
    )
    db.add(lead)
    await db.flush()
    logger.info(f"Novo lead criado via Email inbound: {lead.id} ({email_norm})")
    return lead


async def resolver_oportunidade_ativa(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> Oportunidade:
    """
    Retorna a Oportunidade mais recente do Lead que NÃO esteja fechada.
    Se não houver nenhuma aberta, cria uma nova em 'Prospecção'.
    
    Estratégia de roteamento: 'mais recente não-fechada'. Para o MVP basta.
    """
    estagios_fechados = ("Fechado Ganho", "Fechado Perdido")
    
    stmt = (
        select(Oportunidade)
        .where(
            Oportunidade.tenant_id == tenant_id,
            Oportunidade.lead_id == lead_id,
            Oportunidade.estagio_funil.notin_(estagios_fechados),
        )
        .order_by(desc(Oportunidade.ultima_interacao.nulls_last()))
    )
    result = await db.execute(stmt)
    oportunidade = result.scalars().first()
    
    if oportunidade:
        return oportunidade
    
    # Sem oportunidade aberta — cria uma nova em Prospecção
    oportunidade = Oportunidade(
        tenant_id=tenant_id,
        lead_id=lead_id,
        estagio_funil="Prospecção",
        ultima_interacao=datetime.now(timezone.utc),
    )
    db.add(oportunidade)
    await db.flush()
    logger.info(f"Nova oportunidade criada automaticamente para lead {lead_id}: {oportunidade.id}")
    return oportunidade


async def registrar_mensagem_recebida(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    oportunidade_id: uuid.UUID,
    conteudo: str,
    tipo: TipoMensagem,
    id_externo: Optional[str] = None,
) -> Optional[Mensagem]:
    """
    Registra uma mensagem recebida (do Lead) em uma Oportunidade.
    Idempotente: se id_externo já existir no banco, não duplica.
    Retorna a mensagem criada, ou None se for duplicata.
    """
    if id_externo:
        stmt = select(Mensagem).where(
            Mensagem.tenant_id == tenant_id,
            Mensagem.id_externo == id_externo,
        )
        result = await db.execute(stmt)
        if result.scalars().first():
            logger.info(f"Mensagem duplicada ignorada (id_externo={id_externo})")
            return None
    
    msg = Mensagem(
        tenant_id=tenant_id,
        oportunidade_id=oportunidade_id,
        remetente=RemetenteRole.LEAD,
        tipo=tipo,
        conteudo_texto=conteudo,
        id_externo=id_externo,
    )
    db.add(msg)
    
    # Atualiza timestamp da oportunidade
    stmt_op = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id,
        Oportunidade.tenant_id == tenant_id,
    )
    result_op = await db.execute(stmt_op)
    op = result_op.scalars().first()
    if op:
        op.ultima_interacao = datetime.now(timezone.utc)
    
    return msg
