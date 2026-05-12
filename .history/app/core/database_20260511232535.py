import os
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
        # Cria todas as tabelas (definidas em app.models) se não existirem
        await conn.run_sync(Base.metadata.create_all)