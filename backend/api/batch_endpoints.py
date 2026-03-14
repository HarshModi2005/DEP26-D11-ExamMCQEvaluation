#!/usr/bin/env python3
"""
Batch Processing API Endpoints for High-Throughput OCR
======================================================
New endpoints optimized for 300+ RPS processing using multi-region OCR service
"""

import asyncio
import os
import tempfile
import shutil
import time
from typing import List, Dict
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from ..services.multi_region_ocr_service import MultiRegionOCRService
from ..services.drive_service import DriveService
from ..services.evaluation_service import EvaluationService
from ..services.answer_key_service import AnswerKeyService

# Initialize services
router = APIRouter(prefix="/api/batch", tags=["batch"])
multi_ocr_service = MultiRegionOCRService()
drive_service = DriveService()
answer_key_service = AnswerKeyService()

# Global state
_current_answer_key = None
_batch_results = {}

class BatchProcessRequest(BaseModel):
    folder_url: str
    max_concurrent: int = 300
    use_multi_region: bool = True
    batch_size: int = 50

class BatchStatusResponse(BaseModel):
    batch_id: str
    status: str  # "processing", "completed", "failed"
    total_files: int
    processed_files: int
    success_count: int
    error_count: int
    start_time: float
    end_time: float = None
    estimated_completion: float = None
    results: List[Dict] = []

@router.get("/health")
async def get_batch_health():
    """Get health status of multi-region OCR service"""
    try:
        health_results = await multi_ocr_service.health_check()
        stats = multi_ocr_service.get_stats()
        
        return {
            "status": "healthy",
            "endpoints": health_results,
            "stats": stats,
            "timestamp": time.time()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@router.post("/process-folder")
async def process_folder_batch(request: BatchProcessRequest, background_tasks: BackgroundTasks):
    """
    Process entire Drive folder using high-throughput batch processing
    
    This endpoint:
    1. Downloads all images in parallel
    2. Processes OCR using multi-region service
    3. Scores against answer key
    4. Returns results
    """
    global _current_answer_key
    
    start_time = time.time()
    batch_id = f"batch_{int(start_time)}"
    
    try:
        # Extract folder ID and list files
        folder_id = DriveService.extract_folder_id(request.folder_url)
        all_files = drive_service.list_all_files_in_folder(folder_id)
        
        if not all_files:
            raise HTTPException(status_code=404, detail="No files found in the Drive folder")
        
        # Separate answer key and student sheets
        answer_key_files, student_sheets = drive_service.separate_files(all_files)
        
        # Load answer key if not already loaded
        if _current_answer_key is None:
            if not answer_key_files:
                raise HTTPException(
                    status_code=400,
                    detail="No answer key found. Please include an answer key file in the folder."
                )
            
            temp_dir = tempfile.mkdtemp(prefix="ak_")
            try:
                local_path = drive_service.download_answer_key(answer_key_files[0], temp_dir)
                mime_type = answer_key_files[0].get("mimeType", "")
                _current_answer_key = answer_key_service.extract_answer_key(local_path, mime_type)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        
        if not student_sheets:
            raise HTTPException(
                status_code=404,
                detail="No student answer sheets found in the folder"
            )
        
        # Initialize batch status
        _batch_results[batch_id] = {
            "batch_id": batch_id,
            "status": "processing",
            "total_files": len(student_sheets),
            "processed_files": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": start_time,
            "results": []
        }
        
        # Process in background for large batches
        if len(student_sheets) > 10:
            background_tasks.add_task(
                _process_batch_background,
                batch_id,
                student_sheets,
                request.max_concurrent,
                request.batch_size
            )
            
            return {
                "batch_id": batch_id,
                "status": "processing",
                "message": f"Processing {len(student_sheets)} files in background",
                "check_status_url": f"/api/batch/status/{batch_id}"
            }
        else:
            # Process small batches synchronously
            results = await _process_student_sheets_batch(
                student_sheets, request.max_concurrent, request.batch_size
            )
            
            _batch_results[batch_id].update({
                "status": "completed",
                "processed_files": len(results),
                "success_count": len([r for r in results if "error" not in r]),
                "error_count": len([r for r in results if "error" in r]),
                "end_time": time.time(),
                "results": results
            })
            
            return _batch_results[batch_id]
    
    except Exception as e:
        if batch_id in _batch_results:
            _batch_results[batch_id]["status"] = "failed"
            _batch_results[batch_id]["error"] = str(e)
        
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")

@router.get("/status/{batch_id}")
async def get_batch_status(batch_id: str):
    """Get status of a batch processing job"""
    if batch_id not in _batch_results:
        raise HTTPException(status_code=404, detail="Batch ID not found")
    
    batch_info = _batch_results[batch_id]
    
    # Calculate estimated completion time
    if batch_info["status"] == "processing" and batch_info["processed_files"] > 0:
        elapsed = time.time() - batch_info["start_time"]
        rate = batch_info["processed_files"] / elapsed
        remaining = batch_info["total_files"] - batch_info["processed_files"]
        batch_info["estimated_completion"] = time.time() + (remaining / rate)
    
    return batch_info

@router.delete("/status/{batch_id}")
async def delete_batch_results(batch_id: str):
    """Delete batch results to free memory"""
    if batch_id not in _batch_results:
        raise HTTPException(status_code=404, detail="Batch ID not found")
    
    del _batch_results[batch_id]
    return {"message": f"Batch {batch_id} results deleted"}

@router.get("/stats")
async def get_ocr_stats():
    """Get OCR service statistics"""
    try:
        stats = multi_ocr_service.get_stats()
        return {
            "service_stats": stats,
            "active_batches": len(_batch_results),
            "batch_statuses": {
                bid: info["status"] for bid, info in _batch_results.items()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

@router.post("/test-throughput")
async def test_throughput(num_requests: int = 100, max_concurrent: int = 300):
    """
    Test OCR throughput with dummy requests
    Useful for performance testing and quota validation
    """
    if num_requests > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 test requests allowed")
    
    start_time = time.time()
    
    # Create dummy image paths (you'd need actual test images)
    test_image = "test_answer_sheet.jpg"  # Should exist in your test data
    if not os.path.exists(test_image):
        raise HTTPException(status_code=404, detail="Test image not found")
    
    image_paths = [test_image] * num_requests
    
    try:
        results = await multi_ocr_service.process_batch(image_paths, max_concurrent)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        success_count = len([r for r in results if "error" not in r])
        error_count = len([r for r in results if "error" in r])
        
        rps = num_requests / total_time if total_time > 0 else 0
        
        return {
            "test_results": {
                "total_requests": num_requests,
                "success_count": success_count,
                "error_count": error_count,
                "total_time_seconds": round(total_time, 2),
                "requests_per_second": round(rps, 1),
                "average_response_time": round(total_time / num_requests, 3),
                "target_300_rps": rps >= 300
            },
            "service_stats": multi_ocr_service.get_stats(),
            "sample_results": results[:3]  # First 3 results as samples
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Throughput test failed: {str(e)}")

# Background processing functions

async def _process_batch_background(batch_id: str, student_sheets: List[Dict], 
                                   max_concurrent: int, batch_size: int):
    """Process batch in background"""
    try:
        results = await _process_student_sheets_batch(student_sheets, max_concurrent, batch_size)
        
        _batch_results[batch_id].update({
            "status": "completed",
            "processed_files": len(results),
            "success_count": len([r for r in results if "error" not in r]),
            "error_count": len([r for r in results if "error" in r]),
            "end_time": time.time(),
            "results": results
        })
        
    except Exception as e:
        _batch_results[batch_id].update({
            "status": "failed",
            "error": str(e),
            "end_time": time.time()
        })

async def _process_student_sheets_batch(student_sheets: List[Dict], 
                                       max_concurrent: int, batch_size: int) -> List[Dict]:
    """Process student sheets in batches"""
    global _current_answer_key
    
    temp_dir = tempfile.mkdtemp(prefix="batch_sheets_")
    all_results = []
    
    try:
        # Step 1: Download all images in parallel
        download_tasks = []
        for sheet_file in student_sheets:
            local_path = os.path.join(temp_dir, sheet_file["name"])
            task = asyncio.create_task(
                _download_file_async(sheet_file["id"], local_path, sheet_file)
            )
            download_tasks.append(task)
        
        # Wait for downloads with progress tracking
        download_results = []
        for task in asyncio.as_completed(download_tasks):
            result = await task
            download_results.append(result)
        
        # Filter successful downloads
        successful_downloads = [
            (local_path, sheet_file) for local_path, sheet_file, success in download_results if success
        ]
        
        if not successful_downloads:
            raise Exception("No files downloaded successfully")
        
        # Step 2: Process OCR in batches
        image_paths = [local_path for local_path, _ in successful_downloads]
        file_mapping = {local_path: sheet_file for local_path, sheet_file in successful_downloads}
        
        # Split into batches
        batches = [image_paths[i:i+batch_size] for i in range(0, len(image_paths), batch_size)]
        
        for batch_paths in batches:
            # Process batch with OCR
            ocr_results = await multi_ocr_service.process_batch(batch_paths, max_concurrent)
            
            # Score each result
            for image_path, ocr_result in zip(batch_paths, ocr_results):
                sheet_file = file_mapping[image_path]
                
                if "error" not in ocr_result:
                    try:
                        # Score against answer key
                        student_result = EvaluationService.match_and_score(
                            _current_answer_key, ocr_result
                        )
                        
                        result_dict = {
                            "file_name": sheet_file["name"],
                            "file_id": sheet_file["id"],
                            "entry_number": student_result.entry_number,
                            "name": student_result.name,
                            "total_score": student_result.total_score,
                            "max_score": student_result.max_score,
                            "percentage": round((student_result.total_score / student_result.max_score) * 100, 1) if student_result.max_score > 0 else 0,
                            "correct_answers": student_result.correct_answers,
                            "wrong_answers": student_result.wrong_answers,
                            "unanswered": student_result.unanswered,
                            "processing_time": ocr_result.get("processing_time", 0),
                            "endpoint": ocr_result.get("endpoint", "unknown")
                        }
                        
                        all_results.append(result_dict)
                        
                    except Exception as e:
                        all_results.append({
                            "file_name": sheet_file["name"],
                            "file_id": sheet_file["id"],
                            "error": f"Scoring failed: {str(e)}",
                            "ocr_result": ocr_result
                        })
                else:
                    all_results.append({
                        "file_name": sheet_file["name"],
                        "file_id": sheet_file["id"],
                        "error": ocr_result["error"],
                        "endpoint": ocr_result.get("endpoint", "unknown")
                    })
        
        return all_results
    
    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

async def _download_file_async(file_id: str, local_path: str, sheet_file: Dict) -> tuple:
    """Download file asynchronously"""
    try:
        success = drive_service.download_file(file_id, local_path)
        return local_path, sheet_file, success
    except Exception as e:
        return local_path, sheet_file, False

# Cleanup on shutdown
@router.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on shutdown"""
    await multi_ocr_service.cleanup()
