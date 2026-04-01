"""
All prompts used in the GLM pipeline, centralised in one place.
Easy to tweak without touching service logic.
"""


# ─────────────────────────────────────────────────────────────────────
# 1.  GLM Bounding-Box Detection Prompt
# ─────────────────────────────────────────────────────────────────────

GLM_BOUNDING_BOX_PROMPT = """
You are an expert document layout analyser. You are looking at a scanned/photographed
student answer sheet from a university exam.

CONTEXT: Students write their answers by hand on the sheet. The format is typically:
- Printed questions appear on one part of the page
- The student writes their NAME and ENTRY/ROLL NUMBER somewhere on the sheet
- The student writes their ANSWERS as a handwritten numbered list (e.g. "1. CD",
  "2. 576", "3. A") — usually in a single column, sometimes in two columns
- The page may be rotated or mixed-orientation

YOUR JOB: Return GENEROUS bounding boxes for these regions:

1. **answers_block** — a SINGLE box that encompasses the ENTIRE area where the
   student wrote their answers. This should include ALL handwritten answer lines
   from the first question to the last. Make this box VERY generous — it's better
   to include extra whitespace than to miss any answer line.

2. **question_N** — one box per individual answer line the student wrote.
   Each box should enclose the handwritten question number and the answer next to it.
   Number them sequentially: question_1, question_2, ...

CRITICAL RULES:
- The answers_block box MUST contain ALL individual question boxes with generous margin.
- Make ALL bounding boxes GENEROUS — add at least 25% extra margin.
- DO NOT include printed question text/problem statements.
- Coordinates: [y_min, x_min, y_max, x_max] normalised to 0-1000.

Return ONLY valid JSON (no markdown fences, no explanation):

{
    "regions": [
        {"label": "answers_block", "bbox": [y_min, x_min, y_max, x_max]},
        {"label": "question_1",    "bbox": [y_min, x_min, y_max, x_max]},
        {"label": "question_2",    "bbox": [y_min, x_min, y_max, x_max]},
        ...
    ]
}
"""


# ─────────────────────────────────────────────────────────────────────
# 2.  Header OCR Prompt  (used on the cropped header image)
# ─────────────────────────────────────────────────────────────────────

HEADER_OCR_PROMPT = """
This is a photograph of a student answer sheet. Somewhere on this page the
student has handwritten their NAME and ENTRY NUMBER (roll number).

The name/entry might be:
- Written anywhere on the page (top, middle, bottom, side)
- Written at any angle or orientation (the page may be rotated)
- Written freeform or next to labels like "Name:", "Entry No.", "Roll No."

Your ONLY job: find and extract the student's name and entry number.

ENTRY NUMBER PATTERNS: 2023CSB1001, 2025CSB1174, 2023MCB1353, 2024MCB126, 2025MEB1234
(format: 4-digit year + 2-3 letter department code + 3-4 digit number)

Return ONLY valid JSON (no markdown, no explanation):

{
    "entry_number": "the student's entry/roll number exactly as written",
    "name": "the student's full name exactly as written"
}

If a field is not visible, set it to null.
Return ONLY the JSON object.
"""


# ─────────────────────────────────────────────────────────────────────
# 3.  Single-Question OCR Prompt  (used on each cropped question image)
# ─────────────────────────────────────────────────────────────────────

QUESTION_OCR_PROMPT = """
This is a CROPPED region from a student's handwritten answer sheet. It shows
the student's ANSWER AREA — a handwritten numbered list of answers.

The student writes answers like:
  "1. CD"  or  "2. 576"  or  "3. C"  or  "4. 245"  or  "5. AB"
  (one answer per line, with a question number followed by their answer)

Extract ALL question-answer pairs visible in this crop.
Return ONLY valid JSON (no markdown):

{
    "answers": {
        "1": "CD",
        "2": "576",
        "3": "C",
        "4": "245",
        "5": "AB"
    }
}

Rules for answers:
- MCQ letter(s): "A", "B", "C", "D", "AB", "CD", "ACD", "ABCD"
- If written as "c), d)" or "c, d" or "(c) (d)" → combine to uppercase: "CD"
- Numerical answers: "576", "625", "1369", "2.5" — keep as-is
- If a question is blank or crossed out, OMIT it from the dict
- Convert all lowercase letters to UPPERCASE
- Sort the letters alphabetically within each answer: "DC" → "CD", "BA" → "AB"
- The handwriting may be at an angle or rotated — still read it

Return ONLY the JSON object.
"""
