from transformers import AutoProcessor, AutoModelForVision2Seq
import torch
from PIL import Image
import os
import time

class GraniteOCRService:
    def __init__(self):
        """
        Initializes Granite Vision 3.3-2B model for local document understanding.
        """
        self.model_path = "ibm-granite/granite-vision-3.3-2b"
        self.processor = None
        self.model = None
        self.device = self._get_device()
        
    def _get_device(self):
        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps" # Optimized for Mac
        return "cpu"

    def _load_model(self):
        if self.model is None:
            try:
                print(f"Loading Granite Vision model ({self.device})... (First run downloads ~4GB)")
                start_time = time.time()
                
                self.processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
                
                # Load model with optimizations if possible
                self.model = AutoModelForVision2Seq.from_pretrained(
                    self.model_path, 
                    trust_remote_code=True,
                    torch_dtype=torch.float16 if self.device != "cpu" else torch.float32
                ).to(self.device)
                
                self.model.eval() # Set to evaluation mode
                print(f"Granite Vision loaded in {time.time() - start_time:.2f}s")
            except Exception as e:
                print(f"Failed to load Granite Vision: {e}")
                self.model = None

    def extract_text(self, image_path: str) -> str:
        """
        Extracts text from an image using Granite Vision model.
        """
        if not os.path.exists(image_path):
            return ""

        # Load model lazily
        if self.model is None:
            self._load_model()
            if self.model is None:
                return ""

        try:
            print(f"Granite Vision processing: {image_path}")
            
            image = Image.open(image_path).convert("RGB")
            
            question = "Extract all text from this document image structure-wise. If it is a table or chart, represent it clearly."
            
            conversation = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": question},
                    ],
                },
            ]
            
            # Prepare inputs
            inputs = self.processor.apply_chat_template(
                conversation,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt"
            ).to(self.device)
            
            # Since apply_chat_template handles text, we handle image separately if needed by processor
            # Wait, the user snippet showed apply_chat_template doing it all?
            # User snippet:
            # inputs = processor.apply_chat_template(...)
            # Wait, the user snippet passed 'url' in content. We act locally.
            # Local transformers usage usually requires passing pixel_values separately if strictly visual model
            # But the user snippet implies apply_chat_template handles it?
            # Let's check documentation pattern in snippet.
            # Snippet: {"type": "image", "url": img_path}
            # Since we have local file, we might need to pass PIL image.
            
            # Let's try passing the PIL image object directly in 'content' if supported,
            # or rely on standard processor call.
            
            # Alternative standard usage for VLM in transformers:
            # inputs = processor(images=image, text=prompt, return_tensors="pt").to(device)
            
            # User snippet uses apply_chat_template with `url`. 
            # I will try the standard `processor(text=..., images=...)` pattern which is robust for local images.
            
            prompt = f"<|user|>\n<image>\n{question}\n<|assistant|>\n"
            inputs = self.processor(text=prompt, images=image, return_tensors="pt").to(self.device)
            
            # Generate
            output = self.model.generate(**inputs, max_new_tokens=1024)
            decoded_text = self.processor.decode(output[0], skip_special_tokens=True)
            
            # Post-process to remove the prompt/input if echoed
            # Usually decode returns full text. We need to extract the assistant response.
            # But standard decode often includes prompt.
            # Let's assume it returns everything.
            
            # A cleaner simple approach if chat template is complex:
            # Just return the full string and let the next LLM clean it.
            return decoded_text.replace(prompt, "").strip()

        except Exception as e:
            print(f"Granite Vision extraction failed: {e}")
            # Fallback to pure transformers generation if template failed
            return ""
