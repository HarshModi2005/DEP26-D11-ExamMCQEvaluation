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

# Module-level dedup set — suppresses duplicate Entry Correction log lines
# when sync-results is polled repeatedly for the same stale OCR entries.
_entry_correction_logged: set = set()


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

    # ─────────────────────────────────────────────────
    #  OCR Correction Constants
    # ─────────────────────────────────────────────────
    KNOWN_DEPT_CODES = {'CS', 'AI', 'MC', 'EE', 'EP', 'CH', 'CE', 'MM', 'IC', 'DA'}
    KNOWN_DEGREE_TYPES = {'B', 'M'}  # B.Tech, M.Tech

    # Similar-looking characters: digit → letter (for branch section LLL)
    _DIGIT_TO_LETTER = {
        '0': 'O', '1': 'I', '2': 'Z', '3': 'E', '4': 'A',
        '5': 'S', '6': 'C', '7': 'T', '8': 'B', '9': 'G',
    }

    # Similar-looking characters: letter → digit (for YYYY and NNNN)
    _LETTER_TO_DIGIT = {
        'O': '0', 'I': '1', 'L': '1', 'Z': '2', 'E': '3',
        'A': '4', 'S': '5', 'G': '6', 'T': '7', 'B': '8',
        'Q': '0', 'D': '0', 'R': '2', 'J': '1',
    }

    # Similar-looking characters: letter → letter (for dept code fix)
    # These are letters OCR might confuse with known dept letters
    _LETTER_TO_LETTER = {
        'K': 'C', 'U': 'C', 'G': 'C', 'Q': 'C', 'O': 'C',  # look like C
        'H': 'M', 'N': 'M', 'W': 'M',             # look like M
        'J': 'I', 'L': 'I',                         # look like I
        'R': 'B', 'P': 'B',                         # look like B (for degree)
        'V': 'E', 'E': 'C',                         # V→E, E→C (OCR confuses E/C)
        'F': 'E', 'X': 'E',                         # stretch but OCR confuses
    }

    # Similar-looking degree chars → B or M
    _DEGREE_FIX = {
        '8': 'B', 'R': 'B', 'P': 'B', 'D': 'B', 'E': 'B', 'H': 'B',
        'N': 'M', 'W': 'M', 'H': 'M',  # H can be M too; B takes priority
    }

    # Special OCR chars → alphanumeric before stripping
    _SPECIAL_CHAR_MAP = {
        '(': 'C', ')': 'J', '{': 'C', '}': 'J', '[': 'C', ']': 'J',
        '|': '1', '!': '1', '$': 'S', '@': 'A', '#': 'H', '&': '8',
        '?': '7', '/': '1', '\\': '1',
    }

    @classmethod
    def _correct_entry_number_ocr(cls, raw: str) -> str:
        """
        Correct OCR'd entry number to YYYYLLLNNNN format.

        YYYY = 4 digits (year like 2023, 2024, 2025)
        LL   = 2 letters (dept: CS, MC, EE, AI, etc.)
        L    = 1 letter  (degree: B or M)
        NNNN = 4 digits  (roll number)

        Workflow:
        1. Replace special OCR chars (like '(' → 'C')
        2. Strip all remaining non-alphanumeric chars (dots, spaces, dashes)
        3. Handle length anomalies (11 chars → fix extra char)
        4. YYYY: force to digits using similar-looking char map
        5. LLL first 2 chars: force to letters, then fix to known dept (CS/MC/...)
        6. LLL 3rd char: force to B or M using similar-looking char map
        7. NNNN: force to digits using similar-looking char map
        """
        if not raw:
            return raw

        # Step 1: Replace special OCR chars with likely alphanumeric equivalents
        mapped = raw
        for special_ch, replacement in cls._SPECIAL_CHAR_MAP.items():
            mapped = mapped.replace(special_ch, replacement)

        # Step 2: Strip ALL non-alphanumeric characters (dots, spaces, dashes, etc.)
        clean = re.sub(r'[^A-Za-z0-9]', '', mapped).upper()

        if len(clean) < 8:
            return clean  # Too short, can't be an entry number

        # Step 3: Handle length anomalies
        # Expected: YYYYLLLNNNN = 4 + 3 + 4 = 11 characters
        if len(clean) == 12:
            # Extra char crept in — try to identify and fix it
            possible_dept = clean[4:6]
            if possible_dept in cls.KNOWN_DEPT_CODES and clean[6].isdigit():
                # Extra digit between dept and roll: e.g. '2025CS112034'
                degree_fix = cls._DIGIT_TO_LETTER.get(clean[6], 'B')
                if degree_fix not in cls.KNOWN_DEGREE_TYPES:
                    degree_fix = 'B'
                clean = clean[:6] + degree_fix + clean[7:11]
            else:
                clean = clean[:11]  # Truncate to 11
        elif len(clean) > 12:
            clean = clean[:11]

        # Step 4: Fix YYYY (positions 0-3) — MUST be digits
        year_chars = list(clean[:4])
        for i in range(len(year_chars)):
            if not year_chars[i].isdigit():
                year_chars[i] = cls._LETTER_TO_DIGIT.get(year_chars[i], year_chars[i])
        year_str = ''.join(year_chars)

        # Step 5: Fix dept code (positions 4-5) — MUST be letters
        dept_chars = list(clean[4:6]) if len(clean) >= 6 else list(clean[4:])
        for i in range(len(dept_chars)):
            ch = dept_chars[i]
            if ch.isdigit():
                dept_chars[i] = cls._DIGIT_TO_LETTER.get(ch, ch)
        dept_str = ''.join(dept_chars).upper()

        # Try to fix dept to a known code using letter-to-letter confusables
        if dept_str not in cls.KNOWN_DEPT_CODES:
            # Try fixing each char independently
            for i in range(len(dept_str)):
                ch = dept_str[i]
                if ch in cls._LETTER_TO_LETTER:
                    candidate = dept_str[:i] + cls._LETTER_TO_LETTER[ch] + dept_str[i+1:]
                    if candidate in cls.KNOWN_DEPT_CODES:
                        dept_str = candidate
                        break
            # Try fixing both chars
            if dept_str not in cls.KNOWN_DEPT_CODES:
                for i in range(len(dept_str)):
                    for j in range(len(dept_str)):
                        if i == j:
                            continue
                        ch_i = dept_str[i]
                        ch_j = dept_str[j]
                        fix_i = cls._LETTER_TO_LETTER.get(ch_i, ch_i)
                        fix_j = cls._LETTER_TO_LETTER.get(ch_j, ch_j)
                        candidate = ''
                        for k in range(len(dept_str)):
                            if k == i:
                                candidate += fix_i
                            elif k == j:
                                candidate += fix_j
                            else:
                                candidate += dept_str[k]
                        if candidate in cls.KNOWN_DEPT_CODES:
                            dept_str = candidate
                            break
                    if dept_str in cls.KNOWN_DEPT_CODES:
                        break

        # Step 6: Fix degree char (position 6) — MUST be B or M
        if len(clean) >= 7:
            degree_ch = clean[6]
        else:
            degree_ch = 'B'  # Default

        if degree_ch.isdigit():
            degree_ch = cls._DIGIT_TO_LETTER.get(degree_ch, 'B')
        if degree_ch not in cls.KNOWN_DEGREE_TYPES:
            degree_ch = cls._DEGREE_FIX.get(degree_ch, 'B')
        if degree_ch not in cls.KNOWN_DEGREE_TYPES:
            degree_ch = 'B'  # Final fallback

        # Step 7: Fix NNNN (positions 7-10) — MUST be digits
        tail_chars = list(clean[7:11]) if len(clean) >= 8 else []
        for i in range(len(tail_chars)):
            if not tail_chars[i].isdigit():
                tail_chars[i] = cls._LETTER_TO_DIGIT.get(tail_chars[i], tail_chars[i])
        tail_str = ''.join(tail_chars).ljust(4, '0')[:4]

        corrected = year_str + dept_str + degree_ch + tail_str
        original_clean = re.sub(r'[^A-Za-z0-9]', '', raw).upper()
        if corrected != original_clean:
            _key = (raw, corrected)
            if _key not in _entry_correction_logged:
                _entry_correction_logged.add(_key)
                print(f"  🔧 [Entry Correction] '{raw}' \u2192 '{corrected}'")
        return corrected
    
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
        # In-memory master student list cache keyed by sheet_url. Populated by
        # read_student_list and consumed by the rename flow (which does not
        # otherwise know which spreadsheet is authoritative).
        self._master_students_cache: Dict[str, List[Dict]] = {}
        self._last_master_url: Optional[str] = None

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

    def get_cached_master_students(self, sheet_url: Optional[str] = None) -> List[Dict]:
        """Return the cached master student list for `sheet_url`, or the most
        recently cached list if `sheet_url` is not provided. Returns [] on miss.
        """
        if sheet_url and sheet_url in self._master_students_cache:
            return self._master_students_cache[sheet_url]
        if not sheet_url and self._last_master_url:
            return self._master_students_cache.get(self._last_master_url, [])
        return []

    def refresh_master_students_cache(self, sheet_url: str) -> List[Dict]:
        """Read the sheet and populate the master-students cache. Best-effort:
        on failure, returns [] and leaves the cache untouched.
        """
        try:
            data = self.read_student_list(sheet_url)
            students = data.get("students", []) or []
            self._master_students_cache[sheet_url] = students
            self._last_master_url = sheet_url
            return students
        except Exception as e:
            print(f"⚠️  refresh_master_students_cache failed for {sheet_url}: {e}")
            return []

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
        """Normalize to YYYYLLLNNNN using domain-aware OCR correction."""
        if not raw or raw.lower() in ('unknown', 'none', 'n/a', ''):
            return None

        # Apply domain-aware OCR correction first
        corrected = cls._correct_entry_number_ocr(raw)

        m = cls.ENTRY_NUMBER_PATTERN.search(corrected)
        if m:
            year = m.group(1)
            branch = m.group(2).upper()
            number = m.group(3)
            return f"{year}{branch}{number}"

        fallback = re.sub(r'[\s\-_./]', '', corrected).upper()
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
        Final 3-stage matching workflow:

        Stage 1: Exact corrected entry number match.
                 Correct OCR output → YYYYLLLNNNN. If exact match AND
                 name_sim >= 0.40 → confident match (score 1.0).
                 Pure exact entry with no name → score 0.98.

        Stage 2: Year-sliding.
                 Same branch+roll but different year (±3).
                 Requires name_sim >= 0.50 → score 0.95.

        Stage 3: Combined entry Levenshtein + name similarity.
                 Entry distance ≤ 2 AND name_sim >= 0.60 → weighted score.
                 This catches cases where OCR mangled 1-2 chars in entry AND
                 the name is clearly the same student.
        """
        # Correct both entry numbers using domain knowledge
        e1 = cls._correct_entry_number_ocr(sheet_entry)
        e2 = cls._correct_entry_number_ocr(ocr_entry)
        e1 = re.sub(r'[^A-Za-z0-9]', '', e1).upper()
        e2 = re.sub(r'[^A-Za-z0-9]', '', e2).upper()

        name_sim = cls._name_similarity(sheet_name, ocr_name)

        # ── Stage 1: Exact corrected entry number match ──
        if e1 and e2 and e1 == e2:
            # Entry matches exactly after correction.
            # Name check is a soft sanity check — if no name data, still accept.
            if name_sim >= 0.40 or not ocr_name.strip():
                return 1.0
            # Entry matches but names are very different — could be a collision.
            # Still return high score since entry was exact.
            return 0.98

        # ── Stage 2: Year-sliding ──
        # Same branch (LLL) + same roll (NNNN), only year (YYYY) differs.
        # e.g. master has 2025CSB1454, OCR read 2024CSB1454.
        if len(e1) >= 10 and len(e2) >= 10 and e1[4:] == e2[4:]:
            # Branch+roll match, year differs
            try:
                y1, y2 = int(e1[:4]), int(e2[:4])
                if abs(y1 - y2) <= 3 and name_sim >= 0.50:
                    return 0.95
            except ValueError:
                pass

        # ── Stage 3: Combined entry Levenshtein + name similarity ──
        # Entry is close (1-2 edits) AND name clearly matches.
        # This catches OCR errors that the corrector couldn't fix.
        # Check distance on BOTH corrected and raw strings, because the 
        # aggressive length fixer might have mangled short raw strings.
        e1_raw = re.sub(r'[^A-Za-z0-9]', '', str(sheet_entry)).upper()
        e2_raw = re.sub(r'[^A-Za-z0-9]', '', str(ocr_entry)).upper()
        
        best_dist = 999
        if e1 and e2:
            best_dist = min(best_dist, cls._levenshtein_distance(e1, e2))
        if e1_raw and e2_raw:
            best_dist = min(best_dist, cls._levenshtein_distance(e1_raw, e2_raw))
            
        if best_dist <= 2 and name_sim >= 0.60:
            # Both entry and name are close — weighted combination.
            # Base the len on whichever was used (approx)
            max_elen = max(len(e1) if e1 else len(e1_raw), len(e2) if e2 else len(e2_raw), 1)
            entry_sim = 1.0 - (best_dist / max_elen)
            # Weight: entry number 40%, name 60% (name is more reliable here)
            score = entry_sim * 0.40 + name_sim * 0.60
            return round(min(score, 0.89), 4)  # Cap at 0.89 to rank below exact/year-slid

        # ── Stage 4: Raw uncorrected Levenshtein + name similarity ──
        # If the correction logic drastically mangled the entry (e.g. 20244B1376), we just compare the raw alphanumerics
        raw_e1 = re.sub(r'[^A-Za-z0-9]', '', sheet_entry).upper()
        raw_e2 = re.sub(r'[^A-Za-z0-9]', '', ocr_entry).upper()
        if raw_e1 and raw_e2:
            raw_dist = cls._levenshtein_distance(raw_e1, raw_e2)
            if raw_dist <= 2 and name_sim >= 0.50:
                max_elen = max(len(raw_e1), len(raw_e2), 1)
                entry_sim = 1.0 - (raw_dist / max_elen)
                score = entry_sim * 0.40 + name_sim * 0.60
                return round(min(score, 0.88), 4)

        # ── Stage 5: Dominant name similarity ──
        # If the student wrote their own roll number so poorly that the edit distance exceeds 2,
        # but their name almost completely matches the master list, assign a score based on name only.
        if name_sim >= 0.90:
            return round(min(name_sim * 0.85, 0.85), 4)  # Cap at 0.85, below entry-linked matches

        return 0.0

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

        # Side-effect: cache for rename fallback. Safe because `students` is
        # always a list of dicts here — no stale state leaks between requests.
        try:
            self._master_students_cache[sheet_url] = students
            self._last_master_url = sheet_url
        except Exception:
            pass

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
        # Uses lists to handle enrollment number collisions (multiple OCR
        # results with the same normalized enrollment number).
        results_map = {}       # normalized_entry -> list of result dicts
        _placeholder_counter = 0
        for r in results:
            # Sanitize in-place so downstream code sees clean values
            if isinstance(r, dict):
                r['entry_number'] = _sanitize(str(r.get('entry_number', '')))
                r['name'] = _sanitize(str(r.get('name', '')))
            raw = r.get('entry_number', '') if isinstance(r, dict) else ''
            normalized = self._normalize_entry_number(raw)
            if normalized:
                results_map.setdefault(normalized, []).append(r)
            elif r.get('name') or r.get('answers'):
                # No valid entry number but has other data — still include with a placeholder key
                placeholder_key = f"__noentry_{_placeholder_counter}"
                _placeholder_counter += 1
                results_map.setdefault(placeholder_key, []).append(r)

        # Build headers — include OCR-detected name/entry for cross-reference
        headers = ["Entry Number", "Name", "OCR Entry Number", "Processed Entry Number", "OCR Name"]
        for q in all_q_nums:
            headers.append(f"Q{q}")
        headers.append("Marks")
        headers.append("Comments")

        data_rows = []       # Each entry: (category, row_data)  category: 'confident', 'fuzzy', 'unmatched'
        all_scores = []
        
        summary = {
            "updated": 0,
            "not_found_in_sheet": [],
            "not_found_in_results": [],
            "name_mismatches": [],
            "errors": [],
            "sheet_tab": target_sheet,
            "statistics": {}
        }

        matched_results = set()  # set of (normalized_entry, index_in_list) tuples

        if master_students:
            # We have a master list to match against
            for student in master_students:
                raw_entry = student.get('entry_number', '')
                normalized = self._normalize_entry_number(raw_entry)
                result = None
                is_fuzzy_match = False

                # ═══ STAGE 1: Exact corrected entry number lookup ═══
                if normalized and normalized in results_map:
                    candidates = results_map[normalized]
                    available = [(i, c) for i, c in enumerate(candidates)
                                 if (normalized, i) not in matched_results]
                    if len(available) == 1:
                        idx, candidate = available[0]
                        result = candidate
                        matched_results.add((normalized, idx))
                    elif len(available) > 1:
                        # Collision: pick the candidate with the closest name
                        sheet_name_str = student.get('name', '').strip()
                        best_idx, best_candidate, best_sim = None, None, -1.0
                        for idx, c in available:
                            ocr_name_str = str(c.get('name', '')).strip()
                            sim = self._name_similarity(sheet_name_str, ocr_name_str)
                            if sim > best_sim:
                                best_sim = sim
                                best_idx = idx
                                best_candidate = c
                        if best_candidate is not None:
                            result = best_candidate
                            matched_results.add((normalized, best_idx))
                            if len(available) > 1:
                                print(f"  🔀 Collision for '{raw_entry}': picked '{best_candidate.get('name','')}' "
                                      f"(sim={best_sim:.2f}), {len(available)-1} other(s) remain")

                # ═══ STAGE 2: Year-sliding lookup ═══
                if not result and normalized and len(normalized) >= 10:
                    sheet_name_str = student.get('name', '').strip()
                    try:
                        base_year = int(normalized[:4])
                        for offset in [-1, 1, -2, 2, -3, 3]:
                            slid_key = str(base_year + offset) + normalized[4:]
                            if slid_key not in results_map:
                                continue
                            candidates = results_map[slid_key]
                            available = [(i, c) for i, c in enumerate(candidates)
                                         if (slid_key, i) not in matched_results]
                            if not available:
                                continue
                            # Pick best by name similarity, require >= 0.50
                            best_idx, best_candidate, best_sim = None, None, -1.0
                            for idx, c in available:
                                ocr_name_str = str(c.get('name', '')).strip()
                                sim = self._name_similarity(sheet_name_str, ocr_name_str)
                                if sim > best_sim:
                                    best_sim = sim
                                    best_idx = idx
                                    best_candidate = c
                            if best_candidate is not None and best_sim >= 0.50:
                                result = best_candidate
                                is_fuzzy_match = True
                                matched_results.add((slid_key, best_idx))
                                print(f"  📅 Year-slid: '{raw_entry}' → '{slid_key}' name '{best_candidate.get('name','')}'")
                                break
                    except ValueError:
                        pass

                # ═══ STAGE 3: Combined entry Levenshtein + name matching ═══
                if not result and raw_entry:
                    sheet_name_str = student.get('name', '').strip()
                    sheet_entry_str = str(raw_entry).strip()

                    best_match_id = None
                    best_match_r = None
                    best_score = 0.0

                    for norm_id, r_list in results_map.items():
                        for r_idx, r in enumerate(r_list):
                            if (norm_id, r_idx) in matched_results:
                                continue

                            ocr_name_str = r.get('name', '').strip()
                            ocr_entry_str = str(r.get('entry_number', '')).strip()

                            match_score = self._smart_match_score(
                                sheet_entry_str, sheet_name_str,
                                ocr_entry_str, ocr_name_str
                            )

                            if match_score >= 0.55 and match_score > best_score:
                                best_score = match_score
                                best_match_id = (norm_id, r_idx)
                                best_match_r = r

                    if best_match_r:
                        result = best_match_r
                        is_fuzzy_match = True
                        matched_results.add(best_match_id)
                        print(f"  🔗 Smart match: '{sheet_entry_str}' → '{best_match_r.get('entry_number', '')}' "
                              f"(score: {best_score:.2f})")
                        # If multiple candidates had the same best score with
                        # different names, the first found wins. The collision
                        # resolution above (Stage 1) handles same-key dups.

                row = [
                    raw_entry,
                    student.get('name', ''),
                ]

                if not result:
                    summary['not_found_in_results'].append(raw_entry)
                    row.extend(['', '', ''])  # OCR Entry, Processed Entry, OCR Name
                    for q in all_q_nums: row.append('')
                    row.append('') # Marks
                    row.append('Absent / No Answer Sheet Found')
                    data_rows.append(('unmatched', row))
                    continue

                # Add OCR-detected entry number and name
                ocr_entry = str(result.get('entry_number', '')).strip()
                processed_entry = self._correct_entry_number_ocr(ocr_entry)
                ocr_name = str(result.get('name', '')).strip()
                row.extend([ocr_entry, processed_entry, ocr_name])

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

                if is_fuzzy_match:
                    final_comments.append(f"Fuzzy Match: OCR ID='{ocr_entry}', OCR Name='{ocr_name}'")
                    summary['name_mismatches'].append({
                        "entry_number": raw_entry,
                        "sheet_name": student.get('name', ''),
                        "ocr_name": ocr_name,
                        "ocr_entry": ocr_entry,
                        "type": "fuzzy_match"
                    })
                elif mismatch_msg:
                    final_comments.append(mismatch_msg)
                    summary['name_mismatches'].append({
                        "entry_number": raw_entry,
                        "sheet_name": student.get('name', ''),
                        "ocr_name": ocr_name,
                        "ocr_entry": ocr_entry,
                        "type": "mismatch"
                    })
                
                # Per-question scores
                d_map = {}
                for d in result.get('details', []):
                    qn = d.get('question_number') if isinstance(d, dict) else getattr(d, 'question_number', None)
                    if qn: d_map[int(qn)] = d
                
                for q in all_q_nums:
                    d = d_map.get(q, {})
                    val = d.get('score', 0) if isinstance(d, dict) else getattr(d, 'score', 0)
                    row.append(val)
                
                total = result.get('total_score', 0)
                row.append(total)
                all_scores.append(total)
                
                row.append("; ".join(final_comments))

                # Categorize: confident (exact match) vs fuzzy
                category = 'fuzzy' if is_fuzzy_match else 'confident'
                data_rows.append((category, row))

        # Handle results that weren't matched in the master list, or if NO master list exists
        for norm_id, r_list in results_map.items():
            for r_idx, r in enumerate(r_list):
                if (norm_id, r_idx) in matched_results:
                    continue
                raw_entry = r.get('entry_number', '')
                processed_entry = self._correct_entry_number_ocr(raw_entry)
                ocr_name_unmatched = r.get('name', '')
                if master_students:
                    # Only report as not found if there was a master list to check against
                    summary['not_found_in_sheet'].append(raw_entry)
                summary['updated'] += 1
                
                if master_students:
                    row = [
                        "",              # Master Entry Number
                        "",              # Master Name
                        raw_entry,       # OCR Entry Number
                        processed_entry, # Processed Entry Number
                        ocr_name_unmatched,  # OCR Name
                    ]
                else:
                    row = [
                        raw_entry,
                        ocr_name_unmatched,
                        raw_entry,       # OCR Entry Number
                        processed_entry, # Processed Entry Number
                        ocr_name_unmatched,  # OCR Name
                    ]
                
                d_map = {}
                for d in r.get('details', []):
                    qn = d.get('question_number') if isinstance(d, dict) else getattr(d, 'question_number', None)
                    if qn: d_map[int(qn)] = d
                
                for q in all_q_nums:
                    d = d_map.get(q, {})
                    val = d.get('score', 0) if isinstance(d, dict) else getattr(d, 'score', 0)
                    row.append(val)
                
                total = r.get('total_score', 0)
                row.append(total)
                all_scores.append(total)
                
                final_comments = []
                if r.get('comments'): final_comments.append(r.get('comments'))
                if master_students:
                    final_comments.append("Not found in Master Student List")
                
                row.append("; ".join(final_comments))
                data_rows.append(('unmatched', row))

        # ── SORT: confident first, then fuzzy, then unmatched ──
        category_order = {'confident': 0, 'fuzzy': 1, 'unmatched': 2}
        data_rows.sort(key=lambda x: (category_order.get(x[0], 3), x[1][0]))  # secondary sort by entry number

        def _get_col_letter(col_idx: int) -> str:
            result = ""
            while col_idx >= 0:
                result = chr(col_idx % 26 + 65) + result
                col_idx = col_idx // 26 - 1
            return result

        start_col_letter = _get_col_letter(5)
        end_col_letter = _get_col_letter(5 + len(all_q_nums) - 1)
        marks_col_idx = 5 + len(all_q_nums)

        # Build final row list and compute formatting indices post-sort
        sorted_rows = []
        confident_rows = []
        fuzzy_rows = []
        unmatched_rows = []
        for i, (cat, row_data) in enumerate(data_rows):
            real_row_num = i + 2
            if len(all_q_nums) > 0:
                row_data[marks_col_idx] = f"=SUM({start_col_letter}{real_row_num}:{end_col_letter}{real_row_num})"
            sorted_rows.append(row_data)
            if cat == 'confident':
                confident_rows.append(i)
            elif cat == 'fuzzy':
                fuzzy_rows.append(i)
            elif cat == 'unmatched':
                unmatched_rows.append(i)

        print(f"  📊 Row sorting: {len(confident_rows)} confident, "
              f"{len(fuzzy_rows)} fuzzy, {len(unmatched_rows)} unmatched")

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

        marks_col_letter = _get_col_letter(marks_col_idx)
        data_start_row = 2
        data_end_row = len(sorted_rows) + 1

        mean_row = [''] * len(headers)
        mean_row[1] = 'Mean / Average'
        mean_row[marks_col_idx] = f"=AVERAGE({marks_col_letter}{data_start_row}:{marks_col_letter}{data_end_row})" if sorted_rows else 0

        median_row = [''] * len(headers)
        median_row[1] = 'Median'
        median_row[marks_col_idx] = f"=MEDIAN({marks_col_letter}{data_start_row}:{marks_col_letter}{data_end_row})" if sorted_rows else 0

        highest_row = [''] * len(headers)
        highest_row[1] = 'Highest'
        highest_row[marks_col_idx] = f"=MAX({marks_col_letter}{data_start_row}:{marks_col_letter}{data_end_row})" if sorted_rows else 0

        lowest_row = [''] * len(headers)
        lowest_row[1] = 'Lowest'
        lowest_row[marks_col_idx] = f"=MIN({marks_col_letter}{data_start_row}:{marks_col_letter}{data_end_row})" if sorted_rows else 0

        all_data = [headers] + sorted_rows + [empty_row, stats_label_row, mean_row, median_row, highest_row, lowest_row]

        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{target_sheet}'!A1",
            valueInputOption='USER_ENTERED',
            body={'values': all_data}
        ).execute()

        self._format_marks_sheet(spreadsheet_id, target_sheet, len(headers), len(sorted_rows), len(all_data), confident_rows, fuzzy_rows, unmatched_rows)

        print(f"✅ Wrote {len(sorted_rows)} students to '{target_sheet}'. Matches: {summary['updated']}, Fuzzy: {len(fuzzy_rows)}, Unmatched: {len(unmatched_rows)}")
        return summary

    def _format_marks_sheet(self, spreadsheet_id: str, sheet_name: str, num_cols: int, num_data_rows: int, total_rows: int, confident_rows: List[int] = None, fuzzy_rows: List[int] = None, unmatched_rows: List[int] = None):
        """Apply formatting to the marks sheet — bold header, statistics, and highlights for mismatches."""
        confident_rows = confident_rows or []
        fuzzy_rows = fuzzy_rows or []
        unmatched_rows = unmatched_rows or []
        
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

            # Formatting for confident matches (COMPLETE ENTRY NUMBER MATCHES BLACK)
            if confident_rows:
                for r_idx in confident_rows:
                    real_row = r_idx + 1
                    requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': sheet_id,
                                'startRowIndex': real_row, 'endRowIndex': real_row + 1,
                                'startColumnIndex': 0, 'endColumnIndex': num_cols
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'backgroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0},
                                    'textFormat': {
                                        'bold': False,
                                        'foregroundColor': {'red': 0.0, 'green': 0.0, 'blue': 0.0}
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat(backgroundColor,textFormat)'
                        }
                    })

            # Formatting for fuzzy matches (FUZZY MATCHES RED)
            if fuzzy_rows:
                for r_idx in fuzzy_rows:
                    real_row = r_idx + 1
                    requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': sheet_id,
                                'startRowIndex': real_row, 'endRowIndex': real_row + 1,
                                'startColumnIndex': 0, 'endColumnIndex': num_cols
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'backgroundColor': {'red': 1.0, 'green': 0.9, 'blue': 0.9},
                                    'textFormat': {
                                        'bold': True,
                                        'foregroundColor': {'red': 0.8, 'green': 0.0, 'blue': 0.0}
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat(backgroundColor,textFormat)'
                        }
                    })

            # Formatting for unmatched rows (Different color)
            if unmatched_rows:
                for r_idx in unmatched_rows:
                    real_row = r_idx + 1
                    requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': sheet_id,
                                'startRowIndex': real_row, 'endRowIndex': real_row + 1,
                                'startColumnIndex': 0, 'endColumnIndex': num_cols
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'backgroundColor': {'red': 1.0, 'green': 0.95, 'blue': 0.8},
                                    'textFormat': {
                                        'bold': True,
                                        'foregroundColor': {'red': 0.9, 'green': 0.4, 'blue': 0.0}
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat(backgroundColor,textFormat)'
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

    def sync_results_with_master(self, sheet_url: str, results: List[Dict], subsheet_name: str = None) -> List[Dict]:
        """Matches OCR results against the master sheet and returns updated results.
        If subsheet_name is provided, also syncs marks and comments from the exported sheet tab.
        """
        try:
            sheet_data = self.read_student_list(sheet_url)
            master_students = sheet_data.get('students', [])
        except Exception:
            master_students = []

        if not master_students:
            return results

        results_map = {}
        _UNKNOWN_PLACEHOLDERS = {'unknown', 'n/a', 'none', 'null'}
        def _sanitize(val: str) -> str:
            stripped = (val or '').strip()
            return '' if stripped.lower() in _UNKNOWN_PLACEHOLDERS else stripped

        import copy
        results_copy = copy.deepcopy(results)
        _placeholder_counter = 0

        for i, r in enumerate(results_copy):
            # Try to grab dictionary if it's a Pydantic model
            r_dict = r if isinstance(r, dict) else (r.dict() if hasattr(r, 'dict') else r)
            if not isinstance(r_dict, dict):
                continue
            raw = (r_dict.get('entry_number') or r_dict.get('students', {}).get('roll_number') or '')
            raw = _sanitize(str(raw))
            norm = self._normalize_entry_number(raw)
            if norm:
                results_map.setdefault(norm, []).append((i, r_dict))
            elif r_dict.get('name') or r_dict.get('answers'):
                results_map.setdefault(f"__noentry_{_placeholder_counter}", []).append((i, r_dict))
                _placeholder_counter += 1

        matched_results = set()
        for student in master_students:
            raw_entry = student.get('entry_number', '')
            normalized = self._normalize_entry_number(raw_entry)
            result_idx = None
            result = None

            # STAGE 1
            if normalized and normalized in results_map:
                candidates = results_map[normalized]
                available = [(idx, c) for idx, c in candidates if (normalized, idx) not in matched_results]
                if len(available) == 1:
                    result_idx, result = available[0]
                    matched_results.add((normalized, result_idx))
                elif len(available) > 1:
                    sheet_name_str = student.get('name', '').strip()
                    best_idx, best_candidate, best_sim = None, None, -1.0
                    for idx, c in available:
                        sim = self._name_similarity(sheet_name_str, str(c.get('name', '')).strip())
                        if sim > best_sim:
                            best_sim, best_idx, best_candidate = sim, idx, c
                    if best_candidate is not None:
                        result_idx, result = best_idx, best_candidate
                        matched_results.add((normalized, best_idx))

            # STAGE 2
            if not result and normalized and len(normalized) >= 10:
                sheet_name_str = student.get('name', '').strip()
                try:
                    base_year = int(normalized[:4])
                    for offset in [-1, 1, -2, 2, -3, 3]:
                        slid_key = str(base_year + offset) + normalized[4:]
                        if slid_key not in results_map: continue
                        available = [(idx, c) for idx, c in results_map[slid_key] if (slid_key, idx) not in matched_results]
                        if not available: continue
                        best_idx, best_candidate, best_sim = None, None, -1.0
                        for idx, c in available:
                            sim = self._name_similarity(sheet_name_str, str(c.get('name', '')).strip())
                            if sim > best_sim:
                                best_sim, best_idx, best_candidate = sim, idx, c
                        if best_candidate is not None and best_sim >= 0.50:
                            result_idx, result = best_idx, best_candidate
                            matched_results.add((slid_key, best_idx))
                            break
                except ValueError: pass

            # STAGE 3
            if not result and raw_entry:
                sheet_name_str = student.get('name', '').strip()
                sheet_entry_str = str(raw_entry).strip()
                best_match_id = None
                best_match_r = None
                best_score = 0.0

                for norm_id, r_list in results_map.items():
                    for idx, r_candidate in r_list:
                        if (norm_id, idx) in matched_results: continue
                        match_score = self._smart_match_score(
                            sheet_entry_str, sheet_name_str,
                            str(r_candidate.get('entry_number', '')).strip(),
                            str(r_candidate.get('name', '')).strip()
                        )
                        if match_score >= 0.55 and match_score > best_score:
                            best_score, best_match_id, best_match_r = match_score, (norm_id, idx), r_candidate
                if best_match_r:
                    norm_id, idx = best_match_id
                    result_idx, result = idx, best_match_r
                    matched_results.add(best_match_id)

            if result:
                # Update the result OCR with true attributes
                # Note: 'entry_number', 'name' are saved back so frontend gets the fixed version.
                result['ocr_entry_number'] = result.get('entry_number', '')
                result['ocr_name'] = result.get('name', '')
                result['entry_number'] = raw_entry
                result['name'] = student.get('name', '')
                # Re-assign back to list in case it's a completely new dict
                results_copy[result_idx] = result
                
        if subsheet_name and self.service:
            # Sync scores & comments from the exported sheet!
            spreadsheet_id, _ = self.parse_sheet_url(sheet_url)
            try:
                sheet_values = self.service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{subsheet_name}'"
                ).execute().get('values', [])
                
                if sheet_values and len(sheet_values) > 0:
                    headers = sheet_values[0]
                    # Find column indices
                    entry_col = headers.index("Entry Number") if "Entry Number" in headers else -1
                    name_col = headers.index("Name") if "Name" in headers else -1
                    ocr_entry_col = headers.index("OCR Entry Number") if "OCR Entry Number" in headers else -1
                    marks_col = headers.index("Marks") if "Marks" in headers else -1
                    comments_col = headers.index("Comments") if "Comments" in headers else -1
                    
                    q_cols = {}
                    for idx, h in enumerate(headers):
                        if h.startswith("Q") and h[1:].isdigit():
                            q_cols[int(h[1:])] = idx
                            
                    # Now update the results mapping
                    for r in results_copy:
                        matched_row = None
                        r_entry = str(r.get('entry_number', '')).strip()
                        r_ocr_entry = str(r.get('ocr_entry_number', '')).strip()
                        
                        # Find best match from rows
                        for row in sheet_values[1:]:
                            entry_val = str(self._safe_get(row, entry_col, '')).strip()
                            ocr_entry_val = str(self._safe_get(row, ocr_entry_col, '')).strip()
                            
                            # Priority 1: Match by invariant OCR Entry
                            if r_ocr_entry and ocr_entry_val and r_ocr_entry == ocr_entry_val:
                                matched_row = row
                                break
                            # Priority 2: Match by latest/resolved Entry
                            elif r_entry and entry_val and r_entry == entry_val:
                                matched_row = row
                                break
                            # Priority 3: Cross-match
                            elif r_entry and ocr_entry_val and r_entry == ocr_entry_val:
                                matched_row = row
                                break

                        if matched_row:
                            row = matched_row
                            
                            # Extract true Name and Entry Number directly from the Quiz sheet!
                            if entry_col != -1 and len(row) > entry_col and row[entry_col].strip():
                                r['entry_number'] = row[entry_col].strip()
                            if name_col != -1 and len(row) > name_col and row[name_col].strip():
                                r['name'] = row[name_col].strip()
                            
                            # NOTE: We do NOT overwrite total_score from the subsheet.
                            # The subsheet may contain stale scores from a previous single-page run.
                            # The freshly computed score from this pipeline run is always authoritative.
                            # Scores from the subsheet are only used when viewing historical exports,
                            # not during a live evaluation result sync.
                                    
                            # Parse comments only (safe to override — not computed by pipeline)
                            if comments_col != -1 and len(row) > comments_col:
                                r['comments'] = row[comments_col]
                                
                            # Parse Q marks
                            if 'details' not in r:
                                r['details'] = []
                                
                            # Convert existing details list into dict by question_number
                            d_map = {d.get('question_number'): d for d in r['details'] if isinstance(d, dict)}
                            
                            for qn, col_idx in q_cols.items():
                                if len(row) > col_idx:
                                    try:
                                        sc = float(row[col_idx])
                                        if qn in d_map:
                                            d_map[qn]['score'] = sc
                                        else:
                                            d_map[qn] = {'question_number': qn, 'score': sc}
                                    except ValueError:
                                        pass
                                        
                            r['details'] = list(d_map.values())
            except Exception as e:
                print(f"Failed to sync from subsheet {subsheet_name}: {e}")

        return results_copy
