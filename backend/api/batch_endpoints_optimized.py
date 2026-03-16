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


async def _process_sheets_optimized(
    student_sheets: List[Dict], 
    answer_key,
    processing_id: str
) -> tuple[List, List]:
    """
    Optimized processing pipeline with caching and batch operations.
    """
    results = []
    errors = []
    
    # Step 1: Download files in parallel
    _processing_stats[processing_id]["status"] = "downloading_files"
    temp_dir = tempfile.mkdtemp(prefix="sheets_opt_")
    
    try:
        # Parallel download with progress tracking
        downloaded_files = await _download_files_with_progress(
            student_sheets, temp_dir, processing_id
        )
        
        # Step 2: OCR processing with intelligent caching
        _processing_stats[processing_id]["status"] = "ocr_processing"
        ocr_results = await _process_ocr_with_caching(
            downloaded_files, processing_id
        )
        
        # Step 3: Batch evaluation
        _processing_stats[processing_id]["status"] = "batch_evaluation"
        valid_ocr_results = []
        
        for ocr_result in ocr_results:
            if "error" in ocr_result:
                errors.append({
                    "file": ocr_result.get("file_name", "unknown"),
                    "error": ocr_result["error"]
                })
            else:
                valid_ocr_results.append(ocr_result)
        
        if valid_ocr_results:
            # Use optimized batch evaluation
            batch_results, batch_stats = await batch_match_and_score(
                answer_key,
                valid_ocr_results,
                use_multiprocessing=len(valid_ocr_results) > 15
            )
            
            results.extend(batch_results)
            
            # Batch database write
            if batch_results:
                _processing_stats[processing_id]["status"] = "database_write"
                await batch_write_student_results(
                    batch_results,
                    optimized_db,
                    exam_id=f"optimized_batch_{processing_id}"
                )
            
            # Update processing stats
            _processing_stats[processing_id].update({
                "batch_evaluation_time": batch_stats.processing_time,
                "avg_evaluation_time": batch_stats.avg_time_per_student,
                "evaluation_success_rate": batch_stats.successful_evaluations / batch_stats.total_students
            })
        
        _processing_stats[processing_id]["processed_files"] = len(results)
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return results, errors


async def _download_files_with_progress(
    student_sheets: List[Dict], 
    temp_dir: str, 
    processing_id: str
) -> List[tuple]:
    """Download files with progress tracking."""
    async def _download_single(sheet_file, index):
        local_path = os.path.join(temp_dir, f"{index}_{sheet_file['name']}")
        success = await asyncio.to_thread(
            drive_service.download_file, 
            sheet_file["id"], 
            local_path
        )
        return (local_path, sheet_file, success, index)
    
    # Download in batches to avoid overwhelming the API
    batch_size = 20
    downloaded_files = []
    
    for i in range(0, len(student_sheets), batch_size):
        batch = student_sheets[i:i + batch_size]
        batch_tasks = [
            _download_single(sheet, i + j) 
            for j, sheet in enumerate(batch)
        ]
        
        batch_results = await asyncio.gather(*batch_tasks)
        downloaded_files.extend([
            (lp, sf, idx) for lp, sf, success, idx in batch_results if success
        ])
        
        # Update progress
        _processing_stats[processing_id]["downloaded_files"] = len(downloaded_files)
    
    return downloaded_files


async def _process_ocr_with_caching(
    downloaded_files: List[tuple], 
    processing_id: str
) -> List[Dict]:
    """Process OCR with intelligent caching."""
    ocr_results = []
    cache_hits = 0
    cache_misses = 0
    
    # Check cache for each file
    cached_results = []
    files_to_process = []
    
    for local_path, sheet_file, index in downloaded_files:
        cached_result = await cache_service.get_cached_ocr_result(local_path)
        if cached_result:
            cached_result["index"] = index
            cached_result["file_name"] = sheet_file["name"]
            cached_results.append(cached_result)
            cache_hits += 1
        else:
            files_to_process.append((local_path, sheet_file, index))
            cache_misses += 1
    
    # Update cache stats
    _processing_stats[processing_id].update({
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate": cache_hits / (cache_hits + cache_misses) if (cache_hits + cache_misses) > 0 else 0
    })
    
    # Process uncached files
    if files_to_process:
        image_paths = [lp for lp, _, _ in files_to_process]
        
        # Use multi-region OCR for large batches
        if len(files_to_process) > 50:
            print(f"🌍 Using multi-region OCR for {len(files_to_process)} files")
            fresh_results = await multi_region_ocr.process_batch_multi_region(
                image_paths,
                target_time_minutes=4.0
            )
        else:
            print(f"🚀 Using optimized OCR for {len(files_to_process)} files")
            fresh_results = await optimized_ocr.process_batch_optimized(
                image_paths,
                target_time_minutes=5.0
            )
        
        # Cache fresh results and add metadata
        for i, result in enumerate(fresh_results):
            if i < len(files_to_process):
                local_path, sheet_file, index = files_to_process[i]
                result["index"] = index
                result["file_name"] = sheet_file["name"]
                
                # Cache the result if successful
                if "error" not in result:
                    await cache_service.cache_ocr_result(local_path, result)
        
        ocr_results.extend(fresh_results)
    
    # Combine cached and fresh results
    ocr_results.extend(cached_results)
    
    # Sort by index to maintain order
    ocr_results.sort(key=lambda x: x.get("index", 0))
    
    return ocr_results


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