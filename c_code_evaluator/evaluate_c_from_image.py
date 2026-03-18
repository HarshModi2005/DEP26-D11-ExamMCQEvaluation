#!/usr/bin/env python3
"""
Vanilla C-code evaluator pipeline:
1) OCR (Gemini) to extract C code from an image
2) Write extracted code to a .c file and also a .txt file
3) Compile with gcc
4) Run the binary (optional stdin) and capture stdout/stderr
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import requests


DEFAULT_MODEL = os.getenv("GEMINI_OCR_MODEL", "gemini-2.5-flash-lite")
DEFAULT_VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
DEFAULT_VERTEX_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT_ID")


def _encode_image_base64(image_path: Path) -> Tuple[str, str]:
    ext = image_path.suffix.lower().lstrip(".")
    mime_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    mime_type = mime_type_map.get(ext, "image/jpeg")
    data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return data, mime_type


def _gemini_stream_generate_content(api_key: str, model: str, payload: dict, timeout_s: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}"
    resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    result = resp.json()

    parts: list[str] = []
    if isinstance(result, list):
        for chunk in result:
            for cand in chunk.get("candidates", []) or []:
                content = cand.get("content") or {}
                for part in content.get("parts", []) or []:
                    text = part.get("text")
                    if text:
                        parts.append(text)
    elif isinstance(result, dict):
        for cand in result.get("candidates", []) or []:
            content = cand.get("content") or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if text:
                    parts.append(text)

    return "".join(parts).strip()


def _vertex_stream_generate_content(
    project_id: str,
    location: str,
    model: str,
    payload: dict,
    timeout_s: int,
) -> str:
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "Vertex auth requested (GOOGLE_APPLICATION_CREDENTIALS detected), but google-auth is not available. "
            "Install it (pip install google-auth) or use an API key."
        ) from e

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise SystemExit(
            "GOOGLE_APPLICATION_CREDENTIALS is not set or points to a missing file. "
            "Either set it correctly or use an API key."
        )

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/publishers/google/models/{model}:streamGenerateContent"
    )
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    result = resp.json()

    parts: list[str] = []
    if isinstance(result, list):
        for chunk in result:
            for cand in chunk.get("candidates", []) or []:
                content = cand.get("content") or {}
                for part in content.get("parts", []) or []:
                    text = part.get("text")
                    if text:
                        parts.append(text)
    elif isinstance(result, dict):
        for cand in result.get("candidates", []) or []:
            content = cand.get("content") or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if text:
                    parts.append(text)

    return "".join(parts).strip()


def _strip_markdown_fences(text: str) -> str:
    # Remove ```c, ```C, ``` etc fences if the model returns them anyway
    text = re.sub(r"```[a-zA-Z0-9_+-]*\s*", "", text)
    text = text.replace("```", "")
    return text.strip()


def extract_c_code_from_image(
    image_path: Path,
    *,
    api_key: Optional[str],
    model: str = DEFAULT_MODEL,
    timeout_s: int = 60,
    vertex_project_id: Optional[str] = None,
    vertex_location: str = DEFAULT_VERTEX_LOCATION,
) -> str:
    base64_image, mime_type = _encode_image_base64(image_path)

    prompt = (
        "You are doing OCR on a photo of handwritten/printed C source code.\n"
        "Return ONLY the reconstructed C code as plain text.\n"
        "- Do NOT add explanations.\n"
        "- Do NOT wrap in markdown fences.\n"
        "- Preserve newlines and indentation.\n"
        "- If a character is unclear, make your best guess.\n"
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": base64_image}},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
    }

    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        project_id = vertex_project_id or DEFAULT_VERTEX_PROJECT
        if not project_id:
            raise SystemExit(
                "GOOGLE_APPLICATION_CREDENTIALS is set, but project id is missing. "
                "Set GOOGLE_CLOUD_PROJECT (or pass --vertex-project-id)."
            )
        raw = _vertex_stream_generate_content(
            project_id=project_id,
            location=vertex_location,
            model=model,
            payload=payload,
            timeout_s=timeout_s,
        )
    else:
        if not api_key:
            raise SystemExit(
                "Missing API key. Set one of GOOGLE_API_KEY / VERTEX_AI_API_KEY / GEMINI_API_KEY "
                "or pass --api-key (or set GOOGLE_APPLICATION_CREDENTIALS for Vertex auth)."
            )
        raw = _gemini_stream_generate_content(api_key=api_key, model=model, payload=payload, timeout_s=timeout_s)
    return _strip_markdown_fences(raw)


@dataclass
class CompileRunResult:
    compile_ok: bool
    compile_stdout: str
    compile_stderr: str
    run_ok: bool
    run_stdout: str
    run_stderr: str
    exit_code: Optional[int]
    timed_out: bool


def compile_c(source_path: Path, binary_path: Path, timeout_s: int = 20) -> Tuple[bool, str, str]:
    proc = subprocess.run(
        ["gcc", str(source_path), "-O2", "-std=c11", "-Wall", "-Wextra", "-o", str(binary_path)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    ok = proc.returncode == 0
    return ok, proc.stdout, proc.stderr


def run_binary(binary_path: Path, stdin_text: Optional[str], timeout_s: int = 2) -> Tuple[bool, str, str, Optional[int], bool]:
    try:
        proc = subprocess.run(
            [str(binary_path)],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return proc.returncode == 0, proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        err = e.stderr or ""
        return False, out, err, None, True


def _resolve_api_key(cli_api_key: Optional[str]) -> str:
    key = cli_api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("VERTEX_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise SystemExit(
            "Missing API key. Set one of GOOGLE_API_KEY / VERTEX_AI_API_KEY / GEMINI_API_KEY "
            "or pass --api-key."
        )
    return key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Path to code image (jpg/png/webp/...)")
    parser.add_argument("--out-dir", default=str(Path(__file__).parent / "output"), help="Output directory")
    parser.add_argument("--api-key", default=None, help="Gemini API key (or use env var)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model id (default from env or flash-lite)")
    parser.add_argument("--vertex-project-id", default=None, help="Vertex project id (if using service account auth)")
    parser.add_argument("--vertex-location", default=DEFAULT_VERTEX_LOCATION, help="Vertex location/region")
    parser.add_argument("--stdin-file", default=None, help="Optional file to provide stdin to the compiled program")
    parser.add_argument(
        "--run-anyway",
        action="store_true",
        help="Run even if no --stdin-file is provided (may time out if program waits for input).",
    )
    parser.add_argument("--run-timeout-s", type=int, default=2, help="Program run timeout seconds")
    parser.add_argument("--ocr-timeout-s", type=int, default=60, help="OCR request timeout seconds")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = image_path.stem
    code_txt_path = out_dir / f"{base}_{stamp}_ocr.txt"
    code_c_path = out_dir / f"{base}_{stamp}.c"
    compile_log_path = out_dir / f"{base}_{stamp}_compile.txt"
    run_log_path = out_dir / f"{base}_{stamp}_run.txt"
    binary_path = out_dir / f"{base}_{stamp}.out"

    api_key: Optional[str]
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        api_key = None
    else:
        api_key = _resolve_api_key(args.api_key)

    code = extract_c_code_from_image(
        image_path=image_path,
        api_key=api_key,
        model=args.model,
        timeout_s=args.ocr_timeout_s,
        vertex_project_id=args.vertex_project_id,
        vertex_location=args.vertex_location,
    )

    code_txt_path.write_text(code + "\n", encoding="utf-8")
    code_c_path.write_text(code + "\n", encoding="utf-8")

    compile_ok, c_out, c_err = compile_c(code_c_path, binary_path)
    compile_log_path.write_text(
        f"compile_ok={compile_ok}\n\n=== gcc stdout ===\n{c_out}\n\n=== gcc stderr ===\n{c_err}\n",
        encoding="utf-8",
    )

    stdin_text = None
    if args.stdin_file:
        stdin_text = Path(args.stdin_file).expanduser().read_text(encoding="utf-8")

    did_run = False
    if compile_ok and (stdin_text is not None or args.run_anyway):
        did_run = True
        run_ok, r_out, r_err, exit_code, timed_out = run_binary(
            binary_path=binary_path,
            stdin_text=stdin_text,
            timeout_s=args.run_timeout_s,
        )
    elif compile_ok and stdin_text is None and not args.run_anyway:
        run_ok, r_out, r_err, exit_code, timed_out = True, "", "", 0, False
    else:
        run_ok, r_out, r_err, exit_code, timed_out = False, "", "", None, False

    run_log_path.write_text(
        f"did_run={did_run}\nrun_ok={run_ok}\nexit_code={exit_code}\ntimed_out={timed_out}\n\n"
        f"=== program stdout ===\n{r_out}\n\n=== program stderr ===\n{r_err}\n",
        encoding="utf-8",
    )

    print("Saved:")
    print(f"- OCR text: {code_txt_path}")
    print(f"- C source: {code_c_path}")
    print(f"- Compile log: {compile_log_path}")
    print(f"- Run log: {run_log_path}")
    if compile_ok:
        print(f"- Binary: {binary_path}")

    # If we didn't run (no stdin provided), consider compile success as overall success.
    return 0 if (compile_ok and run_ok and not timed_out) else 1


if __name__ == "__main__":
    raise SystemExit(main())

