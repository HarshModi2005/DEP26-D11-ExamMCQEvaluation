import os
import json
from typing import List, Dict, Any, Optional
from models import StudentResult, QuestionResult

class StateService:
    """
    Manages session states to allow pipeline resumption.
    Saves and loads progress based on the Google Drive folder ID.
    """
    def __init__(self, storage_dir: str = ".sessions"):
        self.storage_dir = storage_dir
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir, exist_ok=True)

    def _get_file_path(self, folder_id: str) -> str:
        return os.path.join(self.storage_dir, f"{folder_id}.json")

    def save_session(self, folder_id: str, processed_file_ids: List[str], results: List[StudentResult], errors: List[Dict]):
        path = self._get_file_path(folder_id)
        data = {
            "processed_file_ids": processed_file_ids,
            "results": [r.model_dump() for r in results],
            "errors": errors
        }
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to save session state: {e}")

    def load_session(self, folder_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_file_path(folder_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            # Reconstruct StudentResult objects
            results = []
            for r_data in data.get("results", []):
                details = [QuestionResult(**d) for d in r_data.get("details", [])]
                r_data["details"] = details
                results.append(StudentResult(**r_data))
                
            return {
                "processed_file_ids": data.get("processed_file_ids", []),
                "results": results,
                "errors": data.get("errors", [])
            }
        except Exception as e:
            print(f"⚠️ Error loading session state for {folder_id}: {e}")
            return None

    def clear_session(self, folder_id: str):
        path = self._get_file_path(folder_id)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"⚠️ Could not remove session state file: {e}")

    def clear_all_sessions(self):
        for filename in os.listdir(self.storage_dir):
            if filename.endswith(".json"):
                path = os.path.join(self.storage_dir, filename)
                try:
                    os.remove(path)
                except Exception:
                    pass
