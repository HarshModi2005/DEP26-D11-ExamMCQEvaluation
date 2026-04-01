# GLM-Enhanced OCR Pipeline

## Overview

This folder contains a **completely self-contained** OCR pipeline that adds a
**Grounding Language Model (GLM)** bounding-box detection step **before** the
actual text extraction (OCR).

The existing pipeline in `../services/ocr_service.py` is **not modified** in
any way. This is a parallel pipeline you can switch to when you want higher
accuracy on complex answer sheets.

---

## Architecture

```
Full Answer Sheet Image
        │
        ▼
┌──────────────────────────┐
│  1. GLM Bounding Box     │  glm_service.py
│     Detection            │  Prompt: "Find header + each question"
│     (Gemini 2.5 Flash)   │  Returns: list of [y1,x1,y2,x2] per region
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  2. Image Cropping       │  crop_service.py
│     (PIL / Pillow)       │  Crops each bounding box from original image
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  3. Per-Region OCR       │  ocr_service.py
│     (Gemini 2.5 Flash)   │  Header crop  → {entry_number, name}
│                          │  Question crop → {question_number, marked_answer}
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  4. Result Merging       │  pipeline.py
│                          │  Combines all per-question OCR results into:
│                          │  {entry_number, name, answers: {"1":"A",...}}
└──────────────────────────┘
           │
           ▼
   Existing EvaluationService.match_and_score()
```

---

## File Structure

```
backend/glm_pipeline/
├── __init__.py          # Package marker + version
├── models.py            # Pydantic models (BoundingBox, GLMPipelineResult, etc.)
├── prompts.py           # All prompts in one place (easy to tweak)
├── glm_service.py       # Step 1: Bounding-box detection via Gemini
├── crop_service.py      # Step 2: Image cropping via PIL
├── ocr_service.py       # Step 3: Per-region OCR via Gemini
├── pipeline.py          # Step 4: Orchestrator (chains steps 1→2→3→merge)
├── smoke_test.py        # Quick test script
└── README.md            # This file
```

---

## Usage

### As a Python module

```python
from glm_pipeline.pipeline import GLMPipeline

pipeline = GLMPipeline()                    # uses env vars for API keys
result = pipeline.process("path/to/sheet.jpg")

print(result.entry_number)   # "2021CSB1001"
print(result.name)           # "Harsh"
print(result.answers)        # {"1": "A", "2": "C", "3": "B", ...}

# Or get a plain dict for match_and_score():
result_dict = pipeline.process_to_dict("path/to/sheet.jpg")
```

### Smoke test from CLI

```bash
cd backend
python -m glm_pipeline.smoke_test ../test_images/converted/IMG_0012.jpg
```

### Integration with existing evaluation

```python
from glm_pipeline.pipeline import GLMPipeline
from services.evaluation_service import EvaluationService
from services.answer_key_service import AnswerKeyService

# Load answer key (existing service)
ak_service = AnswerKeyService()
answer_key = ak_service.load_from_disk("current_answer_key.json")

# GLM pipeline extraction
pipeline = GLMPipeline()
student_data = pipeline.process_to_dict("path/to/student_sheet.jpg")

# Score it (existing evaluation service)
result = EvaluationService.match_and_score(answer_key, student_data)
print(f"Score: {result.total_score}/{result.max_score}")
```

---

## How It Differs From the Existing Pipeline

| Aspect | Existing (`ocr_service.py`) | GLM Pipeline |
|--------|----------------------------|--------------|
| **API calls per image** | 1 (big prompt) | 2–12 (1 GLM + 1 per region) |
| **Prompt complexity** | ~40 lines, does everything | 3 small focused prompts |
| **Layout handling** | Model must "find" regions | GLM pre-detects all regions |
| **Two-column grids** | Often misses right column | Each cell is a separate crop |
| **Entry number accuracy** | ~70-80% | Expected ~95%+ (isolated crop) |
| **Latency** | ~2-3s | ~5-10s (more API calls) |
| **Existing code changes** | N/A | ZERO — fully separate folder |

---

## Prompt Locations

All prompts live in `prompts.py` for easy tuning:

1. **`GLM_BOUNDING_BOX_PROMPT`** — tells Gemini to detect header + per-question regions
2. **`HEADER_OCR_PROMPT`** — extracts name/entry from the header crop
3. **`QUESTION_OCR_PROMPT`** — extracts question number + answer from each question crop

---

## Environment Variables

Same as the existing pipeline:

- `GOOGLE_APPLICATION_CREDENTIALS` — path to service account JSON (preferred)
- `VERTEX_AI_API_KEY` or `GOOGLE_API_KEY` — API key fallback

---

## What This Changes in the Agent / System Prompt

If you want to integrate this into your automated agent:

1. **Before**: The agent's system prompt told the OCR to extract everything in one shot
2. **Now**: The agent can use a two-phase approach:
   - Phase 1: "Detect all regions" (GLM step) — layout understanding only
   - Phase 2: "Read this specific crop" (OCR step) — text extraction only
3. The **prompts are smaller and more focused**, which means:
   - Less hallucination
   - Higher accuracy on each individual field
   - Easier to debug (you can see exactly which crop failed)
4. The **pipeline.py orchestrator** handles the chaining automatically
