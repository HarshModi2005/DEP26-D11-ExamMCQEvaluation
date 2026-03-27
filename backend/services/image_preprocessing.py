#!/usr/bin/env python3
"""
Shared Image Preprocessing Utilities for OCR Services
======================================================
Intelligently crops / isolates the white answer-sheet paper from any
surrounding background (dark scanner lid, desk surface, shadows, etc.)
before handing the image to the Gemini OCR API.

Algorithm (in order):
1. Try to detect the white paper region via HSV colour thresholding +
   morphological cleanup + contour search (best quality).
2. Fallback: numpy-based dark-pixel bounding-box crop (removes white
   margins from an already clean scan).
3. Final fallback: return the image untouched.
"""

import io
import logging
from typing import Tuple, Optional
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def preprocess_for_ocr(
    image_path: str,
    max_size: Tuple[int, int] = (1920, 1920),
    jpeg_quality: int = 85,
) -> Tuple[bytes, str]:
    """
    Load an image, intelligently crop the white paper region, resize and
    compress it, then return (jpeg_bytes, mime_type).

    Parameters
    ----------
    image_path : str
        Absolute path to the source image (JPEG / PNG / any PIL-readable).
    max_size : (int, int)
        Maximum (width, height) after crop – the image is scaled down with
        aspect-ratio preserved if it exceeds this.
    jpeg_quality : int
        JPEG compression quality (1-95).

    Returns
    -------
    (bytes, "image/jpeg")
    """
    try:
        with Image.open(image_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif img.mode == "L":
                img = img.convert("RGB")

            # Step 1 – try HSV-based paper detection (requires numpy + cv2)
            cropped = _crop_paper_region_cv2(img)

            if cropped is None:
                # Step 2 – numpy dark-pixel bounding-box fallback
                cropped = _crop_dark_pixel_bbox(img)

            if cropped is None:
                # Step 3 – no-op, use full image
                cropped = img.copy()

            # Resize if still too large (keeps aspect ratio)
            if cropped.size[0] > max_size[0] or cropped.size[1] > max_size[1]:
                cropped.thumbnail(max_size, Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            cropped.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
            buf.seek(0)
            return buf.read(), "image/jpeg"

    except Exception as exc:
        logger.warning(f"preprocess_for_ocr failed for {image_path}: {exc}. Using raw file.")
        # Hard fallback: read and return raw bytes
        with open(image_path, "rb") as fh:
            raw = fh.read()
        mime = (
            "image/jpeg"
            if image_path.lower().endswith((".jpg", ".jpeg"))
            else "image/png"
        )
        return raw, mime


# ---------------------------------------------------------------------------
# Strategy 1 – HSV-based white-paper detection via OpenCV
# ---------------------------------------------------------------------------

def _crop_paper_region_cv2(img: Image.Image) -> Optional[Image.Image]:
    """
    Detect the largest white-paper region in the image using OpenCV.

    The algorithm:
    - Convert to HSV.
    - Threshold for *white* pixels: high Value (>160), low Saturation (<60).
      This isolates the paper while ignoring dark/coloured backgrounds.
    - Morphological close to fill small holes (printed text, tick marks).
    - Find external contours; pick the largest one whose area is ≥ 15 % of
      the image area (avoids false positives from small white patches).
    - Fit a bounding rectangle to that contour and crop with small padding.
    """
    try:
        import cv2
        import numpy as np

        img_rgb = np.array(img)  # PIL is already RGB
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

        h, w = img_hsv.shape[:2]
        image_area = h * w

        # --- White-paper mask ---
        # S < 60  →  low saturation (grey-ish / white)
        # V > 160 →  high brightness (white, not dark grey)
        lower_white = np.array([0,   0, 160], dtype=np.uint8)
        upper_white = np.array([180, 60, 255], dtype=np.uint8)
        mask = cv2.inRange(img_hsv, lower_white, upper_white)

        # Morphological close: fill holes left by text, printed lines, stamps
        kernel_size = max(20, int(min(h, w) * 0.02))  # ~2 % of shorter dim
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kernel_size, kernel_size)
        )
        mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        # Small erosion to separate sheet from thin white borders on scanner bed
        erode_sz = max(5, kernel_size // 4)
        erode_k = cv2.getStructuringElement(cv2.MORPH_RECT, (erode_sz, erode_sz))
        mask_eroded = cv2.erode(mask_closed, erode_k, iterations=1)

        contour_result = cv2.findContours(
            mask_eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        # OpenCV 4.x returns (contours, hierarchy); 3.x returns (img, contours, hierarchy)
        contours = contour_result[0] if len(contour_result) == 2 else contour_result[1]
        
        if not contours:
            logger.debug("cv2 paper crop: no contours found, skipping.")
            return None

        # Pick largest contour whose bounding box covers ≥ 15 % of image
        contours_sorted = sorted(contours, key=cv2.contourArea, reverse=True)
        best = None
        for cnt in contours_sorted:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            if (bw * bh) >= 0.15 * image_area:
                best = (bx, by, bw, bh)
                break

        if best is None:
            logger.debug("cv2 paper crop: largest contour too small, skipping.")
            return None

        bx, by, bw, bh = best
        pad = 15
        x0 = max(0, bx - pad)
        y0 = max(0, by - pad)
        x1 = min(w, bx + bw + pad)
        y1 = min(h, by + bh + pad)

        cropped_arr = img_rgb[y0:y1, x0:x1]
        result = Image.fromarray(cropped_arr, "RGB")

        reduction = 1.0 - (result.size[0] * result.size[1]) / image_area
        logger.info(
            f"cv2 paper crop: {img.size} -> {result.size} "
            f"(removed {reduction:.1%} of image area)"
        )
        return result

    except ImportError:
        logger.debug("cv2 not available; skipping HSV paper detection.")
        return None
    except Exception as exc:
        logger.warning(f"cv2 paper crop failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Strategy 2 – Dark-pixel bounding box (numpy only)
# ---------------------------------------------------------------------------

def _crop_dark_pixel_bbox(
    img: Image.Image, threshold: int = 240, padding: int = 40
) -> Optional[Image.Image]:
    """
    Find the bounding box of all pixels darker than `threshold` (i.e., not
    scanner-white) and crop to that box plus `padding` pixels on each side.

    This is an effective way to remove large plain-white scanner margins when
    the background is already white/near-white.
    """
    try:
        import numpy as np

        arr = np.array(img.convert("L"))
        dark_ys, dark_xs = np.where(arr < threshold)

        if dark_ys.size == 0 or dark_xs.size == 0:
            return None

        y_min, y_max = int(np.min(dark_ys)), int(np.max(dark_ys))
        x_min, x_max = int(np.min(dark_xs)), int(np.max(dark_xs))

        h, w = arr.shape
        x0 = max(0, x_min - padding)
        y0 = max(0, y_min - padding)
        x1 = min(w, x_max + padding)
        y1 = min(h, y_max + padding)

        cropped = img.crop((x0, y0, x1, y1))
        logger.info(
            f"numpy bbox crop: {img.size} -> {cropped.size}"
        )
        return cropped

    except ImportError:
        return None
    except Exception as exc:
        logger.warning(f"numpy bbox crop failed: {exc}")
        return None
