import os
import io
import re
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from typing import List, Dict, Tuple


class DriveService:
    SCOPES = [
        'https://www.googleapis.com/auth/drive',  # Full access for rename support
    ]

    # File name patterns that indicate an answer key
    ANSWER_KEY_PATTERNS = [
        r'answer[_\s-]*key',
        r'answer[_\s-]*sheet[_\s-]*key',
        r'correct[_\s-]*answers',
        r'marking[_\s-]*scheme',
        r'solution[_\s-]*key',
    ]

    def __init__(self, credentials_path: str = "credentials.json"):
        self.creds = None
        self.api_key = None
        
        # 1. Try Service Account
        if not os.path.exists(credentials_path):
            env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if env_path and os.path.exists(env_path):
                credentials_path = env_path
        
        if os.path.exists(credentials_path):
            try:
                self.creds = service_account.Credentials.from_service_account_file(
                    credentials_path, scopes=self.SCOPES)
                print("Drive Service: Using Service Account Credentials")
            except Exception as e:
                print(f"Error loading service account credentials: {e}")
        
        # 2. Fallback to API Key (for public folders)
        if not self.creds:
            self.api_key = os.getenv("GOOGLE_API_KEY")
            if self.api_key:
                print("Drive Service: Using API Key (Public Access Mode)")
            else:
                print(f"Warning: No Service Account credentials found at {credentials_path} and no GOOGLE_API_KEY found.")

    def get_service(self, timeout: int = 60):
        """Build the Drive service with a specific timeout."""
        import httplib2
        
        if self.creds:
            import google_auth_httplib2
            http = httplib2.Http(timeout=timeout)
            authed_http = google_auth_httplib2.AuthorizedHttp(self.creds, http=http)
            return build('drive', 'v3', http=authed_http)
        elif self.api_key:
            http = httplib2.Http(timeout=timeout)
            return build('drive', 'v3', developerKey=self.api_key, http=http)
        else:
            return None

    # ──────────────────────────────────────
    #  Listing Files
    # ──────────────────────────────────────

    def list_files_in_folder(self, folder_id: str) -> List[Dict]:
        """List only image files in a folder (legacy method)."""
        return self._list_files(folder_id, mime_filter="image/")

    def list_all_files_in_folder(self, folder_id: str) -> List[Dict]:
        """List ALL files in a folder regardless of type."""
        return self._list_files(folder_id, mime_filter=None)

    def _list_files(self, folder_id: str, mime_filter: str = None) -> List[Dict]:
        """
        Internal method to list files with optional MIME type filter.
        Handles pagination for large folders.
        """
        service = self.get_service()
        if not service:
            print("Drive service not initialized")
            return []

        import time
        query = f"'{folder_id}' in parents and trashed=false"
        if mime_filter:
            query += f" and mimeType contains '{mime_filter}'"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                all_files = []
                page_token = None
                while True:
                    results = service.files().list(
                        q=query,
                        pageSize=100,
                        pageToken=page_token,
                        fields="nextPageToken, files(id, name, mimeType, webContentLink, size)",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()

                    items = results.get('files', [])
                    all_files.extend(items)

                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
                return all_files
            except Exception as e:
                # If it's a timeout or something retryable, wait and try again
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"  ⚠️ Drive listing attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                # Re-raise so the caller knows it failed (timeout, auth, etc.)
                # Instead of returning [ ] which is the same as "folder is empty"
                print(f"  ❌ Drive Service Error listing files: {e}")
                raise RuntimeError(f"Drive API listing failed: {e}")

    # ──────────────────────────────────────
    #  Separating Answer Key vs Student Sheets
    # ──────────────────────────────────────

    def separate_files(self, files: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Separates files into answer key files and student answer sheet files.
        
        An answer key file is identified by its name containing patterns like
        'answer_key', 'answer key', 'correct_answers', 'marking_scheme', etc.
        
        Returns:
            (answer_key_files, student_sheet_files)
        """
        answer_key_files = []
        student_sheet_files = []

        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.ANSWER_KEY_PATTERNS]

        for f in files:
            file_name = f.get("name", "")
            is_answer_key = any(pattern.search(file_name) for pattern in compiled_patterns)

            if is_answer_key:
                answer_key_files.append(f)
                print(f"  📋 Identified answer key: {file_name}")
            else:
                student_sheet_files.append(f)
                print(f"  📄 Student sheet: {file_name}")

        return answer_key_files, student_sheet_files

    # ──────────────────────────────────────
    #  Downloading Files
    # ──────────────────────────────────────

    def download_file(self, file_id: str, destination_path: str) -> bool:
        """Download a file from Drive by its file ID."""
        service = self.get_service()
        if not service:
            return False

        try:
            request = service.files().get_media(fileId=file_id)
            fh = io.FileIO(destination_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return True
        except Exception as e:
            print(f"An error occurred downloading file: {e}")
            return False

    def export_google_file(self, file_id: str, export_mime: str, destination_path: str) -> bool:
        """
        Export a Google Workspace file (Sheets, Docs) to a specific format.
        
        Args:
            file_id: The Drive file ID.
            export_mime: Target MIME type, e.g. 'text/csv', 'application/pdf'.
            destination_path: Local path to save the exported file.
        """
        service = self.get_service()
        if not service:
            return False

        try:
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
            fh = io.FileIO(destination_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            return True
        except Exception as e:
            print(f"An error occurred exporting Google file: {e}")
            return False

    def download_answer_key(self, file_info: Dict, temp_dir: str = "/tmp") -> str:
        """
        Download an answer key file, handling Google Workspace exports.
        
        For Google Sheets → exports as CSV.
        For Google Docs → exports as PDF.
        For regular files → direct download.
        
        Returns:
            Local path to the downloaded file.
        """
        file_id = file_info["id"]
        file_name = file_info["name"]
        mime_type = file_info.get("mimeType", "")

        os.makedirs(temp_dir, exist_ok=True)

        # Handle Google Workspace files
        if mime_type == "application/vnd.google-apps.spreadsheet":
            dest_path = os.path.join(temp_dir, f"{file_name}.csv")
            success = self.export_google_file(file_id, "text/csv", dest_path)
        elif mime_type == "application/vnd.google-apps.document":
            dest_path = os.path.join(temp_dir, f"{file_name}.pdf")
            success = self.export_google_file(file_id, "application/pdf", dest_path)
        else:
            dest_path = os.path.join(temp_dir, file_name)
            success = self.download_file(file_id, dest_path)

        if success:
            print(f"  ⬇️  Downloaded answer key to: {dest_path}")
            return dest_path
        else:
            raise RuntimeError(f"Failed to download answer key: {file_name}")

    # ──────────────────────────────────────
    #  Renaming Files
    # ──────────────────────────────────────

    def rename_file(self, file_id: str, new_name: str, max_retries: int = 3) -> bool:
        """
        Rename a file in Google Drive.
        
        Args:
            file_id: The Drive file ID.
            new_name: The new name for the file.
            max_retries: Number of retries on transient errors.
        
        Returns:
            True if renamed successfully, False otherwise.
        """
        service = self.get_service()
        if not service:
            print("Drive service not initialized — cannot rename")
            return False

        for attempt in range(max_retries):
            try:
                service.files().update(
                    fileId=file_id,
                    body={'name': new_name},
                    supportsAllDrives=True,
                ).execute()
                return True
            except Exception as e:
                err_str = str(e)
                # Retry on rate-limit (429) or server errors (5xx)
                if ('429' in err_str or '500' in err_str or '503' in err_str) and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠️ Rename attempt {attempt+1} for '{new_name}' failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"  ❌ Failed to rename file {file_id} to '{new_name}': {e}")
                return False

    def batch_rename_files(
        self,
        rename_map: List[Dict],
        rate_limit_delay: float = 0.2,
    ) -> Dict:
        """
        Rename multiple files in Google Drive with rate limiting.
        
        Args:
            rename_map: List of dicts with keys 'file_id', 'new_name', and optionally 'old_name'.
            rate_limit_delay: Seconds to wait between renames (default 0.2 = 5 renames/sec).
        
        Returns:
            Summary dict with counts and error details.
        """
        summary = {
            "total": len(rename_map),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "renamed": [],
        }

        for i, entry in enumerate(rename_map):
            file_id = entry.get('file_id', '')
            new_name = entry.get('new_name', '')
            old_name = entry.get('old_name', f'file_{i}')

            if not file_id or not new_name:
                summary['skipped'] += 1
                continue

            print(f"  📝 [{i+1}/{len(rename_map)}] '{old_name}' → '{new_name}'")
            ok = self.rename_file(file_id, new_name)
            if ok:
                summary['success'] += 1
                summary['renamed'].append({
                    'file_id': file_id,
                    'old_name': old_name,
                    'new_name': new_name,
                })
            else:
                summary['failed'] += 1
                summary['errors'].append({
                    'file_id': file_id,
                    'old_name': old_name,
                    'new_name': new_name,
                    'error': 'Rename API call failed',
                })

            # Rate limit to avoid 429s
            if i < len(rename_map) - 1:
                time.sleep(rate_limit_delay)

        print(f"  ✅ Batch rename complete: {summary['success']} success, "
              f"{summary['failed']} failed, {summary['skipped']} skipped")
        return summary

    # ──────────────────────────────────────
    #  URL Parsing
    # ──────────────────────────────────────

    @staticmethod
    def extract_folder_id(url_or_id: str) -> str:
        """
        Extract folder ID from a Google Drive URL or return as-is if already an ID.
        
        Handles:
        - https://drive.google.com/drive/folders/1oVtYZ...
        - https://drive.google.com/drive/u/0/folders/1oVtYZ...?usp=sharing
        - Raw folder IDs
        """
        if "drive.google.com" in url_or_id:
            try:
                folder_id = url_or_id.split("/folders/")[1]
                if "?" in folder_id:
                    folder_id = folder_id.split("?")[0]
                return folder_id
            except IndexError:
                pass
        return url_or_id
