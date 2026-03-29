from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None


@dataclass
class LeetParamSpec:
    name: str
    logical_type: str


@dataclass
class LeetProblemSpec:
    title_slug: Optional[str]
    question_id: Optional[str]
    function_name: Optional[str]
    params: List[LeetParamSpec]
    return_type: Optional[str]
    sources: List[str]


@dataclass
class LeetCase:
    args: List[Any]
    expected: Any
    source: str


@dataclass
class CFunctionParam:
    name: str
    c_type: str


@dataclass
class CFunctionSpec:
    name: str
    return_type: str
    params: List[CFunctionParam]
    signature: str


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return "\n".join(lines)


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(value)


def _split_top_level_csv(text: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    quote: Optional[str] = None
    esc = False
    for ch in text:
        if quote:
            buf.append(ch)
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == quote:
                quote = None
            continue

        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
            buf.append(ch)
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _to_python_literal(value_text: str) -> Any:
    text = value_text.strip()
    text = re.sub(r"\bnull\b", "None", text, flags=re.IGNORECASE)
    text = re.sub(r"\btrue\b", "True", text, flags=re.IGNORECASE)
    text = re.sub(r"\bfalse\b", "False", text, flags=re.IGNORECASE)
    try:
        return ast.literal_eval(text)
    except Exception:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            try:
                return int(text)
            except Exception:
                pass
        return text


def _extract_text_from_html(html: str) -> str:
    if BeautifulSoup is None:
        text = re.sub(r"<[^>]+>", " ", html or "")
        return re.sub(r"\s+\n", "\n", text)
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.get_text("\n")


def _parse_example_pairs_from_content(content_html: str) -> List[Tuple[str, str]]:
    text = _extract_text_from_html(content_html)
    pattern = re.compile(
        r"Input:\s*(.*?)\s*Output:\s*(.*?)(?=(?:\n\s*Input:)|(?:\n\s*Constraints:)|\Z)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    pairs: List[Tuple[str, str]] = []
    for m in pattern.finditer(text):
        raw_input = m.group(1).strip()
        raw_output = m.group(2).strip()
        raw_output = re.split(r"\n\s*Explanation\s*:", raw_output, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if raw_input and raw_output:
            pairs.append((raw_input, raw_output))
    return pairs


def _parse_input_assignment_text(raw_input: str, param_names: List[str]) -> List[Any]:
    compact = raw_input.replace("\r", "").strip()
    if "=" in compact:
        assignments = _split_top_level_csv(compact.replace("\n", ","))
        kv: Dict[str, Any] = {}
        ordered: List[Tuple[str, Any]] = []
        for part in assignments:
            if "=" not in part:
                continue
            left, right = part.split("=", 1)
            key = left.strip()
            value = _to_python_literal(right.strip())
            kv[key] = value
            ordered.append((key, value))
        if param_names:
            out: List[Any] = []
            for p in param_names:
                if p in kv:
                    out.append(kv[p])
                else:
                    out.append(None)
            if all(x is not None for x in out):
                return out
        return [v for _, v in ordered]

    lines = [x.strip() for x in compact.splitlines() if x.strip()]
    if not lines:
        return []
    if len(param_names) == 1:
        return [_to_python_literal("\n".join(lines))]
    return [_to_python_literal(line) for line in lines]


def _normalize_meta_params(meta: Dict[str, Any]) -> List[LeetParamSpec]:
    params = meta.get("params") or []
    out: List[LeetParamSpec] = []
    for item in params:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        logical_type = str(item.get("type") or "").strip() or "unknown"
        out.append(LeetParamSpec(name=name, logical_type=logical_type))
    return out


def _problem_from_meta(
    *,
    title_slug: Optional[str],
    question_id: Optional[str],
    meta: Dict[str, Any],
    source: str,
) -> LeetProblemSpec:
    ret = meta.get("return")
    if isinstance(ret, dict):
        return_type = str(ret.get("type") or "").strip() or None
    else:
        return_type = str(ret).strip() or None if ret is not None else None
    fn = str(meta.get("name") or "").strip() or None
    return LeetProblemSpec(
        title_slug=title_slug,
        question_id=question_id,
        function_name=fn,
        params=_normalize_meta_params(meta),
        return_type=return_type,
        sources=[source],
    )


def _dedupe_cases(cases: List[LeetCase]) -> List[LeetCase]:
    seen = set()
    out: List[LeetCase] = []
    for case in cases:
        key = (_safe_json_dumps(case.args), _safe_json_dumps(case.expected))
        if key in seen:
            continue
        seen.add(key)
        out.append(case)
    return out


def _merge_problem_specs(base: Optional[LeetProblemSpec], incoming: Optional[LeetProblemSpec]) -> Optional[LeetProblemSpec]:
    if incoming is None:
        return base
    if base is None:
        return incoming
    merged = LeetProblemSpec(
        title_slug=base.title_slug or incoming.title_slug,
        question_id=base.question_id or incoming.question_id,
        function_name=base.function_name or incoming.function_name,
        params=base.params or incoming.params,
        return_type=base.return_type or incoming.return_type,
        sources=sorted(set(base.sources + incoming.sources)),
    )
    return merged


def _parse_cases_file(path: Path) -> Tuple[Optional[LeetProblemSpec], List[LeetCase]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        data = {"testcases": raw}
    elif isinstance(raw, dict):
        data = raw
    else:
        raise SystemExit("LeetCode cases file must be a JSON list or object.")

    meta = data.get("meta") or data.get("problem") or {}
    title_slug = str(data.get("title_slug") or data.get("slug") or "").strip() or None
    question_id = str(data.get("question_id") or data.get("id") or "").strip() or None
    problem: Optional[LeetProblemSpec] = None
    if isinstance(meta, dict) and meta:
        problem = _problem_from_meta(
            title_slug=title_slug,
            question_id=question_id,
            meta=meta,
            source=f"file:{path.name}",
        )

    entries = data.get("testcases") or data.get("cases") or []
    if not isinstance(entries, list):
        raise SystemExit("LeetCode cases JSON field must be a list.")
    cases: List[LeetCase] = []
    for i, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"LeetCode testcase #{i} must be an object.")
        if "args" in item:
            args = item["args"]
            if not isinstance(args, list):
                raise SystemExit(f"LeetCode testcase #{i} field 'args' must be a list.")
        elif "input" in item:
            inp = item["input"]
            args = inp if isinstance(inp, list) else [inp]
        else:
            raise SystemExit(f"LeetCode testcase #{i} must contain 'args' or 'input'.")
        if "expected" in item:
            expected = item["expected"]
        elif "output" in item:
            expected = item["output"]
        else:
            raise SystemExit(f"LeetCode testcase #{i} must contain 'expected' or 'output'.")
        cases.append(LeetCase(args=args, expected=expected, source=f"file:{path.name}"))
    return problem, cases


def _fetch_with_pyleet(
    *,
    slug: Optional[str],
    question_id: Optional[str],
) -> Tuple[Optional[LeetProblemSpec], List[LeetCase], List[str]]:
    notes: List[str] = []
    try:
        from pyleet import get_testcase
        from pyleet.testcase_retriever import TestCaseRetriever
    except Exception as e:
        notes.append(f"pyleet_unavailable:{e.__class__.__name__}")
        return None, [], notes

    retriever = TestCaseRetriever()
    resolved_slug = slug
    if not resolved_slug and question_id:
        try:
            resolved_slug = retriever.get_problem_by_id(int(question_id))
        except Exception:
            resolved_slug = None
        if not resolved_slug:
            notes.append("pyleet_problem_lookup_failed")
            return None, [], notes

    if not resolved_slug:
        notes.append("pyleet_missing_slug")
        return None, [], notes

    question_data = retriever.get_question_data(resolved_slug)
    meta_raw = question_data.get("metaData") or "{}"
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {}

    problem = _problem_from_meta(
        title_slug=resolved_slug,
        question_id=str(question_data.get("questionId") or question_id or ""),
        meta=meta,
        source="pyleet",
    )

    pyleet_cases = get_testcase(title_slug=resolved_slug)
    param_count = len(problem.params)
    cases: List[LeetCase] = []
    for inp, exp in pyleet_cases:
        if param_count <= 1:
            args = [inp]
        elif isinstance(inp, (list, tuple)):
            args = list(inp)
        else:
            args = [inp]
        cases.append(LeetCase(args=args, expected=exp, source="pyleet"))

    notes.append(f"pyleet_cases={len(cases)}")
    return problem, cases, notes


def _extract_cases_from_leetscrape_payload(payload: Any) -> Tuple[Optional[LeetProblemSpec], List[LeetCase]]:
    if not isinstance(payload, dict):
        return None, []
    meta = payload.get("meta") or payload.get("metadata") or {}
    title_slug = str(payload.get("title_slug") or payload.get("slug") or "").strip() or None
    question_id = str(payload.get("question_id") or payload.get("id") or "").strip() or None
    problem = None
    if isinstance(meta, dict) and meta:
        problem = _problem_from_meta(
            title_slug=title_slug,
            question_id=question_id,
            meta=meta,
            source="leetscrape",
        )

    items = payload.get("testcases") or payload.get("cases") or payload.get("examples") or []
    cases: List[LeetCase] = []
    if not isinstance(items, list):
        return problem, cases

    param_names = [p.name for p in (problem.params if problem else [])]
    for item in items:
        if not isinstance(item, dict):
            continue
        if "args" in item:
            args = item["args"] if isinstance(item["args"], list) else [item["args"]]
        elif "input" in item:
            inp = item["input"]
            if isinstance(inp, str):
                args = _parse_input_assignment_text(inp, param_names)
            elif isinstance(inp, list):
                args = inp
            else:
                args = [inp]
        else:
            continue

        if "expected" in item:
            expected = item["expected"]
        elif "output" in item:
            out = item["output"]
            expected = _to_python_literal(out) if isinstance(out, str) else out
        else:
            continue
        cases.append(LeetCase(args=args, expected=expected, source="leetscrape"))
    return problem, cases


def _fetch_with_leetscrape(
    *,
    slug: Optional[str],
    question_id: Optional[str],
) -> Tuple[Optional[LeetProblemSpec], List[LeetCase], List[str]]:
    notes: List[str] = []
    module = None
    for module_name in ("leetscrape", "leetcode_scrape", "leetscraper"):
        try:
            module = importlib.import_module(module_name)
            notes.append(f"leetscrape_module={module_name}")
            break
        except Exception:
            continue
    if module is None:
        notes.append("leetscrape_unavailable")
        return None, [], notes

    payload = None
    call_specs = [
        ("get_problem", {"slug": slug, "question_id": question_id}),
        ("fetch_problem", {"slug": slug, "question_id": question_id}),
        ("get_question", {"slug": slug, "question_id": question_id}),
        ("fetch_question", {"slug": slug, "question_id": question_id}),
    ]
    for fn_name, kwargs in call_specs:
        fn = getattr(module, fn_name, None)
        if not callable(fn):
            continue
        try:
            filtered_kwargs = {k: v for k, v in kwargs.items() if v}
            payload = fn(**filtered_kwargs)
            notes.append(f"leetscrape_fn={fn_name}")
            break
        except TypeError:
            try:
                payload = fn(slug or question_id)
                notes.append(f"leetscrape_fn={fn_name}")
                break
            except Exception:
                continue
        except Exception:
            continue

    if payload is None and getattr(module, "__name__", "") == "leetscraper":
        notes.append("leetscrape_leetscraper_requires_webdriver")

    if payload is None:
        notes.append("leetscrape_no_supported_api")
        return None, [], notes

    problem, cases = _extract_cases_from_leetscrape_payload(payload)
    notes.append(f"leetscrape_cases={len(cases)}")
    return problem, cases, notes


def _fetch_from_graphql(
    *,
    slug: str,
    timeout_s: int,
) -> Tuple[Optional[LeetProblemSpec], List[LeetCase], List[str]]:
    notes: List[str] = []
    query = """
    query questionData($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        questionId
        titleSlug
        isPaidOnly
        metaData
        content
        sampleTestCase
        exampleTestcases
      }
    }
    """
    try:
        resp = requests.post(
            "https://leetcode.com/graphql",
            json={"query": query, "variables": {"titleSlug": slug}},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        notes.append(f"graphql_fetch_failed:{e.__class__.__name__}")
        return None, [], notes

    errors = payload.get("errors")
    if errors:
        notes.append("graphql_errors_present")
        return None, [], notes
    q = payload.get("data", {}).get("question")
    if not q:
        notes.append("graphql_question_missing")
        return None, [], notes

    meta_raw = q.get("metaData") or "{}"
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {}
    problem = _problem_from_meta(
        title_slug=q.get("titleSlug") or slug,
        question_id=str(q.get("questionId") or ""),
        meta=meta,
        source="graphql",
    )
    param_names = [p.name for p in problem.params]
    example_pairs = _parse_example_pairs_from_content(q.get("content") or "")
    cases: List[LeetCase] = []
    for raw_input, raw_output in example_pairs:
        args = _parse_input_assignment_text(raw_input, param_names)
        expected = _to_python_literal(raw_output)
        cases.append(LeetCase(args=args, expected=expected, source="graphql_content"))

    if not cases:
        raw_examples = q.get("exampleTestcases") or q.get("sampleTestCase") or ""
        lines = [line.strip() for line in raw_examples.splitlines() if line.strip()]
        param_count = max(1, len(problem.params))
        for i in range(0, len(lines), param_count):
            block = lines[i : i + param_count]
            if len(block) != param_count:
                break
            args = [_to_python_literal(x) for x in block]
            cases.append(LeetCase(args=args, expected=None, source="graphql_sample_inputs"))
    notes.append(f"graphql_cases={len(cases)}")
    return problem, cases, notes


def resolve_leetcode_problem_and_cases(
    *,
    slug: Optional[str],
    question_id: Optional[str],
    cases_file: Optional[Path],
    max_cases: int,
    timeout_s: int,
) -> Tuple[LeetProblemSpec, List[LeetCase], List[str]]:
    notes: List[str] = []
    merged_problem: Optional[LeetProblemSpec] = None
    collected: List[LeetCase] = []

    if cases_file:
        if not cases_file.exists():
            raise SystemExit(f"LeetCode cases file not found: {cases_file}")
        file_problem, file_cases = _parse_cases_file(cases_file)
        merged_problem = _merge_problem_specs(merged_problem, file_problem)
        collected.extend(file_cases)
        notes.append(f"cases_file_cases={len(file_cases)}")

    leetscrape_problem, leetscrape_cases, leetscrape_notes = _fetch_with_leetscrape(
        slug=slug,
        question_id=question_id,
    )
    notes.extend(leetscrape_notes)
    merged_problem = _merge_problem_specs(merged_problem, leetscrape_problem)
    collected.extend(leetscrape_cases)

    pyleet_problem, pyleet_cases, pyleet_notes = _fetch_with_pyleet(
        slug=slug,
        question_id=question_id,
    )
    notes.extend(pyleet_notes)
    merged_problem = _merge_problem_specs(merged_problem, pyleet_problem)
    collected.extend(pyleet_cases)

    if not collected and slug:
        gql_problem, gql_cases, gql_notes = _fetch_from_graphql(slug=slug, timeout_s=timeout_s)
        notes.extend(gql_notes)
        merged_problem = _merge_problem_specs(merged_problem, gql_problem)
        collected.extend(gql_cases)

    collected = [c for c in collected if c.expected is not None]
    collected = _dedupe_cases(collected)
    if max_cases > 0:
        collected = collected[:max_cases]

    if merged_problem is None:
        merged_problem = LeetProblemSpec(
            title_slug=slug,
            question_id=question_id,
            function_name=None,
            params=[],
            return_type=None,
            sources=[],
        )
    if slug and not merged_problem.title_slug:
        merged_problem.title_slug = slug
    if question_id and not merged_problem.question_id:
        merged_problem.question_id = question_id

    if not collected:
        raise SystemExit(
            "Could not build LeetCode testcases from leetscrape/pyleet/graphql. "
            "Pass --leetcode-cases-file with normalized testcases."
        )
    return merged_problem, collected, notes


def _strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    code = re.sub(r"//.*", "", code)
    return code


def _split_param_tokens(param_text: str) -> List[str]:
    return _split_top_level_csv(param_text)


def _normalize_c_type(type_text: str) -> str:
    text = re.sub(r"\s+", " ", type_text.strip())
    text = text.replace(" *", "*").replace("* ", "*")
    return text


def extract_c_function_specs(code: str) -> List[CFunctionSpec]:
    cleaned = _strip_comments(code)
    pattern = re.compile(
        r"(^|\n)\s*([A-Za-z_][\w\s\*]*?)\s+([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{",
        flags=re.MULTILINE,
    )
    specs: List[CFunctionSpec] = []
    disallowed_names = {"if", "for", "while", "switch"}
    for m in pattern.finditer(cleaned):
        ret = _normalize_c_type(m.group(2))
        name = m.group(3).strip()
        if name in disallowed_names:
            continue
        signature = f"{ret} {name}({m.group(4).strip()})"
        raw_params = m.group(4).strip()
        params: List[CFunctionParam] = []
        if raw_params and raw_params != "void":
            for token in _split_param_tokens(raw_params):
                t = token.strip()
                if not t:
                    continue
                pm = re.search(r"([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*$", t)
                if not pm:
                    continue
                pname = pm.group(1)
                ptype = t[: pm.start(1)].strip()
                if pm.group(2):
                    if not ptype.endswith("*"):
                        ptype = ptype + "*"
                ptype = _normalize_c_type(ptype)
                params.append(CFunctionParam(name=pname, c_type=ptype))
        specs.append(CFunctionSpec(name=name, return_type=ret, params=params, signature=signature))
    return specs


def _select_function(
    specs: List[CFunctionSpec],
    *,
    override_name: Optional[str],
    preferred_name: Optional[str],
) -> Tuple[CFunctionSpec, List[str]]:
    notes: List[str] = []
    candidates = [x for x in specs if x.name != "main"]
    if not candidates:
        raise ValueError("No callable function definitions found in OCR C code.")

    if override_name:
        for fn in candidates:
            if fn.name == override_name:
                return fn, notes
        raise ValueError(f"Requested function '{override_name}' not found in OCR C code.")

    if preferred_name:
        for fn in candidates:
            if fn.name == preferred_name:
                return fn, notes

    if len(candidates) == 1:
        return candidates[0], notes
    notes.append(f"multiple_functions_detected={len(candidates)}")
    notes.append(f"defaulting_to={candidates[-1].name}")
    return candidates[-1], notes


def _ctype_pointer_depth(c_type: str) -> int:
    return c_type.count("*")


def _ctype_base(c_type: str) -> str:
    text = c_type.replace("*", " ")
    text = re.sub(r"\b(const|volatile|restrict|signed|unsigned)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _is_bool_scalar(c_type: str) -> bool:
    return _ctype_pointer_depth(c_type) == 0 and _ctype_base(c_type) in {"bool", "_bool"}


def _is_listnode_ptr(c_type: str) -> bool:
    base = _ctype_base(c_type)
    return _ctype_pointer_depth(c_type) == 1 and ("listnode" in base)


def _is_treenode_ptr(c_type: str) -> bool:
    base = _ctype_base(c_type)
    return _ctype_pointer_depth(c_type) == 1 and ("treenode" in base)


def _is_integer_scalar(c_type: str) -> bool:
    if _ctype_pointer_depth(c_type) != 0:
        return False
    base = _ctype_base(c_type)
    if "char" in base or "float" in base or "double" in base or "bool" in base:
        return False
    return any(tok in base for tok in ("int", "long", "short"))


def _is_char_ptr(c_type: str) -> bool:
    return _ctype_pointer_depth(c_type) == 1 and "char" in _ctype_base(c_type)


def _is_char_ptr_ptr(c_type: str) -> bool:
    return _ctype_pointer_depth(c_type) == 2 and "char" in _ctype_base(c_type)


def _is_integer_ptr(c_type: str) -> bool:
    base = _ctype_base(c_type)
    if "listnode" in base or "treenode" in base:
        return False
    return _ctype_pointer_depth(c_type) == 1 and not ("char" in base) and not ("bool" in base)


def _is_integer_ptr_ptr(c_type: str) -> bool:
    base = _ctype_base(c_type)
    if "listnode" in base or "treenode" in base:
        return False
    return _ctype_pointer_depth(c_type) == 2 and not ("char" in base) and not ("bool" in base)


def _strip_pointer(c_type: str, count: int = 1) -> str:
    out = c_type.strip()
    for _ in range(count):
        idx = out.rfind("*")
        if idx < 0:
            break
        out = out[:idx]
    return _normalize_c_type(out)


def _is_size_param_name(name: str) -> bool:
    low = name.lower()
    return low.endswith("size") or low.endswith("len")


def _is_col_size_param_name(name: str) -> bool:
    return name.lower().endswith("colsize")


def _is_output_size_param(param: CFunctionParam, logical_input_names: set[str]) -> bool:
    low = param.name.lower()
    if param.name in logical_input_names:
        return False
    if "returnsize" in low and _is_integer_ptr(param.c_type):
        return True
    return False


def _find_base_name_for_size_param(size_name: str, logical_input_names: set[str]) -> Optional[str]:
    candidates = []
    low = size_name.lower()
    if low.endswith("size"):
        candidates.append(size_name[:-4])
    if low.endswith("len"):
        candidates.append(size_name[:-3])
    if low.endswith("colsize"):
        candidates.append(size_name[:-7])
    for c in candidates:
        c = c.strip("_")
        for name in logical_input_names:
            if name == c:
                return name
            if name.lower() == c.lower():
                return name
    return None


def _c_string_literal(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _format_int_list(values: List[Any]) -> str:
    return ", ".join(str(int(v)) for v in values)


def _serialize_expected(expected: Any, return_type: str) -> str:
    if _is_bool_scalar(return_type):
        return "true" if bool(expected) else "false"
    if _is_integer_scalar(return_type):
        return str(int(expected))
    if _is_char_ptr(return_type):
        if expected is None:
            return "<null>"
        return str(expected)
    if _is_listnode_ptr(return_type) or _is_treenode_ptr(return_type):
        if expected is None:
            return "[]"
        if isinstance(expected, list):
            return json.dumps(expected, separators=(",", ":"))
        return _safe_json_dumps(expected)
    if _is_integer_ptr(return_type):
        if expected is None:
            return "[]"
        if not isinstance(expected, list):
            return _safe_json_dumps(expected)
        return "[" + ",".join(str(int(x)) for x in expected) + "]"
    return _safe_json_dumps(expected)


def _logical_input_map(
    case: LeetCase,
    *,
    problem: LeetProblemSpec,
    func: CFunctionSpec,
) -> Dict[str, Any]:
    if problem.params:
        names = [p.name for p in problem.params]
        if len(names) >= len(case.args):
            return {names[i]: case.args[i] for i in range(len(case.args))}

    candidate_names = []
    for p in func.params:
        if _is_size_param_name(p.name):
            continue
        if _is_col_size_param_name(p.name):
            continue
        if "returnsize" in p.name.lower():
            continue
        candidate_names.append(p.name)

    if len(candidate_names) >= len(case.args):
        return {candidate_names[i]: case.args[i] for i in range(len(case.args))}
    return {f"arg{i}": v for i, v in enumerate(case.args)}


def _build_input_binding(name: str, c_type: str, value: Any) -> Tuple[List[str], str, Dict[str, Any]]:
    lines: List[str] = []
    meta: Dict[str, Any] = {}

    if _is_integer_scalar(c_type):
        lines.append(f"{c_type} {name} = {int(value)};")
        return lines, name, meta

    if _is_bool_scalar(c_type):
        lines.append(f"bool {name} = {'true' if bool(value) else 'false'};")
        return lines, name, meta

    if _is_char_ptr(c_type):
        if value is None:
            lines.append(f"{c_type} {name} = NULL;")
            return lines, name, meta
        if not isinstance(value, str):
            raise ValueError(f"Parameter '{name}' expects string-compatible input.")
        lines.append(f"char {name}_storage[] = {_c_string_literal(value)};")
        lines.append(f"{c_type} {name} = {name}_storage;")
        return lines, name, meta

    if _is_integer_ptr(c_type):
        if not isinstance(value, list):
            raise ValueError(f"Parameter '{name}' expects list-compatible input.")
        elem_type = _strip_pointer(c_type, 1)
        lines.append(f"{elem_type} {name}_storage[] = {{{_format_int_list(value)}}};")
        lines.append(f"{c_type} {name} = {name}_storage;")
        meta["len"] = len(value)
        return lines, name, meta

    if _is_char_ptr_ptr(c_type):
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f"Parameter '{name}' expects list[string] input.")
        for i, s in enumerate(value):
            lines.append(f"char {name}_str_{i}[] = {_c_string_literal(s)};")
        refs = ", ".join(f"{name}_str_{i}" for i in range(len(value)))
        lines.append(f"char* {name}_storage[] = {{{refs}}};")
        lines.append(f"{c_type} {name} = {name}_storage;")
        meta["len"] = len(value)
        return lines, name, meta

    if _is_listnode_ptr(c_type):
        if value is None:
            lines.append(f"{c_type} {name} = NULL;")
            return lines, name, meta
        if not isinstance(value, list):
            raise ValueError(f"Parameter '{name}' expects list-compatible input for ListNode.")
        filtered = [x for x in value if x is not None]
        lines.append(f"int {name}_vals[] = {{{_format_int_list(filtered)}}};")
        lines.append(f"int {name}_n = {len(filtered)};")
        lines.append(f"{c_type} {name} = __build_listnode({name}_vals, {name}_n);")
        meta["len"] = len(filtered)
        return lines, name, meta

    if _is_treenode_ptr(c_type):
        if value is None:
            lines.append(f"{c_type} {name} = NULL;")
            return lines, name, meta
        if not isinstance(value, list):
            raise ValueError(f"Parameter '{name}' expects list-compatible input for TreeNode.")
        vals: List[int] = []
        nulls: List[int] = []
        for item in value:
            if item is None:
                vals.append(0)
                nulls.append(1)
            else:
                vals.append(int(item))
                nulls.append(0)
        lines.append(f"int {name}_vals[] = {{{', '.join(str(v) for v in vals)}}};")
        lines.append(
            f"bool {name}_is_null[] = {{{', '.join('true' if x else 'false' for x in nulls)}}};"
        )
        lines.append(f"int {name}_n = {len(vals)};")
        lines.append(f"{c_type} {name} = __build_tree({name}_vals, {name}_is_null, {name}_n);")
        meta["len"] = len(vals)
        return lines, name, meta

    if _is_integer_ptr_ptr(c_type):
        if not isinstance(value, list) or any(not isinstance(row, list) for row in value):
            raise ValueError(f"Parameter '{name}' expects list[list[int]] input.")
        row_elem_type = _strip_pointer(c_type, 2)
        row_ptr_type = _strip_pointer(c_type, 1)
        col_sizes: List[int] = []
        for i, row in enumerate(value):
            col_sizes.append(len(row))
            lines.append(f"{row_elem_type} {name}_row_{i}[] = {{{_format_int_list(row)}}};")
        refs = ", ".join(f"{name}_row_{i}" for i in range(len(value)))
        lines.append(f"{row_ptr_type} {name}_storage[] = {{{refs}}};")
        lines.append(f"{c_type} {name} = {name}_storage;")
        meta["len"] = len(value)
        meta["col_sizes"] = col_sizes
        return lines, name, meta

    raise ValueError(f"Unsupported parameter type '{c_type}' for '{name}'.")


def _scalar_printf_fmt(c_type: str) -> str:
    low = _ctype_base(c_type)
    if "long long" in low:
        return "%lld"
    if "long" in low:
        return "%ld"
    if "short" in low:
        return "%d"
    return "%d"


def _render_case_harness(
    *,
    code: str,
    func: CFunctionSpec,
    problem: LeetProblemSpec,
    case: LeetCase,
) -> Tuple[str, str]:
    logical = _logical_input_map(case, problem=problem, func=func)
    logical_names = set(logical.keys())
    declarations: List[str] = []
    call_args: List[str] = []
    input_meta: Dict[str, Dict[str, Any]] = {}
    out_size_vars: Dict[str, str] = {}

    for p in func.params:
        if p.name in logical:
            decl, expr, meta = _build_input_binding(p.name, p.c_type, logical[p.name])
            declarations.extend(decl)
            call_args.append(expr)
            input_meta[p.name] = meta
            continue

        if _is_col_size_param_name(p.name) and _is_integer_ptr(p.c_type):
            base = _find_base_name_for_size_param(p.name, logical_names)
            if base and isinstance(logical.get(base), list):
                base_meta = input_meta.get(base, {})
                col_sizes = base_meta.get("col_sizes")
                if not col_sizes and isinstance(logical[base], list):
                    col_sizes = [len(row) if isinstance(row, list) else 0 for row in logical[base]]
                col_sizes = col_sizes or []
                declarations.append(f"int {p.name}_storage[] = {{{_format_int_list(col_sizes)}}};")
                declarations.append(f"{p.c_type} {p.name} = {p.name}_storage;")
                call_args.append(p.name)
                continue

        if _is_size_param_name(p.name) and _is_integer_scalar(p.c_type):
            base = _find_base_name_for_size_param(p.name, logical_names)
            if base and isinstance(logical.get(base), list):
                sz = len(logical[base])
            else:
                sz = 0
            declarations.append(f"{p.c_type} {p.name} = {sz};")
            call_args.append(p.name)
            continue

        if _is_output_size_param(p, logical_names):
            local = f"{p.name}_value"
            declarations.append(f"int {local} = 0;")
            out_size_vars[p.name] = local
            call_args.append(f"&{local}")
            continue

        raise ValueError(f"Could not bind argument '{p.name}' of type '{p.c_type}'.")

    call_text = f"{func.name}({', '.join(call_args)})"
    result_lines: List[str] = []
    ret = func.return_type
    needs_list_helpers = _is_listnode_ptr(ret) or any(_is_listnode_ptr(p.c_type) for p in func.params)
    needs_tree_helpers = _is_treenode_ptr(ret) or any(_is_treenode_ptr(p.c_type) for p in func.params)

    helpers: List[str] = []
    if needs_list_helpers:
        helpers.extend(
            [
                "static struct ListNode* __build_listnode(const int* vals, int n) {",
                "    if (n <= 0) return NULL;",
                "    struct ListNode* head = (struct ListNode*)malloc(sizeof(struct ListNode));",
                "    head->val = vals[0];",
                "    head->next = NULL;",
                "    struct ListNode* cur = head;",
                "    for (int i = 1; i < n; ++i) {",
                "        struct ListNode* node = (struct ListNode*)malloc(sizeof(struct ListNode));",
                "        node->val = vals[i];",
                "        node->next = NULL;",
                "        cur->next = node;",
                "        cur = node;",
                "    }",
                "    return head;",
                "}",
                "static void __print_listnode(struct ListNode* head) {",
                '    printf("[");',
                "    struct ListNode* cur = head;",
                "    int first = 1;",
                "    while (cur != NULL) {",
                "        if (!first) printf(\",\");",
                "        first = 0;",
                "        printf(\"%d\", cur->val);",
                "        cur = cur->next;",
                "    }",
                '    printf("]\\n");',
                "}",
            ]
        )

    if needs_tree_helpers:
        helpers.extend(
            [
                "static struct TreeNode* __build_tree(const int* vals, const bool* is_null, int n) {",
                "    if (n <= 0) return NULL;",
                "    struct TreeNode** nodes = (struct TreeNode**)calloc((size_t)n, sizeof(struct TreeNode*));",
                "    for (int i = 0; i < n; ++i) {",
                "        if (is_null[i]) {",
                "            nodes[i] = NULL;",
                "            continue;",
                "        }",
                "        nodes[i] = (struct TreeNode*)malloc(sizeof(struct TreeNode));",
                "        nodes[i]->val = vals[i];",
                "        nodes[i]->left = NULL;",
                "        nodes[i]->right = NULL;",
                "    }",
                "    for (int i = 0; i < n; ++i) {",
                "        if (nodes[i] == NULL) continue;",
                "        int li = 2 * i + 1;",
                "        int ri = 2 * i + 2;",
                "        if (li < n) nodes[i]->left = nodes[li];",
                "        if (ri < n) nodes[i]->right = nodes[ri];",
                "    }",
                "    struct TreeNode* root = nodes[0];",
                "    free(nodes);",
                "    return root;",
                "}",
                "static void __print_tree(struct TreeNode* root) {",
                '    printf("[");',
                "    if (root == NULL) {",
                '        printf("]\\n");',
                "        return;",
                "    }",
                "    int cap = 256;",
                "    struct TreeNode** q = (struct TreeNode**)malloc(sizeof(struct TreeNode*) * (size_t)cap);",
                "    int head = 0, tail = 0;",
                "    q[tail++] = root;",
                "    int out_cap = 256;",
                "    struct TreeNode** out = (struct TreeNode**)malloc(sizeof(struct TreeNode*) * (size_t)out_cap);",
                "    int out_n = 0;",
                "    while (head < tail) {",
                "        struct TreeNode* node = q[head++];",
                "        if (out_n >= out_cap) {",
                "            out_cap *= 2;",
                "            out = (struct TreeNode**)realloc(out, sizeof(struct TreeNode*) * (size_t)out_cap);",
                "        }",
                "        out[out_n++] = node;",
                "        if (node != NULL) {",
                "            if (tail + 2 >= cap) {",
                "                cap *= 2;",
                "                q = (struct TreeNode**)realloc(q, sizeof(struct TreeNode*) * (size_t)cap);",
                "            }",
                "            q[tail++] = node->left;",
                "            q[tail++] = node->right;",
                "        }",
                "    }",
                "    int last = out_n - 1;",
                "    while (last >= 0 && out[last] == NULL) last--;",
                "    for (int i = 0; i <= last; ++i) {",
                "        if (i) printf(\",\");",
                "        if (out[i] == NULL) {",
                "            printf(\"null\");",
                "        } else {",
                "            printf(\"%d\", out[i]->val);",
                "        }",
                "    }",
                '    printf("]\\n");',
                "    free(q);",
                "    free(out);",
                "}",
            ]
        )
    if _is_integer_scalar(ret):
        fmt = _scalar_printf_fmt(ret)
        result_lines.append(f"{ret} __result = {call_text};")
        result_lines.append(f'printf("{fmt}\\n", __result);')
    elif _is_bool_scalar(ret):
        result_lines.append(f"{ret} __result = {call_text};")
        result_lines.append('printf("%s\\n", __result ? "true" : "false");')
    elif _is_char_ptr(ret):
        result_lines.append(f"{ret} __result = {call_text};")
        result_lines.append('if (__result == NULL) { printf("<null>\\n"); } else { printf("%s\\n", __result); }')
    elif _is_integer_ptr(ret):
        size_var = None
        for _, v in out_size_vars.items():
            size_var = v
            break
        if not size_var:
            raise ValueError("Return pointer requires returnSize-style out parameter.")
        fmt = _scalar_printf_fmt(_strip_pointer(ret, 1))
        result_lines.append(f"{ret} __result = {call_text};")
        result_lines.append('printf("[");')
        result_lines.append(f"for (int i = 0; i < {size_var}; ++i) {{")
        result_lines.append('    if (i) printf(",");')
        result_lines.append(f'    printf("{fmt}", __result[i]);')
        result_lines.append("}")
        result_lines.append('printf("]\\n");')
    elif _is_listnode_ptr(ret):
        result_lines.append(f"{ret} __result = {call_text};")
        result_lines.append("__print_listnode(__result);")
    elif _is_treenode_ptr(ret):
        result_lines.append(f"{ret} __result = {call_text};")
        result_lines.append("__print_tree(__result);")
    else:
        raise ValueError(f"Unsupported return type '{ret}'.")

    harness = "\n".join(
        [
            "#include <stdio.h>",
            "#include <stdlib.h>",
            "#include <string.h>",
            "#include <stdbool.h>",
            "",
            code.strip(),
            "",
            *helpers,
            "",
            "int main(void) {",
            *[f"    {line}" for line in declarations],
            *[f"    {line}" for line in result_lines],
            "    return 0;",
            "}",
            "",
        ]
    )
    expected_normalized = _serialize_expected(case.expected, ret)
    return harness, expected_normalized


def _compile_harness(source_path: Path, binary_path: Path, timeout_s: int) -> Tuple[bool, str, str]:
    proc = subprocess.run(
        ["gcc", str(source_path), "-O2", "-std=c11", "-Wall", "-Wextra", "-o", str(binary_path)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return proc.returncode == 0, proc.stdout, proc.stderr


def _run_binary(binary_path: Path, timeout_s: int) -> Tuple[bool, str, str, Optional[int], bool]:
    try:
        proc = subprocess.run(
            [str(binary_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return proc.returncode == 0, proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as e:
        return False, e.stdout or "", e.stderr or "", None, True


def evaluate_leetcode_cases(
    *,
    code: str,
    out_dir: Path,
    base: str,
    stamp: str,
    cases: List[LeetCase],
    problem: LeetProblemSpec,
    function_name_override: Optional[str],
    run_timeout_s: int,
    compile_timeout_s: int,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = extract_c_function_specs(code)
    selected, selection_notes = _select_function(
        specs,
        override_name=function_name_override,
        preferred_name=problem.function_name,
    )
    notes: List[str] = []
    notes.extend(selection_notes)
    notes.append(f"selected_function={selected.name}")

    testcase_results: List[Dict[str, Any]] = []
    lines = [f"selected_function={selected.name}", f"testcases_total={len(cases)}", ""]
    run_ok = True
    timed_out_any = False
    passed = 0
    did_run = False

    for idx, case in enumerate(cases, start=1):
        did_run = True
        status = "FAILED"
        case_compile_ok = False
        case_compile_out = ""
        case_compile_err = ""
        case_run_ok = False
        case_out = ""
        case_err = ""
        case_exit: Optional[int] = None
        case_timed_out = False
        expected_normalized = ""
        actual_normalized = ""
        matched = False
        harness_path = out_dir / f"{base}_{stamp}_leetcode_case_{idx}.c"
        harness_bin = out_dir / f"{base}_{stamp}_leetcode_case_{idx}.out"

        try:
            harness_code, expected_normalized = _render_case_harness(
                code=code,
                func=selected,
                problem=problem,
                case=case,
            )
            harness_path.write_text(harness_code, encoding="utf-8")
        except Exception as e:
            status = "HARNESS_BUILD_ERROR"
            run_ok = False
            case_err = str(e)
            testcase_results.append(
                {
                    "index": idx,
                    "status": status,
                    "run_ok": False,
                    "timed_out": False,
                    "exit_code": None,
                    "matched": False,
                    "actual_normalized": "",
                    "expected_normalized": expected_normalized,
                    "stderr": case_err,
                    "source": case.source,
                    "args": case.args,
                }
            )
            lines.append(
                f"=== testcase {idx} ===\n"
                f"status={status}\n"
                f"source={case.source}\n"
                f"stderr={case_err}\n"
            )
            continue

        case_compile_ok, case_compile_out, case_compile_err = _compile_harness(
            harness_path, harness_bin, timeout_s=compile_timeout_s
        )
        if not case_compile_ok:
            status = "COMPILE_ERROR"
            run_ok = False
        else:
            case_run_ok, case_out, case_err, case_exit, case_timed_out = _run_binary(
                harness_bin, timeout_s=run_timeout_s
            )
            actual_normalized = _normalize_whitespace(case_out)
            expected_normalized = _normalize_whitespace(expected_normalized)
            matched = case_run_ok and (not case_timed_out) and (actual_normalized == expected_normalized)
            if case_timed_out:
                status = "TIMEOUT"
                run_ok = False
                timed_out_any = True
            elif not case_run_ok:
                status = "RUNTIME_ERROR"
                run_ok = False
            elif matched:
                status = "PASSED"
                passed += 1
            else:
                status = "WRONG_OUTPUT"

        testcase_results.append(
            {
                "index": idx,
                "status": status,
                "run_ok": case_run_ok,
                "timed_out": case_timed_out,
                "exit_code": case_exit,
                "matched": matched,
                "actual_normalized": actual_normalized,
                "expected_normalized": expected_normalized,
                "stderr": case_err,
                "compile_stderr": case_compile_err,
                "source": case.source,
                "args": case.args,
            }
        )

        lines.append(
            f"=== testcase {idx} ===\n"
            f"status={status}\n"
            f"source={case.source}\n"
            f"compile_ok={case_compile_ok}\n"
            f"run_ok={case_run_ok}\n"
            f"exit_code={case_exit}\n"
            f"timed_out={case_timed_out}\n"
            f"matched={matched}\n\n"
            f"--- compile stderr ---\n{case_compile_err}\n\n"
            f"--- actual stdout ---\n{case_out}\n\n"
            f"--- expected normalized ---\n{expected_normalized}\n\n"
            f"--- stderr ---\n{case_err}\n"
        )

    return {
        "did_run": did_run,
        "run_ok": run_ok,
        "timed_out": timed_out_any,
        "testcase_total": len(cases),
        "testcase_passed": passed,
        "testcase_results": testcase_results,
        "run_log_text": "\n".join(lines),
        "selected_function": selected.name,
        "notes": notes,
    }
