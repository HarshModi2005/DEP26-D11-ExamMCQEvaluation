# Objective Answer Sheet Evaluation Pipeline — Detailed Plan

## 🎯 Problem Statement

Build a backend pipeline that:
1. Reads answer sheets + answer key from a Google Drive folder
2. Separates the answer key, extracts it, and uses it to score student answer sheets via OCR
3. Writes results back to a Google Sheet containing the student list

---

## 📂 Current Codebase State (What Already Exists)

| Component | File | Status |
|---|---|---|
| Google Drive read | `services/drive_service.py` | ✅ Implemented (list files, download files) |
| OCR Extraction | `services/ocr_service.py` | ✅ Implemented (Vertex AI Gemini 2.5 Flash Lite) |
| Objective Evaluation | `services/evaluation_service.py` → `evaluate_objective()` | ✅ Implemented (matching logic) |
| Subjective Evaluation | `services/evaluation_service.py` → `evaluate_subjective()` | ✅ Implemented (LLM grading) |
| API Endpoints | `api/endpoints.py` | ✅ Basic `/sync-drive`, `/process-file`, `/results` |
| Database | `database.py` | ✅ SQLite with students, submissions, results |
| Models | `models.py` | ✅ Student, Submission, EvaluationResult |
| Answer Key | `api/endpoints.py` | ⚠️ **Hardcoded** as `ANSWER_KEY_OBJECTIVE` placeholder |

### Key Gap
- The answer key is **hardcoded** in `endpoints.py`. It needs to be **dynamically extracted** from the Drive folder.
- There is **no Google Sheets integration** for writing results back.
- The Drive service only lists **image** files (`mimeType contains 'image/'`). It needs to also support answer key files (PDF, DOCX, XLSX, CSV, images).

---

## 🔁 Pipeline Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     USER PROVIDES DRIVE LINK                     │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: Drive Ingestion                                        │
│  ─────────────────────────                                       │
│  1. Parse folder ID from Drive link                              │
│  2. List ALL files in folder (not just images)                   │
│  3. Identify the answer key file by name pattern "answer_key"    │
│  4. Separate: answer_key files vs student answer sheet files     │
│  5. Download all files to temp dir                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: Answer Key Extraction + Scoring                        │
│  ──────────────────────────────────                              │
│  A. ANSWER KEY EXTRACTION                                        │
│     1. Detect answer key file format (CSV, XLSX, PDF, image,     │
│        DOCX, Google Sheets)                                      │
│     2. Parse based on format:                                    │
│        • CSV/XLSX → direct parse (pandas)                        │
│        • PDF/Image → OCR + LLM structured extraction             │
│        • Google Sheets → API read                                │
│     3. Normalize to static AnswerKey object:                     │
│        {                                                         │
│          "total_questions": 30,                                  │
│          "answers": {                                            │
│            1: {"correct_option": "A", "marks": 1},               │
│            2: {"correct_option": "C", "marks": 1},               │
│            ...                                                   │
│          },                                                      │
│          "negative_marking": 0.0,  # optional                    │
│          "metadata": {"source_file": "answer_key.csv", ...}      │
│        }                                                         │
│                                                                  │
│  B. STUDENT ANSWER SHEET PROCESSING                              │
│     For each student sheet:                                      │
│     1. OCR extract → get entry_number, name, question→option map │
│     2. Normalize to:                                             │
│        {                                                         │
│          "entry_number": "2023CSE001",                           │
│          "name": "Harsh",                                        │
│          "answers": {1: "A", 2: "B", 3: "C", ...}               │
│        }                                                         │
│                                                                  │
│  C. SCORING                                                      │
│     score = match_and_score(answer_key, student_answers)         │
│     Returns:                                                     │
│        {                                                         │
│          "entry_number": "2023CSE001",                           │
│          "name": "Harsh",                                        │
│          "total_score": 25,                                      │
│          "max_score": 30,                                        │
│          "correct": 25,                                          │
│          "incorrect": 3,                                         │
│          "unattempted": 2,                                       │
│          "details": [...]                                        │
│        }                                                         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: Google Sheets Integration                              │
│  ──────────────────────────────                                  │
│  1. User provides Google Sheets link (student list)              │
│  2. Read sheet → get columns: Entry Number, Name, Marks          │
│  3. For each scored student:                                     │
│     a. Find row by entry_number match                            │
│     b. Optionally verify name match                              │
│     c. Write score to the Marks column                           │
│  4. Return summary of updates                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Detailed Implementation Plan

### Phase 1: Enhanced Drive Ingestion

**File:** `services/drive_service.py`

#### Changes:
1. **`list_all_files_in_folder(folder_id)`** — New method that lists ALL files (not just images)
   - Remove the `mimeType contains 'image/'` filter
   - Return full metadata including `mimeType`, `name`, `id`, `webContentLink`

2. **`identify_answer_key(files_list)`** — New method
   - Scan file names for pattern: file name contains `"answer_key"` (case-insensitive)
   - Return the matching file(s) separately from student answer sheets
   - Supported formats to look for:
     - CSV (`.csv`)
     - Excel (`.xlsx`, `.xls`)  
     - PDF (`.pdf`)
     - Images (`.png`, `.jpg`, `.jpeg`)
     - Word (`.docx`)
     - Google Sheets (mimeType = `application/vnd.google-apps.spreadsheet`)

3. **`download_file_as_export(file_id, mime_type, destination)`** — New method for Google Docs Editors files
   - Google Sheets → export as CSV
   - Google Docs → export as PDF

#### Separation Logic:
```python
def separate_files(files):
    answer_key_files = []
    student_sheets = []
    for f in files:
        if "answer_key" in f["name"].lower():
            answer_key_files.append(f)
        else:
            student_sheets.append(f)
    return answer_key_files, student_sheets
```

---

### Phase 2A: Answer Key Extraction Service

**New File:** `services/answer_key_service.py`

This is the core new service. It handles parsing the answer key from any supported format.

#### Class: `AnswerKeyService`

```python
class AnswerKeyService:
    def extract_answer_key(self, file_path: str, mime_type: str) -> dict:
        """
        Routes to the appropriate parser based on file type.
        Returns a normalized answer key dict.
        """
        
    def _parse_csv(self, file_path: str) -> dict:
        """Parse CSV file with columns: question_number, correct_option, marks"""
        
    def _parse_excel(self, file_path: str) -> dict:
        """Parse XLSX/XLS file"""
        
    def _parse_pdf(self, file_path: str) -> dict:
        """Use OCR + LLM to extract answer key from PDF"""
        
    def _parse_image(self, file_path: str) -> dict:
        """Use OCR to extract answer key from image"""
        
    def _parse_with_ocr(self, file_path: str) -> dict:
        """Common OCR extraction logic for PDF/images with a special prompt"""
```

#### The Static Answer Key Object:

```python
# Data class / TypedDict for the answer key
class AnswerKey:
    total_questions: int
    answers: Dict[int, AnswerKeyEntry]  # {1: {"correct_option": "A", "marks": 1}}
    negative_marking: float  # marks deducted per wrong answer (0 = no negative)
    metadata: Dict  # source file, extraction timestamp, etc.

class AnswerKeyEntry:
    correct_option: str
    marks: float
```

#### Expected Answer Key File Formats:

| Format | Expected Structure |
|---|---|
| CSV | `question_number,correct_option,marks` (header row + data) |
| XLSX | Same columns as CSV |
| PDF/Image | A table or list: `Q1: A`, `Q2: B`, etc. — parsed via OCR+LLM |
| Google Sheet | Exported as CSV, then parsed |

---

### Phase 2B: Enhanced OCR Prompt for Objective Sheets

**File:** `services/ocr_service.py`

#### Changes:
- Add a new method `extract_objective_sheet(image_path)` with a **specialized prompt** for objective answer sheets:

```python
def _get_objective_prompt(self):
    return """
    This is an OBJECTIVE answer sheet (MCQ/OMR style).
    Extract ONLY the following and return as valid JSON:
    
    1. "entry_number": The student's entry/roll number
    2. "name": The student's name 
    3. "answers": A dictionary mapping question_number (int) to marked_option (string)
       Example: {"1": "A", "2": "C", "3": "B", ...}
    
    Rules:
    - Question numbers should be integers
    - Options should be single uppercase letters (A, B, C, D)
    - If a question appears unanswered/blank, DO NOT include it
    - If multiple options are marked for a question, mark it as "MULTIPLE"
    
    Return ONLY valid JSON, no markdown formatting.
    """
```

---

### Phase 2C: Scoring Function

**File:** `services/evaluation_service.py`

#### New Function: `match_and_score(answer_key: dict, student_answers: dict) -> dict`

```python
def match_and_score(answer_key: dict, student_answers: dict) -> dict:
    """
    Pure function — no LLM needed, just matching.
    
    Args:
        answer_key: The static answer key object
            {
                "answers": {1: {"correct_option": "A", "marks": 1}, ...},
                "negative_marking": 0.25
            }
        student_answers: Extracted from OCR
            {
                "entry_number": "2023CSE001",
                "name": "Harsh",
                "answers": {1: "A", 2: "B", ...}
            }
    
    Returns:
        {
            "entry_number": "2023CSE001",
            "name": "Harsh",
            "total_score": 25.0,
            "max_score": 30.0,
            "correct": 25,
            "incorrect": 3,
            "unattempted": 2,
            "negative_deduction": 0.75,
            "details": [
                {"q": 1, "marked": "A", "correct": "A", "result": "correct", "score": 1},
                {"q": 2, "marked": "B", "correct": "C", "result": "incorrect", "score": -0.25},
                ...
            ]
        }
    """
```

This is deliberately a **pure function** — it takes in static data and returns a result, making it easy to test and debug.

---

### Phase 3: Google Sheets Integration

**New File:** `services/sheets_service.py`

#### Dependencies:
- `gspread` (Python library for Google Sheets API)
- OR raw `googleapiclient` (already in requirements)

#### Class: `SheetsService`

```python
class SheetsService:
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',  # Read+Write
    ]
    
    def __init__(self, credentials_path: str = "credentials.json"):
        """Initialize with service account credentials"""
        
    def read_student_list(self, sheet_url: str) -> List[Dict]:
        """
        Reads the Google Sheet and returns student list.
        
        Expected columns: Entry Number | Name | Marks
        (Column names are flexible — will auto-detect)
        
        Returns: [
            {"row": 2, "entry_number": "2023CSE001", "name": "Harsh", "marks": None},
            ...
        ]
        """
        
    def update_marks(self, sheet_url: str, results: List[Dict]) -> Dict:
        """
        For each result, finds the student row by entry_number and writes score.
        
        Args:
            results: [
                {"entry_number": "2023CSE001", "total_score": 25, "max_score": 30},
                ...
            ]
        
        Returns:
            {
                "updated": 28,
                "not_found": ["2023CSE045"],  # entry numbers not in sheet
                "mismatches": [...]  # name mismatches for manual review
            }
        """
    
    def _parse_sheet_url(self, url: str) -> tuple:
        """Extract spreadsheet ID and optional sheet name from URL"""
        
    def _detect_columns(self, header_row: list) -> dict:
        """
        Auto-detect which columns contain entry_number, name, marks.
        Uses fuzzy matching on column headers.
        """
```

#### Column Detection Logic:
```python
ENTRY_NUMBER_ALIASES = ["entry number", "entry_number", "entry no", "roll number", 
                         "roll no", "roll_number", "enrollment", "id", "student id"]
NAME_ALIASES = ["name", "student name", "student_name", "full name"]
MARKS_ALIASES = ["marks", "score", "total", "grade", "result", "total marks"]
```

---

### API Endpoints (Updated)

**File:** `api/endpoints.py`

#### New / Modified Endpoints:

```python
# ── Phase 1 ──
@router.post("/process-drive-folder")
def process_drive_folder(folder_url: str):
    """
    Main entry point. Given a Drive folder URL:
    1. Lists all files
    2. Separates answer key from student sheets
    3. Extracts & stores the answer key
    4. Processes each student sheet
    5. Returns all scores
    """

# ── Phase 2 ──
@router.get("/answer-key")
def get_current_answer_key():
    """Returns the currently loaded answer key"""

@router.post("/answer-key/upload")
def upload_answer_key(file: UploadFile):
    """Manual upload of answer key (alternative to Drive extraction)"""

# ── Phase 3 ──
@router.post("/export-to-sheets")
def export_to_sheets(sheet_url: str):
    """
    Takes a Google Sheets URL. Reads student list, matches with
    evaluation results by entry_number, writes marks.
    """

@router.post("/full-pipeline")
def run_full_pipeline(drive_folder_url: str, sheets_url: str):
    """
    One-click pipeline:
    Drive folder → Extract answer key → OCR all sheets → 
    Score all → Write to Google Sheets
    """
```

---

## 📁 File Structure After Implementation

```
backend/
├── api/
│   └── endpoints.py              # Updated with new routes
├── services/
│   ├── drive_service.py          # Enhanced (list all files, export Google Sheets)
│   ├── ocr_service.py            # Enhanced (objective sheet prompt)
│   ├── evaluation_service.py     # Enhanced (match_and_score pure function)
│   ├── answer_key_service.py     # NEW — parse answer key from any format
│   ├── sheets_service.py         # NEW — read/write Google Sheets
│   └── ...
├── models.py                     # Enhanced with AnswerKey, StudentResult models
├── database.py                   # Enhanced (store answer keys, batch results)
├── main.py
├── requirements.txt              # Add: gspread, openpyxl, pandas, PyPDF2
└── .env
```

---

## 📦 New Dependencies

```
gspread          # Google Sheets API wrapper (simpler than raw API)
openpyxl         # Excel file parsing
pandas           # CSV/XLSX parsing
PyPDF2           # PDF text extraction (for simple key files)
```

---

## 🔧 Implementation Order

| Step | Task | Depends On |
|------|------|------------|
| 1 | Create `AnswerKey` and `StudentResult` pydantic models | — |
| 2 | Create `answer_key_service.py` with CSV/XLSX/image/PDF parsers | Models |
| 3 | Update `drive_service.py` to list all files + identify answer key | — |
| 4 | Add `extract_objective_sheet()` to `ocr_service.py` | — |
| 5 | Add `match_and_score()` pure function to `evaluation_service.py` | Models |
| 6 | Create `sheets_service.py` | — |
| 7 | Wire up new endpoints in `endpoints.py` | Steps 1-6 |
| 8 | Update `requirements.txt` | — |
| 9 | Test end-to-end with sample data | Steps 1-7 |

---

## ⚠️ Edge Cases to Handle

1. **OCR misreads option** — e.g., "B" read as "8" → normalization layer
2. **Multiple marked options** → flag as "MULTIPLE", score 0
3. **Entry number not in sheet** → add to `not_found` list
4. **Name mismatch** → fuzzy match with threshold, flag if uncertain
5. **Answer key has variable marks** → support per-question mark allocation
6. **Negative marking** → configurable per exam
7. **Google Sheets permission** → service account needs Editor access to the sheet
8. **Large folders** → pagination in Drive API (currently limited to 100 files)
9. **Mixed file types in folder** → only process image/PDF files as answer sheets
10. **Answer key not found** → return clear error, don't process sheets

---

## 🧪 Testing Strategy

1. **Unit tests** for `match_and_score()` — pure function, easy to test
2. **Unit tests** for answer key parsers — provide sample CSV/XLSX files
3. **Integration test** with a real Drive folder (small, 3-5 sheets)
4. **Mock OCR responses** for endpoint tests
5. **Google Sheets sandbox** for write tests
