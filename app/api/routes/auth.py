from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.dependencies import get_db
from app.models import Usuario
from app.core.security import verify_password, create_access_token

router = APIRouter(tags=["Autenticação"])

@router.post("/login")
async def login(
    response: Response,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """Autentica o usuário e retorna o Token JWT."""
    stmt = select(Usuario).where(Usuario.email == form_data.username)
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="E-mail ou senha incorretos")
        
    access_token = create_access_token(subject=user.id, tenant_id=user.tenant_id)
    
    # Retorna o token para o Swagger usar e seta como Cookie para o Kanban HTML
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    response.headers["HX-Redirect"] = "/" # Informa ao HTMX para recarregar a tela no Kanban
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout(response: Response):
    """Remove o token do navegador e desloga o usuário."""
    response.delete_cookie("access_token")
    response.headers["HX-Redirect"] = "/login"
    return {"mensagem": "Logout efetuado com sucesso"}