import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base

# URL do PostgreSQL (Async). Usa a variável de ambiente se existir, senão usa default local
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5432/leadpulse"
)

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=True  # Imprime as queries SQL no console (útil no desenvolvimento)
)

AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Adiciona colunas novas sem quebrar bancos existentes
        await conn.execute(text("ALTER TABLE oportunidade ADD COLUMN IF NOT EXISTS notas TEXT"))
        await conn.execute(text("ALTER TABLE lead ADD COLUMN IF NOT EXISTS is_cliente BOOLEAN NOT NULL DEFAULT false"))
        await conn.execute(text("ALTER TABLE lead ADD COLUMN IF NOT EXISTS nome_completo VARCHAR"))
        await conn.execute(text("ALTER TABLE lead ADD COLUMN IF NOT EXISTS cpf_cnpj VARCHAR"))
        await conn.execute(text("ALTER TABLE lead ADD COLUMN IF NOT EXISTS cidade VARCHAR"))
        await conn.execute(text("ALTER TABLE lead ADD COLUMN IF NOT EXISTS data_conversao TIMESTAMPTZ"))