# Answer Key Evaluation DEP

A comprehensive, automated Answer Sheet Evaluation System designed to streamline the grading process for educational institutions. This system allows professors and Teaching Assistants to manage courses, process student answer sheets via OCR, evaluate them against predefined answer keys, and manage the results.

## Project Architecture

This project is structured as a full-stack application divided into two main parts:

- **[`/backend`](./backend)**: A Python-based FastAPI backend that handles OCR processing, evaluation logic, and dataset management (SQLite).
- **[`/frontend-new-design`](./frontend-new-design)**: A modern React-based frontend built with Node.js that provides the user interface for Faculty members, TAs, and Admin users.

---

## 🚀 Getting Started

To run the full application locally, you will need to start both the Backend and Frontend servers.

**⚠️ IMPORTANT: You must start the Backend before starting the Frontend.** The frontend relies on the backend API endpoints to fetch data, and the backend initializes local databases and connection pools upon startup.

### 1. Running the Backend

The backend is written in Python using FastAPI.

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create and activate a run environment (recommended):
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Mac/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Setup environment variables:
   Copy `.env.example` to `.env` and fill in necessary keys (Google API, OpenAI keys, etc.).
   ```bash
   cp .env.example .env
   ```
5. Start the FastAPI development server:
   ```bash
   uvicorn main:app --reload
   ```

*The backend API will run on `http://127.0.0.1:8000` by default. You can view the API documentation at `http://127.0.0.1:8000/docs`.*

For more details on backend architecture, see the [Backend README](./backend/README.md).

---

### 2. Running the Frontend

The frontend is a React application using Vite and Node.js.

1. Open a new terminal window and navigate to the frontend directory:
   ```bash
   cd frontend-new-design
   ```
2. Install node dependencies:
   ```bash
   npm install
   ```
3. Set up environment variables:
   Copy `.env.example` to `.env.local` if necessary (e.g. Supabase keys).
4. Start the frontend development server:
   ```bash
   npm start
   ```

*The frontend application will start up, usually available on `http://localhost:5173` or `http://localhost:3000` depending on Vite configurations.*

---

## 🛠 Features

### Backend Features
- **OCR Pipelines**: Configurable LLM-driven OCR services to extract text accurately.
- **Evaluation Logic**: Compare extracted text against defined answer keys with customizable, AI-driven scoring algorithms.
- **Google Integrations**: Direct reading from Google Drive folders and writing results to Google Sheets.

### Frontend Features
- **Faculty Dashboard**: An intuitive overview for creating courses, tracking evaluations, and managing pending grading tasks.
- **Team Management**: Robust controls to assign and invite Teaching Assistants to manage evaluations.
- **Kanban Board**: Drag-and-drop task tracking for grading assignments.
- **Student Data Upload**: Direct Google Sheet imports for syncing class rosters and exporting results.

---

## Technical Stack
- **Backend:** Python, FastAPI, SQLite
- **Frontend:** React, React Router, Recharts, TailwindCSS context (Vite)
- **Database/Auth:** Supabase, SQLite (Local Data Storage)
- **AI/LLM:** Google Vertex AI / Gemini, OpenAI 
