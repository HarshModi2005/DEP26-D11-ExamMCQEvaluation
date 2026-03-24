import os
import requests
import base64
import json
import re
import logging

logger = logging.getLogger(__name__)

class OCRService:
    def __init__(self, api_key: str = None, provider: str = None):
        """
        Initialize OCR service with Google Workspace Gemini 3.1 Flash Lite.
        """
        from google.oauth2 import service_account
        import google.auth.transport.requests
        import google.auth
        
        self.project_id = "project-75abf07c-e594-4660-ab7"
        self.location = "us-central1"
        self.model_id = "gemini-2.5-flash"
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
                print(f"⚠️ Failed to load Service Account in OCRService: {e}")

        self.vertex_api_key = api_key or os.getenv("VERTEX_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
        if self.creds:
             self.vertex_url = (
                f"https://{self.location}-aiplatform.googleapis.com/v1/"
                f"projects/{self.project_id}/locations/{self.location}/"
                f"publishers/google/models/{self.model_id}:streamGenerateContent"
             )
        elif self.vertex_api_key:
            # Use generativelanguage endpoint if using Google AI Studio API Key
             self.vertex_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:streamGenerateContent?key={self.vertex_api_key}"
        else:
            self.vertex_url = None
            print("⚠️ WARNING: Neither Service Account nor API_KEY found. OCR features will be disabled.")
            
        print(f"✅ OCR Service initialized (has_creds={bool(self.creds)})")

    def _get_auth_header(self):
        """Get Authorization header with Bearer token if using Service Account."""
        import google.auth.transport.requests
        if self.creds:
            try:
                auth_req = google.auth.transport.requests.Request()
                self.creds.refresh(auth_req)
                return {"Authorization": f"Bearer {self.creds.token}", "Content-Type": "application/json"}
            except Exception as e:
                print(f"❌ Failed to refresh token: {e}")
                return {"Content-Type": "application/json"} 
        return {"Content-Type": "application/json"}

    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def extract_data(self, image_path: str):
        """
        Extracts student info using Vertex AI Gemini 2.5 Flash Lite.
        """
        if not os.path.exists(image_path):
            return {"error": f"File not found: {image_path}"}

        print(f"Processing image with Vertex AI: {image_path}")
        
        try:
            # Encode image
            base64_image = self._encode_image(image_path)
            
            # Determine mime type
            mime_type = "image/png"
            if image_path.lower().endswith(('.jpg', '.jpeg')):
                mime_type = "image/jpeg"
            
            # Prepare request
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": self._get_prompt()
                            },
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_image
                                }
                            }
                        ]
                    }
                ]
            }
            
            headers = self._get_auth_header()
            
            # Make request
            response = requests.post(self.vertex_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            # Parse streaming response
            result = response.json()
            extracted_text = self._parse_streaming_response(result)
            
            # Parse JSON from extracted text
            return self._parse_json(extracted_text)
            
        except Exception as e:
            print(f"Vertex AI extraction failed: {e}")
            return {"error": str(e)}

    def _parse_streaming_response(self, result):
        """Parse streaming response from Vertex AI"""
        all_text = []
        
        # Handle both single object and array of objects
        if isinstance(result, list):
            # Streaming response - array of chunks
            for chunk in result:
                if "candidates" in chunk:
                    for candidate in chunk["candidates"]:
                        if "content" in candidate and "parts" in candidate["content"]:
                            for part in candidate["content"]["parts"]:
                                if "text" in part:
                                    all_text.append(part["text"])
        elif isinstance(result, dict):
            # Single response object
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                all_text.append(part["text"])
        
        return "".join(all_text)

    def _get_prompt(self):
        return """
        Analyze this answer sheet image. 
        Extract the following fields and return ONLY a valid JSON object. Do not format as markdown.
        
        Fields to extract:
        1. "student_name": The name of the student if written.
        2. "roll_number": The roll number/ID.
        3. "exam_code": Any exam code or subject code if visible.
        4. "objective_answers": A list of objects for MCQ/One-word answers, containing:
           - "question_number": (integer)
           - "marked_option": (string, e.g., "A", "B", "C", "D" or the handwritten text)
        5. "subjective_answers": A list of objects for descriptive answers, containing:
           - "question_number": (integer)
           - "answer_text": (string, the full handwritten text of the answer)
        
        If a specific field is not found, set it to null or empty list.
        Ensure the JSON is valid and properly formatted.
        """

    def _parse_json(self, text):
        """Parse JSON from text, handling markdown code blocks"""
        # Remove markdown code blocks
        cleaned_text = re.sub(r'```json\s*|\s*```', '', text).strip()
        
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            # Try to find JSON object in text
            match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            
            # If all else fails, return error
            return {
                "error": "Failed to parse JSON from response",
                "raw_response": text[:500]
            }

    # ──────────────────────────────────────
    #  Objective Sheet Extraction
    # ──────────────────────────────────────

    def extract_objective_sheet(self, image_path: str) -> dict:
        """
        Specialized extraction for OBJECTIVE answer sheets.

        Returns a dict ready for match_and_score():
            {
                "entry_number": "2023CSE001",
                "name": "Harsh",
                "answers": {"1": "A", "2": "C", "3": "B", ...}
            }
        """
        if not os.path.exists(image_path):
            return {"error": f"File not found: {image_path}"}

        print(f"📝 Processing objective sheet: {image_path}")
        logger.info(f"[OCR] Starting extraction for: {image_path}")

        try:
            base64_image = self._encode_image(image_path)

            mime_type = "image/png"
            if image_path.lower().endswith(('.jpg', '.jpeg')):
                mime_type = "image/jpeg"
            elif image_path.lower().endswith('.pdf'):
                mime_type = "application/pdf"

            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": self._get_objective_prompt()},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_image
                                }
                            }
                        ]
                    }
                ]
            }

            headers = self._get_auth_header()
            response = requests.post(
                self.vertex_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            result = response.json()
            extracted_text = self._parse_streaming_response(result)

            # ── LOG 1: raw model output ───────────────────────────────────
            logger.info(f"[OCR] Raw model text for {os.path.basename(image_path)}:\n{extracted_text[:800]}")
            print(f"  📋 Raw OCR text:\n{extracted_text[:600]}")

            cleaned = re.sub(r'```json\s*|\s*```', '', extracted_text).strip()
            parsed = None
            parse_error = None

            # ── LOG 2: JSON parse attempt ─────────────────────────────────
            try:
                parsed = json.loads(cleaned)
                logger.info(f"[OCR] JSON parse OK — keys: {list(parsed.keys())}")
            except json.JSONDecodeError as je:
                parse_error = str(je)
                logger.warning(f"[OCR] JSON parse FAILED ({je}), trying regex extraction")
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                        logger.info(f"[OCR] Regex JSON extraction OK — keys: {list(parsed.keys())}")
                    except json.JSONDecodeError as je2:
                        logger.error(f"[OCR] Regex JSON extraction also FAILED: {je2}")
                        return {"error": f"Parse failed: {je2}", "raw_response": extracted_text[:500]}
                else:
                    logger.error("[OCR] No JSON object found in model output at all")
                    return {"error": "No JSON found in model response", "raw_response": extracted_text[:500]}

            if "error" in parsed:
                logger.warning(f"[OCR] Model returned error field: {parsed['error']}")
                return parsed

            # ── LOG 3: raw field values before normalization ───────────────
            raw_entry = parsed.get("entry_number") or parsed.get("roll_number") or ""
            raw_name  = parsed.get("name") or parsed.get("student_name") or ""
            raw_answers = parsed.get("answers", {})
            logger.info(
                f"[OCR] Pre-norm → entry='{raw_entry}' name='{raw_name}' "
                f"answer_count={len(raw_answers) if isinstance(raw_answers, dict) else 'list:'+str(len(raw_answers))}"
            )
            print(
                f"  🔍 OCR extracted: entry='{raw_entry}' | name='{raw_name}' | "
                f"answers ({len(raw_answers) if isinstance(raw_answers, dict) else len(raw_answers)} qs): "
                f"{dict(list(raw_answers.items())[:5]) if isinstance(raw_answers, dict) else raw_answers[:5]}"
            )

            # ── LOG 4: common format-related diagnosis ────────────────────
            if not raw_entry:
                logger.warning(
                    "[OCR] ⚠️  entry_number is EMPTY — common causes:\n"
                    "  • 'Entry No.' label + value written on same line at bottom of question section\n"
                    "  • Entry number has spaces (e.g. 'B21 CSB 1001') which confused the model\n"
                    "  • Model returned it under a different key (e.g. 'roll_number', 'id')\n"
                    f"  • All keys in parsed JSON: {list(parsed.keys())}"
                )
                print(f"  ⚠️  No entry_number found! All OCR keys: {list(parsed.keys())}")
            if not raw_name:
                logger.warning(
                    "[OCR] ⚠️  name is EMPTY — the model may have missed 'Name -' label\n"
                    f"  • All keys in parsed JSON: {list(parsed.keys())}"
                )
            if isinstance(raw_answers, dict) and len(raw_answers) == 0:
                logger.warning(
                    "[OCR] ⚠️  answers dict is EMPTY — common causes:\n"
                    "  • Two-column answer grid (1-5 left, 6-10 right) not parsed correctly\n"
                    "  • Model returned answers under a different key (e.g. 'objective_answers')\n"
                    f"  • All keys in parsed JSON: {list(parsed.keys())}"
                )

            # Normalize the output
            normalized = self._normalize_objective_output(parsed)

            # ── LOG 5: final normalized result ────────────────────────────
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
            return {"error": str(e)}


    def _get_objective_prompt(self):
        return """
You are analyzing a student OBJECTIVE answer sheet. The sheet has a specific layout:
- The TOP section contains printed questions (Q1 to Q10 or similar).
- Below the questions, near the BOTTOM of the question block, there is a "Name" field and an "Entry No." field written by the student — look for them carefully even if they are on the same line or have labels like "Name -" or "Entry No.-".
- Below that is an ANSWER GRID with question numbers (1, 2, 3...) and the student's handwritten answers.
- The answer grid may be in TWO COLUMNS (e.g., questions 1-5 on the left and 6-10 on the right).

Extract the following and return ONLY valid JSON (no markdown, no explanation):

{
    "entry_number": "the student's entry/roll number exactly as written (e.g. '2021CSB1001' or 'B21 CSB 1001' — DO NOT normalize or remove spaces)",
    "name": "the student's name as written",
    "answers": {
        "1": "A",
        "2": "C",
        "3": "AC",
        "4": "2.5",
        ...
    },
    "comments": "Any observations about the sheet quality or ambiguities. null if clean."
}

Rules for answers:
- Scan BOTH columns of the answer grid. Do not miss the right column.
- Single MCQ: one letter e.g. "A", "B", "C", "D"
- Multiple MCQ: concatenated letters e.g. "AC", "BCD"
- Numerical: include decimals e.g. "2.5", "7.0"
- If a question is blank/unanswered, OMIT it from answers (do not include it at all).
- If multiple options are circled for a SINGLE-choice question, use "MULTIPLE".
- Question numbers MUST be strings ("1", "2", ...), not integers.

For entry_number:
- Look for a field labelled "Entry No.", "Entry Number", "Roll No.", "Enrollment No.", or similar.
- It is usually written near the student's name, often in the format YYYY<branch><number> e.g. "2021CSB1001" or with spaces like "B21 CSB 1001".
- Return it EXACTLY as written by the student, including spaces.
- If not found, return null.

Return ONLY the JSON object.
"""

    def _normalize_objective_output(self, parsed: dict) -> dict:
        """Normalize OCR output to the expected format for match_and_score()."""
        result = {
            "entry_number": parsed.get("entry_number") or parsed.get("roll_number") or "",
            "name": parsed.get("name") or parsed.get("student_name") or "",
            "comments": parsed.get("comments") or "",
            "answers": {}
        }

        # Handle answers in different possible formats
        raw_answers = parsed.get("answers", {})

        if isinstance(raw_answers, dict):
            # Already a dict — normalize keys and values
            for k, v in raw_answers.items():
                try:
                    q_num = str(int(k))
                    option = str(v).strip().upper()
                    if "OPTION" in option:
                        option = option.replace("OPTION", "").strip()
                    result["answers"][q_num] = option
                except (ValueError, TypeError):
                    continue

        elif isinstance(raw_answers, list):
            # List of dicts like [{"question_number": 1, "marked_option": "A"}, ...]
            for item in raw_answers:
                if isinstance(item, dict):
                    q_num = item.get("question_number")
                    option = item.get("marked_option") or item.get("option") or item.get("answer")
                    if q_num is not None and option:
                        result["answers"][str(int(q_num))] = str(option).strip().upper()

        return result

