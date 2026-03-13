import sys
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add backend to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

from services.ocr_service import OCRService

def test_simplified_ocr():
    print("Testing Simplified OCR Service (Vertex AI only)...")
    
    try:
        service = OCRService()
        
        image_path = "/Users/harsh/Desktop/DEP/temp_Screenshot 2026-02-08 at 6.53.08\u202fPM.png"
        
        if not os.path.exists(image_path):
            print(f"Error: Image not found at {image_path}")
            return

        print(f"\nExtracting data from: {image_path}\n")
        result = service.extract_data(image_path)
        
        print("\n" + "="*60)
        print("EXTRACTION RESULT")
        print("="*60)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("="*60)
        
        # Save result
        output_file = "/Users/harsh/Desktop/DEP/backend/debug_ocr/simplified_ocr_test.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Result saved to: {output_file}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_simplified_ocr()
