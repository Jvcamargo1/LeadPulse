import uuid
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Gera uma nova sessão de banco de dados para cada requisição."""
    async with AsyncSessionLocal() as session:
        yield session

# Para o MVP rodar sem tela de login, fixamos um Tenant ID estático ("mock")
# Em produção, este valor seria extraído do Token JWT do usuário logado.
MOCK_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

async def get_current_tenant_id() -> uuid.UUID:
    """Retorna o ID do tenant (empresa) atual."""
    return MOCK_TENANT_ID