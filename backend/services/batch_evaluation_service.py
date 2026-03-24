"""
Batch Evaluation Service
========================
Optimized batch processing for answer key matching and scoring.
Reduces overhead through vectorized operations and batch database writes.
"""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from models import AnswerKey, StudentResult, QuestionResult
from services.evaluation_service import EvaluationService
from database import Database
import sqlite3


@dataclass
class BatchProcessingStats:
    total_students: int
    processing_time: float
    avg_time_per_student: float
    successful_evaluations: int
    failed_evaluations: int
    database_write_time: float


class BatchEvaluationService:
    """
    High-performance batch evaluation service that processes multiple student
    answers simultaneously with optimized database operations.
    """
    
    def __init__(self, db: Database = None, max_workers: int = None):
        self.db = db or Database()
        # Use CPU count for optimal parallelism
        self.max_workers = max_workers or min(32, (asyncio.get_event_loop()._thread_pool_executor._max_workers if hasattr(asyncio.get_event_loop(), '_thread_pool_executor') else 8))
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
    def __del__(self):
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    async def process_batch_async(
        self, 
        answer_key: AnswerKey, 
        student_ocr_results: List[Dict],
        use_multiprocessing: bool = False
    ) -> Tuple[List[StudentResult], BatchProcessingStats]:
        """
        Process a batch of student OCR results against an answer key with optimizations.
        
        Args:
            answer_key: The answer key to match against
            student_ocr_results: List of OCR results from students
            use_multiprocessing: Use process pool for CPU-intensive tasks
            
        Returns:
            Tuple of (student_results, processing_stats)
        """
        start_time = time.time()
        
        # Pre-process answer key for faster lookups
        optimized_key = self.optimize_answer_key(answer_key)
        
        if use_multiprocessing and len(student_ocr_results) > 10:
            # Use process pool for large batches
            results = await self._process_with_multiprocessing(optimized_key, student_ocr_results)
        else:
            # Use thread pool for smaller batches or when multiprocessing overhead isn't worth it
            results = await self._process_with_threading(optimized_key, student_ocr_results)
        
        # Separate successful and failed results
        successful_results = [r for r in results if isinstance(r, StudentResult)]
        failed_results = [r for r in results if isinstance(r, dict) and 'error' in r]
        
        # Batch database operations
        db_start = time.time()
        if successful_results:
            await self._batch_write_to_database(successful_results)
        db_time = time.time() - db_start
        
        total_time = time.time() - start_time
        
        stats = BatchProcessingStats(
            total_students=len(student_ocr_results),
            processing_time=total_time,
            avg_time_per_student=total_time / len(student_ocr_results) if student_ocr_results else 0,
            successful_evaluations=len(successful_results),
            failed_evaluations=len(failed_results),
            database_write_time=db_time
        )
        
        print(f"📊 Batch Processing Stats:")
        print(f"   Total Students: {stats.total_students}")
        print(f"   Processing Time: {stats.processing_time:.2f}s")
        print(f"   Avg Time/Student: {stats.avg_time_per_student:.3f}s")
        print(f"   Success Rate: {stats.successful_evaluations}/{stats.total_students} ({stats.successful_evaluations/stats.total_students*100:.1f}%)")
        print(f"   DB Write Time: {stats.database_write_time:.2f}s")
        
        return successful_results, stats

    def optimize_answer_key(self, answer_key: AnswerKey) -> Dict:
        """
        Pre-process answer key for faster lookups during batch processing.
        """
        return {
            'answers': {
                q_num: {
                    'correct_option': entry.correct_option.strip().upper(),
                    'marks': entry.marks
                }
                for q_num, entry in answer_key.answers.items()
            },
            'negative_marking': answer_key.negative_marking,
            'total_questions': answer_key.total_questions,
            'question_numbers': set(answer_key.answers.keys())  # Fast lookup set
        }

    async def _process_with_threading(self, optimized_key: Dict, student_ocr_results: List[Dict]) -> List:
        """Process using thread pool for I/O bound operations."""
        loop = asyncio.get_event_loop()
        
        # Create tasks for parallel processing
        tasks = [
            loop.run_in_executor(
                self.executor,
                self.evaluate_single_student_optimized,
                optimized_key,
                ocr_result,
                idx
            )
            for idx, ocr_result in enumerate(student_ocr_results)
        ]
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'error': str(result),
                    'student_index': i,
                    'entry_number': student_ocr_results[i].get('entry_number', f'student_{i}')
                })
            else:
                processed_results.append(result)
        
        return processed_results

    async def _process_with_multiprocessing(self, optimized_key: Dict, student_ocr_results: List[Dict]) -> List:
        """Process using process pool for CPU-intensive operations."""
        loop = asyncio.get_event_loop()
        
        # Use process pool for CPU-bound work
        with ProcessPoolExecutor(max_workers=min(8, len(student_ocr_results))) as process_executor:
            tasks = [
                loop.run_in_executor(
                    process_executor,
                    _evaluate_student_worker,  # Must be a top-level function for pickling
                    optimized_key,
                    ocr_result,
                    idx
                )
                for idx, ocr_result in enumerate(student_ocr_results)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'error': str(result),
                    'student_index': i,
                    'entry_number': student_ocr_results[i].get('entry_number', f'student_{i}')
                })
            else:
                processed_results.append(result)
        
        return processed_results

    def evaluate_single_student_optimized(self, optimized_key: Dict, student_ocr_result: Dict, student_index: int) -> StudentResult:
        """
        Optimized single student evaluation using pre-processed answer key.
        Removes debug prints and uses efficient data structures.
        """
        try:
            entry_number = str(student_ocr_result.get("entry_number", f"student_{student_index}")).strip()
            name = str(student_ocr_result.get("name", "")).strip()
            raw_answers = student_ocr_result.get("answers", {})
            
            # Aggregate comments efficiently
            comments_list = []
            if student_ocr_result.get("comments"):
                c = str(student_ocr_result["comments"]).strip()
                if c and c.lower() not in ("none", "null", ""):
                    comments_list.append(c)

            # Normalize student answers with optimized processing
            student_ans = {}
            for k, v in raw_answers.items():
                try:
                    q_num = int(k)
                    option = str(v).strip().upper()
                    if "OPTION" in option:
                        option = option.replace("OPTION", "").strip()
                    student_ans[q_num] = option
                except (ValueError, TypeError):
                    continue

            # Initialize counters
            total_score = 0.0
            max_score = 0.0
            correct_count = 0
            incorrect_count = 0
            unattempted_count = 0
            negative_deduction = 0.0
            details = []

            # Process questions using optimized answer key
            answers_dict = optimized_key['answers']
            negative_marking = optimized_key['negative_marking']
            
            # Iterate over answer key questions (more efficient than original)
            for q_num, key_data in answers_dict.items():
                correct_option = key_data['correct_option']
                marks = key_data['marks']
                max_score += marks

                if q_num in student_ans:
                    marked = student_ans[q_num]
                    
                    if marked == "MULTIPLE":
                        # Multiple options marked -> Incorrect
                        incorrect_count += 1
                        negative_deduction += negative_marking
                        total_score -= negative_marking
                        details.append(QuestionResult(
                            question_number=q_num,
                            marked=marked,
                            correct=correct_option,
                            result="multiple",
                            score=-negative_marking
                        ))
                        comments_list.append(f"Q{q_num}: Multiple marks")
                    
                    elif marked == correct_option:
                        correct_count += 1
                        total_score += marks
                        details.append(QuestionResult(
                            question_number=q_num,
                            marked=marked,
                            correct=correct_option,
                            result="correct",
                            score=marks
                        ))
                    
                    elif EvaluationService._ocr_correct_mcq_answer(marked) == correct_option:
                        # OCR digit-to-letter correction matched (e.g. '8' → 'B')
                        correct_count += 1
                        total_score += marks
                        details.append(QuestionResult(
                            question_number=q_num,
                            marked=marked,
                            correct=correct_option,
                            result="correct",
                            score=marks
                        ))
                    
                    else:
                        incorrect_count += 1
                        negative_deduction += negative_marking
                        total_score -= negative_marking
                        details.append(QuestionResult(
                            question_number=q_num,
                            marked=marked,
                            correct=correct_option,
                            result="incorrect",
                            score=-negative_marking
                        ))
                else:
                    unattempted_count += 1
                    details.append(QuestionResult(
                        question_number=q_num,
                        marked=None,
                        correct=correct_option,
                        result="unattempted",
                        score=0.0
                    ))

            # Sort details by question number (more efficient than lambda)
            details.sort(key=lambda d: d.question_number)

            return StudentResult(
                entry_number=entry_number,
                name=name,
                total_score=max(total_score, 0),
                max_score=max_score,
                correct_count=correct_count,
                incorrect_count=incorrect_count,
                unattempted_count=unattempted_count,
                negative_deduction=negative_deduction,
                details=details,
                comments="; ".join(comments_list) if comments_list else ""
            )
            
        except Exception as e:
            # Return error info instead of raising
            return {
                'error': str(e),
                'entry_number': student_ocr_result.get('entry_number', f'student_{student_index}'),
                'student_index': student_index
            }

    async def _batch_write_to_database(self, student_results: List[StudentResult]):
        """
        Efficiently write multiple student results to database using batch operations.
        """
        if not student_results:
            return
            
        # Prepare batch data
        student_data = []
        result_data = []
        
        for result in student_results:
            # Prepare student data
            student_data.append((
                result.entry_number,
                result.name,
                result.entry_number  # roll_number same as entry_number
            ))
            
            # Prepare result data (using entry_number as submission_id for simplicity)
            result_data.append((
                result.entry_number,  # submission_id
                result.total_score,
                f"{result.correct_count} correct, {result.incorrect_count} incorrect, {result.unattempted_count} unattempted",
                json.dumps(result.model_dump())
            ))
        
        # Execute batch operations in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._execute_batch_db_operations,
            student_data,
            result_data
        )

    def _execute_batch_db_operations(self, student_data: List[Tuple], result_data: List[Tuple]):
        """Execute batch database operations synchronously."""
        conn = sqlite3.connect(self.db.db_path)
        try:
            c = conn.cursor()
            
            # Batch insert students
            c.executemany(
                "INSERT OR REPLACE INTO students (id, name, roll_number) VALUES (?, ?, ?)",
                student_data
            )
            
            # Batch insert results
            c.executemany(
                "INSERT OR REPLACE INTO results (submission_id, score, feedback, details) VALUES (?, ?, ?, ?)",
                result_data
            )
            
            conn.commit()
            print(f"✅ Batch wrote {len(student_data)} students and {len(result_data)} results to database")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ Batch database write failed: {e}")
            raise
        finally:
            conn.close()


# Top-level function for multiprocessing (must be picklable)
def _evaluate_student_worker(optimized_key: Dict, student_ocr_result: Dict, student_index: int):
    """Worker function for multiprocessing evaluation."""
    service = BatchEvaluationService()
    return service.evaluate_single_student_optimized(optimized_key, student_ocr_result, student_index)


# Convenience function for backward compatibility
async def batch_match_and_score(
    answer_key: AnswerKey, 
    student_ocr_results: List[Dict],
    use_multiprocessing: bool = None
) -> Tuple[List[StudentResult], BatchProcessingStats]:
    """
    Convenience function for batch processing student results.
    
    Args:
        answer_key: Answer key to match against
        student_ocr_results: List of OCR results
        use_multiprocessing: Auto-detect based on batch size if None
        
    Returns:
        Tuple of (results, stats)
    """
    # Auto-detect multiprocessing based on batch size
    if use_multiprocessing is None:
        use_multiprocessing = len(student_ocr_results) > 20
    
    service = BatchEvaluationService()
    return await service.process_batch_async(
        answer_key, 
        student_ocr_results, 
        use_multiprocessing=use_multiprocessing
    )