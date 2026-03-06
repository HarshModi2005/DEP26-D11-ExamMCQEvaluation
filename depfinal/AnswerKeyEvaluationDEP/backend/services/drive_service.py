import os
import io
import re
import requests
import socket
from typing import List, Dict, Tuple, Optional

# --- CRITICAL NETWORK FIX ---
# The host environment blackholes IPv6 traffic to www.googleapis.com, causing 
# 120-second hangs on every API call before falling back to IPv4. 
# This monkeypatch forces all Python sockets to use IPv4 by default.
old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return old_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = new_getaddrinfo
# ----------------------------


class DriveService:
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

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
                from google.oauth2 import service_account
                self.creds = service_account.Credentials.from_service_account_file(
                    credentials_path, scopes=self.SCOPES)
                # Override token URI to bypass blocked oauth2.googleapis.com domain
                self.creds._token_uri = "https://www.googleapis.com/oauth2/v4/token"
                print("Drive Service: Using Service Account Credentials")
            except Exception as e:
                print(f"Error loading service account credentials: {e}")

        # 2. Fallback to API Key (for public folders)
        if not self.creds:
            self.api_key = os.getenv("GOOGLE_API_KEY")
            if self.api_key:
                print("Drive Service: Using API Key (Public Access Mode)")
            else:
                print(f"Warning: No credentials found at {credentials_path} and no GOOGLE_API_KEY.")

    # ──────────────────────────────────────
    #  Auth
    # ──────────────────────────────────────

    def _get_token(self) -> Optional[str]:
        """
        Get a fresh OAuth2 Bearer token from the service account credentials.
        Uses a strictly bounded requests Session to prevent httplib2 hangs.
        """
        if not self.creds:
            return None
        try:
            import google.auth.transport.requests
            import requests

            req_session = requests.Session()
            # Explicit timeout to prevent infinite hangs
            def _request_with_timeout(method, url, **kwargs):
                kwargs.setdefault("timeout", 10)
                return requests.Session.request(req_session, method, url, **kwargs)
            req_session.request = _request_with_timeout
            auth_req = google.auth.transport.requests.Request(session=req_session)
            
            self.creds.refresh(auth_req)
            return self.creds.token
        except Exception as e:
            print(f"Failed to refresh service account token: {e}")
            return None

    def _auth_headers(self) -> dict:
        """Return Authorization headers for API calls."""
        token = self._get_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _base_params(self) -> dict:
        """Return base query params (API key if no service account)."""
        if not self.creds and self.api_key:
            return {"key": self.api_key}
        return {}

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
        """List files using the Drive REST API via requests (bypasses httplib2)."""
        if not self.creds and not self.api_key:
            print("Drive service not initialized")
            return []

        try:
            query = f"'{folder_id}' in parents and trashed=false"
            if mime_filter:
                query += f" and mimeType contains '{mime_filter}'"

            all_files = []
            page_token = None

            while True:
                params = {
                    **self._base_params(),
                    "q": query,
                    "pageSize": 100,
                    "fields": "nextPageToken, files(id, name, mimeType, webContentLink, size)",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                }
                if page_token:
                    params["pageToken"] = page_token

                resp = requests.get(
                    "https://www.googleapis.com/drive/v3/files",
                    params=params,
                    headers=self._auth_headers(),
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                items = data.get("files", [])
                all_files.extend(items)

                page_token = data.get("nextPageToken")
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
        Returns: (answer_key_files, student_sheet_files)
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
        """Download a file from Drive by its file ID using requests."""
        try:
            params = {**self._base_params(), "alt": "media"}
            resp = requests.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params=params,
                headers=self._auth_headers(),
                timeout=60,
                stream=True,
            )
            resp.raise_for_status()
            with open(destination_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"An error occurred downloading file {file_id}: {e}")
            return False

    def export_google_file(self, file_id: str, export_mime: str, destination_path: str) -> bool:
        """Export a Google Workspace file (Sheets, Docs) to a specific format."""
        try:
            params = {**self._base_params(), "mimeType": export_mime}
            resp = requests.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                params=params,
                headers=self._auth_headers(),
                timeout=60,
                stream=True,
            )
            resp.raise_for_status()
            with open(destination_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"An error occurred exporting Google file {file_id}: {e}")
            return False

    def download_answer_key(self, file_info: Dict, temp_dir: str = "/tmp") -> str:
        """
        Download an answer key file, handling Google Workspace exports.
        Returns local path to the downloaded file.
        """
        file_id = file_info["id"]
        file_name = file_info["name"]
        mime_type = file_info.get("mimeType", "")

        os.makedirs(temp_dir, exist_ok=True)

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
