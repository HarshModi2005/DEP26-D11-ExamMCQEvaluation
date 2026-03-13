import requests
import base64
import json
import os

def encode_image(image_path):
    """Encode image to base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def extract_text_via_vertex_ai(image_path, api_key):
    """Extract text from image using Vertex AI Gemini API"""
    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(image_path)}")
    print(f"{'='*60}")
    
    # Encode image
    print("Encoding image...")
    base64_image = encode_image(image_path)
    
    # Determine MIME type based on file extension
    ext = image_path.lower().split('.')[-1]
    mime_type_map = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    mime_type = mime_type_map.get(ext, 'image/jpeg')
    
    # Prepare API request
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash-lite:streamGenerateContent?key={api_key}"
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "Extract all text from this image. Preserve the structure and layout as much as possible. If there are tables, charts, or forms, represent them clearly."
                    },
                    {
                        "inline_data": {
                            "mime_type": mime_type,
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
        
        # Parse streaming response
        result = response.json()
        
        # Collect all text parts
        all_text = []
        
        if isinstance(result, list):
            for chunk in result:
                if "candidates" in chunk:
                    for candidate in chunk["candidates"]:
                        if "content" in candidate and "parts" in candidate["content"]:
                            for part in candidate["content"]["parts"]:
                                if "text" in part:
                                    all_text.append(part["text"])
        elif isinstance(result, dict):
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                all_text.append(part["text"])
        
        # Combine all text
        combined_text = "".join(all_text)
        
        print("\n" + "─"*60)
        print("EXTRACTED TEXT:")
        print("─"*60)
        print(combined_text)
        print("─"*60)
        
        return combined_text
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return None

def main():
    # API Key
    API_KEY = "AQ.Ab8RN6LgH79cn39jKqNmNXmJiXxwHfbRh6YqZlmHUo36HsDoCg"
    
    # Image paths
    images = [
        "/Users/harsh/Desktop/DEP/WhatsApp Image 2026-02-09 at 12.04.58 PM.jpeg",
        "/Users/harsh/Desktop/DEP/WhatsApp Image 2026-02-09 at 12.05.08 PM.jpeg"
    ]
    
    # Extract text from both images
    results = {}
    for image_path in images:
        if os.path.exists(image_path):
            text = extract_text_via_vertex_ai(image_path, API_KEY)
            results[os.path.basename(image_path)] = text
        else:
            print(f"❌ Image not found: {image_path}")
    
    # Save combined results
    output_file = "/Users/harsh/Desktop/DEP/extracted_text_output.txt"
    print(f"\n{'='*60}")
    print(f"Saving results to: {output_file}")
    print(f"{'='*60}")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("EXTRACTED TEXT FROM WHATSAPP IMAGES\n")
        f.write("="*60 + "\n\n")
        
        for image_name, text in results.items():
            f.write(f"\n{'─'*60}\n")
            f.write(f"IMAGE: {image_name}\n")
            f.write(f"{'─'*60}\n\n")
            if text:
                f.write(text)
            else:
                f.write("(Failed to extract text)\n")
            f.write("\n\n")
    
    print(f"✅ Results saved to: {output_file}")
    
    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for image_name, text in results.items():
        status = "✅ SUCCESS" if text else "❌ FAILED"
        char_count = len(text) if text else 0
        print(f"{image_name}: {status} ({char_count} characters)")

if __name__ == "__main__":
    main()
