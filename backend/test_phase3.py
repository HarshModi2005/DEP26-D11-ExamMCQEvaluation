import asyncio
import os
import json
from dotenv import load_dotenv
load_dotenv()
from services.ocr_service import OCRService
from services.batch_evaluation_service import BatchEvaluationService
from models import AnswerKey, AnswerKeyEntry

async def main():
    folder = "/Users/harsh/Downloads/Photo"
    files = ["IMG_5267.HEIC", "IMG_5268.HEIC", "IMG_5269.HEIC"]
    ocr_service = OCRService()
    ocr_results = []
    
    for idx, f in enumerate(files):
        path = os.path.join(folder, f)
        print(f"Processing {f}...")
        try:
            res = ocr_service.extract_objective_sheet(path)
            res["file_name"] = f
            res["file_id"] = f"id_{idx}"
            res["index"] = idx
            ocr_results.append(res)
        except Exception as e:
            print(f"Error on {f}: {e}")

    # Phase 3
    grouped_ocrs = []
    current_group = None
    
    for idx, ocr in enumerate(ocr_results):
        if ocr is None: continue
        entry = str(ocr.get("entry_number", "")).strip()
        if entry and not entry.startswith("UNREAD_"):
            if current_group is not None:
                grouped_ocrs.append(current_group)
            current_group = dict(ocr)
        else:
            if current_group is None:
                ocr["entry_number"] = f"UNREAD_{os.path.splitext(ocr['file_name'])[0]}"
                current_group = dict(ocr)
            else:
                print(f"    🔗 Merging {ocr['file_name']} into {current_group['file_name']}")
                current_group["answers"].update(ocr.get("answers", {}))
                current_group["file_name"] += " + " + ocr["file_name"]

    if current_group is not None:
        grouped_ocrs.append(current_group)

    # Load Answer Key
    with open("current_answer_key.json") as f:
        ak_dict = json.load(f)
    # create AnswerKey
    answers_map = {int(k): AnswerKeyEntry(**v) for k, v in ak_dict["answers"].items()}
    ak = AnswerKey(answers=answers_map, negative_marking=ak_dict.get("negative_marking", 0.0), total_questions=ak_dict.get("total_questions", 20))
    
    batch_eval_service = BatchEvaluationService()
    optimized_key = batch_eval_service.optimize_answer_key(ak)

    for ocr in grouped_ocrs:
        fname = ocr["file_name"]
        print(f"  ⚖️  [GROUPED] {fname}: evaluating | entry={ocr['entry_number']!r} | {len(ocr.get('answers',{}))} answers")
        student_result = batch_eval_service.evaluate_single_student_optimized(optimized_key, ocr, ocr["index"])
        print(f"Score: {student_result.total_score} / {student_result.max_score}")

asyncio.run(main())
