# Answer Sheet Evaluation Backend

This is the backend for the Automated Answer Sheet Evaluation System. It provides a robust API to handle student submissions, process answer sheets using OCR, evaluate them against answer keys, and manage results.

## Languages & Technologies Used
* **Python**: Core programming language.
* **FastAPI**: High-performance web framework for building the API.
* **SQLite**: Lightweight database for storing student, submission, and evaluation result data.
* **Google Cloud Services**: Integrations with Google Drive and Google Sheets APIs for file management and result export.
* **OCR (Optical Character Recognition)**: Advanced OCR services including multi-region and optimized extraction via LLMs (e.g., Gemini/Vertex AI, OpenAI).

## Features
* **Automated Evaluation API**: Standard and high-throughput batch endpoints for processing answer sheets.
* **OCR Pipelines**: Configurable OCR services (`ocr_service`, `multi_region_ocr_service`, `optimized_ocr_service`) to accurately extract text from student submissions.
* **Google Integration**: Fetch submissions directly from Google Drive folders and export graded results to Google Sheets.
* **Evaluation Logic**: Compare extracted text against defined answer keys with customizable scoring algorithms.
* **Result Management**: Manage students, track submission statuses, and store detailed feedback.

## Folder Structure
```
backend/
├── .env                  # Environment variables (from .env.example)
├── main.py               # FastAPI application entry point & standard/batch router inclusion
├── database.py           # SQLite database initialization and local data management
├── models.py             # Data models for Students, Submissions, and Evaluation Results
├── api/                  # FastAPI routers and endpoints
│   ├── endpoints.py      # Standard pipeline endpoints
│   └── batch_endpoints.py# High-throughput batch processing endpoints
└── services/             # Core business logic
    ├── answer_key_service.py      # Manages answer key parsing and structuring
    ├── evaluation_service.py      # Handles logic to compare answers and assign scores
    ├── drive_service.py           # Google Drive API integration
    ├── sheets_service.py          # Google Sheets API integration
    ├── ocr_service.py             # Standard OCR extraction
    ├── optimized_ocr_service.py   # Specialized, high-performance OCR logic
    └── multi_region_ocr_service.py# OCR handling multiple regions of interest
```

## Installation & Setup

1. **Navigate to the backend directory:**
   ```bash
   cd backend
   ```

2. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   Make sure you have the required packages installed. (If a `requirements.txt` is present, run `pip install -r requirements.txt`). Generally, you will need `fastapi`, `uvicorn`, `python-dotenv`, `google-api-python-client`, etc.

4. **Environment Variables:**
   Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   Fill in your `.env` file with appropriate API keys (e.g., `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`).

## Running the Backend

To start the FastAPI development server, run:
```bash
uvicorn main:app --reload
```
The API will be available at `http://127.0.0.1:8000`. You can access the interactive API documentation (Swagger UI) at `http://127.0.0.1:8000/docs`.

## Why the Backend Needs to be Run First
The backend must be running **before** you start the frontend application for several critical reasons:
1. **API Dependency:** The frontend relies entirely on the backend API endpoints (`/api/*`, `/api/batch/*`) to function. Without the backend, API calls will fail, leading to infinite loading states or immediate errors.
2. **Database Initialization:** The backend runs local SQLite initialization on startup (`database.py`), ensuring that tables for students, submissions, and results exist before any data operations occur.
3. **Service Connection Pools:** Core infrastructure, including OCR service connection pools and API clients, are initialized during the backend's startup lifespan. The frontend cannot process uploads or evaluations if these services are inactive.
