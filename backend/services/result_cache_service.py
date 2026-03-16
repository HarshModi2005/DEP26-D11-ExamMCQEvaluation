"""
Result Cache Service
===================
Caches OCR results and evaluation outcomes to avoid reprocessing.
Uses file hashing and intelligent cache invalidation.
"""

import hashlib
import json
import os
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor


@dataclass
class CacheEntry:
    file_hash: str
    file_name: str
    ocr_result: Dict[str, Any]
    evaluation_result: Optional[Dict[str, Any]]
    answer_key_hash: str
    created_at: float
    last_accessed: float
    access_count: int = 0


class ResultCacheService:
    """
    High-performance caching service for OCR and evaluation results.
    Reduces redundant processing by caching based on file content hashes.
    """
    
    def __init__(self, cache_db_path: str = "result_cache.db", max_cache_size_mb: int = 500):
        self.cache_db_path = cache_db_path
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._init_cache_db()
        
    def __del__(self):
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def _init_cache_db(self):
        """Initialize the cache database with optimized schema."""
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        
        # Create cache table with indexes for performance
        c.execute('''
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
        ''')
        
        # Create indexes for faster lookups
        c.execute('CREATE INDEX IF NOT EXISTS idx_answer_key_hash ON result_cache(answer_key_hash)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_last_accessed ON result_cache(last_accessed)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON result_cache(created_at)')
        
        conn.commit()
        conn.close()
        print(f"✅ Result cache initialized at {self.cache_db_path}")

    async def get_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA-256 hash of file content for cache key.
        Uses async execution to avoid blocking.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._calculate_file_hash, file_path)

    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate file hash synchronously."""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files efficiently
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_answer_key_hash(self, answer_key: Dict) -> str:
        """Generate hash for answer key to detect changes."""
        # Create a stable hash from answer key content
        key_content = json.dumps(answer_key, sort_keys=True)
        return hashlib.sha256(key_content.encode()).hexdigest()

    async def get_cached_ocr_result(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached OCR result if available.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Cached OCR result or None if not found/expired
        """
        try:
            file_hash = await self.get_file_hash(file_path)
            loop = asyncio.get_event_loop()
            
            return await loop.run_in_executor(
                self.executor,
                self._get_cached_result_sync,
                file_hash,
                'ocr'
            )
        except Exception as e:
            print(f"⚠️  Cache lookup failed for {file_path}: {e}")
            return None

    async def get_cached_evaluation_result(
        self, 
        file_path: str, 
        answer_key: Dict
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached evaluation result if available and answer key matches.
        
        Args:
            file_path: Path to the image file
            answer_key: Current answer key for validation
            
        Returns:
            Cached evaluation result or None if not found/invalid
        """
        try:
            file_hash = await self.get_file_hash(file_path)
            answer_key_hash = self.get_answer_key_hash(answer_key)
            loop = asyncio.get_event_loop()
            
            return await loop.run_in_executor(
                self.executor,
                self._get_cached_evaluation_sync,
                file_hash,
                answer_key_hash
            )
        except Exception as e:
            print(f"⚠️  Evaluation cache lookup failed for {file_path}: {e}")
            return None

    def _get_cached_result_sync(self, file_hash: str, result_type: str) -> Optional[Dict[str, Any]]:
        """Synchronous cache lookup."""
        conn = sqlite3.connect(self.cache_db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT * FROM result_cache WHERE file_hash = ?",
                (file_hash,)
            )
            row = c.fetchone()
            
            if row:
                # Update access statistics
                c.execute(
                    "UPDATE result_cache SET last_accessed = ?, access_count = access_count + 1 WHERE file_hash = ?",
                    (time.time(), file_hash)
                )
                conn.commit()
                
                # Return requested result type
                if result_type == 'ocr':
                    return json.loads(row['ocr_result'])
                elif result_type == 'evaluation' and row['evaluation_result']:
                    return json.loads(row['evaluation_result'])
            
            return None
            
        except Exception as e:
            print(f"Cache lookup error: {e}")
            return None
        finally:
            conn.close()

    def _get_cached_evaluation_sync(self, file_hash: str, answer_key_hash: str) -> Optional[Dict[str, Any]]:
        """Synchronous evaluation cache lookup with answer key validation."""
        conn = sqlite3.connect(self.cache_db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        try:
            c.execute(
                "SELECT * FROM result_cache WHERE file_hash = ? AND answer_key_hash = ?",
                (file_hash, answer_key_hash)
            )
            row = c.fetchone()
            
            if row and row['evaluation_result']:
                # Update access statistics
                c.execute(
                    "UPDATE result_cache SET last_accessed = ?, access_count = access_count + 1 WHERE file_hash = ?",
                    (time.time(), file_hash)
                )
                conn.commit()
                
                return json.loads(row['evaluation_result'])
            
            return None
            
        except Exception as e:
            print(f"Evaluation cache lookup error: {e}")
            return None
        finally:
            conn.close()

    async def cache_ocr_result(self, file_path: str, ocr_result: Dict[str, Any]):
        """
        Cache OCR result for future use.
        
        Args:
            file_path: Path to the processed image file
            ocr_result: OCR extraction result to cache
        """
        try:
            file_hash = await self.get_file_hash(file_path)
            file_name = os.path.basename(file_path)
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                self._cache_result_sync,
                file_hash,
                file_name,
                ocr_result,
                None,  # No evaluation result yet
                None   # No answer key hash yet
            )
        except Exception as e:
            print(f"⚠️  Failed to cache OCR result for {file_path}: {e}")

    async def cache_evaluation_result(
        self, 
        file_path: str, 
        ocr_result: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        answer_key: Dict
    ):
        """
        Cache both OCR and evaluation results.
        
        Args:
            file_path: Path to the processed image file
            ocr_result: OCR extraction result
            evaluation_result: Evaluation/scoring result
            answer_key: Answer key used for evaluation
        """
        try:
            file_hash = await self.get_file_hash(file_path)
            file_name = os.path.basename(file_path)
            answer_key_hash = self.get_answer_key_hash(answer_key)
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                self._cache_result_sync,
                file_hash,
                file_name,
                ocr_result,
                evaluation_result,
                answer_key_hash
            )
        except Exception as e:
            print(f"⚠️  Failed to cache evaluation result for {file_path}: {e}")

    def _cache_result_sync(
        self, 
        file_hash: str, 
        file_name: str,
        ocr_result: Dict[str, Any],
        evaluation_result: Optional[Dict[str, Any]],
        answer_key_hash: Optional[str]
    ):
        """Synchronous cache write operation."""
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        
        try:
            ocr_json = json.dumps(ocr_result)
            eval_json = json.dumps(evaluation_result) if evaluation_result else None
            result_size = len(ocr_json) + (len(eval_json) if eval_json else 0)
            current_time = time.time()
            
            c.execute('''
                INSERT OR REPLACE INTO result_cache 
                (file_hash, file_name, ocr_result, evaluation_result, answer_key_hash, 
                 created_at, last_accessed, access_count, result_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            ''', (
                file_hash, file_name, ocr_json, eval_json, answer_key_hash,
                current_time, current_time, result_size
            ))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(f"Cache write error: {e}")
            raise
        finally:
            conn.close()

    async def cleanup_cache(self, max_age_days: int = 30, force_cleanup: bool = False):
        """
        Clean up old cache entries to manage storage space.
        
        Args:
            max_age_days: Remove entries older than this many days
            force_cleanup: Force cleanup even if under size limit
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._cleanup_cache_sync,
            max_age_days,
            force_cleanup
        )

    def _cleanup_cache_sync(self, max_age_days: int, force_cleanup: bool):
        """Synchronous cache cleanup."""
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        
        try:
            # Check current cache size
            c.execute("SELECT SUM(result_size) FROM result_cache")
            current_size = c.fetchone()[0] or 0
            
            cutoff_time = time.time() - (max_age_days * 24 * 3600)
            
            if current_size > self.max_cache_size_bytes or force_cleanup:
                # Remove old entries first
                c.execute("DELETE FROM result_cache WHERE created_at < ?", (cutoff_time,))
                old_deleted = c.rowcount
                
                # If still over limit, remove least recently accessed
                if current_size > self.max_cache_size_bytes:
                    c.execute("""
                        DELETE FROM result_cache 
                        WHERE file_hash IN (
                            SELECT file_hash FROM result_cache 
                            ORDER BY last_accessed ASC 
                            LIMIT (SELECT COUNT(*) / 4 FROM result_cache)
                        )
                    """)
                    lru_deleted = c.rowcount
                else:
                    lru_deleted = 0
                
                conn.commit()
                
                # Get new size
                c.execute("SELECT SUM(result_size) FROM result_cache")
                new_size = c.fetchone()[0] or 0
                
                print(f"🧹 Cache cleanup completed:")
                print(f"   Removed {old_deleted} old entries, {lru_deleted} LRU entries")
                print(f"   Size: {current_size/1024/1024:.1f}MB → {new_size/1024/1024:.1f}MB")
            
        except Exception as e:
            conn.rollback()
            print(f"Cache cleanup error: {e}")
        finally:
            conn.close()

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_cache_stats_sync)

    def _get_cache_stats_sync(self) -> Dict[str, Any]:
        """Synchronous cache statistics."""
        conn = sqlite3.connect(self.cache_db_path)
        c = conn.cursor()
        
        try:
            # Basic stats
            c.execute("SELECT COUNT(*), SUM(result_size), AVG(access_count) FROM result_cache")
            count, total_size, avg_access = c.fetchone()
            
            # Recent activity
            recent_cutoff = time.time() - (24 * 3600)  # Last 24 hours
            c.execute("SELECT COUNT(*) FROM result_cache WHERE last_accessed > ?", (recent_cutoff,))
            recent_access = c.fetchone()[0]
            
            # Answer key distribution
            c.execute("SELECT answer_key_hash, COUNT(*) FROM result_cache GROUP BY answer_key_hash")
            key_distribution = dict(c.fetchall())
            
            return {
                'total_entries': count or 0,
                'total_size_mb': (total_size or 0) / 1024 / 1024,
                'average_access_count': avg_access or 0,
                'recent_access_24h': recent_access or 0,
                'answer_key_distribution': key_distribution,
                'cache_hit_potential': f"{min(100, (count or 0) * 2)}%"  # Rough estimate
            }
            
        except Exception as e:
            print(f"Cache stats error: {e}")
            return {}
        finally:
            conn.close()


# Convenience functions for easy integration
async def get_cached_or_process_ocr(
    file_path: str, 
    ocr_processor_func,
    cache_service: ResultCacheService = None
) -> Dict[str, Any]:
    """
    Get cached OCR result or process if not cached.
    
    Args:
        file_path: Path to image file
        ocr_processor_func: Function to call if not cached
        cache_service: Cache service instance
        
    Returns:
        OCR result (from cache or fresh processing)
    """
    cache = cache_service or ResultCacheService()
    
    # Try cache first
    cached_result = await cache.get_cached_ocr_result(file_path)
    if cached_result:
        print(f"🎯 Cache hit for OCR: {os.path.basename(file_path)}")
        return cached_result
    
    # Process and cache
    print(f"🔄 Processing OCR: {os.path.basename(file_path)}")
    result = await ocr_processor_func(file_path)
    await cache.cache_ocr_result(file_path, result)
    
    return result


async def get_cached_or_evaluate(
    file_path: str,
    ocr_result: Dict[str, Any],
    answer_key: Dict,
    evaluation_func,
    cache_service: ResultCacheService = None
) -> Dict[str, Any]:
    """
    Get cached evaluation result or evaluate if not cached.
    
    Args:
        file_path: Path to image file
        ocr_result: OCR result for the file
        answer_key: Answer key for evaluation
        evaluation_func: Function to call if not cached
        cache_service: Cache service instance
        
    Returns:
        Evaluation result (from cache or fresh evaluation)
    """
    cache = cache_service or ResultCacheService()
    
    # Try cache first
    cached_result = await cache.get_cached_evaluation_result(file_path, answer_key)
    if cached_result:
        print(f"🎯 Cache hit for evaluation: {os.path.basename(file_path)}")
        return cached_result
    
    # Evaluate and cache
    print(f"🔄 Evaluating: {os.path.basename(file_path)}")
    result = await evaluation_func(ocr_result, answer_key)
    await cache.cache_evaluation_result(file_path, ocr_result, result, answer_key)
    
    return result