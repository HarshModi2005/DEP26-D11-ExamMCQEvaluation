"""
Google Workspace Gemini Parallelism Stress Test (March 2026)
============================================================
Progressively ramps up concurrent requests to the Gemini 3.1 Flash Lite
endpoint to find the max safe parallelism level.

Usage:
    python test_gemini_parallelism.py
"""

import os
import sys
import time
import json
import asyncio
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
import google.auth.transport.requests

# ── Load .env ─────────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# ── SETTINGS ──────────────────────────────────────────────────────────────────
MODEL_ID   = "gemini-3.1-flash-lite"   # Latest Gemini 3.1 series
LOCATION   = "us-central1"
CONCURRENCY_LEVELS   = [1, 2, 4, 8, 12, 16, 20, 25, 30, 40, 50]
REQUESTS_PER_LEVEL   = 20
TIMEOUT_SECONDS      = 30
BETWEEN_LEVELS_PAUSE = 3

# ── Service Account Auth ──────────────────────────────────────────────────────
CREDS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if not CREDS_PATH or not os.path.exists(CREDS_PATH):
    print("❌  GOOGLE_APPLICATION_CREDENTIALS not set or file missing.")
    sys.exit(1)

_sa_creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
PROJECT_ID = _sa_creds.project_id or "project-75abf07c-e594-4660-ab7"

API_URL = (
    f"https://{LOCATION}-aiplatform.googleapis.com/v1/"
    f"projects/{PROJECT_ID}/locations/{LOCATION}/"
    f"publishers/google/models/{MODEL_ID}:generateContent"
)

def get_bearer_token() -> str:
    req = google.auth.transport.requests.Request()
    _sa_creds.refresh(req)
    return _sa_creds.token

# ── Minimal payload ───────────────────────────────────────────────────────────
PAYLOAD = {
    "contents": [{"role": "user", "parts": [{"text": "Reply with ONLY the word: OK"}]}],
    "generationConfig": {"maxOutputTokens": 8, "temperature": 0.0},
}

# ── Single async request ──────────────────────────────────────────────────────
async def single_request(session, req_id, bearer_token):
    start = time.monotonic()
    result = {"req_id": req_id, "status": None, "latency_ms": None, "error": None, "rate_limited": False}
    headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
    try:
        async with session.post(API_URL, headers=headers, json=PAYLOAD, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)) as resp:
            elapsed_ms = (time.monotonic() - start) * 1000
            result["status"] = resp.status
            result["latency_ms"] = round(elapsed_ms, 1)
            if resp.status == 429:
                result["rate_limited"] = True
                result["error"] = f"429 — {await resp.text()}"
            elif resp.status != 200:
                result["error"] = f"HTTP {resp.status} — {await resp.text()}"
    except asyncio.TimeoutError:
        result["latency_ms"] = TIMEOUT_SECONDS * 1000
        result["status"] = -1
        result["error"] = "TIMEOUT"
    except Exception as exc:
        result["latency_ms"] = round((time.monotonic() - start) * 1000, 1)
        result["status"] = -1
        result["error"] = str(exc)
    return result

# ── Probe one level ───────────────────────────────────────────────────────────
async def probe_level(concurrency, bearer_token):
    sem = asyncio.Semaphore(concurrency)
    async def bounded(session, i):
        async with sem: return await single_request(session, i, bearer_token)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        tasks = [asyncio.create_task(bounded(session, i)) for i in range(REQUESTS_PER_LEVEL)]
        results = await asyncio.gather(*tasks)
    ok = [r for r in results if r["status"] == 200]; rl = [r for r in results if r["rate_limited"]]
    errs = [r for r in results if r["error"] and not r["rate_limited"]]
    lats = [r["latency_ms"] for r in ok if r["latency_ms"] is not None]
    return {
        "concurrency": concurrency, "total": len(results), "success_count": len(ok),
        "rate_limit_count": len(rl), "other_error_count": len(errs),
        "success_rate_pct": round(len(ok) / len(results) * 100, 1) if results else 0,
        "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else None,
        "max_latency_ms": round(max(lats), 1) if lats else None,
        "sample_rl_errors": [r["error"] for r in rl][:3]
    }

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 68)
    print("  Google Workspace Gemini — Parallelism Stress Test (2026)")
    print(f"  Model    : {MODEL_ID}")
    print(f"  Project  : {PROJECT_ID}  |  Region: {LOCATION}")
    print(f"  Auth     : Service Account  ({os.path.basename(CREDS_PATH)})")
    print(f"  Levels   : {CONCURRENCY_LEVELS}")
    print("=" * 68)

    print("\n🔑 Refreshing token …", end=" ", flush=True)
    try:
        token = get_bearer_token()
        print("✅\n")
    except Exception as e:
        print(f"❌ {e}"); sys.exit(1)

    all_results = []; safe_limit = 0; hit_limit = False; last_level = 0
    for level in CONCURRENCY_LEVELS:
        print(f"▶  concurrency = {level:>3} …", end="  ", flush=True)
        t0 = time.monotonic(); lvl = await probe_level(level, token); wall_s = time.monotonic() - t0
        all_results.append(lvl); last_level = level
        print(f"✅ {lvl['success_count']}/{lvl['total']} ({lvl['success_rate_pct']}%) ⏱ avg={lvl['avg_latency_ms']}ms 🚫 RL={lvl['rate_limit_count']} [{wall_s:.1f}s]")
        if lvl["rate_limit_count"] > 0:
            print(f"\n🛑  Rate limiting detected at concurrency={level}!")
            hit_limit = True; break
        else: safe_limit = level
        if level != CONCURRENCY_LEVELS[-1]: await asyncio.sleep(BETWEEN_LEVELS_PAUSE)

    print("\n" + "=" * 68)
    print(f"📊  RESULT SUMMARY")
    print(f"   Safe parallel limit : {safe_limit} concurrent Gemini calls")
    print(f"   Rate-limited at     : {last_level if hit_limit else 'N/A'} concurrent calls")
    print("=" * 68)

    report_path = os.path.join(os.path.dirname(__file__), "gemini_parallelism_results.json")
    with open(report_path, "w") as f: json.dump({"timestamp": datetime.now().isoformat(), "model": MODEL_ID, "safe_limit": safe_limit, "results": all_results}, f, indent=2)
    print(f"💾  Saved → {report_path}\n")

if __name__ == "__main__":
    asyncio.run(main())
