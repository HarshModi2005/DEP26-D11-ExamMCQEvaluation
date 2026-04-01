"""
GLM Bounding-Box Detection Service
===================================
Sends the full answer-sheet image to Gemini and asks it to return
bounding boxes for the header and each individual question's answer area.

This module is self-contained — it does NOT import from ../services/.
"""

import os
import base64
import json
import re
import logging
import requests
from typing import Optional
from PIL import Image

from .models import BoundingBox, GLMDetectionResult
from .prompts import GLM_BOUNDING_BOX_PROMPT

logger = logging.getLogger(__name__)


class GLMService:
    """Detect bounding boxes on an answer sheet using Gemini vision."""

    def __init__(self, api_key: str = None):
        self.creds = None
        self.project_id = "project-75abf07c-e594-4660-ab7"
        self.location = "us-central1"
        self.model_id = "gemini-2.5-flash"

        # ── Try Service Account credentials first ──
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path and os.path.exists(creds_path):
            try:
                from google.oauth2 import service_account
                self.creds = service_account.Credentials.from_service_account_file(
                    creds_path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                if hasattr(self.creds, "project_id") and self.creds.project_id:
                    self.project_id = self.creds.project_id
            except Exception as e:
                logger.warning(f"Failed to load SA creds in GLMService: {e}")

        self.api_key = api_key or os.getenv("VERTEX_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        # ── Build the endpoint URL (non-streaming for structured output) ──
        if self.creds:
            self.url = (
                f"https://{self.location}-aiplatform.googleapis.com/v1/"
                f"projects/{self.project_id}/locations/{self.location}/"
                f"publishers/google/models/{self.model_id}:generateContent"
            )
        elif self.api_key:
            self.url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model_id}:generateContent?key={self.api_key}"
            )
        else:
            self.url = None
            logger.warning("GLMService: no credentials found — bounding-box detection disabled.")

        logger.info(f"GLMService initialised (has_creds={bool(self.creds)}, has_key={bool(self.api_key)})")

    # ──────────────────────────────────────────────────────────────────
    # Auth
    # ──────────────────────────────────────────────────────────────────

    def _get_auth_header(self) -> dict:
        if self.creds:
            try:
                import google.auth.transport.requests as gauth_req
                self.creds.refresh(gauth_req.Request())
                return {
                    "Authorization": f"Bearer {self.creds.token}",
                    "Content-Type": "application/json",
                }
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")
        return {"Content-Type": "application/json"}

    # ──────────────────────────────────────────────────────────────────
    # Core
    # ──────────────────────────────────────────────────────────────────

    def detect_regions(self, image_path: str) -> GLMDetectionResult:
        """
        Run GLM bounding-box detection on *image_path*.

        Returns a GLMDetectionResult with pixel-coordinate bounding boxes.
        """
        if not self.url:
            raise RuntimeError("GLMService has no credentials — cannot detect regions.")

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        # ── Read image, resize if too large, get dimensions ──
        with Image.open(image_path) as img:
            orig_w, orig_h = img.size
            # Resize large images for better GLM performance
            max_dim = 2048
            if orig_w > max_dim or orig_h > max_dim:
                img_copy = img.copy()
                img_copy.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                img_w, img_h = img_copy.size
                logger.info(f"[GLM] Resized {orig_w}x{orig_h} -> {img_w}x{img_h} for detection")
                import io
                buf = io.BytesIO()
                img_copy.save(buf, format="JPEG", quality=85)
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode("utf-8")
                mime = "image/jpeg"
            else:
                img_w, img_h = orig_w, orig_h
                with open(image_path, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode("utf-8")
                mime = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"

        # ── Build Gemini request ──
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": GLM_BOUNDING_BOX_PROMPT},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ],
                }
            ]
        }

        headers = self._get_auth_header()

        logger.info(f"[GLM] Sending bounding-box request for {os.path.basename(image_path)} ({img_w}x{img_h})")

        # Retry with backoff for rate limits
        import time as _time
        raw_text = None
        for attempt in range(3):
            try:
                response = requests.post(self.url, headers=headers, json=payload, timeout=90)
                if response.status_code == 429:
                    wait = (attempt + 1) * 8
                    logger.warning(f"[GLM] Rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                    _time.sleep(wait)
                    headers = self._get_auth_header()
                    continue
                response.raise_for_status()
                raw_text = self._parse_streaming_response(response.json())
                break
            except requests.exceptions.Timeout:
                logger.warning(f"[GLM] Timeout on attempt {attempt+1}/3")
                if attempt < 2:
                    _time.sleep(5)
                    continue
                raise
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    wait = (attempt + 1) * 8
                    logger.warning(f"[GLM] Rate limit, waiting {wait}s")
                    _time.sleep(wait)
                    headers = self._get_auth_header()
                    continue
                raise

        if raw_text is None:
            return GLMDetectionResult(
                image_path=image_path, image_width=orig_w, image_height=orig_h,
                regions=[], raw_model_response="All retries exhausted"
            )

        raw_text = self._parse_streaming_response(response.json())
        logger.info(f"[GLM] Raw response:\n{raw_text[:600]}")

        parsed = self._extract_json(raw_text)

        # ── Convert normalised coords (0-1000) → pixel coords on ORIGINAL image ──
        # GLM saw the resized image, but crops will be taken from the original.
        # So we scale to original dimensions.
        regions = []
        for r in parsed.get("regions", []):
            bbox = r.get("bbox", [0, 0, 1000, 1000])
            # Gemini format: [y_min, x_min, y_max, x_max] normalised 0-1000
            y1_norm, x1_norm, y2_norm, x2_norm = bbox

            y1 = int(y1_norm / 1000 * orig_h)
            x1 = int(x1_norm / 1000 * orig_w)
            y2 = int(y2_norm / 1000 * orig_h)
            x2 = int(x2_norm / 1000 * orig_w)

            # Add generous padding (15% of box size on each side)
            box_h = y2 - y1
            box_w = x2 - x1
            pad_y = max(10, int(box_h * 0.15))
            pad_x = max(10, int(box_w * 0.15))

            y1 = max(0, y1 - pad_y)
            x1 = max(0, x1 - pad_x)
            y2 = min(orig_h, y2 + pad_y)
            x2 = min(orig_w, x2 + pad_x)

            regions.append(BoundingBox(
                label=r.get("label", "unknown"),
                y_min=y1, x_min=x1, y_max=y2, x_max=x2,
                confidence=r.get("confidence"),
                raw_normalized=bbox,
            ))

        logger.info(f"[GLM] Detected {len(regions)} regions: {[r.label for r in regions]}")

        return GLMDetectionResult(
            image_path=image_path,
            image_width=orig_w,
            image_height=orig_h,
            regions=regions,
            raw_model_response=raw_text,
        )

    # ──────────────────────────────────────────────────────────────────
    # Helpers (copied from existing OCR service to stay self-contained)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_streaming_response(result) -> str:
        """Parse Vertex AI / generativelanguage streaming JSON response."""
        all_text = []
        items = result if isinstance(result, list) else [result]
        for chunk in items:
            for candidate in chunk.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if "text" in part:
                        all_text.append(part["text"])
        return "".join(all_text)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract the first JSON object from model output."""
        cleaned = re.sub(r'```json\s*|\s*```', '', text).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        logger.error(f"[GLM] Failed to parse JSON from response: {text[:300]}")
        return {"regions": []}
