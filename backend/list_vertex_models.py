import os
import requests
from google.oauth2 import service_account
import google.auth.transport.requests

CREDS_PATH = "vertex_key.json"
_sa_creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)

req = google.auth.transport.requests.Request()
_sa_creds.refresh(req)
token = _sa_creds.token
PROJECT_ID = _sa_creds.project_id

print(f"Project ID: {PROJECT_ID}")

candidates = [
    "gemini-1.0-pro-001",
    "gemini-1.0-pro-002",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
    "gemini-1.5-pro-001",
    "gemini-1.5-pro-002",
    "gemini-pro"
]

PAYLOAD = {
    "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    "generationConfig": {"maxOutputTokens": 1, "temperature": 0.0},
}

for model in candidates:
    print(f"Testing {model}...")
    url = f"https://asia-east1-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/asia-east1/publishers/google/models/{model}:generateContent"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    resp = requests.post(url, headers=headers, json=PAYLOAD)
    if resp.status_code == 200:
        print(f"✅ {model} works!")
    else:
        print(f"❌ {model} failed: {resp.status_code}")
        # print(resp.text[:100])
