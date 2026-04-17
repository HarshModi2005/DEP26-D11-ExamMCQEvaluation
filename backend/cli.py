#!/usr/bin/env python3
"""
CLI: Drive folder → OCR (local engines or online Gemini) → score → Google Sheets.

Run from the backend directory:
  cd backend && python cli.py --help

Requires:
  - Service account JSON (credentials.json or GOOGLE_APPLICATION_CREDENTIALS)
  - Offline: Tesseract (optional), and/or pip install -r requirements-local-ocr.txt (Paddle), and/or easyocr
  - Online mode: same Vertex/API setup as OCRService
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile

# Resolve imports when executed as a script
_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("cli")


def _is_student_image_file(f: dict) -> bool:
    mime = (f.get("mimeType") or "").lower()
    name = (f.get("name") or "").lower()
    if mime.startswith("image/"):
        return True
    return name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate objective sheets from a Google Drive folder and export marks to Google Sheets."
    )
    parser.add_argument(
        "--drive-folder",
        required=True,
        help="Google Drive folder URL or folder ID containing answer key + student images",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Google Sheets URL for marks export (required unless --dry-run or --no-export)",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "online"),
        default="offline",
        help="offline: local OCR (see --local-ocr). online: OCRService (Gemini)",
    )
    parser.add_argument(
        "--local-ocr",
        choices=("ensemble", "paddle", "tesseract", "easyocr"),
        default="ensemble",
        help=(
            "Used with --mode offline. ensemble=all installed backends (default); "
            "paddle=PaddleOCR; tesseract=Tesseract only; easyocr=EasyOCR only. "
            "Install extras: pip install -r requirements-local-ocr.txt"
        ),
    )
    parser.add_argument(
        "--tab-name",
        default=None,
        help="Sheet tab name to create/overwrite with marks (recommended)",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Do not call Sheets API; print JSON summary to stdout only",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List Drive files only (no download, OCR, or export)",
    )
    parser.add_argument(
        "--answer-key",
        default=None,
        help=(
            "Answer key when none is named answer_key/marking_scheme in the folder: "
            "local path to .csv/.xlsx, or a Google Drive file URL, or a Google Sheets URL for the key."
        ),
    )
    args = parser.parse_args()
    if not args.dry_run and not args.no_export and not args.sheet:
        parser.error("--sheet is required when exporting to Google Sheets")

    os.chdir(_BACKEND_ROOT)

    from services.drive_service import DriveService
    from services.answer_key_service import AnswerKeyService
    from services.evaluation_service import EvaluationService
    from services.sheets_service import SheetsService
    from models import AnswerKey, StudentResult

    drive = DriveService()
    answer_key_service = AnswerKeyService()
    sheets_service = SheetsService()

    if args.mode == "offline":
        from services.offline_ocr_service import OfflineOCRService

        ocr = OfflineOCRService(engine=args.local_ocr)
    else:
        from services.ocr_service import OCRService

        ocr = OCRService()

    folder_id = DriveService.extract_folder_id(args.drive_folder)
    all_files = drive.list_all_files_in_folder(folder_id)
    if not all_files:
        logger.error("No files in folder.")
        return 1

    answer_key_files, student_sheets = drive.separate_files(all_files)
    student_sheets = [f for f in student_sheets if _is_student_image_file(f)]

    if args.dry_run:
        print(json.dumps({"folder_id": folder_id, "answer_keys": [x["name"] for x in answer_key_files], "students": [x["name"] for x in student_sheets]}, indent=2))
        return 0

    if not answer_key_files and not args.answer_key:
        logger.error(
            "No answer key file in folder (expected name containing answer_key, marking_scheme, etc.). "
            "Pass --answer-key with a local .csv/.xlsx path or a Drive file / Sheets URL for the key."
        )
        return 1

    if not student_sheets:
        logger.error("No image student sheets found after filtering.")
        return 1

    temp_ak = tempfile.mkdtemp(prefix="cli_ak_")
    try:
        if args.answer_key:
            ak_src = args.answer_key.strip()
            if os.path.isfile(ak_src):
                ak_path = ak_src
                mime_type = ""
            else:
                file_id = DriveService.extract_file_id(ak_src)
                if not file_id:
                    logger.error(
                        "--answer-key must be a local file path or a valid Drive/Sheets URL with a file id."
                    )
                    return 1
                service = drive.get_service()
                if not service:
                    logger.error("Drive service not available for --answer-key download.")
                    return 1
                meta = (
                    service.files()
                    .get(
                        fileId=file_id,
                        fields="id,name,mimeType",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
                ak_path = drive.download_answer_key(meta, temp_ak)
                mime_type = meta.get("mimeType", "")
        else:
            ak_path = drive.download_answer_key(answer_key_files[0], temp_ak)
            mime_type = answer_key_files[0].get("mimeType", "")
        answer_key: AnswerKey = answer_key_service.extract_answer_key(ak_path, mime_type)
    except Exception as exc:
        logger.error("Answer key failed: %s", exc)
        return 1
    finally:
        shutil.rmtree(temp_ak, ignore_errors=True)

    temp_sheets = tempfile.mkdtemp(prefix="cli_sheets_")
    results: list[StudentResult] = []
    errors: list[dict] = []

    try:
        for idx, sheet_file in enumerate(student_sheets):
            file_name = sheet_file["name"]
            file_id = str(sheet_file.get("id") or "")
            safe = re.sub(r"[^\w.\-]", "_", file_name)
            local_path = os.path.join(temp_sheets, f"{idx:04d}_{safe}")

            logger.info("[%d/%d] %s", idx + 1, len(student_sheets), file_name)
            if not drive.download_file(sheet_file["id"], local_path):
                errors.append({"file": file_name, "error": "download failed"})
                continue

            try:
                extracted = ocr.extract_objective_sheet(local_path)
            except Exception as exc:
                errors.append({"file": file_name, "error": str(exc)})
                continue

            if isinstance(extracted, dict) and extracted.get("error"):
                errors.append({"file": file_name, "error": extracted["error"]})
                continue

            student_result = EvaluationService.match_and_score(answer_key, extracted)
            student_result = student_result.model_copy(
                update={"file_id": file_id or None, "file_name": file_name}
            )
            results.append(student_result)
            logger.info(
                "  → %s | %s | %.1f / %.1f",
                student_result.entry_number or "?",
                student_result.name or "?",
                student_result.total_score,
                student_result.max_score,
            )

        summary = {
            "processed": len(results),
            "errors": errors,
            "results": [r.model_dump() for r in results],
        }

        if args.no_export:
            print(json.dumps(summary, indent=2, default=str))
            return 0 if not errors else 2

        if not sheets_service.service:
            logger.error(
                "Sheets service not initialized. Set GOOGLE_APPLICATION_CREDENTIALS or credentials.json."
            )
            return 1

        try:
            export = sheets_service.update_marks(
                args.sheet,
                [r.model_dump() for r in results],
                sheet_tab_name=args.tab_name,
            )
            logger.info("Sheets export: %s", export.get("updated", export))
        except Exception as exc:
            logger.error("Sheets export failed: %s", exc)
            return 1

        if errors:
            logger.warning("%d file(s) had errors", len(errors))
            for e in errors:
                logger.warning("  %s: %s", e.get("file"), e.get("error"))
            return 2
        return 0
    finally:
        shutil.rmtree(temp_sheets, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
