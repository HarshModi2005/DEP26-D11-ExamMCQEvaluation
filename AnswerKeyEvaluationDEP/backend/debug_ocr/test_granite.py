
import sys
import os

# Add backend to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

from services.granite_ocr_service import GraniteOCRService

def test_granite():
    print("Initializing Granite OCR Service...")
    service = GraniteOCRService()
    
    image_path = "/Users/harsh/Desktop/DEP/Screenshot 2026-02-08 at 6.53.08 PM.png"
    
    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        return

    print(f"Extracting text from {image_path}...")
    try:
        text = service.extract_text(image_path)
        print("\n--- Extracted Text Start ---")
        print(text)
        print("--- Extracted Text End ---\n")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    test_granite()
