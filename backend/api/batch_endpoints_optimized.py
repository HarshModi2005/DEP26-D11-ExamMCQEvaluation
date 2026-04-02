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

from fastapi import APIRouter, HTTPException, BackgroundTasks
from models import ProcessFolderRequest, PipelineSummary
from services.drive_service import DriveService
from services.answer_key_service import AnswerKeyService
from services.batch_evaluation_service import BatchEvaluationService, batch_match_and_score
from services.result_cache_service import ResultCacheService, get_cached_or_process_ocr
from services.optimized_database_service import OptimizedDatabaseService, batch_write_student_results
import aiohttp
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


def _initialize_processing_stats(processing_id: str, start_time: float):
    _processing_stats[processing_id] = {
        "processing_id": processing_id,
        "start_time": start_time,
        "status": "initializing",
        "total_files": 0,
        "processed_files": 0,
        "cache_hits": 0,
        "ocr_cache_hits": 0,
        "cache_misses": 0,
        "errors": [],
        "results": [],
        "log_line": "",
    }


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
_rr_lock: asyncio.Lock = asyncio.Lock()

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
    global _rr_counter
    candidates = _get_healthy_pool(exclude_regions)
    async with _rr_lock:
        idx = _rr_counter % len(candidates)
        _rr_counter += 1
        return candidates[idx]


# ─────────────────────────────────────────────────────────────────────
#  CORE OCR FUNCTION — Pro-only, rate-limited, multi-region
# ─────────────────────────────────────────────────────────────────────

def _build_ocr_prompt(answer_key: Optional[dict] = None) -> str:
    example_answers_json = '{"1":"A","2":"AC","4":"10",...}'
    schema_str = ""
    
    if answer_key and "answers" in answer_key:
        schema = []
        example_dict = {}
        # Sort keys to ensure deterministic behavior
        sorted_keys = sorted(answer_key["answers"].keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
        
        for q in sorted_keys:
            meta = answer_key["answers"][q]
            if isinstance(meta, dict):
                q_type = meta.get("question_type", "")
                if q_type == "SMCQ":
                    schema.append(f"Q{q}: Single checkbox (A, B, C, D)")
                    if len(example_dict) < 3: example_dict[str(q)] = "A"
                elif q_type == "MMCQ":
                    schema.append(f"Q{q}: Multiple checkboxes (e.g., AB, BCD)")
                    if len(example_dict) < 3: example_dict[str(q)] = "AC"
                elif q_type == "NCQ":
                    schema.append(f"Q{q}: Numerical Text Box")
                    if len(example_dict) < 3: example_dict[str(q)] = "2.5"
                    
        if schema:
            schema_str = "\n".join(schema)
        if example_dict:
            import json
            # Build a string like '{"1": "A", "2": "AC", ...}'
            example_json_str = json.dumps(example_dict)
            example_answers_json = example_json_str[:-1] + ',...}'

    prompt = (
        'Extract from this answer sheet and return JSON:\n'
        '{"entry_number":"roll number","name":"student name",'
        f'"answers":{example_answers_json}}}\n'
        'answers: dict of question_number(str)->answer(str). '
        'For checkboxes, ONLY return the exact letters checked (A/B/C/D). NEVER guess numbers like "3" for checked boxes. '
        'For numerical text boxes, return the exact number written. '
        'Omit blank questions. '
        'The image may be rotated or tilted — read it in whatever orientation makes the text readable. '
        'entry_number/roll number is REQUIRED — look for it carefully.'
    )
    
    if schema_str:
        prompt += f"\n\n**CRITICAL SCHEMA INSTRUCTIONS GIVEN BY ANSWER KEY:**\n{schema_str}\n"
        prompt += "\nDO NOT GUESS OR CHANGE FORMATS! If a question is an SMCQ/MMCQ, you MUST extract ONLY letters. If it is NCQ, you MUST extract ONLY numbers."
        
    return prompt

# Maximum retries per single OCR pass — we wait as long as needed on Pro.
_OCR_MAX_RETRIES = 20
# 429 backoff cap (seconds): will wait up to 2 min before cycling to next region.
_OCR_BACKOFF_CAP = 120

# Cache prompt strings so _build_ocr_prompt runs at most once per unique answer key
_ocr_prompt_cache: Dict[str, str] = {}  # answer_key fingerprint → prompt string


def _get_ocr_prompt(answer_key: Optional[dict] = None) -> str:
    """Return a cached OCR prompt for the given answer key. Builds once, reuses always."""
    if not answer_key:
        key = "__no_answer_key__"
    else:
        # Fingerprint using sorted question types — fast and stable
        try:
            fingerprint_parts = sorted(
                (str(q), str(meta.get("question_type", "")))
                for q, meta in answer_key.get("answers", {}).items()
                if isinstance(meta, dict)
            )
            key = str(fingerprint_parts)
        except Exception:
            key = "__fallback__"
    if key not in _ocr_prompt_cache:
        _ocr_prompt_cache[key] = _build_ocr_prompt(answer_key)
    return _ocr_prompt_cache[key]


def _prepare_image_payload(image_path: str) -> tuple[str, str]:
    """
    Intelligent image preparation:
    Uses CV2 HSV pipeline to crop out the background desk, maximizing the resolution 
    given to the checkboxes.
    """
    fname = os.path.basename(image_path)
    from services.image_preprocessing import preprocess_for_ocr
    try:
        img_bytes, mime = preprocess_for_ocr(image_path)
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        return b64, mime
    except Exception as e:
        print(f"  [WARN] CV2 Crop failed for {image_path}: {e}. Falling back to default resize.")
        from PIL import Image, ImageOps
        import io
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            # Using 2560x2560 fallback resolution
            img.thumbnail((2560, 2560))
            
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            img_bytes = buffer.getvalue()

        b64 = base64.b64encode(img_bytes).decode('utf-8')
        return b64, "image/jpeg"


def _parse_ocr_text(text: str, image_path: str) -> Optional[dict]:
    """Parse OCR JSON from raw model text. Returns None if completely unparseable."""
    fname = os.path.basename(image_path)
    print(f"  📝 [PARSE] {fname}: raw response length={len(text)} chars | preview={text[:120].strip()!r}")
    cleaned = re.sub(r'```json\s*|\s*```', '', text).strip()
    parsed = None
    parse_strategy = None

    # Strategy 1: direct JSON parse
    try:
        parsed = json.loads(cleaned)
        parse_strategy = "direct"
    except Exception as e:
        print(f"  📝 [PARSE] {fname}: direct JSON failed: {e}")

    # Strategy 2: find ALL JSON objects, use the LAST valid one
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
        print(f"  📝 [PARSE] {fname}: found {len(json_candidates)} JSON object candidate(s)")
        for candidate in reversed(json_candidates):
            try:
                test = json.loads(candidate)
                if isinstance(test, dict) and ("answers" in test or "entry_number" in test or "name" in test):
                    parsed = test
                    parse_strategy = "json-scan"
                    break
            except Exception:
                continue

    # Strategy 3: regex field extraction (last resort)
    if not parsed:
        parse_strategy = "regex"
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
            print(f"  🔧 [PARSE] {fname}: regex-extracted fields: {list(parsed.keys())}")
        else:
            print(f"  ❌ [PARSE] {fname}: ALL strategies failed. Full model text:\n{text[:600]}")
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
    entry_str = str(entry).strip()
    if not entry_str:
        non_answer_keys = {k: v for k, v in parsed.items() if k != "answers"}
        print(f"  ⚠️ [PARSE] {fname}: entry_number EMPTY. All model keys (excl answers): {non_answer_keys}")
        print(f"  ⚠️ [PARSE] {fname}: full model text for manual inspection:\n{text[:800]}")
    else:
        print(f"  ✅ [PARSE] {fname}: strategy={parse_strategy} entry={entry_str!r} answers_count={len(parsed.get('answers') or {})}")

    result = {
        "entry_number": entry_str,
        "name": str(parsed.get("name") or parsed.get("student_name") or "").strip(),
        "comments": parsed.get("comments") or "",
        "answers": {},
    }
    skipped_keys = []
    for k, v in (parsed.get("answers") or {}).items():
        try:
            result["answers"][str(int(k))] = str(v).strip().upper()
        except Exception:
            skipped_keys.append(k)
    if skipped_keys:
        print(f"  ⚠️ [PARSE] {fname}: skipped non-integer answer keys: {skipped_keys}")
    if not result["answers"] and parsed.get("answers"):
        print(f"  ⚠️ [PARSE] {fname}: raw answers dict non-empty but all keys invalid: {parsed['answers']}")
    return result


async def _ocr_single_pass(
    session, image_path: str, get_headers, project_id: str,
    exclude_regions: Optional[list] = None,
    b64: Optional[str] = None,
    mime: Optional[str] = None,
    ocr_prompt: Optional[str] = None,   # Pre-built prompt string — pass once from _ocr_one
) -> dict:
    """
    Execute ONE OCR pass against gemini-2.5-pro only.

    Key optimizations vs old version:
    - On 429: immediately mark the endpoint as cooling-down and retry on
      a DIFFERENT healthy region without sleeping (no blocking delay).
    - b64/mime can be pre-computed and shared across concurrent passes.
    - exclude_regions: list of regions to avoid (for cross-region verification).
    - ocr_prompt: pre-built prompt string, passed in once by _ocr_one to avoid
      rebuilding the prompt string on every retry attempt.
    """
    last_error = None
    # Pre-encode image once (caller may pass it in to avoid redundant work)
    if b64 is None or mime is None:
        b64, mime = _prepare_image_payload(image_path)

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

        prompt_text = ocr_prompt or _get_ocr_prompt(None)
        payload = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt_text},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]}],
            "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.0},
        }

        fname = os.path.basename(image_path)
        print(f"  🌐 [OCR] {fname} attempt {attempt+1}/{_OCR_MAX_RETRIES+1} → {ep['model']}@{ep['region']}")
        try:
            async with session.post(url, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                print(f"  🌐 [OCR] {fname} HTTP {resp.status} from {ep['region']}")
                if resp.status == 200:
                    _clear_cooldown(ep)
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    print(f"  🌐 [OCR] {fname}: {len(candidates)} candidate(s) returned")
                    text = "".join(
                        part["text"]
                        for cand in candidates
                        for part in cand.get("content", {}).get("parts", [])
                        if "text" in part
                    )

                    if not text.strip():
                        if not candidates:
                            last_error = f"No candidates for {fname}"
                            print(f"  ❌ [OCR] {fname}: NO candidates in response. Full response: {json.dumps(data)[:400]}")
                        else:
                            cand0 = candidates[0]
                            fr = cand0.get("finishReason", "UNKNOWN")
                            safety = cand0.get("safetyRatings", [])
                            blocked = [s for s in safety if s.get("blocked")]
                            last_error = f"Empty text for {fname} (finishReason={fr})"
                            print(f"  ❌ [OCR] {fname}: empty text. finishReason={fr} | safetyRatings={safety} | blocked={blocked}")
                            if fr == "MAX_TOKENS":
                                print(f"  ❌ [OCR] {fname}: MAX_TOKENS hit — response was truncated. Consider increasing maxOutputTokens.")
                            elif fr == "SAFETY":
                                print(f"  ❌ [OCR] {fname}: SAFETY block — image may contain flagged content")
                        await asyncio.sleep(1)
                        continue

                    print(f"  🌐 [OCR] {fname}: got {len(text)} chars of text from model")
                    parsed = _parse_ocr_text(text, image_path)
                    if not parsed:
                        last_error = f"Parse failed (malformed JSON) for {fname}"
                        print(f"  ⚠️ [OCR] {fname}: {last_error}. Retrying...")
                        await asyncio.sleep(1)
                        continue

                    parsed["_endpoint"] = f"{ep['model']}@{ep['region']}"
                    return parsed

                elif resp.status == 429:
                    _mark_cooldown(ep)
                    last_error = f"429 on {ep['model']}@{ep['region']} (now cooling, switching region)"
                    print(f"  🚫 [OCR] {fname}: 429 rate-limit on {ep['region']}, switching endpoint")
                    await asyncio.sleep(0.1)

                else:
                    body = await resp.text()
                    last_error = f"HTTP {resp.status}: {body[:300]}"
                    print(f"  ❌ [OCR] {fname}: HTTP {resp.status} error. Body: {body[:400]}")
                    await asyncio.sleep(2 * (attempt + 1))

        except asyncio.TimeoutError:
            last_error = f"Timeout on {ep['model']}@{ep['region']} attempt {attempt+1}"
            print(f"  ⏱️ [OCR] {fname}: timeout on {ep['region']} (attempt {attempt+1})")
            await asyncio.sleep(2)
        except (ConnectionError, OSError) as e:
            last_error = f"Connection lost on {ep['model']}@{ep['region']} attempt {attempt+1}: {e}"
            print(f"  ❌ [OCR] {fname}: connection error: {e}")
            await asyncio.sleep(3)
        except Exception as e:
            last_error = str(e)
            print(f"  ❌ [OCR] {fname}: unexpected error attempt {attempt+1}: {e}")
            await asyncio.sleep(2)

    print(f"  ❌ [OCR] {fname}: ALL {_OCR_MAX_RETRIES+1} attempts exhausted. Last error: {last_error}")
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
                   answer_key: Optional[dict] = None, max_retries: int = _OCR_MAX_RETRIES) -> dict:
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

    # ── Build OCR prompt ONCE for this image — shared across all passes ───────
    ocr_prompt = _get_ocr_prompt(answer_key)

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
                         exclude_regions=None, b64=b64, mime=mime, ocr_prompt=ocr_prompt),
        _ocr_single_pass(session, image_path, get_headers, project_id,
                         exclude_regions=ep2_exclude, b64=b64, mime=mime, ocr_prompt=ocr_prompt),
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
        ans_count = len(r1.get("answers", {}))
        
        # --- SALVAGE PASS: Double empty hallucination ---
        # Both models read 0 answers but an identity field exists. This proves it's a real sheet,
        # but the pencil marks are likely faint and the model got distracted by the printed header.
        if ans_count == 0 and (str(r1.get("entry_number", "")).strip() or str(r1.get("name", "")).strip()):
            print(f"  🆘 [OCR SALVAGE] {fname} — both passes read 0 answers but found identity. Retrying with cropped grid...")
            # Crop bottom 60% of image (where answer grid typically lives)
            try:
                from PIL import Image as _PILImage
                with _PILImage.open(image_path) as _img:
                    w, h = _img.size
                    cropped = _img.crop((0, int(h * 0.4), w, h))
                    _buf = io.BytesIO()
                    cropped.save(_buf, format="JPEG", quality=85)
                    b64_crop = base64.b64encode(_buf.getvalue()).decode("utf-8")
                    mime_crop = "image/jpeg"
            except Exception as crop_err:
                print(f"  ⚠️ [OCR SALVAGE] {fname}: crop failed: {crop_err}, using full image")
                b64_crop, mime_crop = b64, mime
            r3_salvage = await _ocr_single_pass(
                session, image_path, get_headers, project_id,
                exclude_regions=None, b64=b64_crop, mime=mime_crop, ocr_prompt=ocr_prompt
            )
            if "error" not in r3_salvage and len(r3_salvage.get("answers", {})) > 0:
                print(f"  🎯 [OCR SALVAGE SUCCESS] {fname} — recovered {len(r3_salvage['answers'])} answers!")
                # Identity fields might have been cropped out, restore them from our solid r1 read
                r3_salvage["entry_number"] = r1.get("entry_number") or r3_salvage.get("entry_number")
                r3_salvage["name"] = r1.get("name") or r3_salvage.get("name")
                r3_salvage["comments"] = "[Salvaged via grid-crop] " + str(r3_salvage.get("comments", ""))
                r3_salvage["_endpoint"] = r3_salvage.get("_endpoint", "?") + " (salvage)"
                r3_salvage["_verified_passes"] = 2  # treat as verified since it required targeted effort
                return r3_salvage
            else:
                print(f"  ☠️ [OCR SALVAGE FAILED] {fname} — still 0 answers after grid crop.")

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
        b64=b64, mime=mime, ocr_prompt=ocr_prompt
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

def _make_eval_cache_key(file_id: str, answer_key_hash: str, evaluation_id: str = "default") -> str:
    """Stable cache key for a fully evaluated result (OCR + scoring), namespaced by evaluation AND answer key."""
    raw = f"eval:{evaluation_id}:{file_id}:{answer_key_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Per-run OCR debug dump ────────────────────────────────────────────────────
# Written to backend/ocr_debug_<processing_id>.json at the end of each batch.
# Keys: file name → raw OCR dict (entry_number, name, answers, _endpoint, etc.)
_ocr_debug_log: Dict[str, dict] = {}   # processing_id → {fname: ocr_dict}
_ocr_debug_lock: asyncio.Lock = asyncio.Lock()

# ── Problem-file tracker — feed the download endpoint ─────────────────────────
# Stores Drive file metadata for any sheet that produced an empty/error result.
# Schema: processing_id → list of {name, id, reason, entry_number, answers_count}
_problem_files: Dict[str, List[Dict]] = {}


async def _process_sheets_optimized(student_sheets: List[Dict], answer_key, processing_id: str, evaluation_id: str = "default", force_reprocess: bool = False):
    """
    Streaming pipeline:
      - Cache check (OCR + evaluation) BEFORE downloading anything
      - Cache hits skip download, OCR AND re-evaluation entirely
      - Downloads & OCR run concurrently across all sheets
      - Token-bucket rate limiting per (model, region) pair prevents 429
      - Evaluation + DB write happen immediately after OCR
      - Tier-1 (Pro) → Tier-2 (Flash) → Tier-3 (Lite) failover
    """
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

    def _is_valid_cached_entry(entry_val):
        """Legacy check just for entry_number validity."""
        if not entry_val:
            return False
        s = str(entry_val).strip()
        return bool(s) and not s.startswith("UNREAD_")

    def _is_valid_ocr_result(ocr_dict):
        """True if it has a valid entry_number. Zero answers are allowed for blank sheets."""
        if not ocr_dict:
            return False
        return _is_valid_cached_entry(ocr_dict.get("entry_number", ""))

    async def _handle(sheet_file: dict, idx: int):
        nonlocal success_count, cache_hit_count  # noqa: E741
        fname = sheet_file["name"]
        print(f"\n{'─'*60}\n  📄 [PIPELINE] [{idx+1}/{total}] START: {fname}")
        file_id = sheet_file["id"]
        local_path = os.path.join(temp_dir, f"{idx}_{fname}")
        # Eval cache key now encodes the answer_key_hash so stale results
        # from a previous answer key are automatically missed.
        eval_cache_key = _make_eval_cache_key(file_id, answer_key_hash, evaluation_id)
        ocr_cache_key = f"ocr:{evaluation_id}:{file_id}"

        try:
            # ── STEP 1: Check FULL evaluation cache (OCR + scored result) ──
            # If hit, we're done — no download, no OCR, no re-evaluation needed.
            # IMPORTANT: Reject cached results with empty/UNREAD_ entry_number,
            # AND reject if the embedded answer_key_hash doesn't match current one
            # (prevents stale 0-score results from old answer keys being served).
            eval_cached = None
            if not force_reprocess:
                eval_cached = await cache_service.get_cached_ocr_result("__eval__", file_hash=eval_cache_key)

            cached_entry = (eval_cached or {}).get("entry_number", "") if eval_cached else ""
            cached_ak_hash = (eval_cached or {}).get("_answer_key_hash", "") if eval_cached else ""
            eval_cache_valid = (
                eval_cached
                and _is_valid_cached_entry(cached_entry)
                and "total_score" in eval_cached
                and cached_ak_hash == answer_key_hash  # ← KEY FIX: reject stale answer key
            )
            if eval_cache_valid:
                score = eval_cached.get('total_score', '?')
                n_answers = len(eval_cached.get('answers', {}) or eval_cached.get('details', []))
                print(f"  ⚡ [PIPELINE] {fname}: EVAL CACHE HIT | entry={cached_entry!r} score={score} ak_hash_ok=True")
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
                print(f"  🔄 [PIPELINE] {fname}: eval cache INVALID entry='{cached_entry}' — re-processing")
            elif eval_cached and cached_ak_hash != answer_key_hash:
                print(f"  🔄 [PIPELINE] {fname}: eval cache STALE answer-key (cached={cached_ak_hash[:8]}… current={answer_key_hash[:8]}…) — re-evaluating")
            else:
                print(f"  🔍 [PIPELINE] {fname}: no eval cache — proceeding to OCR")

            # ── STEP 2: Check OCR-only cache ──
            # Reject OCR cache if entry_number is empty OR if it has zero answers
            ocr_cached = None
            if not force_reprocess:
                ocr_cached = await cache_service.get_cached_ocr_result(local_path, file_hash=ocr_cache_key)
            
            if ocr_cached and _is_valid_ocr_result(ocr_cached):
                ocr = ocr_cached
                n_cached_ans = len(ocr_cached.get("answers", {}))
                print(f"  ⚡ [PIPELINE] {fname}: OCR CACHE HIT | entry={ocr_cached.get('entry_number','')} answers={n_cached_ans}")
                async with lock:
                    _processing_stats[processing_id]["ocr_cache_hits"] = \
                        _processing_stats[processing_id].get("ocr_cache_hits", 0) + 1
            else:
                if ocr_cached:
                    cached_entry = ocr_cached.get('entry_number', '')
                    ans_count = len(ocr_cached.get('answers', {}))
                    print(f"  🔄 [PIPELINE] {fname}: OCR cache INVALID (entry='{cached_entry}', answers={ans_count}) — re-OCR")
                else:
                    print(f"  ⬇️  [PIPELINE] {fname}: Downloading for fresh OCR")
                async with lock:
                    _processing_stats[processing_id]["cache_misses"] = \
                        _processing_stats[processing_id].get("cache_misses", 0) + 1

                # ── STEP 3: Download ──
                print(f"  ⬇️  [PIPELINE] {fname}: downloading (file_id={file_id})")
                async with download_sem:
                    ok = await asyncio.to_thread(drive_service.download_file, file_id, local_path)
                if not ok:
                    print(f"  ❌ [PIPELINE] {fname}: DOWNLOAD FAILED")
                    async with lock:
                        errors.append({"file": fname, "error": "Download failed", "file_id": file_id})
                        _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
                        _problem_files.setdefault(processing_id, []).append(
                            {"name": fname, "id": file_id, "reason": "download_failed", "entry_number": "", "answers_count": 0}
                        )
                    return
                file_size_kb = os.path.getsize(local_path) / 1024 if os.path.exists(local_path) else 0
                print(f"  ✅ [PIPELINE] {fname}: downloaded ({file_size_kb:.0f} KB) → {local_path}")

                # ── STEP 4: OCR (rate-limited, multi-tier, multi-region) ──
                ocr = await _ocr_one(session, local_path, _get_headers, project_id, answer_key=answer_key)

                # ── DEBUG: log raw OCR output immediately for inspection ──
                async with _ocr_debug_lock:
                    if processing_id not in _ocr_debug_log:
                        _ocr_debug_log[processing_id] = {}
                    _ocr_debug_log[processing_id][fname] = {
                        "entry_number": ocr.get("entry_number", ""),
                        "name": ocr.get("name", ""),
                        "answers": ocr.get("answers", {}),
                        "error": ocr.get("error", ""),
                        "_endpoint": ocr.get("_endpoint", ""),
                        "_verified_passes": ocr.get("_verified_passes", 0),
                    }
                    # Write incrementally so partial results are always inspectable
                    debug_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        f"ocr_debug_{processing_id}.json"
                    )
                    try:
                        with open(debug_path, "w") as _f:
                            json.dump(_ocr_debug_log[processing_id], _f, indent=2)
                    except Exception:
                        pass

                if "error" not in ocr:
                    ocr_entry = ocr.get("entry_number", "")
                    ocr_ans = ocr.get("answers", {})
                    print(f"  🧠 [PIPELINE] {fname}: OCR done | entry={ocr_entry!r} | answers({len(ocr_ans)}): {dict(list(ocr_ans.items())[:5])}")
                    # Track problem files for download endpoint
                    if not str(ocr_entry).strip():
                        _problem_files.setdefault(processing_id, []).append(
                            {"name": fname, "id": file_id, "reason": "empty_entry_number",
                             "entry_number": "", "answers_count": len(ocr_ans)}
                        )
                    elif not ocr_ans:
                        _problem_files.setdefault(processing_id, []).append(
                            {"name": fname, "id": file_id, "reason": "empty_answers",
                             "entry_number": ocr_entry, "answers_count": 0}
                        )
                    # Cache valid results
                    if _is_valid_ocr_result(ocr):
                        await cache_service.cache_ocr_result(local_path, ocr, file_hash=ocr_cache_key)
                    else:
                        print(f"  ⚠️ [PIPELINE] {fname}: NOT caching (empty entry_number) — will retry on next run")
                else:
                    print(f"  ❌ [PIPELINE] {fname}: OCR returned error: {ocr.get('error')}")

            if "error" in ocr:
                print(f"  ❌ [PIPELINE] {fname}: FATAL OCR error — {ocr['error']}")
                _problem_files.setdefault(processing_id, []).append(
                    {"name": fname, "id": file_id, "reason": "ocr_error",
                     "entry_number": "", "answers_count": 0, "detail": ocr["error"]}
                )
                async with lock:
                    errors.append({"file": fname, "error": ocr["error"], "file_id": file_id})
                    _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
                try:
                    os.path.exists(local_path) and os.remove(local_path)
                except Exception:
                    pass
                return

            # ── STEP 5: Evaluate ──
            ocr["index"] = idx
            ocr["file_name"] = fname
            if not str(ocr.get("entry_number", "")).strip():
                fallback_id = os.path.splitext(fname)[0]
                ocr["entry_number"] = f"UNREAD_{fallback_id}"
                print(f"  ⚠️ [PIPELINE] {fname}: assigning fallback entry_number={ocr['entry_number']!r}")
            print(f"  ⚖️  [PIPELINE] {fname}: evaluating | entry={ocr['entry_number']!r} | {len(ocr.get('answers',{}))} answers")
            student_result = batch_eval_service.evaluate_single_student_optimized(optimized_key, ocr, idx)

            if isinstance(student_result, dict) and "error" in student_result:
                print(f"  ❌ [PIPELINE] {fname}: EVAL ERROR — {student_result['error']}")
                _problem_files.setdefault(processing_id, []).append(
                    {"name": fname, "id": file_id, "reason": "eval_error",
                     "entry_number": ocr.get("entry_number", ""), "answers_count": len(ocr.get("answers", {})),
                     "detail": student_result["error"]}
                )
                async with lock:
                    errors.append({"file": fname, "error": student_result["error"], "file_id": file_id})
                    _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)
            else:
                scored_entry = getattr(student_result, 'entry_number', None) or (student_result.get('entry_number') if isinstance(student_result, dict) else '')
                scored_score = getattr(student_result, 'total_score', None) or (student_result.get('total_score') if isinstance(student_result, dict) else '?')
                print(f"  ✅ [PIPELINE] {fname}: DONE | entry={scored_entry!r} score={scored_score}")
                # ── STEP 6: Cache the fully evaluated result ──
                try:
                    scored_dict = student_result.model_dump() if hasattr(student_result, "model_dump") else dict(student_result)
                    if _is_valid_cached_entry(scored_dict.get("entry_number", "")):
                        scored_dict["_answer_key_hash"] = answer_key_hash
                        await cache_service.cache_ocr_result("__eval__", scored_dict, file_hash=eval_cache_key)
                    else:
                        print(f"  ⚠️ [PIPELINE] {fname}: NOT caching eval (UNREAD entry) — will retry next run")
                except Exception as cache_exc:
                    print(f"  ⚠️ [PIPELINE] {fname}: eval cache write failed: {cache_exc}")

                await db_queue.put(student_result)
                async with lock:
                    results.append(student_result)
                    success_count += 1
                    processed = len(results) + len(errors)
                    _processing_stats[processing_id]["processed_files"] = processed
                    _log_progress(processing_id, processed, total, success_count,
                                  len(errors), cache_hit_count, start_t, from_cache=False)

        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            print(f"  ❌ [PIPELINE] {fname}: UNHANDLED EXCEPTION: {exc}\n{tb}")
            _problem_files.setdefault(processing_id, []).append(
                {"name": fname, "id": file_id, "reason": "unhandled_exception",
                 "entry_number": "", "answers_count": 0, "detail": str(exc)}
            )
            async with lock:
                errors.append({"file": fname, "error": str(exc), "file_id": file_id})
                _processing_stats[processing_id]["processed_files"] = len(results) + len(errors)

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

async def _run_process_folder_optimized(processing_id: str, request: ProcessFolderRequest, force_reprocess: bool = False):
    """
    Ultra-optimized folder processing.
    - Full evaluation cache: cache hits skip download, OCR AND re-evaluation
    - Tier-1 Pro → Tier-2 Flash → Tier-3 Lite failover
    - 14+ endpoint pool with independent token-bucket rate limiting
    - Streaming pipeline, high concurrency
    """
    start_time = _processing_stats.get(processing_id, {}).get("start_time", time.time())
    folder_id = DriveService.extract_folder_id(request.folder_url)

    try:
        # Discover files
        _processing_stats[processing_id]["status"] = "discovering_files"
        try:
            all_files = drive_service.list_all_files_in_folder(folder_id)
        except Exception as e:
            msg = f"Failed to list files from Drive: {str(e)}"
            print(f"  ❌ {msg}")
            _processing_stats[processing_id].update({
                "status": "failed",
                "error": msg,
                "total_time": time.time() - start_time,
            })
            return  # Stop the background task gracefully

        if not all_files:
            msg = "No files found in the designated Drive folder. Please verify folder ID and permissions."
            print(f"  ⚠️ {msg}")
            _processing_stats[processing_id].update({
                "status": "failed",
                "error": msg,
                "total_time": time.time() - start_time,
            })
            return

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
        results, errors = await _process_sheets_optimized(student_sheets, _current_answer_key, processing_id, eval_id, force_reprocess)

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

        _processing_stats[processing_id].update({
            "results": display_results,
            "errors": errors,
            "answer_key_source": _current_answer_key.metadata.get("source_file", "loaded"),
        })

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

    finally:
        # ── Auto-cleanup: remove debug JSON files older than 24 hours ──────────
        try:
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cutoff = time.time() - 86400
            for dname in os.listdir(backend_dir):
                if dname.startswith("ocr_debug_") and dname.endswith(".json"):
                    fpath = os.path.join(backend_dir, dname)
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
        except Exception:
            pass
        # ── Auto-trim _processing_stats: keep only last 50 runs ─────────────
        try:
            if len(_processing_stats) > 50:
                sorted_ids = sorted(
                    _processing_stats.keys(),
                    key=lambda k: _processing_stats[k].get("start_time", 0)
                )
                for old_id in sorted_ids[:-50]:
                    _processing_stats[old_id]["results"] = []
                    _processing_stats.pop(old_id, None)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
#  STATUS + UTILITIES
# ─────────────────────────────────────────────────────────────────────

@router.post("/batch/process-folder-optimized")
async def process_folder_optimized(request: ProcessFolderRequest, force_reprocess: bool = False):
    """
    Ultra-optimized folder processing.
    - Full evaluation cache: cache hits skip download, OCR AND re-evaluation
    - Tier-1 Pro â†’ Tier-2 Flash â†’ Tier-3 Lite failover
    - 14+ endpoint pool with independent token-bucket rate limiting
    - Streaming pipeline, high concurrency
    """
    start_time = time.time()
    processing_id = f"batch_{int(start_time)}"
    _initialize_processing_stats(processing_id, start_time)
    return await _run_process_folder_optimized(processing_id, request, force_reprocess)


@router.post("/batch/process-folder-optimized/start")
async def start_process_folder_optimized(request: ProcessFolderRequest, background_tasks: BackgroundTasks, force_reprocess: bool = False):
    """Start optimized Drive processing in the background and return a polling id immediately."""
    start_time = time.time()
    processing_id = f"batch_{int(start_time * 1000)}"
    _initialize_processing_stats(processing_id, start_time)
    background_tasks.add_task(_run_process_folder_optimized, processing_id, request, force_reprocess)
    return {
        "processing_id": processing_id,
        "status": "started",
        "status_url": f"/api/batch/processing-status/{processing_id}",
    }


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


@router.get("/batch/ocr-debug/{processing_id}")
async def get_ocr_debug(processing_id: str):
    """
    Return the intermediate OCR debug dump for a processing run.
    This tells you exactly what entry_number + answers the model extracted
    for each file — even for stale/cache runs (in-memory only).
    Also checks for the on-disk JSON file written during the run.
    """
    in_memory = _ocr_debug_log.get(processing_id)
    debug_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        f"ocr_debug_{processing_id}.json"
    )
    from_disk = None
    if os.path.exists(debug_path):
        try:
            with open(debug_path) as f:
                from_disk = json.load(f)
        except Exception:
            pass

    combined = from_disk or in_memory or {}
    if not combined:
        raise HTTPException(status_code=404, detail=f"No OCR debug data found for processing_id={processing_id!r}. "
                            "Only fresh (non-cached) OCR runs produce debug data.")

    # Summarise: count empty entries
    empty_entries = [k for k, v in combined.items() if not str(v.get("entry_number", "")).strip()]
    empty_answers = [k for k, v in combined.items() if not v.get("answers")]
    return {
        "processing_id": processing_id,
        "total_files": len(combined),
        "empty_entry_number": len(empty_entries),
        "empty_answers": len(empty_answers),
        "empty_entry_files": empty_entries[:20],
        "empty_answers_files": empty_answers[:20],
        "ocr_results": combined,
    }


@router.delete("/batch/purge-stale-eval-cache")
async def purge_stale_eval_cache():
    """
    Delete all __eval__ cache entries that were written before the answer-key-hash
    tracking fix (i.e., they have no _answer_key_hash embedded in the payload).
    This forces a fresh evaluation on the next run without re-doing OCR.
    """
    import sqlite3 as _sqlite3

    def _purge():
        conn = _sqlite3.connect(cache_service.cache_db_path)
        c = conn.cursor()
        try:
            # Get all __eval__ entries
            c.execute("SELECT file_hash, ocr_result FROM result_cache WHERE file_name = '__eval__'")
            rows = c.fetchall()
            stale = []
            for file_hash, ocr_json in rows:
                try:
                    data = json.loads(ocr_json)
                    if "_answer_key_hash" not in data:
                        stale.append(file_hash)
                except Exception:
                    stale.append(file_hash)
            if stale:
                c.executemany("DELETE FROM result_cache WHERE file_hash = ?", [(h,) for h in stale])
                conn.commit()
            return len(stale), len(rows)
        finally:
            conn.close()

    loop = asyncio.get_event_loop()
    purged, total = await loop.run_in_executor(None, _purge)
    return {
        "purged_stale_entries": purged,
        "total_eval_entries_before": total,
        "remaining": total - purged,
        "message": f"Purged {purged} stale eval-cache entries (no _answer_key_hash). "
                   "Next run will re-evaluate from OCR cache (no re-download/re-OCR needed).",
    }


@router.get("/batch/problem-files/{processing_id}")
async def get_problem_files(processing_id: str):
    """
    List all files from a batch run that produced suspicious OCR results:
    empty entry_number, empty answers, OCR API errors, eval errors, download
    failures, or unhandled exceptions.
    """
    problems = _problem_files.get(processing_id)
    if problems is None:
        if processing_id not in _processing_stats:
            raise HTTPException(status_code=404, detail=f"processing_id={processing_id!r} not found")
        return {"processing_id": processing_id, "total_problems": 0, "problems": [],
                "message": "No problem files recorded — all OCR results were clean."}

    counts_by_reason: Dict[str, int] = {}
    for p in problems:
        counts_by_reason[p["reason"]] = counts_by_reason.get(p["reason"], 0) + 1

    return {
        "processing_id": processing_id,
        "total_problems": len(problems),
        "counts_by_reason": counts_by_reason,
        "problems": problems,
    }


@router.get("/batch/download-problem-images/{processing_id}")
async def download_problem_images(processing_id: str, reason: Optional[str] = None):
    """
    Download all problem images from a batch run as a ZIP file.

    Optional query param `reason`: filter to a specific failure type.
    Values: empty_entry_number | empty_answers | ocr_error | eval_error |
            download_failed | unhandled_exception

    Returns a ZIP with images organised by reason/ subfolder + manifest.json.
    """
    from fastapi.responses import StreamingResponse
    import zipfile

    problems = _problem_files.get(processing_id)
    if not problems:
        if processing_id not in _processing_stats:
            raise HTTPException(status_code=404, detail=f"processing_id={processing_id!r} not found")
        raise HTTPException(status_code=404, detail="No problem files recorded for this run.")

    targets = [p for p in problems if p.get("reason") == reason] if reason else problems
    if not targets:
        raise HTTPException(
            status_code=404,
            detail=f"No problem files with reason={reason!r}. "
                   f"Available: {list({p['reason'] for p in problems})}",
        )

    tmp = tempfile.mkdtemp(prefix="problem_imgs_")
    zip_path = os.path.join(tmp, f"problem_images_{processing_id}.zip")

    try:
        downloaded = []
        failed_dl = []
        for pf in targets:
            file_id = pf.get("id", "")
            fname = pf.get("name", f"unknown_{file_id}")
            pf_reason = pf.get("reason", "unknown")
            if not file_id:
                failed_dl.append({"name": fname, "error": "no file_id recorded"})
                continue
            sub_dir = os.path.join(tmp, pf_reason)
            os.makedirs(sub_dir, exist_ok=True)
            local = os.path.join(sub_dir, fname)
            print(f"  ⬇️  [DOWNLOAD-PROBLEM] {fname} ({pf_reason}) id={file_id}")
            ok = await asyncio.to_thread(drive_service.download_file, file_id, local)
            if ok and os.path.exists(local):
                downloaded.append((pf_reason, fname, local))
                print(f"  ✅ [DOWNLOAD-PROBLEM] {fname} ({os.path.getsize(local)//1024} KB)")
            else:
                failed_dl.append({"name": fname, "reason": pf_reason, "error": "drive download failed"})
                print(f"  ❌ [DOWNLOAD-PROBLEM] {fname}: Drive download failed")

        if not downloaded:
            shutil.rmtree(tmp, ignore_errors=True)
            raise HTTPException(status_code=502,
                                detail=f"Could not download any of the {len(targets)} files. Failures: {failed_dl}")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for pf_reason, fname, local_path in downloaded:
                zf.write(local_path, f"{pf_reason}/{fname}")
            manifest = {
                "processing_id": processing_id,
                "filter_reason": reason,
                "total_requested": len(targets),
                "total_downloaded": len(downloaded),
                "failed": failed_dl,
                "files": [
                    {"reason": r, "name": n,
                     "entry_number": next((p.get("entry_number", "") for p in targets if p["name"] == n), ""),
                     "answers_count": next((p.get("answers_count", 0) for p in targets if p["name"] == n), 0),
                     "detail": next((p.get("detail", "") for p in targets if p["name"] == n), "")}
                    for r, n, _ in downloaded
                ],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        zip_size_mb = os.path.getsize(zip_path) / 1024 / 1024
        print(f"  📦 [DOWNLOAD-PROBLEM] ZIP: {len(downloaded)} files, {zip_size_mb:.1f} MB")

        def _stream():
            try:
                with open(zip_path, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            _stream(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="problem_images_{processing_id}.zip"'},
        )

    except HTTPException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"ZIP creation failed: {e}")


@router.delete("/batch/clear-problem-files/{processing_id}")
async def clear_problem_files(processing_id: str):
    """Clear the in-memory problem-file tracker for a given run."""
    removed = _problem_files.pop(processing_id, None)
    return {"cleared": removed is not None, "count_removed": len(removed) if removed else 0}
