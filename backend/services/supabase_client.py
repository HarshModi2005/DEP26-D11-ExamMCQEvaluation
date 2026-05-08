"""
Supabase (Postgres) async client.

Provides a single shared asyncpg connection pool used by services that need
to read/write cache data in Supabase. Configure with the SUPABASE_DB_URL
environment variable (the pooled Postgres connection string from the
Supabase dashboard, typically on port 6543 with sslmode=require).

asyncpg is imported lazily so importing this module does not require asyncpg
until CACHE_BACKEND=supabase actually connects (and so `pip install asyncpg`
in the same environment as uvicorn fixes "No module named asyncpg").
"""

from __future__ import annotations

import os
import asyncio
from typing import Any, Optional

_pool: Optional[Any] = None
_pool_lock = asyncio.Lock()


def _get_dsn() -> str:
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Provide the Supabase Postgres "
            "connection string (prefer the pooled one on port 6543 with sslmode=require)."
        )
    return dsn


def _require_asyncpg():
    try:
        import asyncpg  # noqa: WPS433
    except ImportError as e:
        raise RuntimeError(
            "asyncpg is required when CACHE_BACKEND=supabase. "
            "Install it in the same Python environment that runs uvicorn: "
            "pip install asyncpg"
        ) from e
    return asyncpg


async def get_pool() -> Any:
    """Return the lazily-initialised shared asyncpg pool."""
    global _pool
    if _pool is not None:
        return _pool
    asyncpg = _require_asyncpg()
    async with _pool_lock:
        if _pool is None:
            min_size = int(os.getenv("SUPABASE_POOL_MIN", "1"))
            max_size = int(os.getenv("SUPABASE_POOL_MAX", "10"))
            _pool = await asyncpg.create_pool(
                dsn=_get_dsn(),
                min_size=min_size,
                max_size=max_size,
                command_timeout=30,
                statement_cache_size=0,
            )
    return _pool


async def close_pool() -> None:
    """Close the shared pool on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
