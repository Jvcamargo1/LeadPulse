import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class MensagemBase(BaseModel):
    remetente: str # Ex: "LEAD" ou "VENDEDOR"
    tipo: str # Ex: "TEXTO", "WHATSAPP", "EMAIL"
    conteudo_texto: str

class MensagemCreate(MensagemBase):
    oportunidade_id: uuid.UUID

class MensagemResponse(MensagemBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    oportunidade_id: uuid.UUID
    data_envio: datetime
    analisada_pela_ia: bool

    model_config = ConfigDict(from_attributes=True)
