import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Configurações da aplicação carregadas a partir de variáveis de ambiente.
    Use um arquivo .env na raiz do projeto durante o desenvolvimento.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    # Ambiente
    ENVIRONMENT: str = "development"  # development | production
    
    # Banco
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/leadpulse"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Groq (IA)
    GROQ_API_KEY: str = ""
    
    # Chave-mestre para criptografar credenciais dos canais
    # CRITICAL: gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FERNET_KEY: str = ""
    
    # SECRET KEY para assinatura JWT
    # CRITICAL: NUNCA use o default em produção. Gere com: openssl rand -hex 32
    SECRET_KEY: str = ""
    
    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 dia
    
    # Webhooks
    ZAPI_WEBHOOK_SECRET: str = "troque-este-valor-em-producao"
    
    # Worker IMAP
    IMAP_POLL_INTERVAL_SECONDS: int = 60
    DISABLE_BACKGROUND_WORKERS: bool = False
    
    # Cache
    CACHE_TTL_KANBAN_SECONDS: int = 60

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    
    # Validações fatais em produção
    if settings.is_production:
        if not settings.SECRET_KEY:
            raise RuntimeError("SECRET_KEY é obrigatória em produção")
        if not settings.FERNET_KEY:
            raise RuntimeError("FERNET_KEY é obrigatória em produção")
    
    # Fallback de desenvolvimento (com aviso)
    if not settings.SECRET_KEY:
        import warnings
        warnings.warn("SECRET_KEY não configurada — usando valor inseguro de desenvolvimento")
        settings.SECRET_KEY = "dev-only-NOT-FOR-PRODUCTION-please-set-SECRET_KEY"
    
    return settings
