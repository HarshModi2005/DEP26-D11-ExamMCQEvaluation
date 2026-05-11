"""
Code Evaluation Endpoints
=========================
Routes for the LeetCode-style code evaluation pipeline.
Reuses OCR → compile-fix → LeetCode test case evaluation from c_code_evaluator.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "c_code_evaluator"))

# ── Ensure Vertex AI credentials are available BEFORE importing c_code_evaluator ──
# (evaluate_c_from_image reads GOOGLE_CLOUD_PROJECT at import time)
_vertex_key_path = str(Path(__file__).resolve().parent.parent / "vertex_key.json")
if os.path.exists(_vertex_key_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _vertex_key_path
    try:
        with open(_vertex_key_path) as _f:
            _vertex_data = json.load(_f)
            if _vertex_data.get("project_id"):
                os.environ["GOOGLE_CLOUD_PROJECT"] = _vertex_data["project_id"]
    except Exception:
        pass

from evaluate_c_from_image import (
    extract_c_code_from_image,
    compile_c,
    fix_ocr_syntax_errors,
    validate_trivial_fix,
    _encode_image_base64,
    _vertex_stream_generate_content,
)
from leetcode_mode import (
    resolve_leetcode_problem_and_cases,
    evaluate_leetcode_cases,
)
from services.drive_service import DriveService

router = APIRouter(prefix="/api/code-eval", tags=["code-evaluation"])
drive_service = DriveService()

# ── Request / Response models ──

class CodeEvalRequest(BaseModel):
    """Request body for ZIP-based code evaluation."""
    answer_key: Dict[str, Any]  # { problems: { "1": { slug: "two-sum", marks: 2 } } }


class DriveCodeEvalRequest(BaseModel):
    """Request body for Drive-folder-based code evaluation."""
    folder_url: str
    answer_key: Dict[str, Any]


class CodeEvalResult(BaseModel):
    total_students_processed: int
    results: List[Dict[str, Any]]
    errors: List[str]


# ── Helpers ──

def _extract_student_info_from_filename(filename: str) -> Dict[str, str]:
    """Try to parse enrollment number and name from filename."""
    stem = Path(filename).stem
    parts = re.split(r'[_\-\s]+', stem, maxsplit=1)
    entry = parts[0] if parts else stem
    name = parts[1].replace('_', ' ') if len(parts) > 1 else ""
    return {"entry_number": entry, "name": name}


def _extract_student_info_from_image(image_path: Path, api_key: str) -> Dict[str, str]:
    """Use OCR to extract student name and entry number from the image header."""
    try:
        base64_image, mime_type = _encode_image_base64(image_path)
        prompt = (
            "Look at this image of an answer sheet. "
            "Extract ONLY the student's Name and Entry Number / Roll Number from the image header.\n"
            "Return ONLY a JSON object like: {\"name\": \"John Doe\", \"entry_number\": \"2023CSB1064\"}\n"
            "If you cannot find either field, use an empty string for that field.\n"
            "Return ONLY the JSON, no explanations."
        )
        payload = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": base64_image}},
            ]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 256},
        }
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        location = os.environ.get("VERTEX_LOCATION", "us-central1")
        model = os.environ.get("GEMINI_OCR_MODEL", "gemini-2.5-flash-lite")

        raw = None

        # Try Vertex AI first, fall back to API key if it fails
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and project_id:
            try:
                raw = _vertex_stream_generate_content(
                    project_id=project_id,
                    location=location,
                    model=model,
                    payload=payload,
                    timeout_s=30,
                )
            except (SystemExit, Exception) as ve:
                print(f"  ⚠️ Vertex AI failed, falling back to API key: {ve}")
                raw = None

        if raw is None and api_key:
            import requests as req
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            resp = req.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            parts_list = []
            for cand in result.get("candidates", []) or []:
                content = cand.get("content") or {}
                for part in content.get("parts", []) or []:
                    text = part.get("text")
                    if text:
                        parts_list.append(text)
            raw = "".join(parts_list).strip()

        if not raw:
            return {"entry_number": "", "name": ""}

        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```[a-zA-Z]*\s*", "", raw).replace("```", "").strip()
        info = json.loads(raw)
        return {
            "entry_number": str(info.get("entry_number", "")).strip(),
            "name": str(info.get("name", "")).strip(),
        }
    except Exception as e:
        print(f"  ⚠️ Could not extract student info from image: {e}")
        return {"entry_number": "", "name": ""}


def _compile_c(source_path: Path, binary_path: Path, timeout_s: int = 20):
    """Compile C source code using gcc (compile-only, no linking — LeetCode has no main)."""
    proc = subprocess.run(
        ["gcc", "-c", str(source_path), "-O2", "-std=c11", "-Wall", "-Wextra",
         "-o", str(binary_path)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    ok = proc.returncode == 0
    return ok, proc.stdout, proc.stderr


def _process_single_image(
    image_path: Path,
    problems: Dict[str, Dict[str, Any]],
    work_dir: Path,
    api_key: str,
) -> Dict[str, Any]:
    """Process a single student image through the full code eval pipeline."""
    filename = image_path.name

    # Step 0: Extract student info — try OCR first, fall back to filename
    student_info = _extract_student_info_from_image(image_path, api_key)
    if not student_info.get("entry_number"):
        fallback = _extract_student_info_from_filename(filename)
        if not student_info.get("entry_number"):
            student_info["entry_number"] = fallback["entry_number"]
        if not student_info.get("name"):
            student_info["name"] = fallback["name"]
    print(f"  👤 Student: {student_info['entry_number']} — {student_info['name']}")

    student_dir = work_dir / student_info["entry_number"]
    student_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: OCR — extract C/C++ code from image
    try:
        code = extract_c_code_from_image(
            image_path,
            api_key=api_key,
        )
    except Exception as e:
        print(f"  ❌ Code OCR failed: {e}")
        return {
            **student_info,
            "total_score": 0, "max_score": 0,
            "correct_count": 0, "incorrect_count": 0, "unattempted_count": 0,
            "negative_deduction": 0,
            "details": [],
            "comments": f"OCR failed: {e}",
        }

    print(f"  📝 Code OCR extracted {len(code)} chars")

    # Step 1b: Strip student info header lines from OCR output
    # OCR may pick up "Name: ...", "Entry Number: ...", etc. from the image header
    cleaned_lines = []
    for line in code.split("\n"):
        stripped = line.strip()
        # Skip lines that look like student info headers (not valid C)
        if re.match(r"^(Name|Entry\s*Number|Roll\s*No|Roll\s*Number|Student|Reg\.?\s*No)\s*[:=]", stripped, re.IGNORECASE):
            print(f"  🧹 Stripped header line: {stripped[:60]}")
            continue
        cleaned_lines.append(line)
    code = "\n".join(cleaned_lines)

    if not code or len(code.strip()) < 10:
        print(f"  ❌ Code too short or empty")
        return {
            **student_info,
            "total_score": 0, "max_score": 0,
            "correct_count": 0, "incorrect_count": 0, "unattempted_count": 0,
            "negative_deduction": 0,
            "details": [],
            "comments": "OCR produced no usable code.",
        }

    # Step 2: Inject C standard headers if missing
    if "#include" not in code:
        code = "#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <stdbool.h>\n\n" + code
        print(f"  📦 Injected C headers")

    # Step 3: Compile as C and fix (up to 2 repair attempts)
    source_path = student_dir / "student_code.c"
    binary_path = student_dir / "student_code.o"
    source_path.write_text(code, encoding="utf-8")

    compile_ok, _, compile_stderr = _compile_c(source_path, binary_path)
    print(f"  🔨 Compile: {'✅ OK' if compile_ok else '❌ FAIL'}")
    if not compile_ok:
        print(f"  🔨 Error: {compile_stderr[:300]}")
    fix_attempts = 0

    while not compile_ok and fix_attempts < 2:
        fix_attempts += 1
        print(f"  🔧 Fix attempt {fix_attempts}...")
        try:
            fixed_code = fix_ocr_syntax_errors(
                code, compile_stderr, api_key=api_key,
            )
            is_valid, _reason = validate_trivial_fix(code, fixed_code)
            if is_valid and fixed_code.strip() != code.strip():
                code = fixed_code
                source_path.write_text(code, encoding="utf-8")
                compile_ok, _, compile_stderr = _compile_c(source_path, binary_path)
                print(f"  🔧 After fix: {'✅ OK' if compile_ok else '❌ FAIL'}")
            else:
                print(f"  🔧 Fix rejected (valid={is_valid})")
                break
        except Exception as fix_e:
            print(f"  🔧 Fix error: {fix_e}")
            break

    # Step 4: For each problem, run LeetCode test cases
    total_score = 0.0
    max_score = 0.0
    correct_count = 0
    incorrect_count = 0
    unattempted_count = 0
    details: List[Dict[str, Any]] = []
    problem_notes: List[str] = []

    for q_num, problem_def in problems.items():
        slug = problem_def.get("slug", "")
        marks = float(problem_def.get("marks", 1))
        max_score += marks
        print(f"  🧩 Q{q_num}: slug='{slug}', marks={marks}")

        if not compile_ok:
            details.append({
                "question_number": int(q_num),
                "marked": "COMPILE_ERROR",
                "correct": slug,
                "result": "incorrect",
                "score": 0,
                "test_cases_passed": 0,
                "test_cases_total": 0,
            })
            incorrect_count += 1
            problem_notes.append(f"Q{q_num}: compile error")
            print(f"  🧩 Q{q_num}: skipped — compile error")
            continue

        # Resolve test cases from LeetCode
        try:
            print(f"  🌐 Fetching LeetCode test cases for '{slug}'...")
            leet_problem, leet_cases, fetch_notes = resolve_leetcode_problem_and_cases(
                slug=slug,
                question_id=None,
                cases_file=None,
                max_cases=20,
                timeout_s=15,
            )
            print(f"  🌐 Got {len(leet_cases)} test cases for '{slug}'")
        except (SystemExit, Exception) as e:
            print(f"  ❌ LeetCode fetch failed: {e}")
            details.append({
                "question_number": int(q_num),
                "marked": f"NO_TESTS ({e})",
                "correct": slug,
                "result": "incorrect",
                "score": 0,
                "test_cases_passed": 0,
                "test_cases_total": 0,
            })
            incorrect_count += 1
            problem_notes.append(f"Q{q_num}: could not fetch test cases")
            continue

        if not leet_cases:
            print(f"  ❌ No test cases found for '{slug}'")
            details.append({
                "question_number": int(q_num),
                "marked": "NO_TESTS",
                "correct": slug,
                "result": "incorrect",
                "score": 0,
                "test_cases_passed": 0,
                "test_cases_total": 0,
            })
            incorrect_count += 1
            continue

        # Run evaluation
        try:
            print(f"  ▶ Running evaluation: {len(leet_cases)} test cases...")
            eval_result = evaluate_leetcode_cases(
                code=code,
                out_dir=student_dir,
                base=student_info["entry_number"],
                stamp=q_num,
                cases=leet_cases,
                problem=leet_problem,
                function_name_override=None,
                run_timeout_s=10,
                compile_timeout_s=20,
            )
            print(f"  ▶ Eval result: {eval_result}")
        except Exception as e:
            print(f"  ❌ Evaluation error: {e}")
            details.append({
                "question_number": int(q_num),
                "marked": f"EVAL_ERROR ({e})",
                "correct": slug,
                "result": "incorrect",
                "score": 0,
                "test_cases_passed": 0,
                "test_cases_total": 0,
            })
            incorrect_count += 1
            problem_notes.append(f"Q{q_num}: evaluation error — {e}")
            continue

        tc_passed = eval_result.get("testcase_passed", 0)
        tc_total = eval_result.get("testcase_total", 0)
        all_passed = tc_passed == tc_total and tc_total > 0

        q_score = marks if all_passed else 0
        total_score += q_score
        print(f"  📊 Q{q_num}: {tc_passed}/{tc_total} passed → score={q_score}/{marks}")

        if all_passed:
            correct_count += 1
        else:
            incorrect_count += 1

        details.append({
            "question_number": int(q_num),
            "marked": f"{tc_passed}/{tc_total} passed",
            "correct": slug,
            "result": "correct" if all_passed else "incorrect",
            "score": q_score,
            "test_cases_passed": tc_passed,
            "test_cases_total": tc_total,
        })
        problem_notes.append(f"Q{q_num}: {tc_passed}/{tc_total} passed")

    print(f"  🏁 Final: {total_score}/{max_score}, correct={correct_count}, incorrect={incorrect_count}")
    return {
        **student_info,
        "total_score": total_score,
        "max_score": max_score,
        "correct_count": correct_count,
        "incorrect_count": incorrect_count,
        "unattempted_count": unattempted_count,
        "negative_deduction": 0,
        "details": details,
        "comments": "; ".join(problem_notes) if problem_notes else "",
    }


# ── Endpoints ──

@router.post("/process-zip", response_model=CodeEvalResult)
async def process_zip_code_eval(
    file: UploadFile = File(...),
    answer_key: str = Form(""),
):
    """Process a ZIP of student answer-sheet images through the code evaluation pipeline."""
    try:
        key_data = json.loads(answer_key) if answer_key else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid answer_key JSON")

    problems = key_data.get("problems", {})
    if not problems:
        raise HTTPException(400, "answer_key must contain a 'problems' dict")

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "upload.zip"
        data = await file.read()
        zip_path.write_bytes(data)

        extract_dir = Path(tmpdir) / "images"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
        image_files = sorted([
            p for p in extract_dir.rglob("*")
            if p.suffix.lower() in image_exts and not p.name.startswith(".")
        ])

        if not image_files:
            raise HTTPException(400, "No image files found in ZIP")

        work_dir = Path(tmpdir) / "work"
        work_dir.mkdir()

        results = []
        errors = []
        for idx, img in enumerate(image_files, 1):
            print(f"\n📄 Code eval [{idx}/{len(image_files)}]: {img.name}")
            try:
                result = await asyncio.to_thread(
                    _process_single_image, img, problems, work_dir, api_key
                )
                results.append(result)
            except Exception as e:
                errors.append(f"{img.name}: {e}")

    return CodeEvalResult(
        total_students_processed=len(results),
        results=results,
        errors=errors,
    )


@router.post("/process-drive-folder", response_model=CodeEvalResult)
async def process_drive_code_eval(request: DriveCodeEvalRequest):
    """Process student images from a Google Drive folder through the code eval pipeline."""
    problems = request.answer_key.get("problems", {})
    if not problems:
        raise HTTPException(400, "answer_key must contain a 'problems' dict")

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""

    # List files in the Drive folder. DriveService does not expose a generic
    # `list_files(url)` — resolve the folder id first, then list all files.
    try:
        folder_id = DriveService.extract_folder_id(request.folder_url)
        files_list = drive_service.list_all_files_in_folder(folder_id)
    except Exception as e:
        raise HTTPException(400, f"Could not list Drive folder: {e}")

    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
    image_files = [
        f for f in files_list
        if any(f.get("name", "").lower().endswith(ext) for ext in image_exts)
    ]

    if not image_files:
        raise HTTPException(400, "No image files found in Drive folder")

    with tempfile.TemporaryDirectory() as tmpdir:
        download_dir = Path(tmpdir) / "images"
        download_dir.mkdir()
        work_dir = Path(tmpdir) / "work"
        work_dir.mkdir()

        results = []
        errors = []
        for idx, file_info in enumerate(image_files, 1):
            fname = file_info.get("name", f"image_{idx}.jpg")
            fid = file_info.get("id", "")
            print(f"\n📄 Code eval [{idx}/{len(image_files)}]: {fname}")

            # Download the image
            local_path = download_dir / fname
            try:
                drive_service.download_file(fid, str(local_path))
            except Exception as e:
                errors.append(f"{fname}: download failed — {e}")
                continue

            try:
                result = await asyncio.to_thread(
                    _process_single_image, local_path, problems, work_dir, api_key
                )
                results.append(result)
            except Exception as e:
                errors.append(f"{fname}: {e}")

    return CodeEvalResult(
        total_students_processed=len(results),
        results=results,
        errors=errors,
    )
