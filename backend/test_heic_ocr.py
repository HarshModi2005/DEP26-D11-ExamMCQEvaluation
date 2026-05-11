import sys
import json
import os
from dotenv import load_dotenv
load_dotenv()
from services.ocr_service import OCRService

def main():
    service = OCRService()
    result = service.extract_objective_sheet('/Users/harsh/Desktop/newRepo/AnswerKeyEvaluationDEP/IMG_5267.HEIC')
    print("RESULT:")
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
