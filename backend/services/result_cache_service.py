"""
Result Cache Service
===================
Caches OCR results and evaluation outcomes to avoid reprocessing.
Uses file hashing and intelligent cache invalidation.

Supports two backends selected by the CACHE_BACKEND env var:
    * "sqlite"   - local SQLite file (default, good for local dev)
    * "supabase" - Supabase Postgres via asyncpg (recommended for deployment)

The public async API (get_cached_ocr_result, cache_ocr_result,
get_cached_evaluation_result, cache_evaluation_result, cleanup_cache,
get_cache_stats, purge_stale_eval_entries) is backend-agnostic so callers
do not change.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _calculate_file_hash_sync(file_path: str) -> str:
    """Calculate SHA-256 hash of a file's content."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _calculate_answer_key_hash(answer_key: Dict) -> str:
    """Generate a stable hash from an answer key."""
    key_content = json.dumps(answer_key, sort_keys=True)
    return hashlib.sha256(key_content.encode()).hexdigest()


# NOTE on keying scheme
# ---------------------
# Historically the cache wrote TWO rows per sheet:
#   * OCR row  : file_hash = f"ocr:{evaluation_id}:{file_id}"
#   * Eval row : file_hash = sha256(f"eval:{evaluation_id}:{file_id}:{ak_hash}")
# Result: cache rows duplicated and, worse, stale global `_current_answer_key`
# made quiz6 runs hit quiz5's eval rows for the same Drive file_id.
#
# The `sheet_cache_key` scheme below consolidates everything into ONE row per
# (evaluation_id, file_id). The row holds both OCR (ocr_result) and the scored
# result (evaluation_result); answer_key_hash in the column is authoritative.

def sheet_cache_key(evaluation_id: str, file_id: str) -> str:
    """
    Deterministic, debuggable cache key for a single student sheet within an
    evaluation. The `v2:` prefix guarantees no collision with legacy keys.
    """
    if not evaluation_id or not str(evaluation_id).strip():
        raise ValueError("evaluation_id is required for sheet cache key")
    if not file_id or not str(file_id).strip():
        raise ValueError("file_id is required for sheet cache key")
    return f"sheet:v2:{evaluation_id}:{file_id}"


# ---------------------------------------------------------------------------
# SQLite driver (legacy / local-dev)
# ---------------------------------------------------------------------------

class _SqliteCacheDriver:
    """Original SQLite-backed cache driver. Kept for local development and fallback."""

    def __init__(self, cache_db_path: str, max_cache_size_bytes: int, executor: ThreadPoolExecutor):
        self.cache_db_path = cache_db_path
        self.max_cache_size_bytes = max_cache_size_bytes
        self.executor = executor
        self._init_cache_db()

    def _init_cache_db(self) -> None:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS result_cache (
                file_hash TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                ocr_result TEXT NOT NULL,
                evaluation_result TEXT,
                answer_key_hash TEXT,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                result_size INTEGER DEFAULT 0
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_answer_key_hash ON result_cache(answer_key_hash)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_last_accessed ON result_cache(last_accessed)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON result_cache(created_at)")

        existing_cols = {row[1] for row in c.execute("PRAGMA table_info(result_cache)").fetchall()}
        if "evaluation_id" not in existing_cols:
            c.execute("ALTER TABLE result_cache ADD COLUMN evaluation_id TEXT")
        if "file_id" not in existing_cols:
            c.execute("ALTER TABLE result_cache ADD COLUMN file_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_evaluation_id ON result_cache(evaluation_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_eval_file ON result_cache(evaluation_id, file_id)")

        conn.commit()
        conn.close()
        print(f"✅ Result cache initialised (sqlite) at {self.cache_db_path}")

    # ---- async wrappers run blocking sqlite on the thread pool ----

    async def get_cached_result(self, file_hash: str, result_type: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_cached_result_sync, file_hash, result_type)

    async def get_cached_evaluation(self, file_hash: str, answer_key_hash: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_cached_evaluation_sync, file_hash, answer_key_hash)

    async def cache_result(
        self,
        file_hash: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Optional[Dict[str, Any]],
        answer_key_hash: Optional[str],
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._cache_result_sync,
            file_hash,
            file_name,
            ocr_result,
            evaluation_result,
            answer_key_hash,
        )

    async def cleanup(self, max_age_days: int, force_cleanup: bool) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._cleanup_sync, max_age_days, force_cleanup)

    async def stats(self) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._stats_sync)

    async def stats_for_evaluation(self, evaluation_id: str) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._stats_for_evaluation_sync, evaluation_id
        )

    async def purge_stale_eval_entries(self) -> Tuple[int, int]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._purge_stale_eval_sync)

    # ---- synchronous sqlite implementations ----

    def _get_cached_result_sync(self, file_hash: str, result_type: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.cache_db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            c.execute("SELECT * FROM result_cache WHERE file_hash = ?", (file_hash,))
            row = c.fetchone()
            if row:
                c.execute(
                    "UPDATE result_cache SET last_accessed = ?, access_count = access_count + 1 WHERE file_hash = ?",
                    (time.time(), file_hash),
                )
                conn.commit()
                if result_type == "ocr":
                    return json.loads(row["ocr_result"])
                if result_type == "evaluation" and row["evaluation_result"]:
                    return json.loads(row["evaluation_result"])
            return None
        except Exception as e:
            print(f"Cache lookup error: {e}")
            return None
        finally:
            conn.close()

    def _get_cached_evaluation_sync(self, file_hash: str, answer_key_hash: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.cache_db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            c.execute(
                "SELECT * FROM result_cache WHERE file_hash = ? AND answer_key_hash = ?",
                (file_hash, answer_key_hash),
            )
            row = c.fetchone()
            if row and row["evaluation_result"]:
                c.execute(
                    "UPDATE result_cache SET last_accessed = ?, access_count = access_count + 1 WHERE file_hash = ?",
                    (time.time(), file_hash),
                )
                conn.commit()
                return json.loads(row["evaluation_result"])
            return None
        except Exception as e:
            print(f"Evaluation cache lookup error: {e}")
            return None
        finally:
            conn.close()

    def _cache_result_sync(
        self,
        file_hash: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Optional[Dict[str, Any]],
        answer_key_hash: Optional[str],
    ) -> None:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            ocr_json = json.dumps(ocr_result)
            eval_json = json.dumps(evaluation_result) if evaluation_result else None
            result_size = len(ocr_json) + (len(eval_json) if eval_json else 0)
            current_time = time.time()
            c.execute(
                """
                INSERT OR REPLACE INTO result_cache
                    (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash,
                     created_at, last_accessed, access_count, result_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    file_hash,
                    file_name,
                    ocr_json,
                    eval_json,
                    answer_key_hash,
                    current_time,
                    current_time,
                    result_size,
                ),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Cache write error: {e}")
            raise
        finally:
            conn.close()

    def _cleanup_sync(self, max_age_days: int, force_cleanup: bool) -> None:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT SUM(result_size) FROM result_cache")
            current_size = c.fetchone()[0] or 0
            cutoff_time = time.time() - (max_age_days * 24 * 3600)
            if current_size > self.max_cache_size_bytes or force_cleanup:
                c.execute("DELETE FROM result_cache WHERE created_at < ?", (cutoff_time,))
                old_deleted = c.rowcount
                lru_deleted = 0
                if current_size > self.max_cache_size_bytes:
                    c.execute(
                        """
                        DELETE FROM result_cache
                        WHERE file_hash IN (
                            SELECT file_hash FROM result_cache
                            ORDER BY last_accessed ASC
                            LIMIT (SELECT COUNT(*) / 4 FROM result_cache)
                        )
                        """
                    )
                    lru_deleted = c.rowcount
                conn.commit()
                c.execute("SELECT SUM(result_size) FROM result_cache")
                new_size = c.fetchone()[0] or 0
                print("🧹 Cache cleanup completed:")
                print(f"   Removed {old_deleted} old entries, {lru_deleted} LRU entries")
                print(f"   Size: {current_size/1024/1024:.1f}MB → {new_size/1024/1024:.1f}MB")
        except Exception as e:
            conn.rollback()
            print(f"Cache cleanup error: {e}")
        finally:
            conn.close()

    def _stats_sync(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*), SUM(result_size), AVG(access_count) FROM result_cache")
            count, total_size, avg_access = c.fetchone()
            recent_cutoff = time.time() - (24 * 3600)
            c.execute("SELECT COUNT(*) FROM result_cache WHERE last_accessed > ?", (recent_cutoff,))
            recent_access = c.fetchone()[0]
            c.execute("SELECT answer_key_hash, COUNT(*) FROM result_cache GROUP BY answer_key_hash")
            key_distribution = dict(c.fetchall())
            return {
                "total_entries": count or 0,
                "total_size_mb": (total_size or 0) / 1024 / 1024,
                "average_access_count": avg_access or 0,
                "recent_access_24h": recent_access or 0,
                "answer_key_distribution": key_distribution,
                "cache_hit_potential": f"{min(100, (count or 0) * 2)}%",
            }
        except Exception as e:
            print(f"Cache stats error: {e}")
            return {}
        finally:
            conn.close()

    def _stats_for_evaluation_sync(self, evaluation_id: str) -> Dict[str, Any]:
        """
        Count cache rows that belong to a single evaluation.

        Includes:
          * rows with evaluation_id column set (new sheet:v2 scheme);
          * legacy OCR rows keyed as ``ocr:<evaluation_id>:<file_id>`` before
            the evaluation_id column existed.
        """
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute(
                """
                SELECT COUNT(*) FROM result_cache
                 WHERE evaluation_id = ?
                    OR (evaluation_id IS NULL AND (
                          file_hash LIKE 'sheet:v2:' || ? || ':%'
                       OR file_hash LIKE 'ocr:' || ? || ':%'
                       ))
                """,
                (evaluation_id, evaluation_id, evaluation_id),
            )
            total = c.fetchone()[0] or 0
            c.execute(
                """
                SELECT COUNT(*) FROM result_cache
                 WHERE (evaluation_id = ?
                    OR (evaluation_id IS NULL AND (
                          file_hash LIKE 'sheet:v2:' || ? || ':%'
                       OR file_hash LIKE 'ocr:' || ? || ':%'
                       )))
                   AND evaluation_result IS NOT NULL
                   AND TRIM(evaluation_result) NOT IN ('', 'null', '{}')
                """,
                (evaluation_id, evaluation_id, evaluation_id),
            )
            scored = c.fetchone()[0] or 0
            return {
                "evaluation_entries": int(total),
                "evaluation_fully_scored": int(scored),
            }
        except Exception as e:
            print(f"Per-evaluation cache stats error: {e}")
            return {"evaluation_entries": 0, "evaluation_fully_scored": 0}
        finally:
            conn.close()

    def _purge_stale_eval_sync(self) -> Tuple[int, int]:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT file_hash, ocr_result FROM result_cache WHERE file_name = '__eval__'")
            rows = c.fetchall()
            stale = []
            for file_hash, ocr_json in rows:
                try:
                    data = json.loads(ocr_json)
                    if "_answer_key_hash" not in data:
                        stale.append(file_hash)
                except Exception:
                    stale.append(file_hash)
            if stale:
                c.executemany("DELETE FROM result_cache WHERE file_hash = ?", [(h,) for h in stale])
                conn.commit()
            return len(stale), len(rows)
        finally:
            conn.close()

    # ---- new single-row sheet cache API (scoped by evaluation_id + file_id) ----

    async def get_sheet_cache(self, evaluation_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._get_sheet_cache_sync, evaluation_id, file_id
        )

    async def upsert_sheet_ocr(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._upsert_sheet_ocr_sync,
            evaluation_id,
            file_id,
            file_name,
            ocr_result,
        )

    async def upsert_sheet_evaluation(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        answer_key_hash: str,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._upsert_sheet_eval_sync,
            evaluation_id,
            file_id,
            file_name,
            ocr_result,
            evaluation_result,
            answer_key_hash,
        )

    async def purge_evaluation(self, evaluation_id: str) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._purge_evaluation_sync, evaluation_id
        )

    async def purge_stale_for_evaluation(
        self, evaluation_id: str, current_answer_key_hash: str
    ) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._purge_stale_for_evaluation_sync,
            evaluation_id,
            current_answer_key_hash,
        )

    def _get_sheet_cache_sync(self, evaluation_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        key = sheet_cache_key(evaluation_id, file_id)
        conn = sqlite3.connect(self.cache_db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            c.execute("SELECT * FROM result_cache WHERE file_hash = ?", (key,))
            row = c.fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE result_cache SET last_accessed = ?, access_count = access_count + 1 WHERE file_hash = ?",
                (time.time(), key),
            )
            conn.commit()
            ocr = None
            eval_res = None
            try:
                ocr = json.loads(row["ocr_result"]) if row["ocr_result"] else None
            except Exception:
                ocr = None
            try:
                eval_res = json.loads(row["evaluation_result"]) if row["evaluation_result"] else None
            except Exception:
                eval_res = None
            return {
                "ocr_result": ocr,
                "evaluation_result": eval_res,
                "answer_key_hash": row["answer_key_hash"],
                "file_name": row["file_name"],
            }
        except Exception as e:
            print(f"Sheet cache lookup error: {e}")
            return None
        finally:
            conn.close()

    def _upsert_sheet_ocr_sync(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
    ) -> None:
        key = sheet_cache_key(evaluation_id, file_id)
        ocr_json = json.dumps(ocr_result)
        now = time.time()
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute(
                """
                INSERT INTO result_cache
                    (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash,
                     created_at, last_accessed, access_count, result_size,
                     evaluation_id, file_id)
                VALUES (?, ?, ?, NULL, NULL, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(file_hash) DO UPDATE SET
                    file_name      = excluded.file_name,
                    ocr_result     = excluded.ocr_result,
                    last_accessed  = excluded.last_accessed,
                    access_count   = result_cache.access_count + 1,
                    result_size    = length(excluded.ocr_result) +
                                     COALESCE(length(result_cache.evaluation_result), 0),
                    evaluation_id  = excluded.evaluation_id,
                    file_id        = excluded.file_id
                """,
                (key, file_name, ocr_json, now, now, len(ocr_json), evaluation_id, file_id),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Sheet cache OCR write error: {e}")
            raise
        finally:
            conn.close()

    def _upsert_sheet_eval_sync(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        answer_key_hash: str,
    ) -> None:
        key = sheet_cache_key(evaluation_id, file_id)
        ocr_json = json.dumps(ocr_result)
        eval_json = json.dumps(evaluation_result)
        size = len(ocr_json) + len(eval_json)
        now = time.time()
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute(
                """
                INSERT INTO result_cache
                    (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash,
                     created_at, last_accessed, access_count, result_size,
                     evaluation_id, file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(file_hash) DO UPDATE SET
                    file_name         = excluded.file_name,
                    ocr_result        = excluded.ocr_result,
                    evaluation_result = excluded.evaluation_result,
                    answer_key_hash   = excluded.answer_key_hash,
                    last_accessed     = excluded.last_accessed,
                    access_count      = result_cache.access_count + 1,
                    result_size       = excluded.result_size,
                    evaluation_id     = excluded.evaluation_id,
                    file_id           = excluded.file_id
                """,
                (
                    key,
                    file_name,
                    ocr_json,
                    eval_json,
                    answer_key_hash,
                    now,
                    now,
                    size,
                    evaluation_id,
                    file_id,
                ),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Sheet cache EVAL write error: {e}")
            raise
        finally:
            conn.close()

    def _purge_evaluation_sync(self, evaluation_id: str) -> int:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute("DELETE FROM result_cache WHERE evaluation_id = ?", (evaluation_id,))
            conn.commit()
            return c.rowcount or 0
        finally:
            conn.close()

    def _purge_stale_for_evaluation_sync(
        self, evaluation_id: str, current_answer_key_hash: str
    ) -> int:
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        try:
            c.execute(
                """
                DELETE FROM result_cache
                 WHERE evaluation_id = ?
                   AND answer_key_hash IS NOT NULL
                   AND answer_key_hash != ?
                """,
                (evaluation_id, current_answer_key_hash),
            )
            conn.commit()
            return c.rowcount or 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Supabase (Postgres) driver
# ---------------------------------------------------------------------------

class _SupabaseCacheDriver:
    """Supabase Postgres-backed cache driver using asyncpg."""

    def __init__(self, max_cache_size_bytes: int):
        self.max_cache_size_bytes = max_cache_size_bytes
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()
        print("✅ Result cache initialised (supabase)")

    async def _pool(self):
        from services.supabase_client import get_pool
        return await get_pool()

    async def _ensure_schema(self) -> None:
        """Create table/indexes if missing. Safe to call repeatedly."""
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            pool = await self._pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.result_cache (
                        file_hash         text PRIMARY KEY,
                        file_name         text NOT NULL,
                        ocr_result        jsonb NOT NULL,
                        evaluation_result jsonb,
                        answer_key_hash   text,
                        created_at        timestamptz NOT NULL DEFAULT now(),
                        last_accessed     timestamptz NOT NULL DEFAULT now(),
                        access_count      integer NOT NULL DEFAULT 0,
                        result_size       integer NOT NULL DEFAULT 0
                    );
                    """
                )
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_result_cache_answer_key_hash ON public.result_cache(answer_key_hash);")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_result_cache_last_accessed ON public.result_cache(last_accessed);")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_result_cache_created_at ON public.result_cache(created_at);")
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_result_cache_eval_only ON public.result_cache(file_name) WHERE file_name = '__eval__';"
                )
                # Per-evaluation scoping (migration 002) — idempotent.
                await conn.execute("ALTER TABLE public.result_cache ADD COLUMN IF NOT EXISTS evaluation_id text;")
                await conn.execute("ALTER TABLE public.result_cache ADD COLUMN IF NOT EXISTS file_id text;")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_result_cache_evaluation_id ON public.result_cache(evaluation_id);")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_result_cache_eval_file ON public.result_cache(evaluation_id, file_id);")
            self._schema_ready = True

    @staticmethod
    def _loads(value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return None

    async def get_cached_result(self, file_hash: str, result_type: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    UPDATE public.result_cache
                       SET last_accessed = now(),
                           access_count  = access_count + 1
                     WHERE file_hash = $1
                    RETURNING ocr_result, evaluation_result
                    """,
                    file_hash,
                )
            if not row:
                return None
            if result_type == "ocr":
                return self._loads(row["ocr_result"])
            if result_type == "evaluation":
                return self._loads(row["evaluation_result"])
            return None
        except Exception as e:
            print(f"Cache lookup error (supabase): {e}")
            return None

    async def get_cached_evaluation(self, file_hash: str, answer_key_hash: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    UPDATE public.result_cache
                       SET last_accessed = now(),
                           access_count  = access_count + 1
                     WHERE file_hash = $1
                       AND answer_key_hash = $2
                       AND evaluation_result IS NOT NULL
                    RETURNING evaluation_result
                    """,
                    file_hash,
                    answer_key_hash,
                )
            if not row:
                return None
            return self._loads(row["evaluation_result"])
        except Exception as e:
            print(f"Evaluation cache lookup error (supabase): {e}")
            return None

    async def cache_result(
        self,
        file_hash: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Optional[Dict[str, Any]],
        answer_key_hash: Optional[str],
    ) -> None:
        await self._ensure_schema()
        ocr_json = json.dumps(ocr_result)
        eval_json = json.dumps(evaluation_result) if evaluation_result else None
        result_size = len(ocr_json) + (len(eval_json) if eval_json else 0)
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.result_cache
                        (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash,
                         created_at, last_accessed, access_count, result_size)
                    VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, now(), now(), 1, $6)
                    ON CONFLICT (file_hash) DO UPDATE SET
                        file_name         = EXCLUDED.file_name,
                        ocr_result        = EXCLUDED.ocr_result,
                        evaluation_result = EXCLUDED.evaluation_result,
                        answer_key_hash   = EXCLUDED.answer_key_hash,
                        last_accessed     = now(),
                        access_count      = public.result_cache.access_count + 1,
                        result_size       = EXCLUDED.result_size
                    """,
                    file_hash,
                    file_name,
                    ocr_json,
                    eval_json,
                    answer_key_hash,
                    result_size,
                )
        except Exception as e:
            print(f"Cache write error (supabase): {e}")
            raise

    async def cleanup(self, max_age_days: int, force_cleanup: bool) -> None:
        await self._ensure_schema()
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                current_size = await conn.fetchval("SELECT COALESCE(SUM(result_size), 0) FROM public.result_cache")
                cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
                if current_size <= self.max_cache_size_bytes and not force_cleanup:
                    return
                old_deleted = await conn.fetchval(
                    """
                    WITH d AS (
                        DELETE FROM public.result_cache WHERE created_at < $1 RETURNING 1
                    )
                    SELECT COUNT(*) FROM d
                    """,
                    cutoff,
                )
                lru_deleted = 0
                if current_size > self.max_cache_size_bytes:
                    total = await conn.fetchval("SELECT COUNT(*) FROM public.result_cache")
                    limit = max(1, (total or 0) // 4)
                    lru_deleted = await conn.fetchval(
                        """
                        WITH victims AS (
                            SELECT file_hash FROM public.result_cache
                            ORDER BY last_accessed ASC
                            LIMIT $1
                        ), d AS (
                            DELETE FROM public.result_cache r
                             USING victims v
                             WHERE r.file_hash = v.file_hash
                         RETURNING 1
                        )
                        SELECT COUNT(*) FROM d
                        """,
                        limit,
                    )
                new_size = await conn.fetchval("SELECT COALESCE(SUM(result_size), 0) FROM public.result_cache")
                print("🧹 Cache cleanup completed (supabase):")
                print(f"   Removed {old_deleted} old entries, {lru_deleted} LRU entries")
                print(f"   Size: {current_size/1024/1024:.1f}MB → {new_size/1024/1024:.1f}MB")
        except Exception as e:
            print(f"Cache cleanup error (supabase): {e}")

    async def stats(self) -> Dict[str, Any]:
        await self._ensure_schema()
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS c, COALESCE(SUM(result_size), 0) AS s, COALESCE(AVG(access_count), 0) AS a FROM public.result_cache"
                )
                recent = await conn.fetchval(
                    "SELECT COUNT(*) FROM public.result_cache WHERE last_accessed > now() - interval '24 hours'"
                )
                dist_rows = await conn.fetch(
                    "SELECT answer_key_hash, COUNT(*) FROM public.result_cache GROUP BY answer_key_hash"
                )
            count = row["c"] or 0
            return {
                "total_entries": count,
                "total_size_mb": (row["s"] or 0) / 1024 / 1024,
                "average_access_count": float(row["a"] or 0),
                "recent_access_24h": recent or 0,
                "answer_key_distribution": {r[0]: r[1] for r in dist_rows},
                "cache_hit_potential": f"{min(100, count * 2)}%",
            }
        except Exception as e:
            print(f"Cache stats error (supabase): {e}")
            return {}

    async def stats_for_evaluation(self, evaluation_id: str) -> Dict[str, Any]:
        await self._ensure_schema()
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM public.result_cache
                     WHERE evaluation_id = $1
                        OR (evaluation_id IS NULL AND (
                              file_hash LIKE 'sheet:v2:' || $1 || ':%'
                           OR file_hash LIKE 'ocr:' || $1 || ':%'
                           ))
                    """,
                    evaluation_id,
                )
                scored = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM public.result_cache
                     WHERE (evaluation_id = $1
                        OR (evaluation_id IS NULL AND (
                              file_hash LIKE 'sheet:v2:' || $1 || ':%'
                           OR file_hash LIKE 'ocr:' || $1 || ':%'
                           )))
                       AND evaluation_result IS NOT NULL
                    """,
                    evaluation_id,
                )
            return {
                "evaluation_entries": int(total or 0),
                "evaluation_fully_scored": int(scored or 0),
            }
        except Exception as e:
            print(f"Per-evaluation cache stats error (supabase): {e}")
            return {"evaluation_entries": 0, "evaluation_fully_scored": 0}

    async def purge_stale_eval_entries(self) -> Tuple[int, int]:
        await self._ensure_schema()
        pool = await self._pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM public.result_cache WHERE file_name = '__eval__'"
            )
            purged = await conn.fetchval(
                """
                WITH d AS (
                    DELETE FROM public.result_cache
                     WHERE file_name = '__eval__'
                       AND NOT (ocr_result ? '_answer_key_hash')
                 RETURNING 1
                )
                SELECT COUNT(*) FROM d
                """
            )
            return int(purged or 0), int(total or 0)

    # ---- new single-row sheet cache API (scoped by evaluation_id + file_id) ----

    async def get_sheet_cache(self, evaluation_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        key = sheet_cache_key(evaluation_id, file_id)
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    UPDATE public.result_cache
                       SET last_accessed = now(),
                           access_count  = access_count + 1
                     WHERE file_hash = $1
                    RETURNING ocr_result, evaluation_result, answer_key_hash, file_name
                    """,
                    key,
                )
            if not row:
                return None
            return {
                "ocr_result": self._loads(row["ocr_result"]),
                "evaluation_result": self._loads(row["evaluation_result"]),
                "answer_key_hash": row["answer_key_hash"],
                "file_name": row["file_name"],
            }
        except Exception as e:
            print(f"Sheet cache lookup error (supabase): {e}")
            return None

    async def upsert_sheet_ocr(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
    ) -> None:
        await self._ensure_schema()
        key = sheet_cache_key(evaluation_id, file_id)
        ocr_json = json.dumps(ocr_result)
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.result_cache
                        (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash,
                         created_at, last_accessed, access_count, result_size,
                         evaluation_id, file_id)
                    VALUES ($1, $2, $3::jsonb, NULL, NULL, now(), now(), 1, $4, $5, $6)
                    ON CONFLICT (file_hash) DO UPDATE SET
                        file_name     = EXCLUDED.file_name,
                        ocr_result    = EXCLUDED.ocr_result,
                        last_accessed = now(),
                        access_count  = public.result_cache.access_count + 1,
                        result_size   = length(EXCLUDED.ocr_result::text) +
                                        COALESCE(length(public.result_cache.evaluation_result::text), 0),
                        evaluation_id = EXCLUDED.evaluation_id,
                        file_id       = EXCLUDED.file_id
                    """,
                    key,
                    file_name,
                    ocr_json,
                    len(ocr_json),
                    evaluation_id,
                    file_id,
                )
        except Exception as e:
            print(f"Sheet cache OCR write error (supabase): {e}")
            raise

    async def upsert_sheet_evaluation(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        answer_key_hash: str,
    ) -> None:
        await self._ensure_schema()
        key = sheet_cache_key(evaluation_id, file_id)
        ocr_json = json.dumps(ocr_result)
        eval_json = json.dumps(evaluation_result)
        size = len(ocr_json) + len(eval_json)
        pool = await self._pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.result_cache
                        (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash,
                         created_at, last_accessed, access_count, result_size,
                         evaluation_id, file_id)
                    VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, now(), now(), 1, $6, $7, $8)
                    ON CONFLICT (file_hash) DO UPDATE SET
                        file_name         = EXCLUDED.file_name,
                        ocr_result        = EXCLUDED.ocr_result,
                        evaluation_result = EXCLUDED.evaluation_result,
                        answer_key_hash   = EXCLUDED.answer_key_hash,
                        last_accessed     = now(),
                        access_count      = public.result_cache.access_count + 1,
                        result_size       = EXCLUDED.result_size,
                        evaluation_id     = EXCLUDED.evaluation_id,
                        file_id           = EXCLUDED.file_id
                    """,
                    key,
                    file_name,
                    ocr_json,
                    eval_json,
                    answer_key_hash,
                    size,
                    evaluation_id,
                    file_id,
                )
        except Exception as e:
            print(f"Sheet cache EVAL write error (supabase): {e}")
            raise

    async def purge_evaluation(self, evaluation_id: str) -> int:
        await self._ensure_schema()
        pool = await self._pool()
        async with pool.acquire() as conn:
            purged = await conn.fetchval(
                """
                WITH d AS (
                    DELETE FROM public.result_cache
                     WHERE evaluation_id = $1
                 RETURNING 1
                )
                SELECT COUNT(*) FROM d
                """,
                evaluation_id,
            )
        return int(purged or 0)

    async def purge_stale_for_evaluation(
        self, evaluation_id: str, current_answer_key_hash: str
    ) -> int:
        await self._ensure_schema()
        pool = await self._pool()
        async with pool.acquire() as conn:
            purged = await conn.fetchval(
                """
                WITH d AS (
                    DELETE FROM public.result_cache
                     WHERE evaluation_id = $1
                       AND answer_key_hash IS NOT NULL
                       AND answer_key_hash <> $2
                 RETURNING 1
                )
                SELECT COUNT(*) FROM d
                """,
                evaluation_id,
                current_answer_key_hash,
            )
        return int(purged or 0)


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class ResultCacheService:
    """
    High-performance caching service for OCR and evaluation results.
    Delegates storage to a pluggable driver (SQLite or Supabase).
    """

    def __init__(self, cache_db_path: str = "result_cache.db", max_cache_size_mb: int = 500):
        self.cache_db_path = cache_db_path
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        self.executor = ThreadPoolExecutor(max_workers=4)

        backend = os.getenv("CACHE_BACKEND", "sqlite").strip().lower()
        if backend == "supabase":
            self.backend = "supabase"
            self._driver: Any = _SupabaseCacheDriver(self.max_cache_size_bytes)
        else:
            self.backend = "sqlite"
            self._driver = _SqliteCacheDriver(
                cache_db_path=self.cache_db_path,
                max_cache_size_bytes=self.max_cache_size_bytes,
                executor=self.executor,
            )

    def __del__(self):
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)

    # ---- hashing helpers (unchanged public API) ----

    async def get_file_hash(self, file_path: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, _calculate_file_hash_sync, file_path)

    def get_answer_key_hash(self, answer_key: Dict) -> str:
        return _calculate_answer_key_hash(answer_key)

    # ---- OCR cache ----

    async def get_cached_ocr_result(self, file_path: str, file_hash: str = None) -> Optional[Dict[str, Any]]:
        try:
            computed_hash = file_hash if file_hash else await self.get_file_hash(file_path)
            return await self._driver.get_cached_result(computed_hash, "ocr")
        except Exception as e:
            print(f"⚠️  Cache lookup failed for {file_path}: {e}")
            return None

    async def cache_ocr_result(self, file_path: str, ocr_result: Dict[str, Any], file_hash: str = None):
        try:
            computed_hash = file_hash if file_hash else await self.get_file_hash(file_path)
            file_name = os.path.basename(file_path)
            await self._driver.cache_result(computed_hash, file_name, ocr_result, None, None)
        except Exception as e:
            print(f"⚠️  Failed to cache OCR result for {file_path}: {e}")

    # ---- Evaluation cache ----

    async def get_cached_evaluation_result(
        self, file_path: str, answer_key: Dict
    ) -> Optional[Dict[str, Any]]:
        try:
            file_hash = await self.get_file_hash(file_path)
            answer_key_hash = self.get_answer_key_hash(answer_key)
            return await self._driver.get_cached_evaluation(file_hash, answer_key_hash)
        except Exception as e:
            print(f"⚠️  Evaluation cache lookup failed for {file_path}: {e}")
            return None

    async def cache_evaluation_result(
        self,
        file_path: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        answer_key: Dict,
    ):
        try:
            file_hash = await self.get_file_hash(file_path)
            file_name = os.path.basename(file_path)
            answer_key_hash = self.get_answer_key_hash(answer_key)
            await self._driver.cache_result(
                file_hash, file_name, ocr_result, evaluation_result, answer_key_hash
            )
        except Exception as e:
            print(f"⚠️  Failed to cache evaluation result for {file_path}: {e}")

    # ---- Maintenance ----

    async def cleanup_cache(self, max_age_days: int = 30, force_cleanup: bool = False):
        await self._driver.cleanup(max_age_days, force_cleanup)

    async def get_cache_stats(self) -> Dict[str, Any]:
        return await self._driver.stats()

    async def get_cache_stats_for_evaluation(self, evaluation_id: str) -> Dict[str, Any]:
        """Row counts scoped to one evaluation (see driver docstring)."""
        if not evaluation_id or not str(evaluation_id).strip():
            return {"evaluation_entries": 0, "evaluation_fully_scored": 0}
        return await self._driver.stats_for_evaluation(str(evaluation_id).strip())

    async def purge_stale_eval_entries(self) -> Tuple[int, int]:
        """
        Delete __eval__ cache entries that were written before answer-key-hash
        tracking was added (no `_answer_key_hash` in payload).
        Returns (purged, total_before).
        """
        return await self._driver.purge_stale_eval_entries()

    # ---- single-row sheet cache (evaluation_id + file_id) ----

    async def get_sheet_cache(self, evaluation_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Return the single cache row for a (evaluation_id, file_id) pair, or None.

        The returned dict has keys:
            - ocr_result:        Dict or None
            - evaluation_result: Dict or None
            - answer_key_hash:   str or None   (None until scoring cached)
            - file_name:         str
        """
        try:
            return await self._driver.get_sheet_cache(evaluation_id, file_id)
        except Exception as e:
            print(f"⚠️  Sheet cache lookup failed for eval={evaluation_id} file={file_id}: {e}")
            return None

    async def upsert_sheet_ocr(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
    ) -> None:
        """Write/refresh the OCR portion of a sheet row, leaving any existing
        evaluation_result untouched in DB semantics (we overwrite ocr_result
        and keep evaluation_result via the column-level UPDATE)."""
        try:
            await self._driver.upsert_sheet_ocr(evaluation_id, file_id, file_name, ocr_result)
        except Exception as e:
            print(f"⚠️  Sheet OCR cache write failed for eval={evaluation_id} file={file_id}: {e}")

    async def upsert_sheet_evaluation(
        self,
        evaluation_id: str,
        file_id: str,
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        answer_key_hash: str,
    ) -> None:
        """Write the fully scored result AND the OCR side-by-side in one row."""
        try:
            await self._driver.upsert_sheet_evaluation(
                evaluation_id, file_id, file_name, ocr_result, evaluation_result, answer_key_hash
            )
        except Exception as e:
            print(f"⚠️  Sheet eval cache write failed for eval={evaluation_id} file={file_id}: {e}")

    async def purge_evaluation(self, evaluation_id: str) -> int:
        """Delete every cache row for a single evaluation. Returns rows removed."""
        try:
            return await self._driver.purge_evaluation(evaluation_id)
        except Exception as e:
            print(f"⚠️  Purge evaluation failed for {evaluation_id}: {e}")
            return 0

    async def purge_stale_for_evaluation(
        self, evaluation_id: str, current_answer_key_hash: str
    ) -> int:
        """
        Delete rows in an evaluation whose cached answer_key_hash differs
        from the one we're about to use. Keeps OCR-only rows (hash IS NULL).
        """
        try:
            return await self._driver.purge_stale_for_evaluation(
                evaluation_id, current_answer_key_hash
            )
        except Exception as e:
            print(f"⚠️  Purge-stale for eval={evaluation_id} failed: {e}")
            return 0


# ---------------------------------------------------------------------------
# Convenience wrappers (unchanged behaviour)
# ---------------------------------------------------------------------------

async def get_cached_or_process_ocr(
    file_path: str,
    ocr_processor_func,
    cache_service: ResultCacheService = None,
) -> Dict[str, Any]:
    cache = cache_service or ResultCacheService()
    cached_result = await cache.get_cached_ocr_result(file_path)
    if cached_result:
        print(f"🎯 Cache hit for OCR: {os.path.basename(file_path)}")
        return cached_result
    print(f"🔄 Processing OCR: {os.path.basename(file_path)}")
    result = await ocr_processor_func(file_path)
    await cache.cache_ocr_result(file_path, result)
    return result


async def get_cached_or_evaluate(
    file_path: str,
    ocr_result: Dict[str, Any],
    answer_key: Dict,
    evaluation_func,
    cache_service: ResultCacheService = None,
) -> Dict[str, Any]:
    cache = cache_service or ResultCacheService()
    cached_result = await cache.get_cached_evaluation_result(file_path, answer_key)
    if cached_result:
        print(f"🎯 Cache hit for evaluation: {os.path.basename(file_path)}")
        return cached_result
    print(f"🔄 Evaluating: {os.path.basename(file_path)}")
    result = await evaluation_func(ocr_result, answer_key)
    await cache.cache_evaluation_result(file_path, ocr_result, result, answer_key)
    return result
