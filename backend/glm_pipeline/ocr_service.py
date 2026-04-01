"""
Region-Specific OCR Service
============================
Processes individual cropped images with FOCUSED prompts
(header prompt vs question prompt).

Self-contained — does NOT import from ../services/ocr_service.py.
The auth / API plumbing is duplicated here so the original pipeline
is never touched.
"""

import os
import base64
import json
import re
import logging
import requests
from typing import Optional

from .models import HeaderOCRResult, QuestionOCRResult
from .prompts import HEADER_OCR_PROMPT, QUESTION_OCR_PROMPT

logger = logging.getLogger(__name__)


class GLMOCRService:
    """
    OCR service that works on CROPPED regions (bytes),
    not full answer-sheet images.
    """

    def __init__(self, api_key: str = None):
        self.creds = None
        self.project_id = "project-75abf07c-e594-4660-ab7"
        self.location = "us-central1"
        self.model_id = "gemini-2.5-flash"

        # ── Try Service Account ──
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
                logger.warning(f"Failed to load SA creds in GLMOCRService: {e}")

        self.api_key = api_key or os.getenv("VERTEX_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")

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
            logger.warning("GLMOCRService: no credentials — OCR disabled.")

        logger.info(f"GLMOCRService initialised (has_creds={bool(self.creds)})")

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
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def ocr_header(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> HeaderOCRResult:
        """
        Extract student name and entry number from the FULL answer sheet image.
        We use the full image because name/entry can be anywhere on the sheet
        and the GLM header bounding box is unreliable for mixed-orientation pages.
        """
        raw_text = self._call_gemini(HEADER_OCR_PROMPT, image_bytes, mime_type)
        if raw_text is None:
            return HeaderOCRResult(error="Gemini call failed")

        parsed = self._extract_json(raw_text)
        return HeaderOCRResult(
            entry_number=parsed.get("entry_number"),
            name=parsed.get("name"),
            exam_code=parsed.get("exam_code"),
            raw_text=raw_text,
        )

    def ocr_question(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> QuestionOCRResult:
        """
        Extract ALL question-answer pairs from a cropped answers block.
        Returns a QuestionOCRResult where marked_answer contains the full JSON.
        """
        raw_text = self._call_gemini(QUESTION_OCR_PROMPT, image_bytes, mime_type)
        if raw_text is None:
            return QuestionOCRResult(error="Gemini call failed")

        parsed = self._extract_json(raw_text)
        answers = parsed.get("answers", {})

        # Normalize each answer
        normalized = {}
        for q_num, ans in answers.items():
            try:
                q = int(q_num)
            except (ValueError, TypeError):
                continue
            ans_str = str(ans).strip().upper()
            # Clean parentheses and separators
            ans_str = ans_str.replace(")", "").replace("(", "").replace(",", "").replace(" ", "")
            if "OPTION" in ans_str:
                ans_str = ans_str.replace("OPTION", "").strip()
            # Sort letters alphabetically for MCQ
            if ans_str.isalpha() and len(ans_str) <= 4:
                ans_str = "".join(sorted(ans_str))
            if ans_str and ans_str not in ("X", "BLANK", "NONE", "NA", "N/A", "-"):
                normalized[str(q)] = ans_str

        return QuestionOCRResult(
            question_number=None,  # Not applicable for block mode
            marked_answer=json.dumps(normalized),  # Store as JSON string
            raw_text=raw_text,
        )

    # ──────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────

    def _call_gemini(self, prompt: str, image_bytes: bytes, mime_type: str) -> Optional[str]:
        """Send a prompt + image to Gemini and return the raw text response."""
        if not self.url:
            logger.error("GLMOCRService has no URL configured.")
            return None

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": b64}},
                    ],
                }
            ]
        }

        headers = self._get_auth_header()

        # Retry with backoff for rate limits
        import time as _time
        for attempt in range(3):
            try:
                response = requests.post(self.url, headers=headers, json=payload, timeout=60)
                if response.status_code == 429:
                    wait = (attempt + 1) * 5
                    logger.warning(f"[GLM-OCR] Rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                    _time.sleep(wait)
                    # Refresh auth header
                    headers = self._get_auth_header()
                    continue
                response.raise_for_status()
                return self._parse_streaming_response(response.json())
            except requests.exceptions.Timeout:
                logger.warning(f"[GLM-OCR] Timeout on attempt {attempt+1}/3")
                if attempt < 2:
                    _time.sleep(3)
                    continue
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    wait = (attempt + 1) * 5
                    logger.warning(f"[GLM-OCR] Rate limit error, waiting {wait}s")
                    _time.sleep(wait)
                    headers = self._get_auth_header()
                    continue
                logger.error(f"[GLM-OCR] Gemini call failed: {e}")
                return None
        logger.error("[GLM-OCR] All retries exhausted")
        return None

    # ──────────────────────────────────────────────────────────────────
    # Helpers (self-contained copies)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_streaming_response(result) -> str:
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
        logger.error(f"[GLM-OCR] JSON parse failed: {text[:300]}")
        return {}
