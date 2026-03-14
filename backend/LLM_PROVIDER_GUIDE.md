# Google Workspace & AI Integration Guide (March 2026)

This application is powered by **Gemini for Google Workspace** and **Google AI Studio**. 

## Supported Providers

### 1. Google Gemini (Latest: 3.1)
- **Primary Model**: `gemini-3.1-flash` (Optimized for speed/cost)
- **High Intelligence Model**: `gemini-3.1-pro` (Optimized for reasoning)
- **Lite Model**: `gemini-3.1-flash-lite` (Used for high-throughput OCR)
- **API Key**: Set in `GOOGLE_API_KEY` environment variable.
- **Enterprise Access**: Through Google Workspace editions (Business/Enterprise).

### 2. OpenRouter (Multi-model aggregation)
- **Default**: `google/gemini-3.1-flash`
- **Supported**: Access to frontier models from OpenAI, Anthropic, and Meta.
- **Note**: Ensure `OPENROUTER_API_KEY` is set.

## Configuration

### Environment Variables (.env)

```bash
# API Keys (Rotate your keys if they were created before Jan 2025)
GOOGLE_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
GROQ_API_KEY=your_key_here

# Provider Selection (gemini, groq, openrouter, or auto)
LLM_PROVIDER=auto

# Specific Model Overrides
GEMINI_MODEL=gemini-3.1-flash
```

## Parallelism & Quotas (2026 Update)

As of March 2026, **Gemini 3.1 Flash Lite** offers significantly higher concurrency limits than its predecessors.

- **Standard Tier**: 15 requests per minute (RPM).
- **AI Expanded Access (Workspace Add-on)**: ~60-120 RPM (Project dependent).
- **Pay-as-you-go**: Scale up to 2000+ RPM.

To test your specific safe parallelism limit, use the included benchmark tool:
```bash
python test_gemini_parallelism.py
```

## Troubleshooting Branding Changes

If you see references to "G Suite", "MakerSuite", or "Duet AI", please note:
- **G Suite** is now **Google Workspace**.
- **MakerSuite** has been fully migrated to **Google AI Studio**.
- **Duet AI** has been renamed to **Gemini for Workspace**.
- **Vertex AI Search and Conversation** is now just **Vertex AI Search**.

For any issues with authentication, ensure your **Service Account** has the `roles/aiplatform.user` role in the Google Cloud Console.
