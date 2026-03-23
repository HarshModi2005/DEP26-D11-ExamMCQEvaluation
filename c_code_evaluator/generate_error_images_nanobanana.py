#!/usr/bin/env python3
"""
Generate synthetic code-image variants with subtle and major errors using
Google Gemini image generation/editing ("Nano Banana"-style workflow).

Inputs:
- Base images (default: test_images_new/converted)
- Auth via Vertex project credentials or API key (Vertex Express / Gemini API)

Outputs:
- Generated images in categorized folders
- Per-image metadata JSON (prompt + source + model response info)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


DEFAULT_MODEL = os.getenv("NANO_BANANA_MODEL", "gemini-2.5-flash-image")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
VERTEX_EXPRESS_API_BASE = "https://aiplatform.googleapis.com/v1/publishers/google/models"
DEFAULT_VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

SUBTLE_ERROR_PROMPTS = [
    "Introduce exactly one subtle off-by-one bug in the range sum formula (e.g. wrong left index handling), while keeping code otherwise clean.",
    "Replace long long-based prefix storage with int-based storage to create overflow risk on large values; keep everything else similar.",
    "Keep logic mostly correct but print answers in a subtly wrong format (single-line space-separated instead of one-per-line).",
    "Create a subtle indexing mismatch between 1-indexed queries and prefix array usage without changing overall structure much.",
    "Introduce a tiny loop-bound bug affecting only edge cases (like first/last query).",
]

MAJOR_ERROR_PROMPTS = [
    "Introduce multiple syntax issues (missing semicolon/brace and at least one misspelled C function name like scanf/printf).",
    "Create a major logical bug by swapping roles of n and q in loops/allocation so the program compiles but behaves incorrectly.",
    "Break the include/header section (missing needed header or malformed include) and include at least one undeclared identifier error.",
    "Produce a visibly flawed program with both syntax and logic mistakes that would fail compilation under gcc -std=c11.",
    "Create a strongly incorrect solution that compiles but uses a fundamentally wrong approach for range sums.",
]


@dataclass
class VariantSpec:
    category: str
    prompt: str
    index: int


@dataclass
class RequestConfig:
    mode: str
    url: str
    headers: dict[str, str]


def resolve_project_id(cli_project: Optional[str]) -> Optional[str]:
    return cli_project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT_ID")


def resolve_vertex_token() -> str:
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "google-auth is required for Vertex service-account auth. Install with: pip install google-auth"
        ) from e

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise SystemExit(
            "GOOGLE_APPLICATION_CREDENTIALS is missing. Set it or use --api-mode vertex_express/gemini_api."
        )

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds.token


def build_request_config(
    *,
    mode: str,
    model: str,
    api_key: Optional[str],
    vertex_project_id: Optional[str],
    vertex_location: str,
) -> RequestConfig:
    chosen = mode
    if chosen == "auto":
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and vertex_project_id:
            chosen = "vertex_project"
        else:
            chosen = "vertex_express"

    if chosen == "vertex_project":
        if not vertex_project_id:
            raise SystemExit("Missing Vertex project id. Set GOOGLE_CLOUD_PROJECT / VERTEX_PROJECT_ID or pass --vertex-project-id.")
        token = resolve_vertex_token()
        url = (
            f"https://{vertex_location}-aiplatform.googleapis.com/v1/projects/{vertex_project_id}"
            f"/locations/{vertex_location}/publishers/google/models/{model}:generateContent"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        return RequestConfig(mode=chosen, url=url, headers=headers)

    if chosen == "vertex_express":
        if not api_key:
            raise SystemExit("Missing API key for vertex_express mode. Pass --api-key or set GOOGLE_API_KEY.")
        url = f"{VERTEX_EXPRESS_API_BASE}/{model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        return RequestConfig(mode=chosen, url=url, headers=headers)

    if chosen == "gemini_api":
        if not api_key:
            raise SystemExit("Missing API key for gemini_api mode. Pass --api-key or set GOOGLE_API_KEY.")
        url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        return RequestConfig(mode=chosen, url=url, headers=headers)

    raise SystemExit(f"Unsupported --api-mode: {mode}")


def image_to_b64(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise SystemExit(f"Unsupported image extension for {path}. Supported: {sorted(SUPPORTED_EXTS)}")
    mime = MIME_BY_EXT[ext]
    return base64.b64encode(path.read_bytes()).decode("utf-8"), mime


def find_source_images(input_dir: Path) -> list[Path]:
    files = [p for p in sorted(input_dir.iterdir()) if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    if not files:
        raise SystemExit(f"No supported images found in {input_dir}")
    return files


def build_edit_prompt(error_instruction: str) -> str:
    return (
        "You are editing a photo of handwritten/printed C code for a competitive-programming prefix-sum problem.\n"
        "Keep the same visual style, handwriting/print look, lighting, framing, and paper/background.\n"
        "Edit only the code content to create a realistic student-written variant.\n"
        "Do not add explanations, labels, watermarks, or extra non-code text.\n"
        "Return an edited image only.\n\n"
        f"Required edit:\n{error_instruction}\n"
    )


def build_inline_part(mode: str, mime: str, data_b64: str) -> dict:
    if mode == "gemini_api":
        return {"inline_data": {"mime_type": mime, "data": data_b64}}
    return {"inlineData": {"mimeType": mime, "data": data_b64}}


def extract_inline_image_part(resp_json: dict) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Returns (image_bytes, mime_type, text_fallback).
    Accepts both snake_case and camelCase payload keys.
    """
    text_parts: list[str] = []

    for cand in resp_json.get("candidates", []) or []:
        content = cand.get("content") or {}
        for part in content.get("parts", []) or []:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and ("data" in inline):
                mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                try:
                    return base64.b64decode(inline["data"]), mime, None
                except Exception:
                    pass
            if "text" in part and part["text"]:
                text_parts.append(str(part["text"]))

    fallback = "\n".join(text_parts).strip() if text_parts else None
    return None, None, fallback


def call_nanobanana_edit(
    *,
    request_config: RequestConfig,
    source_path: Path,
    prompt: str,
    timeout_s: int = 120,
    max_retries: int = 6,
) -> tuple[bytes, str, dict]:
    img_b64, mime = image_to_b64(source_path)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    build_inline_part(request_config.mode, mime, img_b64),
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    last_err: Optional[Exception] = None
    retryable_codes = {429, 500, 502, 503, 504}
    for attempt in range(1, max_retries + 2):
        try:
            resp = requests.post(request_config.url, headers=request_config.headers, json=payload, timeout=timeout_s)
            if resp.status_code in retryable_codes:
                snippet = (resp.text or "")[:800]
                last_err = RuntimeError(f"HTTP {resp.status_code}: {snippet}")
                if attempt <= max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait_s = max(1.0, float(retry_after))
                    else:
                        wait_s = min(10.0 * attempt, 60.0)
                    time.sleep(wait_s)
                    continue
                raise last_err
            resp.raise_for_status()
            data = resp.json()
            out_bytes, out_mime, text_fallback = extract_inline_image_part(data)
            if out_bytes and out_mime:
                return out_bytes, out_mime, data
            msg = text_fallback or f"Response did not include an image. Raw keys: {list(data.keys())}"
            raise RuntimeError(msg)
        except Exception as e:
            last_err = e
            if attempt <= max_retries:
                time.sleep(min(5.0 * attempt, 30.0))
                continue
            raise RuntimeError(f"Image generation failed after retries: {e}") from e

    raise RuntimeError(f"Image generation failed: {last_err}")


def choose_variants(
    *,
    subtle_count: int,
    major_count: int,
    rng: random.Random,
) -> list[VariantSpec]:
    subtle = SUBTLE_ERROR_PROMPTS[:]
    major = MAJOR_ERROR_PROMPTS[:]
    rng.shuffle(subtle)
    rng.shuffle(major)

    subtle_sel = subtle[: max(0, min(subtle_count, len(subtle)))]
    major_sel = major[: max(0, min(major_count, len(major)))]

    specs: list[VariantSpec] = []
    for i, p in enumerate(subtle_sel, start=1):
        specs.append(VariantSpec(category="subtle", prompt=p, index=i))
    for i, p in enumerate(major_sel, start=1):
        specs.append(VariantSpec(category="major", prompt=p, index=i))
    return specs


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic erroneous code images using Nano Banana/Gemini image editing.")
    parser.add_argument("--input-dir", default="test_images_new/converted", help="Folder with source images")
    parser.add_argument("--output-dir", default="test_images_new/generated_errors", help="Folder to write generated outputs")
    parser.add_argument("--api-mode", choices=["auto", "vertex_project", "vertex_express", "gemini_api"], default="auto", help="Auth/API route to use")
    parser.add_argument("--api-key", default=None, help="API key (required for vertex_express or gemini_api)")
    parser.add_argument("--vertex-project-id", default=None, help="Vertex project id for vertex_project mode")
    parser.add_argument("--vertex-location", default=DEFAULT_VERTEX_LOCATION, help="Vertex location (default: us-central1)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model id (default: gemini-2.5-flash-image)")
    parser.add_argument("--subtle-per-image", type=int, default=3, help="How many subtle variants per source image")
    parser.add_argument("--major-per-image", type=int, default=3, help="How many major variants per source image")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for prompt selection")
    parser.add_argument("--timeout-s", type=int, default=120, help="Per-request timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=6, help="Retries for 429/5xx/API transient failures")
    parser.add_argument("--request-delay-s", type=float, default=None, help="Delay between API requests (seconds)")
    args = parser.parse_args()

    vertex_project_id = resolve_project_id(args.vertex_project_id)
    api_key = args.api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("VERTEX_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    request_config = build_request_config(
        mode=args.api_mode,
        model=args.model,
        api_key=api_key,
        vertex_project_id=vertex_project_id,
        vertex_location=args.vertex_location,
    )
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = find_source_images(input_dir)
    rng = random.Random(args.seed)
    request_delay_s = args.request_delay_s
    if request_delay_s is None:
        # Vertex Express API keys often have low per-minute request budgets.
        request_delay_s = 6.5 if request_config.mode == "vertex_express" else 0.0

    print(f"Using model: {args.model}")
    print(f"API mode: {request_config.mode}")
    print(f"Endpoint: {request_config.url}")
    print(f"Input dir: {input_dir}")
    print(f"Output dir: {output_dir}")
    print(f"Source images: {len(sources)}")

    generated = 0
    failed = 0
    request_count = 0

    for src in sources:
        base = src.stem
        specs = choose_variants(
            subtle_count=args.subtle_per_image,
            major_count=args.major_per_image,
            rng=rng,
        )
        print(f"\n== Source: {src.name} | variants: {len(specs)} ==")

        for spec in specs:
            cat_dir = output_dir / spec.category
            cat_dir.mkdir(parents=True, exist_ok=True)

            prompt = build_edit_prompt(spec.prompt)
            name_prefix = f"{base}__{spec.category}_{spec.index:02d}"

            try:
                if request_count > 0 and request_delay_s > 0:
                    time.sleep(request_delay_s)
                request_count += 1
                out_bytes, out_mime, raw_resp = call_nanobanana_edit(
                    request_config=request_config,
                    source_path=src,
                    prompt=prompt,
                    timeout_s=args.timeout_s,
                    max_retries=args.max_retries,
                )
                out_ext = EXT_BY_MIME.get(out_mime.lower(), ".png")
                out_path = cat_dir / f"{name_prefix}{out_ext}"
                out_path.write_bytes(out_bytes)

                meta = {
                    "source_image": str(src),
                    "output_image": str(out_path),
                    "category": spec.category,
                    "variant_index": spec.index,
                    "model": args.model,
                    "api_mode": request_config.mode,
                    "prompt": prompt,
                    "response_mime_type": out_mime,
                }
                meta_path = cat_dir / f"{name_prefix}.json"
                meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

                # Keep minimal raw response trace for debugging image-less responses.
                trace_path = cat_dir / f"{name_prefix}_trace.json"
                trace_path.write_text(json.dumps(raw_resp, indent=2) + "\n", encoding="utf-8")

                generated += 1
                print(f"[OK] {spec.category}:{spec.index} -> {out_path.name}")
            except Exception as e:
                failed += 1
                print(f"[FAIL] {spec.category}:{spec.index} for {src.name}: {e}")

    print("\nDone.")
    print(f"Generated: {generated}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
