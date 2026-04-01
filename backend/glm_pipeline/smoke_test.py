"""
Smoke test for the GLM pipeline.
Run from the backend/ directory:

    python -m glm_pipeline.smoke_test <path_to_answer_sheet_image>

Or:
    cd backend
    python -c "from glm_pipeline.smoke_test import run; run('path/to/image.jpg')"
"""

import sys
import os
import json
import logging

# Ensure backend/ is on the path when running as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def run(image_path: str):
    from glm_pipeline.pipeline import GLMPipeline

    print(f"\n{'='*60}")
    print(f"GLM Pipeline Smoke Test")
    print(f"Image: {image_path}")
    print(f"{'='*60}\n")

    pipeline = GLMPipeline()
    result = pipeline.process(image_path)

    print(f"\n{'='*60}")
    print("FINAL RESULT")
    print(f"{'='*60}")
    print(json.dumps(result.model_dump(), indent=2))

    # Also show the dict form (what match_and_score expects)
    print(f"\n{'─'*60}")
    print("Dict for match_and_score():")
    print(json.dumps(pipeline.process_to_dict.__wrapped__(pipeline, image_path) if hasattr(pipeline.process_to_dict, '__wrapped__') else {
        "entry_number": result.entry_number,
        "name": result.name,
        "answers": result.answers,
        "comments": result.comments,
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m glm_pipeline.smoke_test <image_path>")
        print("  e.g. python -m glm_pipeline.smoke_test ../test_images/converted/IMG_0012.jpg")
        sys.exit(1)

    run(sys.argv[1])
