import os
from google.auth import jwt
from googleapiclient.discovery import build

creds_file = "vertex_key.json"
audience = "https://www.googleapis.com/"

try:
    creds = jwt.Credentials.from_service_account_file(
        creds_file, audience=audience)
    service = build('drive', 'v3', credentials=creds)
    files = service.files().list(q="trashed=false", pageSize=5).execute()
    print("JWT auth worked. Files:", len(files.get('files', [])))
except Exception as e:
    print(f"Error: {e}")
