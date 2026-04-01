"""
Data models for the GLM pipeline.
Keeps everything self-contained — no imports from the parent package.
"""

from pydantic import BaseModel
from typing import List, Dict, Optional


# ── Bounding Box Models ──

class BoundingBox(BaseModel):
    """
    A single bounding box detected by the GLM step.
    Coordinates are in PIXELS (converted from Gemini's 0-1000 normalised format).
    """
    label: str                       # "header" | "question_N" (e.g. "question_1")
    y_min: int
    x_min: int
    y_max: int
    x_max: int
    confidence: Optional[float] = None
    raw_normalized: Optional[List[int]] = None  # original [y1, x1, y2, x2] 0-1000


class GLMDetectionResult(BaseModel):
    """Full output of the GLM bounding-box step."""
    image_path: str
    image_width: int
    image_height: int
    regions: List[BoundingBox]
    raw_model_response: Optional[str] = None


# ── Crop Models ──

class CroppedRegion(BaseModel):
    """Metadata for a single cropped region (the actual bytes live in memory)."""
    label: str
    crop_path: Optional[str] = None  # temp file path if saved to disk
    width: int
    height: int


# ── Per-Question OCR Result ──

class QuestionOCRResult(BaseModel):
    """OCR output for one cropped question region."""
    question_number: Optional[int] = None
    marked_answer: Optional[str] = None
    raw_text: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None


class HeaderOCRResult(BaseModel):
    """OCR output for the header region."""
    entry_number: Optional[str] = None
    name: Optional[str] = None
    exam_code: Optional[str] = None
    raw_text: Optional[str] = None
    error: Optional[str] = None


# ── Merged Pipeline Output ──

class GLMPipelineResult(BaseModel):
    """
    Final merged output — same shape as what the existing
    EvaluationService.match_and_score() expects.
    """
    entry_number: str = ""
    name: str = ""
    answers: Dict[str, str] = {}       # {"1": "A", "2": "C", ...}
    comments: str = ""
    glm_metadata: Optional[Dict] = {}  # for debugging / audit
