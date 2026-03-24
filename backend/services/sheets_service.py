"""
Google Sheets Service
=====================
Reads student lists from Google Sheets and writes marks back.
Entry numbers are matched using the pattern yyyyBBBnnnn (e.g. 2023CSB1122).
Names are cross-verified — mismatches are flagged but marks are still written.
Supports writing 'comments' if a column is present.
Supports writing per-question marks if columns like '1', 'Q1', '2', 'Q2' are present.
"""

import os
import re
import difflib
import statistics as stats_module
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import List, Dict, Optional, Tuple, Any


class SheetsService:
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',  # Read + Write
    ]

    # Aliases for auto-detecting column headers
    ENTRY_NUMBER_ALIASES = {
        'entry number', 'entry_number', 'entry no', 'entry no.',
        'roll number', 'roll_number', 'roll no', 'roll no.',
        'enrollment', 'enrollment number', 'enrollment numbers', 'enrollment no',
        'id', 'student id', 'student_id', 'reg number',
        'registration number', 'reg no', 'reg no.',
    }

    NAME_ALIASES = {
        'name', 'names', 'student name', 'student_name', 'full name',
        'full_name', 'candidate name',
    }

    MARKS_ALIASES = {
        'marks', 'mark', 'score', 'total', 'grade', 'result',
        'total marks', 'total_marks', 'total score', 'total_score',
        'obtained marks', 'obtained_marks', 'marks obtained',
    }
    
    COMMENTS_ALIASES = {
        'comments', 'comment', 'remarks', 'remark', 'feedback', 'notes',
        'observation', 'observations', 'issues', 'issue'
    }

    # Regex for entry number format: yyyyBBBnnnn (e.g. 2023CSB1122)
    ENTRY_NUMBER_PATTERN = re.compile(
        r'(\d{4})\s*([A-Za-z]{2,4})\s*(\d{2,5})',
    )
    
    # Regex for question columns: "1", "Q1", "Q 1", "Question 1", "1a" (if simple digit)
    # We will support simple integers for now as per current pipeline.
    # Regex for question columns: 1, Q1, Q.1, Q-1, Question 1
    QUESTION_COLUMN_PATTERN = re.compile(
        r'^(?:q|ques|question)?[\s\.\-\_]*(\d+)$', 
        re.IGNORECASE
    )

    def __init__(self, credentials_path: str = "credentials.json"):
        self.creds = None
        self.service = None

        # Try to load credentials
        if not os.path.exists(credentials_path):
            env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if env_path and os.path.exists(env_path):
                credentials_path = env_path

        if os.path.exists(credentials_path):
            try:
                self.creds = service_account.Credentials.from_service_account_file(
                    credentials_path, scopes=self.SCOPES
                )
                self.service = build('sheets', 'v4', credentials=self.creds)
                print("Sheets Service: Initialized with Service Account")
            except Exception as e:
                print(f"Sheets Service: Error loading credentials: {e}")
        else:
            print(f"Sheets Service: No credentials found at {credentials_path}")

    # ──────────────────────────────────────
    #  URL Parsing
    # ──────────────────────────────────────

    @staticmethod
    def parse_sheet_url(url: str) -> Tuple[str, Optional[str]]:
        """
        Extract spreadsheet ID and optional sheet name/GID from URL.
        """
        spreadsheet_id = url
        sheet_name = None

        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if match:
            spreadsheet_id = match.group(1)

        return spreadsheet_id, sheet_name

    # ──────────────────────────────────────
    #  OCR-Aware Smart Matching System
    # ──────────────────────────────────────

    # Groups of characters that OCR commonly swaps
    OCR_CONFUSABLE_GROUPS = [
        frozenset('0ODQo'),       # zero, O, D, Q, lowercase-o
        frozenset('1IlL|!i'),     # one, I, l, L, pipe, exclamation, lowercase-i
        frozenset('5S$s'),        # five, S, dollar, lowercase-s
        frozenset('8B&'),         # eight, B, ampersand
        frozenset('2Zz'),         # two, Z, lowercase-z
        frozenset('6Gb'),         # six, G, lowercase-b (round shape)
        frozenset('9gq'),         # nine, g, q
        frozenset('UVuv'),        # U, V and lowercase
        frozenset('CcG('),        # C, c, G, open-paren
        frozenset('4A'),          # four looks like A in some fonts
        frozenset('7T'),          # seven looks like T
        frozenset('3E'),          # three looks like E (reversed)
        frozenset('Pp'),          # P, p
        frozenset('Kk'),          # K, k
        frozenset('Ww'),          # W, w
        frozenset('Ff'),          # F, f
        frozenset('Yy'),          # Y, y
        frozenset('Xx'),          # X, x
        frozenset('Hh'),          # H, h — OCR sometimes swaps case
        frozenset('Mm'),          # M, m
        frozenset('Nn'),          # N, n
        frozenset('Rr'),          # R, r
    ]

    # Digit-to-letter confusions for MCQ answer correction (number OCR'd instead of letter)
    # e.g. OCR reads '8' but student actually bubbled 'B'
    OCR_DIGIT_TO_LETTER = {
        '0': 'O', '1': 'I', '2': 'Z', '3': 'E',
        '4': 'A', '5': 'S', '6': 'G', '7': 'T',
        '8': 'B', '9': 'G',
    }

    @classmethod
    def _normalize_entry_number(cls, raw: str) -> Optional[str]:
        """Normalize to YYYYBBBNNNN."""
        if not raw or raw.lower() in ('unknown', 'none', 'n/a', ''):
            return None

        clean = raw.strip()
        m = cls.ENTRY_NUMBER_PATTERN.search(clean)
        if m:
            year = m.group(1)
            branch = m.group(2).upper()
            number = m.group(3)
            return f"{year}{branch}{number}"

        fallback = re.sub(r'[\s\-_./]', '', clean).upper()
        if len(fallback) >= 6:
            return fallback
        return None

    @classmethod
    def _ocr_canonicalize(cls, text: str) -> str:
        """
        Canonicalize a string for OCR-robust comparison.
        Maps all confusable characters to a canonical representative.
        """
        result = []
        for ch in text.upper():
            canonical = ch
            for group in cls.OCR_CONFUSABLE_GROUPS:
                if ch in group:
                    canonical = sorted(group)[0]  # Pick lowest char as canonical
                    break
            result.append(canonical)
        return ''.join(result)

    @classmethod
    def _levenshtein_distance(cls, s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            return cls._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Substitutions cost 0 if chars are OCR-confusable
                if c1 == c2:
                    sub_cost = 0
                elif cls._are_ocr_confusable(c1, c2):
                    sub_cost = 0.3  # Low cost for OCR-common confusions
                else:
                    sub_cost = 1
                curr_row.append(min(
                    curr_row[-1] + 1,           # insertion
                    prev_row[j + 1] + 1,        # deletion
                    prev_row[j] + sub_cost       # substitution
                ))
            prev_row = curr_row
        return prev_row[-1]

    @classmethod
    def _are_ocr_confusable(cls, c1: str, c2: str) -> bool:
        """Check if two characters are commonly confused by OCR."""
        c1u, c2u = c1.upper(), c2.upper()
        if c1u == c2u:
            return True
        for group in cls.OCR_CONFUSABLE_GROUPS:
            if c1u in group and c2u in group:
                return True
        return False

    @classmethod
    def _entry_number_similarity(cls, entry1: str, entry2: str) -> float:
        """
        Compute similarity between two entry numbers using OCR-aware comparison.
        Returns 0.0 to 1.0.
        """
        if not entry1 or not entry2:
            return 0.0

        # Strip all whitespace and punctuation for raw comparison
        e1 = re.sub(r'[\s\-_./]', '', entry1).upper()
        e2 = re.sub(r'[\s\-_./]', '', entry2).upper()

        if not e1 or not e2:
            return 0.0

        # 1. Exact match after cleanup
        if e1 == e2:
            return 1.0

        # 2. OCR-canonical match (maps confusable chars to same representative)
        c1 = cls._ocr_canonicalize(e1)
        c2 = cls._ocr_canonicalize(e2)
        if c1 == c2:
            return 0.98

        # 3. Extract just the digits and compare (handles letter confusion but same digits)
        digits1 = re.sub(r'[^0-9]', '', e1)
        digits2 = re.sub(r'[^0-9]', '', e2)
        if digits1 and digits2 and digits1 == digits2 and len(digits1) >= 4:
            return 0.92

        # 4. Levenshtein distance with OCR-aware substitution costs
        max_len = max(len(e1), len(e2))
        if max_len == 0:
            return 0.0
        lev_dist = cls._levenshtein_distance(e1, e2)
        lev_sim = 1.0 - (lev_dist / max_len)

        # 5. Check if entry numbers share a structural pattern (same year + branch)
        m1 = cls.ENTRY_NUMBER_PATTERN.search(entry1)
        m2 = cls.ENTRY_NUMBER_PATTERN.search(entry2)
        structural_bonus = 0.0
        if m1 and m2:
            if m1.group(1) == m2.group(1):  # Same year
                structural_bonus += 0.05
            if m1.group(2).upper() == m2.group(2).upper():  # Same branch
                structural_bonus += 0.05
            # Compare just the numeric tail with OCR awareness
            tail1 = m1.group(3)
            tail2 = m2.group(3)
            if tail1 == tail2:
                structural_bonus += 0.15
            elif len(tail1) == len(tail2):
                tail_dist = cls._levenshtein_distance(tail1, tail2)
                if tail_dist <= 1:
                    structural_bonus += 0.10

        return min(lev_sim + structural_bonus, 1.0)

    @classmethod
    def _name_similarity(cls, name1: str, name2: str) -> float:
        """
        Compute OCR-aware name similarity using multiple signals.
        Returns 0.0 to 1.0.
        """
        if not name1 or not name2:
            return 0.0

        s = name1.strip().lower()
        o = name2.strip().lower()

        if not s or not o:
            return 0.0

        # 1. Exact match
        if s == o:
            return 1.0

        # 2. Word-level matching (handles word reordering)
        s_parts = set(s.split())
        o_parts = set(o.split())
        s_words = s.split()
        o_words = o.split()

        if s_parts and o_parts:
            # Exact word intersection
            common_exact = s_parts.intersection(o_parts)
            total_words = max(len(s_parts), len(o_parts))
            word_ratio = len(common_exact) / total_words if total_words > 0 else 0

            # If all words match (possibly reordered), it's a perfect match
            if word_ratio >= 1.0:
                return 1.0
            # If most words match, very high confidence
            if word_ratio >= 0.6 and len(common_exact) >= 2:
                return 0.9 + (word_ratio * 0.1)

        # 3. OCR-aware word matching (fuzzy per-word)
        fuzzy_word_matches = 0
        total_word_pairs = max(len(s_words), len(o_words))
        for sw in s_words:
            for ow in o_words:
                if len(sw) >= 2 and len(ow) >= 2:
                    per_word_dist = cls._levenshtein_distance(sw, ow)
                    max_word_len = max(len(sw), len(ow))
                    if per_word_dist <= max(1, max_word_len * 0.3):  # Allow ~30% error
                        fuzzy_word_matches += 1
                        break
        fuzzy_word_ratio = fuzzy_word_matches / total_word_pairs if total_word_pairs > 0 else 0

        # 4. Substring containment (one name contains the other)
        containment_bonus = 0.0
        if s in o or o in s:
            containment_bonus = 0.3
        else:
            # Check if any significant word (>=3 chars) appears as substring
            for word in s_parts:
                if len(word) >= 3 and word in o:
                    containment_bonus = 0.15
                    break
            if containment_bonus == 0:
                for word in o_parts:
                    if len(word) >= 3 and word in s:
                        containment_bonus = 0.15
                        break

        # 5. Character bigram similarity (robust to small OCR errors)
        def bigrams(text):
            return set(text[i:i+2] for i in range(len(text) - 1)) if len(text) >= 2 else set()

        s_bigrams = bigrams(s.replace(' ', ''))
        o_bigrams = bigrams(o.replace(' ', ''))
        if s_bigrams and o_bigrams:
            bigram_sim = len(s_bigrams & o_bigrams) / len(s_bigrams | o_bigrams)
        else:
            bigram_sim = 0.0

        # 6. SequenceMatcher ratio as baseline
        seq_ratio = difflib.SequenceMatcher(None, s, o).ratio()

        # Combine signals with weights
        combined = (
            fuzzy_word_ratio * 0.35 +
            bigram_sim * 0.25 +
            seq_ratio * 0.25 +
            containment_bonus * 0.15
        )

        return min(combined, 1.0)

    @classmethod
    def _smart_match_score(cls, sheet_entry: str, sheet_name: str,
                           ocr_entry: str, ocr_name: str) -> float:
        """
        Compute an overall match confidence score (0.0 - 1.0) between a master sheet
        student and an OCR result, accounting for common OCR errors.
        """
        entry_sim = cls._entry_number_similarity(sheet_entry, ocr_entry)
        name_sim = cls._name_similarity(sheet_name, ocr_name)

        # Weighted combination: entry number is more reliable than name for matching
        # because names are more prone to OCR errors in handwritten sheets
        if entry_sim >= 0.9:
            # Entry number is very strong match — trust it heavily
            return entry_sim * 0.75 + name_sim * 0.25
        elif entry_sim >= 0.7:
            # Moderate entry match — balance both signals
            return entry_sim * 0.55 + name_sim * 0.45
        elif name_sim >= 0.8:
            # Strong name match even if entry is weak
            return entry_sim * 0.3 + name_sim * 0.7
        else:
            # Both weak — average with entry slightly higher
            return entry_sim * 0.5 + name_sim * 0.5

    # ──────────────────────────────────────
    #  Name Cross-Verification
    # ──────────────────────────────────────

    @classmethod
    def _check_name_mismatch(cls, sheet_name: str, ocr_name: str, entry_number: str, row: int) -> Optional[str]:
        """Returns mismatch message string if names don't match, using OCR-aware comparison."""
        if not sheet_name or not ocr_name:
            return None

        s = sheet_name.strip().lower()
        o = ocr_name.strip().lower()

        # Skip comparison if either name is a known placeholder — raw OCR couldn't read it
        if not s or not o or s == 'unknown' or o == 'unknown':
            return None

        sim = cls._name_similarity(s, o)
        if sim >= 0.6:  # Good enough match — no mismatch
            return None

        return f"Name mismatch: Sheet='{sheet_name}' vs OCR='{ocr_name}' (sim={sim:.2f})"

    # ──────────────────────────────────────
    #  Reading Student List
    # ──────────────────────────────────────

    def read_student_list(self, sheet_url: str) -> Dict:
        """Read the student list and detect columns."""
        if not self.service:
            raise RuntimeError("Sheets service not initialized. Check credentials.")

        spreadsheet_id, sheet_name = self.parse_sheet_url(sheet_url)

        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()

        sheets = spreadsheet.get('sheets', [])
        if not sheets:
            raise ValueError("Spreadsheet has no sheets")

        # Prioritize 'student_names' if no specific tab is mentioned in the URL
        if not sheet_name:
            target_name = "student_names"
            found_target = False
            for sheet in sheets:
                title = sheet['properties']['title']
                if title.strip().lower() == target_name.lower():
                    sheet_name = title
                    found_target = True
                    break
            
            if not found_target:
                sheet_name = sheets[0]['properties']['title']

        range_name = f"'{sheet_name}'"
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()

        values = result.get('values', [])
        
        # If completely empty, we will auto-initialize in update_marks
        if not values:
            return {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "columns": {},
                "students": [],
                "is_empty": True
            }

        headers = values[0]
        columns = self._detect_columns(headers)

        students = []
        if columns.get('entry_number'):
            entry_col = columns['entry_number']['index']
            name_col = columns.get('name', {}).get('index')
            comments_col = columns.get('comments', {}).get('index')

            # Process up to current data rows
            for row_idx, row in enumerate(values[1:], start=2):
                entry_number = self._safe_get(row, entry_col, '').strip()
                if not entry_number:
                    continue

                name = self._safe_get(row, name_col, '').strip() if name_col is not None else ''
                existing_comment = self._safe_get(row, comments_col, '') if comments_col is not None else ''

                students.append({
                    "row": row_idx,
                    "entry_number": entry_number,
                    "name": name,
                    "existing_comment": existing_comment
                })

        return {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "columns": columns,
            "students": students,
            "is_empty": False,
            "headers": headers
        }

    # ──────────────────────────────────────
    #  Writing Marks
    # ──────────────────────────────────────

    def update_marks(self, sheet_url: str, results: List[Dict], sheet_tab_name: str = None) -> Dict:
        """
        Write marks, comments, AND per-question scores to a named sheet tab.
        Auto-creates the tab if it doesn't exist. Matches records against the Master sheet.
        Adds STATISTICS section at the bottom.
        """
        if not self.service:
            raise RuntimeError("Sheets service not initialized. Check credentials.")

        # Read master student list to cross-verify against
        try:
            sheet_data = self.read_student_list(sheet_url)
            master_students = sheet_data.get('students', [])
        except Exception:
            master_students = []

        spreadsheet_id, _ = self.parse_sheet_url(sheet_url)

        # Determine maximum questions from results
        all_q_nums = set()
        for r in results:
            for d in r.get('details', []):
                qn = d.get('question_number') if isinstance(d, dict) else getattr(d, 'question_number', None)
                if qn: all_q_nums.add(int(qn))
        all_q_nums = sorted(list(all_q_nums))

        # If a sheet_tab_name is given, create the tab if it doesn't exist
        if sheet_tab_name:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            existing_sheets = {sheet['properties']['title'] for sheet in spreadsheet.get('sheets', [])}
            
            if sheet_tab_name in existing_sheets:
                self.service.spreadsheets().values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{sheet_tab_name}'"
                ).execute()
            else:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={'requests': [{'addSheet': {'properties': {'title': sheet_tab_name}}}]}
                ).execute()
            
            target_sheet = sheet_tab_name
        else:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            sheets = spreadsheet.get('sheets', [])
            if not sheets:
                raise ValueError("Spreadsheet has no sheets")
            target_sheet = sheets[0]['properties']['title']

        # Sanitize helper — strip known meaningless placeholder strings from OCR results.
        # 'unknown' IS included here: when OCR cannot read a field it outputs 'unknown',
        # which should become an empty string so downstream matching/export stays clean.
        # The actual raw OCR text (garbled entry numbers, partial names) is kept as-is.
        _UNKNOWN_PLACEHOLDERS = {'unknown', 'n/a', 'none', 'null'}

        def _sanitize(val: str) -> str:
            """Return empty string if val is a known placeholder, else val."""
            stripped = (val or '').strip()
            return '' if stripped.lower() in _UNKNOWN_PLACEHOLDERS else stripped

        # Build lookup from OCR results (sanitize entry/name on the way in)
        results_map = {}
        for r in results:
            # Sanitize in-place so downstream code sees clean values
            if isinstance(r, dict):
                r['entry_number'] = _sanitize(str(r.get('entry_number', '')))
                r['name'] = _sanitize(str(r.get('name', '')))
            raw = r.get('entry_number', '') if isinstance(r, dict) else ''
            normalized = self._normalize_entry_number(raw)
            if normalized:
                results_map[normalized] = r
            elif r.get('name') or r.get('answers'):
                # No valid entry number but has other data — still include with a placeholder key
                placeholder_key = f"__noentry_{len(results_map)}"
                results_map[placeholder_key] = r

        # Build headers — include OCR-detected name/entry for cross-reference
        headers = ["Entry Number", "Name", "OCR Entry Number", "OCR Name"]
        for q in all_q_nums:
            headers.append(f"Q{q}")
        headers.append("Marks")
        headers.append("Comments")

        data_rows = []
        all_scores = []
        mismatches_to_bold = []
        unmatched_to_red = []
        
        summary = {
            "updated": 0,
            "not_found_in_sheet": [],
            "not_found_in_results": [],
            "name_mismatches": [],
            "errors": [],
            "sheet_tab": target_sheet,
            "statistics": {}
        }

        matched_results = set()

        if master_students:
            # We have a master list to match against
            for student in master_students:
                raw_entry = student.get('entry_number', '')
                normalized = self._normalize_entry_number(raw_entry)
                result = None
                is_fuzzy_match = False

                if normalized and normalized in results_map:
                    result = results_map[normalized]
                    matched_results.add(normalized)
                elif raw_entry:
                    # Fallback to OCR-Aware Smart Fuzzy Matching
                    sheet_name_str = student.get('name', '').strip()
                    sheet_entry_str = str(raw_entry).strip()
                    
                    best_match_id = None
                    best_match_r = None
                    best_score = 0.0
                    
                    for norm_id, r in results_map.items():
                        if norm_id in matched_results:
                            continue
                            
                        ocr_name_str = r.get('name', '').strip()
                        ocr_entry_str = str(r.get('entry_number', '')).strip()
                        
                        # Multi-signal OCR-aware smart match
                        match_score = self._smart_match_score(
                            sheet_entry_str, sheet_name_str,
                            ocr_entry_str, ocr_name_str
                        )
                        
                        # Accept matches with confidence >= 0.55
                        if match_score >= 0.55 and match_score > best_score:
                            best_score = match_score
                            best_match_id = norm_id
                            best_match_r = r
                            
                    if best_match_r:
                        result = best_match_r
                        is_fuzzy_match = True
                        matched_results.add(best_match_id)
                        print(f"  🔗 Smart match: '{sheet_entry_str}' → '{best_match_r.get('entry_number', '')}' (confidence: {best_score:.2f})")

                row = [
                    raw_entry,
                    student.get('name', ''),
                ]

                if not result:
                    summary['not_found_in_results'].append(raw_entry)
                    row.extend(['', ''])  # OCR Entry, OCR Name
                    for q in all_q_nums: row.append('')
                    row.append('') # Marks
                    row.append('Absent / No Answer Sheet Found')
                    data_rows.append(row)
                    continue

                # Add OCR-detected entry number and name
                ocr_entry = str(result.get('entry_number', '')).strip()
                ocr_name = str(result.get('name', '')).strip()
                row.extend([ocr_entry, ocr_name])

                summary['updated'] += 1

                final_comments = []
                if result.get('comments'):
                    final_comments.append(result.get('comments'))
                
                mismatch_msg = self._check_name_mismatch(
                    student.get('name', ''),
                    ocr_name,
                    raw_entry,
                    0
                )

                # Check if OCR entry number differs from master
                entry_sim = self._entry_number_similarity(raw_entry, ocr_entry)
                entry_mismatch = entry_sim < 0.95

                is_mismatch = bool(mismatch_msg) or is_fuzzy_match or entry_mismatch

                if is_fuzzy_match:
                    final_comments.append(f"Fuzzy Match: OCR ID='{ocr_entry}', OCR Name='{ocr_name}'")
                    summary['name_mismatches'].append({
                        "entry_number": raw_entry,
                        "sheet_name": student.get('name', ''),
                        "ocr_name": ocr_name,
                        "ocr_entry": ocr_entry,
                        "type": "fuzzy_match"
                    })
                elif mismatch_msg or entry_mismatch:
                    if mismatch_msg:
                        final_comments.append(mismatch_msg)
                    if entry_mismatch:
                        final_comments.append(f"Entry mismatch: Sheet='{raw_entry}' vs OCR='{ocr_entry}'")
                    summary['name_mismatches'].append({
                        "entry_number": raw_entry,
                        "sheet_name": student.get('name', ''),
                        "ocr_name": ocr_name,
                        "ocr_entry": ocr_entry,
                        "type": "mismatch"
                    })

                if is_mismatch:
                    mismatches_to_bold.append(len(data_rows))
                
                # Per-question scores
                d_map = {}
                for d in result.get('details', []):
                    qn = d.get('question_number') if isinstance(d, dict) else getattr(d, 'question_number', None)
                    if qn: d_map[int(qn)] = d
                
                for q in all_q_nums:
                    d = d_map.get(q, {})
                    val = d.get('score', 0) if isinstance(d, dict) else getattr(d, 'score', 0)
                    st = d.get('result', '') if isinstance(d, dict) else getattr(d, 'result', '')
                    if st in ['multiple', 'unattempted', 'incorrect']: val = 0
                    row.append(val)
                
                total = result.get('total_score', 0)
                row.append(total)
                all_scores.append(total)
                
                row.append("; ".join(final_comments))
                data_rows.append(row)

        # Handle results that weren't matched in the master list, or if NO master list exists
        for norm_id, r in results_map.items():
            if norm_id not in matched_results:
                raw_entry = r.get('entry_number', '')
                ocr_name_unmatched = r.get('name', '')
                if master_students:
                    # Only report as not found if there was a master list to check against
                    summary['not_found_in_sheet'].append(raw_entry)
                summary['updated'] += 1
                
                row = [
                    raw_entry,
                    ocr_name_unmatched,
                    raw_entry,       # OCR Entry Number (same as raw since no master to compare)
                    ocr_name_unmatched,  # OCR Name
                ]
                
                d_map = {}
                for d in r.get('details', []):
                    qn = d.get('question_number') if isinstance(d, dict) else getattr(d, 'question_number', None)
                    if qn: d_map[int(qn)] = d
                
                for q in all_q_nums:
                    d = d_map.get(q, {})
                    val = d.get('score', 0) if isinstance(d, dict) else getattr(d, 'score', 0)
                    st = d.get('result', '') if isinstance(d, dict) else getattr(d, 'result', '')
                    if st in ['multiple', 'unattempted', 'incorrect']: val = 0
                    row.append(val)
                
                total = r.get('total_score', 0)
                row.append(total)
                all_scores.append(total)
                
                final_comments = []
                if r.get('comments'): final_comments.append(r.get('comments'))
                if master_students:
                    final_comments.append("Not found in Master Student List")
                    unmatched_to_red.append(len(data_rows))
                
                row.append("; ".join(final_comments))
                data_rows.append(row)

        # Statistics
        marks_col_idx = len(headers) - 2
        if all_scores:
            mean_val = round(sum(all_scores) / len(all_scores), 2)
            sorted_scores = sorted(all_scores)
            n = len(sorted_scores)
            median_val = (sorted_scores[n//2 - 1] + sorted_scores[n//2]) / 2 if n % 2 == 0 else sorted_scores[n//2]
            highest_val = max(all_scores)
            lowest_val = min(all_scores)
        else:
            mean_val = median_val = highest_val = lowest_val = 0

        summary['statistics'] = {
            "mean": mean_val,
            "median": median_val,
            "highest": highest_val,
            "lowest": lowest_val
        }

        empty_row = [''] * len(headers)
        stats_label_row = [''] * len(headers)
        stats_label_row[1] = 'STATISTICS'

        mean_row = [''] * len(headers)
        mean_row[1] = 'Mean / Average'
        mean_row[marks_col_idx] = mean_val

        median_row = [''] * len(headers)
        median_row[1] = 'Median'
        median_row[marks_col_idx] = median_val

        highest_row = [''] * len(headers)
        highest_row[1] = 'Highest'
        highest_row[marks_col_idx] = highest_val

        lowest_row = [''] * len(headers)
        lowest_row[1] = 'Lowest'
        lowest_row[marks_col_idx] = lowest_val

        all_data = [headers] + data_rows + [empty_row, stats_label_row, mean_row, median_row, highest_row, lowest_row]

        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{target_sheet}'!A1",
            valueInputOption='USER_ENTERED',
            body={'values': all_data}
        ).execute()

        self._format_marks_sheet(spreadsheet_id, target_sheet, len(headers), len(data_rows), len(all_data), mismatches_to_bold, unmatched_to_red)

        print(f"✅ Wrote {len(data_rows)} students to '{target_sheet}'. Matches: {summary['updated']}, Mismatches: {len(mismatches_to_bold)}")
        return summary

    def _format_marks_sheet(self, spreadsheet_id: str, sheet_name: str, num_cols: int, num_data_rows: int, total_rows: int, mismatches_to_bold: List[int] = None, unmatched_to_red: List[int] = None):
        """Apply formatting to the marks sheet — bold header, statistics, and highlights for mismatches."""
        mismatches_to_bold = mismatches_to_bold or []
        unmatched_to_red = unmatched_to_red or []
        
        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheet_id = None
            for sheet in spreadsheet.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    sheet_id = sheet['properties']['sheetId']
                    break
            if sheet_id is None:
                return

            requests = []

            # Bold header row
            requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': 0, 'endRowIndex': 1,
                        'startColumnIndex': 0, 'endColumnIndex': num_cols
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9},
                            'textFormat': {'bold': True},
                            'horizontalAlignment': 'CENTER'
                        }
                    },
                    'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
                }
            })

            # Formatting for mismatched rows (bold and red text on OCR columns only)
            if mismatches_to_bold:
                for r_idx in mismatches_to_bold:
                    real_row = r_idx + 1  # Offset by 1 for the header
                    # Red text on OCR Entry Number (col 2) and OCR Name (col 3)
                    requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': sheet_id,
                                'startRowIndex': real_row, 'endRowIndex': real_row + 1,
                                'startColumnIndex': 2, 'endColumnIndex': 4  # OCR Entry Number and OCR Name
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'textFormat': {
                                        'bold': True,
                                        'foregroundColor': {'red': 0.8, 'green': 0.0, 'blue': 0.0}
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat(textFormat)'
                        }
                    })

            # Formatting for unmatched rows (bold and red text on ALL identification columns - Master & OCR)
            if unmatched_to_red:
                for r_idx in unmatched_to_red:
                    real_row = r_idx + 1  # Offset by 1 for the header
                    # Red text on Master Entry, Master Name, OCR Entry, OCR Name (cols 0 to 3)
                    requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': sheet_id,
                                'startRowIndex': real_row, 'endRowIndex': real_row + 1,
                                'startColumnIndex': 0, 'endColumnIndex': 4
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'textFormat': {
                                        'bold': True,
                                        'foregroundColor': {'red': 0.8, 'green': 0.0, 'blue': 0.0}
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat(textFormat)'
                        }
                    })

            # Bold statistics section
            stats_start_row = num_data_rows + 2
            if total_rows > stats_start_row:
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': stats_start_row,
                            'endRowIndex': total_rows,
                            'startColumnIndex': 0, 'endColumnIndex': num_cols
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {'bold': True}
                            }
                        },
                        'fields': 'userEnteredFormat(textFormat)'
                    }
                })

            # Freeze header row
            requests.append({
                'updateSheetProperties': {
                    'properties': {
                        'sheetId': sheet_id,
                        'gridProperties': {'frozenRowCount': 1}
                    },
                    'fields': 'gridProperties.frozenRowCount'
                }
            })

            # Auto-resize columns
            requests.append({
                'autoResizeDimensions': {
                    'dimensions': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': 0, 'endIndex': num_cols
                    }
                }
            })

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()

        except Exception as e:
            print(f"Warning: Failed to format marks sheet: {e}")

    def create_student_response_sheet(
        self, 
        sheet_url: str, 
        results: List[Dict], 
        answer_key: Dict,
        response_sheet_name: str = "Student Responses"
    ) -> Dict:
        """
        Create a sheet tab with per-question student responses (marked answers).
        Format: Entry Number | Name | Q1 | Q2 | ... | Qn
        Last row is the Answer Key with correct answers bolded.
        """
        if not self.service:
            raise RuntimeError("Sheets service not initialized. Check credentials.")

        spreadsheet_id, _ = self.parse_sheet_url(sheet_url)

        # Get all questions from answer key — handle both int and str keys
        answers_dict = answer_key.get('answers', {})
        
        # Build a normalized lookup: int -> answer_entry_dict
        normalized_answers = {}
        for k, v in answers_dict.items():
            q_num = int(k)
            normalized_answers[q_num] = v
        
        questions = sorted(normalized_answers.keys())
        if not questions:
            raise ValueError("No questions found in answer key")

        # Prepare headers: Name, Entry Number, Q1, Q2, ..., Qn (user-requested order)
        headers = ['Name', 'Entry Number']
        for q in questions:
            headers.append(f'Q{q}')

        # Prepare student data rows
        data_rows = []
        for result in results:
            if not isinstance(result, dict):
                continue
                
            row = [
                result.get('name', ''),
                result.get('entry_number', ''),
            ]
            
            # Get per-question details
            details_map = {}
            for detail in result.get('details', []):
                if isinstance(detail, dict):
                    q_num = detail.get('question_number')
                    if q_num:
                        details_map[int(q_num)] = detail
            
            # Add marked answer for each question
            for q in questions:
                detail = details_map.get(q, {})
                marked = detail.get('marked', '') or ''
                row.append(str(marked))
            
            data_rows.append(row)

        # Build Answer Key row (last row) — extract correct_answer from each entry
        answer_key_row = ['Answer Key', '']
        for q in questions:
            entry = normalized_answers.get(q)
            correct = ''
            if entry is None:
                correct = ''
            elif isinstance(entry, dict):
                correct = entry.get('correct_answer', '') or entry.get('correct_option', '') or ''
            elif isinstance(entry, str):
                correct = entry
            else:
                # Could be an AnswerKeyEntry Pydantic object (shouldn't happen after model_dump, but just in case)
                correct = getattr(entry, 'correct_answer', getattr(entry, 'correct_option', str(entry)))
            answer_key_row.append(str(correct))
        
        print(f"📋 Student Response Sheet — Answer Key Row: {answer_key_row}")

        # Create or update the response sheet
        try:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            
            existing_sheets = {sheet['properties']['title']: sheet['properties']['sheetId'] 
                             for sheet in spreadsheet.get('sheets', [])}
            
            if response_sheet_name in existing_sheets:
                self.service.spreadsheets().values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{response_sheet_name}'"
                ).execute()
            else:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={'requests': [{'addSheet': {'properties': {'title': response_sheet_name}}}]}
                ).execute()

            # Write data: headers + student rows + empty row + answer key
            all_data = [headers] + data_rows + [[]] + [answer_key_row]
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{response_sheet_name}'!A1",
                valueInputOption='USER_ENTERED',
                body={'values': all_data}
            ).execute()

            # Format the sheet (bold headers and answer key row)
            answer_key_row_idx = len(data_rows) + 2  # +1 header, +1 empty row (0-indexed)
            self._format_response_sheet(spreadsheet_id, response_sheet_name, len(headers), len(all_data), answer_key_row_idx)

            return {
                "message": f"Student response sheet '{response_sheet_name}' created successfully",
                "sheet_name": response_sheet_name,
                "students_exported": len(data_rows),
                "questions_exported": len(questions),
                "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            }

        except Exception as e:
            raise RuntimeError(f"Failed to create student response sheet: {str(e)}")

    def update_super_sheet(self, sheet_url: str, evaluation_name: str, results: List[Dict]) -> Dict:
        """
        Add/update a column in the 'Super Sheet' tab for this evaluation.
        Super Sheet has: Entry Number | Name | <eval1 marks> | <eval2 marks> | ... | Cumulative Total
        """
        if not self.service:
            raise RuntimeError("Sheets service not initialized. Check credentials.")

        spreadsheet_id, _ = self.parse_sheet_url(sheet_url)
        super_sheet_name = "Super Sheet"

        # Get spreadsheet metadata
        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        existing_sheets = {sheet['properties']['title'] for sheet in spreadsheet.get('sheets', [])}

        # Read existing Super Sheet data, or create if missing
        if super_sheet_name not in existing_sheets:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [{'addSheet': {'properties': {'title': super_sheet_name}}}]}
            ).execute()
            existing_data = []
        else:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"'{super_sheet_name}'"
            ).execute()
            existing_data = result.get('values', [])

        # Build student lookup from results
        results_by_entry = {}
        for r in results:
            entry = r.get('entry_number', '')
            if entry:
                results_by_entry[self._normalize_entry_number(entry) or entry] = r

        if not existing_data:
            # Initialize Super Sheet from scratch
            headers = ['Entry Number', 'Name', evaluation_name, 'Cumulative Total']
            rows = [headers]
            for r in results:
                total = r.get('total_score', 0)
                rows.append([
                    r.get('entry_number', ''),
                    r.get('name', ''),
                    total,
                    total
                ])
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{super_sheet_name}'!A1",
                valueInputOption='USER_ENTERED',
                body={'values': rows}
            ).execute()
        else:
            # Super Sheet already has data — add/update column for this evaluation
            headers = existing_data[0] if existing_data else []
            
            # Check if evaluation column already exists
            eval_col_idx = None
            cumulative_col_idx = None
            for idx, h in enumerate(headers):
                if h.strip().lower() == evaluation_name.strip().lower():
                    eval_col_idx = idx
                if h.strip().lower() in ('cumulative total', 'cumulative_total', 'total'):
                    cumulative_col_idx = idx

            if eval_col_idx is not None:
                # Column exists — update it
                pass
            else:
                # Add new column before Cumulative Total (or at end)
                if cumulative_col_idx is not None:
                    # Insert before cumulative
                    eval_col_idx = cumulative_col_idx
                    headers.insert(eval_col_idx, evaluation_name)
                    cumulative_col_idx = eval_col_idx + 1
                    # Shift existing rows
                    for i in range(1, len(existing_data)):
                        row = existing_data[i]
                        while len(row) < len(headers) - 1:
                            row.append('')
                        row.insert(eval_col_idx, '')
                else:
                    # No cumulative column — add eval + cumulative at end
                    eval_col_idx = len(headers)
                    headers.append(evaluation_name)
                    cumulative_col_idx = len(headers)
                    headers.append('Cumulative Total')

            # Ensure all rows have correct length
            for i in range(1, len(existing_data)):
                while len(existing_data[i]) < len(headers):
                    existing_data[i].append('')

            # Build entry-number-indexed rows
            entry_col = 0  # Assume first column is entry number
            student_rows = {}
            for i in range(1, len(existing_data)):
                row = existing_data[i]
                entry = row[entry_col] if row else ''
                norm = self._normalize_entry_number(entry) if entry else None
                if norm:
                    student_rows[norm] = i

            # Update existing students and collect new ones
            new_rows = []
            for norm_entry, r in results_by_entry.items():
                total = r.get('total_score', 0)
                if norm_entry in student_rows:
                    row_idx = student_rows[norm_entry]
                    existing_data[row_idx][eval_col_idx] = total
                else:
                    # New student — create a new row
                    new_row = [''] * len(headers)
                    new_row[0] = r.get('entry_number', '')
                    new_row[1] = r.get('name', '')
                    new_row[eval_col_idx] = total
                    new_rows.append(new_row)

            # Update headers
            existing_data[0] = headers

            # Append new students
            existing_data.extend(new_rows)

            # Recalculate Cumulative Total for all students
            if cumulative_col_idx is not None:
                # Sum all numeric columns between Name and Cumulative Total
                for i in range(1, len(existing_data)):
                    row = existing_data[i]
                    while len(row) < len(headers):
                        row.append('')
                    cumulative = 0
                    for j in range(2, cumulative_col_idx):
                        try:
                            cumulative += float(row[j]) if row[j] != '' else 0
                        except (ValueError, TypeError):
                            pass
                    row[cumulative_col_idx] = cumulative

            # Write back
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{super_sheet_name}'!A1",
                valueInputOption='USER_ENTERED',
                body={'values': existing_data}
            ).execute()

        print(f"✅ Super Sheet updated with '{evaluation_name}' column.")
        return {"message": f"Super Sheet updated with '{evaluation_name}'"}

    def _format_response_sheet(self, spreadsheet_id: str, sheet_name: str, num_cols: int, num_rows: int, answer_key_row_idx: int = -1):
        """Apply formatting to the student response sheet — bold header and Answer Key row."""
        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheet_id = None
            for sheet in spreadsheet.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    sheet_id = sheet['properties']['sheetId']
                    break
            
            if sheet_id is None:
                return

            requests = []
            
            # Format header row — light blue background, bold, centered
            requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': 0, 'endRowIndex': 1,
                        'startColumnIndex': 0, 'endColumnIndex': num_cols
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': {'red': 0.85, 'green': 0.92, 'blue': 1.0},
                            'textFormat': {'bold': True, 'fontSize': 10},
                            'horizontalAlignment': 'CENTER'
                        }
                    },
                    'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
                }
            })

            # Bold Answer Key row with light green background
            if answer_key_row_idx >= 0:
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': answer_key_row_idx,
                            'endRowIndex': answer_key_row_idx + 1,
                            'startColumnIndex': 0, 'endColumnIndex': num_cols
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'backgroundColor': {'red': 0.85, 'green': 0.95, 'blue': 0.85},
                                'textFormat': {'bold': True, 'fontSize': 10},
                                'horizontalAlignment': 'CENTER'
                            }
                        },
                        'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
                    }
                })
            
            # Center-align question columns (C onwards) for all data rows
            if num_cols > 2:
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1, 'endRowIndex': num_rows,
                            'startColumnIndex': 2, 'endColumnIndex': num_cols
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'horizontalAlignment': 'CENTER'
                            }
                        },
                        'fields': 'userEnteredFormat(horizontalAlignment)'
                    }
                })
            
            # Set fixed column widths: Entry Number (140px), Name (160px), Questions (50px each)
            requests.append({
                'updateDimensionProperties': {
                    'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 1},
                    'properties': {'pixelSize': 140},
                    'fields': 'pixelSize'
                }
            })
            requests.append({
                'updateDimensionProperties': {
                    'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 1, 'endIndex': 2},
                    'properties': {'pixelSize': 160},
                    'fields': 'pixelSize'
                }
            })
            if num_cols > 2:
                requests.append({
                    'updateDimensionProperties': {
                        'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 2, 'endIndex': num_cols},
                        'properties': {'pixelSize': 50},
                        'fields': 'pixelSize'
                    }
                })
            
            # Freeze header row
            requests.append({
                'updateSheetProperties': {
                    'properties': {
                        'sheetId': sheet_id,
                        'gridProperties': {'frozenRowCount': 1}
                    },
                    'fields': 'gridProperties.frozenRowCount'
                }
            })

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()

        except Exception as e:
            print(f"Warning: Failed to format response sheet: {e}")

    # ──────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────

    QUESTION_COLUMN_PATTERN = re.compile(
        r'^(?:q|ques|question)?[\s\.\-\_]*(\d+)$', 
        re.IGNORECASE
    )

    def _detect_columns(self, headers: List[str]) -> Dict:
        """
        Auto-detect columns including Question columns (1, Q1, etc.)
        """
        columns = {'questions': {}}
        
        # Helper to normalize
        def norm(h): return h.strip().lower()

        for idx, header_raw in enumerate(headers):
            h = norm(header_raw)
            col_letter = self._index_to_letter(idx)
            
            # 1. Entry Number (High Priority)
            if not columns.get('entry_number'):
                if h in self.ENTRY_NUMBER_ALIASES:
                    columns['entry_number'] = {"index": idx, "letter": col_letter, "header": header_raw}
                    continue

            # 2. Student Name
            if not columns.get('name'):
                 if h in self.NAME_ALIASES:
                    columns['name'] = {"index": idx, "letter": col_letter, "header": header_raw}
                    continue

            # 3. Marks / Total Score
            if not columns.get('marks'):
                 if h in self.MARKS_ALIASES:
                    columns['marks'] = {"index": idx, "letter": col_letter, "header": header_raw}
                    continue
            
            # 4. Comments
            if not columns.get('comments'):
                 if h in self.COMMENTS_ALIASES:
                    columns['comments'] = {"index": idx, "letter": col_letter, "header": header_raw}
                    continue

            # 5. Question Columns (Check regex)
            # Try matching "Q1", "Question 1", "1", etc.
            m = self.QUESTION_COLUMN_PATTERN.match(h)
            if m:
                try:
                    q_num = int(m.group(1))
                    # Prevent "1" from being confused if we want constraints, but usually Qs are 1..N
                    columns['questions'][q_num] = {"index": idx, "letter": col_letter, "header": header_raw}
                    continue
                except ValueError:
                    pass
            
            # 6. Fallback: If header is just an integer, treat as question
            if header_raw.strip().isdigit():
                 q_num = int(header_raw.strip())
                 if q_num not in columns['questions']:
                     columns['questions'][q_num] = {"index": idx, "letter": col_letter, "header": header_raw}

        if columns.get('questions'):
            print(f"📊 Detected {len(columns['questions'])} question columns: {sorted(list(columns['questions'].keys()))}")
        
        return columns

    @staticmethod
    def _index_to_letter(index: int) -> str:
        result = ""
        while True:
            result = chr(65 + (index % 26)) + result
            index = index // 26 - 1
            if index < 0:
                break
        return result

    @staticmethod
    def _safe_get(lst: list, idx: Optional[int], default=None):
        if idx is None or idx >= len(lst):
            return default
        return lst[idx]
