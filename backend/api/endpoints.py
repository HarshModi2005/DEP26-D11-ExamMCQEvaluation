"""
API Endpoints
=============
Routes for the objective answer sheet evaluation pipeline.
Auth is handled entirely by Supabase on the frontend.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
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
from database import Database
import asyncio
import uuid
import os
import json
import tempfile
import shutil
from typing import Optional

router = APIRouter()
db = Database()
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
def get_status():
    return {
        "status": "Service operational",
        "answer_key_loaded": _current_answer_key is not None,
        "answer_key_questions": _current_answer_key.total_questions if _current_answer_key else 0,
        "results_count": len(_current_results),
    }


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


# ═══════════════════════════════════════
#  PHASE 2B — PROCESS STUDENT SHEETS
# ═══════════════════════════════════════

@router.post("/process-drive-folder")
async def process_drive_folder(request: ProcessFolderRequest):
    """
    Main endpoint: Process all student answer sheets in a Drive folder.

    1. Lists all files in the folder
    2. Separates answer key from student sheets
    3. Extracts answer key (if not already loaded)
    4. Downloads all student sheets in parallel
    5. OCR-processes the entire batch concurrently via OptimizedOCRService
    6. Scores each result against the answer key
    7. Returns all results
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

        # --- Score each result ---
        for ocr_result in ocr_results:
            idx = ocr_result.get("index", 0)
            image_path = image_paths[idx] if idx < len(image_paths) else None
            sheet_file = file_map.get(image_path, {})
            file_name = sheet_file.get("name", f"image_{idx}")

            if "error" in ocr_result:
                errors.append({"file": file_name, "error": ocr_result["error"]})
                continue

            try:
                student_result = EvaluationService.match_and_score(
                    _current_answer_key, ocr_result
                )
                _current_results.append(student_result)

                print(f"  ✅ {student_result.entry_number} — {student_result.name}: "
                      f"{student_result.total_score}/{student_result.max_score}")

                db.add_student(Student(
                    id=student_result.entry_number,
                    name=student_result.name,
                    roll_number=student_result.entry_number
                ))
            except Exception as e:
                errors.append({"file": file_name, "error": str(e)})
                print(f"  ❌ Scoring error for {file_name}: {e}")

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
