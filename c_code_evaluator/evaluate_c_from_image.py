#!/usr/bin/env python3
"""
C-code evaluator pipeline with OCR error recovery:
1) OCR (Gemini) to extract C code from an image
2) Compile with gcc
3) If compile succeeds: run with stdin/expected or CP-style testcases
4) If compile fails: agent fixes trivial OCR-induced syntax errors, retry (max 2 attempts)
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import requests

try:
    from leetcode_mode import (
        LeetCase,
        LeetProblemSpec,
        evaluate_leetcode_cases,
        resolve_leetcode_problem_and_cases,
    )
except ModuleNotFoundError:
    from c_code_evaluator.leetcode_mode import (
        LeetCase,
        LeetProblemSpec,
        evaluate_leetcode_cases,
        resolve_leetcode_problem_and_cases,
    )


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
    if not resp.ok:
        raise SystemExit(f"Gemini API error {resp.status_code}: {resp.text[:2000]}")
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
    if not resp.ok:
        raise SystemExit(f"Vertex API error {resp.status_code}: {resp.text[:2000]}")
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


def _gemini_generate_content(api_key: str, model: str, payload: dict, timeout_s: int) -> str:
    """Non-streaming Gemini call for text-only requests (e.g. fix agent)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    result = resp.json()
    parts: list[str] = []
    for cand in result.get("candidates", []) or []:
        content = cand.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                parts.append(text)
    return "".join(parts).strip()


def _vertex_generate_content(
    project_id: str, location: str, model: str, payload: dict, timeout_s: int
) -> str:
    """Non-streaming Vertex call for text-only requests."""
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
    except Exception as e:
        raise SystemExit(
            "Vertex auth requested but google-auth is not available. pip install google-auth"
        ) from e

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise SystemExit("GOOGLE_APPLICATION_CREDENTIALS is set but file is missing.")

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/publishers/google/models/{model}:generateContent"
    )
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    result = resp.json()
    parts: list[str] = []
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


@dataclass
class TestCase:
    input_text: str
    expected_output: str


OCR_LIKE_ERROR_PATTERNS = [
    r"expected\s+['\"].*;.*['\"]",
    r"expected\s+['\"].*[\)\}\]].*['\"]",
    r"undeclared\s+identifier",
    r"use of undeclared identifier",
    r"implicit declaration of function",
    r"too few arguments to function",
    r"too many arguments to function",
    r"expected expression",
    r"expected identifier",
    r"stray .+ in program",
    r"missing terminating ['\"] character",
    r"unknown type name",
    r"use of undeclared identifier",
    r"invalid preprocessing directive",
]


ALLOWED_INCLUDE_HEADERS = {"stdio.h", "stdlib.h", "string.h", "math.h", "stddef.h"}
HEADER_ORDER = ["stdio.h", "stdlib.h", "string.h", "math.h", "stddef.h"]
HEADER_NEEDS = [
    (r"\b(?:printf|scanf|putchar|getchar|fgets|puts)\b", "stdio.h"),
    (r"\b(?:malloc|calloc|realloc|free|exit|qsort|bsearch|atoi|atol|atoll|strtol|strtoll)\b", "stdlib.h"),
    (r"\b(?:strlen|strcmp|strncmp|strcpy|strncpy|memset|memcpy|memmove)\b", "string.h"),
    (r"\b(?:sqrt|pow|fabs|sin|cos|tan|floor|ceil|log|exp)\b", "math.h"),
    (r"\bsize_t\b", "stddef.h"),
]

UNICODE_CHAR_NORMALIZATION = {
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "’": "'",
    "‘": "'",
    "‚": "'",
    "‛": "'",
    "−": "-",
    "–": "-",
    "—": "-",
    "…": "...",
    "×": "*",
    "÷": "/",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "｜": "|",
    "¦": "|",
    "＆": "&",
    "；": ";",
    "：": ":",
    "，": ",",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "｛": "{",
    "｝": "}",
    "＜": "<",
    "＞": ">",
    "＝": "=",
    "！": "!",
    "％": "%",
    "＼": "\\",
}


def _looks_like_ocr_fixable_compile_error(stderr: str) -> bool:
    low = (stderr or "").lower()
    return any(re.search(p, low) for p in OCR_LIKE_ERROR_PATTERNS)


def _tokenize_c_for_guardrails(code: str) -> List[str]:
    return re.findall(r"[A-Za-z_]\w*|\d+|==|!=|<=|>=|&&|\|\||[{}\[\]();,=+\-*/%<>!&|^~?:]", code)


def _strip_preprocessor_lines(code: str) -> str:
    """
    Remove preprocessor directive lines before structural comparisons.
    This prevents harmless include/header edits from being treated as
    operator-level logic changes.
    """
    kept = []
    for line in code.splitlines():
        if re.match(r"^\s*#", line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _extract_identifiers(code: str) -> List[str]:
    return re.findall(r"\b[A-Za-z_]\w*\b", code)


def _edit_distance_leq1(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = j = edits = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(a) > len(b):
            i += 1
        elif len(b) > len(a):
            j += 1
        else:
            i += 1
            j += 1
    if i < len(a) or j < len(b):
        edits += 1
    return edits <= 1


def _includes_from_code(code: str) -> set[str]:
    return {
        m.group(1)
        for m in re.finditer(r"^\s*#\s*include\s*<([^>]+)>\s*$", code, flags=re.MULTILINE)
    }


def _normalize_ocr_special_characters(code: str) -> str:
    normalized = code
    for src, dst in UNICODE_CHAR_NORMALIZATION.items():
        normalized = normalized.replace(src, dst)

    # Heuristic: OCR sometimes turns an escaped newline (`\\n`) inside a string literal
    # into a real newline, producing:
    #   printf("%lld
    #   ", x);
    # Join these back by injecting a literal `\\n`.
    lines = normalized.splitlines()
    repaired_lines: list[str] = []

    def _unescaped_quote_count(s: str) -> int:
        cnt = 0
        esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                cnt += 1
        return cnt

    i = 0
    while i < len(lines):
        line = lines[i]
        if i + 1 < len(lines) and (_unescaped_quote_count(line) % 2 == 1):
            nxt = lines[i + 1]
            if re.match(r'^\s*"', nxt):
                repaired_lines.append(line + r"\n" + nxt.lstrip())
                i += 2
                continue
        repaired_lines.append(line)
        i += 1

    normalized = "\n".join(repaired_lines)

    # Collapse accidental repeated percent signs that break format strings.
    normalized = re.sub(r"%\s+([ldfcsuxX])", r"%\1", normalized)
    return normalized


def _required_headers_for_code(code: str) -> set[str]:
    needed: set[str] = set()
    for pattern, header in HEADER_NEEDS:
        if re.search(pattern, code):
            needed.add(header)
    return needed


def _insert_missing_includes(code: str, missing_headers: List[str]) -> str:
    if not missing_headers:
        return code

    include_lines = [f"#include <{h}>" for h in missing_headers]
    lines = code.splitlines()

    insert_at = 0
    for i, line in enumerate(lines):
        if re.match(r"^\s*#\s*include\b", line):
            insert_at = i + 1
            continue
        if line.strip() == "":
            if insert_at == 0:
                continue
            break
        if line.lstrip().startswith("#"):
            if insert_at == 0:
                insert_at = i + 1
            continue
        break

    out_lines = lines[:insert_at] + include_lines + lines[insert_at:]
    return "\n".join(out_lines)


def _apply_deterministic_ocr_repairs(code: str) -> str:
    repaired = _normalize_ocr_special_characters(code)
    existing = _includes_from_code(repaired)
    needed = _required_headers_for_code(repaired)
    missing = [h for h in HEADER_ORDER if h in needed and h not in existing]
    repaired = _insert_missing_includes(repaired, missing)
    return repaired


def validate_trivial_fix(original: str, fixed: str) -> Tuple[bool, str]:
    if fixed.strip() == original.strip():
        return False, "no_change"

    orig_lines = original.splitlines()
    fixed_lines = fixed.splitlines()

    sm = difflib.SequenceMatcher(None, orig_lines, fixed_lines)
    changed_line_count = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changed_line_count += max(i2 - i1, j2 - j1)
    if changed_line_count > 20:
        return False, f"too_many_line_edits:{changed_line_count}"

    dangerous_keywords = {"for", "while", "switch", "goto", "do"}
    orig_kw_count = {k: len(re.findall(rf"\b{k}\b", original)) for k in dangerous_keywords}
    fix_kw_count = {k: len(re.findall(rf"\b{k}\b", fixed)) for k in dangerous_keywords}
    for k in dangerous_keywords:
        if fix_kw_count[k] != orig_kw_count[k]:
            return False, f"control_flow_changed:{k}"

    orig_includes = _includes_from_code(original)
    fix_includes = _includes_from_code(fixed)
    added_includes = fix_includes - orig_includes
    if any(h not in ALLOWED_INCLUDE_HEADERS for h in added_includes):
        return False, "disallowed_include_added"

    # Ignore preprocessor-only edits (e.g. adding missing headers) when
    # checking operator sequence, since they don't alter runtime logic.
    orig_logic = _strip_preprocessor_lines(original)
    fix_logic = _strip_preprocessor_lines(fixed)

    orig_tokens = _tokenize_c_for_guardrails(orig_logic)
    fix_tokens = _tokenize_c_for_guardrails(fix_logic)

    op_tokens = {"+", "-", "*", "/", "%", "==", "!=", "<=", ">=", "<", ">", "&&", "||"}
    orig_ops = [t for t in orig_tokens if t in op_tokens]
    fix_ops = [t for t in fix_tokens if t in op_tokens]
    if orig_ops != fix_ops:
        sm_ops = difflib.SequenceMatcher(None, orig_ops, fix_ops)
        operator_edits = 0
        for tag, i1, i2, j1, j2 in sm_ops.get_opcodes():
            if tag != "equal":
                operator_edits += max(i2 - i1, j2 - j1)
        if operator_edits > 2:
            return False, f"operator_sequence_changed:{operator_edits}"

    orig_ids = [x for x in _extract_identifiers(original) if x not in {"include"}]
    fix_ids = [x for x in _extract_identifiers(fixed) if x not in {"include"}]
    if len(orig_ids) == len(fix_ids):
        rename_violations = 0
        for a, b in zip(orig_ids, fix_ids):
            if a != b and not _edit_distance_leq1(a, b):
                rename_violations += 1
        if rename_violations > 8:
            return False, f"identifier_changes_too_large:{rename_violations}"

    return True, "accepted"


def normalize_output(text: str) -> str:
    """Normalize stdout for comparison: collapse whitespace, strip."""
    if not text:
        return ""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return "\n".join(lines)


def outputs_match(actual: str, expected: str) -> bool:
    """Compare program output to expected (whitespace-normalized)."""
    return normalize_output(actual) == normalize_output(expected)


def parse_testcases_file(testcases_path: Path) -> List[TestCase]:
    """
    Parse CP-style testcases from file.

    Supported formats:
    1) JSON:
       [
         {"input": "...", "output": "..."},
         {"input": "...", "output": "..."}
       ]
       or {"testcases": [ ... ]}

    2) Text blocks:
       INPUT:
       ...
       OUTPUT:
       ...
       INPUT:
       ...
       OUTPUT:
       ...
    """
    if not testcases_path.exists():
        raise SystemExit(f"Testcases file not found: {testcases_path}")

    raw = testcases_path.read_text(encoding="utf-8")

    # JSON mode
    if testcases_path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise SystemExit(f"Invalid JSON in testcases file: {e}") from e

        if isinstance(data, dict):
            data = data.get("testcases", [])
        if not isinstance(data, list):
            raise SystemExit("Testcases JSON must be a list or {\"testcases\": [...]} object.")

        cases: List[TestCase] = []
        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                raise SystemExit(f"Testcase #{i} is not an object.")
            if "input" not in item or "output" not in item:
                raise SystemExit(f"Testcase #{i} must contain 'input' and 'output' keys.")
            cases.append(
                TestCase(
                    input_text=str(item.get("input", "")),
                    expected_output=str(item.get("output", "")),
                )
            )
        if not cases:
            raise SystemExit("No testcases found in JSON file.")
        return cases

    # Text mode
    pattern = re.compile(
        r"^\s*INPUT\s*:\s*\n?(.*?)^\s*OUTPUT\s*:\s*\n?(.*?)(?=^\s*INPUT\s*:|\Z)",
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    matches = list(pattern.finditer(raw))
    if not matches:
        raise SystemExit(
            "No testcases parsed. For text format, use repeated INPUT:/OUTPUT: blocks."
        )

    cases = []
    for m in matches:
        inp = m.group(1)
        out = m.group(2)
        if inp.startswith("\n"):
            inp = inp[1:]
        if out.startswith("\n"):
            out = out[1:]
        cases.append(TestCase(input_text=inp, expected_output=out))

    return cases


def fix_ocr_syntax_errors(
    code: str,
    compile_stderr: str,
    *,
    api_key: Optional[str],
    model: str = DEFAULT_MODEL,
    timeout_s: int = 30,
    vertex_project_id: Optional[str] = None,
    vertex_location: str = DEFAULT_VERTEX_LOCATION,
) -> str:
    """
    Ask an LLM to fix ONLY trivial OCR-induced syntax errors.
    Returns corrected C code (or original if no fix suggested).
    """
    prompt = (
        "You are fixing ONLY trivial OCR-induced syntax errors in C code. "
        "The code failed to compile. Do NOT change logic, algorithms, or control flow. "
        "Do NOT add/remove statements or refactor.\n\n"
        "ONLY fix:\n"
        "- Missing or extra semicolons\n"
        "- Mismatched brackets/parentheses { } [ ] ( )\n"
        "- Common OCR confusions: 0/O, 1/l/I, ;/:, {/[ etc.\n"
        "- Misread variable/function names when the error points to that identifier "
        "(e.g. nurnber→number, marn→main, print f→printf)\n"
        "- Missing #include if the error says 'implicit declaration'\n\n"
        "Return ONLY the corrected C code. No explanations. No markdown fences.\n\n"
        "=== C code ===\n"
        f"{code}\n\n"
        "=== GCC error ===\n"
        f"{compile_stderr}\n"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 4096},
    }

    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        project_id = vertex_project_id or DEFAULT_VERTEX_PROJECT
        if not project_id:
            raise SystemExit("Vertex: project id missing. Set GOOGLE_CLOUD_PROJECT.")
        raw = _vertex_generate_content(
            project_id=project_id,
            location=vertex_location,
            model=model,
            payload=payload,
            timeout_s=timeout_s,
        )
    else:
        if not api_key:
            raise SystemExit("Missing API key for fix agent.")
        raw = _gemini_generate_content(
            api_key=api_key, model=model, payload=payload, timeout_s=timeout_s
        )

    return _strip_markdown_fences(raw)


def fix_input_output_format_only(
    code: str,
    compile_stderr: str,
    *,
    api_key: Optional[str],
    model: str = DEFAULT_MODEL,
    timeout_s: int = 30,
    vertex_project_id: Optional[str] = None,
    vertex_location: str = DEFAULT_VERTEX_LOCATION,
) -> str:
    """
    First-pass targeted fixer:
    Fix only OCR corruption around input/output tokens and format strings.
    """
    prompt = (
        "Fix ONLY OCR errors in C input/output formatting.\n"
        "Do NOT change algorithm, loops, conditions, variable meanings, or data structures.\n\n"
        "Allowed edits:\n"
        "- scanf/printf/puts/putchar/getchar spelling mistakes\n"
        "- format string corruption (%lld, %d, %s, %c, \\n, quotes, commas)\n"
        "- misplaced punctuation around I/O statements: ; , ( ) [ ] { }\n"
        "- obvious OCR confusions in I/O lines only (0/O, 1/l/I, smart quotes, unicode symbols)\n\n"
        "Not allowed:\n"
        "- changing math/logic\n"
        "- adding/removing loops or branches\n"
        "- refactoring\n\n"
        "Return ONLY corrected C code without markdown.\n\n"
        "=== C code ===\n"
        f"{code}\n\n"
        "=== GCC error ===\n"
        f"{compile_stderr}\n"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 4096},
    }

    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        project_id = vertex_project_id or DEFAULT_VERTEX_PROJECT
        if not project_id:
            raise SystemExit("Vertex: project id missing. Set GOOGLE_CLOUD_PROJECT.")
        raw = _vertex_generate_content(
            project_id=project_id,
            location=vertex_location,
            model=model,
            payload=payload,
            timeout_s=timeout_s,
        )
    else:
        if not api_key:
            raise SystemExit("Missing API key for fix agent.")
        raw = _gemini_generate_content(
            api_key=api_key, model=model, payload=payload, timeout_s=timeout_s
        )

    return _strip_markdown_fences(raw)


def compile_c(source_path: Path, binary_path: Path, timeout_s: int = 20) -> Tuple[bool, str, str]:
    proc = subprocess.run(
        ["gcc", str(source_path), "-O2", "-std=c11", "-Wall", "-Wextra", "-o", str(binary_path)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    ok = proc.returncode == 0
    return ok, proc.stdout, proc.stderr


def compile_c_syntax_only(source_path: Path, timeout_s: int = 20) -> Tuple[bool, str, str]:
    proc = subprocess.run(
        ["gcc", "-c", str(source_path), "-O2", "-std=c11", "-Wall", "-Wextra", "-o", os.devnull],
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
        "--expected-file",
        default=None,
        help="File with expected stdout. If provided, output is compared and result is correct/incorrect.",
    )
    parser.add_argument(
        "--testcases-file",
        default=None,
        help="CP-style testcases file. Supports JSON or repeated INPUT:/OUTPUT: blocks.",
    )
    parser.add_argument(
        "--max-fix-attempts",
        type=int,
        default=3,
        help="Max agent fix attempts when compilation fails (default: 3)",
    )
    parser.add_argument(
        "--run-anyway",
        action="store_true",
        help="Run even if no --stdin-file is provided (may time out if program waits for input).",
    )
    parser.add_argument("--run-timeout-s", type=int, default=2, help="Program run timeout seconds")
    parser.add_argument("--ocr-timeout-s", type=int, default=60, help="OCR request timeout seconds")
    parser.add_argument("--fix-timeout-s", type=int, default=30, help="Fix agent request timeout seconds")
    parser.add_argument(
        "--mode",
        default="cp",
        choices=["cp", "leetcode"],
        help="Evaluation mode: cp (stdin/stdout) or leetcode (function-argument style).",
    )
    parser.add_argument("--leetcode-slug", default=None, help="LeetCode title slug (e.g. two-sum)")
    parser.add_argument("--leetcode-id", default=None, help="LeetCode problem id (e.g. 1)")
    parser.add_argument(
        "--leetcode-cases-file",
        default=None,
        help="Optional JSON with normalized LeetCode cases and optional meta.",
    )
    parser.add_argument(
        "--leetcode-function-name",
        default=None,
        help="Optional function name override inside OCR C code.",
    )
    parser.add_argument(
        "--leetcode-max-cases",
        type=int,
        default=20,
        help="Max LeetCode testcases to evaluate (default: 20).",
    )
    parser.add_argument(
        "--leetcode-fetch-timeout-s",
        type=int,
        default=30,
        help="Timeout seconds for LeetCode testcase fetching.",
    )
    args = parser.parse_args()

    if args.mode == "cp":
        if args.testcases_file and (args.stdin_file or args.expected_file):
            print(
                "Use either --testcases-file OR (--stdin-file/--expected-file), not both.",
                file=sys.stderr,
            )
            return 2
    else:
        if args.stdin_file or args.expected_file or args.testcases_file:
            print(
                "In --mode leetcode, do not use --stdin-file/--expected-file/--testcases-file.",
                file=sys.stderr,
            )
            return 2
        if not (args.leetcode_slug or args.leetcode_id or args.leetcode_cases_file):
            print(
                "In --mode leetcode, pass at least one of --leetcode-slug/--leetcode-id/--leetcode-cases-file.",
                file=sys.stderr,
            )
            return 2

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
    code = _apply_deterministic_ocr_repairs(code)

    code_txt_path.write_text(code + "\n", encoding="utf-8")

    stdin_text = None
    if args.mode == "cp" and args.stdin_file:
        stdin_text = Path(args.stdin_file).expanduser().read_text(encoding="utf-8")

    expected_stdout = None
    if args.mode == "cp" and args.expected_file:
        expected_stdout = Path(args.expected_file).expanduser().read_text(encoding="utf-8")

    testcases: Optional[List[TestCase]] = None
    if args.mode == "cp" and args.testcases_file:
        testcases = parse_testcases_file(Path(args.testcases_file).expanduser().resolve())

    leetcode_problem: Optional[LeetProblemSpec] = None
    leetcode_cases: Optional[List[LeetCase]] = None
    leetcode_fetch_notes: List[str] = []
    selected_leetcode_function: Optional[str] = None
    if args.mode == "leetcode":
        leetcode_problem, leetcode_cases, leetcode_fetch_notes = resolve_leetcode_problem_and_cases(
            slug=args.leetcode_slug,
            question_id=args.leetcode_id,
            cases_file=Path(args.leetcode_cases_file).expanduser().resolve() if args.leetcode_cases_file else None,
            max_cases=max(1, args.leetcode_max_cases),
            timeout_s=args.leetcode_fetch_timeout_s,
        )

    fix_history: List[str] = []
    fix_rejection_reasons: List[str] = []
    compile_ok = False
    c_out, c_err = "", ""
    fix_attempt = 0

    while True:
        code = _apply_deterministic_ocr_repairs(code)
        code_c_path.write_text(code + "\n", encoding="utf-8")
        if args.mode == "leetcode":
            compile_ok, c_out, c_err = compile_c_syntax_only(code_c_path)
        else:
            compile_ok, c_out, c_err = compile_c(code_c_path, binary_path)

        compile_log_path.write_text(
            f"mode={args.mode}\ncompile_ok={compile_ok}\nfix_attempt={fix_attempt}\n\n=== gcc stdout ===\n{c_out}\n\n=== gcc stderr ===\n{c_err}\n",
            encoding="utf-8",
        )

        if compile_ok:
            break

        if fix_attempt >= args.max_fix_attempts:
            break

        fix_attempt += 1
        print(f"Compilation failed. Fix attempt {fix_attempt}/{args.max_fix_attempts}...", file=sys.stderr)
        if fix_attempt == 1:
            fixed = fix_input_output_format_only(
                code=code,
                compile_stderr=c_err,
                api_key=api_key,
                model=args.model,
                timeout_s=args.fix_timeout_s,
                vertex_project_id=args.vertex_project_id,
                vertex_location=args.vertex_location,
            )
            fix_stage = "io_format_only"
        else:
            # Fallback to general OCR syntax repair for attempts 2..N.
            fixed = fix_ocr_syntax_errors(
                code=code,
                compile_stderr=c_err,
                api_key=api_key,
                model=args.model,
                timeout_s=args.fix_timeout_s,
                vertex_project_id=args.vertex_project_id,
                vertex_location=args.vertex_location,
            )
            fix_stage = "general_ocr_fix"
            if not _looks_like_ocr_fixable_compile_error(c_err):
                fix_rejection_reasons.append("non_ocr_like_error_but_fix_attempted")

        fixed = _apply_deterministic_ocr_repairs(fixed)
        accepted, reason = validate_trivial_fix(code, fixed)
        fix_history.append(
            f"--- Fix attempt {fix_attempt} ---\n"
            f"stage={fix_stage}\n"
            f"Original stderr:\n{c_err}\n\n"
            f"validation={accepted} reason={reason}\n\n"
            f"Fixed code:\n{fixed}\n"
        )
        if not accepted:
            fix_rejection_reasons.append(reason)
            break
        if fixed.strip() == code.strip():
            break
        code = fixed

    fix_history_path = out_dir / f"{base}_{stamp}_fix_history.txt"
    if fix_history:
        fix_history_path.write_text("\n".join(fix_history), encoding="utf-8")
        print(f"- Fix history: {fix_history_path}")

    did_run = False
    run_ok = False
    r_out, r_err = "", ""
    exit_code: Optional[int] = None
    timed_out = False
    testcase_results = []
    testcase_total = len(testcases) if testcases else (len(leetcode_cases) if leetcode_cases else 0)
    testcase_passed = 0

    missing_stdin_required = False
    if args.mode == "cp" and compile_ok and testcases is None and stdin_text is None and not args.run_anyway:
        missing_stdin_required = True

    testcase_mode = False
    if args.mode == "cp" and compile_ok and testcases:
        testcase_mode = True
        did_run = True
        run_ok = True
        lines = [f"did_run={did_run}", f"testcases_total={len(testcases)}", ""]

        for idx, tc in enumerate(testcases, start=1):
            case_run_ok, case_out, case_err, case_exit_code, case_timed_out = run_binary(
                binary_path=binary_path,
                stdin_text=tc.input_text,
                timeout_s=args.run_timeout_s,
            )
            case_matched = case_run_ok and (not case_timed_out) and outputs_match(case_out, tc.expected_output)
            status = (
                "PASSED"
                if case_matched
                else ("TIMEOUT" if case_timed_out else ("RUNTIME_ERROR" if not case_run_ok else "WRONG_OUTPUT"))
            )

            if not case_run_ok:
                run_ok = False
            if case_timed_out:
                timed_out = True
            if case_matched:
                testcase_passed += 1

            testcase_results.append(
                {
                    "index": idx,
                    "status": status,
                    "run_ok": case_run_ok,
                    "timed_out": case_timed_out,
                    "exit_code": case_exit_code,
                    "matched": case_matched,
                    "actual_normalized": normalize_output(case_out),
                    "expected_normalized": normalize_output(tc.expected_output),
                    "stderr": case_err,
                }
            )

            lines.append(
                f"=== testcase {idx} ===\n"
                f"status={status}\n"
                f"run_ok={case_run_ok}\n"
                f"exit_code={case_exit_code}\n"
                f"timed_out={case_timed_out}\n"
                f"matched={case_matched}\n\n"
                f"--- actual stdout ---\n{case_out}\n\n"
                f"--- expected stdout ---\n{tc.expected_output}\n\n"
                f"--- stderr ---\n{case_err}\n"
            )

        run_log_path.write_text("\n".join(lines), encoding="utf-8")
    elif args.mode == "leetcode":
        testcase_mode = True
        if compile_ok and leetcode_problem and leetcode_cases:
            leet_eval = evaluate_leetcode_cases(
                code=code,
                out_dir=out_dir,
                base=base,
                stamp=stamp,
                cases=leetcode_cases,
                problem=leetcode_problem,
                function_name_override=args.leetcode_function_name,
                run_timeout_s=args.run_timeout_s,
                compile_timeout_s=20,
            )
            did_run = bool(leet_eval.get("did_run"))
            run_ok = bool(leet_eval.get("run_ok"))
            timed_out = bool(leet_eval.get("timed_out"))
            testcase_total = int(leet_eval.get("testcase_total", 0))
            testcase_passed = int(leet_eval.get("testcase_passed", 0))
            testcase_results = list(leet_eval.get("testcase_results", []))
            selected_leetcode_function = leet_eval.get("selected_function")
            leetcode_fetch_notes.extend(list(leet_eval.get("notes", [])))
            run_log_path.write_text(str(leet_eval.get("run_log_text", "")), encoding="utf-8")
        else:
            run_log_path.write_text(
                f"did_run={did_run}\nrun_ok={run_ok}\nexit_code={exit_code}\ntimed_out={timed_out}\n",
                encoding="utf-8",
            )
    else:
        if compile_ok and (stdin_text is not None or args.run_anyway):
            did_run = True
            run_ok, r_out, r_err, exit_code, timed_out = run_binary(
                binary_path=binary_path,
                stdin_text=stdin_text,
                timeout_s=args.run_timeout_s,
            )

        run_log_path.write_text(
            f"did_run={did_run}\nrun_ok={run_ok}\nexit_code={exit_code}\ntimed_out={timed_out}\n\n"
            f"=== program stdout ===\n{r_out}\n\n=== program stderr ===\n{r_err}\n",
            encoding="utf-8",
        )

    correct = False
    if testcase_mode:
        correct = compile_ok and did_run and (testcase_passed == testcase_total)
        if compile_ok and did_run:
            result_path = out_dir / f"{base}_{stamp}_result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "total": testcase_total,
                        "passed": testcase_passed,
                        "all_passed": correct,
                        "testcases": testcase_results,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"- Result: {result_path}")
    elif compile_ok and run_ok and not timed_out and expected_stdout is not None:
        correct = outputs_match(r_out, expected_stdout)
        result_path = out_dir / f"{base}_{stamp}_result.txt"
        result_path.write_text(
            f"correct={correct}\n"
            f"expected (normalized):\n{normalize_output(expected_stdout)}\n\n"
            f"actual (normalized):\n{normalize_output(r_out)}\n",
            encoding="utf-8",
        )
        print(f"- Result: {result_path}")

    print("Saved:")
    print(f"- OCR text: {code_txt_path}")
    print(f"- C source: {code_c_path}")
    print(f"- Compile log: {compile_log_path}")
    print(f"- Run log: {run_log_path}")
    if compile_ok and args.mode == "cp":
        print(f"- Binary: {binary_path}")

    if testcase_mode:
        if correct:
            print("Result: CORRECT (all testcases passed)")
        elif not compile_ok:
            print("Result: FAILED (compile error)")
        elif timed_out:
            print(f"Result: FAILED ({testcase_passed}/{testcase_total} passed, timeout encountered)")
        elif run_ok:
            print(f"Result: INCORRECT ({testcase_passed}/{testcase_total} testcases passed)")
        else:
            print(f"Result: FAILED ({testcase_passed}/{testcase_total} passed, runtime error)")
    elif expected_stdout is not None:
        if correct:
            print("Result: CORRECT (output matches expected)")
        elif compile_ok and run_ok and not timed_out:
            print("Result: INCORRECT (output does not match expected)")
        elif missing_stdin_required:
            print("Result: FAILED (stdin missing; pass --stdin-file or use --run-anyway)")
        else:
            print("Result: FAILED (compile/run error or timeout)")
    else:
        if compile_ok and run_ok and not timed_out:
            print("Result: OK (compiled and ran successfully)")
        elif missing_stdin_required:
            print("Result: FAILED (stdin missing; pass --stdin-file or use --run-anyway)")
        else:
            print("Result: FAILED")

    status_reason = "UNKNOWN"
    if testcase_mode:
        if correct:
            status_reason = "CORRECT"
        elif not compile_ok:
            status_reason = "COMPILE_ERROR"
        elif timed_out:
            status_reason = "RUNTIME_TIMEOUT"
        elif run_ok:
            status_reason = "WRONG_OUTPUT"
        else:
            status_reason = "RUNTIME_ERROR"
    elif expected_stdout is not None:
        if correct:
            status_reason = "CORRECT"
        elif not compile_ok:
            status_reason = "COMPILE_ERROR"
        elif missing_stdin_required:
            status_reason = "FAILED_INPUT_MISSING"
        elif timed_out:
            status_reason = "RUNTIME_TIMEOUT"
        elif run_ok:
            status_reason = "WRONG_OUTPUT"
        else:
            status_reason = "RUNTIME_ERROR"
    else:
        if compile_ok and run_ok and not timed_out:
            status_reason = "OK"
        elif not compile_ok:
            status_reason = "COMPILE_ERROR"
        elif missing_stdin_required:
            status_reason = "FAILED_INPUT_MISSING"
        elif timed_out:
            status_reason = "RUNTIME_TIMEOUT"
        else:
            status_reason = "RUNTIME_ERROR"

    summary_path = out_dir / f"{base}_{stamp}_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "image": str(image_path),
                "compile_ok": compile_ok,
                "fix_attempts": fix_attempt,
                "fix_rejection_reasons": fix_rejection_reasons,
                "did_run": did_run,
                "run_ok": run_ok,
                "timed_out": timed_out,
                "exit_code": exit_code,
                "testcases_provided": testcase_mode,
                "testcases_total": testcase_total,
                "testcases_passed": testcase_passed,
                "expected_provided": expected_stdout is not None,
                "correct": correct,
                "status_reason": status_reason,
                "mode": args.mode,
                "leetcode_problem_slug": leetcode_problem.title_slug if leetcode_problem else None,
                "leetcode_problem_id": leetcode_problem.question_id if leetcode_problem else None,
                "leetcode_function_name": selected_leetcode_function
                or (leetcode_problem.function_name if leetcode_problem else None),
                "leetcode_cases_sources": sorted({c.source for c in leetcode_cases}) if leetcode_cases else [],
                "leetcode_fetch_notes": leetcode_fetch_notes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"- Summary: {summary_path}")

    if testcase_mode:
        return 0 if correct else 1
    if expected_stdout is not None:
        return 0 if correct else 1
    return 0 if (compile_ok and run_ok and not timed_out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
