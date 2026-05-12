"""
Cache async usando Redis, padrão cache-aside.

Uso típico:
    cache = get_cache()
    dados = await cache.get_json(f"kanban:{tenant_id}")
    if dados is None:
        dados = await consulta_pesada(...)
        await cache.set_json(f"kanban:{tenant_id}", dados, ttl=60)
    return dados
"""
import json
import logging
from typing import Any, Optional
import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Cache:
    """Wrapper fino sobre redis.asyncio com helpers para JSON e invalidação por padrão."""
    
    def __init__(self, url: str):
        self._client = aioredis.from_url(url, decode_responses=True, max_connections=10)
    
    async def get_json(self, key: str) -> Optional[Any]:
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Cache GET falhou para '{key}': {e}")
            return None
    
    async def set_json(self, key: str, value: Any, ttl: int = 60) -> None:
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as e:
            logger.warning(f"Cache SET falhou para '{key}': {e}")
    
    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning(f"Cache DELETE falhou para '{key}': {e}")
    
    async def delete_pattern(self, pattern: str) -> None:
        """Deleta todas as chaves que batem com um padrão glob (ex: 'kanban:*')."""
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"Cache DELETE_PATTERN falhou para '{pattern}': {e}")
    
    async def close(self) -> None:
        await self._client.aclose()


# Singleton lazy
_cache_instance: Optional[Cache] = None


def get_cache() -> Cache:
    global _cache_instance
    if _cache_instance is None:
        settings = get_settings()
        _cache_instance = Cache(settings.REDIS_URL)
    return _cache_instance


# ============================================================
# Helpers específicos do domínio
# ============================================================

def kanban_cache_key(tenant_id) -> str:
    return f"kanban:{tenant_id}"


async def invalidar_kanban(tenant_id) -> None:
    """Invalida o cache do Kanban de um tenant após qualquer modificação."""
    await get_cache().delete(kanban_cache_key(tenant_id))
