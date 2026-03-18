import os
import requests
import base64
import json
import re

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
            parsed = self._parse_json(extracted_text)

            if "error" in parsed:
                return parsed

            # Normalize the output
            return self._normalize_objective_output(parsed)

        except Exception as e:
            print(f"❌ Objective sheet extraction failed: {e}")
            return {"error": str(e)}

    def _get_objective_prompt(self):
        return """
You are analyzing an OBJECTIVE answer sheet (MCQ/OMR style) that may contain different question types.

Extract ONLY the following fields and return as valid JSON (no markdown):

{
    "entry_number": "the student's entry/roll number",
    "name": "the student's name",
    "answers": {
        "1": "A",
        "2": "C",
        "3": "AC",
        "4": "2.5",
        ...
    },
    "comments": "Any observations about the sheet: e.g. 'Damage on corner', 'Q5 ambiguous', 'Name unclear', 'Erasures detected'. If clean, return null."
}

Rules:
- "entry_number": Look for roll number, entry number, enrollment number, registration number, student ID, etc.
- "name": The student's name as written on the sheet.
- "answers": A dictionary mapping question number (as string) to the marked answer.
  
Answer formats by question type:
- Single MCQ (SMCQ): Single letter like "A", "B", "C", "D"
- Multiple MCQ (MMCQ): Multiple letters like "AC", "BCD", "AB" (no spaces)
- Numerical (NCQ): Numbers like "2.5", "7.0", "15"

General rules:
- If a question appears unanswered or blank, DO NOT include it in answers.
- If multiple options are marked for a single-choice question, set the value to "MULTIPLE".
- For multiple-choice questions, combine all marked letters (e.g., if A and C are marked, use "AC").
- For numerical answers, include decimal points if present (e.g., "2.5" not "2").
- Question numbers must be integers represented as strings.
- If entry_number or name is not found, set to null.

Return ONLY valid JSON, no explanation, no markdown.
"""

    def _normalize_objective_output(self, parsed: dict) -> dict:
        """Normalize OCR output to the expected format for match_and_score()."""
        result = {
            "entry_number": parsed.get("entry_number") or parsed.get("roll_number") or "unknown",
            "name": parsed.get("name") or parsed.get("student_name") or "unknown",
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

