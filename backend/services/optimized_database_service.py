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
        """Initialize database with backward compatible schema migration."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            
            # First, create tables with basic schema (backward compatible)
            c.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    roll_number TEXT NOT NULL
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
                    FOREIGN KEY (student_id) REFERENCES students (id)
                )
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    submission_id TEXT PRIMARY KEY,
                    score REAL NOT NULL,
                    feedback TEXT,
                    details TEXT,
                    FOREIGN KEY (submission_id) REFERENCES submissions (id)
                )
            ''')
            
            # Add timestamp columns if they don't exist (graceful migration)
            try:
                c.execute('ALTER TABLE students ADD COLUMN created_at REAL DEFAULT (julianday("now"))')
            except sqlite3.OperationalError:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE students ADD COLUMN updated_at REAL DEFAULT (julianday("now"))')
            except sqlite3.OperationalError:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE submissions ADD COLUMN created_at REAL DEFAULT (julianday("now"))')
            except sqlite3.OperationalError:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE submissions ADD COLUMN updated_at REAL DEFAULT (julianday("now"))')
            except sqlite3.OperationalError:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE results ADD COLUMN created_at REAL DEFAULT (julianday("now"))')
            except sqlite3.OperationalError:
                pass  # Column already exists
                
            try:
                c.execute('ALTER TABLE results ADD COLUMN updated_at REAL DEFAULT (julianday("now"))')
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Create basic performance indexes (always safe)
            c.execute('CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll_number)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_exam ON submissions(exam_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_results_score ON results(score)')
            
            # Create timestamp indexes only if columns exist
            c.execute("PRAGMA table_info(students)")
            students_columns = [col[1] for col in c.fetchall()]
            if 'created_at' in students_columns:
                c.execute('CREATE INDEX IF NOT EXISTS idx_students_created_at ON students(created_at)')
                
            c.execute("PRAGMA table_info(submissions)")
            submissions_columns = [col[1] for col in c.fetchall()]
            if 'created_at' in submissions_columns:
                c.execute('CREATE INDEX IF NOT EXISTS idx_submissions_created_at ON submissions(created_at)')
                
            c.execute("PRAGMA table_info(results)")
            results_columns = [col[1] for col in c.fetchall()]
            if 'created_at' in results_columns:
                c.execute('CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at)')
            
            conn.commit()
        
        print(f"✅ Optimized database initialized at {self.db_path}")
    
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
    
    def _batch_add_results_sync(self, student_results: List[StudentResult], exam_id: str) -> int:
        """Synchronous batch result insertion."""
        with self.pool.get_connection() as conn:
            c = conn.cursor()
            
            try:
                current_time = time.time()
                
                # Prepare student data
                student_data = []
                submission_data = []
                result_data = []
                
                for result in student_results:
                    # Student data
                    student_data.append((
                        result.entry_number,
                        result.name,
                        result.entry_number,
                        current_time,
                        current_time
                    ))
                    
                    # Submission data (using entry_number as submission_id)
                    submission_id = f"{exam_id}_{result.entry_number}"
                    submission_data.append((
                        submission_id,
                        result.entry_number,
                        exam_id,
                        None,  # file_id
                        "evaluated",
                        json.dumps({
                            "entry_number": result.entry_number,
                            "name": result.name,
                            "answers": {d.question_number: d.marked for d in result.details if d.marked}
                        }),
                        current_time,
                        current_time
                    ))
                    
                    # Result data
                    result_data.append((
                        submission_id,
                        result.total_score,
                        f"{result.correct_count} correct, {result.incorrect_count} incorrect, {result.unattempted_count} unattempted",
                        json.dumps(result.model_dump()),
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