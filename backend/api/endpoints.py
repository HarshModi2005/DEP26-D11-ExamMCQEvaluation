"""
API Endpoints
=============
Routes for the objective answer sheet evaluation pipeline.
Auth is handled entirely by Supabase on the frontend.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import Response
from models import (
    Student, Submission, EvaluationResult,
    AnswerKey, StudentResult, PipelineSummary, SheetUpdateSummary,
    ProcessFolderRequest, ExportToSheetsRequest, FullPipelineRequest,
)
from services.drive_service import DriveService
from services.ocr_service import OCRService
from services.optimized_ocr_service import OptimizedOCRService
from services.evaluation_service import EvaluationService
from services.answer_key_service import AnswerKeyService
from services.sheets_service import SheetsService
from services.batch_evaluation_service import BatchEvaluationService, batch_match_and_score
from services.result_cache_service import ResultCacheService, get_cached_or_process_ocr, get_cached_or_evaluate
from services.optimized_database_service import OptimizedDatabaseService, batch_write_student_results
from database import Database
import asyncio
import uuid
import os
import json
import tempfile
import shutil
import zipfile
from typing import Optional, List

router = APIRouter()
db = Database()
optimized_db = OptimizedDatabaseService()    # High-performance database service
cache_service = ResultCacheService()         # Result caching service
batch_eval_service = BatchEvaluationService(optimized_db)  # Batch evaluation service
drive_service = DriveService()
ocr_service = OCRService()                   # kept for the legacy /process-file endpoint
optimized_ocr = OptimizedOCRService()        # used for the main /process-drive-folder pipeline
eval_service = EvaluationService()
answer_key_service = AnswerKeyService()
sheets_service = SheetsService()

# ──────────────────────────────────────
#  In-memory state for the current exam session
# ──────────────────────────────────────

# The currently loaded answer key (set via drive extraction or manual upload)
_current_answer_key: Optional[AnswerKey] = None
# Scored results from the latest pipeline run
_current_results: list[StudentResult] = []


# ═══════════════════════════════════════
#  HEALTH & STATUS
# ═══════════════════════════════════════

@router.get("/status")
async def get_status():
    # Get cache and database stats
    cache_stats = await cache_service.get_cache_stats()
    db_stats = await optimized_db.get_performance_analytics()
    
    return {
        "status": "Service operational",
        "answer_key_loaded": _current_answer_key is not None,
        "answer_key_questions": _current_answer_key.total_questions if _current_answer_key else 0,
        "results_count": len(_current_results),
        "cache_stats": cache_stats,
        "database_stats": db_stats,
        "optimization_features": {
            "batch_evaluation": True,
            "result_caching": True,
            "connection_pooling": True,
            "async_processing": True
        }
    }


@router.get("/performance")
async def get_performance_metrics():
    """Get detailed performance metrics for optimization monitoring."""
    cache_stats = await cache_service.get_cache_stats()
    db_stats = await optimized_db.get_performance_analytics()
    
    return {
        "cache_performance": cache_stats,
        "database_performance": db_stats,
        "current_session": {
            "answer_key_loaded": _current_answer_key is not None,
            "results_in_memory": len(_current_results),
            "total_questions": _current_answer_key.total_questions if _current_answer_key else 0
        },
        "optimization_recommendations": _get_optimization_recommendations(cache_stats, db_stats)
    }


def _get_optimization_recommendations(cache_stats: dict, db_stats: dict) -> list:
    """Generate optimization recommendations based on current metrics."""
    recommendations = []
    
    # Cache recommendations
    cache_size_mb = cache_stats.get('total_size_mb', 0)
    if cache_size_mb > 400:  # Near 500MB limit
        recommendations.append({
            "type": "cache",
            "priority": "medium",
            "message": f"Cache size is {cache_size_mb:.1f}MB, consider cleanup",
            "action": "Run cache cleanup or increase cache limit"
        })
    
    cache_entries = cache_stats.get('total_entries', 0)
    if cache_entries < 10:
        recommendations.append({
            "type": "cache",
            "priority": "low", 
            "message": "Low cache utilization detected",
            "action": "Cache will improve performance as more files are processed"
        })
    
    # Database recommendations
    db_size_mb = db_stats.get('database_size_mb', 0)
    if db_size_mb > 100:
        recommendations.append({
            "type": "database",
            "priority": "low",
            "message": f"Database size is {db_size_mb:.1f}MB",
            "action": "Consider running VACUUM during maintenance window"
        })
    
    # Connection pool recommendations
    pool_stats = db_stats.get('connection_pool', {})
    hit_ratio = pool_stats.get('hit_ratio', 0)
    if hit_ratio < 0.8:
        recommendations.append({
            "type": "database",
            "priority": "medium",
            "message": f"Connection pool hit ratio is {hit_ratio:.1%}",
            "action": "Consider increasing pool size for better performance"
        })
    
    # Performance recommendations
    batch_ratio = db_stats.get('service_stats', {}).get('batch_ratio', 0)
    if batch_ratio < 0.5:
        recommendations.append({
            "type": "performance",
            "priority": "high",
            "message": f"Only {batch_ratio:.1%} of operations are batched",
            "action": "Use batch processing endpoints for better performance"
        })
    
    return recommendations


# NOTE: Authentication is handled entirely by Supabase on the frontend.
# No backend auth endpoints needed — the frontend talks to Supabase directly.


# ═══════════════════════════════════════
#  PHASE 1 — DRIVE FOLDER INGESTION
# ═══════════════════════════════════════

@router.post("/sync-drive")
def sync_drive(folder_id: str):
    """
    Lists all files in a Google Drive folder (legacy endpoint — images only).
    """
    folder_id = DriveService.extract_folder_id(folder_id)
    files = drive_service.list_files_in_folder(folder_id)
    return {"files_found": len(files), "files": files}


@router.post("/scan-drive-folder")
def scan_drive_folder(request: ProcessFolderRequest):
    """
    Scans a Drive folder and separates answer key from student sheets.
    Does NOT process anything — just shows what's in the folder.
    """
    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)

    if not all_files:
        raise HTTPException(status_code=404, detail="No files found in the Drive folder.")

    answer_key_files, student_sheets = drive_service.separate_files(all_files)

    return {
        "total_files": len(all_files),
        "answer_key_files": answer_key_files,
        "student_sheets": student_sheets,
        "answer_key_count": len(answer_key_files),
        "student_sheet_count": len(student_sheets),
    }


# ═══════════════════════════════════════
#  PHASE 2A — ANSWER KEY MANAGEMENT
# ═══════════════════════════════════════

@router.get("/answer-key")
def get_current_answer_key():
    """Returns the currently loaded answer key."""
    if _current_answer_key is None:
        raise HTTPException(status_code=404, detail="No answer key is currently loaded.")
    return _current_answer_key.model_dump()


@router.post("/answer-key/extract-from-drive")
def extract_answer_key_from_drive(request: ProcessFolderRequest):
    """
    Extracts the answer key from a Drive folder.
    Looks for a file named 'answer_key' (case-insensitive).
    """
    global _current_answer_key

    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)

    if not all_files:
        raise HTTPException(status_code=404, detail="No files found in the Drive folder.")

    answer_key_files, _ = drive_service.separate_files(all_files)

    if not answer_key_files:
        raise HTTPException(
            status_code=404,
            detail=(
                "No answer key file found. "
                "Please name your answer key file with 'answer_key' in the name "
                "(e.g., 'answer_key.csv', 'Answer_Key.xlsx', 'answer_key.pdf')."
            )
        )

    # Use the first answer key file found
    ak_file = answer_key_files[0]
    if len(answer_key_files) > 1:
        print(f"⚠️  Multiple answer key files found, using: {ak_file['name']}")

    # Download and parse
    temp_dir = tempfile.mkdtemp(prefix="ak_")
    try:
        local_path = drive_service.download_answer_key(ak_file, temp_dir)
        mime_type = ak_file.get("mimeType", "")
        _current_answer_key = answer_key_service.extract_answer_key(local_path, mime_type)

        return {
            "message": "Answer key extracted successfully",
            "source_file": ak_file["name"],
            "total_questions": _current_answer_key.total_questions,
            "answer_key": _current_answer_key.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract answer key: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/answer-key/upload")
async def upload_answer_key(file: UploadFile = File(...)):
    """
    Manual upload of an answer key file.
    Supports: CSV, XLSX, PDF, PNG, JPG, TXT
    """
    global _current_answer_key

    temp_dir = tempfile.mkdtemp(prefix="ak_upload_")
    try:
        # Save uploaded file
        local_path = os.path.join(temp_dir, file.filename)
        with open(local_path, "wb") as f:
            content = await file.read()
            f.write(content)

        _current_answer_key = answer_key_service.extract_answer_key(
            local_path, file.content_type
        )

        return {
            "message": "Answer key uploaded and parsed",
            "filename": file.filename,
            "total_questions": _current_answer_key.total_questions,
            "answer_key": _current_answer_key.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse answer key: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/answer-key/set-manual")
def set_answer_key_manual(answers: dict):
    """
    Manually set the answer key via JSON body.
    
    Expected format:
    {
        "answers": {"1": "A", "2": "C", "3": "B", ...},
        "marks_per_question": 1,
        "negative_marking": 0
    }
    """
    global _current_answer_key
    from models import AnswerKeyEntry

    raw_answers = answers.get("answers", {})
    marks = float(answers.get("marks_per_question", 1.0))
    negative = float(answers.get("negative_marking", 0.0))

    parsed = {}
    for k, v in raw_answers.items():
        q_num = int(k)
        parsed[q_num] = AnswerKeyEntry(correct_option=str(v).strip().upper(), marks=marks)

    _current_answer_key = AnswerKey(
        total_questions=len(parsed),
        answers=parsed,
        negative_marking=negative,
        metadata={"source": "manual_input"}
    )

    return {
        "message": "Answer key set manually",
        "total_questions": _current_answer_key.total_questions,
    }


@router.post("/process-zip")
async def process_zip_upload(
    file: UploadFile = File(...), 
    force_reprocess: bool = False,
    extract_answer_key: bool = True
):
    """
    Upload and process a ZIP file containing answer key and student answer sheets.
    
    Args:
        file: ZIP file containing answer key and student sheets
        force_reprocess: If True, bypass cache and reprocess all files
        extract_answer_key: If True, auto-extract answer key from ZIP
    
    Returns:
        Pipeline summary with results and processing stats
    """
    global _current_answer_key, _current_results

    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    temp_dir = tempfile.mkdtemp(prefix="zip_upload_")
    extract_dir = os.path.join(temp_dir, "extracted")
    
    try:
        # Save uploaded ZIP
        zip_path = os.path.join(temp_dir, file.filename)
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Extract ZIP
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Get all extracted files
        all_files = []
        for root, dirs, files in os.walk(extract_dir):
            for filename in files:
                if not filename.startswith('.') and not filename.startswith('__'):  # Skip hidden/system files
                    file_path = os.path.join(root, filename)
                    # Create file info dict similar to Drive API format
                    all_files.append({
                        "id": file_path,  # Use local path as ID
                        "name": filename,
                        "mimeType": _guess_mime_type(filename),
                        "local_path": file_path
                    })

        if not all_files:
            raise HTTPException(status_code=404, detail="No valid files found in ZIP archive")

        # Separate answer key from student sheets
        answer_key_files, student_sheets = drive_service.separate_files(all_files)

        # Step 1: Extract answer key if requested.
        # If the ZIP doesn't contain an answer key, we can still proceed as long as one is already loaded.
        if extract_answer_key and (_current_answer_key is None or force_reprocess):
            if not answer_key_files:
                if _current_answer_key is not None and not force_reprocess:
                    print("ℹ️  No answer key found in ZIP — using currently loaded answer key.")
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "No answer key file found in ZIP. Either:\n"
                            "- include a file with 'answer_key' in the name, OR\n"
                            "- load an answer key first (Drive/manual/upload), OR\n"
                            "- call /api/process-zip with extract_answer_key=false to skip ZIP key extraction."
                        )
                    )

            ak_file = answer_key_files[0]
            if len(answer_key_files) > 1:
                print(f"⚠️  Multiple answer key files found, using: {ak_file['name']}")

            try:
                local_path = ak_file["local_path"]
                mime_type = ak_file.get("mimeType", "")
                _current_answer_key = answer_key_service.extract_answer_key(local_path, mime_type)
                print(f"✅ Answer key extracted from ZIP: {_current_answer_key.total_questions} questions")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to extract answer key: {str(e)}")

        if not _current_answer_key:
            raise HTTPException(
                status_code=400,
                detail="No answer key loaded. Set extract_answer_key=true or upload answer key separately."
            )

        if not student_sheets:
            raise HTTPException(
                status_code=404,
                detail="No student answer sheets found in ZIP (only answer key found)."
            )

        # Step 2: Process student sheets with caching support
        _current_results = []
        errors = []
        cache_hits = 0
        processed_count = 0

        print(f"\n🚀 Processing {len(student_sheets)} student sheets from ZIP...")
        print(f"   Force reprocess: {force_reprocess}")

        # Process each student sheet
        for idx, sheet_file in enumerate(student_sheets):
            file_name = sheet_file["name"]
            local_path = sheet_file["local_path"]
            
            print(f"\n📄 Processing [{idx+1}/{len(student_sheets)}]: {file_name}")

            try:
                # Check cache first (unless force_reprocess)
                if not force_reprocess:
                    cached_result = await cache_service.get_cached_evaluation_result(
                        local_path, _current_answer_key.model_dump()
                    )
                    if cached_result:
                        # Reconstruct StudentResult from cached data
                        from models import StudentResult
                        student_result = StudentResult(**cached_result)
                        _current_results.append(student_result)
                        cache_hits += 1
                        print(f"  🎯 Cache hit: {student_result.entry_number} — {student_result.name}")
                        continue

                # OCR Extract
                extracted = await get_cached_or_process_ocr(
                    local_path,
                    lambda path: asyncio.to_thread(ocr_service.extract_objective_sheet, path),
                    cache_service if not force_reprocess else None
                )

                if "error" in extracted:
                    errors.append({"file": file_name, "error": extracted["error"]})
                    continue

                # Score
                student_result = EvaluationService.match_and_score(_current_answer_key, extracted)
                _current_results.append(student_result)
                processed_count += 1

                # Cache the result
                if not force_reprocess:
                    await cache_service.cache_evaluation_result(
                        local_path, extracted, student_result.model_dump(), _current_answer_key.model_dump()
                    )

                print(f"  ✅ {student_result.entry_number} — {student_result.name}: "
                      f"{student_result.total_score}/{student_result.max_score}")

                # Also save to DB
                db.add_student(Student(
                    id=student_result.entry_number,
                    name=student_result.name,
                    roll_number=student_result.entry_number
                ))

            except Exception as e:
                errors.append({"file": file_name, "error": str(e)})
                print(f"  ❌ Error: {e}")

        # Batch write results to optimized database
        if _current_results:
            await batch_write_student_results(
                _current_results,
                optimized_db,
                exam_id="zip_upload_processing"
            )

        return PipelineSummary(
            total_students_processed=len(_current_results),
            answer_key_source=_current_answer_key.metadata.get("source_file", "zip_upload"),
            results=_current_results,
            errors=errors,
            processing_stats={
                "cache_hits": cache_hits,
                "newly_processed": processed_count,
                "force_reprocess": force_reprocess,
                "zip_filename": file.filename
            }
        ).model_dump()

    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def _guess_mime_type(filename: str) -> str:
    """Guess MIME type from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.csv': 'text/csv',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.txt': 'text/plain',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    }
    return mime_map.get(ext, 'application/octet-stream')


# ═══════════════════════════════════════
#  PHASE 2B — PROCESS STUDENT SHEETS
# ═══════════════════════════════════════

@router.post("/process-drive-folder")
async def process_drive_folder(request: ProcessFolderRequest, force_reprocess: bool = False):
    """
    Main endpoint: Process all student answer sheets in a Drive folder.

    1. Lists all files in the folder
    2. Separates answer key from student sheets
    3. Extracts answer key (if not already loaded)
    4. Downloads all student sheets in parallel
    5. OCR-processes the entire batch concurrently via OptimizedOCRService
    6. Scores each result against the answer key
    7. Returns all results
    
    Args:
        request: Drive folder processing request
        force_reprocess: If True, bypass cache and reprocess all files
    """
    global _current_answer_key, _current_results

    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)

    if not all_files:
        raise HTTPException(status_code=404, detail="No files found in the Drive folder.")

    answer_key_files, student_sheets = drive_service.separate_files(all_files)

    # Step 1: Extract answer key if not already loaded
    if _current_answer_key is None:
        if not answer_key_files:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No answer key loaded and no answer_key file found in the folder. "
                    "Please upload an answer key first via /api/answer-key/upload or "
                    "include a file named 'answer_key' in your Drive folder."
                )
            )

        temp_dir = tempfile.mkdtemp(prefix="ak_")
        try:
            local_path = drive_service.download_answer_key(answer_key_files[0], temp_dir)
            mime_type = answer_key_files[0].get("mimeType", "")
            _current_answer_key = answer_key_service.extract_answer_key(local_path, mime_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract answer key: {str(e)}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if not student_sheets:
        raise HTTPException(
            status_code=404,
            detail="No student answer sheets found in the folder (only the answer key was found)."
        )

    # Step 2: Download all sheets in parallel
    _current_results = []
    errors = []
    temp_dir = tempfile.mkdtemp(prefix="sheets_")

    try:
        # --- Parallel download ---
        async def _download(sheet_file):
            local_path = os.path.join(temp_dir, sheet_file["name"])
            ok = await asyncio.to_thread(
                drive_service.download_file, sheet_file["id"], local_path
            )
            return local_path, sheet_file, ok

        download_results = await asyncio.gather(*[_download(sf) for sf in student_sheets])

        successful_downloads = [
            (lp, sf) for lp, sf, ok in download_results if ok
        ]
        failed_downloads = [
            sf for _, sf, ok in download_results if not ok
        ]
        for sf in failed_downloads:
            errors.append({"file": sf["name"], "error": "Download failed"})

        if not successful_downloads:
            raise HTTPException(status_code=500, detail="All downloads failed.")

        # --- Parallel OCR via OptimizedOCRService ---
        image_paths = [lp for lp, _ in successful_downloads]
        file_map = {lp: sf for lp, sf in successful_downloads}

        print(f"\n🚀 Running parallel OCR on {len(image_paths)} sheets...")
        ocr_results = await optimized_ocr.process_batch_optimized(
            image_paths,
            target_time_minutes=5.0,
        )

        # --- Optimized Batch Scoring ---
        print(f"\n🧮 Running optimized batch evaluation on {len(ocr_results)} results...")
        
        # Filter successful OCR results
        valid_ocr_results = []
        for ocr_result in ocr_results:
            idx = ocr_result.get("index", 0)
            image_path = image_paths[idx] if idx < len(image_paths) else None
            sheet_file = file_map.get(image_path, {})
            file_name = sheet_file.get("name", f"image_{idx}")

            if "error" in ocr_result:
                errors.append({"file": file_name, "error": ocr_result["error"]})
            else:
                # Add file metadata to OCR result for better error tracking
                ocr_result["_file_name"] = file_name
                ocr_result["_image_path"] = image_path
                valid_ocr_results.append(ocr_result)
        
        if valid_ocr_results:
            try:
                # Use batch evaluation service for optimized processing
                batch_results, batch_stats = await batch_match_and_score(
                    _current_answer_key, 
                    valid_ocr_results,
                    use_multiprocessing=len(valid_ocr_results) > 20
                )
                
                _current_results.extend(batch_results)
                
                # Batch write to optimized database
                if batch_results:
                    await batch_write_student_results(
                        batch_results, 
                        optimized_db,
                        exam_id="drive_folder_processing"
                    )
                
                # Print summary
                print(f"  ✅ Batch processed {len(batch_results)} students in {batch_stats.processing_time:.2f}s")
                print(f"  📊 Average time per student: {batch_stats.avg_time_per_student:.3f}s")
                
                for result in batch_results:
                    print(f"     {result.entry_number} — {result.name}: "
                          f"{result.total_score}/{result.max_score}")
                
            except Exception as e:
                # Fallback to individual processing if batch fails
                print(f"⚠️  Batch processing failed, falling back to individual processing: {e}")
                
                for ocr_result in valid_ocr_results:
                    try:
                        student_result = EvaluationService.match_and_score(
                            _current_answer_key, ocr_result
                        )
                        _current_results.append(student_result)
                        
                        db.add_student(Student(
                            id=student_result.entry_number,
                            name=student_result.name,
                            roll_number=student_result.entry_number
                        ))
                        
                    except Exception as individual_error:
                        file_name = ocr_result.get("_file_name", "unknown")
                        errors.append({"file": file_name, "error": str(individual_error)})
                        print(f"  ❌ Individual scoring error for {file_name}: {individual_error}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return PipelineSummary(
        total_students_processed=len(_current_results),
        answer_key_source=_current_answer_key.metadata.get("source_file", "loaded"),
        results=_current_results,
        errors=errors,
    ).model_dump()


# ═══════════════════════════════════════
#  PHASE 3 — GOOGLE SHEETS EXPORT
# ═══════════════════════════════════════

@router.post("/export-to-sheets")
def export_to_sheets(request: ExportToSheetsRequest):
    """
    Matches evaluated results with a Google Sheet student list and writes marks.
    
    The Google Sheet should have columns for: Entry Number, Name, Marks
    Column headers are auto-detected.
    
    Entry numbers are matched using the format yyyybbbnnnn (e.g. 2023CSB1122).
    Names are cross-verified — mismatches are flagged but marks are still written.
    """
    # Try in-memory results first, fall back to database
    results_dicts = []
    
    if _current_results:
        results_dicts = [
            {
                "entry_number": r.entry_number,
                "name": r.name,
                "total_score": r.total_score,
                "comments": r.comments,  # Pass comments to sheet
            }
            for r in _current_results
        ]
    else:
        # Pull from database
        db_results = db.get_all_results()
        if db_results:
            for row in db_results:
                # DB results have student_id (which is roll_no) and score
                entry = row.get("student_id", "")
                score = row.get("score", 0)
                # Try to get name from students table
                details_raw = row.get("details")
                name = ""
                if details_raw:
                    try:
                        details = json.loads(details_raw) if isinstance(details_raw, str) else details_raw
                        name = details.get("name", "") or ""
                    except (json.JSONDecodeError, AttributeError):
                        pass
                
                if entry and entry != "temp_unknown":
                    results_dicts.append({
                        "entry_number": entry,
                        "name": name,
                        "total_score": score,
                        "comments": row.get("feedback", ""), 
                    })

    if not results_dicts:
        raise HTTPException(
            status_code=400,
            detail="No results to export. Process some answer sheets first."
        )

    try:
        summary = sheets_service.update_marks(request.sheet_url, results_dicts)
        return summary

    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sheet export failed: {str(e)}")


@router.get("/sheets/preview")
def preview_sheet(sheet_url: str):
    """
    Preview a Google Sheet — shows detected columns and student list.
    Does NOT write anything.
    """
    try:
        data = sheets_service.read_student_list(sheet_url)
        return {
            "sheet_name": data["sheet_name"],
            "columns_detected": data["columns"],
            "student_count": len(data["students"]),
            "students": data["students"][:20],  # preview first 20
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export-student-responses")
def export_student_responses(request: ExportToSheetsRequest):
    """
    Create a detailed student response sheet with per-question answers.
    
    Creates a new tab in the Google Sheet with:
    - Student info (entry number, name, total score)
    - Per-question data (marked answer, correct answer, result status)
    - Comments and observations
    """
    if not _current_answer_key:
        raise HTTPException(
            status_code=400,
            detail="No answer key loaded. Cannot create response sheet without answer key."
        )

    # Get results data
    results_dicts = []
    
    if _current_results:
        results_dicts = [r.model_dump() for r in _current_results]
    else:
        # Pull from database and reconstruct
        db_results = db.get_all_results()
        if db_results:
            for row in db_results:
                details_raw = row.get("details")
                if details_raw:
                    try:
                        details = json.loads(details_raw) if isinstance(details_raw, str) else details_raw
                        results_dicts.append(details)
                    except (json.JSONDecodeError, AttributeError):
                        continue

    if not results_dicts:
        raise HTTPException(
            status_code=400,
            detail="No results to export. Process some answer sheets first."
        )

    try:
        summary = sheets_service.create_student_response_sheet(
            request.sheet_url, 
            results_dicts,
            _current_answer_key.model_dump(),
            response_sheet_name="Student Responses"
        )
        return summary

    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Response sheet export failed: {str(e)}")


@router.get("/download-answer-sheet-template")
def download_answer_sheet_template(format: str = "csv", num_questions: int = 50):
    """
    Download a blank answer sheet template.
    
    Args:
        format: Template format ("csv", "xlsx", or "json")
        num_questions: Number of questions to include in template
    
    Returns:
        Template file for download
    """
    if format not in ["csv", "xlsx", "json"]:
        raise HTTPException(status_code=400, detail="Format must be 'csv', 'xlsx', or 'json'")
    
    if num_questions < 1 or num_questions > 200:
        raise HTTPException(status_code=400, detail="Number of questions must be between 1 and 200")

    try:
        if format == "csv":
            content = _generate_csv_template(num_questions)
            return Response(
                content=content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=answer_key_template_{num_questions}q.csv"}
            )
        elif format == "xlsx":
            content = _generate_xlsx_template(num_questions)
            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=answer_key_template_{num_questions}q.xlsx"}
            )
        elif format == "json":
            content = _generate_json_template(num_questions)
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=answer_key_template_{num_questions}q.json"}
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate template: {str(e)}")


def _generate_csv_template(num_questions: int) -> str:
    """Generate comprehensive CSV answer key template."""
    import io
    import csv
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header for comprehensive format
    writer.writerow(["Question Number", "Type", "Positive Marks", "Negative Marks", "Correct Answer"])
    
    # Sample data with different question types
    for i in range(1, num_questions + 1):
        if i <= num_questions * 0.7:  # 70% SMCQ
            writer.writerow([i, "SMCQ", 3, 1, "A"])
        elif i <= num_questions * 0.9:  # 20% MMCQ
            writer.writerow([i, "MMCQ", 4, 0, "AC"])
        else:  # 10% NCQ
            writer.writerow([i, "NCQ", 4, 1, "2.5"])
    
    return output.getvalue()


def _generate_xlsx_template(num_questions: int) -> bytes:
    """Generate comprehensive XLSX answer key template."""
    try:
        import openpyxl
        from io import BytesIO
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Answer Key"
        
        # Headers for comprehensive format
        headers = ["Question Number", "Type", "Positive Marks", "Negative Marks", "Correct Answer"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = openpyxl.styles.Font(bold=True)
            cell.fill = openpyxl.styles.PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
        
        # Sample data with different question types
        for i in range(1, num_questions + 1):
            row = i + 1
            ws.cell(row=row, column=1, value=i)  # Question Number
            
            if i <= num_questions * 0.7:  # 70% SMCQ
                ws.cell(row=row, column=2, value="SMCQ")
                ws.cell(row=row, column=3, value=3)  # Positive marks
                ws.cell(row=row, column=4, value=1)  # Negative marks
                ws.cell(row=row, column=5, value="A")  # Correct answer
            elif i <= num_questions * 0.9:  # 20% MMCQ
                ws.cell(row=row, column=2, value="MMCQ")
                ws.cell(row=row, column=3, value=4)
                ws.cell(row=row, column=4, value=0)
                ws.cell(row=row, column=5, value="AC")
            else:  # 10% NCQ
                ws.cell(row=row, column=2, value="NCQ")
                ws.cell(row=row, column=3, value=4)
                ws.cell(row=row, column=4, value=1)
                ws.cell(row=row, column=5, value="2.5")
        
        # Auto-size columns
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Save to bytes
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output.read()
        
    except ImportError:
        # Fallback if openpyxl not available
        raise HTTPException(status_code=500, detail="XLSX support not available. Please use CSV format.")


def _generate_json_template(num_questions: int) -> str:
    """Generate comprehensive JSON answer key template."""
    answers = {}
    
    # Generate sample answers with different question types
    for i in range(1, num_questions + 1):
        if i <= num_questions * 0.7:  # 70% SMCQ
            answers[str(i)] = {
                "question_type": "SMCQ",
                "correct_answer": "A",
                "positive_marks": 3,
                "negative_marks": 1
            }
        elif i <= num_questions * 0.9:  # 20% MMCQ
            answers[str(i)] = {
                "question_type": "MMCQ",
                "correct_answer": "AC",
                "positive_marks": 4,
                "negative_marks": 0
            }
        else:  # 10% NCQ
            answers[str(i)] = {
                "question_type": "NCQ",
                "correct_answer": "2.5",
                "positive_marks": 4,
                "negative_marks": 1
            }
    
    template = {
        "answers": answers,
        "negative_marking": 0,
        "_instructions": {
            "format": "Comprehensive answer key format supporting SMCQ, MMCQ, and NCQ",
            "question_types": {
                "SMCQ": "Single Multiple Choice Question (A, B, C, D)",
                "MMCQ": "Multiple Multiple Choice Question (AC, BCD, etc.)",
                "NCQ": "Numerical Choice Question (2.5, 7.0, etc.)"
            },
            "fields": {
                "question_type": "Type of question (SMCQ/MMCQ/NCQ)",
                "correct_answer": "Correct answer based on question type",
                "positive_marks": "Marks awarded for correct answer",
                "negative_marks": "Marks deducted for wrong answer (0 for no penalty)"
            }
        }
    }
    return json.dumps(template, indent=2)


# ═══════════════════════════════════════
#  FULL PIPELINE (ONE-CLICK)
# ═══════════════════════════════════════

@router.post("/full-pipeline")
async def run_full_pipeline(request: FullPipelineRequest):
    """
    One-click pipeline:
    Drive folder → Extract answer key → OCR all sheets → Score → Write to Google Sheets
    """
    # Step 1 & 2: Process drive folder (extracts key + scores students)
    folder_result = await process_drive_folder(
        ProcessFolderRequest(folder_url=request.drive_folder_url)
    )

    # Step 3: Export to sheets
    try:
        sheet_result = export_to_sheets(
            ExportToSheetsRequest(sheet_url=request.sheets_url)
        )
    except HTTPException as e:
        sheet_result = {"error": e.detail}

    return {
        "pipeline": folder_result,
        "sheet_export": sheet_result,
    }


# ═══════════════════════════════════════
#  RESULTS & DATA ACCESS
# ═══════════════════════════════════════

@router.get("/results")
def get_results():
    """Get all results from the current session."""
    if _current_results:
        return {
            "source": "current_session",
            "count": len(_current_results),
            "results": [r.model_dump() for r in _current_results],
        }
    # Fallback to DB
    return {
        "source": "database",
        "results": db.get_all_results(),
    }


@router.delete("/results/clear")
def clear_results():
    """Clear current session results and answer key."""
    global _current_answer_key, _current_results
    _current_answer_key = None
    _current_results = []
    return {"message": "Session cleared"}


@router.post("/cache/cleanup")
async def cleanup_cache(max_age_days: int = 30, force: bool = False):
    """Clean up old cache entries to free space."""
    await cache_service.cleanup_cache(max_age_days, force)
    stats = await cache_service.get_cache_stats()
    return {
        "message": "Cache cleanup completed",
        "cache_stats": stats
    }


@router.post("/database/optimize")
async def optimize_database():
    """Run database optimization (VACUUM and ANALYZE)."""
    success = await optimized_db.vacuum_database()
    await optimized_db.create_indexes_if_missing()
    
    if success:
        stats = await optimized_db.get_performance_analytics()
        return {
            "message": "Database optimization completed",
            "database_stats": stats
        }
    else:
        return {
            "message": "Database optimization failed",
            "error": "See logs for details"
        }


@router.get("/cache/status")
async def get_cache_status():
    """Get detailed cache status and statistics."""
    cache_stats = await cache_service.get_cache_stats()
    
    # Get cache recommendations
    recommendations = []
    cache_size_mb = cache_stats.get('total_size_mb', 0)
    cache_entries = cache_stats.get('total_entries', 0)
    
    if cache_size_mb > 400:
        recommendations.append({
            "type": "warning",
            "message": f"Cache size is {cache_size_mb:.1f}MB (near 500MB limit)",
            "action": "Consider running cache cleanup"
        })
    
    if cache_entries > 1000:
        recommendations.append({
            "type": "info", 
            "message": f"Cache has {cache_entries} entries",
            "action": "Good cache utilization for performance"
        })
    elif cache_entries < 10:
        recommendations.append({
            "type": "info",
            "message": "Low cache utilization",
            "action": "Cache will improve performance as more files are processed"
        })
    
    return {
        "cache_stats": cache_stats,
        "recommendations": recommendations,
        "cache_enabled": True,
        "max_size_mb": 500
    }


@router.post("/cache/clear")
async def clear_cache(confirm: bool = False):
    """Clear all cached results."""
    if not confirm:
        raise HTTPException(
            status_code=400, 
            detail="Set confirm=true to clear cache. This will remove all cached OCR and evaluation results."
        )
    
    try:
        # Clear cache by removing all entries
        await cache_service.cleanup_cache(max_age_days=0, force_cleanup=True)
        
        stats = await cache_service.get_cache_stats()
        return {
            "message": "Cache cleared successfully",
            "remaining_entries": stats.get('total_entries', 0),
            "remaining_size_mb": stats.get('total_size_mb', 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@router.get("/processing/status")
async def get_processing_status():
    """Get current processing status and session info."""
    cache_stats = await cache_service.get_cache_stats()
    
    return {
        "session": {
            "answer_key_loaded": _current_answer_key is not None,
            "answer_key_questions": _current_answer_key.total_questions if _current_answer_key else 0,
            "results_count": len(_current_results),
            "answer_key_source": _current_answer_key.metadata.get("source_file", "unknown") if _current_answer_key else None
        },
        "cache": {
            "total_entries": cache_stats.get('total_entries', 0),
            "total_size_mb": cache_stats.get('total_size_mb', 0),
            "recent_access_24h": cache_stats.get('recent_access_24h', 0)
        },
        "capabilities": {
            "zip_upload": True,
            "drive_processing": True,
            "resume_support": True,
            "student_response_export": True,
            "template_download": True
        }
    }


# ═══════════════════════════════════════
#  LEGACY ENDPOINTS (kept for compat)
# ═══════════════════════════════════════

@router.post("/process-file")
def process_file(file_id: str, file_name: str, background_tasks: BackgroundTasks):
    """
    Legacy: Downloads and processes a single file (OCR + Evaluation).
    """
    submission_id = str(uuid.uuid4())
    submission = Submission(
        id=submission_id,
        student_id="temp_unknown",
        exam_id="exam_001",
        file_id=file_id,
        status="processing"
    )
    db.add_submission(submission)
    background_tasks.add_task(_legacy_process_task, submission_id, file_id, file_name)
    return {"message": "Processing started", "submission_id": submission_id}


def _legacy_process_task(submission_id: str, file_id: str, file_name: str):
    """Legacy background task for processing a single file."""
    try:
        temp_path = f"temp_{file_name}"
        download_success = drive_service.download_file(file_id, temp_path)

        if not download_success and not os.path.exists(temp_path):
            print(f"Failed to download {file_id}")
            return

        extracted_data = ocr_service.extract_data(temp_path)
        if "error" in extracted_data:
            print(f"OCR Error: {extracted_data['error']}")
            return

        roll_no = extracted_data.get("roll_number") or "unknown"
        student_name = extracted_data.get("student_name") or "unknown"
        db.add_student(Student(id=str(roll_no), name=str(student_name), roll_number=str(roll_no)))

        updated_sub = Submission(
            id=submission_id,
            student_id=roll_no,
            exam_id="exam_001",
            file_id=file_id,
            status="evaluated"
        )
        db.add_submission(updated_sub, extracted_data)

        # If we have an answer key, use the new scoring
        if _current_answer_key:
            normalized = ocr_service._normalize_objective_output(extracted_data)
            student_result = EvaluationService.match_and_score(
                _current_answer_key, normalized
            )
            result_record = EvaluationResult(
                submission_id=submission_id,
                score=student_result.total_score,
                feedback=f"{student_result.correct_count} correct, "
                         f"{student_result.incorrect_count} incorrect, "
                         f"{student_result.unattempted_count} unattempted"
            )
            db.add_result(result_record, student_result.model_dump())
        else:
            # Fallback to old hardcoded evaluation
            ANSWER_KEY_OBJECTIVE = [
                {"question_number": i, "correct_option": opt, "marks": 1}
                for i, opt in enumerate(["A", "B", "C", "D", "A"], start=1)
            ]
            obj_answers = extracted_data.get("objective_answers") or extracted_data.get("answers", [])
            obj_result = eval_service.evaluate_objective(obj_answers, ANSWER_KEY_OBJECTIVE)
            result_record = EvaluationResult(
                submission_id=submission_id,
                score=obj_result['total_score'],
                feedback=f"Objective: {obj_result['correct_count']} correct"
            )
            db.add_result(result_record, obj_result)

        if os.path.exists(temp_path):
            os.remove(temp_path)

    except Exception as e:
        print(f"Error processing submission {submission_id}: {e}")
