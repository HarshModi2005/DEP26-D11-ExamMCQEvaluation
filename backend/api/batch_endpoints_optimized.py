"""
Optimized Batch Processing Endpoints
=====================================
True streaming pipeline: Download → OCR → Evaluate → DB, all concurrent.

Model priority:
  1. gemini-2.5-pro   (GA) — primary, highest quality
  2. gemini-2.5-flash       — fallback, fast & capable
  3. gemini-2.5-flash-lite  — last resort only

Multi-region load distribution across 14+ endpoints using all available quota.
Token-bucket rate limiting prevents 429s proactively.
Evaluation results are FULLY CACHED — cache hits skip OCR AND evaluation entirely.
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
import hashlib
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

# Global state — answer key is shared with endpoints.py to stay in sync
import api.endpoints as _endpoints_module
_processing_stats: Dict[str, Any] = {}

def _get_answer_key():
    return _endpoints_module._current_answer_key

def _set_answer_key(val):
    _endpoints_module._current_answer_key = val


# ─────────────────────────────────────────────────────────────────────
#  MODEL TIERS — priority order (Pro first, then Flash, then Lite)
# ─────────────────────────────────────────────────────────────────────

# Each entry: (model_id, region, rpm_budget)
# Distribute load across all available regions for maximum throughput.
# Budgets are conservative (well below quota limits) to stay stable.

_ENDPOINT_POOL: List[Dict] = [
    # ── Tier 1: gemini-2.5-pro GA  (40,248 RPM across US regions) ──
    {"model": "gemini-2.5-pro",       "region": "us-central1",   "rpm": 250, "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "us-east1",      "rpm": 250, "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "us-east4",      "rpm": 250, "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "us-east5",      "rpm": 250, "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "us-south1",     "rpm": 250, "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "us-west1",      "rpm": 250, "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "us-west4",      "rpm": 250, "tier": 1},
    # ── Tier 1: gemini-2.5-pro GA  (Europe) ──
    {"model": "gemini-2.5-pro",       "region": "europe-west1",  "rpm": 60,  "tier": 1},
    {"model": "gemini-2.5-pro",       "region": "europe-west4",  "rpm": 60,  "tier": 1},

    # ── Tier 2: gemini-2.5-flash (40,248 RPM across Asia+US) ──
    {"model": "gemini-2.5-flash",     "region": "asia-east1",    "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "asia-east2",    "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "asia-northeast1","rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "asia-northeast3","rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "us-east4",      "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "us-east5",      "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "us-south1",     "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "us-west2",      "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "us-west4",      "rpm": 200, "tier": 2},
    {"model": "gemini-2.5-flash",     "region": "europe-west1",  "rpm": 60,  "tier": 2},

    # ── Tier 3: gemini-2.5-flash-lite  (LAST RESORT only) ──
    {"model": "gemini-2.5-flash-lite", "region": "us-central1",  "rpm": 40,  "tier": 3},
    {"model": "gemini-2.5-flash-lite", "region": "us-east1",     "rpm": 40,  "tier": 3},
]

# ─────────────────────────────────────────────────────────────────────
#  PER-ENDPOINT TOKEN BUCKETS
# ─────────────────────────────────────────────────────────────────────

class _TokenBucket:
    """Strict token-bucket: at most `rpm` tokens per 60 seconds."""
    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm
        self._lock = asyncio.Lock()
        self._next_allowed = time.monotonic()
        self.rpm = rpm

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(self._next_allowed, now) + self.interval
        if wait > 0:
            await asyncio.sleep(wait)


# Bucket per (model, region) pair, lazily initialised
_buckets: Dict[str, _TokenBucket] = {}
_bucket_lock: Optional[asyncio.Lock] = None

def _bucket_key(ep: Dict) -> str:
    return f"{ep['model']}|{ep['region']}"

def _get_bucket(ep: Dict) -> _TokenBucket:
    key = _bucket_key(ep)
    if key not in _buckets:
        _buckets[key] = _TokenBucket(ep["rpm"])
    return _buckets[key]


# Round-robin counters per tier
_rr: Dict[int, int] = {1: 0, 2: 0, 3: 0}
_rr_lock: Optional[asyncio.Lock] = None

_tier1_eps = [ep for ep in _ENDPOINT_POOL if ep["tier"] == 1]
_tier2_eps = [ep for ep in _ENDPOINT_POOL if ep["tier"] == 2]
_tier3_eps = [ep for ep in _ENDPOINT_POOL if ep["tier"] == 3]

# Track which tiers are degraded (too many 429s recently)
_tier_failures: Dict[int, int] = {1: 0, 2: 0, 3: 0}
_TIER_FAILURE_THRESHOLD = 15  # escalate only after this many consecutive 429s on a tier (Pro gets priority)


async def _pick_endpoint(prefer_tier: int = 1) -> Dict:
    """Pick the next endpoint via round-robin within the current active tier."""
    global _rr_lock
    if _rr_lock is None:
        _rr_lock = asyncio.Lock()

    async with _rr_lock:
        # Walk up tiers only when lower tier is fully degraded
        for tier in [prefer_tier, 2, 3]:
            eps = [_tier1_eps, _tier2_eps, _tier3_eps][tier - 1]
            if not eps:
                continue
            if _tier_failures[tier] >= _TIER_FAILURE_THRESHOLD and tier < 3:
                continue  # skip degraded tier, try next
            idx = _rr[tier] % len(eps)
            _rr[tier] += 1
            return eps[idx]

        # Absolute fallback
        return _tier3_eps[0] if _tier3_eps else _tier1_eps[0]


# ─────────────────────────────────────────────────────────────────────
#  CORE OCR FUNCTION — rate-limited, multi-tier, multi-region
# ─────────────────────────────────────────────────────────────────────

_OCR_PROMPT = (
    'Extract from this answer sheet and return JSON:\n'
    '{"entry_number":"roll number","name":"student name",'
    '"answers":{"1":"A","2":"AC","3":"2.5",...}}\n'
    'answers: dict of question_number(str)->answer(str). '
    'Single letter (A/B/C/D), multi-letter (AC/BCD), or number (2.5). '
    'Omit blank questions. '
    'The image may be rotated or tilted — read it in whatever orientation makes the text readable. '
    'entry_number/roll number is REQUIRED — look for it carefully in corners, margins, and headers.'
)


async def _ocr_one(session, image_path: str, get_headers, project_id: str,
                   max_retries: int = 12) -> dict:
    """
    OCR one image.  Tries Tier-1 (Pro) first; on repeated 429s quietly
    falls back to Tier-2 (Flash) then Tier-3 (Lite) as a last resort.
    """
    last_error = None
    prefer_tier = 1

    for attempt in range(max_retries + 1):
        ep = await _pick_endpoint(prefer_tier)
        bucket = _get_bucket(ep)
        await bucket.acquire()

        url = (
            f"https://{ep['region']}-aiplatform.googleapis.com/v1/"
            f"projects/{project_id}/locations/{ep['region']}/"
            f"publishers/google/models/{ep['model']}:generateContent"
        )
        headers = await get_headers()

        # Compress image and fix orientation
        try:
            from PIL import Image, ImageOps
            with Image.open(image_path) as img:
                # Fix EXIF orientation (phone cameras store rotation as metadata)
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass

                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                # Auto-rotate: if image is significantly more tall than wide,
                # it's likely a rotated landscape photo — rotate 90° CCW
                w, h = img.size
                if h > w * 1.5:  # portrait orientation, likely rotated
                    img = img.rotate(90, expand=True)

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
                {"text": _OCR_PROMPT},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.0},
        }

        try:
            import aiohttp
            async with session.post(url, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    _tier_failures[ep["tier"]] = max(0, _tier_failures[ep["tier"]] - 1)
                    data = await resp.json()
                    text = "".join(
                        part["text"]
                        for cand in data.get("candidates", [])
                        for part in cand.get("content", {}).get("parts", [])
                        if "text" in part
                    )

                    # If the model returned no text at all, check why and RETRY
                    if not text.strip():
                        # Check for safety block or empty candidates
                        candidates = data.get("candidates", [])
                        if not candidates:
                            last_error = f"No candidates in response for {os.path.basename(image_path)}"
                        else:
                            finish_reason = candidates[0].get("finishReason", "UNKNOWN")
                            safety = candidates[0].get("safetyRatings", [])
                            last_error = (f"Empty text for {os.path.basename(image_path)} "
                                          f"(finishReason={finish_reason}, safety={safety})")
                        print(f"  ⚠️ [OCR] {last_error}")
                        await asyncio.sleep(1)
                        continue  # retry on next attempt/endpoint

                    cleaned = re.sub(r'```json\s*|\s*```', '', text).strip()
                    parsed = None

                    # Strategy 1: Direct JSON parse
                    try:
                        parsed = json.loads(cleaned)
                    except Exception:
                        pass

                    # Strategy 2: Find ALL JSON objects and use the LAST valid one
                    # (Gemini thinking models put explanation before the actual JSON)
                    if not parsed:
                        # Find all potential JSON objects by matching balanced braces
                        json_candidates = []
                        depth = 0
                        start_idx = None
                        for i, ch in enumerate(cleaned):
                            if ch == '{':
                                if depth == 0:
                                    start_idx = i
                                depth += 1
                            elif ch == '}':
                                depth -= 1
                                if depth == 0 and start_idx is not None:
                                    json_candidates.append(cleaned[start_idx:i+1])
                                    start_idx = None

                        # Try each candidate in REVERSE order (last = most likely the actual answer)
                        for candidate in reversed(json_candidates):
                            try:
                                test = json.loads(candidate)
                                if isinstance(test, dict) and ("answers" in test or "entry_number" in test or "name" in test):
                                    parsed = test
                                    break
                            except Exception:
                                continue

                    # Strategy 3: Last resort — extract fields via regex
                    if not parsed:
                        parsed = {}
                        # Try to extract entry_number
                        m = re.search(r'"entry_number"\s*:\s*"([^"]*)"', text)
                        if m:
                            parsed["entry_number"] = m.group(1)
                        # Try to extract name
                        m = re.search(r'"name"\s*:\s*"([^"]*)"', text)
                        if m:
                            parsed["name"] = m.group(1)
                        # Try to extract answers block
                        m = re.search(r'"answers"\s*:\s*(\{[^}]*\})', text)
                        if m:
                            try:
                                parsed["answers"] = json.loads(m.group(1))
                            except Exception:
                                pass
                        if parsed:
                            print(f"  🔧 [OCR] Regex-extracted fields for {os.path.basename(image_path)}: {list(parsed.keys())}")
                        else:
                            print(f"  ⚠️ [OCR] JSON parse completely failed for {os.path.basename(image_path)}: raw text={text[:300]}")
                            last_error = f"JSON parse failed for {os.path.basename(image_path)}"
                            await asyncio.sleep(1)
                            continue  # retry only when we got absolutely nothing

                    # Try multiple keys the model might use for the enrollment number
                    entry = (
                        parsed.get("entry_number")
                        or parsed.get("roll_number")
                        or parsed.get("enrollment_number")
                        or parsed.get("roll")
                        or parsed.get("enrollment")
                        or parsed.get("roll_no")
                        or parsed.get("enroll")
                        or parsed.get("id")
                        or parsed.get("student_id")
                        or ""
                    )
                    result = {
                        "entry_number": str(entry).strip(),
                        "name": str(parsed.get("name") or parsed.get("student_name") or "").strip(),
                        "comments": parsed.get("comments") or "",
                        "answers": {},
                        "_endpoint": f"{ep['model']}@{ep['region']}",
                    }
                    # Debug: if entry_number is empty, log ALL keys the model returned
                    if not str(entry).strip():
                        non_answer_keys = {k: v for k, v in parsed.items() if k != "answers"}
                        print(f"  🔍 [OCR DEBUG] Empty entry for {os.path.basename(image_path)}: model returned keys={non_answer_keys}")
                    for k, v in (parsed.get("answers") or {}).items():
                        try:
                            result["answers"][str(int(k))] = str(v).strip().upper()
                        except Exception:
                            pass
                    return result

                elif resp.status == 429:
                    _tier_failures[ep["tier"]] += 1
                    backoff = min(4 * (2 ** attempt), 60)
                    last_error = f"429 rate-limited ({ep['model']}@{ep['region']})"
                    print(f"  ⏳ 429 on {ep['model']}@{ep['region']} attempt {attempt+1} — wait {backoff}s")
                    # Step down only when: threshold hit AND we are past the halfway point of retries.
                    # This ensures Tier-1 (Pro) gets the full retry budget before Flash is ever used.
                    past_halfway = attempt >= max_retries // 2
                    if (
                        _tier_failures[ep["tier"]] >= _TIER_FAILURE_THRESHOLD
                        and past_halfway
                        and prefer_tier < 3
                    ):
                        prefer_tier += 1
                        print(f"  ⬇️  Stepping down to Tier-{prefer_tier} (attempt {attempt+1}/{max_retries+1}, {_tier_failures[ep['tier']]} failures on Tier-{ep['tier']})")
                    await asyncio.sleep(backoff)

                else:
                    body = await resp.text()
                    last_error = f"HTTP {resp.status}: {body[:150]}"
                    await asyncio.sleep(2 * (attempt + 1))

        except asyncio.TimeoutError:
            last_error = f"Timeout on {ep['model']}@{ep['region']} attempt {attempt+1}"
            backoff = min(2 * (attempt + 1), 30)
            await asyncio.sleep(backoff)
        except (ConnectionError, OSError) as e:
            # Network glitch — retry with backoff (covers ServerDisconnectedError)
            last_error = f"Connection lost on {ep['model']}@{ep['region']} attempt {attempt+1}: {e}"
            backoff = min(3 * (attempt + 1), 30)
            await asyncio.sleep(backoff)
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep(min(2 * (attempt + 1), 20))

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

def _make_eval_cache_key(file_id: str, answer_key_hash: str, evaluation_id: str = "default") -> str:
    """Stable cache key for a fully evaluated result (OCR + scoring), namespaced by evaluation."""
    raw = f"eval:{evaluation_id}:{file_id}:{answer_key_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _process_sheets_optimized(student_sheets: List[Dict], answer_key, processing_id: str, evaluation_id: str = "default"):
    """
    Streaming pipeline:
      - Cache check (OCR + evaluation) BEFORE downloading anything
      - Cache hits skip download, OCR AND re-evaluation entirely
      - Downloads & OCR run concurrently across all sheets
      - Token-bucket rate limiting per (model, region) pair prevents 429
      - Evaluation + DB write happen immediately after OCR
      - Tier-1 (Pro) → Tier-2 (Flash) → Tier-3 (Lite) failover
    """
    import aiohttp
    from google.oauth2 import service_account
    import google.auth.transport.requests

    results: List = []
    errors: List = []
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "project-75abf07c-e594-4660-ab7")
    optimized_key = batch_eval_service.optimize_answer_key(answer_key)
    answer_key_hash = cache_service.get_answer_key_hash(
        {"answers": optimized_key["answers"], "negative_marking": optimized_key["negative_marking"]}
    )

    # Shared HTTP session — large pool for many concurrent connections
    connector = aiohttp.TCPConnector(
        limit=256,
        limit_per_host=32,
        keepalive_timeout=60,
        enable_cleanup_closed=True,
    )
    session = aiohttp.ClientSession(connector=connector)

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

    # High concurrency — token buckets do the pacing, not a semaphore
    # Use a generous semaphore just to cap memory from too many in-flight downloads
    download_sem = asyncio.Semaphore(50)
    lock = asyncio.Lock()
    success_count = 0
    cache_hit_count = 0
    start_t = time.time()
    _processing_stats[processing_id]["start_time"] = start_t
    total = len(student_sheets)

    def _is_valid_cached_entry(entry_val) -> bool:
        """Return True only if this entry_number is real (not empty, not UNREAD_ placeholder)."""
        if not entry_val:
            return False
        s = str(entry_val).strip()
        return bool(s) and not s.startswith("UNREAD_")

    async def _handle(sheet_file: dict, idx: int):
        nonlocal success_count, cache_hit_count  # noqa: E741
        fname = sheet_file["name"]
        file_id = sheet_file["id"]
        local_path = os.path.join(temp_dir, f"{idx}_{fname}")
        eval_cache_key = _make_eval_cache_key(file_id, answer_key_hash, evaluation_id)
        ocr_cache_key = f"ocr:{evaluation_id}:{file_id}"

        try:
            # ── STEP 1: Check FULL evaluation cache (OCR + scored result) ──
            # If hit, we're done — no download, no OCR, no re-evaluation needed.
            # IMPORTANT: Reject cached results with empty/UNREAD_ entry_number (network-failure garbage).
            eval_cached = await cache_service.get_cached_ocr_result("__eval__", file_hash=eval_cache_key)
            cached_entry = (eval_cached or {}).get("entry_number", "") if eval_cached else ""
            if eval_cached and _is_valid_cached_entry(cached_entry) and "total_score" in eval_cached:
                async with lock:
                    cache_hit_count += 1
                    _processing_stats[processing_id]["cache_hits"] = cache_hit_count
                    student_result = eval_cached  # already fully scored
                    results.append(student_result)
                    success_count += 1
                    processed = len(results) + len(errors)
                    _processing_stats[processing_id]["processed_files"] = processed
                    _log_progress(processing_id, processed, total, success_count,
                                  len(errors), cache_hit_count, start_t, from_cache=True)
                await db_queue.put(student_result)
                return
            elif eval_cached and not _is_valid_cached_entry(cached_entry):
                print(f"  🔄 Skipping incomplete eval cache for {fname} (entry='{cached_entry}') — re-processing")

            # ── STEP 2: Check OCR-only cache ──
            # Reject OCR cache if entry_number is empty or UNREAD_ placeholder
            ocr_cached = await cache_service.get_cached_ocr_result(local_path, file_hash=ocr_cache_key)
            ocr_cached_entry = (ocr_cached or {}).get("entry_number", "") if ocr_cached else ""
            if ocr_cached and _is_valid_cached_entry(ocr_cached_entry):
                ocr = ocr_cached
                async with lock:
                    _processing_stats[processing_id]["ocr_cache_hits"] = \
                        _processing_stats[processing_id].get("ocr_cache_hits", 0) + 1
            else:
                if ocr_cached and not _is_valid_cached_entry(ocr_cached_entry):
                    print(f"  🔄 Skipping incomplete OCR cache for {fname} (entry='{ocr_cached_entry}') — re-processing")
                async with lock:
                    _processing_stats[processing_id]["cache_misses"] = \
                        _processing_stats[processing_id].get("cache_misses", 0) + 1

                # ── STEP 3: Download ──
                async with download_sem:
                    ok = await asyncio.to_thread(drive_service.download_file, file_id, local_path)
                if not ok:
                    async with lock:
                        errors.append({"file": fname, "error": "Download failed"})
                        _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
                    return

                # ── STEP 4: OCR (rate-limited, multi-tier, multi-region) ──
                ocr = await _ocr_one(session, local_path, _get_headers, project_id)
                if "error" not in ocr:
                    # Only cache OCR results with valid entry_number (not empty, not UNREAD_)
                    if _is_valid_cached_entry(ocr.get("entry_number", "")):
                        await cache_service.cache_ocr_result(local_path, ocr, file_hash=ocr_cache_key)
                    else:
                        print(f"  ⚠️ OCR returned empty entry_number for {fname} — NOT caching (will retry on next run)")

            if "error" in ocr:
                async with lock:
                    errors.append({"file": fname, "error": ocr["error"]})
                    _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
                try:
                    os.path.exists(local_path) and os.remove(local_path)
                except Exception:
                    pass
                return

            # ── STEP 5: Evaluate ──
            ocr["index"] = idx
            ocr["file_name"] = fname
            # Assign a unique fallback entry_number from the filename if OCR couldn't extract one
            if not str(ocr.get("entry_number", "")).strip():
                # Use filename without extension as a unique (but temporary) identifier
                fallback_id = os.path.splitext(fname)[0]
                ocr["entry_number"] = f"UNREAD_{fallback_id}"
            student_result = batch_eval_service.evaluate_single_student_optimized(optimized_key, ocr, idx)

            if isinstance(student_result, dict) and "error" in student_result:
                async with lock:
                    errors.append({"file": fname, "error": student_result["error"]})
                    _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
            else:
                # ── STEP 6: Cache the fully evaluated result ──
                # Only cache if entry_number is valid (not empty, not UNREAD_)
                try:
                    scored_dict = student_result.model_dump() if hasattr(student_result, "model_dump") else dict(student_result)
                    if _is_valid_cached_entry(scored_dict.get("entry_number", "")):
                        await cache_service.cache_ocr_result("__eval__", scored_dict, file_hash=eval_cache_key)
                    else:
                        print(f"  ⚠️ Skipping eval cache for {fname} (entry='{scored_dict.get('entry_number','')}') — will retry on next run")
                except Exception:
                    pass

                await db_queue.put(student_result)
                async with lock:
                    results.append(student_result)
                    success_count += 1
                    processed = len(results) + len(errors)
                    _processing_stats[processing_id]["processed_files"] = processed
                    _log_progress(processing_id, processed, total, success_count,
                                  len(errors), cache_hit_count, start_t, from_cache=False)

        except Exception as exc:
            # Catch ANY unhandled error (FileNotFoundError, etc.) so it doesn't
            # crash the entire asyncio.gather pipeline for all students.
            async with lock:
                errors.append({"file": fname, "error": str(exc)})
                _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
            print(f"  ⚠️ Error processing {fname}: {exc}")

        finally:
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


def _log_progress(processing_id: str, processed: int, total: int, success: int,
                  error_count: int, cache_hits: int, start_t: float, from_cache: bool):
    """Emit a structured progress log entry."""
    elapsed = time.time() - start_t
    rate = processed / max(elapsed, 1)
    eta = (total - processed) / rate if rate > 0 else 0
    pct = processed / total * 100 if total else 0
    cache_tag = "⚡CACHE" if from_cache else "🔬OCR"
    print(
        f"  [{cache_tag}] {processed}/{total} ({pct:.0f}%) | "
        f"✅{success} ❌{error_count} 💾{cache_hits} cached | "
        f"{rate:.2f}/s | ETA {eta:.0f}s"
    )
    _processing_stats[processing_id]["log_line"] = (
        f"{processed}/{total} ({pct:.0f}%) | ✅{success} ❌{error_count} 💾{cache_hits} cached | "
        f"{rate:.2f} sheets/s | ETA {eta:.0f}s"
    )


# ─────────────────────────────────────────────────────────────────────
#  ENDPOINT
# ─────────────────────────────────────────────────────────────────────

@router.post("/batch/process-folder-optimized")
async def process_folder_optimized(request: ProcessFolderRequest, force_reprocess: bool = False):
    """
    Ultra-optimized folder processing.
    - Full evaluation cache: cache hits skip download, OCR AND re-evaluation
    - Tier-1 Pro → Tier-2 Flash → Tier-3 Lite failover
    - 14+ endpoint pool with independent token-bucket rate limiting
    - Streaming pipeline, high concurrency
    """
    global _processing_stats

    start_time = time.time()
    folder_id = DriveService.extract_folder_id(request.folder_url)

    processing_id = f"batch_{int(start_time)}"
    _processing_stats[processing_id] = {
        "start_time": start_time,
        "status": "initializing",
        "total_files": 0,
        "processed_files": 0,
        "cache_hits": 0,
        "ocr_cache_hits": 0,
        "cache_misses": 0,
        "errors": [],
        "log_line": "",
    }

    try:
        # Discover files
        _processing_stats[processing_id]["status"] = "discovering_files"
        all_files = drive_service.list_all_files_in_folder(folder_id)
        if not all_files:
            raise HTTPException(status_code=404, detail="No files found in the Drive folder.")

        answer_key_files, student_sheets = drive_service.separate_files(all_files)
        total_sheets = len(student_sheets)
        _processing_stats[processing_id]["total_files"] = total_sheets

        print(f"📂 Discovered {total_sheets} student sheet(s) + {len(answer_key_files)} answer key file(s)")

        # Load answer key
        _current_answer_key = _get_answer_key()
        if _current_answer_key is None or force_reprocess:
            if answer_key_files:
                _processing_stats[processing_id]["status"] = "loading_answer_key"
                tmp = tempfile.mkdtemp(prefix="ak_")
                try:
                    local_ak = drive_service.download_answer_key(answer_key_files[0], tmp)
                    _current_answer_key = answer_key_service.extract_answer_key(
                        local_ak, answer_key_files[0].get("mimeType", "")
                    )
                    _set_answer_key(_current_answer_key)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            else:
                _current_answer_key = answer_key_service.load_from_disk()
                _set_answer_key(_current_answer_key)

        if not _current_answer_key:
            raise HTTPException(status_code=400, detail="No answer key loaded.")
        if not student_sheets:
            raise HTTPException(status_code=404, detail="No student sheets found.")

        print(f"🚀 Starting pipeline: {total_sheets} sheets | Pro→Flash→Lite tier failover | Full eval cache enabled")

        # Run pipeline
        eval_id = request.evaluation_id or "default"
        results, errors = await _process_sheets_optimized(student_sheets, _current_answer_key, processing_id, eval_id)

        total_time = time.time() - start_time
        _processing_stats[processing_id].update({
            "status": "completed",
            "total_time": total_time,
            "avg_time_per_file": total_time / total_sheets if total_sheets else 0,
            "success_rate": len(results) / total_sheets if total_sheets else 0,
        })

        # Normalize results: convert StudentResult objects to dicts for consistent serialization
        normalized_results = []
        for r in results:
            if hasattr(r, 'model_dump'):
                normalized_results.append(r.model_dump())
            elif isinstance(r, dict):
                normalized_results.append(r)
            else:
                normalized_results.append(dict(r))

        # ── DEBUG: entry_number distribution ──
        from collections import Counter
        entry_nums = [r.get("entry_number", "(missing)") for r in normalized_results]
        unique_count = len(set(entry_nums))
        freq = Counter(entry_nums)
        dupes = {k: v for k, v in freq.items() if v > 1}
        print(f"\n📊 [DEBUG] {len(normalized_results)} results, {unique_count} unique entry_numbers")
        if dupes:
            print(f"📊 [DEBUG] Duplicated entry_numbers (>1 occurrence): {dict(list(dupes.items())[:15])}")
        # ── END DEBUG ──

        # Filter out UNREAD_ entries from the response — they should NOT appear in UI/export
        # They are kept internally (not cached) so re-runs will re-process them
        unread_results = [r for r in normalized_results if str(r.get("entry_number", "")).startswith("UNREAD_")]
        display_results = [r for r in normalized_results if not str(r.get("entry_number", "")).startswith("UNREAD_")]
        if unread_results:
            print(f"\n🔄 Filtered {len(unread_results)} UNREAD entries from response (not in UI/export, will be re-processed on next run)")
            _processing_stats[processing_id]["unread_sheets"] = len(unread_results)
            _processing_stats[processing_id]["unread_files"] = [
                str(r.get("entry_number", "")).replace("UNREAD_", "") for r in unread_results
            ][:10]  # first 10 for reference

        return PipelineSummary(
            total_students_processed=len(display_results),
            answer_key_source=_current_answer_key.metadata.get("source_file", "loaded"),
            results=display_results,
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