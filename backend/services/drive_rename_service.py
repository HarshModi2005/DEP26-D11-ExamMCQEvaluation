"""
Drive Rename Service
====================
Intelligently renames Google Drive answer sheet files based on OCR matching results.

Naming conventions:
  - Matched (confident):  {EntryNumber} - {Name}.{ext}
  - Matched (fuzzy):      FUZZY - {EntryNumber} - {Name}.{ext}
  - Unmatched (has OCR):  UNMATCHED - OCR {OCREntry} - OCR {OCRName}.{ext}
  - Unmatched (no data):  UNMATCHED_NODATA - {original}.{ext}
  - Answer key:           ANSWER_KEY - {original}.{ext}
  - Error:                ERROR - {original}.{ext}

Edge cases handled:
  - Duplicate entry numbers → _DUP1, _DUP2 suffix
  - Special characters in names → replaced with underscores
  - Long names → truncated to 50 chars
  - Already-renamed files → detection and skip option
  - Rate limiting via DriveService.batch_rename_files
"""

import os
import re
from typing import List, Dict, Optional, Tuple
from services.drive_service import DriveService
from services.sheets_service import SheetsService


class DriveRenameService:
    """Orchestrates intelligent file renaming in Google Drive."""

    ALREADY_RENAMED_PATTERN = re.compile(r'^(FUZZY - |UNMATCHED|ANSWER_KEY - |ERROR - |[A-Z0-9]{5,15} - )')

    # Characters not safe in filenames
    UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')

    # Collapse multiple spaces
    MULTI_SPACE = re.compile(r'\s+')

    def __init__(self, drive_service: DriveService = None):
        self.drive_service = drive_service or DriveService()

    # ──────────────────────────────────────
    #  Name Sanitization
    # ──────────────────────────────────────

    @classmethod
    def _sanitize_name(cls, name: str, max_length: int = 50) -> str:
        """
        Sanitize a name for use in a filename.
        - Replace unsafe chars with underscores
        - Collapse multiple spaces
        - Truncate to max_length
        - Strip leading/trailing spaces
        """
        if not name:
            return ""
        s = cls.UNSAFE_CHARS.sub('_', name)
        s = cls.MULTI_SPACE.sub(' ', s)
        s = s.strip()
        if len(s) > max_length:
            s = s[:max_length].strip()
        return s

    @staticmethod
    def _get_extension(filename: str) -> str:
        """Extract file extension (with dot) from filename."""
        _, ext = os.path.splitext(filename)
        return ext  # e.g. ".jpg", ".heic"

    def classify_match(self, result: Dict) -> str:
        """Public wrapper for match category (confident / fuzzy / unmatched)."""
        return self._classify_match(result)

    def compute_new_name_for_student_sheet(
        self,
        old_name: str,
        result: Dict,
        match_type: str,
        entry_usage_count: Dict[str, int],
        skip_already_renamed: bool = False,
    ) -> Optional[str]:
        """
        Target Drive filename for one student sheet, same rules as build_rename_map.
        Mutates entry_usage_count for duplicate-entry suffixes. Returns None if unchanged / skipped.
        """
        ext = self._get_extension(old_name)
        entry = str(result.get("entry_number", "")).strip()
        name = str(result.get("name", "")).strip()
        entry_clean = self._sanitize_name(entry)
        name_clean = self._sanitize_name(name)
        category = match_type

        dup_suffix = ""
        if entry_clean:
            entry_usage_count[entry_clean] = entry_usage_count.get(entry_clean, 0) + 1
            if entry_usage_count[entry_clean] > 1:
                dup_suffix = f" (DUP{entry_usage_count[entry_clean] - 1})"

        if category == "confident" and entry_clean:
            parts = [entry_clean]
            if name_clean:
                parts.append(name_clean)
            new_name = " - ".join(parts) + dup_suffix + ext
        elif category == "fuzzy" and entry_clean:
            parts = ["FUZZY", entry_clean]
            if name_clean:
                parts.append(name_clean)
            new_name = " - ".join(parts) + dup_suffix + ext
        elif entry_clean or name_clean:
            ocr_parts = ["UNMATCHED"]
            if entry_clean:
                ocr_parts.append(f"OCR {entry_clean}")
            if name_clean:
                ocr_parts.append(f"OCR {name_clean}")
            new_name = " - ".join(ocr_parts) + ext
        else:
            orig_clean = self._sanitize_name(os.path.splitext(old_name)[0], max_length=40)
            new_name = f"UNMATCHED_NODATA - {orig_clean}{ext}"

        if old_name == new_name:
            return None
        if skip_already_renamed and self.ALREADY_RENAMED_PATTERN.match(old_name):
            return None
        return new_name

    # ──────────────────────────────────────
    #  Building the Rename Map
    # ──────────────────────────────────────

    def build_rename_map(
        self,
        files: List[Dict],
        results: List[Dict],
        master_students: List[Dict] = None,
        answer_key_file_ids: List[str] = None,
        error_file_names: List[str] = None,
        skip_already_renamed: bool = False,
    ) -> List[Dict]:
        """
        Build a list of rename operations from processing results.

        Args:
            files: Original Drive file list (from list_all_files_in_folder).
                   Each dict has 'id', 'name', 'mimeType'.
            results: OCR + evaluation results. Each dict has 'entry_number',
                     'name', 'total_score', 'details', 'comments', and
                     optionally '_source_file_name' / '_source_file_id'.
            master_students: Master student list from Google Sheets (optional).
                             Used to determine confident vs fuzzy matches.
            answer_key_file_ids: Set of file IDs identified as answer keys.
            error_file_names: List of filenames that errored during processing.
            skip_already_renamed: If True, skip files whose names already
                                  match the renamed pattern (re-run safe). If False,
                                  recompute target names even for already-tagged files.

        Returns:
            List of rename operation dicts:
            [
                {
                    'file_id': str,
                    'old_name': str,
                    'new_name': str,
                    'category': str,   # 'confident', 'fuzzy', 'unmatched', 'answer_key', 'error'
                    'entry_number': str,
                    'student_name': str,
                },
                ...
            ]
        """
        answer_key_file_ids = set(answer_key_file_ids or [])
        error_file_names = set(error_file_names or [])

        # Build file lookup: file_name -> file_info
        file_by_name = {}
        for f in files:
            file_by_name[f['name']] = f

        # Build file lookup by ID too
        file_by_id = {}
        for f in files:
            file_by_id[f['id']] = f

        # Build master student lookup for match categorization
        master_lookup = {}
        if master_students:
            for s in master_students:
                norm = SheetsService._normalize_entry_number(s.get('entry_number', ''))
                if norm:
                    master_lookup[norm] = s

        # Map results to their source files
        # The pipeline stores file_name; we need to correlate result → file
        result_file_map = self._correlate_results_to_files(files, results, answer_key_file_ids)

        # Track entry number usage for duplicate detection
        entry_usage_count = {}
        rename_ops = []
        seq = 1

        for file_id, file_info, result, match_type in result_file_map:
            old_name = file_info['name']
            ext = self._get_extension(old_name)

            entry = str(result.get('entry_number', '')).strip()
            name = str(result.get('name', '')).strip()
            
            # Use raw OCR response if entry is missing or fuzzy? The user said "NAME THE SHEETS WITH THE MATCHED NAME AND ENTRY NUMBER"
            # The matched name and entry number from the result object should be used.
            # However, if it's completely unmatched, fallback to OCR components.
            entry_clean = self._sanitize_name(entry)
            name_clean = self._sanitize_name(name)

            # Determine category
            category = match_type  # 'confident', 'fuzzy', 'unmatched'

            # Handle duplicate entry numbers
            dup_suffix = ""
            if entry_clean:
                entry_usage_count[entry_clean] = entry_usage_count.get(entry_clean, 0) + 1
                if entry_usage_count[entry_clean] > 1:
                    dup_suffix = f" (DUP{entry_usage_count[entry_clean] - 1})"

            if category == 'confident' and entry_clean:
                # Confident match: {Entry} - {Name}{dup}.{ext}
                parts = [entry_clean]
                if name_clean:
                    parts.append(name_clean)
                new_name = ' - '.join(parts) + dup_suffix + ext

            elif category == 'fuzzy' and entry_clean:
                # Fuzzy match: FUZZY - {Entry} - {Name}{dup}.{ext}
                parts = ['FUZZY', entry_clean]
                if name_clean:
                    parts.append(name_clean)
                new_name = ' - '.join(parts) + dup_suffix + ext

            elif entry_clean or name_clean:
                # Unmatched but OCR got something
                ocr_parts = ['UNMATCHED']
                if entry_clean:
                    ocr_parts.append(f'OCR {entry_clean}')
                if name_clean:
                    ocr_parts.append(f'OCR {name_clean}')
                new_name = ' - '.join(ocr_parts) + ext

            else:
                # Unmatched with no usable OCR data
                orig_clean = self._sanitize_name(
                    os.path.splitext(old_name)[0], max_length=40
                )
                new_name = f"UNMATCHED_NODATA - {orig_clean}{ext}"
                category = 'unmatched'

            if old_name == new_name:
                continue

            # Also check if skip_already_renamed matches some of our patterns to avoid re-tagging already renamed files that failed differently
            if skip_already_renamed and self.ALREADY_RENAMED_PATTERN.match(old_name):
                # If we are changing an already renamed file, we should only do it if the new matched data is better.
                # However, since the user usually processes unprocessed files, we skip if already tagged.
                continue

            rename_ops.append({
                'file_id': file_id,
                'old_name': old_name,
                'new_name': new_name,
                'category': category,
                'entry_number': entry,
                'student_name': name,
            })

        # ── Process answer key files ──
        for f in files:
            if f['id'] in answer_key_file_ids:
                old_name = f['name']
                ext = self._get_extension(old_name)
                orig_clean = self._sanitize_name(os.path.splitext(old_name)[0], max_length=60)
                new_name = f"ANSWER_KEY - {orig_clean}{ext}"
                
                if old_name == new_name:
                    continue
                if skip_already_renamed and old_name.startswith('ANSWER_KEY - '):
                    continue
                    
                rename_ops.append({
                    'file_id': f['id'],
                    'old_name': old_name,
                    'new_name': new_name,
                    'category': 'answer_key',
                    'entry_number': '',
                    'student_name': '',
                })

        # ── Process error files ──
        for f in files:
            if f['name'] in error_file_names and f['id'] not in answer_key_file_ids:
                # Check if already handled by results
                already_handled = any(op['file_id'] == f['id'] for op in rename_ops)
                if already_handled:
                    continue
                old_name = f['name']
                ext = self._get_extension(old_name)
                orig_clean = self._sanitize_name(os.path.splitext(old_name)[0], max_length=40)
                new_name = f"ERROR - {orig_clean}{ext}"

                if old_name == new_name:
                    continue
                if skip_already_renamed and self.ALREADY_RENAMED_PATTERN.match(old_name):
                    continue

                rename_ops.append({
                    'file_id': f['id'],
                    'old_name': old_name,
                    'new_name': new_name,
                    'category': 'error',
                    'entry_number': '',
                    'student_name': '',
                })

        # ── Handle remaining files (not in results, not answer key, not error) ──
        handled_ids = {op['file_id'] for op in rename_ops}
        for f in files:
            if f['id'] in handled_ids or f['id'] in answer_key_file_ids:
                continue
            old_name = f['name']
            # Check if this file was processed but somehow missed
            ext = self._get_extension(old_name)
            orig_clean = self._sanitize_name(os.path.splitext(old_name)[0], max_length=40)
            new_name = f"UNMATCHED_NODATA - {orig_clean}{ext}"

            if old_name == new_name:
                continue
            if skip_already_renamed and self.ALREADY_RENAMED_PATTERN.match(old_name):
                continue
                
            rename_ops.append({
                'file_id': f['id'],
                'old_name': old_name,
                'new_name': new_name,
                'category': 'unmatched',
                'entry_number': '',
                'student_name': '',
            })

        return rename_ops

    def _correlate_results_to_files(
        self,
        files: List[Dict],
        results: List[Dict],
        answer_key_file_ids: set,
    ) -> List[Tuple[str, Dict, Dict, str]]:
        """
        Correlate OCR results back to their source Drive files.

        Returns list of (file_id, file_info, result_dict, match_type).
        match_type is 'confident', 'fuzzy', or 'unmatched'.
        """
        correlations = []

        # Build file lookup by name
        file_by_name = {}
        for f in files:
            if f['id'] not in answer_key_file_ids:
                file_by_name[f['name']] = f

        # If results have _source_file_name or _source_file_id, use them directly
        used_file_ids = set()
        used_result_indices = set()

        for i, r in enumerate(results):
            src_file_id = str(r.get('_source_file_id') or r.get('file_id') or '').strip()
            src_file_name = str(r.get('_source_file_name') or r.get('file_name') or '').strip()

            file_info = None
            if src_file_id:
                for f in files:
                    if f['id'] == src_file_id and f['id'] not in answer_key_file_ids:
                        file_info = f
                        break
            elif src_file_name and src_file_name in file_by_name:
                file_info = file_by_name[src_file_name]

            if file_info and file_info['id'] not in used_file_ids:
                match_type = self._classify_match(r)
                correlations.append((file_info['id'], file_info, r, match_type))
                used_file_ids.add(file_info['id'])
                used_result_indices.add(i)

        # For results without source info, match by order
        # (files that aren't answer keys, haven't been used yet)
        remaining_files = [
            f for f in files
            if f['id'] not in answer_key_file_ids and f['id'] not in used_file_ids
        ]
        remaining_results = [
            r for i, r in enumerate(results) if i not in used_result_indices
        ]

        for file_info, result in zip(remaining_files, remaining_results):
            match_type = self._classify_match(result)
            correlations.append((file_info['id'], file_info, result, match_type))

        return correlations

    def _classify_match(self, result: Dict) -> str:
        """
        Classify a result as confident, fuzzy, or unmatched.

        Heuristics:
        - If comments contain 'Fuzzy Match' → fuzzy
        - If comments contain 'Not found in Master' → unmatched
        - If comments contain 'Absent' → unmatched
        - If entry_number is empty or 'unknown' → unmatched
        - Otherwise → confident
        """
        entry = str(result.get('entry_number', '')).strip().lower()
        comments = str(result.get('comments', '')).lower()
        name = str(result.get('name', '')).strip().lower()

        if not entry or entry in ('unknown', 'none', 'n/a', ''):
            return 'unmatched'
        if 'fuzzy match' in comments:
            return 'fuzzy'
        if 'not found in master' in comments:
            return 'unmatched'
        if 'absent' in comments:
            return 'unmatched'
        return 'confident'

    # ──────────────────────────────────────
    #  Execute Rename
    # ──────────────────────────────────────

    def execute_rename(
        self,
        rename_ops: List[Dict],
        dry_run: bool = False,
    ) -> Dict:
        """
        Execute the rename operations via the Drive API.

        Args:
            rename_ops: Output from build_rename_map().
            dry_run: If True, return the plan without making changes.

        Returns:
            Detailed summary of rename results.
        """
        # Build summary
        summary = {
            'dry_run': dry_run,
            'total_operations': len(rename_ops),
            'by_category': {},
            'rename_plan': [],
        }

        for op in rename_ops:
            cat = op['category']
            summary['by_category'][cat] = summary['by_category'].get(cat, 0) + 1
            summary['rename_plan'].append({
                'old_name': op['old_name'],
                'new_name': op['new_name'],
                'category': op['category'],
                'entry_number': op.get('entry_number', ''),
                'student_name': op.get('student_name', ''),
            })

        if dry_run:
            summary['message'] = 'Dry run — no files were renamed. Review the plan above.'
            return summary

        # Execute via DriveService batch rename
        batch_result = self.drive_service.batch_rename_files(rename_ops)
        summary['execution_result'] = batch_result
        summary['message'] = (
            f"Renamed {batch_result['success']}/{batch_result['total']} files "
            f"({batch_result['failed']} failed, {batch_result['skipped']} skipped)"
        )

        return summary

    # ──────────────────────────────────────
    #  Convenience: Full Rename Pipeline
    # ──────────────────────────────────────

    def rename_folder_files(
        self,
        folder_url: str,
        results: List[Dict],
        master_students: List[Dict] = None,
        error_file_names: List[str] = None,
        dry_run: bool = False,
        skip_already_renamed: bool = False,
    ) -> Dict:
        """
        Full pipeline: list folder → separate files → build rename map → execute.

        Args:
            folder_url: Google Drive folder URL or ID.
            results: OCR + evaluation results from the processing pipeline.
            master_students: Master student list (for categorization).
            error_file_names: File names that errored during OCR.
            dry_run: If True, only preview without renaming.
            skip_already_renamed: If True, skip files that appear already renamed.

        Returns:
            Rename summary.
        """
        folder_id = DriveService.extract_folder_id(folder_url)
        all_files = self.drive_service.list_all_files_in_folder(folder_id)

        if not all_files:
            return {'error': 'No files found in Drive folder', 'total_operations': 0}

        # Separate answer key files
        answer_key_files, student_sheets = self.drive_service.separate_files(all_files)
        answer_key_ids = [f['id'] for f in answer_key_files]

        # Build rename map
        rename_ops = self.build_rename_map(
            files=all_files,
            results=results,
            master_students=master_students,
            answer_key_file_ids=answer_key_ids,
            error_file_names=error_file_names,
            skip_already_renamed=skip_already_renamed,
        )

        if not rename_ops:
            return {
                'message': 'No files to rename (all may already be renamed)',
                'total_operations': 0,
            }

        # Execute (or dry-run)
        return self.execute_rename(rename_ops, dry_run=dry_run)
