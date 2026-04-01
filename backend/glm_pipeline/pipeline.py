"""
GLM Pipeline Orchestrator
=========================
Chains together:
  1. GLM bounding-box detection  (glm_service)
  2. Image cropping              (crop_service)
  3. Per-region OCR              (ocr_service)
  4. Result merging              → standard {entry_number, name, answers} dict

Usage:
    from glm_pipeline.pipeline import GLMPipeline

    pipeline = GLMPipeline()
    result = pipeline.process(image_path)
    # result is a GLMPipelineResult (or plain dict) compatible with
    # EvaluationService.match_and_score()
"""

import logging
import time
from typing import Dict, List, Optional

from .glm_service import GLMService
from .crop_service import CropService
from .ocr_service import GLMOCRService
from .models import (
    GLMPipelineResult,
    GLMDetectionResult,
    HeaderOCRResult,
    QuestionOCRResult,
)

logger = logging.getLogger(__name__)


class GLMPipeline:
    """End-to-end GLM-enhanced OCR pipeline."""

    def __init__(self, api_key: str = None):
        self.glm = GLMService(api_key=api_key)
        self.crop = CropService()
        self.ocr = GLMOCRService(api_key=api_key)

    # ──────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────

    def process(self, image_path: str) -> GLMPipelineResult:
        """
        Run the full pipeline on a single answer-sheet image.

        Returns:
            GLMPipelineResult with entry_number, name, answers dict —
            ready to feed into EvaluationService.match_and_score().
        """
        t0 = time.time()
        logger.info(f"[Pipeline] ── START ── {image_path}")

        # ── Step 1: GLM bounding-box detection ──
        t1 = time.time()
        detection = self.glm.detect_regions(image_path)
        logger.info(f"[Pipeline] Step 1 (GLM detect): {time.time()-t1:.2f}s — {len(detection.regions)} regions")
        print(f"  [GLM] Detected {len(detection.regions)} regions in {time.time()-t1:.2f}s")

        if not detection.regions:
            logger.warning("[Pipeline] No regions detected — returning empty result")
            return GLMPipelineResult(
                comments="GLM detected no regions on this sheet.",
                glm_metadata={"detection_time": time.time() - t1},
            )

        # ── Step 2: Separate regions ──
        answers_block_region = None
        question_regions = []
        for r in detection.regions:
            if r.label == "answers_block":
                answers_block_region = r
            elif r.label.startswith("question_"):
                question_regions.append(r)

        # ── Step 3: Get the answers block ──
        # Prefer the GLM-detected answers_block; fall back to merging question boxes
        from .models import BoundingBox
        if answers_block_region:
            answers_block = answers_block_region
            # Add extra padding
            pad_y = max(30, int((answers_block.y_max - answers_block.y_min) * 0.10))
            pad_x = max(30, int((answers_block.x_max - answers_block.x_min) * 0.10))
            answers_block = BoundingBox(
                label="answers_block",
                y_min=max(0, answers_block.y_min - pad_y),
                x_min=max(0, answers_block.x_min - pad_x),
                y_max=min(detection.image_height, answers_block.y_max + pad_y),
                x_max=min(detection.image_width, answers_block.x_max + pad_x),
            )
        elif question_regions:
            # Fallback: merge all question bounding boxes
            y_min = min(r.y_min for r in question_regions)
            x_min = min(r.x_min for r in question_regions)
            y_max = max(r.y_max for r in question_regions)
            x_max = max(r.x_max for r in question_regions)
            pad_y = max(30, int((y_max - y_min) * 0.15))
            pad_x = max(30, int((x_max - x_min) * 0.15))
            answers_block = BoundingBox(
                label="answers_block",
                y_min=max(0, y_min - pad_y),
                x_min=max(0, x_min - pad_x),
                y_max=min(detection.image_height, y_max + pad_y),
                x_max=min(detection.image_width, x_max + pad_x),
            )
        else:
            answers_block = None

        # ── Step 4: Crop answers block only ──
        t2 = time.time()
        from .models import GLMDetectionResult as _Det
        crop_regions = []
        if answers_block:
            crop_regions.append(answers_block)

        crop_detection = _Det(
            image_path=image_path,
            image_width=detection.image_width,
            image_height=detection.image_height,
            regions=crop_regions,
        )
        crops = self.crop.crop_all(crop_detection)
        logger.info(f"[Pipeline] Step 2 (crop): {time.time()-t2:.2f}s — {len(crops)} crops")
        print(f"  [Crop] Produced {len(crops)} crops in {time.time()-t2:.2f}s")

        # ── Step 5: OCR header (from FULL image) and answers block ──
        t3 = time.time()
        header_result = None
        answers = {}
        comments_parts = []

        # OCR header from FULL resized image (not crop — name/entry can be anywhere)
        import io
        from PIL import Image
        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_copy = img.copy()
            img_copy.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img_copy.save(buf, format="JPEG", quality=85)
            buf.seek(0)
            full_img_bytes = buf.read()

        header_result = self.ocr.ocr_header(full_img_bytes, "image/jpeg")
        logger.info(
            f"[Pipeline] Header OCR -> entry='{header_result.entry_number}' "
            f"name='{header_result.name}'"
        )
        print(
            f"  [OCR] Header: entry='{header_result.entry_number}' | "
            f"name='{header_result.name}'"
        )

        # OCR answers block (all questions at once)
        if "answers_block" in crops:
            img_bytes, mime, meta = crops["answers_block"]
            qr = self.ocr.ocr_question(img_bytes, mime)
            if qr.error:
                comments_parts.append(f"Answers block OCR error: {qr.error}")
            elif qr.marked_answer:
                try:
                    import json as _json
                    answers = _json.loads(qr.marked_answer)
                    logger.info(f"[Pipeline] Answers OCR -> {answers}")
                    print(f"  [OCR] Answers: {answers}")
                except Exception:
                    comments_parts.append(f"Failed to parse answers JSON")

        # FALLBACK: If answers block returned empty/failed, try full image OCR
        if not answers:
            logger.info("[Pipeline] Answers block empty — falling back to full-image OCR")
            print("  [OCR] Answers block empty — trying full image fallback...")
            qr_fallback = self.ocr.ocr_question(full_img_bytes, "image/jpeg")
            if not qr_fallback.error and qr_fallback.marked_answer:
                try:
                    import json as _json
                    answers = _json.loads(qr_fallback.marked_answer)
                    logger.info(f"[Pipeline] Fallback answers -> {answers}")
                    print(f"  [OCR] Fallback answers: {answers}")
                    comments_parts.append("Used full-image fallback for answers")
                except Exception:
                    comments_parts.append("Full-image fallback also failed to parse")

        logger.info(f"[Pipeline] Step 3 (OCR): {time.time()-t3:.2f}s")
        print(f"  [OCR] Completed OCR in {time.time()-t3:.2f}s")

        # ── Step 6: Build result ──
        entry_number = ""
        name = ""
        if header_result and not header_result.error:
            entry_number = (header_result.entry_number or "").strip()
            name = (header_result.name or "").strip()

        total = time.time() - t0
        logger.info(
            f"[Pipeline] ── DONE ── {total:.2f}s  "
            f"entry='{entry_number}' name='{name}' answers={answers}"
        )
        print(
            f"  [Pipeline] DONE in {total:.2f}s: "
            f"entry='{entry_number}' | name='{name}' | {len(answers)} answers"
        )

        return GLMPipelineResult(
            entry_number=entry_number,
            name=name,
            answers=answers,
            comments="; ".join(comments_parts) if comments_parts else "",
            glm_metadata={
                "regions_detected": len(detection.regions),
                "question_regions": len(question_regions),
                "image_path": image_path,
                "total_pipeline_time": round(total, 2),
                "per_question_boxes": [
                    {"label": r.label, "bbox": [r.y_min, r.x_min, r.y_max, r.x_max]}
                    for r in question_regions
                ],
            },
        )

    # ──────────────────────────────────────────────────────────────────
    # Merge
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_results(
        header: Optional[HeaderOCRResult],
        questions: List[QuestionOCRResult],
        detection: GLMDetectionResult,
    ) -> GLMPipelineResult:
        """Combine header + per-question OCR into one result dict."""

        entry_number = ""
        name = ""
        if header and not header.error:
            entry_number = (header.entry_number or "").strip()
            name = (header.name or "").strip()

        answers: Dict[str, str] = {}
        comments_parts = []
        skipped = 0

        for qr in questions:
            if qr.error:
                comments_parts.append(f"OCR error on a question crop: {qr.error}")
                skipped += 1
                continue

            if qr.question_number is None:
                # GLM detected a region but OCR couldn't read a question number.
                # This can happen with blank / illegible entries.
                comments_parts.append(
                    f"Could not read question number from one crop (answer='{qr.marked_answer}')"
                )
                skipped += 1
                continue

            q_key = str(qr.question_number)

            if qr.marked_answer is not None and qr.marked_answer != "":
                answers[q_key] = qr.marked_answer

        if skipped:
            comments_parts.insert(0, f"{skipped} question crop(s) could not be read.")

        return GLMPipelineResult(
            entry_number=entry_number,
            name=name,
            answers=answers,
            comments="; ".join(comments_parts) if comments_parts else "",
            glm_metadata={
                "regions_detected": len(detection.regions),
                "questions_ocrd": len(questions),
                "questions_skipped": skipped,
                "image_path": detection.image_path,
            },
        )

    # ──────────────────────────────────────────────────────────────────
    # Convenience: dict output for direct use with match_and_score()
    # ──────────────────────────────────────────────────────────────────

    def process_to_dict(self, image_path: str) -> dict:
        """
        Same as process() but returns a plain dict that can be passed
        directly to EvaluationService.match_and_score().
        """
        result = self.process(image_path)
        return {
            "entry_number": result.entry_number,
            "name": result.name,
            "answers": result.answers,
            "comments": result.comments,
        }
