"""
Optimized Database Service
=========================
High-performance database operations with connection pooling,
batch operations, and async support.
"""

import sqlite3
import json
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Queue, Empty
import threading
from models import Student, Submission, EvaluationResult, StudentResult


@dataclass
class DatabaseStats:
    total_operations: int
    batch_operations: int
    avg_operation_time: float
    connection_pool_hits: int
    connection_pool_misses: int


class ConnectionPool:
    """
    Thread-safe SQLite connection pool for better performance.
    """
    
    def __init__(self, db_path: str, pool_size: int = 10):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool = Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        
        # Pre-populate pool
        for _ in range(pool_size):
            conn = self._create_connection()
            self._pool.put(conn)
    
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimizations."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False
        )
        
        # SQLite performance optimizations
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
        conn.execute("PRAGMA synchronous=NORMAL")  # Faster than FULL
        conn.execute("PRAGMA cache_size=10000")  # 10MB cache
        conn.execute("PRAGMA temp_store=MEMORY")  # Use memory for temp tables
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory mapping
        
        return conn
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        conn = None
        try:
            # Try to get from pool
            try:
                conn = self._pool.get_nowait()
                with self._lock:
                    self._hits += 1
            except Empty:
                # Pool exhausted, create new connection
                conn = self._create_connection()
                with self._lock:
                    self._misses += 1
            
            yield conn
            
        finally:
            if conn:
                try:
                    # Return to pool if space available
                    self._pool.put_nowait(conn)
                except:
                    # Pool full, close connection
                    conn.close()
    
    def get_stats(self) -> Tuple[int, int]:
        """Get pool hit/miss statistics."""
        with self._lock:
            return self._hits, self._misses
    
    def close_all(self):
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break


class OptimizedDatabaseService:
    """
    High-performance database service with connection pooling,
    batch operations, and async support.
    """
    
    def __init__(self, db_path: str = "evaluation.db", pool_size: int = 10):
        self.db_path = db_path
        self.pool = ConnectionPool(db_path, pool_size)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.stats = DatabaseStats(0, 0, 0.0, 0, 0)
        self._init_db()
    
    def __del__(self):
        if hasattr(self, 'pool'):
            self.pool.close_all()
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
    
    def _init_db(self):
        """Initialize database with optimized schema and indexes."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            
            # Create tables with optimized schema
            c.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    roll_number TEXT NOT NULL,
                    created_at REAL DEFAULT (julianday('now')),
                    updated_at REAL DEFAULT (julianday('now'))
                )
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    exam_id TEXT NOT NULL,
                    file_id TEXT,
                    status TEXT NOT NULL,
                    extracted_data TEXT,
                    created_at REAL DEFAULT (julianday('now')),
                    updated_at REAL DEFAULT (julianday('now')),
                    FOREIGN KEY (student_id) REFERENCES students (id)
                )
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    submission_id TEXT PRIMARY KEY,
                    score REAL NOT NULL,
                    feedback TEXT,
                    details TEXT,
                    created_at REAL DEFAULT (julianday('now')),
                    updated_at REAL DEFAULT (julianday('now')),
                    FOREIGN KEY (submission_id) REFERENCES submissions (id)
                )
            ''')

            # Pipeline run tracking (for resume/benchmarking)
            c.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,        -- 'drive' | 'zip' | 'manual'
                    source_ref TEXT,                  -- drive folder url/id, zip filename, etc.
                    status TEXT NOT NULL,             -- 'running' | 'completed' | 'failed'
                    total_files INTEGER DEFAULT 0,
                    processed_files INTEGER DEFAULT 0,
                    cache_hits INTEGER DEFAULT 0,
                    errors TEXT,                      -- JSON
                    started_at REAL DEFAULT (julianday('now')),
                    updated_at REAL DEFAULT (julianday('now'))
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_run_items (
                    run_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_hash TEXT,
                    status TEXT NOT NULL,             -- 'processed' | 'cached' | 'error'
                    entry_number TEXT,
                    ocr_json TEXT,                    -- raw OCR output (entry_number, name, answers, comments)
                    result_json TEXT,                 -- JSON StudentResult (score, details, etc.)
                    error TEXT,                       -- error string (optional)
                    created_at REAL DEFAULT (julianday('now')),
                    PRIMARY KEY (run_id, file_name)
                )
            ''')

            # PDF page → student mapping (populated only for source_type='pdf' runs).
            # Lets the UI jump from a page number to the scored student (and vice-versa)
            # without scanning all pipeline_run_items.
            c.execute('''
                CREATE TABLE IF NOT EXISTS pdf_page_map (
                    run_id TEXT NOT NULL,
                    pdf_hash TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    page_index INTEGER NOT NULL,
                    file_id TEXT,
                    file_name TEXT,
                    entry_number TEXT,
                    name TEXT,
                    status TEXT NOT NULL,             -- 'processed' | 'error' | 'unresolved'
                    total_score REAL,
                    max_score REAL,
                    created_at REAL DEFAULT (julianday('now')),
                    PRIMARY KEY (run_id, page_number)
                )
            ''')

            # If the DB already existed with an older schema, CREATE TABLE IF NOT EXISTS
            # will not add new columns. Ensure required columns exist before indexing.
            self._ensure_schema(conn)
            
            # Create performance indexes
            c.execute('CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll_number)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_exam ON submissions(exam_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_results_score ON results(score)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON students(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_created_at ON submissions(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_pipeline_runs_updated ON pipeline_runs(updated_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_pipeline_items_status ON pipeline_run_items(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_pdf_page_map_hash ON pdf_page_map(pdf_hash)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_pdf_page_map_entry ON pdf_page_map(entry_number)')
            
            conn.commit()
        
        print(f"✅ Optimized database initialized at {self.db_path}")

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """
        Migrate existing DBs created by `backend/database.py` (older schema).
        Adds missing timestamp columns so index creation doesn't crash.
        """
        c = conn.cursor()

        def cols(table: str) -> set[str]:
            c.execute(f"PRAGMA table_info({table})")
            return {row[1] for row in c.fetchall()}

        # students: add created_at/updated_at if missing
        student_cols = cols("students")
        if "created_at" not in student_cols:
            c.execute("ALTER TABLE students ADD COLUMN created_at REAL")
            c.execute("UPDATE students SET created_at = COALESCE(created_at, julianday('now'))")
        if "updated_at" not in student_cols:
            c.execute("ALTER TABLE students ADD COLUMN updated_at REAL")
            c.execute("UPDATE students SET updated_at = COALESCE(updated_at, julianday('now'))")

        # submissions: add created_at/updated_at if missing
        submission_cols = cols("submissions")
        if "created_at" not in submission_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN created_at REAL")
            c.execute("UPDATE submissions SET created_at = COALESCE(created_at, julianday('now'))")
        if "updated_at" not in submission_cols:
            c.execute("ALTER TABLE submissions ADD COLUMN updated_at REAL")
            c.execute("UPDATE submissions SET updated_at = COALESCE(updated_at, julianday('now'))")

        # results: add created_at/updated_at if missing
        results_cols = cols("results")
        if "created_at" not in results_cols:
            c.execute("ALTER TABLE results ADD COLUMN created_at REAL")
            c.execute("UPDATE results SET created_at = COALESCE(created_at, julianday('now'))")
        if "updated_at" not in results_cols:
            c.execute("ALTER TABLE results ADD COLUMN updated_at REAL")
            c.execute("UPDATE results SET updated_at = COALESCE(updated_at, julianday('now'))")

        # pipeline_run_items: add ocr_json if missing (for OCR response persistence)
        try:
            items_cols = cols("pipeline_run_items")
            if "ocr_json" not in items_cols:
                c.execute("ALTER TABLE pipeline_run_items ADD COLUMN ocr_json TEXT")
        except Exception:
            pass  # table may not exist yet
    
    async def batch_add_students(self, students: List[Student]) -> int:
        """
        Add multiple students in a single batch operation.
        
        Args:
            students: List of Student objects to add
            
        Returns:
            Number of students successfully added
        """
        if not students:
            return 0
        
        start_time = time.time()
        loop = asyncio.get_event_loop()
        
        result = await loop.run_in_executor(
            self.executor,
            self._batch_add_students_sync,
            students
        )
        
        # Update stats
        operation_time = time.time() - start_time
        self.stats.total_operations += 1
        self.stats.batch_operations += 1
        self.stats.avg_operation_time = (
            (self.stats.avg_operation_time * (self.stats.total_operations - 1) + operation_time) /
            self.stats.total_operations
        )
        
        return result

    # ──────────────────────────────────────
    #  Pipeline run persistence (resume)
    # ──────────────────────────────────────

    async def create_pipeline_run(self, run_id: str, source_type: str, source_ref: str, total_files: int) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._create_pipeline_run_sync,
            run_id,
            source_type,
            source_ref,
            total_files,
        )

    def _create_pipeline_run_sync(self, run_id: str, source_type: str, source_ref: str, total_files: int) -> None:
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO pipeline_runs "
                "(run_id, source_type, source_ref, status, total_files, processed_files, cache_hits, errors, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, julianday('now'))",
                (run_id, source_type, source_ref, "running", int(total_files), 0, 0, "[]"),
            )
            conn.commit()

    async def update_pipeline_run_progress(
        self,
        run_id: str,
        processed_files: int,
        cache_hits: int,
        errors: List[Dict[str, Any]],
        status: Optional[str] = None,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._update_pipeline_run_progress_sync,
            run_id,
            processed_files,
            cache_hits,
            json.dumps(errors),
            status,
        )

    def _update_pipeline_run_progress_sync(
        self,
        run_id: str,
        processed_files: int,
        cache_hits: int,
        errors_json: str,
        status: Optional[str],
    ) -> None:
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            if status:
                c.execute(
                    "UPDATE pipeline_runs SET processed_files=?, cache_hits=?, errors=?, status=?, updated_at=julianday('now') WHERE run_id=?",
                    (int(processed_files), int(cache_hits), errors_json, status, run_id),
                )
            else:
                c.execute(
                    "UPDATE pipeline_runs SET processed_files=?, cache_hits=?, errors=?, updated_at=julianday('now') WHERE run_id=?",
                    (int(processed_files), int(cache_hits), errors_json, run_id),
                )
            conn.commit()

    async def upsert_pipeline_run_item(
        self,
        run_id: str,
        file_name: str,
        status: str,
        file_hash: Optional[str] = None,
        entry_number: Optional[str] = None,
        ocr_json: Optional[Dict[str, Any]] = None,
        result_json: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._upsert_pipeline_run_item_sync,
            run_id,
            file_name,
            file_hash,
            status,
            entry_number,
            json.dumps(ocr_json) if ocr_json is not None else None,
            json.dumps(result_json) if result_json is not None else None,
            error,
        )

    def _upsert_pipeline_run_item_sync(
        self,
        run_id: str,
        file_name: str,
        file_hash: Optional[str],
        status: str,
        entry_number: Optional[str],
        ocr_json: Optional[str],
        result_json: Optional[str],
        error: Optional[str],
    ) -> None:
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO pipeline_run_items "
                "(run_id, file_name, file_hash, status, entry_number, ocr_json, result_json, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, julianday('now'))",
                (run_id, file_name, file_hash, status, entry_number, ocr_json, result_json, error),
            )
            conn.commit()

    async def find_incomplete_run(self, source_type: str, source_ref: str) -> Optional[Dict[str, Any]]:
        """Find the most recent incomplete run for this source (for resume)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._find_incomplete_run_sync, source_type, source_ref
        )

    def _find_incomplete_run_sync(self, source_type: str, source_ref: str) -> Optional[Dict[str, Any]]:
        # Only `running` runs are considered resumable. A `failed` run represents
        # a definite error state — resuming it would silently inherit the prior
        # error context. Callers that really want to retry a failed run should
        # pass its run_id explicitly.
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                "SELECT * FROM pipeline_runs WHERE source_type=? AND source_ref=? AND status = 'running' "
                "ORDER BY updated_at DESC LIMIT 1",
                (source_type, source_ref),
            )
            row = c.fetchone()
            return dict(row) if row else None

    async def get_pipeline_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_pipeline_run_sync, run_id)

    def _get_pipeline_run_sync(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,))
            row = c.fetchone()
            return dict(row) if row else None

    async def list_pipeline_run_items(self, run_id: str) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._list_pipeline_run_items_sync, run_id)

    def _list_pipeline_run_items_sync(self, run_id: str) -> List[Dict[str, Any]]:
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM pipeline_run_items WHERE run_id=? ORDER BY created_at ASC", (run_id,))
            return [dict(r) for r in c.fetchall()]

    # ──────────────────────────────────────
    #  PDF page ↔ student mapping
    # ──────────────────────────────────────

    async def upsert_pdf_page_map(
        self,
        run_id: str,
        pdf_hash: str,
        page_number: int,
        page_index: int,
        status: str,
        file_id: Optional[str] = None,
        file_name: Optional[str] = None,
        entry_number: Optional[str] = None,
        name: Optional[str] = None,
        total_score: Optional[float] = None,
        max_score: Optional[float] = None,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._upsert_pdf_page_map_sync,
            run_id, pdf_hash, page_number, page_index, status,
            file_id, file_name, entry_number, name, total_score, max_score,
        )

    def _upsert_pdf_page_map_sync(
        self,
        run_id: str,
        pdf_hash: str,
        page_number: int,
        page_index: int,
        status: str,
        file_id: Optional[str],
        file_name: Optional[str],
        entry_number: Optional[str],
        name: Optional[str],
        total_score: Optional[float],
        max_score: Optional[float],
    ) -> None:
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO pdf_page_map "
                "(run_id, pdf_hash, page_number, page_index, file_id, file_name, "
                " entry_number, name, status, total_score, max_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, julianday('now'))",
                (run_id, pdf_hash, int(page_number), int(page_index),
                 file_id, file_name, entry_number, name, status,
                 total_score, max_score),
            )
            conn.commit()

    async def list_pdf_page_map(self, run_id: str) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._list_pdf_page_map_sync, run_id)

    def _list_pdf_page_map_sync(self, run_id: str) -> List[Dict[str, Any]]:
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                "SELECT * FROM pdf_page_map WHERE run_id=? ORDER BY page_number ASC",
                (run_id,),
            )
            return [dict(r) for r in c.fetchall()]

    async def get_pdf_page(self, run_id: str, page_number: int) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._get_pdf_page_sync, run_id, page_number
        )

    def _get_pdf_page_sync(self, run_id: str, page_number: int) -> Optional[Dict[str, Any]]:
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                "SELECT * FROM pdf_page_map WHERE run_id=? AND page_number=?",
                (run_id, int(page_number)),
            )
            row = c.fetchone()
            return dict(row) if row else None

    async def find_pdf_page_by_entry(self, run_id: str, entry_number: str) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._find_pdf_page_by_entry_sync, run_id, entry_number
        )

    def _find_pdf_page_by_entry_sync(self, run_id: str, entry_number: str) -> List[Dict[str, Any]]:
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                "SELECT * FROM pdf_page_map WHERE run_id=? AND entry_number=? ORDER BY page_number ASC",
                (run_id, entry_number),
            )
            return [dict(r) for r in c.fetchall()]
    
    def _batch_add_students_sync(self, students: List[Student]) -> int:
        """Synchronous batch student insertion."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            
            try:
                # Prepare batch data
                student_data = [
                    (s.id, s.name, s.roll_number, time.time(), time.time())
                    for s in students
                ]
                
                # Batch insert with conflict resolution
                c.executemany('''
                    INSERT OR REPLACE INTO students 
                    (id, name, roll_number, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', student_data)
                
                conn.commit()
                return len(students)
                
            except Exception as e:
                conn.rollback()
                print(f"Batch student insert failed: {e}")
                return 0
    
    async def batch_add_results(
        self, 
        student_results: List[StudentResult],
        exam_id: str = "current_exam"
    ) -> int:
        """
        Add multiple student results in a single batch operation.
        
        Args:
            student_results: List of StudentResult objects
            exam_id: Exam identifier
            
        Returns:
            Number of results successfully added
        """
        if not student_results:
            return 0
        
        start_time = time.time()
        loop = asyncio.get_event_loop()
        
        result = await loop.run_in_executor(
            self.executor,
            self._batch_add_results_sync,
            student_results,
            exam_id
        )
        
        # Update stats
        operation_time = time.time() - start_time
        self.stats.total_operations += 1
        self.stats.batch_operations += 1
        self.stats.avg_operation_time = (
            (self.stats.avg_operation_time * (self.stats.total_operations - 1) + operation_time) /
            self.stats.total_operations
        )
        
        return result
    
    def _batch_add_results_sync(self, student_results: List, exam_id: str) -> int:
        """Synchronous batch result insertion. Handles both StudentResult objects and dicts."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            
            try:
                current_time = time.time()

                # Helper: access field from either a Pydantic model or a dict
                def _get(obj, key, default=""):
                    if isinstance(obj, dict):
                        return obj.get(key, default)
                    return getattr(obj, key, default)
                
                # Prepare student data
                student_data = []
                submission_data = []
                result_data = []
                
                for result in student_results:
                    entry_number = str(_get(result, "entry_number", "unknown"))
                    name = str(_get(result, "name", ""))
                    total_score = float(_get(result, "total_score", 0))
                    correct_count = int(_get(result, "correct_count", 0))
                    incorrect_count = int(_get(result, "incorrect_count", 0))
                    unattempted_count = int(_get(result, "unattempted_count", 0))
                    details_raw = _get(result, "details", [])

                    # Student data
                    student_data.append((
                        entry_number,
                        name,
                        entry_number,
                        current_time,
                        current_time
                    ))
                    
                    # Submission data (using entry_number as submission_id)
                    submission_id = f"{exam_id}_{entry_number}"

                    # Build answers dict from details (handles both object and dict)
                    answers = {}
                    for d in (details_raw or []):
                        q = _get(d, "question_number", None)
                        marked = _get(d, "marked", None)
                        if q is not None and marked:
                            answers[q] = marked

                    submission_data.append((
                        submission_id,
                        entry_number,
                        exam_id,
                        None,  # file_id
                        "evaluated",
                        json.dumps({
                            "entry_number": entry_number,
                            "name": name,
                            "answers": answers
                        }),
                        current_time,
                        current_time
                    ))
                    
                    # Result data — serialize the full result
                    if hasattr(result, "model_dump"):
                        result_dump = json.dumps(result.model_dump())
                    elif isinstance(result, dict):
                        result_dump = json.dumps(result)
                    else:
                        result_dump = json.dumps(str(result))

                    result_data.append((
                        submission_id,
                        total_score,
                        f"{correct_count} correct, {incorrect_count} incorrect, {unattempted_count} unattempted",
                        result_dump,
                        current_time,
                        current_time
                    ))
                
                # Execute batch operations
                c.executemany('''
                    INSERT OR REPLACE INTO students 
                    (id, name, roll_number, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', student_data)
                
                c.executemany('''
                    INSERT OR REPLACE INTO submissions 
                    (id, student_id, exam_id, file_id, status, extracted_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', submission_data)
                
                c.executemany('''
                    INSERT OR REPLACE INTO results 
                    (submission_id, score, feedback, details, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', result_data)
                
                conn.commit()
                return len(student_results)
                
            except Exception as e:
                conn.rollback()
                print(f"Batch result insert failed: {e}")
                return 0
    
    async def get_results_paginated(
        self, 
        offset: int = 0, 
        limit: int = 100,
        order_by: str = "score DESC"
    ) -> Tuple[List[Dict], int]:
        """
        Get results with pagination for better memory usage.
        
        Args:
            offset: Number of records to skip
            limit: Maximum number of records to return
            order_by: SQL ORDER BY clause
            
        Returns:
            Tuple of (results, total_count)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._get_results_paginated_sync,
            offset,
            limit,
            order_by
        )
    
    def _get_results_paginated_sync(
        self, 
        offset: int, 
        limit: int, 
        order_by: str
    ) -> Tuple[List[Dict], int]:
        """Synchronous paginated results query."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            try:
                # Get total count
                c.execute("""
                    SELECT COUNT(*) 
                    FROM results r
                    JOIN submissions s ON r.submission_id = s.id
                    JOIN students st ON s.student_id = st.id
                """)
                total_count = c.fetchone()[0]
                
                # Get paginated results
                query = f"""
                    SELECT 
                        r.*,
                        s.student_id,
                        s.exam_id,
                        s.status,
                        st.name as student_name,
                        st.roll_number
                    FROM results r
                    JOIN submissions s ON r.submission_id = s.id
                    JOIN students st ON s.student_id = st.id
                    ORDER BY {order_by}
                    LIMIT ? OFFSET ?
                """
                
                c.execute(query, (limit, offset))
                rows = c.fetchall()
                results = [dict(row) for row in rows]
                
                return results, total_count
                
            except Exception as e:
                print(f"Paginated query failed: {e}")
                return [], 0
    
    async def get_performance_analytics(self) -> Dict[str, Any]:
        """Get database performance and usage analytics."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._get_performance_analytics_sync
        )
    
    def _get_performance_analytics_sync(self) -> Dict[str, Any]:
        """Synchronous performance analytics query."""
        with self.pool.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            try:
                analytics = {}
                
                # Basic counts
                c.execute("SELECT COUNT(*) FROM students")
                analytics['total_students'] = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM submissions")
                analytics['total_submissions'] = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM results")
                analytics['total_results'] = c.fetchone()[0]
                
                # Score statistics
                c.execute("""
                    SELECT 
                        AVG(score) as avg_score,
                        MIN(score) as min_score,
                        MAX(score) as max_score,
                        COUNT(CASE WHEN score >= 60 THEN 1 END) as passing_count
                    FROM results
                """)
                score_stats = dict(c.fetchone())
                analytics.update(score_stats)
                
                # Recent activity (last 24 hours)
                c.execute("""
                    SELECT COUNT(*) 
                    FROM results 
                    WHERE created_at > julianday('now') - 1
                """)
                analytics['recent_results_24h'] = c.fetchone()[0]
                
                # Database size info
                c.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
                db_size = c.fetchone()
                analytics['database_size_mb'] = (db_size[0] if db_size else 0) / 1024 / 1024
                
                # Connection pool stats
                hits, misses = self.pool.get_stats()
                analytics['connection_pool'] = {
                    'hits': hits,
                    'misses': misses,
                    'hit_ratio': hits / (hits + misses) if (hits + misses) > 0 else 0
                }
                
                # Service stats
                analytics['service_stats'] = {
                    'total_operations': self.stats.total_operations,
                    'batch_operations': self.stats.batch_operations,
                    'avg_operation_time': self.stats.avg_operation_time,
                    'batch_ratio': self.stats.batch_operations / self.stats.total_operations if self.stats.total_operations > 0 else 0
                }
                
                return analytics
                
            except Exception as e:
                print(f"Analytics query failed: {e}")
                return {}
    
    async def vacuum_database(self) -> bool:
        """
        Vacuum database to reclaim space and optimize performance.
        Should be run periodically during maintenance windows.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._vacuum_database_sync)
    
    def _vacuum_database_sync(self) -> bool:
        """Synchronous database vacuum operation."""
        try:
            with self.pool.get_connection() as conn:
                print("🧹 Starting database vacuum...")
                start_time = time.time()
                
                conn.execute("VACUUM")
                conn.execute("ANALYZE")
                
                vacuum_time = time.time() - start_time
                print(f"✅ Database vacuum completed in {vacuum_time:.2f}s")
                return True
                
        except Exception as e:
            print(f"Database vacuum failed: {e}")
            return False
    
    async def create_indexes_if_missing(self):
        """Create additional performance indexes if they don't exist."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._create_indexes_sync)
    
    def _create_indexes_sync(self):
        """Synchronous index creation."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            
            additional_indexes = [
                "CREATE INDEX IF NOT EXISTS idx_results_score_desc ON results(score DESC)",
                "CREATE INDEX IF NOT EXISTS idx_submissions_exam_status ON submissions(exam_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_students_name ON students(name COLLATE NOCASE)",
                "CREATE INDEX IF NOT EXISTS idx_results_feedback ON results(feedback) WHERE feedback IS NOT NULL"
            ]
            
            for index_sql in additional_indexes:
                try:
                    c.execute(index_sql)
                except Exception as e:
                    print(f"Index creation warning: {e}")
            
            conn.commit()
            print("✅ Additional database indexes created")


# Convenience functions for backward compatibility
async def batch_write_student_results(
    student_results: List[StudentResult],
    db_service: OptimizedDatabaseService = None,
    exam_id: str = "current_exam"
) -> int:
    """
    Convenience function for batch writing student results.
    
    Args:
        student_results: List of StudentResult objects
        db_service: Database service instance (creates new if None)
        exam_id: Exam identifier
        
    Returns:
        Number of results successfully written
    """
    db = db_service or OptimizedDatabaseService()
    return await db.batch_add_results(student_results, exam_id)


async def get_paginated_results(
    offset: int = 0,
    limit: int = 100,
    order_by: str = "score DESC",
    db_service: OptimizedDatabaseService = None
) -> Tuple[List[Dict], int]:
    """
    Convenience function for getting paginated results.
    
    Args:
        offset: Records to skip
        limit: Max records to return
        order_by: Sort order
        db_service: Database service instance
        
    Returns:
        Tuple of (results, total_count)
    """
    db = db_service or OptimizedDatabaseService()
    return await db.get_results_paginated(offset, limit, order_by)