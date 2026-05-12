import uuid
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum

from sqlalchemy import ForeignKey, String, Text, DateTime, Float, Boolean, Uuid, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SALES = "SALES"

class RemetenteRole(str, Enum):
    LEAD = "LEAD"
    VENDEDOR = "VENDEDOR"
    SISTEMA = "SISTEMA"

class TipoMensagem(str, Enum):
    TEXTO = "TEXTO"
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"

class TipoCanal(str, Enum):
    """Tipos de canais de comunicação suportados pelo LeadPulse."""
    WHATSAPP_ZAPI = "WHATSAPP_ZAPI"
    EMAIL_GMAIL = "EMAIL_GMAIL"

class Tenant(Base):
    __tablename__ = "tenant"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nome_empresa: Mapped[str] = mapped_column(String, nullable=False)
    
    # Relacionamentos
    usuarios: Mapped[List["Usuario"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    leads: Mapped[List["Lead"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    oportunidades: Mapped[List["Oportunidade"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    canais: Mapped[List["CanalComunicacao"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")

class Usuario(Base):
    __tablename__ = "usuario"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    role: Mapped[UserRole] = mapped_column(String, nullable=False)
    
    # Relacionamentos
    tenant: Mapped["Tenant"] = relationship(back_populates="usuarios")
    oportunidades: Mapped[List["Oportunidade"]] = relationship(back_populates="vendedor")
    
    __table_args__ = (
        Index("ix_usuario_tenant_email", "tenant_id", "email", unique=True),
    )

class Lead(Base):
    __tablename__ = "lead"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String, nullable=False)
    telefone: Mapped[Optional[str]] = mapped_column(String)
    origem: Mapped[Optional[str]] = mapped_column(String)
    
    # NOVO: Identificadores externos para roteamento de mensagens recebidas
    whatsapp_id: Mapped[Optional[str]] = mapped_column(String, index=True)  # E.164: 5511999999999
    email_principal: Mapped[Optional[str]] = mapped_column(String, index=True)
    
    # Relacionamentos
    tenant: Mapped["Tenant"] = relationship(back_populates="leads")
    oportunidades: Mapped[List["Oportunidade"]] = relationship(back_populates="lead")
    
    # Índices compostos para o roteamento reverso (Webhook → Lead)
    __table_args__ = (
        Index("ix_lead_tenant_whatsapp", "tenant_id", "whatsapp_id"),
        Index("ix_lead_tenant_email_principal", "tenant_id", "email_principal"),
    )

class Oportunidade(Base):
    __tablename__ = "oportunidade"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    vendedor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True, index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"), nullable=False, index=True)
    valor: Mapped[Optional[float]] = mapped_column(Float)
    estagio_funil: Mapped[str] = mapped_column(String, nullable=False)
    temperatura_ia: Mapped[Optional[str]] = mapped_column(String)
    status_conversa_ia: Mapped[Optional[str]] = mapped_column(String)
    ultima_interacao: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relacionamentos
    tenant: Mapped["Tenant"] = relationship(back_populates="oportunidades")
    vendedor: Mapped[Optional["Usuario"]] = relationship(back_populates="oportunidades")
    lead: Mapped["Lead"] = relationship(back_populates="oportunidades")
    mensagens: Mapped[List["Mensagem"]] = relationship(back_populates="oportunidade", cascade="all, delete-orphan")
    tarefas: Mapped[List["Tarefa_FollowUp"]] = relationship(back_populates="oportunidade", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("ix_oportunidade_tenant_estagio", "tenant_id", "estagio_funil"),
    )

class Mensagem(Base):
    __tablename__ = "mensagem"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    oportunidade_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("oportunidade.id", ondelete="CASCADE"), nullable=False, index=True)
    remetente: Mapped[RemetenteRole] = mapped_column(String, nullable=False)
    tipo: Mapped[TipoMensagem] = mapped_column(String, nullable=False)
    conteudo_texto: Mapped[str] = mapped_column(Text, nullable=False)
    data_envio: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    analisada_pela_ia: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # NOVO: ID externo da mensagem no canal de origem (para idempotência)
    id_externo: Mapped[Optional[str]] = mapped_column(String, index=True)
    
    # Relacionamentos
    oportunidade: Mapped["Oportunidade"] = relationship(back_populates="mensagens")

class Tarefa_FollowUp(Base):
    __tablename__ = "tarefa_followup"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    oportunidade_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("oportunidade.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    data_limite: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rascunho_sugerido_ia: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relacionamentos
    oportunidade: Mapped["Oportunidade"] = relationship(back_populates="tarefas")
    
    __table_args__ = (
        Index("ix_tarefa_tenant_status", "tenant_id", "status"),
    )

class CanalComunicacao(Base):
    """
    Representa a conexão de um canal externo (WhatsApp via Z-API, Email via Gmail)
    pertencente a um Tenant. Credenciais são armazenadas criptografadas.
    """
    __tablename__ = "canal_comunicacao"
    
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo: Mapped[TipoCanal] = mapped_column(String, nullable=False)
    
    # Identificador legível (ex: "+5511999999999" para WhatsApp, "vendas@empresa.com" para email)
    identificador: Mapped[str] = mapped_column(String, nullable=False)
    
    # JSON cifrado contendo credenciais (instance_id+token do Z-API, ou imap_user+app_password do Gmail)
    credenciais_cifradas: Mapped[str] = mapped_column(Text, nullable=False)
    
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Última UID lida do IMAP (para Gmail) - evita reprocessar e-mails antigos
    ultimo_uid_lido: Mapped[Optional[str]] = mapped_column(String)
    
    # Relacionamentos
    tenant: Mapped["Tenant"] = relationship(back_populates="canais")
    
    __table_args__ = (
        Index("ix_canal_tenant_tipo_ativo", "tenant_id", "tipo", "ativo"),
    )
