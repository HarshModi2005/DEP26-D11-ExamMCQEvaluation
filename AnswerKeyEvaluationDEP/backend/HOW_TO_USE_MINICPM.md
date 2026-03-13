# How to Use MiniCPM-o 4.5 / MiniCPM-V 4.0 for OCR

You have two main options to run this powerful multimodal model locally on your Mac.

## Option 1: Using Ollama (Recommended & Fastest)
This method is highly optimized for Mac (Metal/GPU) and handles large model files automatically.

1.  **Download Ollama**: Visit [ollama.com](https://ollama.com) and download the macOS version.
2.  **Pull the Model**: Open your terminal and run:
    ```bash
    ollama run minicpm-v
    ```
    (Note: `minicpm-v` usually points to the latest supported vision model. Check Ollama library for specific 4.5 tag if needed).
3.  **Update Backend**: Once Ollama is running, I can update your `OCRService` to call `http://localhost:11434/api/chat` instead of cloud APIs.

## Option 2: Using Python Transformers (Your Current Venv)
This runs the model directly in your Python backend. It requires downloading ~10GB of weights.

**Setup:**
1.  Install dependencies:
    ```bash
    pip install "transformers>=4.40.0" accelerate torch torchvision minicpmo-utils
    ```
2.  Load the model in Python:
    ```python
    from transformers import AutoModel, AutoTokenizer
    import torch
    from PIL import Image

    model_name = "openbmb/MiniCPM-V-2_6" # or MiniCPM-o-4_5 if available on HF
    
    # Load model
    model = AutoModel.from_pretrained(model_name, trust_remote_code=True, torch_dtype=torch.float16)
    model = model.to(device='mps') # Use Mac GPU
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model.eval()

    # Inference
    image = Image.open('image.jpg').convert('RGB')
    question = 'Extract all text from this image.'
    msgs = [{'role': 'user', 'content': question}]
    
    res = model.chat(
        image=image,
        msgs=msgs,
        tokenizer=tokenizer,
        sampling=True,
        temperature=0.7
    )
    print(res)
    ```

## Which should you choose?
-   **Ollama**: If you want a separate, optimized app that stays out of your project's way.
-   **Python**: If you want tight integration and don't mind managing heavy dependencies in your `venv`.

**I can implement Option 2 for you immediately if you wish.** Just say "Use Python".
