import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class OportunidadeBase(BaseModel):
    vendedor_id: Optional[uuid.UUID] = None
    lead_id: uuid.UUID
    valor: Optional[float] = Field(None, ge=0.0)
    estagio_funil: str
    temperatura_ia: Optional[str] = None
    status_conversa_ia: Optional[str] = None

class OportunidadeCreate(OportunidadeBase):
    pass

class OportunidadeUpdate(BaseModel):
    vendedor_id: Optional[uuid.UUID] = None
    valor: Optional[float] = Field(None, ge=0.0)
    estagio_funil: Optional[str] = None
    temperatura_ia: Optional[str] = None
    status_conversa_ia: Optional[str] = None

class OportunidadeResponse(OportunidadeBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    ultima_interacao: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
