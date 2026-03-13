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
import socket
import difflib
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import List, Dict, Optional, Tuple, Any

# --- CRITICAL NETWORK FIX ---
# The host environment blackholes IPv6 traffic to www.googleapis.com, causing 
# 120-second hangs on every API call before falling back to IPv4. 
# This monkeypatch forces all Python sockets to use IPv4 by default.
old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return old_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = new_getaddrinfo
# ----------------------------


class SheetsService:
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',  # Read + Write
    ]

    # Aliases for auto-detecting column headers
    ENTRY_NUMBER_ALIASES = {
        'entry number', 'entry_number', 'entry no', 'entry no.',
        'roll number', 'roll_number', 'roll no', 'roll no.',
        'enrollment', 'enrollment number', 'enrollment no',
        'id', 'student id', 'student_id', 'reg number',
        'registration number', 'reg no', 'reg no.',
    }

    NAME_ALIASES = {
        'name', 'student name', 'student_name', 'full name',
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
                # Override token URI to bypass blocked oauth2.googleapis.com domain
                self.creds._token_uri = "https://www.googleapis.com/oauth2/v4/token"
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
    #  Entry Number Normalization
    # ──────────────────────────────────────

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

    # ──────────────────────────────────────
    #  Name Cross-Verification
    # ──────────────────────────────────────

    @staticmethod
    def _check_name_mismatch(sheet_name: str, ocr_name: str, entry_number: str, row: int) -> Optional[str]:
        """Returns mismatch message string if names don't match."""
        if not sheet_name or not ocr_name:
            return None

        s = sheet_name.strip().lower()
        o = ocr_name.strip().lower()

        if not s or not o or s == 'unknown' or o == 'unknown':
            return None

        if s == o: return None
        
        s_parts = set(s.split())
        o_parts = set(o.split())
        if s_parts.intersection(o_parts): return None

        if s in o or o in s: return None

        for word in s_parts:
            if len(word) >= 3 and word in o: return None
        for word in o_parts:
            if len(word) >= 3 and word in s: return None

        return f"Name mismatch: Sheet='{sheet_name}' vs OCR='{ocr_name}'"

    # ──────────────────────────────────────
    #  Reading Student List
    # ──────────────────────────────────────

    def read_student_list(self, sheet_url: str, sheet_name_override: Optional[str] = None, require_student_names_tab: bool = False) -> Dict:
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

        existing_titles = [s['properties']['title'] for s in sheets]

        if require_student_names_tab:
            if 'student_names' not in existing_titles:
                raise ValueError("A tab named 'student_names' was not found in the master sheet. Please create one to manage the student roster.")
            sheet_name = 'student_names'
        elif sheet_name_override:
            sheet_name = sheet_name_override
        elif not sheet_name:
            sheet_name = existing_titles[0]

        range_name = f"'{sheet_name}'"
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()

        values = result.get('values', [])
        if not values or len(values) < 1:
            # Sheet is completely empty — return empty result so callers can populate it
            return {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "columns": {},
                "students": [],
            }

        headers = values[0]
        columns = self._detect_columns(headers)

        if not columns.get('entry_number'):
            # Headers exist but no entry number column detected — return empty
            # instead of crashing so update_marks can still append new students
            return {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "columns": columns,
                "students": [],
            }

        students = []
        entry_col = columns['entry_number']['index']
        name_col = columns.get('name', {}).get('index')
        comments_col = columns.get('comments', {}).get('index')

        for row_idx, row in enumerate(values[1:], start=2):
            entry_number = self._safe_get(row, entry_col, '').strip()
            if not entry_number:
                continue
                
            # Ignore statistics summary rows
            if entry_number.upper() in ("STATISTICS", "MEAN", "MEDIAN", "HIGHEST", "LOWEST", "MEAN / AVERAGE"):
                continue

            name = self._safe_get(row, name_col, '').strip() if name_col is not None else ''
            
            # The user explicitly wants to only import entries that have a value under "Name"
            if not name:
                continue
                
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
        }

    # ──────────────────────────────────────
    #  Writing Marks
    # ──────────────────────────────────────

    def update_marks(self, sheet_url: str, results: List[Dict], subsheet_name: Optional[str] = None) -> Dict:
        """
        Write marks, comments, AND per-question scores.
        """
        if not self.service:
            raise RuntimeError("Sheets service not initialized. Check credentials.")

        if subsheet_name:
            # Figure out total_questions dynamically to generate headers
            max_q = 0
            for r in results:
                details = r.get('details', [])
                for d in details:
                    try:
                        qn = int(d.get('question_number', 0)) if isinstance(d, dict) else int(getattr(d, 'question_number', 0))
                        if qn > max_q: max_q = qn
                    except (ValueError, TypeError, AttributeError):
                        pass
                        
            self.create_sheet_if_not_exists(sheet_url, subsheet_name, total_questions=max_q)

        # Read current state
        sheet_data = self.read_student_list(sheet_url, subsheet_name)
        spreadsheet_id = sheet_data['spreadsheet_id']
        sheet_name = sheet_data['sheet_name']
        columns = sheet_data['columns']
        students = sheet_data['students']

        # If the sheet has no columns detected (completely empty or no headers),
        # we should not crash — create headers from the results instead.
        if not columns.get('entry_number') or not columns.get('marks'):
            # The sheet is missing required columns; create_sheet_if_not_exists
            # should have handled this, but if not, build and write headers now.
            max_q = 0
            for r in results:
                details = r.get('details', [])
                for d in details:
                    try:
                        qn = int(d.get('question_number', 0)) if isinstance(d, dict) else int(getattr(d, 'question_number', 0))
                        if qn > max_q: max_q = qn
                    except (ValueError, TypeError, AttributeError):
                        pass
            headers_row = ["Entry Number", "Name"]
            if max_q > 0:
                headers_row.extend([f"Q{i}" for i in range(1, max_q + 1)])
            headers_row.extend(["Marks", "Comments"])

            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_name}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [headers_row]}
            ).execute()

            # Re-read the sheet to get proper column detection
            sheet_data = self.read_student_list(sheet_url, subsheet_name)
            columns = sheet_data['columns']
            students = sheet_data['students']

            if not columns.get('marks'):
                raise ValueError("No 'marks' column detected even after writing headers.")

        marks_col_letter = columns['marks']['letter']
        comments_col_letter = columns.get('comments', {}).get('letter')
        question_cols = columns.get('questions', {}) # Dict[int, Dict] {1: {index, letter}, ...}

        # Build lookup: normalized_entry_number -> result dict
        results_map = {}
        for r in results:
            raw = str(r.get('entry_number', '')).strip()
            normalized = self._normalize_entry_number(raw)
            if normalized:
                results_map[normalized] = r

        summary = {
            "updated": 0,
            "not_found_in_sheet": [],
            "not_found_in_results": [],
            "name_mismatches": [],
            "errors": [],
            "has_mismatches": False
        }

        batch_data = []
        matched_normalized = set()   # result keys that have been claimed
        consumed_results = set()     # result keys actually written
        rows_to_bold = set()

        # ── Pre-matching pass ──
        # Match sheet students to results by EXACT or FUZZY entry number AND name
        def _fuzzy_match(s1, s2, threshold=0.85):
            if not s1 or not s2: return False
            return difflib.SequenceMatcher(None, s1, s2).ratio() >= threshold

        def _find_best_match(student_entry, student_name):
            student_name_clean = student_name.strip().lower()
            norm_student_entry = self._normalize_entry_number(student_entry)
            
            best_key = None
            best_score = 0
            
            for norm_key, r in results_map.items():
                if norm_key in matched_normalized: continue
                ocr_name = r.get('name', '').strip().lower()
                
                score = 0
                
                # 1. Score Entry Number
                if norm_student_entry and norm_key:
                    if norm_student_entry == norm_key:
                        score += 100
                    else:
                        ratio = difflib.SequenceMatcher(None, norm_student_entry, norm_key).ratio()
                        if ratio >= 0.75:
                            score += int(50 * ratio)
                            
                # 2. Score Name
                if student_name_clean and ocr_name:
                    if student_name_clean == ocr_name:
                        score += 100
                    else:
                        ratio = difflib.SequenceMatcher(None, student_name_clean, ocr_name).ratio()
                        if ratio >= 0.75:
                            score += int(50 * ratio)
                        else:
                            # Word intersection fallback
                            s_parts = set(student_name_clean.split())
                            o_parts = set(ocr_name.split())
                            intersection = s_parts.intersection(o_parts)
                            if len(intersection) >= 2 or (len(intersection) >= 1 and len(s_parts) == 1 and len(o_parts) == 1):
                                score += 30
                                
                # Pick the highest scoring match that is at least a decent fuzzy match or word match
                if score > best_score and score >= 40:
                    best_score = score
                    best_key = norm_key
                    
            return best_key

        # Determine best match for every existing student in the roster
        for student in students:
            best_key = _find_best_match(student.get('entry_number', ''), student.get('name', ''))
            student['matched_result_key'] = best_key
            if best_key:
                matched_normalized.add(best_key)

        # ── Append pass ──
        # Only append results that were NOT matched in the pre-pass
        last_row = max((s['row'] for s in students), default=1)
        for normalized, result in results_map.items():
            if normalized not in matched_normalized:
                last_row += 1
                students.append({
                    "row": last_row,
                    "entry_number": result.get('entry_number', ''),
                    "name": result.get('name', ''),
                    "existing_comment": "",
                    "is_new": True,
                    "matched_result_key": normalized
                })

        # DEBUG
        print(f"DEBUG: Results Map Keys: {list(results_map.keys())}")
        print(f"DEBUG: Matched (pre-pass): {matched_normalized}")

        # ── Main loop: write marks ──
        for student in students:
            is_new = student.get('is_new', False)
            if is_new:
                summary['has_mismatches'] = True
                rows_to_bold.add(student['row'])
                # Batch write their entry_number and name
                entry_col_letter = columns['entry_number']['letter']
                batch_data.append({"range": f"'{sheet_name}'!{entry_col_letter}{student['row']}", "values": [[student['entry_number']]]})
                if 'name' in columns:
                    name_col_letter = columns['name']['letter']
                    batch_data.append({"range": f"'{sheet_name}'!{name_col_letter}{student['row']}", "values": [[student['name']]]})
            
            res_key = student.get('matched_result_key')
            result = results_map.get(res_key) if res_key else None

            if not result:
                # If there's no result for this student (and they aren't new), just skip them.
                continue

            if res_key in consumed_results:
                continue # Prevent duplicate processing

            consumed_results.add(res_key)

            # Check for name mismatches if they aren't marked as purely new
            mismatch_reason = None
            if not is_new:
                mismatch_reason = self._check_name_mismatch(
                    sheet_name=student.get('name', ''),
                    ocr_name=result.get('name', ''),
                    entry_number=result.get('entry_number', ''),
                    row=student['row']
                )
                if mismatch_reason:
                    summary['name_mismatches'].append({
                        "entry_number": result.get('entry_number', ''),
                        "sheet_name": student.get('name', ''),
                        "ocr_name": result.get('name', ''),
                        "row": student['row']
                    })
                    summary['has_mismatches'] = True
                    rows_to_bold.add(student['row'])
            
            score = result.get('total_score', 0)
            details = result.get('details', []) # List of dicts/objects
            
            # Compose comment
            final_comments = []
            ocr_comment = result.get('comments', '')
            if ocr_comment:
                final_comments.append(ocr_comment)

            if mismatch_reason:
                final_comments.append(mismatch_reason)
            
            comment_str = "; ".join(final_comments)

            # 1. Update Total Score
            batch_data.append({
                "range": f"'{sheet_name}'!{marks_col_letter}{student['row']}",
                "values": [[score]]
            })
            
            # 2. Update Comment
            if comments_col_letter:
                batch_data.append({
                    "range": f"'{sheet_name}'!{comments_col_letter}{student['row']}",
                    "values": [[comment_str]]
                })

            # 3. Update Per-Question Scores
            q_map = {}
            if isinstance(details, list):
                for d in details:
                    try:
                        if isinstance(d, dict):
                            qn = int(d.get('question_number', -1))
                            q_map[qn] = d
                        else:
                            qn = int(d.question_number)
                            q_map[qn] = d
                    except (ValueError, TypeError, AttributeError):
                        continue
            
            # DEBUG: Print details for the first matched student
            if len(matched_normalized) == 1:
                print(f"🔍 DEBUG: Inspecting first student {student['entry_number']}")
                print(f"   Details count: {len(details)}")
                print(f"   Q_MAP keys (int): {list(q_map.keys())}")
                print(f"   Question Cols keys (int): {list(question_cols.keys())}")
                
            for q_num, col_info in question_cols.items():
                col_letter = col_info['letter']
                
                if q_num in q_map:
                    q_data = q_map[q_num]
                    val_to_write = 0
                    
                    if isinstance(q_data, dict):
                        status = q_data.get('result', '')
                        val = q_data.get('score', 0)
                    else:
                        status = getattr(q_data, 'result', '')
                        val = getattr(q_data, 'score', 0)
                    
                    if status in ['multiple', 'unattempted', 'incorrect']:
                        val_to_write = 0
                    elif status == 'correct':
                        val_to_write = val # Should be full marks
                    else:
                         # Default fallback
                        val_to_write = val
                    
                    # Add to batch
                    batch_data.append({
                        "range": f"'{sheet_name}'!{col_letter}{student['row']}",
                        "values": [[val_to_write]]
                    })
                else:
                    # If the student didn't have data for this question (e.g. absent/error or not in answer key?)
                    # We can choose to write 0 or leave blank.
                    pass

        # Execute batch update
        if batch_data:
            try:
                # Split huge batches if necessary (Google limit is around 50k calls?? No, payload size)
                # Chunking 1000 updates at a time is safer
                chunk_size = 500
                for i in range(0, len(batch_data), chunk_size):
                    chunk = batch_data[i:i + chunk_size]
                    body = {
                        "valueInputOption": "RAW",
                        "data": chunk,
                    }
                    self.service.spreadsheets().values().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body=body
                    ).execute()
                
                summary['updated'] = len(matched_normalized)
                print(f"✅ Updated {len(batch_data)} cells for {len(matched_normalized)} students.")
            except Exception as e:
                summary['errors'].append(f"Batch update failed: {str(e)}")
                print(f"❌ Batch update failed: {e}")

            # Apply bold formatting
            if rows_to_bold:
                try:
                    sheet_metadata = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
                    sheet_id = None
                    for s in sheet_metadata.get('sheets', []):
                        if s['properties']['title'] == sheet_name:
                            sheet_id = s['properties']['sheetId']
                            break
                    if sheet_id is not None:
                        requests = []
                        for row_num in rows_to_bold:
                            requests.append({
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sheet_id),
                                        "startRowIndex": int(row_num) - 1,
                                        "endRowIndex": int(row_num)
                                    },
                                    "cell": {
                                        "userEnteredFormat": {
                                            "textFormat": {"bold": True}
                                        }
                                    },
                                    "fields": "userEnteredFormat.textFormat.bold",
                                }
                            })
                        if requests:
                            self.service.spreadsheets().batchUpdate(
                                spreadsheetId=spreadsheet_id,
                                body={"requests": requests}
                            ).execute()
                except Exception as e:
                    summary['errors'].append(f"⚠️ Failed to apply bold formatting: {str(e)}")
                    print(f"⚠️ Failed to apply bold formatting: {e}")

            # Calculate and append statistics to the sheet
            self._append_statistics(spreadsheet_id, sheet_name, students, columns, results_map)

        return summary

    def _append_statistics(self, spreadsheet_id: str, sheet_name: str, students: List[Dict], columns: Dict, results_map: Dict):
        """Calculates and appends Mean, Median, Highest, and Lowest at the bottom of the sheet using formulas."""
        if not students: return
        
        # Find the last student row
        start_row = 2
        last_row = max(s['row'] for s in students)
        if last_row < start_row: return
        start_stat_row = last_row + 2
        
        marks_col_letter = columns['marks']['letter']
        name_col_letter = columns.get('name', {}).get('letter', 'A') # Fallback to A
        
        range_str = f"{marks_col_letter}{start_row}:{marks_col_letter}{last_row}"
        
        # Build batch data for stats using native Google sheet formulas
        stats_data = [
            {"range": f"'{sheet_name}'!{name_col_letter}{start_stat_row}", "values": [["STATISTICS"]]},
            {"range": f"'{sheet_name}'!{name_col_letter}{start_stat_row+1}", "values": [["Mean / Average"]]},
            {"range": f"'{sheet_name}'!{marks_col_letter}{start_stat_row+1}", "values": [[f"=IFERROR(ROUND(AVERAGE({range_str}), 2), 0)"]]},
            {"range": f"'{sheet_name}'!{name_col_letter}{start_stat_row+2}", "values": [["Median"]]},
            {"range": f"'{sheet_name}'!{marks_col_letter}{start_stat_row+2}", "values": [[f"=IFERROR(ROUND(MEDIAN({range_str}), 2), 0)"]]},
            {"range": f"'{sheet_name}'!{name_col_letter}{start_stat_row+3}", "values": [["Highest"]]},
            {"range": f"'{sheet_name}'!{marks_col_letter}{start_stat_row+3}", "values": [[f"=IFERROR(MAX({range_str}), 0)"]]},
            {"range": f"'{sheet_name}'!{name_col_letter}{start_stat_row+4}", "values": [["Lowest"]]},
            {"range": f"'{sheet_name}'!{marks_col_letter}{start_stat_row+4}", "values": [[f"=IFERROR(MIN({range_str}), 0)"]]},
        ]

        try:
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": stats_data}
            ).execute()
        except Exception as e:
            print(f"❌ Failed to append stats to {sheet_name}: {e}")

    def export_student_responses(self, sheet_url: str, results: List[Dict], ak_answers_map: Dict, evaluation_name: str):
        """
        Creates a new sheet named studentResponse_<evaluation_name> and writes
        every student's chosen answer for each question, with the answer key at the bottom.
        
        ak_answers_map: Dict[int, str] — {question_number: correct_answer}
        """
        if not self.service: return
        spreadsheet_id, _ = self.parse_sheet_url(sheet_url)
        
        target_sheet_name = f"studentResponse_{evaluation_name}"

        # Ensure ak_answers_map is a plain dict (int keys -> str values)
        if ak_answers_map is None:
            ak_answers_map = {}
        
        # 1. Create or clear the sheet
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_sheets = {s['properties']['title']: s['properties']['sheetId'] for s in spreadsheet.get('sheets', [])}
        
        if target_sheet_name not in existing_sheets:
            try:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"requests": [{"addSheet": {"properties": {"title": target_sheet_name}}}]}
                ).execute()
            except Exception as e:
                print(f"Failed to create response sheet: {e}")
                return
        else:
            self.service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{target_sheet_name}'"
            ).execute()

        # 2. Determine max question number
        max_q = max(ak_answers_map.keys(), default=0)
        # Also check from student details
        for r in results:
            details = r.get('details') or []
            for d in details:
                try:
                    qn = int(d.get('question_number', 0)) if isinstance(d, dict) else int(getattr(d, 'question_number', 0))
                    if qn > max_q:
                        max_q = qn
                except (ValueError, TypeError):
                    pass
                
        if max_q == 0:
            print("No questions found to export responses.")
            return

        headers = ["Entry Number", "Name"] + [f"Q{i}" for i in range(1, max_q + 1)]
        rows = [headers]
        
        # Populate student rows
        for r in results:
            entry = r.get('entry_number', '')
            name = r.get('name', '')
            details = r.get('details') or []
            
            # Build question -> chosen_option map from details
            student_choices = {}
            for d in details:
                try:
                    qn = int(d.get('question_number', 0)) if isinstance(d, dict) else int(getattr(d, 'question_number', 0))
                    choice = (d.get('chosen_option') or d.get('student_answer', '')) if isinstance(d, dict) else (getattr(d, 'chosen_option', '') or getattr(d, 'student_answer', ''))
                    student_choices[qn] = str(choice) if choice else ""
                except (ValueError, TypeError):
                    pass
                
            row_data = [entry, name] + [student_choices.get(i, "") for i in range(1, max_q + 1)]
            rows.append(row_data)
            
        # 3. Answer Key row
        ak_row = ["Answer Key", ""] + [str(ak_answers_map.get(i, "")) for i in range(1, max_q + 1)]
        rows.append([])  # spacer row
        rows.append(ak_row)
        
        # 4. Write data
        try:
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{target_sheet_name}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": rows}
            ).execute()
            
            # Apply bold formatting to Header and Answer Key rows
            sheet_id = next(
                (s['properties']['sheetId'] for s in
                 self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute().get('sheets', [])
                 if s['properties']['title'] == target_sheet_name), None
            )
            
            if sheet_id is not None:
                ak_row_index = len(rows) - 1  # 0-indexed
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "repeatCell": {
                                    "range": {"sheetId": sheet_id, "startRowIndex": ak_row_index, "endRowIndex": ak_row_index + 1},
                                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}},
                                    "fields": "userEnteredFormat(textFormat.bold,backgroundColor)"
                                }
                            },
                            {
                                "repeatCell": {
                                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}}},
                                    "fields": "userEnteredFormat(textFormat.bold,backgroundColor)"
                                }
                            }
                        ]
                    }
                ).execute()
                
            print(f"✅ Student responses sheet '{target_sheet_name}' written with {len(results)} students and {max_q} questions.")
                
        except Exception as e:
            print(f"Failed to populate response sheet: {e}")

    # ──────────────────────────────────────
    #  Tab Creation & Super Sheet
    # ──────────────────────────────────────


    def create_sheet_if_not_exists(self, sheet_url: str, sheet_name: str, total_questions: int = 0) -> bool:
        """Creates a new sheet tab if it doesn't exist. Copies header from first sheet if possible."""
        if not self.service:
             raise RuntimeError("Sheets service not initialized.")
        spreadsheet_id, _ = self.parse_sheet_url(sheet_url)
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        
        existing_sheets = [s['properties']['title'] for s in spreadsheet.get('sheets', [])]
        
        needs_creation = False
        needs_population = False
        
        if sheet_name not in existing_sheets:
            needs_creation = True
            needs_population = True
        else:
            # Check if it's empty or missing marks
            try:
                sheet_data = self.service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'"
                ).execute()
                values = sheet_data.get('values', [])
                if not values or len(values) == 0:
                    needs_population = True
                else:
                    columns = self._detect_columns(values[0])
                    if not columns.get('entry_number') or not columns.get('marks'):
                        needs_population = True
            except Exception:
                pass
                
        if not needs_creation and not needs_population:
            return False # Already exists and has data/headers
            
        # Build dynamic headers based on total_questions
        headers = ["Entry Number", "Name"]
        if total_questions > 0:
            headers.extend([f"Q{i}" for i in range(1, total_questions + 1)])
        headers.extend(["Marks", "Comments"])
        
        # Helper: populate a sheet tab with headers (+ students from student_names if available)
        def _populate_tab(target_sheet_name):
            """Write headers and optionally copy student list from student_names."""
            # Only copy from student_names tab. If it doesn't exist, evaluation fallback will happen.
            if "student_names" in existing_sheets:
                try:
                    first_sheet_name = "student_names"
                    first_sheet_data = self.service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id, range=f"'{first_sheet_name}'"
                    ).execute()
                    values = first_sheet_data.get('values', [])
                    
                    if values and len(values) > 0:
                        columns = self._detect_columns(values[0])
                        entry_idx = columns.get('entry_number', {}).get('index')
                        name_idx = columns.get('name', {}).get('index')
                        
                        new_values = []
                        if entry_idx is not None:
                            for i, row in enumerate(values):
                                if i == 0:
                                    new_values.append(headers)
                                else:
                                    entry = self._safe_get(row, entry_idx, "").strip()
                                    if entry.upper() in ("STATISTICS", "MEAN", "MEDIAN", "HIGHEST", "LOWEST", "MEAN / AVERAGE"):
                                        break
                                    name = self._safe_get(row, name_idx, "") if name_idx is not None else ""
                                    empty_row = [entry, name] + [""] * (len(headers) - 2)
                                    new_values.append(empty_row)
                                    
                            self.service.spreadsheets().values().update(
                                spreadsheetId=spreadsheet_id,
                                range=f"'{target_sheet_name}'!A1",
                                valueInputOption="USER_ENTERED",
                                body={"values": new_values}
                            ).execute()
                            return
                except Exception as e:
                    print(f"⚠️ Could not copy from existing sheet: {e}")
                    
            # Fallback: just write headers
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{target_sheet_name}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [headers]}
            ).execute()
        
        # Create the tab if it doesn't exist
        if needs_creation:
            try:
                request_body = {
                    "requests": [{
                        "addSheet": {
                            "properties": {"title": sheet_name}
                        }
                    }]
                }
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id, body=request_body
                ).execute()
                _populate_tab(sheet_name)
            except Exception as e:
                 raise RuntimeError(f"Failed to create/populate sheet: {e}")
        elif needs_population:
            # Tab exists but is empty or missing required columns — populate it
            try:
                _populate_tab(sheet_name)
            except Exception as e:
                raise RuntimeError(f"Failed to populate existing empty sheet '{sheet_name}': {e}")
                 
        return True

    def update_super_sheet(self, sheet_url: str):
        """Aggregate all evaluations into a Super Sheet."""
        if not self.service: return
        spreadsheet_id, _ = self.parse_sheet_url(sheet_url)
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets_info = spreadsheet.get('sheets', [])
        
        super_sheet_name = "Super Sheet"
        # Create Super Sheet if missing
        existing_titles = [s['properties']['title'] for s in sheets_info]
        if super_sheet_name not in existing_titles:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": super_sheet_name, "index": 0}}}]}
            ).execute()
        
        # Read all sheets to gather all students and all marks
        all_students = {} # normalized_entry -> { name: str, entry: str, marks: { sheet_name: score } }
        eval_sheets = [t for t in existing_titles if t != super_sheet_name]
        
        for sheet_title in eval_sheets:
            try:
                sheet_data = self.service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id, range=f"'{sheet_title}'"
                ).execute()
                values = sheet_data.get('values', [])
                if not values or len(values) < 2: continue
                
                columns = self._detect_columns(values[0])
                if not columns.get('entry_number') or not columns.get('marks'): continue
                
                entry_idx = columns['entry_number']['index']
                name_idx = columns.get('name', {}).get('index')
                marks_idx = columns['marks']['index']
                
                for row in values[1:]:
                    entry_num = self._safe_get(row, entry_idx, '').strip()
                    
                    # Prevent previously appended statistic rows from being parsed as students
                    if entry_num.upper() in ("STATISTICS", "MEAN", "MEDIAN", "HIGHEST", "LOWEST", "MEAN / AVERAGE"):
                        continue
                        
                    normalized = self._normalize_entry_number(entry_num)
                    if not normalized:
                        # Fallback heuristic: maybe they just have a different ID format?
                        if len(entry_num) > 3: normalized = entry_num.upper()
                        else: continue
                        
                    name = self._safe_get(row, name_idx, '').strip() if name_idx is not None else ''
                    marks_str = self._safe_get(row, marks_idx, '0')
                    try:
                        score = float(marks_str)
                    except ValueError:
                        score = 0
                        
                    if normalized not in all_students:
                        all_students[normalized] = {"entry_number": entry_num, "name": name, "marks": {}}
                    if name and not all_students[normalized]["name"]:
                        all_students[normalized]["name"] = name
                        
                    all_students[normalized]["marks"][sheet_title] = score
                    
            except Exception as e:
                print(f"Error reading {sheet_title} for super sheet: {e}")
                
        if not all_students: return
        
        # Build Super Sheet Data
        # Sort students by Entry Number
        sorted_students = sorted(all_students.values(), key=lambda x: x["entry_number"])
        
        # Headers
        headers = ["Entry Number", "Name"]
        for es in eval_sheets: headers.append(f"{es} Marks")
        headers.append("Cumulative Total")
        
        rows = [headers]
        
        col_scores = {es: [] for es in eval_sheets}
        cumulative_scores = []
        
        for student in sorted_students:
            row = [student["entry_number"], student["name"]]
            total = 0
            for es in eval_sheets:
                score = student["marks"].get(es, 0)
                row.append(score)
                col_scores[es].append(score)
                total += score
            row.append(total)
            cumulative_scores.append(total)
            rows.append(row)
            
        # Add Statistics
        rows.append([]) # Empty row
        rows.append(["STATISTICS", ""])
        
        import statistics
        def get_stats(arr):
            if not arr: return ["", "", "", ""]
            return [
                round(statistics.mean(arr), 2),
                round(statistics.median(arr), 2),
                round(max(arr), 2),
                round(min(arr), 2)
            ]
            
        stat_rows = {
            "Mean": ["Mean", ""],
            "Median": ["Median", ""],
            "Highest": ["Highest", ""],
            "Lowest": ["Lowest", ""]
        }
        
        for es in eval_sheets:
            s_mean, s_median, s_high, s_low = get_stats(col_scores[es])
            stat_rows["Mean"].append(s_mean)
            stat_rows["Median"].append(s_median)
            stat_rows["Highest"].append(s_high)
            stat_rows["Lowest"].append(s_low)
            
        # Stats for cumulative
        c_mean, c_median, c_high, c_low = get_stats(cumulative_scores)
        stat_rows["Mean"].append(c_mean)
        stat_rows["Median"].append(c_median)
        stat_rows["Highest"].append(c_high)
        stat_rows["Lowest"].append(c_low)
        
        rows.append(stat_rows["Mean"])
        rows.append(stat_rows["Median"])
        rows.append(stat_rows["Highest"])
        rows.append(stat_rows["Lowest"])
        
        # Clear existing Super Sheet and write new data
        self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"'{super_sheet_name}'"
        ).execute()
        
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{super_sheet_name}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows}
        ).execute()
        print("✅ Super Sheet updated.")


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
