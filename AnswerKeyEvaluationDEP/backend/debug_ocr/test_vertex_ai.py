import requests
import base64
import json

def encode_image(image_path):
    """Encode image to base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def test_vertex_ai():
    API_KEY = "AQ.Ab8RN6LgH79cn39jKqNmNXmJiXxwHfbRh6YqZlmHUo36HsDoCg"
    image_path = "/Users/harsh/Desktop/DEP/temp_Screenshot 2026-02-08 at 6.53.08\u202fPM.png"
    
    print(f"Encoding image: {image_path}")
    base64_image = encode_image(image_path)
    
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash-lite:streamGenerateContent?key={API_KEY}"
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "Extract all text from this document image. Preserve the structure and layout. If there are tables, charts, or forms, represent them clearly."
                    },
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64_image
                        }
                    }
                ]
            }
        ]
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    print("Sending request to Vertex AI (Gemini 2.5 Flash Lite)...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        # Parse streaming response (array of JSON objects)
        result = response.json()
        
        # Collect all text parts from the streaming response
        all_text = []
        
        # Handle both single object and array of objects
        if isinstance(result, list):
            # Streaming response - array of chunks
            for chunk in result:
                if "candidates" in chunk:
                    for candidate in chunk["candidates"]:
                        if "content" in candidate and "parts" in candidate["content"]:
                            for part in candidate["content"]["parts"]:
                                if "text" in part:
                                    all_text.append(part["text"])
        elif isinstance(result, dict):
            # Single response object
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                all_text.append(part["text"])
        
        # Combine all text
        combined_text = "".join(all_text)
        
        print("\n--- Extracted Text ---")
        print(combined_text)
        print("--- End Extracted Text ---\n")
        
        # Save to file
        output_file = "/Users/harsh/Desktop/DEP/backend/debug_ocr/vertex_ai_output.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(combined_text)
        print(f"Saved output to: {output_file}")
        
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")

if __name__ == "__main__":
    test_vertex_ai()
