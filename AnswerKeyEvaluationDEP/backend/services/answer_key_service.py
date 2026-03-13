"""
Answer Key Service
==================
Parses answer keys from multiple file formats (CSV, XLSX, PDF, Images)
and normalizes them into a static AnswerKey object.
"""

import os
import re
import json
import csv
import base64
import requests
from typing import Dict, Optional
from models import AnswerKey, AnswerKeyEntry
from google.oauth2 import service_account
import google.auth.transport.requests
import google.auth

class AnswerKeyService:
    def __init__(self):
        self.project_id = "project-75abf07c-e594-4660-ab7"
        self.location = "us-central1"
        self.model_id = "gemini-2.5-flash-lite"
        self.creds = None
        
        # Try finding Service Account credentials
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path and os.path.exists(creds_path):
            try:
                self.creds = service_account.Credentials.from_service_account_file(
                    creds_path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                if hasattr(self.creds, "project_id") and self.creds.project_id:
                     self.project_id = self.creds.project_id
            except Exception as e:
                print(f"⚠️ Failed to load Service Account in AnswerKeyService: {e}")

        self.vertex_api_key = os.getenv("VERTEX_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        # Construct URL
        if self.creds:
             self.vertex_url = (
                f"https://{self.location}-aiplatform.googleapis.com/v1/"
                f"projects/{self.project_id}/locations/{self.location}/"
                f"publishers/google/models/{self.model_id}:streamGenerateContent"
             )
        elif self.vertex_api_key:
             self.vertex_url = (
                f"https://aiplatform.googleapis.com/v1/publishers/google/models/"
                f"{self.model_id}:streamGenerateContent?key={self.vertex_api_key}"
             )
        else:
            self.vertex_url = None
            print("⚠️  VERTEX_AI_API_KEY not set and no Service Account found — OCR-based answer key parsing won't work")

    def _get_auth_header(self):
        """Get Authorization header with Bearer token if using Service Account."""
        if self.creds:
            try:
                auth_req = google.auth.transport.requests.Request()
                self.creds.refresh(auth_req)
                return {"Authorization": f"Bearer {self.creds.token}", "Content-Type": "application/json"}
            except Exception as e:
                print(f"❌ Failed to refresh token: {e}")
                return {"Content-Type": "application/json"} 
        return {"Content-Type": "application/json"}

    # ──────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────

    def extract_answer_key(self, file_path: str, mime_type: str = None) -> AnswerKey:
        """
        Main entry point. Detects format and routes to the right parser.
        
        Args:
            file_path: Local path to the downloaded answer key file.
            mime_type: Optional MIME type hint from Drive.
            
        Returns:
            AnswerKey object with all answers normalized.
            
        Raises:
            ValueError: If the file format is unsupported or parsing fails.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Answer key file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        print(f"📋 Parsing answer key: {os.path.basename(file_path)} (ext={ext}, mime={mime_type})")

        # Route by extension first, then MIME type as fallback
        if ext == ".csv" or mime_type == "text/csv":
            raw = self._parse_csv(file_path)
        elif ext in (".xlsx", ".xls") or (mime_type and "spreadsheet" in mime_type):
            raw = self._parse_excel(file_path)
        elif ext == ".pdf" or mime_type == "application/pdf":
            raw = self._parse_with_ocr(file_path, mime_type="application/pdf")
        elif ext in (".png", ".jpg", ".jpeg") or (mime_type and "image/" in mime_type):
            raw = self._parse_with_ocr(file_path, mime_type=mime_type)
        elif ext == ".docx":
            raw = self._parse_docx(file_path)
        elif ext == ".txt":
            raw = self._parse_text(file_path)
        else:
            raise ValueError(
                f"Unsupported answer key format: ext={ext}, mime={mime_type}. "
                f"Supported: .csv, .xlsx, .xls, .pdf, .png, .jpg, .jpeg, .docx, .txt"
            )

        # Normalize raw dict → AnswerKey model
        answer_key = self._normalize(raw, source_file=os.path.basename(file_path))
        print(f"✅ Answer key extracted: {answer_key.total_questions} questions")
        
        # PERSISTENCE: Save to disk automatically
        self.save_to_disk(answer_key)
        
        return answer_key

    def save_to_disk(self, answer_key: AnswerKey, filename: str = "current_answer_key.json"):
        """Save the AnswerKey object to a JSON file."""
        try:
            with open(filename, 'w') as f:
                f.write(answer_key.model_dump_json(indent=2))
            print(f"💾 Saved answer key to {filename}")
        except Exception as e:
            print(f"⚠️ Failed to save answer key to disk: {e}")

    def load_from_disk(self, filename: str = "current_answer_key.json") -> Optional[AnswerKey]:
        """Load the AnswerKey object from a JSON file."""
        if not os.path.exists(filename):
            return None
        
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            # Reconstruct Dictionary with integer keys for answers
            answers_data = data.get("answers", {})
            converted_answers = {}
            for k, v in answers_data.items():
                converted_answers[int(k)] = AnswerKeyEntry(**v)
            
            return AnswerKey(
                total_questions=data["total_questions"],
                answers=converted_answers,
                metadata=data.get("metadata", {})
            )
        except Exception as e:
            print(f"⚠️ Failed to load answer key from disk: {e}")
            return None

    # ──────────────────────────────────────────
    #  Format-Specific Parsers
    # ──────────────────────────────────────────

    def _parse_csv(self, file_path: str) -> Dict:
        """
        Parse CSV with expected columns: question_number, correct_option, marks (optional)
        
        Also handles simpler formats:
        - Two columns: question_number, correct_option
        - Single column with "Q1: A" style entries
        """
        answers = {}

        with open(file_path, 'r', encoding='utf-8-sig') as f:
            # Sniff the dialect
            sample = f.read(2048)
            f.seek(0)
            
            # Try standard CSV parsing
            try:
                sniffer = csv.Sniffer()
                has_header = sniffer.has_header(sample)
            except csv.Error:
                has_header = True  # assume header

            reader = csv.reader(f)
            headers = None

            if has_header:
                headers = [h.strip().lower() for h in next(reader)]

            # Detect column indices
            q_col, type_col, pos_col, neg_col, opt_col = self._detect_excel_columns(headers)

            for idx, row in enumerate(reader, start=2 if has_header else 1):
                if not row or all(cell.strip() == '' for cell in row):
                    continue

                try:
                    if q_col is not None and opt_col is not None:
                        q_num = self._parse_question_number(row[q_col].strip())
                        option = row[opt_col].strip().upper()
                        
                        q_type = "SMCQ"
                        if type_col is not None and type_col < len(row) and row[type_col].strip():
                            q_type = str(row[type_col]).strip().upper()

                        pos_marks = 1.0
                        if pos_col is not None and pos_col < len(row) and row[pos_col].strip():
                            try: pos_marks = float(row[pos_col].strip())
                            except: pass

                        neg_marks = 0.0
                        if neg_col is not None and neg_col < len(row) and row[neg_col].strip():
                            try: neg_marks = float(row[neg_col].strip())
                            except: pass
                            
                        answers[q_num] = {
                            "type": q_type, 
                            "correct_option": option, 
                            "positive_marks": pos_marks, 
                            "negative_marks": neg_marks
                        }
                    else:
                        # Try to parse "Q1: A" style from first column
                        parsed = self._parse_inline_answer(row[0])
                        if parsed:
                            answers[parsed[0]] = {
                                "type": "SMCQ",
                                "correct_option": parsed[1], 
                                "positive_marks": 1.0,
                                "negative_marks": 0.0
                            }
                except (ValueError, IndexError) as e:
                    print(f"  ⚠️  Skipping row {row}: {e}")
                    continue

        if not answers:
            raise ValueError(f"No answers could be parsed from CSV: {file_path}")

        return {"answers": answers}

    def _parse_excel(self, file_path: str) -> Dict:
        """Parse XLSX/XLS file using openpyxl."""
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl is required for Excel parsing. Run: pip install openpyxl")

        wb = openpyxl.load_workbook(file_path, read_only=True)
        ws = wb.active
        answers = {}

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError(f"Empty Excel file: {file_path}")

        # Check if first row is header
        first_row = [str(cell).strip().lower() if cell else '' for cell in rows[0]]
        header_keywords = {'question', 'q', 'number', 'option', 'answer', 'correct', 'marks'}
        has_header = any(kw in cell for cell in first_row for kw in header_keywords)

        start_idx = 1 if has_header else 0
        headers = first_row if has_header else None

        q_col, type_col, pos_col, neg_col, opt_col = self._detect_excel_columns(headers)
        # Default column positions if detection fails
        if q_col is None: q_col = 0
        if type_col is None: type_col = 1
        if pos_col is None: pos_col = 2
        if neg_col is None: neg_col = 3
        if opt_col is None: opt_col = 4

        for row in rows[start_idx:]:
            if not row or all(cell is None for cell in row):
                continue
            try:
                # Ensure we have enough columns gracefully
                val_q    = str(row[q_col]).strip()    if q_col    is not None and q_col    < len(row) else ""
                val_type = str(row[type_col]).strip().upper() if type_col is not None and type_col < len(row) else "SMCQ"
                val_pos  = str(row[pos_col]).strip()  if pos_col  is not None and pos_col  < len(row) else "1.0"
                val_neg  = str(row[neg_col]).strip()  if neg_col  is not None and neg_col  < len(row) else "0.0"
                val_opt  = str(row[opt_col]).strip().upper() if opt_col is not None and opt_col < len(row) else ""

                if not val_q or not val_opt:
                    continue

                q_num = self._parse_question_number(val_q)
                option = val_opt
                
                pos_marks = 1.0
                if val_pos:
                    try: pos_marks = float(val_pos)
                    except: pass
                    
                neg_marks = 0.0
                if val_neg:
                    try: neg_marks = float(val_neg)
                    except: pass

                answers[q_num] = {
                    "type": val_type,
                    "correct_option": option,
                    "positive_marks": pos_marks,
                    "negative_marks": neg_marks
                }
            except (ValueError, IndexError):
                continue

        wb.close()

        if not answers:
            raise ValueError(f"No answers could be parsed from Excel: {file_path}")

        return {"answers": answers}

    def _parse_docx(self, file_path: str) -> Dict:
        """Parse DOCX by extracting text and using pattern matching."""
        try:
            import docx
        except ImportError:
            # Fallback to OCR-based approach
            print("  python-docx not installed, falling back to OCR")
            return self._parse_with_ocr(file_path, mime_type="application/pdf")

        doc = docx.Document(file_path)
        full_text = "\n".join([para.text for para in doc.paragraphs])

        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = "\t".join(cell.text for cell in row.cells)
                full_text += "\n" + row_text

        return self._parse_text_content(full_text)

    def _parse_text(self, file_path: str) -> Dict:
        """Parse plain text answer key."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return self._parse_text_content(content)

    def _parse_text_content(self, text: str) -> Dict:
        """
        Parse free-form text that contains answers like:
        - Q1: A
        - 1. B
        - Question 1 - C
        - 1) D
        """
        answers = {}
        lines = text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue
            parsed = self._parse_inline_answer(line)
            if parsed:
                q_num, option = parsed
                answers[q_num] = {
                    "type": "SMCQ",
                    "correct_option": option, 
                    "positive_marks": 1.0, 
                    "negative_marks": 0.0
                }

        if not answers:
            raise ValueError("No answers could be parsed from text content")

        return {"answers": answers}

    def _parse_with_ocr(self, file_path: str, mime_type: str = None) -> Dict:
        """
        Use OCR (Vertex AI Gemini) to extract answer key from PDF or image.
        Sends the file with a specialized prompt asking for structured JSON output.
        """
        if not self.vertex_url:
            raise ValueError("VERTEX_AI_API_KEY not set — cannot use OCR for answer key parsing")

        # Encode file
        with open(file_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')

        # Detect mime type
        if not mime_type:
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {
                '.pdf': 'application/pdf',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
            }
            mime_type = mime_map.get(ext, 'image/png')

        prompt = self._get_answer_key_ocr_prompt()

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": file_data
                            }
                        }
                    ]
                }
            ]
        }

        try:
            headers = self._get_auth_header()
            response = requests.post(
                self.vertex_url,
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            extracted_text = self._parse_streaming_response(result)
            parsed = self._extract_json(extracted_text)

            if "answers" not in parsed:
                raise ValueError(f"OCR response missing 'answers' field: {extracted_text[:300]}")

            return parsed

        except requests.RequestException as e:
            raise ValueError(f"OCR API request failed: {e}")

    # ──────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────

    def _detect_excel_columns(self, headers: list) -> tuple:
        """Detect question_number, type, positive_marks, negative_marks, and option from headers."""
        if not headers:
            return 0, 1, 2, 3, 4

        q_col = type_col = pos_col = neg_col = opt_col = None

        q_kw = {'question', 'q', 'number', 'q_no'}
        type_kw = {'type'}
        pos_kw = {'positive', 'marks', 'score'}
        neg_kw = {'negative'}
        opt_kw = {'correct', 'option', 'answer', 'key'}

        for idx, header in enumerate(headers):
            h = header.lower().strip()
            if q_col is None and any(k in h for k in q_kw): q_col = idx
            elif type_col is None and any(k in h for k in type_kw): type_col = idx
            elif pos_col is None and any(k in h for k in pos_kw) and 'negative' not in h: pos_col = idx
            elif neg_col is None and any(k in h for k in neg_kw): neg_col = idx
            elif opt_col is None and any(k in h for k in opt_kw): opt_col = idx

        return q_col, type_col, pos_col, neg_col, opt_col

    def _parse_question_number(self, text: str) -> int:
        """Extract integer question number from text like 'Q1', '1.', 'Question 1', '1'"""
        # Remove common prefixes
        cleaned = re.sub(r'^(question|q|no|s\.?no\.?)\s*[.:\-)\s]*', '', text, flags=re.IGNORECASE)
        cleaned = cleaned.strip().rstrip('.):')

        try:
            return int(cleaned)
        except ValueError:
            # Try to find any integer in the text
            match = re.search(r'\d+', text)
            if match:
                return int(match.group())
            raise ValueError(f"Cannot parse question number from: '{text}'")

    def _parse_inline_answer(self, line: str) -> Optional[tuple]:
        """
        Parse a line like:
        'Q1: A', '1. B', 'Question 1 - C', '1) D', '1    A'
        
        Returns: (question_number: int, option: str) or None
        """
        # Pattern: optional prefix (Q/Question) + number + separator + option letter
        patterns = [
            r'(?:question|q)?\.?\s*(\d+)\s*[.:)\-–—\t]+\s*([A-Da-d])\b',
            r'(\d+)\s+([A-Da-d])\s*$',  # Just "1  A"
        ]
        for pattern in patterns:
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match:
                q_num = int(match.group(1))
                option = match.group(2).upper()
                return (q_num, option)
        return None

    def _normalize(self, raw: Dict, source_file: str = "") -> AnswerKey:
        """Convert raw parsed dict to AnswerKey model. Also handles strict format validation."""
        raw_answers = raw.get("answers", {})
        answers = {}
        validation_errors = []

        for key, value in raw_answers.items():
            q_num = int(key)
            if isinstance(value, dict):
                q_type = str(value.get("type", "SMCQ")).strip().upper()
                option = str(value.get("correct_option", "")).strip().upper()
                pos_marks = float(value.get("positive_marks", 1.0))
                neg_marks = float(value.get("negative_marks", 0.0))
            elif isinstance(value, str):
                q_type = "SMCQ"
                option = value.strip().upper()
                pos_marks = 1.0
                neg_marks = 0.0
            else:
                continue
                
            # Perform validation based on Type
            if q_type == "SMCQ":
                if not option or len(option) != 1 or not option.isalpha():
                    validation_errors.append(f"Row {q_num}: Invalid answer '{option}' for SMCQ. Expected a single alphabet character.")
                else:
                    answers[q_num] = AnswerKeyEntry(type=q_type, correct_option=option, positive_marks=pos_marks, negative_marks=neg_marks)
            
            elif q_type == "MMCQ":
                if not option or not bool(re.search(r'[A-Za-z]', option)):
                     validation_errors.append(f"Row {q_num}: Invalid answer '{option}' for MMCQ. Expected multiple alphabetical options.")
                else:
                    answers[q_num] = AnswerKeyEntry(type=q_type, correct_option=option, positive_marks=pos_marks, negative_marks=neg_marks)
            
            elif q_type == "NCQ":
                try:
                    # Strip standard NCQ answers to float
                    float(re.sub(r'[^0-9.-]', '', str(option)))
                    answers[q_num] = AnswerKeyEntry(type=q_type, correct_option=option, positive_marks=pos_marks, negative_marks=neg_marks)
                except ValueError:
                    validation_errors.append(f"Row {q_num}: Invalid answer '{option}' for NCQ. Expected a numerical/decimal value.")
            
            else:
                validation_errors.append(f"Row {q_num}: Unknown Question Type '{q_type}'. Expected SMCQ, MMCQ, or NCQ.")

        if validation_errors:
            error_msg = "; ".join(validation_errors)
            raise ValueError(f"Format Validation Errors:\n{error_msg}")

        if not answers:
            raise ValueError("No valid answers found after normalization")

        return AnswerKey(
            total_questions=len(answers),
            answers=answers,
            metadata={
                "source_file": source_file,
                "raw_question_count": len(raw_answers),
                "parsed_question_count": len(answers),
            }
        )

    def _get_answer_key_ocr_prompt(self) -> str:
        return """
You are analyzing an ANSWER KEY document for an objective/MCQ examination.

Extract ALL question numbers and their correct options. Be mindful of three possible formats: SMCQ (Single Choice), MMCQ (Multiple Choice), and NCQ (Numerical).
Return ONLY a valid JSON object (no markdown):

{
    "answers": {
        "1": {"type": "SMCQ", "correct_option": "A", "positive_marks": 1.0, "negative_marks": 0.0},
        "2": {"type": "SMCQ", "correct_option": "C", "positive_marks": 1.0, "negative_marks": 0.0},
        "3": {"type": "MMCQ", "correct_option": "A,B,C", "positive_marks": 4.0, "negative_marks": 1.0},
        "4": {"type": "NCQ", "correct_option": "4.15", "positive_marks": 3.0, "negative_marks": 0.0},
        ...
    }
}

Rules:
- Question numbers must be integers (as strings in the JSON keys)
- 'type' should be one of SMCQ, MMCQ, or NCQ.
- If positive/negative marks per question are visible, include them; otherwise default to 1.0 positive, 0.0 negative.
- Include ALL questions visible in the document
- Return ONLY the JSON object, no explanation text
"""

    def _parse_streaming_response(self, result) -> str:
        """Parse streaming response from Vertex AI."""
        all_text = []
        if isinstance(result, list):
            for chunk in result:
                if "candidates" in chunk:
                    for candidate in chunk["candidates"]:
                        if "content" in candidate and "parts" in candidate["content"]:
                            for part in candidate["content"]["parts"]:
                                if "text" in part:
                                    all_text.append(part["text"])
        elif isinstance(result, dict):
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                all_text.append(part["text"])
        return "".join(all_text)

    def _extract_json(self, text: str) -> Dict:
        """Extract JSON from text, handling markdown fences."""
        cleaned = re.sub(r'```json\s*|\s*```', '', text).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"Failed to parse JSON from OCR response: {text[:300]}")
