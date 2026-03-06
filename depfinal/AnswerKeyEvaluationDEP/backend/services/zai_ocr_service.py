import os
from zai import ZaiClient
import json
import base64

class ZaiOCRService:
    def __init__(self):
        """
        Initializes Zai OCR Service using ZAI_API_KEY.
        """
        self.api_key = os.getenv("ZAI_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                # Initialize client
                self.client = ZaiClient(api_key=self.api_key)
                print("Zai OCR Service initialized.")
            except Exception as e:
                print(f"Error initializing ZaiClient: {e}")
        else:
            print("Warning: ZAI_API_KEY not found. Zai OCR service disabled.")

    def extract_text(self, image_path: str) -> str:
        """
        Call Zai (GLM-OCR) Layout Parsing API.
        Expected 'file' arg: URL or Base64 string.
        """
        if not self.client:
            return ""
            
        if not os.path.exists(image_path):
            print(f"Zai OCR: File not found {image_path}")
            return ""

        try:
            print(f"Sending {image_path} to Zai GLM-OCR...")
            
            # SDK requires Base64 for local files
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            
            response = self.client.layout_parsing.create(
                model="glm-ocr",
                file=encoded_string 
            )
            
            # Return raw string representation for LLM structuring
            return str(response)
            
        except Exception as e:
            print(f"Zai OCR extraction failed: {e}")
            return ""
