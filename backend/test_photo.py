import asyncio
import os
import json
from dotenv import load_dotenv
load_dotenv()
from services.ocr_service import OCRService

async def main():
    folder = "/Users/harsh/Downloads/Photo"
    files = [f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.heic'))]
    files.sort()
    results = {}
    ocr = OCRService()
    for f in files:
        path = os.path.join(folder, f)
        print(f"Processing {f}...")
        try:
            res = ocr.extract_objective_sheet(path)
            results[f] = res
            print(json.dumps(res, indent=2))
        except Exception as e:
            print(f"Error on {f}: {e}")

asyncio.run(main())
