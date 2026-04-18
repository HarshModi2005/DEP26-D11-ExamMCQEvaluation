"""
PDF Split Service
=================
Turns a multi-page PDF containing one student answer sheet per page into
a flat list of per-page JPEG "sheet file" dicts that the existing batch
OCR pipeline can consume **unchanged**.

Design goals
------------
1. Produce sheet-file dicts with the same shape the Drive / ZIP flows use:
       {"id", "name", "mimeType", "local_path", "_pdf_meta"}
2. Deterministic synthetic IDs (``pdf:<pdf_hash>:p<idx>``) so the OCR and
   evaluation caches in `ResultCacheService` hit on re-uploads of the
   identical PDF — zero duplicate OCR calls.
3. Attach ``_pdf_meta`` (pdf_hash, pdf_name, page_number, page_index) so
   downstream code (``_handle_core`` in batch_endpoints_optimized.py) can
   build a page→entry / entry→page mapping without a brute search.
4. Prefer PyMuPDF (fast, no external binary). Fallback paths are kept
   minimal to avoid new system deps — if PyMuPDF is missing, raise a
   clear ImportError so the user can install it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Target render resolution for OCR. 220 DPI empirically balances OCR
# accuracy (small checkboxes still legible) with payload size / VRAM.
DEFAULT_DPI = 220
# JPEG quality for page renders. Gemini does fine with 88–92.
DEFAULT_JPEG_QUALITY = 90


def compute_pdf_hash(pdf_path: str) -> str:
    """SHA-256 of the raw PDF bytes. Stable across re-uploads."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _synthetic_sheet_file(
    page_index: int,
    page_path: str,
    pdf_hash: str,
    pdf_name: str,
    pdf_stem: str,
) -> Dict:
    """Build a dict shaped like the objects produced by ZIP / Drive ingress."""
    page_number = page_index + 1
    fname = f"{pdf_stem}__page_{page_number:03d}.jpg"
    return {
        "id": f"pdf:{pdf_hash[:16]}:p{page_index}",
        "name": fname,
        "mimeType": "image/jpeg",
        "local_path": page_path,
        "_pdf_meta": {
            "pdf_name": pdf_name,
            "pdf_hash": pdf_hash,
            "page_index": page_index,
            "page_number": page_number,
        },
    }


def split_pdf_to_pages(
    pdf_path: str,
    output_dir: str,
    dpi: int = DEFAULT_DPI,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> Tuple[List[Dict], Dict]:
    """
    Render every page of a PDF to a JPEG on disk and return
    ``(sheet_files, pdf_meta)``.

    Parameters
    ----------
    pdf_path
        Absolute path to the PDF file.
    output_dir
        Directory where rendered page images will be written. Callers are
        expected to ``shutil.rmtree`` this at the end of the run.
    dpi
        Render DPI. See :data:`DEFAULT_DPI`.
    jpeg_quality
        JPEG quality for the rendered pages (1–100).

    Returns
    -------
    sheet_files, pdf_meta
        ``sheet_files`` is the list of per-page dicts suitable for the
        batch pipeline. ``pdf_meta`` summarises the PDF (hash, name,
        total_pages) for status / index use.

    Raises
    ------
    ImportError
        If PyMuPDF is not installed.
    RuntimeError
        If the PDF cannot be opened or yields zero pages.
    """
    try:
        import fitz  # PyMuPDF
    except ModuleNotFoundError as exc:  # pragma: no cover - deps check
        raise ImportError(
            "PyMuPDF (import name `fitz`) is not installed for the Python interpreter "
            f"that is running this API ({sys.executable}). Install into that same "
            f'environment with: "{sys.executable}" -m pip install PyMuPDF'
        ) from exc
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "PyMuPDF failed to import (ImportError). "
            f"Interpreter: {sys.executable}. Original error: {exc}. "
            f'Try: "{sys.executable}" -m pip install --upgrade PyMuPDF'
        ) from exc

    pdf_path = str(pdf_path)
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF not found: {pdf_path}")

    os.makedirs(output_dir, exist_ok=True)

    pdf_name = os.path.basename(pdf_path)
    pdf_stem = os.path.splitext(pdf_name)[0]
    pdf_hash = compute_pdf_hash(pdf_path)
    # Zoom factor in PyMuPDF: 72 DPI is the PDF native resolution.
    zoom = max(1.0, float(dpi) / 72.0)
    matrix = fitz.Matrix(zoom, zoom)

    sheet_files: List[Dict] = []

    with fitz.open(pdf_path) as doc:
        total_pages = doc.page_count
        if total_pages == 0:
            raise RuntimeError(f"PDF has zero pages: {pdf_path}")

        for page_index in range(total_pages):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            page_path = os.path.join(
                output_dir, f"{pdf_stem}__page_{page_index + 1:03d}.jpg"
            )
            # PyMuPDF writes JPEG directly; `jpg_quality` is respected.
            pix.save(page_path, jpg_quality=jpeg_quality)

            sheet_files.append(
                _synthetic_sheet_file(
                    page_index=page_index,
                    page_path=page_path,
                    pdf_hash=pdf_hash,
                    pdf_name=pdf_name,
                    pdf_stem=pdf_stem,
                )
            )

    pdf_meta = {
        "pdf_name": pdf_name,
        "pdf_hash": pdf_hash,
        "pdf_stem": pdf_stem,
        "total_pages": len(sheet_files),
        "render_dpi": dpi,
    }

    logger.info(
        "PDF split complete: %s → %d page(s) @ %d DPI (hash=%s…)",
        pdf_name, len(sheet_files), dpi, pdf_hash[:12],
    )
    return sheet_files, pdf_meta


def get_page_image_path(output_dir: str, pdf_stem: str, page_number: int) -> Optional[str]:
    """Resolve the on-disk JPEG for a given 1-based page number, if it still exists."""
    candidate = os.path.join(output_dir, f"{pdf_stem}__page_{page_number:03d}.jpg")
    return candidate if os.path.exists(candidate) else None
