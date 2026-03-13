import sys
import os
import json

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from services.ocr_service import OCRService

def test_ocr(image_path):
    print(f"🔍 Testing OCR on: {image_path}")
    
    service = OCRService()
    
    if not os.path.exists(image_path):
        print(f"❌ File not found: {image_path}")
        return

    try:
        # Use the specific objective sheet extraction
        result = service.extract_objective_sheet(image_path)
        
        print("\n" + "="*40)
        print("📄 OCR RESULT")
        print("="*40)
        print(json.dumps(result, indent=2))
        print("="*40)
        
    except Exception as e:
        print(f"❌ Error during OCR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Use the file found in Downloads
    target_file = "/Users/harsh/Downloads/20260214_213615.jpg"
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
        
    test_ocr(target_file)
