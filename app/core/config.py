import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Configurações da aplicação carregadas a partir de variáveis de ambiente.
    Use um arquivo .env na raiz do projeto durante o desenvolvimento.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    # Banco
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/leadpulse"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Groq (IA)
    GROQ_API_KEY: str = ""
    
    # Chave-mestre para criptografar credenciais dos canais
    # CRITICAL: gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FERNET_KEY: str = ""
    
    # Webhooks - segredo compartilhado por instalação para validar callbacks da Z-API
    ZAPI_WEBHOOK_SECRET: str = "troque-este-valor-em-producao"
    
    # Worker IMAP - intervalo de checagem em segundos
    IMAP_POLL_INTERVAL_SECONDS: int = 60
    
    # Modo desenvolvimento - desabilita o worker IMAP automático
    DISABLE_BACKGROUND_WORKERS: bool = False

@lru_cache
def get_settings() -> Settings:
    return Settings()
