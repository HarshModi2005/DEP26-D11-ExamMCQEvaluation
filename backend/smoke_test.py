import os
import io
import json
import base64
import requests
import datetime
from PIL import Image
from google.oauth2 import service_account
import google.auth.transport.requests

def test_ocr():
    PROJECT_ID = "project-fd1a2f17-2b4d-4858-9e8"
    LOCATION = "asia-east2"
    # Will try testing "gemini-pro" and "gemini-1.5-flash"
    MODEL_ID = "gemini-pro"
    
    creds_path = "/Users/harsh/Desktop/newRepo/AnswerKeyEvaluationDEP/backend/vertex_key.json"
    
    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        if hasattr(creds, "project_id") and creds.project_id:
            PROJECT_ID = creds.project_id
            
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    except Exception as e:
        print(f"Auth failed: {e}")
        return

    # Create dummy image
    img = Image.new('RGB', (100, 30), color = (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    
    url = (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{PROJECT_ID}/locations/{LOCATION}/"
        f"publishers/google/models/{MODEL_ID}:generateContent"
    )
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "What is in this image?"},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64
                        }
                    }
                ]
            }
        ]
    }
    
    print(f"Testing OCR with {MODEL_ID} in {LOCATION}...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Success! Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_ocr()
