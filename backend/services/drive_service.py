import os
import io
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from typing import List, Dict, Tuple


class DriveService:
    SCOPES = [
        'https://www.googleapis.com/auth/drive.readonly',
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

    def get_service(self):
        if self.creds:
            return build('drive', 'v3', credentials=self.creds)
        elif self.api_key:
            return build('drive', 'v3', developerKey=self.api_key)
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

        try:
            query = f"'{folder_id}' in parents and trashed=false"
            if mime_filter:
                query += f" and mimeType contains '{mime_filter}'"

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
            print(f"An error occurred listing files: {e}")
            return []

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

    def rename_file(self, file_id: str, new_name: str) -> bool:
        """Rename a file in Google Drive."""
        service = self.get_service()
        if not service:
            return False
        
        try:
            # We don't change the extension, just the name. Wait, the extension in Google Drive is part of the name.
            # But we can just set it to the new name directly.
            file_metadata = {'name': new_name}
            service.files().update(fileId=file_id, body=file_metadata).execute()
            print(f"  📛 Renamed Drive file to: {new_name}")
            return True
        except Exception as e:
            print(f"  ⚠️ Failed to rename Drive file {file_id}: {e}")
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
