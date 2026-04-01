import re

with open("backend/services/ocr_service.py", "r", encoding="utf-8") as f:
    content = f.read()

target = r"""    def extract_objective_sheet\(self, image_path: str\) -> dict:.*?        except Exception as e:
            logger\.exception\(f"\[OCR\] Unexpected exception for \{image_path\}: \{e\}"\)
            print\(f"❌ Objective sheet extraction failed: \{e\}"\)
            return \{"error": str\(e\)\}"""

replacement = """    def extract_objective_sheet(self, image_path: str) -> dict:
        \"\"\"
        Specialized extraction for OBJECTIVE answer sheets.

        Returns a dict ready for match_and_score():
            {
                "entry_number": "2023CSE001",
                "name": "Harsh",
                "answers": {"1": "A", "2": "C", "3": "B", ...}
            }
        \"\"\"
        import os, logging
        logger = logging.getLogger(__name__)
        if not os.path.exists(image_path):
            return {"error": f"File not found: {image_path}"}

        print(f"📝 Processing objective sheet: {image_path}")
        logger.info(f"[OCR] Starting extraction for: {image_path}")

        try:
            from glm_pipeline.pipeline import GLMPipeline
            
            # Use GLMPipeline instead of raw vertex calls
            pipeline = GLMPipeline()
            result = pipeline.process_to_dict(image_path)
            
            # Format enforcement logic to match exact old signature
            normalized = {
                "entry_number": result.get("entry_number", ""),
                "name": result.get("name", ""),
                "comments": result.get("comments", ""),
                "answers": result.get("answers", {})
            }
            
            logger.info(
                f"[OCR] Normalized → entry='{normalized['entry_number']}' "
                f"name='{normalized['name']}' "
                f"answers={normalized['answers']}"
            )
            print(
                f"  ✅ Normalized: entry='{normalized['entry_number']}' | "
                f"name='{normalized['name']}' | answers={normalized['answers']}"
            )
            return normalized

        except Exception as e:
            logger.exception(f"[OCR] Unexpected exception for {image_path}: {e}")
            print(f"❌ Objective sheet extraction failed: {e}")
            return {"error": str(e)}"""

new_content = re.sub(target, replacement, content, flags=re.DOTALL)
if new_content != content and "GLMPipeline" in new_content:
    with open("backend/services/ocr_service.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Patched!")
else:
    print("Target not found or no change.")
