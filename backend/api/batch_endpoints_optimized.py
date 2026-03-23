"""
Optimized Batch Processing Endpoints
=====================================
True streaming pipeline: Download → OCR → Evaluate → DB, all concurrent.
Rate-aware: per-region token bucket throttling (12 RPM × 4 regions = 48 effective RPM).
Automatic 429 retry with exponential backoff.
"""

from fastapi import APIRouter, HTTPException
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
import base64
import json
import re
import io
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

router = APIRouter(prefix="/api")

# Services
drive_service = DriveService()
optimized_ocr = OptimizedOCRService()
multi_region_ocr = MultiRegionOCRService()
answer_key_service = AnswerKeyService()
batch_eval_service = BatchEvaluationService()
cache_service = ResultCacheService()
optimized_db = OptimizedDatabaseService()

# Global state
_current_answer_key: Optional[Any] = None
_processing_stats: Dict[str, Any] = {}


# ─────────────────────────────────────────────────────────────────────
#  RATE LIMITER — per-region token bucket
# ─────────────────────────────────────────────────────────────────────

_REGIONS = ["us-central1", "us-east1", "us-west1", "europe-west1"]
_MODEL = "gemini-2.5-flash"
_RPM_PER_REGION = 12   # 12 × 4 regions = 48 effective RPM


class _TokenBucket:
    """Allows at most `rate` calls per 60 seconds per bucket."""
    def __init__(self, rate: int):
        self.interval = 60.0 / rate
        self._lock = asyncio.Lock()
        self._next_allowed = time.monotonic()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(self._next_allowed, now) + self.interval
        if wait > 0:
            await asyncio.sleep(wait)


_rate_limiters: Dict[str, _TokenBucket] = {}    # built lazily inside event loop
_rr_counter = 0
_rr_lock: Optional[asyncio.Lock] = None


def _get_bucket(region: str) -> _TokenBucket:
    if region not in _rate_limiters:
        _rate_limiters[region] = _TokenBucket(_RPM_PER_REGION)
    return _rate_limiters[region]


async def _pick_region() -> str:
    global _rr_counter, _rr_lock
    if _rr_lock is None:
        _rr_lock = asyncio.Lock()
    async with _rr_lock:
        region = _REGIONS[_rr_counter % len(_REGIONS)]
        _rr_counter += 1
    return region


# ─────────────────────────────────────────────────────────────────────
#  CORE OCR FUNCTION — rate-limited, multi-region, auto-retried
# ─────────────────────────────────────────────────────────────────────

async def _ocr_one(session, image_path: str, get_headers, project_id: str, max_retries: int = 4) -> dict:
    """
    OCR a single image with:
    - Token-bucket rate limiting per region (prevents 429 proactively)
    - Round-robin across 4 regions (distributes quota)
    - Exponential backoff on 429
    """
    last_error = None

    for attempt in range(max_retries + 1):
        region = await _pick_region()
        await _get_bucket(region).acquire()

        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/"
            f"projects/{project_id}/locations/{region}/"
            f"publishers/google/models/{_MODEL}:generateContent"
        )
        headers = await get_headers()

        # Compress image
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode()
            mime = "image/jpeg"
        except Exception:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"

        payload = {
            "contents": [{"role": "user", "parts": [
                {"text": (
                    'Extract from this answer sheet and return JSON:\n'
                    '{"entry_number":"roll number","name":"student name",'
                    '"answers":{"1":"A","2":"AC","3":"2.5",...}}\n'
                    'answers: dict of question_number(str)->answer(str). '
                    'Single letter (A/B/C/D), multi-letter (AC/BCD), or number (2.5). '
                    'Omit blank questions.'
                )},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.0},
        }

        try:
            import aiohttp
            async with session.post(url, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = "".join(
                        part["text"]
                        for cand in data.get("candidates", [])
                        for part in cand.get("content", {}).get("parts", [])
                        if "text" in part
                    )
                    cleaned = re.sub(r'```json\s*|\s*```', '', text).strip()
                    try:
                        parsed = json.loads(cleaned)
                    except Exception:
                        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
                        parsed = json.loads(m.group()) if m else {}
                    result = {
                        "entry_number": parsed.get("entry_number") or "unknown",
                        "name": parsed.get("name") or "unknown",
                        "comments": parsed.get("comments") or "",
                        "answers": {},
                    }
                    for k, v in (parsed.get("answers") or {}).items():
                        try:
                            result["answers"][str(int(k))] = str(v).strip().upper()
                        except Exception:
                            pass
                    return result

                elif resp.status == 429:
                    backoff = min(5 * (2 ** attempt), 60)
                    last_error = f"429 rate-limited (region={region})"
                    print(f"  ⏳ 429 on {region} attempt {attempt+1}/{max_retries+1} — wait {backoff}s")
                    await asyncio.sleep(backoff)

                else:
                    body = await resp.text()
                    last_error = f"HTTP {resp.status}: {body[:150]}"
                    await asyncio.sleep(2 * (attempt + 1))

        except asyncio.TimeoutError:
            last_error = f"Timeout on {region} attempt {attempt+1}"
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep(1 * (attempt + 1))

    return {"error": last_error or "All retries exhausted"}


# ─────────────────────────────────────────────────────────────────────
#  DB WRITER WORKER
# ─────────────────────────────────────────────────────────────────────

async def _db_writer_worker(queue: asyncio.Queue, processing_id: str):
    batch = []
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=2.0)
            if item is None:
                if batch:
                    await batch_write_student_results(batch, optimized_db, exam_id=f"batch_{processing_id}")
                queue.task_done()
                break
            batch.append(item)
            queue.task_done()
            if len(batch) >= 20:
                await batch_write_student_results(batch, optimized_db, exam_id=f"batch_{processing_id}")
                batch = []
        except asyncio.TimeoutError:
            if batch:
                await batch_write_student_results(batch, optimized_db, exam_id=f"batch_{processing_id}")
                batch = []


# ─────────────────────────────────────────────────────────────────────
#  TRUE STREAMING PIPELINE
# ─────────────────────────────────────────────────────────────────────

async def _process_sheets_optimized(student_sheets: List[Dict], answer_key, processing_id: str):
    """
    Streaming pipeline:
      - All downloads start concurrently
      - OCR starts the moment each file downloads (no waiting for full batch)
      - Token-bucket rate limiting per region prevents 429
      - Evaluation + DB write happen immediately after OCR
    """
    import aiohttp
    from google.oauth2 import service_account
    import google.auth.transport.requests

    results: List = []
    errors: List = []
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "project-75abf07c-e594-4660-ab7")
    optimized_key = batch_eval_service.optimize_answer_key(answer_key)

    # Shared HTTP session
    import aiohttp as _aio
    connector = _aio.TCPConnector(limit=64, keepalive_timeout=60, enable_cleanup_closed=True)
    session = _aio.ClientSession(connector=connector)

    # Auth token refresher
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "vertex_key.json")
    _creds_holder = [None]

    async def _get_headers():
        import datetime
        if _creds_holder[0] is None:
            _creds_holder[0] = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        c = _creds_holder[0]
        if not c.valid or c.expiry is None or (c.expiry - datetime.datetime.utcnow()).total_seconds() < 120:
            await asyncio.to_thread(c.refresh, google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {c.token}", "Content-Type": "application/json"}

    temp_dir = tempfile.mkdtemp(prefix="stream_")
    db_queue: asyncio.Queue = asyncio.Queue()
    writer_task = asyncio.create_task(_db_writer_worker(db_queue, processing_id))

    # 6 concurrent OCR slots — rate buckets handle the actual pacing
    ocr_sem = asyncio.Semaphore(6)
    lock = asyncio.Lock()
    success_count = 0
    start_t = time.time()
    _processing_stats[processing_id]["start_time"] = start_t
    total = len(student_sheets)

    async def _handle(sheet_file: dict, idx: int):
        nonlocal success_count
        fname = sheet_file["name"]
        file_id = sheet_file["id"]
        local_path = os.path.join(temp_dir, f"{idx}_{fname}")

        # 1. Cache check BEFORE download
        cached = await cache_service.get_cached_ocr_result(local_path, file_hash=file_id)
        if cached:
            ocr = cached
            async with lock:
                _processing_stats[processing_id]["cache_hits"] = _processing_stats[processing_id].get("cache_hits", 0) + 1
        else:
            async with lock:
                _processing_stats[processing_id]["cache_misses"] = _processing_stats[processing_id].get("cache_misses", 0) + 1
            
            # 2. Download
            ok = await asyncio.to_thread(drive_service.download_file, file_id, local_path)
            if not ok:
                async with lock:
                    errors.append({"file": fname, "error": "Download failed"})
                    _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
                return

            # 3. OCR — rate-limited, multi-region, auto-retry
            async with ocr_sem:
                ocr = await _ocr_one(session, local_path, _get_headers, project_id)
            if "error" not in ocr:
                await cache_service.cache_ocr_result(local_path, ocr, file_hash=file_id)

        if "error" in ocr:
            async with lock:
                errors.append({"file": fname, "error": ocr["error"]})
                _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
            try:
                os.path.exists(local_path) and os.remove(local_path)
            except Exception:
                pass
            return

        # 4. Evaluate
        ocr["index"] = idx
        ocr["file_name"] = fname
        student_result = batch_eval_service.evaluate_single_student_optimized(optimized_key, ocr, idx)

        if isinstance(student_result, dict) and "error" in student_result:
            async with lock:
                errors.append({"file": fname, "error": student_result["error"]})
        else:
            await db_queue.put(student_result)
            async with lock:
                results.append(student_result)
                success_count += 1
                processed = len(results) + len(errors)
                _processing_stats[processing_id]["processed_files"] = processed
                if processed % 10 == 0 or processed == total:
                    elapsed = time.time() - start_t
                    rate = processed / max(elapsed, 1)
                    eta = (total - processed) / rate if rate > 0 else 0
                    pct = processed / total * 100
                    print(f"  📊 {processed}/{total} ({pct:.0f}%) | ✅{success_count} ❌{len(errors)} | {rate:.2f}/s | ETA {eta:.0f}s")

        try:
            os.path.exists(local_path) and os.remove(local_path)
        except Exception:
            pass

    try:
        _processing_stats[processing_id]["status"] = "streaming_pipeline"
        tasks = [asyncio.create_task(_handle(sf, i)) for i, sf in enumerate(student_sheets)]
        await asyncio.gather(*tasks)
    finally:
        await db_queue.put(None)
        await writer_task
        await session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    _processing_stats[processing_id].update({
        "evaluation_success_rate": success_count / total if total else 0,
    })
    return results, errors


# ─────────────────────────────────────────────────────────────────────
#  ENDPOINT
# ─────────────────────────────────────────────────────────────────────

@router.post("/batch/process-folder-optimized")
async def process_folder_optimized(request: ProcessFolderRequest, force_reprocess: bool = False):
    """
    Ultra-optimized folder processing.
    - Streaming pipeline: each file is OCR'd as soon as it downloads
    - Rate-aware: token-bucket throttling per region prevents 429
    - 4 regions × 12 RPM = 48 effective RPM
    - Exponential backoff retry on 429
    """
    global _current_answer_key, _processing_stats

    start_time = time.time()
    folder_id = DriveService.extract_folder_id(request.folder_url)

    processing_id = f"batch_{int(start_time)}"
    _processing_stats[processing_id] = {
        "start_time": start_time,
        "status": "initializing",
        "total_files": 0,
        "processed_files": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "errors": [],
    }

    try:
        # Discover files
        _processing_stats[processing_id]["status"] = "discovering_files"
        all_files = drive_service.list_all_files_in_folder(folder_id)
        if not all_files:
            raise HTTPException(status_code=404, detail="No files found in the Drive folder.")

        answer_key_files, student_sheets = drive_service.separate_files(all_files)
        _processing_stats[processing_id]["total_files"] = len(student_sheets)

        # Load answer key
        if (_current_answer_key is None or force_reprocess):
            if answer_key_files:
                _processing_stats[processing_id]["status"] = "loading_answer_key"
                tmp = tempfile.mkdtemp(prefix="ak_")
                try:
                    local_ak = drive_service.download_answer_key(answer_key_files[0], tmp)
                    _current_answer_key = answer_key_service.extract_answer_key(
                        local_ak, answer_key_files[0].get("mimeType", "")
                    )
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            else:
                # Fallback to local disk if previously uploaded
                _current_answer_key = answer_key_service.load_from_disk()

        if not _current_answer_key:
            raise HTTPException(status_code=400, detail="No answer key loaded.")
        if not student_sheets:
            raise HTTPException(status_code=404, detail="No student sheets found.")

        # Run pipeline
        results, errors = await _process_sheets_optimized(student_sheets, _current_answer_key, processing_id)

        total_time = time.time() - start_time
        _processing_stats[processing_id].update({
            "status": "completed",
            "total_time": total_time,
            "avg_time_per_file": total_time / len(student_sheets) if student_sheets else 0,
            "success_rate": len(results) / len(student_sheets) if student_sheets else 0,
        })

        return PipelineSummary(
            total_students_processed=len(results),
            answer_key_source=_current_answer_key.metadata.get("source_file", "loaded"),
            results=results,
            errors=errors,
            processing_stats=_processing_stats[processing_id],
        ).model_dump()

    except Exception as e:
        _processing_stats[processing_id].update({
            "status": "failed",
            "error": str(e),
            "total_time": time.time() - start_time,
        })
        raise


# ─────────────────────────────────────────────────────────────────────
#  STATUS + UTILITIES
# ─────────────────────────────────────────────────────────────────────

@router.get("/batch/processing-status/{processing_id}")
async def get_processing_status(processing_id: str):
    if processing_id not in _processing_stats:
        raise HTTPException(status_code=404, detail="Processing ID not found")
    stats = _processing_stats[processing_id].copy()
    if stats["status"] not in ("completed", "failed"):
        elapsed = time.time() - stats.get("start_time", time.time())
        processed = stats.get("processed_files", 0)
        total = max(stats.get("total_files", 1), 1)
        stats.update({
            "elapsed_time": elapsed,
            "progress_percentage": processed / total * 100,
            "estimated_remaining": (elapsed / processed) * (total - processed) if processed > 0 else None,
        })
    return stats


@router.post("/batch/preload-cache")
async def preload_cache(request: ProcessFolderRequest):
    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)
    if not all_files:
        raise HTTPException(status_code=404, detail="No files found.")
    _, student_sheets = drive_service.separate_files(all_files)
    if not student_sheets:
        raise HTTPException(status_code=404, detail="No student sheets found.")

    temp_dir = tempfile.mkdtemp(prefix="preload_")
    cached_count = 0
    processed_count = 0

    try:
        batch_size = 10
        for i in range(0, len(student_sheets), batch_size):
            batch = student_sheets[i:i + batch_size]
            download_tasks = [
                asyncio.to_thread(drive_service.download_file, sheet["id"],
                                  os.path.join(temp_dir, f"pre_{i+j}_{sheet['name']}"))
                for j, sheet in enumerate(batch)
            ]
            successes = await asyncio.gather(*download_tasks)
            for j, (sheet, ok) in enumerate(zip(batch, successes)):
                if ok:
                    lp = os.path.join(temp_dir, f"pre_{i+j}_{sheet['name']}")
                    if await cache_service.get_cached_ocr_result(lp):
                        cached_count += 1
                    else:
                        processed_count += 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "files_already_cached": cached_count,
        "files_newly_processed": processed_count,
        "total_files": len(student_sheets),
        "cache_stats": await cache_service.get_cache_stats(),
    }


@router.delete("/batch/clear-processing-stats")
async def clear_processing_stats():
    global _processing_stats
    cutoff = time.time() - 86400
    old = len(_processing_stats)
    _processing_stats = {k: v for k, v in _processing_stats.items() if v.get("start_time", 0) > cutoff}
    return {"cleared": old - len(_processing_stats), "remaining": len(_processing_stats)}