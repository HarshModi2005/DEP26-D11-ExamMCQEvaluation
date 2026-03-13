import sys
from dotenv import load_dotenv
import os

load_dotenv()
print(f"API KEY: {os.getenv('GOOGLE_API_KEY')[:5]}...")

from services.drive_service import DriveService

url = "https://drive.google.com/drive/folders/1P7QM11inmhUXDQn9pdVymbUwDVvuk2GP?usp=drive_link"
ds = DriveService()
folder_id = ds.extract_folder_id(url)
print(f"Folder ID: {folder_id}")

try:
    print("Listing files...")
    files = ds.list_all_files_in_folder(folder_id)
    print(f"Found {len(files)} files")
    for f in files:
        print(f.get('name'))
except Exception as e:
    import traceback
    traceback.print_exc()

