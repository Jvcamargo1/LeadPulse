from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base

# Usando SQLite assíncrono para o MVP e desenvolvimento local
SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./leadpulse.db"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}, 
    echo=True  # Imprime as queries SQL no console (útil no desenvolvimento)
)

AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def init_db():
    async with engine.begin() as conn:
        # Cria todas as tabelas (definidas em app.models) se não existirem
        await conn.run_sync(Base.metadata.create_all)