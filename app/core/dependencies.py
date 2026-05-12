import uuid
from typing import AsyncGenerator
from fastapi import Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from app.core.database import AsyncSessionLocal
from app.core.security import SECRET_KEY, ALGORITHM

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Gera uma nova sessão de banco de dados para cada requisição."""
    async with AsyncSessionLocal() as session:
        yield session

async def get_current_tenant_id(request: Request) -> uuid.UUID:
    """Retorna o ID do tenant (empresa) atual."""
    # 1. Busca token nos cookies (Navegador/HTMX) ou no Header Authorization (API/Swagger)
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tenant_id: str = payload.get("tenant_id")
        if tenant_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token não possui Tenant ID")
        return uuid.UUID(tenant_id)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")