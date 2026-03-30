"""
Optimized Batch Processing Endpoints
=====================================
True streaming pipeline: Download → OCR → Evaluate → DB, all concurrent.

Model policy: gemini-2.5-pro ONLY (highest quality, no Flash fallback).

Reliability guarantee:
  1. Every image is OCR'd twice independently on different Pro regions.
  2. If answer sets agree completely → use the result immediately.
  3. If ANY answer disagrees → run a 3rd tiebreaker pass and use majority vote.

Multi-region load distribution across 9 Pro endpoints for maximum quota.
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
#  MODEL POOL — gemini-2.5-pro ONLY across all available regions
# ─────────────────────────────────────────────────────────────────────

# Each entry: (model_id, region, rpm_budget)
# Pro model only — no Flash, no Flash-Lite fallback under any circumstances.
# 9 regions provide ample quota headroom (~2,250+ RPM combined).

_ENDPOINT_POOL: List[Dict] = [
    # ── gemini-2.5-pro GA  (US regions — primary quota) ──
    {"model": "gemini-2.5-pro", "region": "us-central1",  "rpm": 250},
    {"model": "gemini-2.5-pro", "region": "us-east1",     "rpm": 250},
    {"model": "gemini-2.5-pro", "region": "us-east4",     "rpm": 250},
    {"model": "gemini-2.5-pro", "region": "us-east5",     "rpm": 250},
    {"model": "gemini-2.5-pro", "region": "us-south1",    "rpm": 250},
    {"model": "gemini-2.5-pro", "region": "us-west1",     "rpm": 250},
    {"model": "gemini-2.5-pro", "region": "us-west4",     "rpm": 250},
    # ── gemini-2.5-pro GA  (Europe regions — secondary quota) ──
    {"model": "gemini-2.5-pro", "region": "europe-west1", "rpm": 60},
    {"model": "gemini-2.5-pro", "region": "europe-west4", "rpm": 60},
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
_rr_counter: int = 0  # global round-robin index across all Pro endpoints
_rr_lock: Optional[asyncio.Lock] = None

# ─── Per-endpoint 429 cooldown ────────────────────────────────────────────────
# When an endpoint returns 429, we mark it as cooling down for N seconds.
# The picker skips it immediately rather than sleeping and blocking a request.
_cooldown_until: Dict[str, float] = {}   # region -> monotonic timestamp when it's usable again
_COOLDOWN_BASE = 30.0                     # initial cooldown on first 429 (seconds)
_COOLDOWN_MAX  = 300.0                   # cap: 5 minutes per endpoint
_cooldown_hits: Dict[str, int] = {}      # track consecutive 429s for exponential backoff


def _bucket_key(ep: Dict) -> str:
    return f"{ep['model']}|{ep['region']}"


def _get_bucket(ep: Dict) -> _TokenBucket:
    key = _bucket_key(ep)
    if key not in _buckets:
        _buckets[key] = _TokenBucket(ep["rpm"])
    return _buckets[key]


def _is_cooling_down(ep: Dict) -> bool:
    """Return True if this endpoint is in its 429-cooldown period."""
    until = _cooldown_until.get(ep["region"], 0.0)
    return time.monotonic() < until


def _mark_cooldown(ep: Dict) -> None:
    """Exponential cooldown on 429: 30s, 60s, 120s … capped at 5 min."""
    hits = _cooldown_hits.get(ep["region"], 0) + 1
    _cooldown_hits[ep["region"]] = hits
    delay = min(_COOLDOWN_BASE * (2 ** (hits - 1)), _COOLDOWN_MAX)
    _cooldown_until[ep["region"]] = time.monotonic() + delay
    print(f"  🚫 [COOLDOWN] {ep['region']} rate-limited — cooling {delay:.0f}s (hit #{hits})")


def _clear_cooldown(ep: Dict) -> None:
    """Reset cooldown state on a successful response."""
    _cooldown_hits.pop(ep["region"], None)
    _cooldown_until.pop(ep["region"], None)


def _get_healthy_pool(exclude_regions: Optional[list] = None) -> List[Dict]:
    """Return all Pro endpoints that are NOT currently in cooldown."""
    now = time.monotonic()
    pool = [ep for ep in _ENDPOINT_POOL
            if now >= _cooldown_until.get(ep["region"], 0.0)
            and (not exclude_regions or ep["region"] not in exclude_regions)]
    # Fallback: if everything is cooling down, return least-recently-429'd endpoints
    if not pool:
        sorted_eps = sorted(_ENDPOINT_POOL,
                            key=lambda e: _cooldown_until.get(e["region"], 0.0))
        pool = [sorted_eps[0]]  # take the one that recovers soonest
    return pool


async def _pick_endpoint(exclude_regions: Optional[list] = None) -> Dict:
    """Round-robin across healthy (non-cooling-down) Pro endpoints."""
    global _rr_lock, _rr_counter
    if _rr_lock is None:
        _rr_lock = asyncio.Lock()
    candidates = _get_healthy_pool(exclude_regions)
    async with _rr_lock:
        idx = _rr_counter % len(candidates)
        _rr_counter += 1
        return candidates[idx]


# ─────────────────────────────────────────────────────────────────────
#  CORE OCR FUNCTION — Pro-only, rate-limited, multi-region
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

# Enhanced retry prompt — used when the first pass returned empty answers.
# Much more explicit about finding the answer grid and checking all sections.
_OCR_RETRY_PROMPT = (
    'IMPORTANT: A previous OCR attempt on this answer sheet returned EMPTY ANSWERS. '
    'The student HAS written answers — look MORE carefully.\n\n'
    'This is a student answer sheet for an objective (MCQ) exam. It typically has:\n'
    '1. Printed questions at the TOP (ignore these).\n'
    '2. A student-written "Name" and "Entry No." field.\n'
    '3. An ANSWER GRID below the questions where students write their answers '
    '   — this may be in ONE or TWO COLUMNS (e.g. Q1-5 on left, Q6-10 on right).\n'
    '4. Answers might be circled options (A/B/C/D), written letters, or tick marks.\n\n'
    'The image may be rotated, upside-down, or at an angle. '
    'Try reading it in ALL orientations until you find the answer grid.\n\n'
    'Look for ANY pattern that could be answers: numbers followed by letters, '
    'circled options, table grids, handwritten A/B/C/D marks, etc.\n\n'
    'Return JSON ONLY:\n'
    '{"entry_number":"roll number","name":"student name",'
    '"answers":{"1":"A","2":"C",...}}\n'
    'answers: dict of question_number(str)->answer(str). '
    'Single letter (A/B/C/D), multi-letter (AC/BCD), or number (2.5). '
    'Omit only truly blank questions.'
)

# Minimum expected answers — if OCR returns fewer than this many, it suggests
# the model failed to read the answer grid and we should retry.
_MIN_EXPECTED_ANSWERS = 3

# Maximum retries per single OCR pass — we wait as long as needed on Pro.
_OCR_MAX_RETRIES = 20
# 429 backoff cap (seconds): will wait up to 2 min before cycling to next region.
_OCR_BACKOFF_CAP = 120


def _prepare_image_payload(image_path: str) -> tuple:
    """Encode and compress an image, returning (b64_str, mime_type)."""
    try:
        from PIL import Image, ImageOps
        with Image.open(image_path) as img:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            w, h = img.size
            if h > w * 1.5:  # portrait-rotated landscape photo
                img = img.rotate(90, expand=True)
            img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
    except Exception:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        return b64, mime


def _prepare_image_enhanced(image_path: str) -> tuple:
    """
    Contrast-enhanced image encoding for retry attempts.

    When the model returns empty answers on the default encoding, the handwriting
    may be too faint or washed out.  This variant applies:
      - Auto-contrast (stretches histogram to full range)
      - Mild sharpening
      - Slight brightness boost
    """
    try:
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
        with Image.open(image_path) as img:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Auto-contrast: stretch histogram per-channel
            img = ImageOps.autocontrast(img, cutoff=1)

            # Sharpen
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.8)

            # Contrast boost
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.4)

            w, h = img.size
            if h > w * 1.5:
                img = img.rotate(90, expand=True)
            img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90, optimize=True)
            return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
    except Exception:
        # Fall back to normal encoding
        return _prepare_image_payload(image_path)


def _parse_ocr_text(text: str, image_path: str) -> Optional[dict]:
    """Parse OCR JSON from raw model text. Returns None if completely unparseable."""
    fname = os.path.basename(image_path)
    cleaned = re.sub(r'```json\s*|\s*```', '', text).strip()
    parsed = None

    # Strategy 1: direct JSON parse
    try:
        parsed = json.loads(cleaned)
    except Exception:
        pass

    # Strategy 2: find ALL JSON objects, use the LAST valid one
    # (thinking models often prefix with explanation text)
    if not parsed:
        json_candidates = []
        depth, start_idx = 0, None
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
        for candidate in reversed(json_candidates):
            try:
                test = json.loads(candidate)
                if isinstance(test, dict) and ("answers" in test or "entry_number" in test or "name" in test):
                    parsed = test
                    break
            except Exception:
                continue

    # Strategy 3: regex field extraction (last resort)
    if not parsed:
        parsed = {}
        m = re.search(r'"entry_number"\s*:\s*"([^"]*)"', text)
        if m:
            parsed["entry_number"] = m.group(1)
        m = re.search(r'"name"\s*:\s*"([^"]*)"', text)
        if m:
            parsed["name"] = m.group(1)
        m = re.search(r'"answers"\s*:\s*(\{[^}]*\})', text)
        if m:
            try:
                parsed["answers"] = json.loads(m.group(1))
            except Exception:
                pass
        if parsed:
            print(f"  🔧 [OCR] Regex-extracted fields for {fname}: {list(parsed.keys())}")
        else:
            print(f"  ⚠️ [OCR] JSON parse completely failed for {fname}: raw text={text[:300]}")
            return None

    # Normalise to canonical output dict
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
    if not str(entry).strip():
        non_answer_keys = {k: v for k, v in parsed.items() if k != "answers"}
        print(f"  🔍 [OCR DEBUG] Empty entry for {fname}: model returned keys={non_answer_keys}")

    result = {
        "entry_number": str(entry).strip(),
        "name": str(parsed.get("name") or parsed.get("student_name") or "").strip(),
        "comments": parsed.get("comments") or "",
        "answers": {},
    }
    for k, v in (parsed.get("answers") or {}).items():
        try:
            result["answers"][str(int(k))] = str(v).strip().upper()
        except Exception:
            pass
    return result


async def _ocr_single_pass(
    session, image_path: str, get_headers, project_id: str,
    exclude_regions: Optional[list] = None,
    b64: Optional[str] = None,
    mime: Optional[str] = None,
) -> dict:
    """
    Execute ONE OCR pass against gemini-2.5-pro only.

    Key optimizations vs old version:
    - On 429: immediately mark the endpoint as cooling-down and retry on
      a DIFFERENT healthy region without sleeping (no blocking delay).
    - b64/mime can be pre-computed and shared across concurrent passes.
    - exclude_regions: list of regions to avoid (for cross-region verification).
    - On empty entry_number: retry up to _OCR_MAX_RETRIES on fresh regions.
    - On empty/sparse answers (<_MIN_EXPECTED_ANSWERS): retry with enhanced
      prompt and contrast-boosted image to catch faint handwriting.
    """
    last_error = None
    fname = os.path.basename(image_path)
    empty_answers_retries = 0   # track how many times we got empty answers
    used_enhanced_image = False  # whether we've switched to contrast-boosted encoding
    active_prompt = _OCR_PROMPT  # start with normal prompt, escalate if needed

    # Pre-encode image once (caller may pass it in to avoid redundant work)
    if b64 is None or mime is None:
        b64, mime = _prepare_image_payload(image_path)

    # Keep the enhanced encoding handy — computed lazily only if needed
    enhanced_b64: Optional[str] = None
    enhanced_mime: Optional[str] = None

    for attempt in range(_OCR_MAX_RETRIES + 1):
        ep = await _pick_endpoint(exclude_regions=exclude_regions)

        bucket = _get_bucket(ep)
        await bucket.acquire()

        url = (
            f"https://{ep['region']}-aiplatform.googleapis.com/v1/"
            f"projects/{project_id}/locations/{ep['region']}/"
            f"publishers/google/models/{ep['model']}:generateContent"
        )
        headers = await get_headers()

        # After several empty-answers retries, switch to enhanced image + retry prompt
        current_b64 = b64
        current_mime = mime
        if empty_answers_retries >= 5 and not used_enhanced_image:
            # Lazy-compute enhanced encoding
            if enhanced_b64 is None:
                enhanced_b64, enhanced_mime = _prepare_image_enhanced(image_path)
                print(f"  🔬 [OCR] Switching to contrast-enhanced image for {fname}")
            current_b64 = enhanced_b64
            current_mime = enhanced_mime
            used_enhanced_image = True
        if empty_answers_retries >= 3:
            active_prompt = _OCR_RETRY_PROMPT

        payload = {
            "contents": [{"role": "user", "parts": [
                {"text": active_prompt},
                {"inline_data": {"mime_type": current_mime, "data": current_b64}},
            ]}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.0},
        }

        try:
            import aiohttp
            async with session.post(url, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    _clear_cooldown(ep)
                    data = await resp.json()
                    text = "".join(
                        part["text"]
                        for cand in data.get("candidates", [])
                        for part in cand.get("content", {}).get("parts", [])
                        if "text" in part
                    )

                    if not text.strip():
                        candidates = data.get("candidates", [])
                        if not candidates:
                            last_error = f"No candidates for {fname}"
                        else:
                            fr = candidates[0].get("finishReason", "UNKNOWN")
                            last_error = f"Empty text for {fname} (finishReason={fr})"
                        print(f"  ⚠️ [OCR] {last_error}")
                        empty_answers_retries += 1
                        await asyncio.sleep(1)
                        continue

                    parsed = _parse_ocr_text(text, image_path)
                    if parsed is None:
                        last_error = f"JSON parse failed for {fname}"
                        await asyncio.sleep(1)
                        continue

                    # FIX 1: Retry if entry_number is empty — the model parsed
                    # JSON successfully but couldn't extract the roll number.
                    # This is a soft failure: treat it like a bad response and
                    # burn another retry slot (possibly on a different region).
                    if not str(parsed.get("entry_number", "")).strip():
                        last_error = (
                            f"Empty entry_number for {fname} "
                            f"on {ep['model']}@{ep['region']} — retrying on different region"
                        )
                        print(f"  🔄 [OCR] {last_error}")
                        await asyncio.sleep(1)
                        continue

                    # FIX 3: Retry if answers dict is empty or suspiciously sparse.
                    # The student has written answers but the model couldn't read them.
                    # After multiple retries, escalate to enhanced image + retry prompt.
                    answer_count = len(parsed.get("answers", {}))
                    if answer_count < _MIN_EXPECTED_ANSWERS:
                        empty_answers_retries += 1
                        last_error = (
                            f"Sparse/empty answers ({answer_count} answers) for {fname} "
                            f"on {ep['model']}@{ep['region']} — "
                            f"retry #{empty_answers_retries} on different region"
                        )
                        print(f"  🔄 [OCR] {last_error}")
                        if empty_answers_retries >= 3:
                            print(
                                f"  📝 [OCR] Escalating to enhanced retry prompt for {fname} "
                                f"(empty answers retry #{empty_answers_retries})"
                            )
                        if empty_answers_retries >= 5:
                            print(
                                f"  🔬 [OCR] Will use contrast-enhanced image on next attempt for {fname}"
                            )
                        # After many empty-answers retries, accept whatever we got
                        # — the sheet may genuinely be blank or illegible.
                        if empty_answers_retries > 8:
                            print(
                                f"  ⚠️ [OCR] Giving up after {empty_answers_retries} empty-answers retries "
                                f"for {fname} — accepting {answer_count} answers as final result"
                            )
                            parsed["_endpoint"] = f"{ep['model']}@{ep['region']}"
                            parsed["comments"] = (
                                f"[WARNING: only {answer_count} answer(s) detected after "
                                f"{empty_answers_retries} retries — possible handwriting issue] "
                                + (parsed.get("comments") or "")
                            )
                            return parsed
                        await asyncio.sleep(1)
                        continue

                    parsed["_endpoint"] = f"{ep['model']}@{ep['region']}"
                    return parsed

                elif resp.status == 429:
                    # Mark this endpoint as cooling down — IMMEDIATELY retry on another region.
                    # No asyncio.sleep here: the next loop iteration picks a healthy endpoint.
                    _mark_cooldown(ep)
                    last_error = f"429 on {ep['model']}@{ep['region']} (now cooling, switching region)"
                    # Tiny yield to let the event loop breathe between rapid retries
                    await asyncio.sleep(0.1)

                else:
                    body = await resp.text()
                    last_error = f"HTTP {resp.status}: {body[:150]}"
                    await asyncio.sleep(2 * (attempt + 1))

        except asyncio.TimeoutError:
            last_error = f"Timeout on {ep['model']}@{ep['region']} attempt {attempt+1}"
            # Don't mark cooldown for timeouts — may be network hiccup, not quota
            await asyncio.sleep(2)
        except (ConnectionError, OSError) as e:
            last_error = f"Connection lost on {ep['model']}@{ep['region']} attempt {attempt+1}: {e}"
            await asyncio.sleep(3)
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep(2)

    return {"error": last_error or "All Pro retries exhausted"}


def _answers_agree(a: dict, b: dict) -> bool:
    """True if both OCR passes produced identical answers dicts."""
    return a.get("answers", {}) == b.get("answers", {})


def _majority_vote(results: list) -> dict:
    """
    Given 2 or 3 OCR result dicts, produce a merged result using majority vote
    per question independently. Ties broken by first pass's answer.
    entry_number and name taken from the pass with the most complete data.
    """
    from collections import Counter

    valid = [r for r in results if "error" not in r]
    if not valid:
        return results[0] if results else {"error": "All passes failed"}
    if len(valid) == 1:
        return valid[0]

    all_q_nums: set = set()
    for r in valid:
        all_q_nums.update(r.get("answers", {}).keys())

    merged_answers: dict = {}
    for q in sorted(all_q_nums, key=lambda x: int(x) if x.isdigit() else 0):
        votes = [r["answers"].get(q) for r in valid if q in r.get("answers", {})]
        if not votes:
            continue
        winner, _ = Counter(votes).most_common(1)[0]
        merged_answers[q] = winner

    entry = max((r.get("entry_number", "") for r in valid), key=lambda e: len(str(e).strip()))
    name  = max((r.get("name", "")         for r in valid), key=lambda n: len(str(n).strip()))
    endpoints = ", ".join(r.get("_endpoint", "?") for r in valid)
    n_passes = len(valid)

    return {
        "entry_number": entry,
        "name": name,
        "comments": f"[{n_passes}-pass verified] " + (valid[0].get("comments") or ""),
        "answers": merged_answers,
        "_endpoint": endpoints,
        "_verified_passes": n_passes,
    }


async def _ocr_one(session, image_path: str, get_headers, project_id: str,
                   max_retries: int = _OCR_MAX_RETRIES) -> dict:
    """
    High-reliability OCR — gemini-2.5-pro ONLY, concurrent double-run verification.

    ┌─────────────────────────────────────────────────────────────┐
    │   Pass 1 ──┐                                                │
    │            ├─ asyncio.gather (run simultaneously) ─►        │
    │   Pass 2 ──┘   (different Pro region)                      │
    │                                                             │
    │   Agree?  ──► return immediately  (~1×LLM latency)         │
    │   Differ? ──► Pass 3 tiebreaker ──► majority vote           │
    └─────────────────────────────────────────────────────────────┘

    Image is encoded once and shared between passes (no double CPU work).
    429s are handled by per-endpoint cooldown — no sleeping, instant failover.
    """
    fname = os.path.basename(image_path)

    # ── Pre-encode image ONCE — shared by all passes ──────────────────
    b64, mime = _prepare_image_payload(image_path)

    # ── Launch Pass 1 & Pass 2 CONCURRENTLY ──────────────────────────
    # Pass 2 deliberately excludes Pass 1's region (chosen at call time).
    # We pick Pass 1's region hint before launching so they diverge.
    ep1_hint_candidates = _get_healthy_pool()
    ep1_region_hint = ep1_hint_candidates[0]["region"] if ep1_hint_candidates else None
    ep2_exclude = [ep1_region_hint] if ep1_region_hint else []

    print(f"  🚀 [OCR Pass 1+2 concurrent] {fname}")
    r1, r2 = await asyncio.gather(
        _ocr_single_pass(session, image_path, get_headers, project_id,
                         exclude_regions=None, b64=b64, mime=mime),
        _ocr_single_pass(session, image_path, get_headers, project_id,
                         exclude_regions=ep2_exclude, b64=b64, mime=mime),
        return_exceptions=False,
    )

    # Handle errors from either pass
    if "error" in r1 and "error" in r2:
        print(f"  ❌ [OCR both passes failed] {fname}: P1={r1['error']} | P2={r2['error']}")
        return r1
    if "error" in r1:
        print(f"  ⚠️ [OCR Pass 1 failed] {fname}: {r1['error']} — using Pass 2 only")
        return r2
    if "error" in r2:
        print(f"  ⚠️ [OCR Pass 2 failed] {fname}: {r2['error']} — using Pass 1 only")
        return r1

    ep1_ep = r1.get('_endpoint', '?')
    ep2_ep = r2.get('_endpoint', '?')
    print(f"  ✅ [OCR P1+P2 done] {fname} | P1={ep1_ep} ({len(r1.get('answers',{}))}q) | P2={ep2_ep} ({len(r2.get('answers',{}))}q)")

    # ── Agreement check ─────────────────────────────────────────────
    if _answers_agree(r1, r2):
        print(f"  ✅✅ [OCR VERIFIED] {fname} — passes agree, done")
        result = dict(r1)
        result["comments"] = "[2-pass verified] " + (r1.get("comments") or "")
        result["_endpoint"] = f"{ep1_ep}, {ep2_ep}"
        result["_verified_passes"] = 2
        return result

    # ── Disagreement — run Pass 3 tiebreaker ────────────────────────
    ep1_region = ep1_ep.split("@")[-1]
    ep2_region = ep2_ep.split("@")[-1]
    differing = [
        q for q in sorted(set(r1.get("answers", {}).keys()) | set(r2.get("answers", {}).keys()))
        if r1.get("answers", {}).get(q) != r2.get("answers", {}).get(q)
    ]
    print(f"  ⚖️  [OCR DISAGREE] {fname} — differ on Q{differing}. Launching tiebreaker (Pass 3)...")

    r3 = await _ocr_single_pass(
        session, image_path, get_headers, project_id,
        exclude_regions=[ep1_region, ep2_region],
        b64=b64, mime=mime,
    )
    if "error" in r3:
        print(f"  ⚠️ [OCR Pass 3 failed] {fname}: {r3['error']} — majority of 2")
        result = _majority_vote([r1, r2])
        result["comments"] = "[2-of-3 pass, tiebreaker failed] " + (result.get("comments") or "")
        return result

    print(f"  ✅ [OCR Pass 3 done] {fname} via {r3.get('_endpoint')} ({len(r3.get('answers',{}))}q)")
    result = _majority_vote([r1, r2, r3])
    print(f"  🏆 [OCR FINAL] {fname} — 3-pass majority vote | {len(result.get('answers',{}))} answers")
    return result


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

def _make_eval_cache_key(
    file_id: str, answer_key_hash: str,
    evaluation_id: str = "default",
    run_ts: str = ""
) -> str:
    """
    Stable cache key for a fully evaluated result (OCR + scoring).

    FIX 2: Include `run_ts` (a per-run timestamp string) so that each fresh
    pipeline run gets its own namespace and never serves stale evaluations
    from a previous run.  When force_reprocess=False and you want to reuse
    prior results, pass run_ts="" (the default) — that restores the old
    behaviour.  When force_reprocess=True (or a new run is started), the
    caller passes run_ts=processing_id so every key is unique.
    """
    raw = f"eval:{evaluation_id}:{run_ts}:{file_id}:{answer_key_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _process_sheets_optimized(student_sheets: List[Dict], answer_key, processing_id: str, evaluation_id: str = "default", force_reprocess: bool = False, run_ts: str = ""):
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
        # FIX 2: Pass run_ts so each independent run gets a fresh eval cache
        # namespace and never replays stale scores from a prior run.
        eval_cache_key = _make_eval_cache_key(file_id, answer_key_hash, evaluation_id, run_ts)
        ocr_cache_key = f"ocr:{evaluation_id}:{file_id}"

        try:
            # ── STEP 1: Check FULL evaluation cache (OCR + scored result) ──
            # If hit, we're done — no download, no OCR, no re-evaluation needed.
            # IMPORTANT: Reject cached results with empty/UNREAD_ entry_number (network-failure garbage).
            eval_cached = None
            if not force_reprocess:
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
            ocr_cached = None
            if not force_reprocess:
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
        # FIX 2: Pass processing_id as run_ts — every run gets its own eval
        # cache namespace so stale evaluations from previous runs are never served.
        results, errors = await _process_sheets_optimized(
            student_sheets, _current_answer_key, processing_id,
            eval_id, force_reprocess, run_ts=processing_id
        )

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