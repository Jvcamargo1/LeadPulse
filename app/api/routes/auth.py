from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.dependencies import get_db
from app.core.security import verify_password, create_access_token
from app.models import Usuario

router = APIRouter(tags=["Autenticação"])
settings = get_settings()


@router.post("/login")
async def login(
    response: Response,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Autentica o usuário e retorna o Token JWT."""
    email_norm = form_data.username.strip().lower()
    
    # Como email agora é globalmente único, esta busca é segura
    stmt = select(Usuario).where(Usuario.email == email_norm)
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="E-mail ou senha incorretos")
    
    access_token = create_access_token(subject=user.id, tenant_id=user.tenant_id)
    
    # Cookie seguro: httponly impede acesso por JS, samesite="lax" protege contra CSRF,
    # secure=True só em produção (HTTPS), max_age alinha com expiração do JWT.
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.headers["HX-Redirect"] = "/"
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.headers["HX-Redirect"] = "/login"
    return {"mensagem": "Logout efetuado"}
