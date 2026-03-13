import cv2
import pytesseract
import numpy as np
from PIL import Image
import os
import easyocr

# Try importing PaddleOCR
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

class LocalOCRService:
    def __init__(self):
        """
        Initializes Local OCR service supporting EasyOCR, PaddleOCR, and Tesseract.
        """
        self.easyocr_reader = None
        self.paddle_ocr = None
        self.use_paddle = PADDLE_AVAILABLE

    def _get_easyocr_reader(self):
        if self.easyocr_reader is None:
            print("Initializing EasyOCR...")
            # Use GPU if available (MPS on Mac, CUDA on Linux)
            self.easyocr_reader = easyocr.Reader(['en'], gpu=True)
        return self.easyocr_reader

    def _get_paddle_ocr(self):
        if self.paddle_ocr is None and PADDLE_AVAILABLE:
            print("Initializing PaddleOCR...")
            self.paddle_ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
        return self.paddle_ocr

    def extract_text(self, image_path: str) -> str:
        """
        Extracts raw text from an image using available local OCR engines.
        Priority: EasyOCR -> PaddleOCR -> Tesseract
        """
        if not os.path.exists(image_path):
            return ""

        text = ""
        
        # 1. Try EasyOCR (Primary)
        try:
            reader = self._get_easyocr_reader()
            results = reader.readtext(image_path, detail=0)
            text = " ".join(results)
            if len(text.strip()) > 10:
                print("✅ EasyOCR successful.")
                return text.strip()
        except Exception as e:
            print(f"EasyOCR failed: {e}")

        # 2. Try PaddleOCR (Secondary)
        if self.use_paddle:
            try:
                ocr = self._get_paddle_ocr()
                result = ocr.ocr(image_path, cls=True)
                if result and result[0]:
                    # Paddle returns [[[box], [text, conf]], ...]
                    text_lines = [line[1][0] for line in result[0]]
                    text = " ".join(text_lines)
                    if len(text.strip()) > 10:
                        print("✅ PaddleOCR successful.")
                        return text.strip()
            except Exception as e:
                print(f"PaddleOCR failed: {e}")

        # 3. Fallback to Tesseract
        print("Falling back to Tesseract...")
        try:
            img = cv2.imread(image_path)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            custom_config = r'--oem 3 --psm 3' 
            text = pytesseract.image_to_string(thresh, config=custom_config)
            return text.strip()
            
        except Exception as e:
            print(f"Local OCR Failed completely: {e}")
            return ""
