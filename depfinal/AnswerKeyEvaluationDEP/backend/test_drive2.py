import sys
from dotenv import load_dotenv
load_dotenv()
from services.drive_service import DriveService

url = "https://drive.google.com/drive/folders/1P7QM11inmhUXDQn9pdVymbUwDVvuk2GP?usp=drive_link"
ds = DriveService()
folder_id = ds.extract_folder_id(url)
print(f"Folder ID: {folder_id}")
files = ds.list_all_files_in_folder(folder_id)
print(f"Found {len(files)} files")
for f in files:
    print(f.get('name'))
