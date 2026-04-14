"""
Code Evaluation Endpoints
=========================
Routes for the LeetCode-style code evaluation pipeline.
Reuses OCR → compile-fix → LeetCode test case evaluation from c_code_evaluator.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path
import asyncio
import json
import os
import re
import shutil
import tempfile
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "c_code_evaluator"))

# ── Ensure Vertex AI credentials are available BEFORE importing c_code_evaluator ──
# (evaluate_c_from_image reads GOOGLE_CLOUD_PROJECT at import time)
_vertex_key_path = str(Path(__file__).resolve().parent.parent / "vertex_key.json")
if os.path.exists(_vertex_key_path):
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", _vertex_key_path)
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
import subprocess
from leetcode_mode import (
    resolve_leetcode_problem_and_cases,
    evaluate_leetcode_cases,
)
from services.drive_service import DriveService

router = APIRouter(prefix="/api/code-eval", tags=["code-evaluation"])
drive_service = DriveService()

# ── Request / Response models ──

class CodeEvalRequest(BaseModel):
    folder_url: Optional[str] = None
    answer_key: Dict[str, Any]  # {"problems": {"1": {"slug": "two-sum", "marks": 2}, ...}}
    evaluation_id: Optional[str] = None


class CodeEvalResult(BaseModel):
    entry_number: str
    name: str
    total_score: float
    max_score: float
    correct_count: int
    incorrect_count: int
    unattempted_count: int
    negative_deduction: float = 0.0
    details: List[Dict[str, Any]] = []
    comments: str = ""


# ── Helpers ──

def _get_api_key() -> str:
    for env_var in ("GOOGLE_API_KEY", "VERTEX_AI_API_KEY", "GEMINI_API_KEY"):
        key = os.getenv(env_var)
        if key:
            return key
    return ""


def _extract_student_info_from_filename(filename: str) -> Dict[str, str]:
    """Try to parse enrollment number and name from filename."""
    stem = Path(filename).stem
    # Common patterns:  "2023CSB1064_John_Doe.jpg" or "2023CSB1064.jpg"
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

        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and project_id:
            raw = _vertex_stream_generate_content(
                project_id=project_id,
                location=location,
                model=model,
                payload=payload,
                timeout_s=30,
            )
        elif api_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            resp = __import__("requests").post(url, json=payload, timeout=30)
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
        else:
            return {"entry_number": "", "name": ""}

        # Parse JSON from response
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


def _compile_cpp(source_path: Path, binary_path: Path, timeout_s: int = 20):
    """Compile C++ source code using g++."""
    # Use -c to compile only (do not link), because LeetCode solutions don't have a main() function.
    proc = subprocess.run(
        ["g++", "-c", str(source_path), "-O2", "-std=c++17", "-Wall", "-Wextra", "-o", str(binary_path)],
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
        return {
            **student_info,
            "total_score": 0, "max_score": 0,
            "correct_count": 0, "incorrect_count": 0, "unattempted_count": 0,
            "details": [],
            "comments": f"OCR failed: {e}",
        }

    if not code or len(code.strip()) < 10:
        return {
            **student_info,
            "total_score": 0, "max_score": 0,
            "correct_count": 0, "incorrect_count": 0, "unattempted_count": 0,
            "details": [],
            "comments": "OCR produced no usable code.",
        }

    # Step 2: Compile as C++ (LeetCode style) and fix (up to 2 repair attempts)
    # LeetCode solutions typically don't include headers, so inject common ones
    if "#include" not in code:
        leetcode_headers = (
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n\n"
        )
        code = leetcode_headers + code

    source_path = student_dir / "student_code.cpp"
    binary_path = student_dir / "student_code.out"
    source_path.write_text(code, encoding="utf-8")

    compile_ok, _, compile_stderr = _compile_cpp(source_path, binary_path)
    fix_attempts = 0

    while not compile_ok and fix_attempts < 2:
        fix_attempts += 1
        try:
            fixed_code = fix_ocr_syntax_errors(
                code, compile_stderr, api_key=api_key,
            )
            is_valid, _reason = validate_trivial_fix(code, fixed_code)
            if is_valid and fixed_code.strip() != code.strip():
                code = fixed_code
                source_path.write_text(code, encoding="utf-8")
                compile_ok, _, compile_stderr = _compile_cpp(source_path, binary_path)
            else:
                break
        except Exception:
            break

    # Step 3: For each problem, run LeetCode test cases
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
            continue

        # Resolve test cases from LeetCode
        try:
            leet_problem, leet_cases, fetch_notes = resolve_leetcode_problem_and_cases(
                slug=slug,
                question_id=None,
                cases_file=None,
                max_cases=20,
                timeout_s=15,
            )
        except SystemExit as e:
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
            eval_result = evaluate_leetcode_cases(
                code=code,
                out_dir=student_dir / f"q{q_num}",
                base=f"q{q_num}",
                stamp="eval",
                cases=leet_cases,
                problem=leet_problem,
                function_name_override=None,
                run_timeout_s=5,
                compile_timeout_s=20,
            )

            passed = eval_result.get("testcase_passed", 0)
            total = eval_result.get("testcase_total", 0)
            all_passed = (passed == total) and total > 0

            q_score = marks if all_passed else 0
            total_score += q_score

            if all_passed:
                correct_count += 1
            else:
                incorrect_count += 1

            details.append({
                "question_number": int(q_num),
                "marked": f"{passed}/{total}",
                "correct": slug,
                "result": "correct" if all_passed else "incorrect",
                "score": q_score,
                "test_cases_passed": passed,
                "test_cases_total": total,
            })
        except Exception as e:
            details.append({
                "question_number": int(q_num),
                "marked": f"ERROR ({str(e)[:50]})",
                "correct": slug,
                "result": "incorrect",
                "score": 0,
                "test_cases_passed": 0,
                "test_cases_total": 0,
            })
            incorrect_count += 1

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

@router.post("/process-zip")
async def process_zip_code_eval(
    file: UploadFile = File(...),
    answer_key_json: str = "",
):
    """
    Process a ZIP of student code images through the LeetCode evaluation pipeline.
    answer_key_json should be a JSON string with the problems definition.
    """
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    try:
        answer_key = json.loads(answer_key_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="answer_key_json must be valid JSON")

    problems = answer_key.get("problems", {})
    if not problems:
        raise HTTPException(status_code=400, detail="answer_key must contain 'problems'")

    api_key = _get_api_key()
    temp_dir = tempfile.mkdtemp(prefix="code_eval_zip_")

    try:
        # Save uploaded file
        zip_path = os.path.join(temp_dir, file.filename)
        content = await file.read()
        with open(zip_path, "wb") as f:
            f.write(content)

        # Extract
        extract_dir = os.path.join(temp_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # Find image files
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        image_files = []
        for root, _dirs, files in os.walk(extract_dir):
            for fname in sorted(files):
                if Path(fname).suffix.lower() in image_exts and not fname.startswith('.'):
                    image_files.append(Path(root) / fname)

        if not image_files:
            raise HTTPException(status_code=400, detail="No image files found in ZIP")

        work_dir = Path(temp_dir) / "work"
        work_dir.mkdir()

        # Process each image
        results = []
        errors = []
        for idx, img_path in enumerate(image_files):
            print(f"\n📄 Code eval [{idx+1}/{len(image_files)}]: {img_path.name}")
            try:
                result = await asyncio.to_thread(
                    _process_single_image, img_path, problems, work_dir, api_key
                )
                results.append(result)
                print(f"  ✅ {result['entry_number']}: {result['total_score']}/{result['max_score']}")
            except Exception as e:
                errors.append({"file": img_path.name, "error": str(e)})
                print(f"  ❌ Error: {e}")

        return {
            "total_students_processed": len(results),
            "results": results,
            "errors": errors,
        }

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/process-drive-folder")
async def process_drive_code_eval(request: CodeEvalRequest):
    """
    Process a Drive folder of student code images through the LeetCode evaluation pipeline.
    """
    if not request.folder_url:
        raise HTTPException(status_code=400, detail="folder_url is required")

    problems = request.answer_key.get("problems", {})
    if not problems:
        raise HTTPException(status_code=400, detail="answer_key must contain 'problems'")

    api_key = _get_api_key()
    folder_id = DriveService.extract_folder_id(request.folder_url)
    all_files = drive_service.list_all_files_in_folder(folder_id)

    if not all_files:
        raise HTTPException(status_code=404, detail="No files found in Drive folder")

    # Filter to image files only (skip answer_key files)
    image_mimes = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
    student_files = [
        f for f in all_files
        if f.get("mimeType", "") in image_mimes
        and "answer_key" not in f.get("name", "").lower()
    ]

    if not student_files:
        raise HTTPException(status_code=404, detail="No student image files found in folder")

    temp_dir = tempfile.mkdtemp(prefix="code_eval_drive_")

    try:
        # Download all files
        async def _download(f):
            local_path = os.path.join(temp_dir, f["name"])
            ok = await asyncio.to_thread(drive_service.download_file, f["id"], local_path)
            return Path(local_path), f, ok

        download_results = await asyncio.gather(*[_download(f) for f in student_files])
        successful = [(lp, sf) for lp, sf, ok in download_results if ok]

        if not successful:
            raise HTTPException(status_code=500, detail="All downloads failed")

        work_dir = Path(temp_dir) / "work"
        work_dir.mkdir()

        results = []
        errors = []
        for idx, (local_path, sf) in enumerate(successful):
            print(f"\n📄 Code eval [{idx+1}/{len(successful)}]: {sf['name']}")
            try:
                result = await asyncio.to_thread(
                    _process_single_image, local_path, problems, work_dir, api_key
                )
                results.append(result)
                print(f"  ✅ {result['entry_number']}: {result['total_score']}/{result['max_score']}")
            except Exception as e:
                errors.append({"file": sf["name"], "error": str(e)})
                print(f"  ❌ Error: {e}")

        return {
            "total_students_processed": len(results),
            "results": results,
            "errors": errors,
        }

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
