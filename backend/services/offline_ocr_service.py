"""
Local objective-sheet extraction (no cloud LLM).
=================================================
Same return shape as OCRService.extract_objective_sheet for match_and_score.

Engines (CLI: --local-ocr):
  - tesseract: system Tesseract + multi-PSM (baseline, needs brew/apt install).
  - paddle:    PaddleOCR (pip install -r requirements-local-ocr.txt).
  - easyocr:   EasyOCR + PyTorch (pip install easyocr).
  - ensemble:  run every backend that is installed and merge parsed answers.

Install extras: backend/requirements-local-ocr.txt
"""

from __future__ import annotations

import io
import logging
import os
import re
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)

# Lazy singletons (Paddle / EasyOCR init is slow)
_paddle_ocr_instance = None
_easyocr_reader = None


def _get_paddle_ocr():
    global _paddle_ocr_instance
    if _paddle_ocr_instance is not None:
        return _paddle_ocr_instance
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    try:
        _paddle_ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang="en",
            show_log=False,
        )
    except Exception as exc:
        logger.warning("PaddleOCR init failed: %s", exc)
        return None
    return _paddle_ocr_instance


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader
    try:
        import easyocr
    except ImportError:
        return None
    try:
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception as exc:
        logger.warning("EasyOCR init failed: %s", exc)
        return None
    return _easyocr_reader


def _ensure_tesseract() -> None:
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise RuntimeError(
            "Tesseract is not installed or not on PATH. "
            "Install: macOS: brew install tesseract | Ubuntu: sudo apt install tesseract-ocr"
        ) from exc


def _normalize_objective_output(parsed: dict) -> dict:
    """Same shape as OCRService._normalize_objective_output."""
    result = {
        "entry_number": parsed.get("entry_number") or parsed.get("roll_number") or "",
        "name": parsed.get("name") or parsed.get("student_name") or "",
        "comments": parsed.get("comments") or "",
        "answers": {},
    }
    raw_answers = parsed.get("answers", {})
    if isinstance(raw_answers, dict):
        for k, v in raw_answers.items():
            try:
                q_num = str(int(k))
                option = str(v).strip().upper()
                if "OPTION" in option:
                    option = option.replace("OPTION", "").strip()
                result["answers"][q_num] = option
            except (ValueError, TypeError):
                continue
    elif isinstance(raw_answers, list):
        for item in raw_answers:
            if isinstance(item, dict):
                q_num = item.get("question_number")
                option = item.get("marked_option") or item.get("option") or item.get("answer")
                if q_num is not None and option:
                    result["answers"][str(int(q_num))] = str(option).strip().upper()
    return result


def _load_pil(image_path: str):
    from PIL import Image, ImageOps

    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _pil_for_tesseract(pil_img) -> "object":
    from PIL import ImageEnhance

    try:
        from services.image_preprocessing import preprocess_for_ocr

        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=95)
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(buf.getvalue())
            tpath = tf.name
        try:
            jpeg_bytes, _ = preprocess_for_ocr(tpath)
            out = Image.open(io.BytesIO(jpeg_bytes)).convert("L")
        finally:
            try:
                os.unlink(tpath)
            except OSError:
                pass
    except Exception as exc:
        logger.debug("preprocess_for_ocr skipped: %s", exc)
        out = pil_img.convert("L")

    from PIL import ImageEnhance

    out = ImageEnhance.Contrast(out).enhance(1.35)
    return out


def _tesseract_text(pil_gray, psm: int = 6) -> str:
    import pytesseract

    cfg = f"--oem 3 --psm {psm}"
    return pytesseract.image_to_string(pil_gray, config=cfg)


def _collect_tesseract_chunks(image_path: str) -> List[str]:
    _ensure_tesseract()
    pil = _load_pil(image_path)
    gray = _pil_for_tesseract(pil)
    return [_tesseract_text(gray, psm=p) for p in (4, 6, 11, 12)]


def _flatten_paddle_result(out) -> str:
    """Turn PaddleOCR ocr() output into top-to-bottom text."""
    if not out:
        return ""
    lines: List[tuple] = []
    pages = out if isinstance(out, list) else [out]
    for page in pages:
        if page is None:
            continue
        if not isinstance(page, list):
            continue
        for item in page:
            if not item or len(item) < 2:
                continue
            box, rec = item[0], item[1]
            if isinstance(rec, (list, tuple)):
                text = str(rec[0])
            else:
                text = str(rec)
            text = text.strip()
            if not text:
                continue
            try:
                ys = [float(p[1]) for p in box]
                y_mid = sum(ys) / len(ys)
            except (TypeError, ValueError, KeyError):
                y_mid = 0.0
            lines.append((y_mid, text))
    lines.sort(key=lambda x: x[0])
    return "\n".join(t[1] for t in lines)


def _paddleocr_text(image_path: str) -> str:
    ocr = _get_paddle_ocr()
    if ocr is None:
        return ""
    try:
        raw = ocr.ocr(image_path, cls=True)
    except TypeError:
        try:
            raw = ocr.ocr(image_path)
        except Exception as exc:
            logger.debug("PaddleOCR ocr() failed: %s", exc)
            return ""
    except Exception as exc:
        logger.debug("PaddleOCR ocr() failed: %s", exc)
        return ""
    return _flatten_paddle_result(raw)


def _easyocr_text(image_path: str) -> str:
    reader = _get_easyocr_reader()
    if reader is None:
        return ""
    try:
        res = reader.readtext(image_path, detail=1, paragraph=False)
    except Exception as exc:
        logger.debug("EasyOCR readtext failed: %s", exc)
        return ""
    lines = []
    for bbox, text, _conf in res:
        if not text or not str(text).strip():
            continue
        try:
            ys = [p[1] for p in bbox]
            y_mid = sum(ys) / len(ys)
        except (TypeError, ValueError):
            y_mid = 0.0
        lines.append((y_mid, str(text).strip()))
    lines.sort(key=lambda x: x[0])
    return "\n".join(t[1] for t in lines)


def _parse_entry_number(text: str) -> str:
    patterns = [
        re.compile(
            r"(?:Entry\s*No\.?|Entry\s*Number|Roll\s*No\.?|Roll\s*Number|"
            r"Enrol(?:l)?ment\s*No\.?|Reg\.?\s*No\.?|Student\s*ID)\s*[:\-]?\s*"
            r"([0-9A-Za-z][0-9A-Za-z\s\-]{5,40})",
            re.I,
        ),
        re.compile(r"\b(\d{4}\s*[A-Za-z]{2,4}\s*[BM]\s*\d{3,5})\b"),
        re.compile(r"\b(\d{4}[A-Za-z]{2,4}[BM]\d{3,5})\b"),
    ]
    for pat in patterns:
        m = pat.search(text)
        if m:
            raw = m.group(1).strip()
            raw = re.sub(r"\s+", "", raw)
            if len(raw) >= 8:
                return raw.upper()
    return ""


def _parse_name(text: str) -> str:
    m = re.search(
        r"(?:^|\n)\s*Name\s*[:\-]\s*([^\n]+)",
        text,
        re.I | re.MULTILINE,
    )
    if not m:
        return ""
    line = m.group(1).strip()
    line = re.split(r"\s{2,}", line)[0]
    line = re.sub(r"\s+Entry\s*$", "", line, flags=re.I).strip()
    if len(line) > 80:
        line = line[:80]
    return line.upper() if line.isalpha() or " " in line else line


def _normalize_mcq_token(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip().upper()
    trans = str.maketrans(
        {
            "¢": "C",
            "©": "C",
            "€": "C",
            "«": "A",
            "»": "B",
            "@": "A",
        }
    )
    s = s.translate(trans)
    s = re.sub(r"[^A-Z0-9.,+\-]", "", s)
    if not s:
        return ""
    for ch in s:
        if ch in "ABCD":
            return ch
    if re.match(r"^[\d.+\-]+$", s):
        return s
    return s[:4] if s else ""


def _parse_answers_block(text: str) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    patterns = [
        re.compile(r"(?:^|\n)\s*(\d{1,3})\s*\)\s*([^\n]{1,12})", re.MULTILINE),
        re.compile(r"(?:^|\n)\s*(\d{1,3})\s*\.\s*([^\n]{1,12})", re.MULTILINE),
        re.compile(r"(?:^|\n)\s*Q\s*(\d{1,3})\s*[.):\-]\s*([^\n]{1,12})", re.I | re.MULTILINE),
        re.compile(r"(?:^|\n)\s*(\d{1,3})\s*[-–:]\s*([^\n]{1,12})", re.MULTILINE),
    ]
    for pat in patterns:
        for m in pat.finditer(text):
            q = str(int(m.group(1)))
            val = _normalize_mcq_token(m.group(2))
            if val and q not in answers:
                answers[q] = val
    return answers


def _merge_answers_from_chunks(chunks: List[str]) -> Dict[str, str]:
    candidates: Dict[str, List[str]] = defaultdict(list)
    for ch in chunks:
        if not ch or not ch.strip():
            continue
        for q, v in _parse_answers_block(ch).items():
            if v:
                candidates[q].append(v)
    answers: Dict[str, str] = {}
    for q, vals in candidates.items():
        best = ""
        for v in vals:
            if len(v) == 1 and v in "ABCD":
                best = v
                break
        answers[q] = best or vals[0]
    return answers


def _best_entry_name(chunks: List[str]) -> tuple:
    entry = ""
    name = ""
    for ch in chunks:
        if not ch:
            continue
        if not entry:
            entry = _parse_entry_number(ch)
        if not name:
            name = _parse_name(ch)
        if entry and name:
            break
    blob = "\n".join(c for c in chunks if c)
    if not entry:
        entry = _parse_entry_number(blob)
    if not name:
        name = _parse_name(blob)
    return entry, name


class OfflineOCRService:
    """
    Local OCR for objective sheets.

    engine:
      tesseract — Tesseract only
      paddle    — PaddleOCR only (must be installed)
      easyocr   — EasyOCR only (must be installed)
      ensemble  — all available backends + merge
    """

    def __init__(self, engine: str = "ensemble"):
        self.engine = (engine or "ensemble").strip().lower()

    def _collect_text_chunks(self, image_path: str) -> tuple[List[str], List[str]]:
        """Returns (chunks, backend_tags used per chunk group)."""
        chunks: List[str] = []
        tags: List[str] = []

        if self.engine in ("tesseract", "ensemble"):
            try:
                tess = _collect_tesseract_chunks(image_path)
                for i, t in enumerate(tess):
                    if t.strip():
                        chunks.append(t)
                        tags.append(f"tesseract_psm_{[4,6,11,12][i]}")
            except RuntimeError as exc:
                if self.engine == "tesseract":
                    raise
                logger.warning("Tesseract skipped in ensemble: %s", exc)

        if self.engine in ("paddle", "ensemble"):
            pt = _paddleocr_text(image_path)
            if pt.strip():
                chunks.append(pt)
                tags.append("paddleocr")

        if self.engine in ("easyocr", "ensemble"):
            et = _easyocr_text(image_path)
            if et.strip():
                chunks.append(et)
                tags.append("easyocr")

        return chunks, tags

    def extract_objective_sheet(self, image_path: str) -> dict:
        if not os.path.exists(image_path):
            return {"error": f"File not found: {image_path}"}

        try:
            chunks, tags = self._collect_text_chunks(image_path)
            if not chunks:
                if self.engine == "paddle":
                    return {
                        "error": "PaddleOCR produced no text or is not installed. "
                        "Try: pip install -r requirements-local-ocr.txt",
                    }
                if self.engine == "easyocr":
                    return {
                        "error": "EasyOCR produced no text or is not installed. Try: pip install easyocr",
                    }
                if self.engine == "tesseract":
                    return {"error": "Tesseract produced no text."}
                return {
                    "error": "No local OCR output. Install Tesseract (brew/apt), and/or "
                    "pip install -r requirements-local-ocr.txt (Paddle), and/or pip install easyocr",
                }

            entry, name = _best_entry_name(chunks)
            answers = _merge_answers_from_chunks(chunks)

            notes: List[str] = []
            if not answers:
                notes.append("No answer lines matched; check scan quality or layout.")
            tag_summary = "+".join(sorted(set(tags))) or self.engine
            comments_parts = [f"local_ocr:{tag_summary}"]
            comments_parts.extend(notes)

            parsed = {
                "entry_number": entry or None,
                "name": name or None,
                "answers": answers,
                "comments": "; ".join(comments_parts),
            }
            normalized = _normalize_objective_output(parsed)
            logger.info(
                "[offline_ocr] %s engine=%s entry=%r name=%r n_answers=%d",
                os.path.basename(image_path),
                self.engine,
                normalized.get("entry_number"),
                normalized.get("name"),
                len(normalized.get("answers", {})),
            )
            return normalized
        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception("offline OCR failed for %s", image_path)
            return {"error": str(exc)}
