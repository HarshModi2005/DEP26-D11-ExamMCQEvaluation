import os
import google.generativeai as genai
import json
import re
import requests
import time
from typing import List, Dict, Any
from models import AnswerKey, StudentResult, QuestionResult


class EvaluationService:

    # ──────────────────────────────────────────
    #  Pure Scoring Function (no LLM needed)
    # ──────────────────────────────────────────

    @staticmethod
    def match_and_score(answer_key: AnswerKey, student_answers: Dict) -> StudentResult:
        """
        Pure function — matches student answers against the answer key and returns a score.
        
        Args:
            answer_key: AnswerKey model.
            student_answers: Dict from OCR extraction:
                {
                    "entry_number": "...",
                    "name": "...",
                    "answers": {1: "A", ...},
                    "comments": "erasure on Q5"  (optional)
                }
        """
        entry_number = str(student_answers.get("entry_number", "")).strip()
        name = str(student_answers.get("name", "")).strip()
        raw_answers = student_answers.get("answers", {})
        
        # Aggregate comments
        comments_list = []
        if student_answers.get("comments"):
            c = str(student_answers["comments"]).strip()
            if c and c.lower() != "none" and c.lower() != "null":
                comments_list.append(c)

        # Normalize student answers
        student_ans = {}
        for k, v in raw_answers.items():
            try:
                q_num = int(k)
                option = EvaluationService._normalize_student_answer(str(v))
                # Apply answer-key-aware sanitization if question type is known
                key_entry = answer_key.answers.get(q_num)
                if key_entry and option and option not in EvaluationService.UNATTEMPTED_MARKERS:
                    option = EvaluationService._sanitize_by_question_type(
                        option, key_entry.question_type.strip().upper()
                    )
                student_ans[q_num] = option
            except (ValueError, TypeError):
                continue

        total_score = 0.0
        max_score = 0.0
        correct_count = 0
        incorrect_count = 0
        unattempted_count = 0
        negative_deduction = 0.0
        details = []

        # Iterate strictly over answer key questions
        for q_num, key_entry in answer_key.answers.items():
            correct_answer = key_entry.correct_answer.strip().upper()
            question_type = key_entry.question_type
            positive_marks = key_entry.positive_marks
            negative_marks = key_entry.negative_marks or answer_key.negative_marking
            
            max_score += positive_marks

            if q_num in student_ans:
                marked = student_ans[q_num]

                # Check if student marked "X" — treat as unattempted (no negative)
                if marked in ('X', 'x', 'NONE', '-', 'NA', 'N/A'):
                    unattempted_count += 1
                    details.append(QuestionResult(
                        question_number=q_num,
                        marked=marked,
                        correct=correct_answer,
                        result="unattempted",
                        score=0.0
                    ))

                elif marked == "MULTIPLE":
                    # Multiple options marked -> Incorrect
                    incorrect_count += 1
                    negative_deduction += negative_marks
                    total_score -= negative_marks
                    details.append(QuestionResult(
                        question_number=q_num,
                        marked=marked,
                        correct=correct_answer,
                        result="multiple",
                        score=-negative_marks
                    ))
                    comments_list.append(f"Q{q_num}: Multiple marks")
                
                elif EvaluationService._is_answer_correct(marked, correct_answer, question_type):
                    correct_count += 1
                    total_score += positive_marks
                    details.append(QuestionResult(
                        question_number=q_num,
                        marked=marked,
                        correct=correct_answer,
                        result="correct",
                        score=positive_marks
                    ))
                
                else:
                    incorrect_count += 1
                    negative_deduction += negative_marks
                    total_score -= negative_marks
                    details.append(QuestionResult(
                        question_number=q_num,
                        marked=marked,
                        correct=correct_answer,
                        result="incorrect",
                        score=-negative_marks
                    ))
            else:
                unattempted_count += 1
                details.append(QuestionResult(
                    question_number=q_num,
                    marked=None,
                    correct=correct_answer,
                    result="unattempted",
                    score=0.0
                ))

        # Sort details by question number
        details.sort(key=lambda d: d.question_number)

        return StudentResult(
            entry_number=entry_number,
            name=name,
            total_score=total_score,  # Allow negative scores
            max_score=max_score,
            correct_count=correct_count,
            incorrect_count=incorrect_count,
            unattempted_count=unattempted_count,
            negative_deduction=negative_deduction,
            details=details,
            comments="; ".join(comments_list) if comments_list else ""
        )

    # Patterns that indicate an unattempted question
    UNATTEMPTED_MARKERS = frozenset({'X', 'NONE', '-', 'NA', 'N/A', 'BLANK', 'NOT ATTEMPTED', 'UNATTEMPTED'})

    @staticmethod
    def _normalize_student_answer(raw: str) -> str:
        """
        Normalize a student's raw OCR answer to extract just the option letter(s).
        
        Handles patterns like:
          - "A"           → "A"
          - "Option A"    → "A"  
          - "1 (A)"       → "A"
          - "(A)"         → "A"
          - "A)"          → "A"
          - "ANS 1 (A) 3" → "A"
          - "X"           → "X" (unattempted marker)
          - "MULTIPLE"    → "MULTIPLE"
          - "2.5"         → "2.5" (numerical answer, kept as-is)
        """
        option = raw.strip().upper()
        if not option:
            return option
        
        # Preserve special markers
        if option in ('MULTIPLE', 'X', 'NONE', '-', 'NA', 'N/A', 'BLANK',
                       'NOT ATTEMPTED', 'UNATTEMPTED'):
            return option
        
        # Strip "OPTION" prefix
        if "OPTION" in option:
            option = option.replace("OPTION", "").strip()
        
        # Strip "ANS" / "ANSWER" prefix
        option = re.sub(r'^(?:ANS(?:WER)?)[\s.:)\-]*', '', option).strip()
        
        # Try to extract letter(s) from parenthesized patterns:
        #   "1 (A)", "(A)", "1(A)3", "ANS 1 (A) 3", "Q1 (B)"
        paren_match = re.search(r'\(\s*([A-Da-d]+)\s*\)', option)
        if paren_match:
            return paren_match.group(1).upper()
        
        # Pattern: "A)" or "1 A)" — option letter followed by closing paren
        close_paren = re.search(r'(?:^|\s)([A-Da-d])\s*\)', option)
        if close_paren:
            return close_paren.group(1).upper()
        
        # Pattern: digit(s) followed by space(s) then a single letter: "1 A", "12 B"
        # But NOT if it looks like a numerical answer (e.g. "2.5")
        num_letter = re.match(r'^\d+[\s.,:;\-]+([A-Da-d])\s*$', option)
        if num_letter:
            return num_letter.group(1).upper()
        
        # Pattern: just digits with optional decimal — numerical answer, keep as-is
        if re.match(r'^[\-]?\d+\.?\d*$', option):
            return option
        
        # Pattern: single letter possibly with trailing noise: "A 3", "B 1"
        single_letter = re.match(r'^([A-Da-d])(?:\s+\d+)?\s*$', option)
        if single_letter:
            return single_letter.group(1).upper()
        
        # Final cleanup: strip any non-alphanumeric except period (for NCQ)
        cleaned = re.sub(r'[^A-Za-z0-9.]', '', option).upper()
        return cleaned if cleaned else option

    # Digit-to-letter OCR confusion map (when OCR reads a number instead of a letter)
    OCR_DIGIT_TO_LETTER = {
        '0': 'O', '1': 'I', '2': 'Z', '3': 'E',
        '4': 'A', '5': 'S', '6': 'G', '7': 'T',
        '8': 'B', '9': 'G',
    }

    # Letter-to-digit OCR confusion map (when OCR reads a letter instead of a number)
    # Used for NCQ (Numerical Choice Questions) where the answer should be a number.
    OCR_LETTER_TO_DIGIT = {
        'O': '0', 'o': '0', 'D': '0',          # O/o/D → 0
        'l': '1', 'L': '1', 'I': '1', 'i': '1', # l/L/I/i → 1
        'Z': '2', 'z': '2',                     # Z → 2
        'S': '5', 's': '5',                     # S → 5
        'G': '6', 'g': '6', 'b': '6', 'B': '6', # G/g/b/B → 6  (NOTE: B→6 not B→8 because
                                                  # 6/B confusion is more common in handwriting
                                                  # for NCQ answers. For MCQ, _ocr_correct_mcq_answer
                                                  # uses B→8 which is the right mapping there.)
        'q': '9',                                # q → 9
    }

    @staticmethod
    def _ocr_correct_mcq_answer(answer: str) -> str:
        """
        If the OCR'd answer is a digit and could be a letter that OCR misread,
        map it to the likely letter. Only applies to single-char digit answers.
        Does NOT do letter-to-letter fuzzy matching.
        """
        if len(answer) == 1 and answer.isdigit():
            return EvaluationService.OCR_DIGIT_TO_LETTER.get(answer, answer)
        # For multi-char answers (MMCQ), correct each digit char but leave letters as-is
        if any(c.isdigit() for c in answer) and not answer.replace('.', '').replace('-', '').isdigit():
            # Mixed digits+letters — correct digits that sit among letters
            corrected = []
            for c in answer:
                if c.isdigit():
                    corrected.append(EvaluationService.OCR_DIGIT_TO_LETTER.get(c, c))
                else:
                    corrected.append(c)
            return ''.join(corrected)
        return answer

    @staticmethod
    def _ocr_correct_ncq_answer(answer: str) -> str:
        """
        Apply OCR letter→digit corrections for numerical (NCQ) answers.
        
        Handles common OCR confusions where the model reads a number as letters:
          - "GOO" → "600"  (G→6, O→0)
          - "l000" → "1000" (l→1)
          - "6OO" → "600"  (O→0)
          - "boo" → "600"  (b→6, o→0)
          - "S76" → "576"  (S→5)
        """
        # Strip spaces, commas, and other noise
        cleaned = re.sub(r'[\s,]+', '', answer)
        
        # If it's already a valid number, return as-is
        try:
            float(cleaned)
            return cleaned
        except ValueError:
            pass
        
        # Apply letter→digit corrections
        corrected = []
        for c in cleaned:
            if c in EvaluationService.OCR_LETTER_TO_DIGIT:
                corrected.append(EvaluationService.OCR_LETTER_TO_DIGIT[c])
            elif c.isdigit() or c in ('.', '-', '+'):
                corrected.append(c)
            else:
                corrected.append(c)  # keep unknown chars
        result = ''.join(corrected)
        
        # Try parsing the corrected result
        try:
            float(result)
            return result
        except ValueError:
            return answer  # couldn't fix it, return original

    @staticmethod
    def _clean_mmcq_answer(answer: str) -> str:
        """
        Clean MMCQ answer: extract only A-D letters, sort, deduplicate.
        Handles OCR artifacts like spaces, periods, dashes between letters:
          - "B CD" → "BCD"
          - "A, C, D" → "ACD"
          - "B.C.D" → "BCD"
        """
        # Extract only A-D letters
        letters = set()
        for c in answer.upper():
            if c in 'ABCD':
                letters.add(c)
        return ''.join(sorted(letters)) if letters else answer

    # ─────────────────────────────────────────────────
    #  MCQ-specific: digit/letter → valid ABCD option
    # ─────────────────────────────────────────────────
    # In MCQ context (only A–D valid), different corrections apply vs. generic
    # digit→letter. E.g. '3' in general OCR maps to 'E', but 'E' isn't a valid
    # option — the real confusion is B↔3 (mirror image in handwriting).
    MCQ_DIGIT_TO_OPTION = {
        '0': 'D',  # 0 → round → D
        '1': 'A',  # 1 → vertical stroke → A (contextual)
        '3': 'B',  # 3 mirrored = B (classic handwriting confusion)
        '4': 'A',  # 4 → A (triangle/pointed shape)
        '5': 'C',  # 5 → S → curved → C (best ABCD match for rounded char)
        '6': 'C',  # 6 → open curve → C
        '8': 'B',  # 8 → B (classic confusion)
        '9': 'D',  # 9 → round bottom → D
    }

    # Non-ABCD letter → closest valid ABCD option
    MCQ_LETTER_TO_OPTION = {
        'E': 'B',  # E ↔ B (horizontal bars; 3→E→B chain)
        'G': 'C',  # G ↔ C (open curve)
        'I': 'A',  # I → 1 → A (vertical stroke context)
        'O': 'D',  # O ↔ D (round shape)
        'P': 'B',  # P → half-circle top like B
        'Q': 'D',  # Q → round like D
        'R': 'B',  # R → vertical + bowl like B
        'S': 'C',  # S → curved like C
        'T': 'A',  # T → 7 → pointed/angular → A
        'Z': 'D',  # Z → 2 → fallback; rare
    }

    @staticmethod
    def _sanitize_by_question_type(answer: str, question_type: str) -> str:
        """
        Sanitize a student answer based on the expected question type.

        For MCQ (SMCQ/MMCQ):  ensure answer only contains valid options A-D.
          - Digits → MCQ_DIGIT_TO_OPTION (e.g. '8' → 'B', '3' → 'B')
          - Non-ABCD letters → MCQ_LETTER_TO_OPTION (e.g. 'E' → 'B')

        For NCQ:  ensure answer is numeric.
          - Letters → OCR_LETTER_TO_DIGIT (e.g. 'O' → '0', 'S' → '5')
          - Strip remaining non-numeric characters.
        """
        if not answer:
            return answer

        # Preserve special markers
        if answer in EvaluationService.UNATTEMPTED_MARKERS or answer == 'MULTIPLE':
            return answer

        q_type = question_type.upper().strip()

        if q_type == 'SMCQ':
            ans = answer.strip().upper()
            # Already a valid option?
            if ans in 'ABCD' and len(ans) == 1:
                return ans
            # Single digit → MCQ digit→option map
            if len(ans) == 1 and ans.isdigit():
                return EvaluationService.MCQ_DIGIT_TO_OPTION.get(ans, ans)
            # Single non-ABCD letter → MCQ letter→option map
            if len(ans) == 1 and ans.isalpha():
                return EvaluationService.MCQ_LETTER_TO_OPTION.get(ans, ans)
            # Multi-char — try to extract a single valid option
            for c in ans:
                if c in 'ABCD':
                    return c
            # Still nothing — try digit→option on first char
            if ans and ans[0].isdigit():
                return EvaluationService.MCQ_DIGIT_TO_OPTION.get(ans[0], ans)
            return ans

        elif q_type == 'MMCQ':
            ans = answer.strip().upper()
            result_letters = set()
            for c in ans:
                if c in 'ABCD':
                    result_letters.add(c)
                elif c.isdigit() and c in EvaluationService.MCQ_DIGIT_TO_OPTION:
                    result_letters.add(EvaluationService.MCQ_DIGIT_TO_OPTION[c])
                elif c.isalpha() and c in EvaluationService.MCQ_LETTER_TO_OPTION:
                    result_letters.add(EvaluationService.MCQ_LETTER_TO_OPTION[c])
            return ''.join(sorted(result_letters)) if result_letters else answer

        elif q_type == 'NCQ':
            # Apply letter→digit OCR correction
            corrected = EvaluationService._ocr_correct_ncq_answer(answer)
            # If that produced a valid number, use it
            try:
                float(corrected)
                return corrected
            except ValueError:
                pass
            # Strip non-numeric chars as fallback
            digits_only = re.sub(r'[^0-9.\-+]', '', answer)
            if digits_only:
                try:
                    float(digits_only)
                    return digits_only
                except ValueError:
                    pass
            return corrected  # return best-effort

        # Unknown question type — no sanitization
        return answer

    @staticmethod
    def _is_answer_correct(student_answer: str, correct_answer: str, question_type: str) -> bool:
        """
        Check if student answer matches correct answer based on question type.
        Applies OCR digit-to-letter correction for MCQ types (SMCQ, MMCQ).
        Does NOT use fuzzy matching between letters -- only digit→letter correction.
        
        Args:
            student_answer: What the student marked
            correct_answer: The correct answer from answer key
            question_type: SMCQ, MMCQ, or NCQ
        """
        if not student_answer or not correct_answer:
            return False
            
        student_answer = student_answer.strip().upper()
        correct_answer = correct_answer.strip().upper()
        
        if question_type == "SMCQ":
            # Exact match first
            if student_answer == correct_answer:
                return True
            # OCR digit-to-letter correction (e.g., '8' → 'B')
            corrected = EvaluationService._ocr_correct_mcq_answer(student_answer)
            return corrected == correct_answer
            
        elif question_type == "MMCQ":
            # Clean and sort both answers: extract only A-D letters
            student_cleaned = EvaluationService._clean_mmcq_answer(student_answer)
            correct_cleaned = EvaluationService._clean_mmcq_answer(correct_answer)
            if student_cleaned == correct_cleaned:
                return True
            # Try OCR digit-to-letter correction on original
            corrected = EvaluationService._ocr_correct_mcq_answer(student_answer)
            corrected_cleaned = EvaluationService._clean_mmcq_answer(corrected)
            return corrected_cleaned == correct_cleaned
            
        elif question_type == "NCQ":
            # Numerical Choice Question — multi-stage matching:
            # 1. Direct float comparison
            # 2. OCR letter→digit corrected float comparison
            # 3. Normalized string comparison
            correct_val = None
            try:
                correct_val = float(correct_answer)
            except ValueError:
                pass
            
            # Stage 1: Direct float parse
            try:
                student_val = float(student_answer)
                if correct_val is not None and abs(student_val - correct_val) < 1e-6:
                    return True
            except ValueError:
                pass
            
            # Stage 2: Apply OCR letter→digit correction, then try float
            corrected = EvaluationService._ocr_correct_ncq_answer(student_answer)
            try:
                corrected_val = float(corrected)
                if correct_val is not None and abs(corrected_val - correct_val) < 1e-6:
                    return True
            except ValueError:
                pass
            
            # Stage 3: Normalized string comparison (strip leading zeros, spaces)
            student_norm = re.sub(r'[\s,]+', '', student_answer).lstrip('0') or '0'
            correct_norm = re.sub(r'[\s,]+', '', correct_answer).lstrip('0') or '0'
            if student_norm == correct_norm:
                return True
            
            # Stage 4: Corrected string comparison
            corrected_norm = re.sub(r'[\s,]+', '', corrected).lstrip('0') or '0'
            if corrected_norm == correct_norm:
                return True
            
            # Stage 5: Strip all non-digit chars from student answer (handles "6M" → "6")
            # Only accept if resulting digits match correct answer after stripping too
            digits_only = re.sub(r'[^0-9.\-+]', '', student_answer)
            if digits_only:
                try:
                    digits_val = float(digits_only)
                    if correct_val is not None and abs(digits_val - correct_val) < 1e-6:
                        return True
                except ValueError:
                    pass
            
            return False
                
        else:
            # Unknown question type, default to exact match
            return student_answer == correct_answer

    def __init__(self, api_key: str = None, provider: str = None):
        """
        Initialize evaluation service with smart provider selection.
        """
        self.provider = provider or os.getenv("LLM_PROVIDER", "auto").lower()
        self.active_provider = None
        self.active_model_name = None
        
        self.gemini_key = os.getenv("GOOGLE_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY") # NEW
        
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"

        # Candidates
        self.gemini_candidates = [
            "gemini-2.5-flash",
            "gemini-3.1-flash",
            "gemini-3.1-pro",
            "gemini-3.0-flash",
            "gemini-1.5-flash"
        ]
        
        self.groq_candidates = [
            "llama-4-70b-chat", # Assumed later version in 2026
            "llama-3.3-70b-versatile",
            "llama3-70b-8192"
        ]
        
        self.openrouter_candidates = [
            "google/gemini-2.0-flash-lite-001",
            "google/gemini-2.0-flash-001",
            "google/gemini-2.0-pro-exp-02-05:free"
        ]

        # Env overrides
        env_gemini = os.getenv("GEMINI_MODEL")
        if env_gemini:
            self.gemini_candidates.insert(0, env_gemini)
            
        env_openrouter = os.getenv("OPENROUTER_MODEL")
        if env_openrouter:
            self.openrouter_candidates.insert(0, env_openrouter)

        self._select_best_provider()

    def _select_best_provider(self):
        print("Selecting best LLM provider (Evaluation)...")
        # 1. Gemini
        if self.gemini_key and (self.provider == "gemini" or self.provider == "auto"):
            genai.configure(api_key=self.gemini_key)
            for model_name in self.gemini_candidates:
                if self._test_gemini(model_name):
                    self.active_provider = "gemini"
                    self.active_model_name = model_name
                    self.model = genai.GenerativeModel(model_name)
                    print(f"✅ Selected Gemini model: {model_name}")
                    return

        # 2. Groq (Fastest)
        if self.groq_key and (self.provider == "groq" or self.provider == "auto"):
            for model_name in self.groq_candidates:
                if self._test_groq(model_name):
                    self.active_provider = "groq"
                    self.active_model_name = model_name
                    print(f"✅ Selected Groq model: {model_name}")
                    return

        # 3. OpenRouter
        if self.openrouter_key and (self.provider == "openrouter" or self.provider == "auto"):
            for model_name in self.openrouter_candidates:
                if self._test_openrouter(model_name):
                    self.active_provider = "openrouter"
                    self.active_model_name = model_name
                    print(f"✅ Selected OpenRouter model: {model_name}")
                    return
        
        # Fallback
        self.active_provider = "gemini"
        self.active_model_name = "gemini-2.5-flash"
        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel("gemini-2.5-flash")

    def _test_gemini(self, model_name):
        return True

    def _test_groq(self, model_name):
        return True

    def _test_openrouter(self, model_name):
        return True



    def evaluate_objective(self, student_answers: List[Dict], answer_key: List[Dict]):
        """
        Evaluates objective answers (MCQ).
        
        Args:
            student_answers: List of dicts, e.g., [{'question_number': 1, 'marked_option': 'A'}, ...]
            answer_key: List of dicts, e.g., [{'question_number': 1, 'correct_option': 'A', 'marks': 1}, ...]
            
        Returns:
            Dict containing total score, max score, and detailed breakdown.
        """
        results = {
            "total_score": 0,
            "max_score": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "unattempted_count": 0,
            "details": []
        }
        
        # Convert key to easier lookup: {1: {'correct_option': 'A', 'marks': 1}}
        key_map = {item['question_number']: item for item in answer_key}
        
        # Track which questions were attempted
        attempted_q_nums = set()
        
        for ans in student_answers:
            q_num = ans.get('question_number')
            # Handle cases where OCR might return "Option A" or just "A"
            marked_raw = str(ans.get('marked_option', ''))
            marked = marked_raw.strip().upper()
            # aggressive normalization if needed, e.g. taking first char if generic word found
            if len(marked) > 1 and "OPTION" in marked:
                 marked = marked.replace("OPTION", "").strip()
            
            if q_num in key_map:
                attempted_q_nums.add(q_num)
                correct_opt = str(key_map[q_num].get('correct_option', '')).strip().upper()
                marks = key_map[q_num].get('marks', 1)
                
                is_correct = (marked == correct_opt)
                score = marks if is_correct else 0
                
                if is_correct:
                    results['correct_count'] += 1
                else:
                    results['incorrect_count'] += 1
                
                results['total_score'] += score
                
                results['details'].append({
                    "question_number": q_num,
                    "type": "objective",
                    "marked": marked,
                    "correct": correct_opt,
                    "is_correct": is_correct,
                    "score": score
                })
        
        # Calculate max score and check for unattempted
        for q_num, key_data in key_map.items():
            results['max_score'] += key_data.get('marks', 1)
            if q_num not in attempted_q_nums:
                results['unattempted_count'] += 1
                results['details'].append({
                    "question_number": q_num,
                    "type": "objective",
                    "marked": None,
                    "correct": key_data.get('correct_option', '').strip().upper(),
                    "is_correct": False,
                    "score": 0,
                    "status": "unattempted"
                })

        return results

    def _call_llm(self, prompt: str) -> str:
        """
        Unified method to call LLM regardless of provider.
        """
        try:
            if self.active_provider == "gemini":
                response = self.model.generate_content(prompt)
                return response.text
            
            elif self.active_provider == "groq":
                headers = {
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": self.active_model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}
                }
                response = requests.post(self.groq_url, headers=headers, json=data, timeout=30)
                response.raise_for_status()
                return response.json()['choices'][0]['message']['content']
            
            elif self.active_provider == "openrouter":
                headers = {
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": self.active_model_name,
                    "messages": [{"role": "user", "content": prompt}]
                }
                response = requests.post(self.openrouter_url, headers=headers, json=data, timeout=30)
                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content']
                
        except Exception as e:
            print(f"Primary call failed: {e}. Trying fallback...")
            
            # Fallback Chain: Try Groq -> OpenRouter -> Gemini (excluding current)
            if self.active_provider != "groq" and self.groq_key:
                try:
                    print("Falling back to Groq...")
                    self.active_provider = "groq"
                    self.active_model_name = self.groq_candidates[0]
                    return self._call_llm(prompt)
                except: pass
                
            if self.active_provider != "openrouter" and self.openrouter_key:
                try:
                     print("Falling back to OpenRouter...")
                     self.active_provider = "openrouter"
                     self.active_model_name = self.openrouter_candidates[0]
                     return self._call_llm(prompt)
                except: pass
            
            raise e


    def evaluate_subjective(self, student_answers: List[Dict], answer_key_map: Dict):
        """
        Evaluates subjective answers using LLM.
        """
        results = {
            "total_score": 0,
            "max_score": 0,
            "details": []
        }

        if not self.active_provider:
            print(f"Warning: No valid LLM Provider initialized")
            return results

        for ans in student_answers:
            q_num = ans.get('question_number')
            student_text = ans.get('answer_text', '')
            
            if q_num in answer_key_map:
                key_data = answer_key_map[q_num]
                ideal_answer = key_data.get('ideal_answer', '')
                max_marks = key_data.get('marks', 5)
                rubric = key_data.get('rubric', 'Award marks based on accuracy and completeness.')
                
                results['max_score'] += max_marks
                
                # LLM Prompt for Grading
                prompt = f"""
You are an expert strict examiner. Grade the following student answer based on the ideal answer and rubric.

Question Number: {q_num}
Max Marks: {max_marks}

Ideal Answer: "{ideal_answer}"
Rubric/Key Points: "{rubric}"

Student Answer: "{student_text}"

Task:
1. Assign a score out of {max_marks} (can be float, e.g. 2.5).
2. Provide brief feedback justifying the score.

Return ONLY a valid JSON object:
{{
    "score": <float>,
    "feedback": "<string>"
}}
                """
                
                try:
                    response_text = self._call_llm(prompt)
                    cleaned_text = re.sub(r'```json\s*|\s*```', '', response_text).strip()
                    # Try to find JSON block if mixed with text
                    match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
                    if match:
                        cleaned_text = match.group()
                    
                    grading = json.loads(cleaned_text)
                    score = float(grading.get('score', 0))
                    feedback = grading.get('feedback', '')
                    
                    # Cap score at max_marks just in case
                    score = min(score, max_marks)
                    
                    results['total_score'] += score
                    results['details'].append({
                        "question_number": q_num,
                        "type": "subjective",
                        "marked": student_text,
                        "correct": ideal_answer, # Or 'See Feedback'
                        "score": score,
                        "feedback": feedback
                    })
                    
                except Exception as e:
                    print(f"Error grading subjective Q{q_num}: {e}")
                    results['details'].append({
                        "question_number": q_num,
                        "type": "subjective",
                        "error": "Grading failed",
                        "score": 0
                    })
        
        return results


