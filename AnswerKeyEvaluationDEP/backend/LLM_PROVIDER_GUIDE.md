# LLM Provider Configuration

This application supports multiple LLM providers for subjective answer evaluation.

## Supported Providers

### 1. Google Gemini (Default)
- **Provider ID**: `gemini`
- **Model**: `gemini-2.5-flash`
- **API Key**: Set in `GOOGLE_API_KEY` environment variable
- **Free tier**: Yes (with limits)

### 2. OpenRouter
- **Provider ID**: `openrouter`
- **Model**: Configurable (default: `google/gemini-2.0-flash-exp:free`)
- **API Key**: Set in `OPENROUTER_API_KEY` environment variable
- **Supports**: Multiple models including free tiers

## Configuration

### Environment Variables (.env file)

```bash
# API Keys
GOOGLE_API_KEY=your_google_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
GROQ_API_KEY=your_groq_api_key_here
ZAI_API_KEY=your_zai_api_key_here

# Provider Selection (gemini, groq, openrouter, or auto)
# "auto" (default) will test models and pick the first working one
LLM_PROVIDER=auto

# Specific Model Overrides (Optional)
# Defaults to gemini-1.5-flash if not set
GEMINI_MODEL=gemini-1.5-flash

# Defaults to google/gemini-2.0-flash-lite-001 if not set
OPENROUTER_MODEL=google/gemini-2.0-flash-lite-001

## Pipeline (Hybrid)
1. **GLM-OCR (Zai)**: Primary cloud OCR (High Accuracy).
2. **Local OCR**: Secondary fallback (EasyOCR/Paddle/Tesseract).
3. **Vision API**: Tertiary fallback (Gemini/Groq Vision).
4. **Text Structuring**: LLM cleans and formats raw OCR text into JSON.
5. **Evaluation**: LLM grades the JSON data.

## Available Models (For Text Structuring & Grading)

### Groq (Fastest Backup)
- **Text**: `llama-3.3-70b-versatile` (Used for structuring & grading)
- **Vision (Fallback)**: `llama-3.2-11b-vision-preview`

### Gemini (Primary)
- `gemini-1.5-flash`

### OpenRouter (Secondary Backup)
- `google/gemini-2.0-flash-lite-001` (and others)
```

## Available Gemini Models (For Your Key)

Based on your API key, you have access to these models (subject to quota limits):

- `gemini-1.5-flash` (Stable, recommended)
- `gemini-2.0-flash`
- `gemini-2.5-flash` (Note: May have 0 quota in some regions)
- `gemini-3-flash-preview` (Experimental)
- `nano-banana-pro` (Experimental/Internal?)

To try any of these, just set `GEMINI_MODEL=model-name` in your `.env` file and restart.

### Switching Providers

To switch between providers, simply change the `LLM_PROVIDER` value in your `.env` file:

**Use Gemini:**
```bash
LLM_PROVIDER=gemini
```

**Use OpenRouter:**
```bash
LLM_PROVIDER=openrouter
```

After changing the provider, restart your backend server for the changes to take effect.

## OpenRouter Models

Some popular models available on OpenRouter:

- `google/gemini-2.0-flash-exp:free` - Free Gemini 2.0 Flash (recommended for testing)
- `openai/gpt-3.5-turbo` - OpenAI GPT-3.5 Turbo
- `anthropic/claude-2` - Anthropic Claude 2
- `meta-llama/llama-2-70b-chat` - Meta's Llama 2

Check [OpenRouter's model listings](https://openrouter.ai/models) for more options and pricing.

## Usage in Code

The `EvaluationService` and `OCRService` automatically use the configured provider:

```python
from services.evaluation_service import EvaluationService
from services.ocr_service import OCRService

# Uses provider from LLM_PROVIDER env var
service = EvaluationService()
ocr = OCRService()

# Or override provider programmatically
service = EvaluationService(provider="openrouter")
ocr = OCRService(provider="openrouter")
```

## Automatic Fallback (OCR Only)

 The `OCRService` includes automatic fallback logic:
 1. Tries the primary provider configured in `LLM_PROVIDER` (e.g., Gemini).
 2. If it fails (e.g., due to rate limits), it automatically attempts to use the secondary provider (e.g., OpenRouter) if the API key is available.
 
 This ensures higher reliability for critical OCR tasks.

## Cost Considerations

- **Gemini**: Free tier available with rate limits
- **OpenRouter**: Varies by model
  - Some models have free tiers (e.g., `google/gemini-2.0-flash-exp:free`)
  - Others are pay-per-use
  - Check OpenRouter for current pricing

## Troubleshooting

### API Key Not Working
- Verify the API key is correctly set in `.env`
- Check that you have sufficient credits/quota
- Ensure no extra spaces in the key

### Provider Not Found
- Ensure `LLM_PROVIDER` is set to either `gemini` or `openrouter`
- Restart the backend after changing the provider

### OpenRouter Authentication Errors
- Verify your OpenRouter API key is valid
- Check that you have credits in your OpenRouter account
- Ensure the model you selected is available
