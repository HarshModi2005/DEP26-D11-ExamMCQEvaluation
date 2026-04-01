"""
Image Crop Service
==================
Takes the original answer-sheet image + bounding boxes from GLMService
and produces individual cropped images (as PIL Images and/or bytes).

Self-contained — no imports from ../services/.
"""

import io
import os
import logging
from typing import Dict, Tuple, Optional
from PIL import Image

from .models import GLMDetectionResult, BoundingBox, CroppedRegion

logger = logging.getLogger(__name__)


class CropService:
    """Crop an answer-sheet image into per-region images."""

    def __init__(self, jpeg_quality: int = 90):
        self.jpeg_quality = jpeg_quality

    def crop_all(
        self,
        detection: GLMDetectionResult,
    ) -> Dict[str, Tuple[bytes, str, CroppedRegion]]:
        """
        Crop all detected regions from the source image.

        Args:
            detection: GLMDetectionResult from GLMService.detect_regions()

        Returns:
            Dict mapping label -> (jpeg_bytes, mime_type, CroppedRegion metadata)
        """
        image_path = detection.image_path
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Source image not found: {image_path}")

        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            results: Dict[str, Tuple[bytes, str, CroppedRegion]] = {}

            for region in detection.regions:
                try:
                    crop = self._crop_region(img, region)
                    jpeg_bytes = self._to_jpeg_bytes(crop)
                    meta = CroppedRegion(
                        label=region.label,
                        width=crop.size[0],
                        height=crop.size[1],
                    )
                    results[region.label] = (jpeg_bytes, "image/jpeg", meta)
                    logger.info(
                        f"[Crop] {region.label}: "
                        f"({region.x_min},{region.y_min})-({region.x_max},{region.y_max}) "
                        f"-> {crop.size[0]}x{crop.size[1]}"
                    )
                except Exception as e:
                    logger.error(f"[Crop] Failed to crop {region.label}: {e}")
                    continue

            return results

    def crop_single(
        self,
        image_path: str,
        bbox: BoundingBox,
    ) -> Tuple[bytes, str]:
        """Crop a single bounding box from an image file. Returns (jpeg_bytes, mime)."""
        with Image.open(image_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            crop = self._crop_region(img, bbox)
            return self._to_jpeg_bytes(crop), "image/jpeg"

    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _crop_region(img: Image.Image, bbox: BoundingBox) -> Image.Image:
        """Crop a PIL image using a BoundingBox (pixel coordinates)."""
        return img.crop((bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max))

    def _to_jpeg_bytes(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.jpeg_quality, optimize=True)
        buf.seek(0)
        return buf.read()
