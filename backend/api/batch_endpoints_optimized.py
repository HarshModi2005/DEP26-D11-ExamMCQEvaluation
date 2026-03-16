"""
Optimized Batch Processing Endpoints
===================================
High-performance endpoints specifically designed for large-scale processing
with advanced caching, batch operations, and performance monitoring.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from models import ProcessFolderRequest, PipelineSummary
from services.drive_service import DriveService
from services.optimized_ocr_service import OptimizedOCRService
from services.multi_region_ocr_service import MultiRegionOCRService
from services.answer_key_service import AnswerKeyService
from services.batch_evaluation_service import BatchEvaluationService, batch_match_and_score
from services.result_cache_service import ResultCacheService, get_cached_or_process_ocr
from services.optimized_database_service import OptimizedDatabaseService, batch_write_student_results
import asyncio
import aiohttp
import tempfile
import shutil
import os
import time
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

router = APIRouter()

# Optimized services for high-performance processing
drive_service = DriveService()
optimized_ocr = OptimizedOCRService()
multi_region_ocr = MultiRegionOCRService()
answer_key_service = AnswerKeyService()
batch_eval_service = BatchEvaluationService()
cache_service = ResultCacheService()
optimized_db = OptimizedDatabaseService()

# Global state for optimized processing
_current_answer_key: Optional = None
_processing_stats: Dict[str, Any] = {}


@router.post("/batch/process-folder-optimized")
async def process_folder_optimized(request: ProcessFolderRequest):
    """
    Ultra-optimized folder processing with advanced caching and batch operations.
    
    Features:
    - Intelligent OCR result caching
    - Batch evaluation processing
    - Multi-region OCR load balancing
    - Optimized database operations
    - Real-time performance monitoring
    """
    global _current_answer_key, _processing_stats
    
    start_time = time.time()
    folder_id = DriveService.extract_folder_id(request.folder_url)
    
    # Initialize processing stats
    processing_id = f"batch_{int(start_time)}"
    _processing_stats[processing_id] = {
        "start_time": start_time,
        "status": "initializing",
        "total_files": 0,
        "processed_files": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "errors": []
    }
    
    try:
        # Step 1: Discover files
        _processing_stats[processing_id]["status"] = "discovering_files"
        all_files = drive_service.list_all_files_in_folder(folder_id)
        
        if not all_files:
            raise HTTPException(status_code=404, detail="No files found in the Drive folder.")
        
        answer_key_files, student_sheets = drive_service.separate_files(all_files)
        _processing_stats[processing_id]["total_files"] = len(student_sheets)
        
        # Step 2: Load answer key if needed
        if _current_answer_key is None and answer_key_files:
            _processing_stats[processing_id]["status"] = "loading_answer_key"
            temp_dir = tempfile.mkdtemp(prefix="ak_opt_")
            try:
                local_path = drive_service.download_answer_key(answer_key_files[0], temp_dir)
                mime_type = answer_key_files[0].get("mimeType", "")
                _current_answer_key = answer_key_service.extract_answer_key(local_path, mime_type)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        
        if not _current_answer_key:
            raise HTTPException(
                status_code=400,
                detail="No answer key available. Please load an answer key first."
            )
        
        if not student_sheets:
            raise HTTPException(
                status_code=404,
                detail="No student answer sheets found in the folder."
            )
        
        # Step 3: Optimized processing pipeline
        results, errors = await _process_sheets_optimized(
            student_sheets, 
            _current_answer_key,
            processing_id
        )
        
        # Step 4: Final statistics
        total_time = time.time() - start_time
        _processing_stats[processing_id].update({
            "status": "completed",
            "total_time": total_time,
            "avg_time_per_file": total_time / len(student_sheets) if student_sheets else 0,
            "success_rate": len(results) / len(student_sheets) if student_sheets else 0
        })
        
        return PipelineSummary(
            total_students_processed=len(results),
            answer_key_source=_current_answer_key.metadata.get("source_file", "loaded"),
            results=results,
            errors=errors,
            processing_stats=_processing_stats[processing_id]
        ).model_dump()
        
    except Exception as e:
        _processing_stats[processing_id].update({
            "status": "failed",
            "error": str(e),
            "total_time": time.time() - start_time
        })
        raise


def write_file_sync(path, data):
    with open(path, 'wb') as f:
        f.write(data)

async def _db_writer_worker(queue: asyncio.Queue, processing_id: str):
    batch = []
    while True:
        try:
            result = await asyncio.wait_for(queue.get(), timeout=2.0)
            if result is None:
                if batch:
                    await batch_write_student_results(batch, optimized_db, exam_id=f"optimized_batch_{processing_id}")
                queue.task_done()
                break
            batch.append(result)
            queue.task_done()
            
            if len(batch) >= 20:
                await batch_write_student_results(batch, optimized_db, exam_id=f"optimized_batch_{processing_id}")
                batch = []
        except asyncio.TimeoutError:
            if batch:
                await batch_write_student_results(batch, optimized_db, exam_id=f"optimized_batch_{processing_id}")
                batch = []

async def _process_and_evaluate_single(
    sheet_file: Dict, 
    index: int, 
    optimized_key: Dict, 
    db_queue: asyncio.Queue, 
    processing_id: str, 
    download_semaphore: asyncio.Semaphore, 
    evaluation_semaphore: asyncio.Semaphore, 
    temp_dir: str, 
    session: aiohttp.ClientSession, 
    drive_token: str, 
    drive_api_key: str
) -> Dict:
    local_path = os.path.join(temp_dir, f"{index}_{sheet_file['name']}")
    
    # 1. Download (Native aiohttp concurrency)
    async with download_semaphore:
        if not os.path.exists(local_path):
            file_id = sheet_file["id"]
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            headers = {"Authorization": f"Bearer {drive_token}"} if drive_token else {}
            params = {"key": drive_api_key} if drive_api_key else {}
            
            try:
                # 20 minutes timeout for slow large images
                async with session.get(url, headers=headers, params=params, timeout=1200) as response:
                    if response.status == 200:
                        content = await response.read()
                        await asyncio.to_thread(write_file_sync, local_path, content)
                    else:
                        # Fallback to sync download
                        success = await asyncio.to_thread(drive_service.download_file, file_id, local_path)
                        if not success:
                            return {"error": f"Drive Download failed: {response.status}", "file": sheet_file["name"]}
            except Exception as e:
                success = await asyncio.to_thread(drive_service.download_file, file_id, local_path)
                if not success:
                    return {"error": f"Download error: {str(e)}", "file": sheet_file["name"]}
                    
    _processing_stats[processing_id]["downloaded_files"] = _processing_stats[processing_id].get("downloaded_files", 0) + 1
    
    # 2. OCR (with caching)
    cached_result = await cache_service.get_cached_ocr_result(local_path)
    
    if cached_result:
        ocr_result = cached_result
        ocr_result["index"] = index
        ocr_result["file_name"] = sheet_file["name"]
        _processing_stats[processing_id]["cache_hits"] = _processing_stats[processing_id].get("cache_hits", 0) + 1
    else:
        _processing_stats[processing_id]["cache_misses"] = _processing_stats[processing_id].get("cache_misses", 0) + 1
        
        async with evaluation_semaphore:
            ocr_result = await optimized_ocr._process_with_retry(local_path, index)
            
        ocr_result["index"] = index
        ocr_result["file_name"] = sheet_file["name"]
        if "error" not in ocr_result:
            await cache_service.cache_ocr_result(local_path, ocr_result)
            
    # 3. Immediate Evaluation
    if "error" not in ocr_result:
        eval_start = time.time()
        # Fallback to _evaluate_single_student_optimized in case public accessor wasn't merged
        eval_method = getattr(batch_eval_service, "evaluate_single_student_optimized", getattr(batch_eval_service, "_evaluate_single_student_optimized"))
        student_result = eval_method(optimized_key, ocr_result, index)
        eval_time = time.time() - eval_start
        
        _processing_stats[processing_id]["total_eval_time"] = _processing_stats[processing_id].get("total_eval_time", 0) + eval_time
        
        if isinstance(student_result, dict) and "error" in student_result:
             return {"error": student_result["error"], "file": sheet_file["name"]}
             
        # Stream to Database Worker
        await db_queue.put(student_result)
        return student_result
    return {"error": ocr_result.get("error"), "file": sheet_file["name"]}

async def _process_sheets_optimized(
    student_sheets: List[Dict], 
    answer_key,
    processing_id: str
) -> tuple[List, List]:
    """
    Optimized processing pipeline using an end-to-end sequential streaming pattern
    incorporating high-speed asynchronous aiohttp downloads.
    """
    results = []
    errors = []
    
    # Pre-process answer key once
    opt_method = getattr(batch_eval_service, "optimize_answer_key", getattr(batch_eval_service, "_optimize_answer_key"))
    optimized_key = opt_method(answer_key)
    
    _processing_stats[processing_id]["status"] = "streaming_pipeline_active"
    _processing_stats[processing_id]["downloaded_files"] = 0
    temp_dir = tempfile.mkdtemp(prefix="sheets_opt_")
    
    try:
        # Setup DB Writer Queue
        db_queue = asyncio.Queue()
        writer_task = asyncio.create_task(_db_writer_worker(db_queue, processing_id))
        
        # Drive authentication for raw HTTP
        drive_token = drive_service.get_access_token()
        drive_api_key = drive_service.api_key
        
        # Semaphore throttling
        download_semaphore = asyncio.Semaphore(100) # Concurrent downloads
        evaluation_semaphore = asyncio.Semaphore(150) # Concurrent OCR/Evaluation
        
        # Create an aiohttp session for downloading
        connector = aiohttp.TCPConnector(limit=100, keepalive_timeout=60)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Parallel end-to-end tasks: Download -> OCR -> Evaluate -> DB writes
            tasks = [
                asyncio.create_task(
                    _process_and_evaluate_single(
                        sheet_file, idx, optimized_key, db_queue, processing_id, 
                        download_semaphore, evaluation_semaphore, temp_dir, 
                        session, drive_token, drive_api_key
                    )
                )
                for idx, sheet_file in enumerate(student_sheets)
            ]
            
            success_count = 0
            
            # Yield as completed
            for completed_task in asyncio.as_completed(tasks):
                result = await completed_task
                
                if isinstance(result, dict) and "error" in result:
                    errors.append(result)
                else:
                    results.append(result)
                    success_count += 1
                    
                _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
            
        # Stop DB writer
        await db_queue.put(None)
        await writer_task
        
        # Update processing stats
        total_students = len(student_sheets)
        eval_time = _processing_stats[processing_id].get("total_eval_time", 0)
        _processing_stats[processing_id].update({
            "batch_evaluation_time": eval_time,
            "avg_evaluation_time": eval_time / success_count if success_count else 0,
            "evaluation_success_rate": success_count / total_students if total_students else 0
        })
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return results, errors


@router.get("/batch/processing-status/{processing_id}")
async def get_processing_status(processing_id: str):
    """Get real-time processing status for a batch operation."""
    if processing_id not in _processing_stats:
        raise HTTPException(status_code=404, detail="Processing ID not found")
    
    stats = _processing_stats[processing_id].copy()
    
    # Add current performance metrics
    if stats["status"] not in ["completed", "failed"]:
        current_time = time.time()
        elapsed = current_time - stats["start_time"]
        processed = stats.get("processed_files", 0)
        total = stats.get("total_files", 1)
        
        stats.update({
            "elapsed_time": elapsed,
            "progress_percentage": (processed / total) * 100 if total > 0 else 0,
            "estimated_remaining": (elapsed / processed) * (total - processed) if processed > 0 else None
        })
    
    return stats


@router.post("/batch/preload-cache")
async def preload_cache(request: ProcessFolderRequest):
    """
    Preload cache with OCR results for faster subsequent processing.
    Useful for repeated processing of the same dataset with different answer keys.
    """
    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)
    
    if not all_files:
        raise HTTPException(status_code=404, detail="No files found in the Drive folder.")
    
    _, student_sheets = drive_service.separate_files(all_files)
    
    if not student_sheets:
        raise HTTPException(status_code=404, detail="No student sheets found.")
    
    # Process files for caching only
    temp_dir = tempfile.mkdtemp(prefix="cache_preload_")
    cached_count = 0
    processed_count = 0
    
    try:
        # Download and process in small batches
        batch_size = 10
        for i in range(0, len(student_sheets), batch_size):
            batch = student_sheets[i:i + batch_size]
            
            # Download batch
            download_tasks = []
            for j, sheet in enumerate(batch):
                local_path = os.path.join(temp_dir, f"preload_{i+j}_{sheet['name']}")
                download_tasks.append(
                    asyncio.to_thread(drive_service.download_file, sheet["id"], local_path)
                )
            
            download_results = await asyncio.gather(*download_tasks)
            
            # Process uncached files
            for j, (sheet, success) in enumerate(zip(batch, download_results)):
                if success:
                    local_path = os.path.join(temp_dir, f"preload_{i+j}_{sheet['name']}")
                    
                    # Check if already cached
                    cached_result = await cache_service.get_cached_ocr_result(local_path)
                    if cached_result:
                        cached_count += 1
                    else:
                        # Process and cache
                        try:
                            result = await optimized_ocr.process_single_image(local_path)
                            if "error" not in result:
                                await cache_service.cache_ocr_result(local_path, result)
                            processed_count += 1
                        except Exception as e:
                            print(f"Preload error for {sheet['name']}: {e}")
    
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    cache_stats = await cache_service.get_cache_stats()
    
    return {
        "message": "Cache preload completed",
        "files_already_cached": cached_count,
        "files_newly_processed": processed_count,
        "total_files": len(student_sheets),
        "cache_stats": cache_stats
    }


@router.delete("/batch/clear-processing-stats")
async def clear_processing_stats():
    """Clear old processing statistics to free memory."""
    global _processing_stats
    
    # Keep only recent stats (last 24 hours)
    current_time = time.time()
    cutoff_time = current_time - (24 * 3600)
    
    old_count = len(_processing_stats)
    _processing_stats = {
        k: v for k, v in _processing_stats.items()
        if v.get("start_time", 0) > cutoff_time
    }
    new_count = len(_processing_stats)
    
    return {
        "message": f"Cleared {old_count - new_count} old processing stats",
        "remaining_stats": new_count
    }