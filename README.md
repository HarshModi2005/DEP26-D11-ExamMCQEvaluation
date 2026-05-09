# Answer Key Evaluation DEP

A comprehensive, automated Answer Sheet Evaluation System designed to streamline the grading process for educational institutions. This system allows professors and Teaching Assistants to manage courses, process student answer sheets via OCR, evaluate them against predefined answer keys, and manage the results through a fully-featured dashboard.

---

## 🏗️ Project Architecture

This project is structured as a full-stack application divided into several modules:

- **[`/backend`](./backend)**: A Python-based FastAPI backend that handles OCR processing, evaluation logic, and dataset management (SQLite).
- **[`/frontend-new-design`](./frontend-new-design)**: A modern React-based frontend built with Vite and Node.js that provides the user interface for Faculty members, TAs, and Admin users.
- **[`/c_code_evaluator`](./c_code_evaluator)**: A dedicated Python module that utilizes OCR to extract handwritten C code from images, compiles it, and evaluates it against automated test cases.
- **[`/cp_problems`](./cp_problems)**: Sample test cases and mock data representing algorithmic problems used by the C code evaluator to validate grading accuracy.

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
2. Create and activate a virtual environment (recommended):
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

### 2. Running the Frontend

The frontend is a React application built with Vite and TailwindCSS.

1. Open a new terminal window and navigate to the frontend directory:
   ```bash
   cd frontend-new-design
   ```
2. Install node dependencies:
   ```bash
   npm install
   ```
3. Set up environment variables:
   Copy `.env.example` to `.env.local` if necessary (e.g., Supabase keys).
4. Start the frontend development server:
   ```bash
   npm start
   ```

*The frontend application will start up, usually available on `http://localhost:5173`.*

For more details, see the [Frontend README](./frontend-new-design/README.md).

---

## 🛠 Features

### Core Evaluation Engine
- **OCR Pipelines**: Configurable LLM-driven OCR services (Vertex AI/Gemini, OpenAI) to extract text accurately from scanned documents.
- **C Code Execution**: End-to-end evaluation of handwritten C code snippets via containerized or sandboxed compilation.
- **Evaluation Logic**: Compare extracted text against defined answer keys with customizable, AI-driven scoring algorithms.

### Dashboard & UI
- **Faculty Dashboard**: An intuitive overview for creating courses, tracking evaluations, and managing pending grading tasks.
- **Kanban Board**: Drag-and-drop task tracking for grading assignments and workflow states.
- **Team Management**: Robust controls to assign and invite Teaching Assistants to manage evaluations.
- **Student Data Integration**: Direct Google Sheet and Excel imports for syncing class rosters and exporting graded results.

---

## 💻 Technical Stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** React 18, React Router v6, Redux Toolkit, Recharts, TailwindCSS (Vite)
- **Database & Auth:** Supabase, SQLite (Local Data Storage)
- **AI/LLM OCR:** Google Vertex AI / Gemini, OpenAI 

---

## 📝 License & Contributions

Please refer to the internal contribution guidelines and maintain clean commits while expanding features on this repository.
